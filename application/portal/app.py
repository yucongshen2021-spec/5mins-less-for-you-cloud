"""Portal Flask app — unified shell + reverse proxy for all sub-apps."""
import json
import os
import sys
import threading
import webbrowser
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, abort, jsonify, render_template, request, send_file
import process_manager
import proxy

# ── Release mode ──
_RELEASE = os.environ.get("RELEASE_MODE", "").strip() == "1"
_PORT = 7000 if _RELEASE else 5000

app = Flask(__name__)

_PORT_MAP = {a["id"]: a["port"] for a in process_manager.APPS}

# ── 下载通道：扫描项目根 dist/*.zip ──────────────────────────────────────
# portal 部署位置：<project_root>/application/portal/app.py
# 所以项目根 = parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DIST_DIR = _PROJECT_ROOT / "dist"


def _find_latest_release():
    """扫描 dist/*.zip，返回最新一份合法包的元数据；不存在或非法则返回 None。

    "合法" 严格要求 zip 内含 RELEASE_INFO.json，缺失者视为不可用，
    避免根据文件名等弱信号猜测版本号。
    """
    if not _DIST_DIR.is_dir():
        return None
    zips = sorted(_DIST_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        return None
    latest = zips[0]

    meta = None
    try:
        with zipfile.ZipFile(latest) as zf:
            for name in zf.namelist():
                if name.endswith("/RELEASE_INFO.json") or name == "RELEASE_INFO.json":
                    with zf.open(name) as f:
                        meta = json.loads(f.read().decode("utf-8"))
                    break
    except (zipfile.BadZipFile, OSError, ValueError, json.JSONDecodeError):
        return None
    if meta is None:
        return None

    size = latest.stat().st_size
    return {
        "available": True,
        "filename": latest.name,
        "size": size,
        "size_mb": round(size / 1024 / 1024, 2),
        "version": meta.get("version"),
        "built_at": meta.get("built_at"),
        "mtime": int(latest.stat().st_mtime),
    }


def _local_version():
    try:
        info = json.loads((Path(__file__).resolve().parents[2] / "RELEASE_INFO.json").read_text(encoding="utf-8-sig"))
        v = info.get("version")
        return v if isinstance(v, str) and v.strip() else None
    except (OSError, json.JSONDecodeError):
        return None


@app.route("/")
def index():
    apps = process_manager.get_apps_status()
    online_count = sum(1 for a in apps if a["reachable"])
    return render_template("index.html", apps=apps, online_count=online_count, total_count=len(apps),
                           local_version=_local_version(), is_release=_RELEASE)


@app.route("/api/status")
def api_status():
    return jsonify(process_manager.get_apps_status())


@app.route("/api/download/latest")
def api_download_latest():
    """返回最新可分发包的元数据；本地无包时返回 {"available": false}。"""
    info = _find_latest_release()
    if info is None:
        return jsonify({"available": False})
    return jsonify(info)


@app.route("/api/update/check")
def api_update_check():
    """版本更新检查。强制刷新时传 ?force=1 跳过缓存。"""
    import update_check
    force = request.args.get("force", "0") == "1"
    return jsonify(update_check.check(force=force))


@app.route("/download/latest.zip")
def download_latest_zip():
    """下发最新可分发包；本地无包时 404。"""
    info = _find_latest_release()
    if info is None:
        abort(404, description="本地暂无可分发 zip，请先在项目根运行 python tools/build_release.py")
    file_path = _DIST_DIR / info["filename"]
    return send_file(
        file_path,
        as_attachment=True,
        download_name=info["filename"],
        mimetype="application/zip",
    )


# ── Reverse proxy for sub-apps ──────────────────────────────────────────
# Routes: /app/<app_id>/  and  /app/<app_id>/<path:subpath>
# Each sub-app is proxied from its localhost port so everything shares
# origin (port 5000), allowing iframe CSS injection.

@app.route("/app/<app_id>/", defaults={"subpath": ""}, methods=[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
@app.route("/app/<app_id>/<path:subpath>", methods=[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def proxy_route(app_id, subpath):
    return proxy.proxy_to(app_id, subpath, _PORT_MAP)


def main():
    process_manager.start_all()
    port = 7000 if _RELEASE else 5000
    threading.Timer(2.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    try:
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        process_manager.shutdown_all()


if __name__ == "__main__":
    main()
