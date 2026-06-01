import json
import os
import queue
import re
import subprocess
import sys
import threading
from datetime import date, datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")

CURRENT_DIR = Path(__file__).resolve().parent
ROOT = CURRENT_DIR
SCRIPT = ROOT / "src" / "make_report.py"
ENGINE_EXE = ROOT / "src" / "make_report.exe"

CE_PRESETS = {
    "bothwin_tfe": ("bothwin/Tfe", "bothwin", "Tfe28@w%"),
    "admin_tfe": ("admin/Tfe", "admin", "Tfe28@w%"),
    "bothwin_dotx12": ("bothwin/.x12", "bothwin", ".x12Tfe192Ti.2024"),
}

log_streams: dict[str, queue.Queue] = {}
proc_registry: dict[str, subprocess.Popen] = {}
stop_flags: dict[str, bool] = {}


def sanitize(value: str, default: str) -> str:
    v = re.sub(r"[^A-Za-z0-9_-]", "_", value.strip())
    return v or default


@app.route("/")
def index():
    return render_template("index.html", today=date.today().isoformat())


@app.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json(force=True)

    date_value = data.get("test_date", "").strip()
    date_key = re.sub(r"[^0-9]", "", date_value)
    if not date_key:
        return jsonify({"ok": False, "error": "测试日期不能为空"}), 400

    line_id = data.get("line_id", "").strip()
    run_dir = ROOT / "log" / f"{date_key}_{sanitize(line_id, 'NO_CID')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "screenshots").mkdir(exist_ok=True)
    (run_dir / "raw").mkdir(exist_ok=True)

    cfg = {
        "customer": data.get("customer", "").strip(),
        "line_id": line_id,
        "bandwidth": data.get("bandwidth", "").strip(),
        "engineer": data.get("engineer", "").strip(),
        "test_date": date_value,
        "ce_host": data.get("ce_host", "").strip(),
        "ce_port": int(data.get("ce_port", "2707").strip() or "2707"),
        "ce_user": data.get("ce_user", "").strip(),
        "main_ip": data.get("main_ip", "").strip(),
        "backup_ip": data.get("backup_ip", "").strip(),
        "local_site": data.get("local_site", "").strip() or "www.baidu.com",
        "accel_site": data.get("accel_site", "").strip() or "www.google.com",
        "product_type": data.get("product_type", "er").strip().lower(),
        "ce_ping_interval_i": data.get("ce_ping_interval_i", "0.01").strip(),
        "ce_ping_interval_m": data.get("ce_ping_interval_m", "1").strip(),
    }
    (run_dir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "state.json").write_text("{}", encoding="utf-8")

    ce_pwd = data.get("ce_password", "")
    if ENGINE_EXE.is_file():
        cmd = [str(ENGINE_EXE), "--resume", str(run_dir), "--ce-password", ce_pwd, "--no-manual-pause"]
    else:
        cmd = [sys.executable, str(SCRIPT), "--resume", str(run_dir), "--ce-password", ce_pwd, "--no-manual-pause"]

    task_id = f"{date_key}_{sanitize(line_id, 'NO_CID')}"

    q: queue.Queue[str] = queue.Queue()
    log_streams[task_id] = q
    stop_flags[task_id] = False
    q.put(f">>> {' '.join(str(x) for x in cmd[:-2])} --no-manual-pause\n")

    t = threading.Thread(target=_run_worker, args=(task_id, cmd, run_dir, cfg), daemon=True)
    t.start()

    return jsonify({"ok": True, "task_id": task_id})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    data = request.get_json(force=True)
    task_id = data.get("task_id", "")
    if task_id in stop_flags:
        stop_flags[task_id] = True
    proc = proc_registry.get(task_id)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        except Exception:
            pass
        proc_registry.pop(task_id, None)
        if task_id in log_streams:
            log_streams[task_id].put("[WARN] 任务已被中断\n")
    return jsonify({"ok": True})


@app.route("/api/logs/<task_id>")
def api_logs(task_id):
    q = log_streams.get(task_id)

    def generate():
        if q is None:
            yield "data: [ERROR] 任务不存在\n\n"
            return
        while True:
            try:
                line = q.get(timeout=30)
                yield f"data: {line}\n\n"
                if line.startswith("__DONE") or line.startswith("[OK] 报告已生成") or line.startswith("[ERROR]") or line.startswith("[WARN] 任务已被中断"):
                    break
            except queue.Empty:
                yield f"data: [WARN] 等待超时\n\n"
                break

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/download/<path:filename>")
def api_download(filename):
    filepath = ROOT / "log" / filename
    if filepath.is_file():
        return send_file(filepath, as_attachment=True)
    return jsonify({"ok": False, "error": "文件不存在"}), 404


def _run_worker(task_id: str, cmd: list[str], run_dir: Path, cfg: dict) -> None:
    q = log_streams.get(task_id)
    if q is None:
        return
    try:
        creationflags = 0
        if sys.platform.startswith("win"):
            creationflags = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        proc_registry[task_id] = proc
        assert proc.stdout is not None
        for line_b in iter(proc.stdout.readline, b""):
            if stop_flags.get(task_id):
                proc.kill()
                break
            line = line_b.decode("utf-8", errors="replace")
            q.put(line.rstrip("\r\n"))
        code = proc.wait()
        proc_registry.pop(task_id, None)

        if stop_flags.get(task_id):
            q.put("[WARN] 任务已被中断\n")
            return

        if code != 0:
            q.put(f"[ERROR] 执行失败，退出码 {code}\n")
            return

        report = run_dir / f"FASTIP-测试报告_{cfg['customer'] or '未命名'}_{cfg['test_date']}.docx"
        rel_path = report.relative_to(ROOT / "log")
        q.put(f"[OK] 报告已生成\n")
        q.put(f"__DOWNLOAD__ {rel_path}\n")
    except Exception as exc:
        q.put(f"[ERROR] {exc}\n")
    finally:
        q.put("__DONE__\n")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
