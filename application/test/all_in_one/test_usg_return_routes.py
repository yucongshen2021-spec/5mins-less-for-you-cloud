"""USG 回程路由生成逻辑回归：
- 任意 inner_nets（含 LAN 直连网段）都必须生成 `ip route-static`，不再过滤
- 输出里不允许出现 `#额外内网段回程路由` 标题注释
- 输出里不允许出现行尾 `  #回程: ...` 注释
覆盖 web API 路径（USG HK / US）和桌面 GUI 路径（generate_config_us）。
"""
from common import *
import common as cm
import ipaddress


HK_HEADER = (
    "main IPSEC_PE: bja-ape1\nmain dial_ip: 118.193.100.10\nmain loopback: 10.18.5.13\n"
    "main auth_id: 608810A10\nmain psk: both-win\n\n"
    "LineID:608810A10\nPE:hkg1-fgpe3\nWANIP:10.22.98.40/30\nTUNNEL:tun1040\n"
    "PE对接:10.255.110.48\nCE对接:10.18.5.13\n出口ip:103.91.158.227"
)

US_HEADER = (
    "main IPSEC_PE: szd-ape2\nmain dial_ip: 121.14.82.235\nmain loopback: 10.18.12.57\n"
    "main auth_id: 609157A1\nmain psk: both-win\n\n"
    "LineID:609157A1\nPE:lax1-fgpe1\nWANIP:10.22.98.40/30\nTUNNEL:tun1213\n"
    "PE对接:10.255.110.6\nCE对接:10.18.12.57\n出口ip:64.81.158.21"
)

LAN_CIDR = "192.168.8.1/24"
LAN_GW   = "192.168.8.1"
LAN_NET  = "192.168.8.0/24"
EXTRA_INNER = "10.0.0.0/8"


def _gen(c, variant, header, network):
    return c.post("/api/generate/usg_fastip", json={
        "variant": variant,
        "header_text": header,
        "network": network,
    }).get_json()


def _assert_route(output, net_cidr, nexthop, label):
    net = ipaddress.ip_network(net_cidr, strict=False)
    needle = f"ip route-static {net.network_address} {net.netmask} {nexthop}"
    if needle not in output:
        raise AssertionError(f"{label}: 缺少回程路由 `{needle}`")


def _assert_no(output, needle, label):
    if needle in output:
        raise AssertionError(f"{label}: 输出不应包含 {needle!r}")


def test_web_hk_includes_lan_segment_and_drops_comments():
    with app.test_client() as c:
        r = _gen(c, "hk", HK_HEADER, {
            "lan_cidr": LAN_CIDR,
            "lan_gw":   LAN_GW,
            "inner_nets": f"{LAN_NET}\n{EXTRA_INNER}",
            "gen_return_route": True,
        })
        assert ok(r), f"USG HK 生成失败: {r.get('error', '')}"
        o = out(r)
        _assert_route(o, LAN_NET,     LAN_GW, "USG HK")
        _assert_route(o, EXTRA_INNER, LAN_GW, "USG HK")
        _assert_no(o, "#额外内网段回程路由", "USG HK")
        _assert_no(o, "#回程:",           "USG HK")


def test_web_us_includes_lan_segment_and_drops_comments():
    with app.test_client() as c:
        r = _gen(c, "us", US_HEADER, {
            "lan_cidr": LAN_CIDR,
            "lan_gw":   LAN_GW,
            "inner_nets": f"{LAN_NET}\n{EXTRA_INNER}",
            "gen_return_route": True,
        })
        assert ok(r), f"USG US 生成失败: {r.get('error', '')}"
        o = out(r)
        _assert_route(o, LAN_NET,     LAN_GW, "USG US")
        _assert_route(o, EXTRA_INNER, LAN_GW, "USG US")
        _assert_no(o, "#额外内网段回程路由", "USG US")
        _assert_no(o, "#回程:",           "USG US")


def test_desktop_generate_config_us_includes_lan_segment_and_drops_comments():
    """桌面 GUI 入口 generate_config_us 也必须同步去掉过滤与注释。"""
    usg = _load_module("usg_fastip_3in1_v5.py")
    # 关掉 field_coverage，防止 generate_config_us 在末尾弹模态 messagebox
    usg["field_coverage"] = None
    generate_config_us  = usg["generate_config_us"]
    build_us_fmt        = usg["build_usg_us_format_dict"]
    d, err = build_us_fmt(US_HEADER)
    if err:
        raise AssertionError(f"build_usg_us_format_dict 失败: {err}")
    fields = {
        "wan_ip":   "10.10.10.2",   "wan_mask": "255.255.255.252",
        "wan_gw":   "10.10.10.1",   "wan_eth":  "GE0/0/9",
        "lan_ip":   LAN_GW,         "lan_mask": "255.255.255.0",
        "lan_eth":  "GE0/0/8",
        "dns1":     "10.255.108.7", "dns2":     "10.255.108.58",
        "parsed":   d,
    }
    inner_raw = f"{LAN_NET}\n{EXTRA_INNER}"
    cfg = generate_config_us(fields, wan_dhcp=False,
                             extra_subnets_raw=inner_raw,
                             return_route_nexthop=LAN_GW,
                             dhcp_en=False)
    _assert_route(cfg, LAN_NET,     LAN_GW, "desktop US")
    _assert_route(cfg, EXTRA_INNER, LAN_GW, "desktop US")
    _assert_no(cfg, "#额外内网段回程路由", "desktop US")
    _assert_no(cfg, "#回程:",           "desktop US")


def test_build_extra_return_routes_helper_has_no_comments():
    """helper 本身不再写注释。"""
    usg = _load_module("usg_fastip_3in1_v5.py")
    build_extra_return_routes = usg["build_extra_return_routes"]
    subs = [
        ("192.168.8.0", "255.255.255.0", "192.168.8.0/24"),
        ("10.0.0.0",    "255.0.0.0",    "10.0.0.0/8"),
    ]
    out_str = build_extra_return_routes(subs, "192.168.8.1")
    _assert_no(out_str, "#额外内网段回程路由", "helper")
    _assert_no(out_str, "#回程:", "helper")
    if "ip route-static 192.168.8.0 255.255.255.0 192.168.8.1" not in out_str:
        raise AssertionError("helper: 缺少 LAN 直连网段回程路由")
    if "ip route-static 10.0.0.0 255.0.0.0 192.168.8.1" not in out_str:
        raise AssertionError("helper: 缺少额外内网段回程路由")
    if build_extra_return_routes([], "192.168.8.1") != "":
        raise AssertionError("helper: 空列表应返回空字符串")


def main():
    t("USG HK · LAN 直连网段也回程 + 无 # 注释",
      test_web_hk_includes_lan_segment_and_drops_comments)
    t("USG US · LAN 直连网段也回程 + 无 # 注释",
      test_web_us_includes_lan_segment_and_drops_comments)
    t("桌面 generate_config_us · LAN 直连网段也回程 + 无 # 注释",
      test_desktop_generate_config_us_includes_lan_segment_and_drops_comments)
    t("build_extra_return_routes 不再产生 # 注释",
      test_build_extra_return_routes_helper_has_no_comments)


if __name__ == "__main__":
    main()
    total = cm.PASS + cm.FAIL
    print(f"\nUSG 回程路由回归: {cm.PASS}/{total} 通过, {cm.FAIL} 失败")
    save_report("usg_return_routes")
