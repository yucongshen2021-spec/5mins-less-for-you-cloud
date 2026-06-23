"""Reverse proxy — route /app/<id>/... → http://localhost:<port>/...

Logs to the shared stats SQLite DB:
- Page visits: lightweight (IP, time, app, function — no content)
- Generate/capture actions: full detail (data-header, generated-content, etc.)

Access logs are written asynchronously via a background worker thread so the
proxy request thread never blocks on SQLite I/O (critical for multi-worker
concurrency — all portal threads share one stats DB + _write_lock).
"""

import gzip
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

from flask import request, Response, session

# ── Stats DB import (shared with the 9000-port stats app) ────────────────────
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # …/application
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from common.stats_db import (
    get_db_path,
    init_db,
    is_generate_endpoint,
    log_access as _db_log,
)

# Ensure the DB exists on first import (tables + indexes).
init_db()

# ── Hop-by-hop / filtered headers ────────────────────────────────────────────
_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
}
_HTML_MIMES = {"text/html", "application/xhtml+xml"}
_JS_MIMES = {"text/javascript", "application/javascript", "application/x-javascript"}

# Rewrite absolute paths in HTML attributes (src/href/action).
_ATTR_RE = re.compile(
    r'\b(src|href|action)="(/(?!/|app/)([^"]*))"',
    re.IGNORECASE,
)

# Rewrite absolute-path string literals in JavaScript code.
_JS_STR_RE = re.compile(
    r"""(["'])(/(?!/|app/)(?=[^"'\s;]*[a-zA-Z])([^"'\s;]{2,}))\1""",
)


# ── Async log writer (background thread + deque) ─────────────────────────────
# 请求线程只做 O(1) 的 deque.append，后台线程批量写 SQLite，避免每个请求
# 都同步等 _write_lock + connect + commit。高并发下 portal 工作线程不再被
# 日志写入阻塞。

_log_queue: deque = deque()
_log_lock = threading.Lock()
_log_flush_event = threading.Event()
_log_started = False


def _log_writer_loop():
    """Background daemon thread: drain the queue and write to SQLite in batches."""
    while True:
        # Wait for work or periodic flush
        _log_flush_event.wait(timeout=0.5)
        _log_flush_event.clear()
        # Drain everything currently queued
        with _log_lock:
            batch = list(_log_queue)
            _log_queue.clear()
        for record in batch:
            try:
                _db_log(**record)
            except Exception:
                pass  # logging must never break the proxy


def _ensure_log_writer():
    """Start the background writer thread once (idempotent, thread-safe)."""
    global _log_started
    if _log_started:
        return
    with _log_lock:
        if _log_started:
            return
        t = threading.Thread(target=_log_writer_loop, name="stats-log-writer", daemon=True)
        t.start()
        _log_started = True


_ensure_log_writer()


def _enqueue_log(record: dict) -> None:
    """Enqueue a log record for async writing. Non-blocking."""
    with _log_lock:
        _log_queue.append(record)
        if len(_log_queue) >= 50:
            _log_flush_event.set()  # batch threshold reached, flush now


# ── Helpers ──────────────────────────────────────────────────────────────────

def _rewrite_paths(text: str, app_id: str) -> str:
    """Rewrite absolute paths in HTML attributes and JS string literals."""
    def _attr(m):
        return f'{m.group(1)}="/app/{app_id}/{m.group(3)}"'
    text = _ATTR_RE.sub(_attr, text)

    def _js_str(m):
        return f'{m.group(1)}/app/{app_id}/{m.group(3)}{m.group(1)}'
    text = _JS_STR_RE.sub(_js_str, text)

    return text


def _filter_headers(headers: dict) -> dict:
    return {
        k: v for k, v in headers.items()
        if k.lower() not in _HOP_HEADERS
        and k.lower() not in ("host", "content-length", "content-encoding")
    }


def _build_proxy_request(target_url: str) -> urllib.request.Request:
    headers = _filter_headers(dict(request.headers))
    headers.pop("Host", None)
    # 删除客户端可能伪造的 X-User-Id/X-Username，再注入可信的 session 值
    headers.pop("X-User-Id", None)
    headers.pop("X-Username", None)
    uid = session.get("user_id", "")
    if uid:
        headers["X-User-Id"] = uid
        headers["X-Username"] = session.get("username", uid)
    data = request.get_data() or None
    return urllib.request.Request(target_url, data=data, headers=headers, method=request.method)


# ── Stats helpers ────────────────────────────────────────────────────────────

def _client_ip() -> str:
    """Best-effort real client IP.

    The portal is the primary entry-point, so ``request.remote_addr`` is
    usually correct.  If the portal itself sits behind a reverse proxy we
    also check ``X-Forwarded-For`` / ``X-Real-IP``.
    """
    xff = request.headers.get("X-Forwarded-For", "").strip()
    if xff:
        return xff.split(",")[0].strip() or request.remote_addr
    xri = request.headers.get("X-Real-IP", "").strip()
    if xri:
        return xri
    return request.remote_addr or "unknown"


def _now_iso() -> str:
    """Beijing time (UTC+8) ISO timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 8 * 3600))


def _try_log(app_id: str, subpath: str, start_s: float,
             resp_status: int, resp_body: bytes,
             error: str = None, is_generate: bool = False) -> None:
    """Enqueue one access record for async writing. Never raises.

    Must capture all request-context data HERE (in the request thread) because
    the background writer thread has no Flask request context. For generate
    actions (is_generate=True) we capture the full request/response body so the
    stats page can show data-header + generated-content. For ordinary page
    visits we only log metadata (IP, time, function).
    """
    try:
        # 只记录生成配置的请求，其他按钮点击/页面访问不记录
        if not is_generate:
            return
        # 测试机器人（ctest 开头）不记录访问日志
        _username = session.get("username", "") or ""
        if _username.startswith("ctest"):
            return
        req_body = request.get_data() or b""
        record = {
            "ts": _now_iso(),
            "ip": _client_ip(),
            "app_id": app_id,
            "method": request.method,
            "path": request.path,
            "query": request.query_string.decode("utf-8") or "",
            "status": resp_status,
            "duration_ms": int((time.time() - start_s) * 1000),
            "req_size": len(req_body),
            "resp_size": len(resp_body) if resp_body is not None else -1,
            "subpath": subpath,
            "req_body_bytes": req_body if is_generate else None,
            "resp_body_bytes": resp_body if is_generate else None,
            "error": error,
            "user_agent": request.headers.get("User-Agent", ""),
            "referer": request.headers.get("Referer", ""),
            "user_id": session.get("user_id", "") or "",
            "username": _username,
        }
        _enqueue_log(record)
    except Exception:
        pass  # logging must never break proxying


# ── Proxy entry point ────────────────────────────────────────────────────────

def proxy_to(app_id: str, subpath: str, port_map: dict) -> Response:
    port = port_map.get(app_id)
    if port is None:
        return Response(f"Unknown app: {app_id}", status=404)

    target = f"http://127.0.0.1:{port}/{urllib.parse.quote(subpath, safe='/')}"
    if request.query_string:
        target += "?" + request.query_string.decode("utf-8")

    backend_req = _build_proxy_request(target)

    # ── Stats preamble ──────────────────────────────────────────────────
    # Log only: (a) page visits (empty subpath = app root), and
    #           (b) generate / capture actions (POST that produce content).
    # Background API calls (sponsor-board, examples, etc.) are skipped.
    is_gen = is_generate_endpoint(app_id, request.method, subpath)
    is_visit = not subpath
    do_log = is_visit or is_gen
    t0 = time.time() if do_log else 0
    # ── /stats preamble ─────────────────────────────────────────────────

    try:
        resp = urllib.request.urlopen(backend_req, timeout=3600)
    except urllib.error.HTTPError as e:
        # e.read() 只能消费一次：先取出 body，再分别用于日志和响应。
        # 此前 e.read() 在 _try_log 里被先读一次，第二次返回空 → 4xx 错误
        # 响应体被静默吞掉，前端只看到空错误（违反「失败必须显式返回」铁律）。
        err_body = e.read() or b""
        if do_log:
            _try_log(app_id, subpath, t0, e.code, err_body, error=f"HTTPError {e.code}", is_generate=is_gen)
        return Response(err_body, status=e.code)
    except Exception as e:
        if do_log:
            _try_log(app_id, subpath, t0, 502, b"", error=str(e), is_generate=is_gen)
        return Response(f"Proxy error: {e}", status=502)

    resp_headers = _filter_headers(dict(resp.headers))
    content_type = resp.headers.get("Content-Type", "").lower()
    is_sse = "text/event-stream" in content_type

    if is_sse:
        # Log SSE without buffering the body
        if do_log:
            _try_log(app_id, subpath, t0, resp.status, None, is_generate=is_gen)
        def generate():
            try:
                while True:
                    chunk = resp.readline()
                    if not chunk:
                        break
                    yield chunk
            finally:
                resp.close()
        return Response(generate(), status=resp.status,
                        headers=resp_headers,
                        content_type="text/event-stream")

    try:
        body = resp.read()
    finally:
        resp.close()

    content_encoding = resp.headers.get("Content-Encoding", "")
    if "gzip" in content_encoding:
        try:
            body = gzip.decompress(body)
        except Exception:
            pass
        resp_headers.pop("Content-Encoding", None)

    # ── Stats: log the full (non-streamed) response ─────────────────────
    if do_log:
        _try_log(app_id, subpath, t0, resp.status, body, is_generate=is_gen)
    # ── /stats ──────────────────────────────────────────────────────────

    is_html = any(m in content_type for m in _HTML_MIMES)
    is_js = any(m in content_type for m in _JS_MIMES)

    if is_html or is_js:
        body_str = body.decode("utf-8", errors="replace")

        # Rewrite absolute paths in both HTML and JS
        body_str = _rewrite_paths(body_str, app_id)

        if is_html:
            # Inject <base> so relative URLs resolve correctly
            base_tag = f'<base href="/app/{app_id}/">'
            if "<head>" in body_str:
                body_str = body_str.replace("<head>", f"<head>\n  {base_tag}", 1)

        body = body_str.encode("utf-8")
        resp_headers["Content-Length"] = str(len(body))

    return Response(body, status=resp.status, headers=resp_headers)
