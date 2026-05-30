"""Portal Flask app — unified shell + reverse proxy for all sub-apps on port 5000."""
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
import update_check

app = Flask(__name__)

# Build port map from process_manager APPS
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


@app.route("/")
def index():
    apps = process_manager.get_apps_status()
    online_count = sum(1 for a in apps if a["reachable"])
    return render_template("index.html", apps=apps, online_count=online_count, total_count=len(apps))


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
    """检查远端是否有更新版本。

    ?force=1 跳过缓存（前端"重试"按钮用）。其余情况按 update_config.json 内
    cache_ttl_seconds 的值复用上次检查结果，避免每次首页刷新都打外网。
    """
    force = request.args.get("force") in ("1", "true", "yes")
    return jsonify(update_check.check(force=force))


@app.route("/api/update/manifest")
def api_update_manifest():
    """对外提供更新源 manifest（让本机 portal 充当其它客户端的 mirror）。

    其它机器上的 portal 把 update_config.json 的 mirror_url 指向这个端点，
    就能拿到「本机 dist/ 里最新一份合法 zip」的版本号 + 下载地址，
    用户点"查看并下载"会直接命中本机 portal 的 /download/latest.zip。

    - 没有合法 zip 时返回 HTTP 404 + 明确错误（绝不返回 200 + 空 manifest，
      避免客户端误把空数据当成"已是最新"）。
    - download_url / release_url 用 request.host_url 动态生成，
      跟随客户端发起请求时使用的 IP 或域名，避免硬编码失配。
    """
    info = _find_latest_release()
    if info is None:
        return jsonify({
            "error": "no_release_available",
            "message": "本机 dist/ 内没有合法 zip 包",
        }), 404

    base = request.host_url.rstrip("/")
    return jsonify({
        "version": info["version"],
        "release_url": f"{base}/",
        "download_url": f"{base}/download/latest.zip",
        "filename": info["filename"],
        "size_bytes": info["size"],
        "built_at": info.get("built_at"),
    })


@app.route("/download/latest.zip")
def download_latest_zip():
    """下发最新可分发包；本地无包时 404。"""
    info = _find_latest_release()
    if info is None:
        abort(404, description="本地暂无可分发包，请先在项目根运行 python tools/build_release.py")
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
    if app_id == "config_analyzer":
        # Config analyzer is http.server on port 5742; default page:
        if not subpath:
            from flask import redirect
            return redirect(f"/app/{app_id}/er_config_analyzer.html")
    return proxy.proxy_to(app_id, subpath, _PORT_MAP)


def main():
    process_manager.start_all()
    threading.Timer(2.5, lambda: webbrowser.open("http://localhost:5000")).start()
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        process_manager.shutdown_all()


if __name__ == "__main__":
    main()
