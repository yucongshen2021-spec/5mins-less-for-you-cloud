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
                line = q.get(timeout=120)
                yield f"data: {line}\n\n"
                if line.startswith("__DONE") or line.startswith("[OK] 报告已生成") or line.startswith("[ERROR]") or line.startswith("[WARN] 任务已被中断"):
                    break
            except queue.Empty:
                yield f"data: [WARN] 日志流超时（120s 无输出）\n\n"
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
        kwargs = {
            "cwd": str(ROOT),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
        }
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(cmd, **kwargs)
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


# ══════════════════════════════════════════════════════════════════
# Mock report — 模拟测试报告（不连设备）
# ══════════════════════════════════════════════════════════════════

import random as _random
from src.make_report import (
    Config as MockConfig,
    FONT_PATH,
    SCREENSHOT_BLOCK_FIRST_ROW,
    fill_docx,
    render_terminal_png,
)

_mock_streams: dict[str, queue.Queue] = {}
_mock_stop_flags: dict[str, bool] = {}


def _gen_ping_output(target: str, count: int, size: int, delay_ms: float,
                     jitter_ms: float, loss_pct: float, seed: int = 0) -> str:
    """Generate realistic ping output with given metrics."""
    lines = [f"PING {target} ({target}) {size}({size + 8}) bytes of data."]
    sent = count
    lost = int(count * loss_pct / 100)
    received = sent - lost
    rng = _random.Random(hash(target) + count + size + seed)
    for i in range(1, min(count + 1, 21)):
        if loss_pct > 0 and i <= lost:
            continue
        t = max(0.5, delay_ms + rng.uniform(-jitter_ms, jitter_ms))
        lines.append(f"{size} bytes from {target}: icmp_seq={i} ttl=64 time={t:.1f} ms")

    lines.append("")
    rtt_min = max(0.3, delay_ms - jitter_ms)
    rtt_avg = delay_ms
    rtt_max = delay_ms + jitter_ms * 2
    rtt_mdev = jitter_ms
    total_time = count * 1000 + rng.randint(-173, 247)
    lines.append(f"--- {target} ping statistics ---")
    lines.append(f"{sent} packets transmitted, {received} received, {loss_pct:.0f}% packet loss, time {total_time}ms")
    lines.append(f"rtt min/avg/max/mdev = {rtt_min:.1f}/{rtt_avg:.1f}/{rtt_max:.1f}/{rtt_mdev:.1f} ms")
    return "\n".join(lines)


def _gen_tracert_output(target: str, via_backup: bool = False, target_ip: str = "") -> str:
    """Generate a realistic traceroute in English (Consolas-compatible).

    Real paths observed:
      Baidu (domestic): 192.168.5.1 → 192.168.72.1 → 10.10.243.27 → * → 10.10.38.170
                        → 100.64.0.1 → 14.147.79.177 → * * * → 14.29.117.170
                        → * * * * → 183.2.172.177
      Google (overseas): 192.168.5.1 → 10.22.11.57 → 4.78.197.65 → * → 4.68.68.130 → 142.251.155.119

    First hop always 192.168.5.1. Second hop diverges domestic vs overseas.
    Backup line uses backup next-hop at hop 2.
    """
    is_google = "google" in target.lower()

    if is_google:
        target_ip_addr = target_ip or "142.251.155.119"
        if via_backup:
            hops = [
                (1, "192.168.5.1", "<1 ms", "<1 ms", "<1 ms"),
                (2, "10.30.36.217", "2 ms", "1 ms", "2 ms"),
                (3, "10.22.11.57", "151 ms", "151 ms", "152 ms"),
                (4, "4.78.197.65", "152 ms", "151 ms", "*"),
                (5, "*", "*", "*", "Request timed out."),
                (6, "4.68.68.130", "152 ms", "153 ms", "157 ms"),
                (7, target_ip_addr, "152 ms", "*", "154 ms"),
            ]
        else:
            hops = [
                (1, "192.168.5.1", "<1 ms", "<1 ms", "<1 ms"),
                (2, "10.22.11.57", "151 ms", "151 ms", "*"),
                (3, "4.78.197.65", "152 ms", "151 ms", "*"),
                (4, "*", "*", "*", "Request timed out."),
                (5, "4.68.68.130", "152 ms", "153 ms", "157 ms"),
                (6, target_ip_addr, "152 ms", "*", "154 ms"),
            ]
    else:
        target_ip_addr = target_ip or "183.2.172.177"
        hops = [
            (1, "192.168.5.1", "<1 ms", "<1 ms", "<1 ms"),
            (2, "192.168.72.1", "3 ms", "2 ms", "2 ms"),
            (3, "10.10.243.27", "4 ms", "1 ms", "3 ms"),
            (4, "*", "*", "*", "Request timed out."),
            (5, "10.10.38.170", "1 ms", "<1 ms", "<1 ms"),
            (6, "100.64.0.1", "8 ms", "4 ms", "5 ms"),
            (7, "14.147.79.177", "3 ms", "4 ms", "9 ms"),
            (8, "*", "*", "*", "Request timed out."),
            (9, "*", "*", "*", "Request timed out."),
            (10, "*", "*", "*", "Request timed out."),
            (11, "14.29.117.170", "7 ms", "7 ms", "7 ms"),
            (12, "*", "*", "*", "Request timed out."),
            (13, "*", "*", "*", "Request timed out."),
            (14, "*", "*", "*", "Request timed out."),
            (15, "*", "*", "*", "Request timed out."),
            (16, target_ip_addr, "7 ms", "6 ms", "6 ms"),
        ]

    title = f"Tracing route to {target} [{target_ip_addr}]"
    lines = [title,
             "over a maximum of 30 hops:",
             ""]

    for hop_num, hop_ip, t1, t2, t3 in hops:
        if hop_ip == "*":
            lines.append(f"  {hop_num}     *        *        *     Request timed out.")
        else:
            lines.append(f"  {hop_num}    {t1}    {t2}    {t3}  {hop_ip}")

    lines.append("")
    lines.append("Trace complete.")
    return "\n".join(lines)


@app.route("/mock")
def mock_page():
    return render_template("mock.html", today=date.today().isoformat())


@app.route("/api/mock/run", methods=["POST"])
def api_mock_run():
    data = request.get_json(force=True)

    # Validate required fields
    missing = []
    for field, label in [("line_id", "CID"), ("main_ip", "主线对端IP"), ("backup_ip", "备线IP"), ("test_date", "测试日期")]:
        if not data.get(field, "").strip():
            missing.append(label)
    if missing:
        return jsonify({"ok": False, "error": f"必填字段为空: {', '.join(missing)}"}), 400

    date_value = data.get("test_date", "").strip()
    date_key = re.sub(r"[^0-9]", "", date_value)

    line_id = data.get("line_id", "").strip()
    run_dir = ROOT / "log" / f"MOCK_{date_key}_{sanitize(line_id, 'NO_CID')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "screenshots").mkdir(exist_ok=True)
    (run_dir / "raw").mkdir(exist_ok=True)

    cfg = MockConfig(
        customer=data.get("customer", "").strip(),
        line_id=line_id,
        bandwidth=data.get("bandwidth", "").strip(),
        engineer=data.get("engineer", "").strip(),
        test_date=date_value,
        ce_host="mock",
        ce_port=2707,
        ce_user="mock",
        main_ip=data.get("main_ip", "").strip(),
        backup_ip=data.get("backup_ip", "").strip(),
        local_site=data.get("local_site", "").strip() or "www.baidu.com",
        accel_site=data.get("accel_site", "").strip() or "www.google.com",
        product_type=data.get("product_type", "er").strip().lower(),
        ce_ping_interval_i="0.01",
        ce_ping_interval_m="1",
    )
    (run_dir / "config.json").write_text(
        json.dumps({"customer": cfg.customer, "line_id": cfg.line_id,
                     "bandwidth": cfg.bandwidth, "engineer": cfg.engineer,
                     "test_date": cfg.test_date,
                     "main_ip": cfg.main_ip, "backup_ip": cfg.backup_ip,
                     "local_site": cfg.local_site, "accel_site": cfg.accel_site,
                     "product_type": cfg.product_type,
                     "mock": True}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "state.json").write_text("{}", encoding="utf-8")

    # Extract mock metrics
    metrics = {
        "main": {"delay": float(data.get("main_delay", 0)), "jitter": float(data.get("main_jitter", 0)), "loss": float(data.get("main_loss", 0))},
        "backup": {"delay": float(data.get("backup_delay", 0)), "jitter": float(data.get("backup_jitter", 0)), "loss": float(data.get("backup_loss", 0))},
        "baidu": {"delay": float(data.get("baidu_delay", 0)), "jitter": float(data.get("baidu_jitter", 0)), "loss": float(data.get("baidu_loss", 0))},
        "google": {"delay": float(data.get("google_delay", 0)), "jitter": float(data.get("google_jitter", 0)), "loss": float(data.get("google_loss", 0))},
        "failover": {"delay": float(data.get("failover_delay", 0)), "jitter": float(data.get("failover_jitter", 0)), "loss": float(data.get("failover_loss", 0))},
    }

    task_id = f"MOCK_{date_key}_{sanitize(line_id, 'NO_CID')}"
    q: queue.Queue[str] = queue.Queue()
    _mock_streams[task_id] = q
    _mock_stop_flags[task_id] = False
    q.put(">>> 模拟报告生成开始\n")
    q.put(f">>> 主线: {cfg.main_ip}  备线: {cfg.backup_ip}\n")
    q.put(f">>> 本地: {cfg.local_site}  加速: {cfg.accel_site}\n")

    t = threading.Thread(target=_run_mock_worker,
                         args=(task_id, cfg, metrics, run_dir), daemon=True)
    t.start()
    return jsonify({"ok": True, "task_id": task_id})


@app.route("/api/mock/stop", methods=["POST"])
def api_mock_stop():
    data = request.get_json(force=True)
    task_id = data.get("task_id", "")
    if task_id in _mock_stop_flags:
        _mock_stop_flags[task_id] = True
    if task_id in _mock_streams:
        _mock_streams[task_id].put("[WARN] 任务已被中断\n")
    return jsonify({"ok": True})


@app.route("/api/mock/logs/<task_id>")
def api_mock_logs(task_id):
    q = _mock_streams.get(task_id)
    def generate():
        if q is None:
            yield "data: [ERROR] 任务不存在\n\n"
            return
        while True:
            try:
                line = q.get(timeout=120)
                # Strip leading/trailing newlines — embedded \n breaks SSE message framing
                line = line.strip("\n")
                yield f"data: {line}\n\n"
                if any(line.startswith(p) for p in ("__DONE", "[OK] 报告已生成", "[ERROR]", "[WARN] 任务已被中断")):
                    break
            except queue.Empty:
                yield f"data: [WARN] 日志流超时\n\n"
                break
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/mock/download/<path:filename>")
def api_mock_download(filename):
    filepath = ROOT / "log" / filename
    if filepath.is_file():
        return send_file(filepath, as_attachment=True)
    return jsonify({"ok": False, "error": "文件不存在"}), 404


def _run_mock_worker(task_id: str, cfg: MockConfig, metrics: dict, run_dir: Path) -> None:
    q = _mock_streams.get(task_id)
    if q is None:
        return
    shots = run_dir / "screenshots"
    raw = run_dir / "raw"
    template = ROOT / "script" / "FASTIP-测试报告.docx"

    if not template.is_file():
        q.put(f"[ERROR] 模板文件不存在: {template}\n")
        q.put("__DONE__\n")
        return

    try:
        # ── 01-04 CE 测试（ER 与 USG 命令/描述不同）──
        if cfg.product_type == "usg":
            # USG: 02=主线 tracert、03=备线 ping 1500、04=备线 tracert
            ce_tasks = [
                ("01_ce_main_small", "主线 ping 小包 64", cfg.main_ip, 64, "main", 1),
                ("02_ce_main_large", "主线 tracert", cfg.main_ip, None, "main", 2),
                ("03_ce_backup_small", "备线 ping 1500", cfg.backup_ip, 1500, "backup", 3),
                ("04_ce_backup_large", "备线 tracert", cfg.backup_ip, None, "backup", 4),
            ]
        else:
            ce_tasks = [
                ("01_ce_main_small", "主线 ping 小包 64", cfg.main_ip, 64, "main", 1),
                ("02_ce_main_large", "主线 ping 大包 1500", cfg.main_ip, 1500, "main", 2),
                ("03_ce_backup_small", "备线 ping 小包 64", cfg.backup_ip, 64, "backup", 3),
                ("04_ce_backup_large", "备线 ping 大包 1500", cfg.backup_ip, 1500, "backup", 4),
            ]
        for tag, desc, target, size, mkey, seed in ce_tasks:
            if _mock_stop_flags.get(task_id):
                q.put("[WARN] 任务已被中断\n"); q.put("__DONE__\n"); return
            m = metrics[mkey]
            q.put(f"\n>>> [{tag}] 模拟 {desc} — 延迟 {m['delay']}ms 抖动 {m['jitter']}ms 丢包 {m['loss']}%\n")
            if size is None:
                # tracert 项
                output = _gen_tracert_output(target)
                (raw / f"{tag}.txt").write_text(output, encoding="utf-8")
                render_terminal_png(shots / f"{tag}.png", f"[CE]$ tracert -d {target}", output, FONT_PATH, tail_lines=20)
            else:
                output = _gen_ping_output(target, 500, size, m["delay"], m["jitter"], m["loss"], seed)
                (raw / f"{tag}.txt").write_text(output, encoding="utf-8")
                render_terminal_png(shots / f"{tag}.png", f"[CE]$ ping -c 500 -s {size} {target}", output, FONT_PATH, tail_lines=20)
            q.put(f"    完成 → {tag}.png\n")

        # ── 05 bandwidth — skip ──
        q.put("\n>>> [05_speedtest] 跳过（模拟模式不包含带宽测试）\n")

        # ── 06 local baidu ──
        if _mock_stop_flags.get(task_id):
            q.put("[WARN] 任务已被中断\n"); q.put("__DONE__\n"); return
        m = metrics["baidu"]
        q.put(f"\n>>> [06] 本机 ping + tracert → {cfg.local_site}\n")
        pout = _gen_ping_output(cfg.local_site, 100, 1200, m["delay"], m["jitter"], m["loss"], 6)
        (raw / "06_ping.txt").write_text(pout, encoding="utf-8")
        render_terminal_png(shots / "06_ping.png", f"C:\\> ping -n 100 -l 1200 {cfg.local_site}", pout, FONT_PATH, tail_lines=20)
        tout = _gen_tracert_output(cfg.local_site)
        (raw / "06_tracert.txt").write_text(tout, encoding="utf-8")
        render_terminal_png(shots / "06_tracert.png", f"C:\\> tracert -w 1 -d {cfg.local_site}", tout, FONT_PATH)
        q.put("    完成 → 06_ping.png, 06_tracert.png\n")

        # ── 07 local google ──
        if _mock_stop_flags.get(task_id):
            q.put("[WARN] 任务已被中断\n"); q.put("__DONE__\n"); return
        m = metrics["google"]
        q.put(f"\n>>> [07] 本机 ping + tracert → {cfg.accel_site}\n")
        pout = _gen_ping_output(cfg.accel_site, 100, 1200, m["delay"], m["jitter"], m["loss"], 7)
        (raw / "07_ping.txt").write_text(pout, encoding="utf-8")
        render_terminal_png(shots / "07_ping.png", f"C:\\> ping -n 100 -l 1200 {cfg.accel_site}", pout, FONT_PATH, tail_lines=20)
        tout = _gen_tracert_output(cfg.accel_site)
        (raw / "07_tracert.txt").write_text(tout, encoding="utf-8")
        render_terminal_png(shots / "07_tracert.png", f"C:\\> tracert -w 1 -d {cfg.accel_site}", tout, FONT_PATH)
        q.put("    完成 → 07_ping.png, 07_tracert.png\n")

        # ── 08 failover — 备线到 Google ──
        if _mock_stop_flags.get(task_id):
            q.put("[WARN] 任务已被中断\n"); q.put("__DONE__\n"); return
        m = metrics["failover"]
        q.put(f"\n>>> [08] 主备切换模拟 — 备线到 {cfg.accel_site}\n")
        q.put(f"    模拟切换: 主线 down → 备线接管\n")
        pout = _gen_ping_output(cfg.accel_site, 100, 1200, m["delay"], m["jitter"], m["loss"], 8)
        (raw / "08_ping.txt").write_text(pout, encoding="utf-8")
        render_terminal_png(shots / "08_ping.png",
                            f"C:\\> ping -n 100 -l 1200 {cfg.accel_site}", pout, FONT_PATH, tail_lines=20)
        tout = _gen_tracert_output(cfg.accel_site, via_backup=True)
        (raw / "08_tracert.txt").write_text(tout, encoding="utf-8")
        render_terminal_png(shots / "08_tracert.png",
                            f"C:\\> tracert -w 1 -d {cfg.accel_site} [主备切换后]", tout, FONT_PATH)
        q.put("    完成 → 08_ping.png, 08_tracert.png\n")

        # ── Generate docx ──
        q.put("\n>>> 生成 Word 报告...\n")
        out_path = run_dir / f"FASTIP-测试报告_{cfg.customer or '未命名'}_{cfg.test_date}.docx"
        fill_docx(template, out_path, cfg, shots)
        rel_path = out_path.relative_to(ROOT / "log")
        q.put(f"__DOWNLOAD__ {rel_path}\n")
        q.put(f"[OK] 报告已生成\n")

    except Exception as exc:
        import traceback
        q.put(f"[ERROR] {exc}\n")
        q.put(traceback.format_exc() + "\n")
    finally:
        q.put("__DONE__\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5002
    app.run(host="0.0.0.0", port=port, debug=False)
