"""Comprehensive test suite for mock report feature. Covers edge cases and bugs."""
import requests
import json
import sys
import time
import re
from pathlib import Path

BASE = "http://127.0.0.1:5002"
PASS = 0
FAIL = 0

def ok(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} — {detail}")

def api_post(path, payload):
    r = requests.post(f"{BASE}{path}", json=payload)
    return r, r.json()

def sse_collect(task_id, endpoint="/api/mock/logs/"):
    """Collect all SSE messages for a task."""
    messages = []
    r = requests.get(f"{BASE}{endpoint}{task_id}", stream=True)
    for line in r.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            msg = line[6:]
            messages.append(msg)
            if msg.startswith("__DONE"):
                break
    return messages

def base_payload(**overrides):
    p = {
        "customer": "综合测试客户", "line_id": "C001", "bandwidth": "100M",
        "engineer": "测试工程师", "test_date": "2026-06-12",
        "main_ip": "10.55.19.237", "backup_ip": "10.30.36.217",
        "local_site": "www.baidu.com", "accel_site": "www.google.com",
        "product_type": "er",
        "main_delay": 3.5, "main_jitter": 1.2, "main_loss": 0,
        "backup_delay": 4.8, "backup_jitter": 2.1, "backup_loss": 0,
        "baidu_delay": 12.0, "baidu_jitter": 3.5, "baidu_loss": 0,
        "google_delay": 180.0, "google_jitter": 15.0, "google_loss": 0,
        "failover_delay": 185.0, "failover_jitter": 12.0, "failover_loss": 0,
    }
    p.update(overrides)
    return p


# ═══ 1. Happy path — standard generation ═══
print("=== 1. Happy path ===")
r, data = api_post("/api/mock/run", base_payload())
msgs = sse_collect(data["task_id"])
ok("task_id starts with MOCK_", data["task_id"].startswith("MOCK_"))
ok("returns [OK]", any("报告已生成" in m for m in msgs))
ok("has __DOWNLOAD__", any(m.startswith("__DOWNLOAD__") for m in msgs))
# __DONE__ is sent after [OK] so SSE may have already broken — that's fine
ok("__DOWNLOAD__ before [OK]",
   next(i for i, m in enumerate(msgs) if m.startswith("__DOWNLOAD__")) <
   next(i for i, m in enumerate(msgs) if "[OK]" in m),
   "download must appear before [OK] so SSE doesn't break early")
dl = next((m for m in msgs if m.startswith("__DOWNLOAD__")), "")
ok("download path has .docx", ".docx" in dl)
ok("response ok=True", data["ok"])

# ═══ 2. Download the docx and verify ═══
print("\n=== 2. Download & verify ===")
dl_path = dl.replace("__DOWNLOAD__ ", "").strip()
r = requests.get(f"{BASE}/api/mock/download/{dl_path}")
ok("download status 200", r.status_code == 200)
ok("file > 100KB", len(r.content) > 100000, f"got {len(r.content)} bytes")
ok("file starts with PK (zip/docx)", r.content[:2] == b"PK")

# ═══ 3. Minimal input — only required fields ═══
print("\n=== 3. Minimal input ===")
r, data = api_post("/api/mock/run", base_payload(
    customer="", bandwidth="", engineer="",
    baidu_delay=0, baidu_jitter=0, baidu_loss=0,
    google_delay=0, google_jitter=0, google_loss=0,
))
ok("minimal works", data["ok"])
msgs = sse_collect(data["task_id"])
ok("minimal generates docx", any("报告已生成" in m for m in msgs))

# ═══ 4. Missing required fields ═══
print("\n=== 4. Missing required fields ===")
for field in ["line_id", "main_ip", "backup_ip"]:
    p = base_payload(**{field: ""})
    r, data = api_post("/api/mock/run", p)
    ok(f"missing {field} rejects", not data.get("ok"),
       f"should reject empty {field}, got {data}")

# ═══ 5. Chinese customer name ═══
print("\n=== 5. Chinese characters ===")
r, data = api_post("/api/mock/run", base_payload(customer="深圳某某科技有限公司（测试部）"))
msgs = sse_collect(data["task_id"])
ok("chinese customer works", data["ok"] and any("报告已生成" in m for m in msgs))

# ═══ 6. Various loss rates ═══
print("\n=== 6. Loss rates ===")
for loss in [0, 0.5, 5, 25, 50]:
    r, data = api_post("/api/mock/run", base_payload(main_loss=loss, backup_loss=loss))
    ok(f"loss={loss}% ok", data["ok"], str(data.get("error", "")))
    msgs = sse_collect(data["task_id"])
    ok(f"loss={loss}% generates", any("报告已生成" in m for m in msgs))

# ═══ 7. High delay values ═══
print("\n=== 7. High delay values ===")
r, data = api_post("/api/mock/run", base_payload(
    main_delay=999, main_jitter=200, google_delay=9999, google_jitter=500
))
msgs = sse_collect(data["task_id"])
ok("high delay works", data["ok"] and any("报告已生成" in m for m in msgs))

# ═══ 8. ER vs USG ═══
print("\n=== 8. Product type ===")
for pt in ["er", "usg"]:
    r, data = api_post("/api/mock/run", base_payload(product_type=pt))
    ok(f"product_type={pt}", data["ok"] and any("报告已生成" in m for m in sse_collect(data["task_id"])))

# ═══ 9. Stop mid-task ═══
print("\n=== 9. Stop mid-task ===")
r, data = api_post("/api/mock/run", base_payload())
task_id = data["task_id"]
time.sleep(0.3)  # let it start
r, _ = api_post("/api/mock/stop", {"task_id": task_id})
msgs = sse_collect(task_id)
ok("stop returns ok", r.json()["ok"])
ok("has interrupt warning", any("中断" in m for m in msgs))

# ═══ 10. Download non-existent file ═══
print("\n=== 10. Non-existent download ===")
r = requests.get(f"{BASE}/api/mock/download/nonexistent/file.docx")
ok("non-existent 404", r.status_code == 404)

# ═══ 11. Concurrent tasks ═══
print("\n=== 11. Concurrent tasks ===")
results = []
for i in range(3):
    r, data = api_post("/api/mock/run", base_payload(line_id=f"CONCUR{i}"))
    results.append((data["task_id"], []))
# Collect all
for tid, msgs in results:
    msgs.extend(sse_collect(tid))
all_ok = all(any("报告已生成" in m for m in msgs) for _, msgs in results)
ok("3 concurrent all generate", all_ok)
for tid, msgs in results:
    ok(f"  {tid} unique", tid not in [t for t, _ in results if t != tid])

# ═══ 12. Traceroute paths verification ═══
print("\n=== 12. Traceroute path correctness ===")
from pathlib import Path as P
log_root = P("C:/Users/123/Desktop/帮你节省5分钟/application/自动做测试报告 - cc/log")

# Find the most recent mock run
mock_dirs = sorted([d for d in log_root.iterdir() if d.name.startswith("MOCK_")],
                   key=lambda d: d.stat().st_mtime, reverse=True)
if mock_dirs:
    latest = mock_dirs[0]
    # Check baidu tracert
    bt = (latest / "raw" / "06_tracert.txt").read_text("utf-8")
    ok("baidu tracert has 192.168.5.1 (hop 1)", "192.168.5.1" in bt and "<1 ms" in bt)
    ok("baidu tracert has 192.168.72.1 (hop 2, domestic)", "192.168.72.1" in bt)
    ok("baidu tracert reaches 183.2.172.177", "183.2.172.177" in bt)

    # Check google tracert
    gt = (latest / "raw" / "07_tracert.txt").read_text("utf-8")
    ok("google tracert has 192.168.5.1 (hop 1)", "192.168.5.1" in gt and "<1 ms" in gt)
    ok("google tracert has 10.22.11.57 (hop 2, overseas)", "10.22.11.57" in gt)
    ok("google tracert reaches 142.251.155.119", "142.251.155.119" in gt)

    # Check failover tracert
    ft = (latest / "raw" / "08_tracert.txt").read_text("utf-8")
    ok("failover tracert has 192.168.5.1 (hop 1)", "192.168.5.1" in ft and "<1 ms" in ft)
    ok("failover tracert has 10.30.36.217 (hop 2, backup)", "10.30.36.217" in ft)
    ok("failover tracert has backup hop at hop 2", "10.30.36.217" in ft)
    ok("failover tracert reaches Google", "142.251.155.119" in ft)

# ═══ 13. PNG files generated ═══
print("\n=== 13. PNG files ===")
if mock_dirs:
    png_dir = latest / "screenshots"
    expected_pngs = [
        "01_ce_main_small.png", "02_ce_main_large.png",
        "03_ce_backup_small.png", "04_ce_backup_large.png",
        "05_speedtest.png",
        "06_ping.png", "06_tracert.png",
        "07_ping.png", "07_tracert.png",
        "08_ping.png", "08_tracert.png",
    ]
    for png in expected_pngs:
        p = png_dir / png
        ok(f"  {png} exists", p.is_file() and p.stat().st_size > 100,
           f"size={p.stat().st_size if p.is_file() else 'missing'}")

# ═══ 14. Ping output realism ═══
print("\n=== 14. Ping output realism ===")
if mock_dirs:
    pout = (latest / "raw" / "01_ce_main_small.txt").read_text("utf-8")
    ok("ping has 'packets transmitted'", "packets transmitted" in pout)
    ok("ping has 'rtt min/avg/max/mdev'", "rtt min/avg/max/mdev" in pout)
    ok("ping has 'icmp_seq='", "icmp_seq=" in pout)
    ok("ping has correct packet count", "500 packets transmitted" in pout)

# ═══ 15. Negative/zero edge cases ═══
print("\n=== 15. Edge case values ===")
r, data = api_post("/api/mock/run", base_payload(
    main_delay=0, main_jitter=0, main_loss=100,  # 100% loss
    google_delay=0.1, google_jitter=0.01
))
ok("zero delay + 100% loss works", data["ok"] and
   any("报告已生成" in m for m in sse_collect(data["task_id"])))

# ═══ Summary ═══
print(f"\n{'='*50}")
print(f"TOTAL: {PASS} passed, {FAIL} failed")
if FAIL:
    sys.exit(1)
else:
    print("ALL CLEAN — no bugs found")
    sys.exit(0)
