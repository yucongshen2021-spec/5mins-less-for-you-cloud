"""8000 端口全量 API 黑盒测试。

目标：对运行中的 8000 测试容器（docker-compose.test.yml，宿主 8000 → 容器 portal 5000）
做完整 HTTP 黑盒测试，检测「应用被误删 / 不工作 / 不符合预期」。

设计原则（区别于旧 comprehensive.py）：
  1. 纯 HTTP 黑盒 —— 不 import 应用代码，验证真实部署态（容器里实际跑的版本）。
  2. 动态拉清单 —— 从 /api/tools 与 /api/scenarios 实时拉取 tool / scenario 列表，
     逐一验证。不再硬编码「==4 / ==20」计数，避免场景增删后测试过期漏检。
  3. 覆盖全链路 —— portal 首页/状态/健康/代理 + all_in_one 全部 generate 路由
     （含 epoch_fastip5）+ 全部 29 场景生成 + 模板生命周期 + 示例/备注 + 错误处理。
  4. 内测版本标识 —— 校验 8000 标题含「内测版本」。

前置：8000 容器在跑（sudo /usr/local/bin/docker-compose -f docker-compose.test.yml up -d）。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from . import headers as H

# ═════════════════════════════════════════════════════════════
# 目标端口 —— 所有测试统一打 8000（测试容器）
# ═════════════════════════════════════════════════════════════
BASE = os.environ.get("BLACKBOX_BASE", "http://127.0.0.1:8000").rstrip("/")
# all_in_one 子应用经 portal 反代访问
AIO = f"{BASE}/app/all_in_one"


def _req(method: str, url: str, *, body=None, timeout: float = 15.0, extra_headers: dict | None = None):
    """发起一次 HTTP 请求，返回 (status, json_or_text)。"""
    data = None
    headers = {"User-Agent": "blackbox-8000/1.0"}
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


def _login_as_admin() -> dict:
    """Login as yucs (template admin) and return Cookie header dict.
    密码通过环境变量 YUCS_PASSWORD 或默认值。
    """
    password = os.environ.get("YUCS_PASSWORD", "yucs123")
    st, body = _req("POST", f"{BASE}/login", body={"username": "yucs", "password": password})
    if st != 200 or not body.get("ok"):
        raise RuntimeError(f"Login as yucs failed: {body}")
    # Extract session cookie from response headers
    # The portal sets a session cookie; we need to capture it
    # Re-implement with http.cookiejar to capture cookies properly
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    data = json.dumps({"username": "yucs", "password": password}).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/login", data=data,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "blackbox-8000/1.0"})
    with opener.open(req, timeout=15.0) as r:
        r.read()
    # Extract cookie header from cookie jar
    cookie_header = ""
    for cookie in cj:
        if cookie.name == "session":
            cookie_header = f"session={cookie.value}"
            break
    if not cookie_header:
        raise RuntimeError("Could not extract session cookie from login response")
    return {"Cookie": cookie_header}


# Module-level admin cookie (lazy init)
_admin_cookie: dict | None = None


def _get_admin_cookie() -> dict:
    global _admin_cookie
    if _admin_cookie is None:
        _admin_cookie = _login_as_admin()
    return _admin_cookie


def _admin_post(url, body, **kw):
    """POST as yucs (template admin)."""
    return _req("POST", url, body=body, extra_headers=_get_admin_cookie(), **kw)


def _admin_get(url, **kw):
    """GET as yucs (template admin)."""
    return _req("GET", url, extra_headers=_get_admin_cookie(), **kw)


def _get(url, **kw):
    return _req("GET", url, **kw)


def _post(url, body, **kw):
    return _req("POST", url, body=body, **kw)


# ═════════════════════════════════════════════════════════════
# session 级：拉取真实清单，供后续用例参数化
# ═════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def catalog():
    """从容器实时拉取 tools / scenarios / scenarios 全量清单。"""
    st, tools_resp = _get(f"{AIO}/api/tools")
    assert st == 200, f"/api/tools 返回 {st}"
    tools = tools_resp["tools"]
    assert tools, "/api/tools 返回空 tools 列表"

    st, sc_resp = _get(f"{AIO}/api/scenarios")
    assert st == 200, f"/api/scenarios 返回 {st}"
    scenarios = sc_resp["scenarios"]
    assert scenarios, "/api/scenarios 返回空场景列表"

    return {"tools": tools, "scenarios": scenarios}


# ═════════════════════════════════════════════════════════════
# 1. Portal 层（首页 / 状态 / 健康 / 反代 / 内测标识）
# ═════════════════════════════════════════════════════════════
class TestPortal:
    def test_index_200(self):
        st, body = _get(f"{BASE}/")
        assert st == 200
        assert isinstance(body, str) and body.strip()

    def test_index_has_beta_label(self):
        """8000 测试容器标题必须注明「内测版本」。"""
        st, body = _get(f"{BASE}/")
        assert st == 200
        assert "内测版本" in body, "首页未出现「内测版本」标识"
        assert "ver-badge beta" in body or "内测" in body, "未渲染内测徽章"

    def test_health_ok(self):
        st, body = _get(f"{BASE}/api/health")
        assert st == 200
        assert body["ok"] is True

    def test_status_lists_all_in_one(self):
        """/api/status 至少含 all_in_one 且 reachable。"""
        st, body = _get(f"{BASE}/api/status")
        assert st == 200
        ids = {a["id"] for a in body}
        assert "all_in_one" in ids, f"all_in_one 不在 status 列表: {ids}"
        aio = next(a for a in body if a["id"] == "all_in_one")
        assert aio["reachable"], f"all_in_one 不可达: {aio}"

    def test_proxy_passes_through(self):
        """portal 反代 all_in_one 的 API 应正常透传。"""
        st, body = _get(f"{AIO}/api/scenarios")
        assert st == 200
        assert isinstance(body, dict) and "scenarios" in body


# ═════════════════════════════════════════════════════════════
# 2. all_in_one 元数据 API —— 校验清单完整、无漂移
# ═════════════════════════════════════════════════════════════
class TestCatalog:
    def test_tools_count_stable(self, catalog):
        """5 个 tool（epoch_fastip / usg_fastip / epoch_mpls / ar_sdwan / ar_traditional）。

        epoch_fastip5 是 epoch_fastip 的 5.0 版本切换，不作为独立 tool 暴露——
        若此处断言失败，说明 tool 被误删或新增未同步。
        """
        ids = {t["id"] for t in catalog["tools"]}
        expect = {"epoch_fastip", "usg_fastip", "epoch_mpls", "ar_sdwan", "ar_traditional"}
        missing = expect - ids
        extra = ids - expect
        assert not missing, f"tool 缺失（疑似误删）: {missing}"
        assert not extra, f"出现未预期 tool（需同步测试）: {extra}"

    def test_each_tool_has_variants(self, catalog):
        for t in catalog["tools"]:
            assert t.get("variants"), f"tool {t['id']} 无 variants"
            for v in t["variants"]:
                assert v.get("id") and v.get("name"), f"tool {t['id']} variant 缺字段: {v}"

    def test_scenarios_nonempty(self, catalog):
        assert len(catalog["scenarios"]) >= 20, \
            f"场景数异常少（疑似误删）: {len(catalog['scenarios'])}"

    def test_scenarios_all_have_required_fields(self, catalog):
        for s in catalog["scenarios"]:
            assert s.get("key"), f"场景缺 key: {s}"
            assert s.get("source"), f"场景 {s['key']} 缺 source"
            assert s.get("tpl_slot"), f"场景 {s['key']} 缺 tpl_slot"

    def test_scenario_tree_matches_list(self, catalog):
        """场景树叶子数 == 扁平 list 数（启动校验 _validate_scenario_tree 的运行时复检）。"""
        # /api/scenarios 返回扁平 list；此处仅校验非空且字段齐全（树校验在 import 期已做）
        keys = [s["key"] for s in catalog["scenarios"]]
        assert len(keys) == len(set(keys)), "场景 key 有重复"


# ═════════════════════════════════════════════════════════════
# 3. 全场景生成 —— 每个 generate 路由 × 每个 variant
# ═════════════════════════════════════════════════════════════
# (route, variant, header, network, output_key, min_lines, must_contain)
# route 含 epoch_fastip5（5.0 版本，不暴露在 /api/tools 但有独立路由）。
# 注意几个 5.0 变体的输入约定（与前端 gn5 一致）：
#   - us_ipsec：variant 仍是 "us"，靠 network.tunnel_type="ipsec" 切换
#   - new_exit：需 network 提供 NAT rule 默认值，否则 span 校验报错
#   - domain_split：域名放 network.ER5_DS_DOMAINS_DEFAULT（5.0）/ header_text（4.0）
GEN_CASES = [
    # ── ER FastIP 4.0 ──
    ("epoch_fastip", "hk", H.ER_HK, {}, "output", 200, ["set epoch", "set system host-name"]),
    ("epoch_fastip", "us", H.ER_US, {}, "output", 250, ["set epoch", "set system host-name"]),
    ("epoch_fastip", "flink", H.ER_FLINK, {}, "output", 3, ["set protocols"]),
    ("epoch_fastip", "new_exit", H.ER_NEW_EXIT, {}, "output", 10, ["set interfaces tunnel"]),
    ("epoch_fastip", "domain_split", H.ER_DOMAIN_SPLIT, {}, "output", 5, ["set protocols static"]),
    # ── ER FastIP 5.0（独立路由；HK/domain_split 用 MAIN 格式数据头）──
    ("epoch_fastip5", "hk", H.ER5_HK, {}, "output", 200, ["set interfaces", "set system"]),
    ("epoch_fastip5", "us", H.ER5_US, {}, "output", 200, ["set interfaces", "set system"]),
    ("epoch_fastip5", "us", H.ER5_US_IPSEC, {"tunnel_type": "ipsec"}, "output", 50, ["ipsec"]),
    ("epoch_fastip5", "flink", H.ER5_FLINK, {}, "output", 3, ["set protocols"]),
    ("epoch_fastip5", "new_exit", H.ER5_NEW_EXIT,
     {"ER5_NE_MAIN_NAT_RULE_DEFAULT": "1001", "ER5_NE_BK_NAT_RULE_DEFAULT": "2001",
      "ER5_NE_FNET_NAT_RULE_DEFAULT": "3001"}, "output", 10, ["set interfaces tunnel"]),
    ("epoch_fastip5", "domain_split", "",
     {"ER5_DS_DOMAINS_DEFAULT": "google.com\nyoutube.com"}, "output", 5, ["domain-list"]),
    # ── USG FastIP ──
    ("usg_fastip", "us", H.USG_US, {}, "output", 100, ["set firewall", "ip address"]),
    ("usg_fastip", "hk", H.USG_US, {}, "output", 100, ["set firewall", "ip address"]),
    ("usg_fastip", "flink", H.USG_FLINK, {}, "output", 20, ["interface Tunnel"]),
    ("usg_fastip", "new_exit", H.USG_NEW_EXIT, {}, "output", 10, ["interface Tunnel"]),
    # ── Epoch MPLS ──
    ("epoch_mpls", "domestic", H.MPLS_CN, {}, "output", 60, ["set firewall", "set protocols bgp"]),
    ("epoch_mpls", "overseas", H.MPLS_CN, {}, "output", 60, ["set firewall", "set protocols bgp"]),
    ("epoch_mpls", "ipsec", H.MPLS_CN, {}, "output", 100, ["set firewall"]),
    # ── AR SD-WAN（ops_output / factory_output 双输出）──
    ("ar_sdwan", "single_ops", H.AR_SDWAN, {}, "ops_output", 50, ["import ops", "def ops_condition"]),
    ("ar_sdwan", "single_factory", H.AR_SDWAN, {}, "factory_output", 30, ["ip vpn-instance"]),
    ("ar_sdwan", "dual_ops_pri", H.AR_SDWAN, {}, "ops_output", 30, ["import ops"]),
    ("ar_sdwan", "dual_ops_bak", H.AR_SDWAN, {}, "ops_output", 30, ["import ops"]),
    # ── AR 传统组网（华为 VRP 语法：sysname / bgp）──
    ("ar_traditional", "dual", H.AR_TRADITIONAL, {}, "output", 50, ["sysname", "bgp"]),
]


@pytest.mark.parametrize(
    "route,variant,header,network,out_key,min_lines,must_contain",
    GEN_CASES,
    ids=[f"{r}/{v}" for r, v, *_ in GEN_CASES],
)
def test_generate_all_scenarios(route, variant, header, network, out_key, min_lines, must_contain):
    """全场景生成：每个 generate 路由 × variant 必须返回非空配置、含关键字、行数合理。"""
    st, body = _post(
        f"{AIO}/api/generate/{route}",
        {"variant": variant, "header_text": header, "network": network},
    )
    assert st == 200, f"/api/generate/{route} variant={variant} 返回 HTTP {st}: {body}"
    assert body.get("ok") is True, \
        f"/api/generate/{route} variant={variant} ok=False: {body.get('error')}"
    out = body.get(out_key, "") or body.get("output", "")
    assert out.strip(), f"/api/generate/{route} variant={variant} 输出为空"
    lines = len(out.splitlines())
    assert lines >= min_lines, \
        f"/api/generate/{route} variant={variant} 行数 {lines} < 期望 {min_lines}"
    missing = [k for k in must_contain if k not in out]
    assert not missing, \
        f"/api/generate/{route} variant={variant} 缺关键字 {missing}"


# ═════════════════════════════════════════════════════════════
# 4. 网络参数注入 —— 参数变化必须反映到输出
# ═════════════════════════════════════════════════════════════
class TestNetworkParams:
    def _gen(self, tool, variant, header, network):
        st, body = _post(
            f"{AIO}/api/generate/{tool}",
            {"variant": variant, "header_text": header, "network": network},
        )
        assert st == 200 and body.get("ok"), f"生成失败: {body}"
        return body.get("output", "")

    def test_wan_ip_reflected(self):
        a = self._gen("epoch_fastip", "hk", H.ER_HK, {"wan_cidr": "192.168.1.10/24"})
        b = self._gen("epoch_fastip", "hk", H.ER_HK, {"wan_cidr": "99.99.99.1/24"})
        assert a != b, "WAN IP 变化未反映到输出"
        assert "192.168.1.10" in a
        assert "99.99.99" in b

    def test_dhcp_toggle_changes_output(self):
        a = self._gen("epoch_fastip", "hk", H.ER_HK, {"wan_dhcp": True, "lan_dhcp": True})
        b = self._gen("epoch_fastip", "hk", H.ER_HK, {"wan_dhcp": False, "lan_dhcp": False})
        assert a != b, "DHCP 开关未反映到输出"

    def test_inner_nets_reflected(self):
        a = self._gen("epoch_fastip", "hk", H.ER_HK, {"inner_nets": "10.10.10.0/24"})
        b = self._gen("epoch_fastip", "hk", H.ER_HK, {"inner_nets": "172.16.0.0/12"})
        assert "10.10.10" in a
        assert "172.16.0" in b

    def test_bypass_toggle_changes_output(self):
        for tool, variant, hdr in [
            ("epoch_fastip", "hk", H.ER_HK),
            ("epoch_mpls", "domestic", H.MPLS_CN),
        ]:
            a = self._gen(tool, variant, hdr, {"bypass": True})
            b = self._gen(tool, variant, hdr, {"bypass": False})
            assert a != b, f"{tool}/{variant} 旁挂开关未反映到输出"


# ═════════════════════════════════════════════════════════════
# 5. 模板生命周期 —— save / generate / reset，全场景覆盖
# ═════════════════════════════════════════════════════════════
MARKER = "BLACKBOX_MARKER_8k_6a3f"


def test_template_load_all_scenarios(catalog):
    """每个场景都能 load 出非空 header + template（检测数据目录文件误删）。"""
    for s in catalog["scenarios"]:
        st, body = _admin_post(f"{AIO}/api/template/load", {"key": s["key"]})
        assert st == 200, f"load {s['key']} 返回 {st}"
        assert body.get("ok"), f"load {s['key']} ok=False"
        assert body.get("header", "").strip(), f"load {s['key']} header 为空"
        assert len(body.get("template", "")) > 0, f"load {s['key']} template 为空"


# 场景 key → (route, variant, header, out_key) 用于自定义模板生成验证
# 注意：AR SD-WAN 不在此列，因其 generate 直接从模块 ns 读模板，不走磁盘模板系统
TPL_VERIFY = {
    "Epoch FastIP · HK 香港出口": ("epoch_fastip", "hk", H.ER_HK, "output"),
    "USG FastIP · 非香港出口": ("usg_fastip", "us", H.USG_US, "output"),
    "Epoch MPLS · 国内配置": ("epoch_mpls", "domestic", H.MPLS_CN, "output"),
    "AR 传统组网 · 双线": ("ar_traditional", "dual", H.AR_TRADITIONAL, "output"),
}


@pytest.mark.parametrize("key,gen", list(TPL_VERIFY.items()))
def test_template_lifecycle(key, gen):
    """save 自定义模板 → 生成含标记 → reset → 生成不含标记。需要 yucs 权限。"""
    route, variant, header, out_key = gen
    custom = f"# {MARKER}\nset system host-name {MARKER}\n"

    # save (as admin)
    st, body = _admin_post(
        f"{AIO}/api/template/save",
        {"key": key, "header": header, "mapping": "", "template": custom},
    )
    assert st == 200 and body.get("ok"), f"save {key} 失败: {body}"

    # generate with custom (must use same user who saved — yucs)
    st, body = _admin_post(
        f"{AIO}/api/generate/{route}",
        {"variant": variant, "header_text": header, "network": {}},
    )
    out = body.get(out_key, "") or body.get("output", "")
    assert MARKER in out, f"save 后生成 {key} 不含自定义标记"

    # reset (as admin)
    st, body = _admin_post(f"{AIO}/api/template/reset", {"key": key})
    assert st == 200 and body.get("ok"), f"reset {key} 失败: {body}"
    assert len(body.get("template", "")) > 50, f"reset {key} 返回的模板过短"

    # generate after reset (must use same user)
    st, body = _admin_post(
        f"{AIO}/api/generate/{route}",
        {"variant": variant, "header_text": header, "network": {}},
    )
    out = body.get(out_key, "") or body.get("output", "")
    assert MARKER not in out, f"reset 后生成 {key} 仍含自定义标记"


def test_template_preview():
    """preview 不落盘，但能渲染出自定义标记。需要 yucs 权限。"""
    key = "Epoch FastIP · HK 香港出口"
    custom = f"# PREVIEW_{MARKER}\nset system host-name PREVIEW\n"
    st, body = _admin_post(
        f"{AIO}/api/template/preview",
        {"key": key, "header": H.ER_HK, "template": custom},
    )
    assert st == 200 and body.get("ok"), f"preview 失败: {body}"
    assert f"PREVIEW_{MARKER}" in body.get("output", "")


# ═════════════════════════════════════════════════════════════
# 6. 示例 & 备注 —— 每个 tool/variant 都能加载
# ═════════════════════════════════════════════════════════════
def test_examples_all_tools(catalog):
    """每个 tool 的每个 variant 都能加载非空示例（检测 _EXAMPLE_MAP 缺失）。"""
    for t in catalog["tools"]:
        for v in t["variants"]:
            st, body = _admin_get(f"{AIO}/api/examples/{t['id']}/{v['id']}")
            assert st == 200, f"/api/examples/{t['id']}/{v['id']} 返回 {st}"
            assert body.get("ok"), \
                f"/api/examples/{t['id']}/{v['id']} ok=False: {body.get('error')}"
            assert len(body.get("example", "")) > 20, \
                f"/api/examples/{t['id']}/{v['id']} example 过短"


def test_notes_all_tools(catalog):
    """每个 tool 都能加载备注。"""
    for t in catalog["tools"]:
        v = t["variants"][0]["id"]
        st, body = _admin_get(f"{AIO}/api/notes/{t['id']}?variant={v}")
        assert st == 200, f"/api/notes/{t['id']} 返回 {st}"
        assert body.get("ok"), f"/api/notes/{t['id']} ok=False"
        assert len(body.get("notes", "")) > 20, f"/api/notes/{t['id']} notes 过短"


# epoch_fastip5 不在 /api/tools，单独验证其示例/备注。
# us_ipsec 是 example 映射 key（取数据头用），generate 时 variant=us+tunnel_type。
@pytest.mark.parametrize(
    "variant",
    ["hk", "us", "us_ipsec", "flink", "new_exit", "domain_split"],
)
def test_examples_epoch_fastip5(variant):
    st, body = _admin_get(f"{AIO}/api/examples/epoch_fastip5/{variant}")
    assert st == 200, f"/api/examples/epoch_fastip5/{variant} 返回 {st}"
    assert body.get("ok"), f"epoch_fastip5/{variant} 示例 ok=False: {body.get('error')}"
    assert len(body.get("example", "")) > 20, f"epoch_fastip5/{variant} 示例为空（数据丢失）"


# ═════════════════════════════════════════════════════════════
# 7. 错误处理 —— 失败必须显式返回错误，禁止兜底
# ═════════════════════════════════════════════════════════════
class TestErrorHandling:
    def test_empty_header_returns_error(self):
        """空数据头必须显式返回错误 JSON（proxy 不得吞 4xx body）。"""
        st, body = _post(
            f"{AIO}/api/generate/epoch_fastip",
            {"variant": "hk", "header_text": "", "network": {}},
        )
        assert st == 400, f"空 header 应 400, 实际 {st}"
        assert isinstance(body, dict), f"4xx 应返回 JSON, 实际 {type(body)}"
        assert not body.get("ok"), "空数据头应返回 ok=False"
        assert body.get("error"), "空数据头应返回非空 error 文案"

    def test_invalid_variant_returns_error(self):
        st, body = _post(
            f"{AIO}/api/generate/epoch_fastip",
            {"variant": "xyz_not_exist", "header_text": "test", "network": {}},
        )
        assert st in (400, 500)
        assert isinstance(body, dict), "错误响应必须是 JSON"
        assert not body.get("ok"), "无效 variant 应返回 ok=False"

    def test_unknown_template_key_returns_error(self):
        st, body = _admin_post(f"{AIO}/api/template/load", {"key": "不存在的场景__xxx"})
        assert st in (200, 404)
        assert not body.get("ok"), "未知场景 key 应返回 ok=False"

    def test_proxy_preserves_4xx_body(self):
        """回归：portal proxy 不得吞掉 4xx 响应 body（曾因 e.read() 双读导致空 body）。"""
        st, body = _post(
            f"{AIO}/api/generate/epoch_fastip",
            {"variant": "hk", "header_text": "", "network": {}},
        )
        assert st == 400
        assert isinstance(body, dict) and body.get("error"), \
            "经 portal 反代后 4xx 错误体被吞空（proxy e.read() 双读 bug 回归）"


# ═════════════════════════════════════════════════════════════
# 8. 初始化默认值持久化
# ═════════════════════════════════════════════════════════════
def test_init_defaults_get():
    st, body = _admin_get(f"{AIO}/api/init-defaults")
    assert st == 200
    assert body.get("ok")
    assert body.get("defaults"), "/api/init-defaults 返回空 defaults"


def test_init_defaults_lifecycle():
    """save → get → reset，验证 init-defaults 链路工作。需要 yucs 权限。"""
    key = "Epoch FastIP · HK 香港出口"
    st, body = _admin_post(
        f"{AIO}/api/init-defaults/save",
        {"key": key, "values": {"DEFAULT_WAN_DHCP": True, "DEFAULT_LAN_DHCP": True}},
    )
    assert st == 200 and body.get("ok"), f"init-defaults save 失败: {body}"

    st, body = _admin_post(f"{AIO}/api/init-defaults/reset", {"key": key})
    assert st == 200 and body.get("ok"), f"init-defaults reset 失败: {body}"


# ═════════════════════════════════════════════════════════════
# 9. 赞助榜单（独立 API）
# ═════════════════════════════════════════════════════════════
def test_sponsor_board():
    st, body = _get(f"{AIO}/api/sponsor-board")
    assert st == 200
    assert body.get("ok")
    assert "赞助榜单" in str(body.get("board", {}))


# ═════════════════════════════════════════════════════════════
# 入口：允许直接 python 运行（不依赖 pytest collection 也能跑）
# ═════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # 简易连通性自检，便于排错
    st, _ = _get(f"{BASE}/api/health")
    if st != 200:
        print(f"[FATAL] 8000 端口不可达 (status={st})，请先启动测试容器：")
        print("  sudo /usr/local/bin/docker-compose -f docker-compose.test.yml up -d")
        raise SystemExit(1)
    print(f"[OK] 8000 健康检查通过，开始 pytest collection")
    pytest.main([__file__, "-v", "--tb=short"])
