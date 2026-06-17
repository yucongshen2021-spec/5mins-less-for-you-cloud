#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户数据库 —— 注册 / 登录 / 查询。独立 SQLite（auth.sqlite），WAL 模式。"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

# ── 数据库文件路径 ──────────────────────────────────────────────────────────
_DEFAULT_DB = Path(__file__).resolve().parent.parent / "portal" / "logs" / "auth.sqlite"
_write_lock = threading.Lock()


def get_auth_db_path() -> Path:
    """返回 auth.sqlite 的绝对路径。"""
    env = __import__("os").environ.get("AUTH_DB", "")
    return Path(env) if env else _DEFAULT_DB


_db_path = get_auth_db_path()


def init_auth_db() -> None:
    """建表（幂等）。WAL 模式提升并发读性能。"""
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        conn = sqlite3.connect(str(_db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id      TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )""")
            conn.commit()
        finally:
            conn.close()


def create_user(username: str, password: str) -> dict:
    """注册新用户。成功返回 {ok: True, user_id: str}，失败返回 {ok: False, error: str}。"""
    username = str(username).strip()
    if not username or len(username) < 2:
        return {"ok": False, "error": "用户名至少 2 个字符"}
    if not password or len(password) < 4:
        return {"ok": False, "error": "密码至少 4 个字符"}

    user_id = uuid.uuid4().hex[:12]
    pw_hash = generate_password_hash(password)

    with _write_lock:
        conn = sqlite3.connect(str(_db_path))
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                (user_id, username, pw_hash),
            )
            conn.commit()
            return {"ok": True, "user_id": user_id}
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "用户名已存在"}
        finally:
            conn.close()


def verify_user(username: str, password: str) -> dict:
    """验证登录。成功返回 {ok: True, user_id: str, username: str}。"""
    username = str(username).strip()
    conn = sqlite3.connect(str(_db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row and check_password_hash(row[2], password):
            return {"ok": True, "user_id": row[0], "username": row[1]}
        return {"ok": False, "error": "用户名或密码错误"}
    finally:
        conn.close()


def get_user_by_id(user_id: str) -> dict | None:
    """根据 user_id 返回用户信息，不存在返回 None。"""
    conn = sqlite3.connect(str(_db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return {"user_id": row[0], "username": row[1], "created_at": row[2]}
        return None
    finally:
        conn.close()


# 模块加载时自动建表
init_auth_db()
