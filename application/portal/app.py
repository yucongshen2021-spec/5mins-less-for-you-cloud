#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Portal — 统一入口 + 反向代理 + 登录鉴权。

Requests flow:
  GET  /login     → 登录页（未登录）
  POST /login     → 验证登录（JSON API）
  POST /register  → 注册（JSON API）
  GET  /logout    → 退出
  GET  /          → 首页（需登录，302 到 /login）
  /app/*          → proxy 到子应用（需登录，转发时注入 X-User-Id）
  /api/health     → 免登录
"""

import json
import os
import shutil
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    session,
)

# ── App config ───────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder=str(Path(__file__).resolve().parent / "templates"))

_PORT = int(os.environ.get("PORT", "5000"))
_SUPERVISOR_MODE = os.environ.get("SUPERVISOR_MODE", "") == "1"
_PORTAL_LABEL = os.environ.get("PORTAL_LABEL", "Demo")

# 会话密钥：优先环境变量 → 从磁盘持久化随机密钥 → 生成新的并持久化
_secret_file = Path(__file__).resolve().parent / "logs" / ".secret_key"
_secret = os.environ.get("SECRET_KEY", "")
if _secret:
    app.secret_key = _secret
else:
    try:
        app.secret_key = _secret_file.read_text().strip()
    except Exception:
        app.secret_key = uuid.uuid4().hex
        _secret_file.parent.mkdir(parents=True, exist_ok=True)
        _secret_file.write_text(app.secret_key)

app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=24)

# ── Auth DB ──────────────────────────────────────────────────────────────────
_APP_DIR = Path(__file__).resolve().parent.parent  # .../application

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

def _local_version():
    try:
        info = json.loads((_PROJECT_ROOT / "RELEASE_INFO.json").read_text(encoding="utf-8-sig"))
        v = info.get("version")
        return v if isinstance(v, str) and v.strip() else None
    except (OSError, json.JSONDecodeError):
        return None
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
from common.auth_db import create_user, get_user_by_id, verify_user  # noqa: E402

# ── Process manager ──────────────────────────────────────────────────────────
from process_manager import APPS, get_apps_status, start_all  # noqa: E402

# ── Proxy ────────────────────────────────────────────────────────────────────
from proxy import proxy_to  # noqa: E402

_AUTH_WHITELIST = {"/login", "/register", "/api/health"}
_AUTH_WHITELIST_PREFIXES = ("/static/",)


# ── Auth middleware ──────────────────────────────────────────────────────────
@app.before_request
def _check_auth():
    """未登录自动给访客 session（默认 workspace），白名单完全跳过。"""
    path = request.path.rstrip("/")
    if path in _AUTH_WHITELIST:
        return None
    for prefix in _AUTH_WHITELIST_PREFIXES:
        if request.path.startswith(prefix):
            return None
    user_id = session.get("user_id")
    if user_id is None:
        # 无 session → 自动创建访客（无需注册，用默认共享 workspace）
        session["user_id"] = ""
        session["username"] = "访客"
        session.permanent = True
    # 刷新 24h
    session.permanent = True


# ── Login / Register / Logout ────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect("/")
        return render_template("login.html")

    data = request.get_json(force=True, silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = data.get("password", "")
    if not username or not password:
        return jsonify({"ok": False, "error": "请输入用户名和密码"})
    result = verify_user(username, password)
    if result.get("ok"):
        session["user_id"] = result["user_id"]
        session["username"] = result["username"]
        session.permanent = True
        return jsonify({"ok": True, "redirect": "/"})
    return jsonify({"ok": False, "error": result.get("error", "用户名或密码错误")})


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect("/")
        return render_template("login.html")

    data = request.get_json(force=True, silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = data.get("password", "")
    result = create_user(username, password)
    status = 200 if result.get("ok") else 409
    return jsonify(result), status


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ── Portal pages ─────────────────────────────────────────────────────────────
@app.route("/")
def index():
    user_id = session.get("user_id", "")
    username = session.get("username", "") if user_id else ""
    apps_status = get_apps_status()
    online = sum(1 for a in apps_status if a.get("reachable"))
    total = len(apps_status)
    return render_template("index.html",
        apps=apps_status, current_user=username,
        local_version=_local_version(), portal_label=_PORTAL_LABEL,
        online_count=online, total_count=total)


@app.route("/api/status")
def api_status():
    return jsonify(get_apps_status())


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "status": "healthy"})


# ── Proxy to sub-apps ────────────────────────────────────────────────────────
_PORT_MAP = {a["id"]: a["port"] for a in APPS}

@app.route("/app/<app_id>/", defaults={"subpath": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
@app.route("/app/<app_id>/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def app_proxy(app_id: str, subpath: str):
    return proxy_to(app_id, subpath, _PORT_MAP)


# ── Entrypoint ───────────────────────────────────────────────────────────────
def main():
    """Start all micro-apps and run Portal."""
    # 启动前清理 __pycache__（避免残留生效）
    try:
        shutil.rmtree(
            Path(__file__).resolve().parent / ".." / ".generated_web",
            ignore_errors=True,
        )
    except Exception:
        pass

    start_all()
    app.run(host="0.0.0.0", port=_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
