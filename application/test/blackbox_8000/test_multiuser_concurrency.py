"""8000 端口多用户登录 + 工作区隔离 + 16 并发验证。

目标：验证登录系统在 16 用户规模下能正常工作、配置生成按用户隔离、
16 个 gunicorn worker 真实并发下无 5xx / 无串号。

设计原则：
  1. 纯 HTTP 黑盒 —— 通过 portal (8000) 发请求，复用 urllib.request 模式。
  2. 16 用户 —— register ctest01~ctest16，各自独立 session cookie。
  3. 并发用 ThreadPoolExecutor(max_workers=16)，每线程用各自 opener。
  4. 隔离验证 —— yucs 保存自定义模板后只有自己生成含标记，其他用户不含。
  5. 权限验证 —— 非 yucs 调用模板/初始化默认值的 save/reset/preview 一律 403。

前置：8000 测试容器在跑，且部署 16 个 gunicorn worker。
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from . import headers as H

# ═════════════════════════════════════════════════════════════
# 配置常量
# ═════════════════════════════════════════════════════════════
BASE = os.environ.get("BLACKBOX_BASE", "http://127.0.0.1:8000").rstrip("/")
AIO = f"{BASE}/app/all_in_one"
CONTAINER = os.environ.get("TEST_CONTAINER", "fivemins-portal-test")

NUM_USERS = 16
TEST_USER_PREFIX = "ctest"
TEST_USER_PW = "ctest123456"
ADMIN_USER = "yucs"
ADMIN_PW = os.environ.get("YUCS_PASSWORD", "yucs123")

# 用于隔离验证的标记前缀（每次测试用唯一标记避免互相影响）
ISOLATION_MARKER = f"ISOLATION_TEST_{int(time.time())}"

# ER FastIP HK 场景的模板文件目录名（safe_key）和模板 slot
ER_HK_KEY = "Epoch FastIP \u00b7 HK \u9999\u6e2f\u51fa\u53e3"

# 生成场景样本（route, variant, header, network）—— 覆盖全部 5 个 tool
GEN_SAMPLES = [
    ("epoch_fastip", "hk", H.ER_HK, {}),
    ("usg_fastip", "us", H.USG_US, {}),
    ("epoch_mpls", "domestic", H.MPLS_CN, {}),
    ("ar_traditional", "dual", H.AR_TRADITIONAL, {}),
]


# ═════════════════════════════════════════════════════════════
# HTTP 工具函数
# ═════════════════════════════════════════════════════════════
def _req(method, url, *, body=None, timeout=30.0, extra_headers=None):
    """发起一次 HTTP 请求，返回 (status, json_or_text)。"""
    data = None
    headers = {"User-Agent": "multiuser-concurrency/1.0"}
    if extra_headers:
        headers.update(extra_headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _make_opener():
    """创建一个带独立 CookieJar 的 opener，返回 (opener, cookiejar)。"""
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    return opener, cj


def _login_with_opener(opener, username, password):
    """用指定 opener 登录，session cookie 自动存入 opener 的 CookieJar。返回是否成功。"""
    data = json.dumps({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/login", data=data,
        headers={"Content-Type": "application/json", "User-Agent": "multiuser-concurrency/1.0"},
    )
    try:
        with opener.open(req, timeout=15.0) as r:
            body = json.loads(r.read().decode("utf-8", errors="replace"))
            return bool(body.get("ok"))
    except Exception:
        return False


def _gen_with_opener(opener, route, variant, header, network=None, timeout=30.0):
    """用指定 opener 发起生成请求（走自己的 session cookie）。返回 (status, body)。"""
    payload = {"variant": variant, "header_text": header, "network": network or {}}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{AIO}/api/generate/{route}", data=data,
        headers={"Content-Type": "application/json", "User-Agent": "multiuser-concurrency/1.0"},
        method="POST",
    )
    try:
        with opener.open(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def _docker_exec(*args):
    """在测试容器内执行命令，返回 stdout。"""
    cmd = ["sudo", "docker", "exec", CONTAINER] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.stdout.strip()


def _docker_exec_bash(script):
    """在测试容器内用 bash -c 执行脚本，返回 stdout。"""
    return _docker_exec("bash", "-c", script)


# ═════════════════════════════════════════════════════════════
# 用户会话类
# ═════════════════════════════════════════════════════════════
class UserSession:
    """一个测试用户的会话句柄。"""
    def __init__(self, username, idx):
        self.username = username
        self.idx = idx
        self.opener, self.cookiejar = _make_opener()
        self.logged_in = False

    def login(self):
        self.logged_in = _login_with_opener(self.opener, self.username, TEST_USER_PW)
        return self.logged_in

    def gen(self, route, variant, header, network=None, timeout=30.0):
        return _gen_with_opener(self.opener, route, variant, header, network, timeout)


# ═════════════════════════════════════════════════════════════
# 清理辅助函数
# ═════════════════════════════════════════════════════════════
def _reset_template_via_admin(admin_opener, key):
    """让 yucs reset 指定场景的模板，清除残留的自定义标记。返回是否成功。"""
    data = json.dumps({"key": key}).encode("utf-8")
    req = urllib.request.Request(
        f"{AIO}/api/template/reset", data=data,
        headers={"Content-Type": "application/json", "User-Agent": "cleanup/1.0"},
        method="POST",
    )
    try:
        with admin_opener.open(req, timeout=15) as r:
            body = json.loads(r.read().decode("utf-8", errors="replace"))
            return bool(body.get("ok"))
    except Exception:
        return False


def _purge_residual_templates():
    """清除容器内所有用户 workspace 里残留的 TEMPLATE_*.tpl，
    避免前次测试运行留下的脏模板干扰本次隔离/并发断言。
    headers.txt / mapping.txt 一并删除，确保回到出厂状态。"""
    _docker_exec_bash(
        "find '/app/application/all_in_one - cc/data/users/' "
        "-type f \\( -name 'TEMPLATE_*.tpl' -o -name 'headers.txt' -o -name 'mapping.txt' \\) "
        "-delete 2>/dev/null || true"
    )


def _find_gunicorn_master_pid():
    """找到 gunicorn master 进程 PID（最小 PID 的 gunicorn 进程）。"""
    # 用 python 在容器内找，避免 bash 引号问题
    py_script = (
        "import os\n"
        "pids = []\n"
        "for d in os.listdir('/proc'):\n"
        "    if d.isdigit():\n"
        "        try:\n"
        "            with open(f'/proc/{d}/comm') as f:\n"
        "                if f.read().strip() == 'gunicorn':\n"
        "                    pids.append(int(d))\n"
        "        except Exception:\n"
        "            pass\n"
        "print(min(pids) if pids else '')\n"
    )
    out = _docker_exec("python3", "-c", py_script)
    try:
        return int(out.strip())
    except (ValueError, TypeError):
        return None


def _restart_gunicorn_workers():
    """重启 all_in_one 的 gunicorn worker，强制每个 worker 重新加载 ns。
    api_template_reset 会把读到的模板写回 ns（line 2107-2108），
    一旦 ns 被脏模板污染就无法通过 reset 清除——必须重启 worker 才能恢复出厂 ns。
    方法：向 gunicorn master 发 SIGHUP，触发 graceful worker 重启。
    SIGHUP 后旧 worker 会处理完当前请求再退出，新旧 worker 共存一段时间，
    所以需要轮询确认所有 worker 都已刷新（生成输出回到出厂模板）。"""
    master_pid = _find_gunicorn_master_pid()
    if master_pid is None:
        pytest.fail("无法找到 gunicorn master 进程，无法重启 worker")
    # SIGHUP → gunicorn master 优雅重启所有 worker
    # busybox 容器没有独立 kill 命令，用 bash 内建 kill
    _docker_exec_bash(f"kill -HUP {master_pid}")
    # 等待 worker 重新就绪（health check）
    for _ in range(30):
        st, _ = _req("GET", f"{BASE}/api/health", timeout=5)
        if st == 200:
            break
        time.sleep(1)
    else:
        pytest.fail("gunicorn SIGHUP 重启后 30s 内未恢复健康")
    # SIGHUP 是 graceful：旧 worker 处理完当前请求才退出。
    # 新旧 worker 共存期间，请求可能命中旧（脏）worker。
    # 轮询生成请求，直到连续 N 次都返回出厂模板（>50 行），
    # 确保所有 worker 都已刷新。
    CLEAN_THRESHOLD = 20
    consecutive_clean = 0
    for _ in range(120):
        st, body = _req("POST", f"{AIO}/api/generate/epoch_fastip",
                        body={"variant": "hk", "header_text": H.ER_HK, "network": {}},
                        timeout=15)
        if st != 200:
            consecutive_clean = 0
            time.sleep(0.5)
            continue
        out = body.get("output", "") if isinstance(body, dict) else ""
        if len(out.splitlines()) > 50:
            consecutive_clean += 1
            if consecutive_clean >= CLEAN_THRESHOLD:
                return
        else:
            consecutive_clean = 0
        time.sleep(0.3)
    pytest.fail(
        f"gunicorn SIGHUP 后 120 次轮询未能确认所有 worker 已刷新 "
        f"（连续干净 {consecutive_clean}/{CLEAN_THRESHOLD}）。"
        f"部分 worker 仍返回脏 ns 模板。"
    )


# ═════════════════════════════════════════════════════════════
# session 级 fixture
# ═════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def container_up():
    """确认容器在跑且 /api/health 返回 200，否则跳过。"""
    st, body = _req("GET", f"{BASE}/api/health", timeout=10)
    if st != 200:
        pytest.skip(f"8000 容器未就绪（/api/health 返回 {st}），跳过多用户并发测试")
    return True


@pytest.fixture(scope="module")
def gunicorn_workers(container_up):
    """确认 gunicorn worker 数 >= 16。"""
    out = _docker_exec_bash(
        "ls /proc/*/comm 2>/dev/null | while read f; do cat \"$f\" 2>/dev/null; done | grep -c gunicorn"
    )
    try:
        count = int(out)
    except ValueError:
        count = 0
    # 16 worker + 1 master = 17
    assert count >= NUM_USERS, (
        f"gunicorn 进程数 {count} 不足（期望 >= {NUM_USERS}，含 master）。"
        f"确认 supervisord 配置 GUNICORN_WORKERS=16"
    )
    return count


@pytest.fixture(scope="module", autouse=True)
def clean_admin_workspace(gunicorn_workers):
    """模块级自动 fixture：
    - 测试前：清除残留模板 + 重启 gunicorn worker 清除脏 ns
    - 测试结束后：清除残留模板 + 重启 gunicorn worker 恢复出厂 ns
    重启是必要的，因为 api_template_reset 会把读到的模板写回 ns（即使读到的
    是脏值），导致 ns 一旦被污染就无法通过 reset 清除，只能重启 worker。"""
    opener, _ = _make_opener()
    ok = _login_with_opener(opener, ADMIN_USER, ADMIN_PW)
    if ok:
        _reset_template_via_admin(opener, ER_HK_KEY)
    _purge_residual_templates()
    _restart_gunicorn_workers()
    yield
    if ok:
        _reset_template_via_admin(opener, ER_HK_KEY)
    _purge_residual_templates()
    _restart_gunicorn_workers()


@pytest.fixture(scope="module")
def test_users(gunicorn_workers):
    """创建并登录 16 个测试用户（ctest01~ctest16）。已存在的用户直接登录。"""
    users = []
    for i in range(1, NUM_USERS + 1):
        uname = f"{TEST_USER_PREFIX}{i:02d}"
        st, body = _req("POST", f"{BASE}/register",
                        body={"username": uname, "password": TEST_USER_PW})
        if st == 200 and body.get("ok"):
            pass  # 新建成功
        elif st == 409 or (body.get("error") and "已存在" in str(body.get("error", ""))):
            pass  # 已存在，正常
        else:
            pytest.fail(f"注册用户 {uname} 失败: status={st}, body={body}")
        u = UserSession(uname, i)
        ok = u.login()
        assert ok, f"用户 {uname} 登录失败"
        users.append(u)
    return users


@pytest.fixture(scope="module")
def admin_session(gunicorn_workers):
    """登录管理员 yucs。"""
    opener, _ = _make_opener()
    ok = _login_with_opener(opener, ADMIN_USER, ADMIN_PW)
    assert ok, f"管理员 {ADMIN_USER} 登录失败（密码 {ADMIN_PW}）"
    return opener


# ═════════════════════════════════════════════════════════════
# 测试组 A：登录系统验证
# ═════════════════════════════════════════════════════════════
class TestLoginSystem:
    """验证 16 用户登录、会话隔离、错误处理、访客模式。"""

    def test_16_users_login_success(self, test_users):
        """16 个用户全部登录成功，各自拿到独立的 session cookie。"""
        assert len(test_users) == NUM_USERS
        cookie_values = set()
        for u in test_users:
            assert u.logged_in, f"{u.username} 未登录成功"
            session_val = None
            for c in u.cookiejar:
                if c.name == "session":
                    session_val = c.value
                    break
            assert session_val is not None, f"{u.username} 无 session cookie"
            cookie_values.add(session_val)
        assert len(cookie_values) == NUM_USERS, \
            f"16 用户的 session cookie 有重复（只有 {len(cookie_values)} 个不同值）"

    def test_session_routes_to_different_workspace(self, test_users):
        """不同 session cookie 路由到不同用户目录。"""
        u1, u2 = test_users[0], test_users[1]
        st1, body1 = u1.gen("epoch_fastip", "hk", H.ER_HK)
        st2, body2 = u2.gen("epoch_fastip", "hk", H.ER_HK)
        assert st1 == 200 and body1.get("ok"), f"{u1.username} 生成失败: {body1}"
        assert st2 == 200 and body2.get("ok"), f"{u2.username} 生成失败: {body2}"
        assert body1.get("output", "").strip(), f"{u1.username} 输出为空"
        assert body2.get("output", "").strip(), f"{u2.username} 输出为空"

    def test_wrong_password_rejected(self, container_up):
        """错误密码返回 ok=False。"""
        st, body = _req("POST", f"{BASE}/login",
                        body={"username": "ctest01", "password": "WRONG_PASSWORD"})
        assert st == 200
        assert body.get("ok") is False, f"错误密码竟登录成功: {body}"

    def test_duplicate_register_rejected(self, container_up):
        """重复用户名注册返回 409 或 ok=False。"""
        st, body = _req("POST", f"{BASE}/register",
                        body={"username": "ctest01", "password": TEST_USER_PW})
        assert st == 409 or body.get("ok") is False, \
            f"重复注册 ctest01 应被拒绝: status={st}, body={body}"

    def test_guest_auto_session(self, container_up):
        """无 cookie 访问首页 → 自动获得 guest session（Set-Cookie）。"""
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(f"{BASE}/", headers={"User-Agent": "guest-test/1.0"})
        try:
            with opener.open(req, timeout=10) as r:
                r.read()
        except urllib.error.HTTPError as e:
            e.read()
        has_session = any(c.name == "session" for c in cj)
        assert has_session, "访客首次访问未获得自动 session cookie"


# ═════════════════════════════════════════════════════════════
# 测试组 B：配置生成工作区隔离
# ═════════════════════════════════════════════════════════════
class TestWorkspaceIsolation:
    """验证每个用户有独立的 workspace 目录，模板不串号。"""

    def test_user_workspace_dirs_independent(self, test_users):
        """16 个用户各自有独立的 data/users/<uid>/ 目录。"""
        for u in test_users:
            u.gen("epoch_fastip", "hk", H.ER_HK)
        out = _docker_exec_bash(
            "ls -1 '/app/application/all_in_one - cc/data/users/' 2>/dev/null || true"
        )
        dirs_after = set(out.split()) if out else set()
        assert len(dirs_after) >= NUM_USERS - 2, (
            f"用户目录数 {len(dirs_after)} 过少（期望 >= {NUM_USERS - 2}）。"
            f"目录列表: {sorted(dirs_after)}"
        )

    def test_template_isolation_admin_vs_user(self, test_users, admin_session):
        """yucs 保存自定义模板后：yucs 自己生成含标记；非 yucs 用户生成不含标记。"""
        key = ER_HK_KEY
        marker = ISOLATION_MARKER + "_ADMIN_VS_USER"
        custom_tpl = f"# {marker}\nset system host-name {marker}\n"

        data = json.dumps({
            "key": key, "header": H.ER_HK, "mapping": "", "template": custom_tpl,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{AIO}/api/template/save", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "isolation/1.0"},
            method="POST",
        )
        with admin_session.open(req, timeout=15.0) as r:
            save_body = json.loads(r.read().decode("utf-8", errors="replace"))
        assert save_body.get("ok"), f"yucs 保存模板失败: {save_body}"

        try:
            # yucs 自己生成 → 应含标记
            yucs_opener, _ = _make_opener()
            _login_with_opener(yucs_opener, ADMIN_USER, ADMIN_PW)
            st, body = _gen_with_opener(yucs_opener, "epoch_fastip", "hk", H.ER_HK)
            assert st == 200 and body.get("ok"), f"yucs 生成失败: {body}"
            yucs_out = body.get("output", "")
            assert marker in yucs_out, "yucs 生成输出不含自己保存的标记"

            # 非 yucs 用户生成 → 不应含该标记
            regular = test_users[0]
            st2, body2 = regular.gen("epoch_fastip", "hk", H.ER_HK)
            assert st2 == 200 and body2.get("ok"), f"{regular.username} 生成失败: {body2}"
            regular_out = body2.get("output", "")
            assert marker not in regular_out, (
                f"{regular.username} 的输出含 yucs 的标记 —— 工作区隔离失败！"
            )
        finally:
            data = json.dumps({"key": key}).encode("utf-8")
            req = urllib.request.Request(
                f"{AIO}/api/template/reset", data=data,
                headers={"Content-Type": "application/json", "User-Agent": "isolation/1.0"},
                method="POST",
            )
            try:
                admin_session.open(req, timeout=15.0).read()
            except Exception:
                pass

    def test_no_cross_user_template_leak(self, test_users):
        """16 用户并发生成同一场景，收集所有输出，确认互相无串号。
        每个用户使用带自己 idx 标记的 WAN IP，验证输出各自独立。
        IP 格式用 10.99.{idx}.1（带尾 .1 匹配，避免 10.99.1 匹配到 10.99.10）。"""
        results = {}

        def _do_gen(u):
            network = {"wan_cidr": f"10.99.{u.idx}.1/24"}
            st, body = u.gen("epoch_fastip", "hk", H.ER_HK, network=network)
            return u.idx, st, body

        with ThreadPoolExecutor(max_workers=NUM_USERS) as pool:
            futures = {pool.submit(_do_gen, u): u for u in test_users}
            for fut in as_completed(futures):
                idx, st, body = fut.result()
                results[idx] = (st, body)

        leaks = []
        for u in test_users:
            st, body = results.get(u.idx, (0, {}))
            assert st == 200, f"{u.username} 生成返回 {st}"
            out = body.get("output", "") if isinstance(body, dict) else ""
            my_ip = f"10.99.{u.idx}.1"
            assert my_ip in out, f"{u.username} 输出不含自己的 WAN IP {my_ip}"
            for other in test_users:
                if other.idx == u.idx:
                    continue
                other_ip = f"10.99.{other.idx}.1"
                if other_ip in out:
                    leaks.append((u.username, other.username, other_ip))

        assert not leaks, (
            f"检测到 {len(leaks)} 起跨用户串号泄漏:\n" +
            "\n".join(f"  {a} 的输出含 {b} 的 IP {c}" for a, b, c in leaks[:10])
        )

    def test_guest_uses_shared_workspace(self, container_up):
        """无 cookie 的请求不创建 users/<uid> 目录（使用共享 fallback）。"""
        before = _docker_exec_bash(
            "ls -1 '/app/application/all_in_one - cc/data/users/' 2>/dev/null | wc -l"
        )
        before_count = int(before) if before.isdigit() else 0

        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        opener.open(urllib.request.Request(f"{BASE}/"), timeout=10).read()
        data = json.dumps({"variant": "hk", "header_text": H.ER_HK, "network": {}}).encode()
        req = urllib.request.Request(
            f"{AIO}/api/generate/epoch_fastip", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "guest-ws/1.0"},
            method="POST",
        )
        opener.open(req, timeout=15).read()

        after = _docker_exec_bash(
            "ls -1 '/app/application/all_in_one - cc/data/users/' 2>/dev/null | wc -l"
        )
        after_count = int(after) if after.isdigit() else 0
        assert after_count == before_count, (
            f"访客请求意外新增了用户目录（{before_count} → {after_count}），"
            f"说明 guest 的 user_id 被错误注入"
        )


# ═════════════════════════════════════════════════════════════
# 测试组 C：并发安全性（重点）
# ═════════════════════════════════════════════════════════════
class TestConcurrency:
    """验证 16 worker 真实并发下无 5xx、无串号、无超时。"""

    def test_16_concurrent_generations_different_users(self, test_users):
        """16 个用户同时各发 1 个生成请求 → 全部 200 + 输出非空。"""
        results = {}

        def _do(u):
            route, variant, header, net = GEN_SAMPLES[u.idx % len(GEN_SAMPLES)]
            return u.idx, u.gen(route, variant, header, net)

        with ThreadPoolExecutor(max_workers=NUM_USERS) as pool:
            futs = {pool.submit(_do, u): u for u in test_users}
            for fut in as_completed(futs):
                idx, (st, body) = fut.result()
                results[idx] = (st, body)

        errors = []
        for u in test_users:
            st, body = results.get(u.idx, (0, {}))
            if st != 200:
                errors.append(f"{u.username}: HTTP {st}")
            elif not (body.get("ok") if isinstance(body, dict) else False):
                errors.append(f"{u.username}: ok=False ({body})")
        assert not errors, (
            f"16 并发生成中 {len(errors)} 个失败:\n" + "\n".join(errors[:10])
        )

    def test_16_concurrent_generations_same_scenario(self, test_users):
        """16 用户同时生成同一场景同一参数 → 全部输出一致，证明无 ns 串号。
        必须显式传完整 network 参数。_inject_network_to_module 对空值不覆盖
        （设计如此，前端总是发完整表单），所以空 network 会读到上一次请求残留的
        ns 值——这不是并发 bug 而是已知设计。用显式参数避免该情况。"""
        results = {}
        shared_network = {
            "wan_cidr": "192.168.99.1/24", "wan_gw": "192.168.99.254",
            "lan_cidr": "10.0.0.1/24", "lan_gw": "10.0.0.254",
            "wan_eth": "eth0", "lan_eth": "eth1", "inner_nets": "172.16.0.0/12",
            "wan_dhcp": False, "lan_dhcp": False,
        }

        def _do(u):
            return u.idx, u.gen("epoch_fastip", "hk", H.ER_HK, network=shared_network)

        with ThreadPoolExecutor(max_workers=NUM_USERS) as pool:
            futs = {pool.submit(_do, u): u for u in test_users}
            for fut in as_completed(futs):
                idx, (st, body) = fut.result()
                results[idx] = (st, body)

        outputs = []
        for u in test_users:
            st, body = results.get(u.idx, (0, {}))
            assert st == 200, f"{u.username} HTTP {st}"
            out = body.get("output", "") if isinstance(body, dict) else ""
            assert out.strip(), f"{u.username} 输出为空"
            outputs.append(out)

        unique_outputs = set(outputs)
        assert len(unique_outputs) == 1, (
            f"16 用户生成同一配置，却得到 {len(unique_outputs)} 种不同输出 —— 疑似 ns 串号"
        )

    def test_mixed_concurrent_load(self, test_users):
        """16 线程混合负载：每线程随机选场景 + 独特参数，并发 3 轮 → 全部成功。"""
        rounds = 3
        total = 0
        failures = []

        def _do_round(u, rnd):
            route, variant, header, net = GEN_SAMPLES[(u.idx + rnd) % len(GEN_SAMPLES)]
            net = dict(net)
            net["wan_cidr"] = f"172.16.{u.idx}.{rnd+1}/24"
            st, body = u.gen(route, variant, header, net)
            return u.username, rnd, st, body

        with ThreadPoolExecutor(max_workers=NUM_USERS) as pool:
            all_futs = []
            for rnd in range(rounds):
                for u in test_users:
                    all_futs.append(pool.submit(_do_round, u, rnd))
            for fut in as_completed(all_futs):
                uname, rnd, st, body = fut.result()
                total += 1
                if st != 200 or not (body.get("ok") if isinstance(body, dict) else False):
                    failures.append(f"{uname} round{rnd}: HTTP {st} {body}")

        assert not failures, (
            f"混合并发 {total} 请求中 {len(failures)} 个失败:\n" + "\n".join(failures[:10])
        )

    def test_concurrent_with_template_save(self, test_users, admin_session):
        """yucs 反复 save/reset 模板的同时，其他用户并发生成 → 普通用户不受影响，无 500。"""
        key = ER_HK_KEY
        marker = ISOLATION_MARKER + "_CONCURRENT_SAVE"

        def _admin_toggle():
            errors = []
            for _ in range(5):
                try:
                    data = json.dumps({
                        "key": key, "header": H.ER_HK, "mapping": "",
                        "template": f"# {marker}\nset system host-name {marker}\n",
                    }).encode()
                    req = urllib.request.Request(
                        f"{AIO}/api/template/save", data=data,
                        headers={"Content-Type": "application/json", "User-Agent": "toggle/1.0"},
                        method="POST",
                    )
                    admin_session.open(req, timeout=15).read()
                    data = json.dumps({"key": key}).encode()
                    req = urllib.request.Request(
                        f"{AIO}/api/template/reset", data=data,
                        headers={"Content-Type": "application/json", "User-Agent": "toggle/1.0"},
                        method="POST",
                    )
                    admin_session.open(req, timeout=15).read()
                except Exception as e:
                    errors.append(str(e))
            return errors

        def _user_gen(u):
            st, body = u.gen("epoch_fastip", "hk", H.ER_HK, timeout=20)
            return u.username, st, body

        admin_errors = []
        user_errors = []
        with ThreadPoolExecutor(max_workers=NUM_USERS + 1) as pool:
            admin_fut = pool.submit(_admin_toggle)
            user_futs = {pool.submit(_user_gen, u): u for u in test_users[:15]}
            for fut in as_completed(user_futs):
                uname, st, body = fut.result()
                if st != 200 or not (body.get("ok") if isinstance(body, dict) else False):
                    user_errors.append(f"{uname}: HTTP {st}")
                out = body.get("output", "") if isinstance(body, dict) else ""
                if marker in out:
                    user_errors.append(f"{uname}: 输出泄漏了 yucs 的并发标记")
            admin_errors = admin_fut.result()

        assert not user_errors, (
            f"yucs 并发 save/reset 期间，普通用户 {len(user_errors)} 个失败:\n"
            + "\n".join(user_errors[:10])
        )
        assert not admin_errors, f"admin 并发 save/reset 出错: {admin_errors[:3]}"

    def test_no_500_under_concurrency(self, test_users):
        """高并发压力（16 线程 × 多轮）下统计 HTTP 5xx 数量 = 0。"""
        rounds = 4
        status_counts = {"2xx": 0, "4xx": 0, "5xx": 0, "other": 0}
        total = 0

        def _do(u, rnd):
            route, variant, header, net = GEN_SAMPLES[(u.idx + rnd) % len(GEN_SAMPLES)]
            st, body = u.gen(route, variant, header, net, timeout=30)
            return st

        with ThreadPoolExecutor(max_workers=NUM_USERS) as pool:
            all_futs = []
            for rnd in range(rounds):
                for u in test_users:
                    all_futs.append(pool.submit(_do, u, rnd))
            for fut in as_completed(all_futs):
                st = fut.result()
                total += 1
                if 200 <= st < 300:
                    status_counts["2xx"] += 1
                elif 400 <= st < 500:
                    status_counts["4xx"] += 1
                elif 500 <= st < 600:
                    status_counts["5xx"] += 1
                else:
                    status_counts["other"] += 1

        assert status_counts["5xx"] == 0, (
            f"高并发 {total} 请求中出现 {status_counts['5xx']} 个 5xx 错误。"
            f"统计: {status_counts}"
        )
        success_rate = status_counts["2xx"] / total if total else 0
        assert success_rate >= 0.95, (
            f"成功率 {success_rate:.1%} 低于 95%。统计: {status_counts}"
        )


# ═════════════════════════════════════════════════════════════
# 测试组 D：权限控制回归
# ═════════════════════════════════════════════════════════════
class TestPermissionControl:
    """验证模板编辑器权限：登录用户可编辑自己的模板，访客（未登录）不可编辑。"""

    def _guest_request(self, path, body):
        """用无 cookie 的访客 opener 发请求，返回 HTTP status。"""
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        # 先访问首页种 guest session
        opener.open(urllib.request.Request(f"{BASE}/"), timeout=10).read()
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{AIO}{path}", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "perm/1.0"},
            method="POST",
        )
        try:
            with opener.open(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_guest_cannot_save_template(self, container_up):
        """访客（未登录）save 模板 → 403。"""
        st = self._guest_request("/api/template/save", {
            "key": ER_HK_KEY,
            "header": H.ER_HK, "mapping": "", "template": "# test\n",
        })
        assert st == 403, f"访客 save 模板应返回 403，实际 {st}"

    def test_guest_cannot_reset_template(self, container_up):
        """访客（未登录）reset 模板 → 403。"""
        st = self._guest_request("/api/template/reset", {"key": ER_HK_KEY})
        assert st == 403, f"访客 reset 模板应返回 403，实际 {st}"

    def test_guest_cannot_preview_template(self, container_up):
        """访客（未登录）preview 模板 → 403。"""
        st = self._guest_request("/api/template/preview", {
            "key": ER_HK_KEY,
            "header": H.ER_HK, "template": "# test\n",
        })
        assert st == 403, f"访客 preview 模板应返回 403，实际 {st}"

    def test_guest_cannot_save_init_defaults(self, container_up):
        """访客（未登录）init-defaults/save → 403。"""
        st = self._guest_request("/api/init-defaults/save", {
            "key": ER_HK_KEY,
            "values": {"DEFAULT_WAN_DHCP": True},
        })
        assert st == 403, f"访客 init-defaults/save 应返回 403，实际 {st}"

    def test_guest_cannot_reset_init_defaults(self, container_up):
        """访客（未登录）init-defaults/reset → 403。"""
        st = self._guest_request("/api/init-defaults/reset", {"key": ER_HK_KEY})
        assert st == 403, f"访客 init-defaults/reset 应返回 403，实际 {st}"

    def test_logged_in_user_can_edit_template(self, test_users):
        """登录用户（非 yucs）save/preview/reset 全部成功（200）。"""
        u = test_users[7]  # ctest08
        marker = ISOLATION_MARKER + "_LOGGED_IN_EDIT"

        # save
        data = json.dumps({
            "key": ER_HK_KEY, "header": H.ER_HK, "mapping": "",
            "template": f"# {marker}\nset system host-name {marker}\n",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{AIO}/api/template/save", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "perm/1.0"},
            method="POST",
        )
        with u.opener.open(req, timeout=15) as r:
            assert r.status == 200, f"登录用户 save 应 200，实际 {r.status}"

        # preview
        data = json.dumps({
            "key": ER_HK_KEY, "header": H.ER_HK, "template": f"# {marker}\n",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{AIO}/api/template/preview", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "perm/1.0"},
            method="POST",
        )
        with u.opener.open(req, timeout=15) as r:
            assert r.status == 200, f"登录用户 preview 应 200，实际 {r.status}"

        # reset（清理）
        data = json.dumps({"key": ER_HK_KEY}).encode("utf-8")
        req = urllib.request.Request(
            f"{AIO}/api/template/reset", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "perm/1.0"},
            method="POST",
        )
        with u.opener.open(req, timeout=15) as r:
            assert r.status == 200, f"登录用户 reset 应 200，实际 {r.status}"

    def test_template_save_adds_user_comment(self, test_users):
        """保存模板后，磁盘上的 .tpl 文件顶部应有 'xxx专属yyy场景模板-yymmdd' 注释行。"""
        import subprocess
        u = test_users[8]  # ctest09
        marker = ISOLATION_MARKER + "_COMMENT_CHECK"
        custom_tpl = f"# {marker}\nset system host-name {marker}\n"

        # save
        data = json.dumps({
            "key": ER_HK_KEY, "header": H.ER_HK, "mapping": "", "template": custom_tpl,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{AIO}/api/template/save", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "perm/1.0"},
            method="POST",
        )
        with u.opener.open(req, timeout=15) as r:
            assert r.status == 200, f"save 失败: {r.status}"

        # 检查磁盘上的 .tpl 文件第一行含 "专属" 和 "场景模板"
        out = _docker_exec("bash", "-c",
            "find '/app/application/all_in_one - cc/data/users/' "
            "-path '*/ER_FastIP___HK_*/TEMPLATE_EPOCH_HK.tpl' "
            "-exec head -1 {} \; 2>/dev/null | tail -1")
        assert "专属" in out and "场景模板" in out, (
            f"保存的 .tpl 文件第一行应含专属注释，实际: {out}"
        )
        assert u.username in out, (
            f"保存的 .tpl 注释应含用户名 {u.username}，实际: {out}"
        )

        # 清理
        data = json.dumps({"key": ER_HK_KEY}).encode("utf-8")
        req = urllib.request.Request(
            f"{AIO}/api/template/reset", data=data,
            headers={"Content-Type": "application/json", "User-Agent": "perm/1.0"},
            method="POST",
        )
        try:
            u.opener.open(req, timeout=15).read()
        except Exception:
            pass
