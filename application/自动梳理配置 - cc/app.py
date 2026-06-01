"""Config Analyzer — serve er_config_analyzer.html via Flask."""
import os
import sys
import threading
import webbrowser

from flask import Flask, send_from_directory

_HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)


@app.route("/")
def index():
    return send_from_directory(_HERE, "er_config_analyzer.html")


@app.route("/<path:filename>")
def static_file(filename):
    return send_from_directory(_HERE, filename)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5004
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
