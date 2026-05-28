"""ER MPLS 模板回归：
1. 旁挂模式下不应残留字面量 't'（来自历史 typo `t{lan_if_block}`）。
2. `set policy prefix-list ...` / `set service dhcp-server ...` 行首不应有空格/TAB
   （历史 typo: `\\t{prefix_list_block}` / `\\t{dhcp_server_block}`）。
3. 用户在 Hostname 输入框填的值应该被采纳，而不是被 LineID 前缀覆盖。
"""
from common import *
import common as cm


def _run(c, variant, header, network):
    return c.post("/api/generate/epoch_mpls", json={
        "variant": variant,
        "header_text": header,
        "network": network,
    }).get_json()


def _assert_no_stray_t(output: str, label: str):
    for i, line in enumerate(output.splitlines()):
        assert line.strip() != "t", f"{label}: 输出第{i+1}行残留字面 t"
    assert "tset interfaces" not in output, f"{label}: 输出含 'tset interfaces'"


def _assert_no_indent_before(output: str, prefix: str, label: str):
    """断言以 `prefix` 开头的 set 命令所在行行首没有多余的空白。"""
    for i, line in enumerate(output.splitlines()):
        stripped = line.lstrip()
        if stripped.startswith(prefix) and line != stripped:
            raise AssertionError(
                f"{label}: 第{i+1}行 '{prefix}' 之前有多余空白: {repr(line)}"
            )


def _assert_hostname(output: str, expected: str, label: str):
    needle_a = f"set system host-name '{expected}'"
    needle_b = f"set openfalcon endpoint-name '{expected}'"
    assert needle_a in output, f"{label}: 未找到 host-name '{expected}'"
    assert needle_b in output, f"{label}: 未找到 openfalcon endpoint-name '{expected}'"


def test():
    with app.test_client() as c:
        # ──────────────────────────────────────────────
        # 旁挂模式：原有 't' 残留 + 新增 prefix-list 空格断言
        # ──────────────────────────────────────────────
        for variant, header in (("domestic", MPLS_CN), ("overseas", MPLS_OV)):
            r = _run(c, variant, header, {
                "bypass": True, "wan_ip": "172.16.100.5/24", "wan_gw": "172.16.100.1",
                "gen_return_route": True,
            })
            t(f"MPLS {variant} 旁挂 ok", lambda r=r: (
                ok(r) or (_ for _ in ()).throw(AssertionError(r.get("error", "")))
            ))
            o = r.get("output", "")
            t(f"MPLS {variant} 旁挂 无残留 t",
              lambda o=o, v=variant: _assert_no_stray_t(o, v))
            t(f"MPLS {variant} 旁挂 prefix-list 行首无空白",
              lambda o=o, v=variant: _assert_no_indent_before(o, "set policy prefix-list", v))

        # ──────────────────────────────────────────────
        # 非旁挂 + 默认 DHCP 服务：dhcp-server 行首无空白
        # ──────────────────────────────────────────────
        for variant, header in (("domestic", MPLS_CN), ("overseas", MPLS_OV)):
            r = _run(c, variant, header, {
                "wan_dhcp": False, "lan_dhcp": True, "bypass": False,
                "gen_return_route": True,
            })
            t(f"MPLS {variant} 非旁挂 ok", lambda r=r: (
                ok(r) or (_ for _ in ()).throw(AssertionError(r.get("error", "")))
            ))
            o = r.get("output", "")
            t(f"MPLS {variant} 非旁挂 prefix-list 行首无空白",
              lambda o=o, v=variant: _assert_no_indent_before(o, "set policy prefix-list", v))
            t(f"MPLS {variant} 非旁挂 dhcp-server 行首无空白",
              lambda o=o, v=variant: _assert_no_indent_before(o, "set service dhcp-server", v))

        # ──────────────────────────────────────────────
        # Hostname 来源：用户输入框值必须生效
        # ──────────────────────────────────────────────
        for variant, header in (("domestic", MPLS_CN), ("overseas", MPLS_OV), ("ipsec", None)):
            hdr = header if header is not None else MPLS_CN
            user_hostname = f"CUSTOM-CE-{variant.upper()}"
            r = _run(c, variant, hdr, {"hostname": user_hostname})
            t(f"MPLS {variant} 自定义 Hostname ok", lambda r=r: (
                ok(r) or (_ for _ in ()).throw(AssertionError(r.get("error", "")))
            ))
            o = r.get("output", "")
            t(f"MPLS {variant} 采用自定义 Hostname",
              lambda o=o, h=user_hostname, v=variant: _assert_hostname(o, h, v))


if __name__ == "__main__":
    test()
    total = cm.PASS + cm.FAIL
    print(f"\nMPLS 旁挂/格式/Hostname 测试: {cm.PASS}/{total} 通过, {cm.FAIL} 失败")
    save_report("mpls_bypass")
