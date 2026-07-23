"""Shared SQLite access-log database for the portal stats system.

All functions accept `db_path` as their first argument so both the portal
(writing) and the stats app (reading) can share the same persistent DB file.
"""

import json
import os
import sqlite3
import threading
from typing import Any, Optional

# ── DB path resolution ──────────────────────────────────────────────────────

_DEFAULT_DB = None  # lazy-resolved once


def get_db_path() -> str:
    """Return the resolved stats DB path.

    Priority: STATS_DB env var > <application_root>/portal/logs/stats.sqlite
    """
    global _DEFAULT_DB
    if _DEFAULT_DB is not None:
        if os.environ.get("STATS_DB"):
            return os.environ["STATS_DB"]
        return _DEFAULT_DB

    env = os.environ.get("STATS_DB")
    if env:
        _DEFAULT_DB = env
        return env

    # Compute relative to this file: …/application/common/stats_db.py → application/portal/logs/
    here = os.path.dirname(os.path.abspath(__file__))
    app_root = os.path.dirname(here)  # application/
    _DEFAULT_DB = os.path.join(app_root, "portal", "logs", "stats.sqlite")
    return _DEFAULT_DB


# ── Schema init ──────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS access_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT    NOT NULL,
    ip              TEXT    NOT NULL,
    app_id          TEXT,
    method          TEXT,
    path            TEXT,
    query           TEXT,
    status          INTEGER,
    duration_ms     INTEGER,
    req_size        INTEGER,
    resp_size       INTEGER,
    function        TEXT,
    variant         TEXT,
    data_header     TEXT,
    request_body    TEXT,
    response_body   TEXT,
    user_agent      TEXT,
    referer         TEXT,
    error           TEXT,
    user_id         TEXT DEFAULT '',
    username        TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_access_ts       ON access_log(ts);
CREATE INDEX IF NOT EXISTS idx_access_ip       ON access_log(ip);
CREATE INDEX IF NOT EXISTS idx_access_function ON access_log(function);
CREATE INDEX IF NOT EXISTS idx_access_app      ON access_log(app_id);
"""

_write_lock = threading.Lock()


def init_db(db_path: str = None) -> str:
    """Ensure the DB file and tables exist.  Returns the resolved path."""
    path = db_path or get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _write_lock:
        conn = sqlite3.connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA_SQL)
            # 兼容旧库：无 user_id/username 列时自动添加
            try: conn.execute("ALTER TABLE access_log ADD COLUMN user_id TEXT DEFAULT ''")
            except Exception: pass
            try: conn.execute("ALTER TABLE access_log ADD COLUMN username TEXT DEFAULT ''")
            except Exception: pass
            conn.commit()
        finally:
            conn.close()
    return path


# ── Content classification helpers ───────────────────────────────────────────

# Paths that should NOT be logged (static assets, health checks)
_STATIC_EXTS = frozenset({
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".eot", ".map", ".webp", ".pdf",
})

_STATIC_PREFIXES = ("static/", "assets/", "favicon", "apple-touch")
_INTERNAL_PREFIXES = ("api/health", "api/status")  # portal's own pings


def is_skippable(subpath: str) -> bool:
    """Return True for paths that should be excluded from access logging."""
    if not subpath:
        return False  # root page — log it
    lower = subpath.lower()
    # Static by extension
    for ext in _STATIC_EXTS:
        if lower.endswith(ext) or f"{ext}?" in lower:
            return True
    # Static by prefix
    for pfx in _STATIC_PREFIXES:
        if lower.startswith(pfx) or f"/{pfx.lstrip('/')}" in lower:
            return True
    # Internal pings
    for pfx in _INTERNAL_PREFIXES:
        if lower.startswith(pfx):
            return True
    return False


# Generate-type endpoints — capture data_header + generated content
_GENERATE_PATTERNS = [
    # all_in_one config generation (6 tools, 7 endpoints incl. epoch_fastip5)
    ("all_in_one", "POST", "api/generate/epoch_fastip5"),
    ("all_in_one", "POST", "api/generate/epoch_fastip"),
    ("all_in_one", "POST", "api/generate/usg_fastip"),
    ("all_in_one", "POST", "api/generate/epoch_mpls"),
    ("all_in_one", "POST", "api/generate/ar_sdwan"),
    ("all_in_one", "POST", "api/generate/ar_traditional"),
    # domain_capture
    ("domain_capture", "POST", "api/capture"),
    # test_report
    ("test_report", "POST", "api/run"),
    ("test_report", "POST", "api/mock/run"),
]


def is_generate_endpoint(app_id: str, method: str, subpath: str) -> bool:
    """Return True if this endpoint should have data_header + content captured."""
    if not subpath:
        return False
    sp = subpath.rstrip("/").split("?")[0]
    for aid, m, prefix in _GENERATE_PATTERNS:
        if app_id == aid and method == m and sp == prefix:
            return True
    return False


def derive_function(app_id: str, method: str, subpath: str,
                    req_json: Optional[dict] = None) -> str:
    """Return a human-readable function label."""
    sp = (subpath or "").rstrip("/").split("?")[0]

    if app_id == "all_in_one":
        if method == "POST" and sp.startswith("api/generate/"):
            tool = sp[len("api/generate/"):]
            variant = (req_json or {}).get("variant", "")
            label = f"生成·{tool}"
            if variant:
                label += f"({variant})"
            return label
        if method == "GET" and not sp:
            return "打开·配置生成"
        if sp.startswith("api/template/"):
            return f"模板·{sp.split('/')[-1]}"
        if sp.startswith("api/tools"):
            return "API·工具列表"
        if sp.startswith("api/examples"):
            return "API·示例"
        if sp.startswith("api/notes"):
            return "API·说明"
        if sp.startswith("api/sponsor-board"):
            return "API·赞助榜"
        if sp.startswith("api/scenarios"):
            return "API·场景"
        if sp.startswith("api/init-defaults"):
            return "API·默认值"

    if app_id == "domain_capture":
        if method == "POST" and sp == "api/capture":
            return "抓取域名"
        if method == "GET" and not sp:
            return "打开·域名抓取"

    if app_id == "test_report":
        if method == "POST" and sp == "api/run":
            return "生成测试报告"
        if method == "POST" and sp == "api/mock/run":
            return "生成·Mock报告"
        if method == "GET" and not sp:
            return "打开·测试报告"
        if sp.startswith("api/download"):
            return "下载报告"

    if app_id == "config_analyzer":
        if method == "GET" and not sp:
            return "打开·配置梳理"

    # Fallback
    short = sp[:50] if sp else "(root)"
    return f"{app_id}:{method} {short}"


def extract_generate_details(app_id: str, method: str, subpath: str,
                             req_json: Optional[dict],
                             resp_json: Optional[dict],
                             resp_text: str) -> dict:
    """Return {data_header, variant, request_body, response_body} for generate endpoints."""
    result = {"data_header": None, "variant": None,
              "request_body": None, "response_body": None}
    if not is_generate_endpoint(app_id, method, subpath):
        return result

    # Data header & request body from request
    if req_json:
        dh = req_json.get("header_text") or ""
        if isinstance(dh, str) and dh.strip():
            result["data_header"] = dh
        if req_json.get("variant"):
            result["variant"] = req_json["variant"]
        # Store full request body (includes network params, etc.)
        result["request_body"] = json.dumps(req_json, ensure_ascii=False, default=str)

    # Generated content from response
    if resp_json and isinstance(resp_json, dict):
        output = (resp_json.get("output") or resp_json.get("ops_output") or
                  resp_json.get("factory_output") or "")
        if isinstance(output, str) and output.strip():
            result["response_body"] = output
        elif output:
            result["response_body"] = str(output)
    elif resp_text and resp_text.strip():
        # Non-JSON response (unlikely for generate endpoints, but safe)
        result["response_body"] = resp_text

    return result


# ── Core write ───────────────────────────────────────────────────────────────

_MAX_FIELD_CHARS = 2_000_000


def _trunc(val: Optional[str]) -> Optional[str]:
    if val is None:
        return None
    if len(val) > _MAX_FIELD_CHARS:
        return val[:_MAX_FIELD_CHARS]
    return val


def log_access(
    ts: str,
    ip: str,
    app_id: str = None,
    method: str = None,
    path: str = None,
    query: str = None,
    status: int = None,
    duration_ms: int = None,
    req_size: int = None,
    resp_size: int = None,
    subpath: str = None,
    req_body_bytes: bytes = None,
    resp_body_bytes: bytes = None,
    error: str = None,
    user_agent: str = None,
    referer: str = None,
    user_id: str = None,
    username: str = None,
) -> bool:
    """Write one access record.  Swallows all exceptions (never breaks the caller)."""
    try:
        # Parse request body
        req_json = None
        if req_body_bytes:
            try:
                req_json = json.loads(req_body_bytes.decode("utf-8", errors="replace"))
            except Exception:
                pass

        # Parse response body
        resp_text = None
        resp_json = None
        if resp_body_bytes:
            try:
                resp_text = resp_body_bytes.decode("utf-8", errors="replace")
                resp_json = json.loads(resp_text)
            except Exception:
                resp_text = str(resp_body_bytes)[:_MAX_FIELD_CHARS]

        # Derive labels
        function = derive_function(app_id, method, subpath, req_json)
        gen = extract_generate_details(app_id, method, subpath,
                                       req_json, resp_json, resp_text or "")

        row = {
            "ts": ts,
            "ip": ip,
            "app_id": app_id,
            "method": method,
            "path": path,
            "query": _trunc(query),
            "status": status,
            "duration_ms": duration_ms,
            "req_size": req_size,
            "resp_size": resp_size,
            "function": function,
            "variant": gen.get("variant"),
            "data_header": _trunc(gen.get("data_header")),
            "request_body": _trunc(gen.get("request_body")),
            "response_body": _trunc(gen.get("response_body")),
            "user_agent": _trunc(user_agent),
            "referer": _trunc(referer),
            "error": _trunc(error),
            "user_id": _trunc(user_id) or "",
            "username": _trunc(username) or "",
        }

        db_path = get_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        with _write_lock:
            conn = sqlite3.connect(db_path)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(
                    """INSERT INTO access_log
                       (ts, ip, app_id, method, path, query, status,
                        duration_ms, req_size, resp_size, function, variant,
                        data_header, request_body, response_body,
                        user_agent, referer, error, user_id, username)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["ts"], row["ip"], row["app_id"], row["method"],
                     row["path"], row["query"], row["status"],
                     row["duration_ms"], row["req_size"], row["resp_size"],
                     row["function"], row["variant"],
                     row["data_header"], row["request_body"], row["response_body"],
                     row["user_agent"], row["referer"], row["error"],
                     row["user_id"], row["username"]),
                )
                conn.commit()
            finally:
                conn.close()
        return True
    except Exception:
        return False


# ── Query helpers (read-only, for the stats app) ─────────────────────────────

def _connect_read(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA query_only=ON")
    return conn


def _build_where(filters: dict) -> tuple:
    """Build WHERE clause + params from filters dict. Shared by query/count/csv."""
    where_clauses = []
    params = []

    if filters.get("ip"):
        where_clauses.append("ip LIKE ?")
        params.append(f"%{filters['ip']}%")
    if filters.get("app_id"):
        where_clauses.append("app_id = ?")
        params.append(filters["app_id"])
    if filters.get("function"):
        where_clauses.append("function LIKE ?")
        params.append(f"%{filters['function']}%")
    if filters.get("username"):
        where_clauses.append("username LIKE ?")
        params.append(f"%{filters['username']}%")
    if filters.get("start"):
        where_clauses.append("ts >= ?")
        params.append(filters["start"])
    if filters.get("end"):
        where_clauses.append("ts <= ?")
        params.append(filters["end"])
    if filters.get("q"):
        where_clauses.append("(path LIKE ? OR data_header LIKE ? OR response_body LIKE ?)")
        q = f"%{filters['q']}%"
        params.extend([q, q, q])

    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    return where, params


# ── Per-user query functions (only generate records) ────────────────────────

_GEN_FILTER = "function LIKE '生成·%'"

# 列表查询只取看板表格需要的轻量列，排除三个大 TEXT 字段
# (data_header / request_body / response_body) —— 完整内容由详情接口
# get_record() 按需拉取。这把单次列表响应从 ~660KB 降到 ~15KB。
_LIST_COLUMNS = (
    "id, ts, ip, app_id, method, path, query, status, duration_ms, "
    "req_size, resp_size, function, variant, user_agent, referer, "
    "error, user_id, username"
)

def query_user_records(db_path: str, username: str,
                       page: int = 1, page_size: int = 20) -> list:
    """Return a page of generate records for a specific user, newest first."""
    offset = max(0, (page - 1)) * page_size
    conn = _connect_read(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_LIST_COLUMNS} FROM access_log WHERE username = ? AND {_GEN_FILTER} ORDER BY id DESC LIMIT ? OFFSET ?",
            [username, page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_user_records(db_path: str, username: str) -> int:
    """Return total generate record count for a specific user."""
    conn = _connect_read(db_path)
    try:
        return conn.execute(
            f"SELECT COUNT(*) FROM access_log WHERE username = ? AND {_GEN_FILTER}", [username]
        ).fetchone()[0]
    finally:
        conn.close()


def query_user_summary(db_path: str, username: str) -> dict:
    """Return per-user statistics: generate count, last active, top scenarios."""
    conn = _connect_read(db_path)
    try:
        gen_count = conn.execute(
            f"SELECT COUNT(*) FROM access_log WHERE username = ? AND {_GEN_FILTER}",
            [username]
        ).fetchone()[0]

        last_active = conn.execute(
            f"SELECT ts FROM access_log WHERE username = ? AND {_GEN_FILTER} ORDER BY id DESC LIMIT 1",
            [username]
        ).fetchone()

        top_scenarios = [
            dict(r) for r in conn.execute(
                f"SELECT function, COUNT(*) as cnt FROM access_log "
                f"WHERE username = ? AND {_GEN_FILTER} "
                f"GROUP BY function ORDER BY cnt DESC LIMIT 5",
                [username]
            ).fetchall()
        ]

        first_seen = conn.execute(
            f"SELECT ts FROM access_log WHERE username = ? AND {_GEN_FILTER} ORDER BY id ASC LIMIT 1",
            [username]
        ).fetchone()

        return {
            "username": username,
            "generate_count": gen_count,
            "last_active": last_active[0] if last_active else None,
            "first_seen": first_seen[0] if first_seen else None,
            "top_scenarios": top_scenarios,
        }
    finally:
        conn.close()


def query_records(db_path: str, filters: dict,
                  page: int = 1, page_size: int = 50) -> list:
    """Return a page of access_log rows as dicts, newest first.

    Only the lightweight columns are selected (see _LIST_COLUMNS); the heavy
    data_header / request_body / response_body are fetched on demand via
    get_record() when a user opens a single record's detail.
    """
    where, params = _build_where(filters)
    offset = max(0, (page - 1)) * page_size

    conn = _connect_read(db_path)
    try:
        rows = conn.execute(
            f"SELECT {_LIST_COLUMNS} FROM access_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_records(db_path: str, filters: dict) -> int:
    """Return total record count for the given filters."""
    where, params = _build_where(filters)
    conn = _connect_read(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM access_log {where}", params).fetchone()[0]
    finally:
        conn.close()


def get_record(db_path: str, record_id: int) -> Optional[dict]:
    """Return a single record by id, or None."""
    conn = _connect_read(db_path)
    try:
        row = conn.execute("SELECT * FROM access_log WHERE id = ?", (record_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def query_summary(db_path: str) -> dict:
    """Return summary statistics as a dict."""
    conn = _connect_read(db_path)
    try:
        total = conn.execute("SELECT COUNT(*) FROM access_log").fetchone()[0]
        unique_ips = conn.execute(
            "SELECT COUNT(DISTINCT ip) FROM access_log").fetchone()[0]
        unique_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM access_log WHERE user_id IS NOT NULL AND user_id != ''").fetchone()[0]
        guest_count = conn.execute(
            "SELECT COUNT(*) FROM access_log WHERE user_id = ''").fetchone()[0]
        generate_count = conn.execute(
            "SELECT COUNT(*) FROM access_log WHERE response_body IS NOT NULL").fetchone()[0]
        error_count = conn.execute(
            "SELECT COUNT(*) FROM access_log WHERE error IS NOT NULL OR (status >= 400 AND status < 600)").fetchone()[0]

        # Top 10 IPs
        top_ips = [
            dict(r) for r in conn.execute(
                "SELECT ip, COUNT(*) as cnt FROM access_log "
                "GROUP BY ip ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
        ]

        # Top 10 functions
        top_funcs = [
            dict(r) for r in conn.execute(
                "SELECT function, COUNT(*) as cnt FROM access_log "
                "WHERE function IS NOT NULL "
                "GROUP BY function ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
        ]

        # Top 10 users (exclude empty username = guest)
        top_users = [
            dict(r) for r in conn.execute(
                "SELECT username, COUNT(*) as cnt FROM access_log "
                "WHERE username IS NOT NULL AND username != '' AND username != '访客' "
                "GROUP BY username ORDER BY cnt DESC LIMIT 10"
            ).fetchall()
        ]

        # Daily trend (last 14 days)
        daily = [
            dict(r) for r in conn.execute(
                "SELECT DATE(ts) as day, COUNT(*) as cnt FROM access_log "
                "WHERE ts >= DATE('now', '+8 hours', '-13 days') "
                "GROUP BY day ORDER BY day"
            ).fetchall()
        ]

        return {
            "total": total,
            "unique_ips": unique_ips,
            "unique_users": unique_users,
            "guest_count": guest_count,
            "generate_count": generate_count,
            "error_count": error_count,
            "top_ips": top_ips,
            "top_functions": top_funcs,
            "top_users": top_users,
            "daily_trend": daily,
        }
    finally:
        conn.close()


def iter_records_csv(db_path: str, filters: dict):
    """Generator yielding CSV lines (one per row)."""
    import csv
    import io

    where, params = _build_where(filters)

    header = ["id", "时间", "IP", "应用", "方法", "路径", "查询",
              "状态码", "耗时(ms)", "请求大小", "响应大小",
              "功能", "variant", "用户", "数据头长度", "生成内容长度",
              "User-Agent", "Referer", "错误"]

    conn = _connect_read(db_path)
    try:
        rows = conn.execute(
            f"SELECT id, ts, ip, app_id, method, path, query, status, "
            f"duration_ms, req_size, resp_size, function, variant, "
            f"username, length(data_header), length(response_body), "
            f"user_agent, referer, error "
            f"FROM access_log {where} ORDER BY id DESC",
            params,
        ).fetchall()

        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(header)
        yield out.getvalue()
        out.close()

        for r in rows:
            d = dict(r)
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow([d.get(k) if d.get(k) is not None else "" for k in [
                "id", "ts", "ip", "app_id", "method", "path", "query",
                "status", "duration_ms", "req_size", "resp_size",
                "function", "variant",
                "username",
                "length(data_header)", "length(response_body)",
                "user_agent", "referer", "error",
            ]])
            yield out.getvalue()
            out.close()
    finally:
        conn.close()
