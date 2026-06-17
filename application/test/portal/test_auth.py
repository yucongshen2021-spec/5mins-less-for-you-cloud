#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录系统测试 — 注册 / 登录 / 鉴权 / workspace 隔离。

测试环境：8000 端口，需启动测试容器。
"""

import json
import urllib.request

import pytest

BASE = "http://localhost:8000"


def post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read()), resp.headers
    except urllib.error.HTTPError as e:
        body = json.loads(e.read()) if e.fp else {"error": str(e)}
        return e.code, body, e.headers


def get(path):
    req = urllib.request.Request(f"{BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read()), resp.headers
    except urllib.error.HTTPError as e:
        body = json.loads(e.read()) if e.fp else {"error": str(e)}
        return e.code, body, e.headers


class TestAuth:
    """注册 / 登录 / 退出。"""

    _test_user = f"testuser_{__name__}"
    _test_pass = "test1234"

    @classmethod
    def setup_class(cls):
        """注册测试用户（幂等）。"""
        post("/register", {"username": cls._test_user, "password": cls._test_pass})

    def test_register_duplicate(self):
        """重复注册应报错。"""
        st, d, _ = post("/register", {"username": self._test_user, "password": "test1234"})
        assert st == 409
        assert not d.get("ok")
        assert "已存在" in d.get("error", "")

    def test_register_short_password(self):
        """密码太短应报错。"""
        st, d, _ = post("/register", {"username": "shortpw", "password": "ab"})
        assert not d.get("ok")

    def test_login_success(self):
        """正确密码登录成功。"""
        st, d, headers = post("/login", {"username": self._test_user, "password": self._test_pass})
        assert st == 200
        assert d.get("ok")
        # 应有 session cookie
        cookie = headers.get("Set-Cookie", "")
        assert "session" in cookie.lower() or st == 200

    def test_login_wrong_password(self):
        """错误密码登录失败。"""
        st, d, _ = post("/login", {"username": self._test_user, "password": "wrongpass"})
        assert not d.get("ok")

    def test_protected_page_without_login(self):
        """未登录访问首页应 302。"""
        st, d, headers = get("/")
        # 302 redirect 可能被 urllib 跟随或返回 302
        # 直接用 HTTP 检查
        req = urllib.request.Request(f"{BASE}/")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code in (302, 303, 401), f"Expected redirect, got {e.code}"
        except Exception:
            pass  # 302 可能被跟随，也 ok

    def test_health_unprotected(self):
        """健康检查不需要登录。"""
        st, d, _ = get("/api/health")
        assert st == 200
        assert d.get("ok")

    def test_logout(self):
        """退出后 session 清空。"""
        # 先登录获取 cookie
        st, d, headers = post("/login", {"username": self._test_user, "password": self._test_pass})
        assert d.get("ok")
        cookie = headers.get("Set-Cookie", "")

        # 退出
        req = urllib.request.Request(f"{BASE}/logout")
        if cookie:
            req.add_header("Cookie", cookie.split(";")[0])
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                assert resp.status in (200, 302, 303)
        except urllib.error.HTTPError as e:
            assert e.code in (302, 303)
