"""Portal Flask app — unified shell + reverse proxy for all sub-apps (Demo only)."""
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, render_template
import process_manager
import proxy

# ── Pure Demo version ──
_PORT = 5000
_SUPERVISOR_MODE = os.environ.get("SUPERVISOR_MODE", "").strip() == "1"

app = Flask(__name__)

_PORT_MAP = {a["id"]: a["port"] for a in process_manager.APPS}

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
                           local_version=_local_version(), is_release=False)


@app.route("/api/status")
def api_status():
    return jsonify(process_manager.get_apps_status())


@app.route("/api/health")
def api_health():
    """Docker / load-balancer health check."""
    return jsonify({"ok": True, "mode": "supervisor" if _SUPERVISOR_MODE else "direct"})


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
    # Clean stale .pyc bytecode before importing anything important.
    import shutil
    for pyc_dir in _PROJECT_ROOT.rglob("__pycache__"):
        try:
            shutil.rmtree(pyc_dir, ignore_errors=True)
        except Exception:
            pass

    process_manager.start_all()
    if os.environ.get("BROWSER") not in ("echo", "", "none"):
        threading.Timer(2.5, lambda: webbrowser.open(f"http://localhost:{_PORT}")).start()
    try:
        app.run(host="0.0.0.0", port=_PORT, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        process_manager.shutdown_all()


if __name__ == "__main__":
    main()
