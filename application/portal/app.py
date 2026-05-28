"""Portal Flask app — unified shell + reverse proxy for all sub-apps on port 5000."""
import sys
import os
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, jsonify, Response
import process_manager
import proxy

app = Flask(__name__)

# Build port map from process_manager APPS
_PORT_MAP = {a["id"]: a["port"] for a in process_manager.APPS}


@app.route("/")
def index():
    apps = process_manager.get_apps_status()
    online_count = sum(1 for a in apps if a["reachable"])
    return render_template("index.html", apps=apps, online_count=online_count, total_count=len(apps))


@app.route("/api/status")
def api_status():
    return jsonify(process_manager.get_apps_status())


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
