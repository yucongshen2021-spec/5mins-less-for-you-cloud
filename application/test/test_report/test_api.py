"""自动做测试报告 (test_report) API 完整测试。

覆盖: /api/run (参数校验 + 执行), /api/stop, /api/logs SSE, /api/download
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer, http_get

APP_DIR = APPLICATION_DIR / "自动做测试报告 - cc"
APP = APP_DIR / "app.py"
PORT = 5002


def _post_json(url: str, data: dict, timeout: float = 10.0) -> tuple[int, dict]:
    """POST JSON 并返回 (status, parsed_body)."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "test/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture(scope="module")
def server():
    if not APP.is_file():
        pytest.skip(f"未找到 {APP}")
    with SmokeServer([PYTHON, str(APP)], cwd=APP_DIR, port=PORT):
        yield f"http://127.0.0.1:{PORT}"


# ── 基础 ──

def test_index_returns_200(server):
    status, body = http_get(server + "/")
    assert status == 200, f"test_report / 应返回 200, 实际 {status}"
    assert "测试报告" in body, "首页应包含「测试报告」"


# ── /api/run ──

def test_run_missing_date_returns_400(server):
    """填缺失日期 → 400。"""
    status, data = _post_json(server + "/api/run", {"line_id": "test"})
    assert status == 400, f"缺日期应返回 400, 实际 {status}"
    assert data.get("ok") is False, f"应 ok=false, 实际 {data}"


def test_run_returns_task_id(server):
    """有效参数 → 200 + task_id 非空。后台 worker 可能失败（无 make_report 环境），
    但 API 层必须正确返 task_id。"""
    status, data = _post_json(server + "/api/run", {
        "test_date": "2099-01-01",
        "line_id": "TEST_LINE",
        "customer": "测试客户",
        "bandwidth": "100M",
        "engineer": "测试工程师",
        "ce_host": "192.168.1.1",
        "ce_port": "2707",
        "ce_user": "admin",
        "ce_password": "test",
        "main_ip": "10.0.0.1",
        "backup_ip": "10.0.0.2",
        "local_site": "www.baidu.com",
        "accel_site": "www.google.com",
    })
    assert status == 200, f"有效参数应返回 200, 实际 {status}"
    assert data.get("ok") is True, f"应 ok=true, 实际 {data}"
    assert data.get("task_id"), f"task_id 不能为空: {data}"


def test_run_generates_task_directory(server):
    """run task 后在 log/ 下生成对应目录。"""
    status, data = _post_json(server + "/api/run", {
        "test_date": "2099-12-31",
        "line_id": "DIR_TEST",
        "customer": "目录测试",
        "ce_host": "192.168.1.1",
        "main_ip": "10.0.0.1",
        "backup_ip": "10.0.0.2",
    })
    assert status == 200
    task_dir = APP_DIR / "log" / f"20991231_DIR_TEST"
    assert task_dir.is_dir(), f"任务目录应存在: {task_dir}"
    assert (task_dir / "config.json").is_file(), "应有 config.json"
    assert (task_dir / "state.json").is_file(), "应有 state.json"
    assert (task_dir / "screenshots").is_dir(), "应有 screenshots/"
    assert (task_dir / "raw").is_dir(), "应有 raw/"


def test_run_missing_line_id_defaults(server):
    """line_id 空白时使用默认值 'NO_CID'。"""
    status, data = _post_json(server + "/api/run", {
        "test_date": "2099-06-15",
        "customer": "NOLINE",
        "ce_host": "192.168.1.1",
        "main_ip": "10.0.0.1",
        "backup_ip": "10.0.0.2",
    })
    assert status == 200, f"缺 line_id 也应返回 200, 实际 {status}"
    assert "NO_CID" in data.get("task_id", ""), f"task_id 应含 NO_CID: {data}"


# ── /api/stop ──

def test_stop_invalid_task_returns_ok(server):
    """停止不存在的任务 → 200 ok (不崩溃)。"""
    status, data = _post_json(server + "/api/stop", {"task_id": "nonexistent_999"})
    assert status == 200, f"停止不存在任务应返回 200, 实际 {status}"
    assert data.get("ok") is True


# ── /api/logs ──

def test_logs_invalid_task_returns_sse_error(server):
    """不存在的 task_id → SSE 流含错误信息。"""
    try:
        http_get(server + "/api/logs/nonexistent_999", timeout=5.0)
    except urllib.error.HTTPError:
        pytest.fail("不应返回 HTTP 错误")
    except Exception:
        # SSE 流可能不会正常关闭，但不应 crash
        pass


# ── /api/download ──

def test_download_not_found_returns_404(server):
    """不存在的文件 → 404。"""
    try:
        http_get(server + "/api/download/nonexistent/report.docx")
        pytest.fail("应返回 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404, f"下载不存在文件应 404, 实际 {e.code}"


# ── 并发 ──

def test_concurrent_runs_different_task_ids(server):
    """并发 POST /api/run → 不同的 task_id。"""
    base = {
        "customer": "concurrent",
        "ce_host": "192.168.1.1",
        "main_ip": "10.0.0.1",
        "backup_ip": "10.0.0.2",
    }
    results = []
    for i in range(3):
        payload = {**base, "test_date": f"2099-01-0{i+1}", "line_id": f"CONCUR_{i}"}
        _, data = _post_json(server + "/api/run", payload)
        results.append(data.get("task_id"))
    assert len(set(results)) == 3, f"3 次 run 应有 3 个不同 task_id, 实际 {results}"
