"""Stats dashboard — serves the access-log viewer on a configurable port (default 9000).

Usage:
    python app.py [port]
"""

import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta

from flask import Flask, Response, render_template, request, jsonify, session

# Allow import of the shared common module
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../application
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from common import stats_db
from common import auth_db

app = Flask(__name__)

# ── Session config (for admin panel) ─────────────────────────────────────────
app.secret_key = os.environ.get("STATS_SECRET_KEY", os.environ.get("SECRET_KEY", "stats-default-secret"))
_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "yucs123")

# ── DB init ──────────────────────────────────────────────────────────────────

_DB_PATH = stats_db.init_db()
print(f"[stats] DB at {_DB_PATH}")

# ── Audit log ────────────────────────────────────────────────────────────────
import logging
_audit_logger = logging.getLogger("stats.admin")
_audit_logger.setLevel(logging.INFO)
_audit_handler = logging.FileHandler(
    os.path.join(os.path.dirname(_DB_PATH), "admin_audit.log"), encoding="utf-8"
)
_audit_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
_audit_logger.addHandler(_audit_handler)


def _audit(action: str, detail: str = ""):
    """记录管理后台操作审计日志。"""
    from datetime import datetime
    _audit_logger.info(f"[{action}] {detail}")

# ── Helpers ───────────────────────────────────────────────────────────────────


def _filters_from_args() -> dict:
    """Extract filter params from request.args."""
    return {
        "ip": request.args.get("ip", "").strip() or None,
        "app_id": request.args.get("app_id", "").strip() or None,
        "function": request.args.get("function", "").strip() or None,
        "username": request.args.get("username", "").strip() or None,
        "start": request.args.get("start", "").strip() or None,
        "end": request.args.get("end", "").strip() or None,
        "q": request.args.get("q", "").strip() or None,
    }


def _page_from_args() -> int:
    try:
        p = int(request.args.get("page", "1"))
        return max(1, p)
    except (ValueError, TypeError):
        return 1


# ── Routes ───────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    """Serve the single-page stats dashboard."""
    return render_template("index.html")


@app.route("/api/records")
def api_records():
    """List access records, paginated and filterable."""
    filters = _filters_from_args()
    page = _page_from_args()
    page_size = min(int(request.args.get("per_page", "50") or "50"), 200)

    total = stats_db.count_records(_DB_PATH, filters)
    rows = stats_db.query_records(_DB_PATH, filters, page=page, page_size=page_size)

    return jsonify({
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
        "rows": rows,
    })


@app.route("/api/records/<int:record_id>")
def api_record_detail(record_id):
    """Return full detail of a single record (incl. full data_header & response_body)."""
    row = stats_db.get_record(_DB_PATH, record_id)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.route("/api/summary")
def api_summary():
    """Return aggregated summary for the dashboard."""
    return jsonify(stats_db.query_summary(_DB_PATH))


@app.route("/api/export.csv")
def api_export_csv():
    """Export filtered records as CSV."""
    filters = _filters_from_args()

    def generate():
        for chunk in stats_db.iter_records_csv(_DB_PATH, filters):
            yield chunk

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        generate(),
        mimetype="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="access_log_{ts}.csv"',
        },
    )


# ── Admin panel ──────────────────────────────────────────────────────────────

def _admin_logged_in() -> bool:
    return session.get("admin") is True


@app.route("/admin")
def admin_page():
    """管理后台页面。未登录显示登录表单，已登录显示用户管理。"""
    return render_template("admin.html", logged_in=_admin_logged_in())


@app.route("/admin/login", methods=["POST"])
def admin_login():
    """管理后台登录：验证密码。"""
    data = request.get_json(force=True, silent=True) or {}
    password = data.get("password", "")
    if password == _ADMIN_PASSWORD:
        session["admin"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "密码错误"}), 401


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/admin/api/users")
def admin_list_users():
    """列出所有用户。"""
    if not _admin_logged_in():
        return jsonify({"ok": False, "error": "未登录"}), 401
    users = auth_db.list_all_users()
    return jsonify({"ok": True, "users": users})


@app.route("/admin/api/users/<user_id>/delete", methods=["POST"])
def admin_delete_user(user_id):
    """删除用户（保护 yucs）。"""
    if not _admin_logged_in():
        return jsonify({"ok": False, "error": "未登录"}), 401
    result = auth_db.delete_user(user_id)
    if result.get("ok"):
        _audit("DELETE_USER", f"user_id={user_id}")
    return jsonify(result)


@app.route("/admin/api/users/<user_id>/reset-password", methods=["POST"])
def admin_reset_password(user_id):
    """管理员重置用户密码。"""
    if not _admin_logged_in():
        return jsonify({"ok": False, "error": "未登录"}), 401
    data = request.get_json(force=True, silent=True) or {}
    new_password = data.get("new_password", "")
    result = auth_db.admin_reset_user_password(user_id, new_password)
    if result.get("ok"):
        _audit("RESET_PASSWORD", f"user_id={user_id}")
    return jsonify(result)


# ── Main ─────────────────────────────────────────────────────────────────────


def main():
    port = 9000
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}, using 9000")
            port = 9000

    print(f"[stats] starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
