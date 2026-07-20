#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Epoch FastIP 配置生成工具 v8.0
  v7 基础上 v8.0 新增：
    ⑫ 是否旁挂：初始化选项（与 LAN DHCP 同行）
        - 旁挂时：不生成 LAN 接口，LAN 口/DHCP/LAN IP/LAN网关 全部变灰
        - 内网段判断改为以 WAN 口为准：内网段与 WAN 不同网段时，生成下一跳为 WAN 网关的回程路由
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import re, ipaddress

try:
    import field_coverage
except ImportError:
    field_coverage = None  # type: ignore

try:
    from field_coverage import inject_er_netpanel_init_aliases
except ImportError:
    def inject_er_netpanel_init_aliases(_d: dict) -> None:  # type: ignore[misc]
        pass

try:
    from user_activity_log import log_generate_config
except ImportError:
    def log_generate_config(**_kwargs):  # type: ignore[misc]
        pass

# =====================================================================
# 公共工具（运行于 all_in_one_v2 时由 shared_utils 注入；独立运行时使用本地副本）
# =====================================================================
try:
    _get  # 已由 all_in_one_v2 注入
except NameError:
    def _get(pattern, block, flags=re.IGNORECASE | re.MULTILINE):
        m = re.search(pattern, block, flags)
        return m.group(1).strip() if m else ""

    def wanip_hosts(cidr):
        """从 CIDR 中返回前两个可用主机 IP。返回 (PE侧=奇数, CE侧=偶数)。"""
        try:
            hosts = list(ipaddress.ip_network(cidr.strip(), strict=False).hosts())
            if len(hosts) >= 2:
                return str(hosts[0]), str(hosts[1])
        except (ValueError, ipaddress.AddressValueError):
            pass
        return "", ""

    def _parse_inner_nets(raw):
        """解析多行/逗号分隔的内网段，返回合法 CIDR 列表。"""
        nets = []
        for token in re.split(r'[\n,，\s]+', raw or ""):
            s = token.strip()
            if not s:
                continue
            try:
                nets.append(str(ipaddress.ip_network(s, strict=False)))
            except (ValueError, ipaddress.AddressValueError):
                pass
        return nets

    # v8：按"直连网段"判断是否需要回程路由
    def _nets_needing_return_by_network(base_cidr, inner_nets):
        try:
            base = ipaddress.ip_network(base_cidr, strict=False)
        except (ValueError, ipaddress.AddressValueError):
            return inner_nets
        res = []
        for s in inner_nets:
            try:
                net = ipaddress.ip_network(s, strict=False)
                if net != base:
                    res.append(s)
            except (ValueError, ipaddress.AddressValueError):
                res.append(s)
        return res


# =====================================================================
# v6：网络格式校验（符合网络标准才允许生成）
# =====================================================================
def _validate_cidr(value, name="CIDR"):
    """校验 CIDR（如 192.168.1.0/24）。返回 (True, None) 或 (False, 错误说明)。"""
    if not value or not value.strip():
        return True, None
    s = value.strip()
    try:
        net = ipaddress.ip_network(s, strict=False)
    except ValueError as e:
        return False, f"{name}「{s}」格式错误：{e}"
    try:
        plen = net.prefixlen
    except Exception:
        plen = -1
    if plen < 0 or plen > 32:
        return False, f"{name}「{s}」掩码长度须为 0～32，当前无效（如 /33 等）"
    return True, None


def _validate_ip(value, name="IP"):
    """校验单个 IPv4 地址（如 192.168.1.1）。返回 (True, None) 或 (False, 错误说明)。"""
    if not value or not value.strip():
        return True, None
    s = value.strip()
    try:
        ipaddress.ip_address(s)
    except ValueError as e:
        return False, f"{name}「{s}」格式错误：{e}（每段须 0～255）"
    return True, None


def _validate_inner_nets(raw):
    """校验内网段多行输入。返回 (合法 CIDR 列表, 错误列表 [(输入片段, 说明), ...])。"""
    nets = []
    errors = []
    for token in re.split(r'[\n,，\s]+', raw or ""):
        s = token.strip()
        if not s:
            continue
        try:
            net = ipaddress.ip_network(s, strict=False)
            if net.prefixlen < 0 or net.prefixlen > 32:
                errors.append((s, "掩码长度须为 0～32"))
            else:
                nets.append(str(net))
        except ValueError as e:
            errors.append((s, str(e)))
    return nets, errors


def validate_net_panel_values(wan_ip, wan_gw, lan_ip, lan_gw, inner_raw,
                              placeholder_wan_cidr, placeholder_wan_gw, placeholder_lan_cidr):
    """
    校验初始化面板中的网络相关输入是否符合标准。
    若某列为占位符则跳过校验。
    返回 (是否全部合法, 错误信息列表)。
    """
    errs = []
    if wan_ip and wan_ip.strip() and wan_ip.strip() != placeholder_wan_cidr:
        ok, msg = _validate_cidr(wan_ip, "WAN IP")
        if not ok:
            errs.append(msg)
    if wan_gw and wan_gw.strip() and wan_gw.strip() != placeholder_wan_gw:
        ok, msg = _validate_ip(wan_gw, "WAN网关")
        if not ok:
            errs.append(msg)
    if lan_ip and lan_ip.strip() and lan_ip.strip() != placeholder_lan_cidr:
        ok, msg = _validate_cidr(lan_ip, "LAN IP")
        if not ok:
            errs.append(msg)
    if lan_gw and lan_gw.strip():
        ok, msg = _validate_ip(lan_gw, "LAN网关")
        if not ok:
            errs.append(msg)
    _, inner_errors = _validate_inner_nets(inner_raw)
    for frag, reason in inner_errors:
        errs.append(f"内网段「{frag}」不符合网络标准：{reason}")
    return (len(errs) == 0, errs)


def _normalize_lan_gw_from_cidr(lan_cidr: str, lan_gw: str) -> str:
    raw = str(lan_gw or "").strip()
    if not raw:
        return raw
    alias = raw.replace(" ", "").lower()
    # 仅兼容历史保存值；正常默认值/UI 均直接使用纯 IP。
    if alias in ("同lanip", "同lan"):
        try:
            return str(ipaddress.ip_interface(str(lan_cidr or "").strip()).ip)
        except Exception:
            return ""
    if "/" in raw:
        try:
            return str(ipaddress.ip_interface(raw).ip)
        except Exception:
            return raw
    return raw


# =====================================================================
# 隧道名称标准化
# =====================================================================
def normalize_vtun(raw):
    if not raw: return ""
    raw = str(raw).strip(); s = raw.lower()
    if s.startswith("vtun"): return s
    m = re.match(r"tunnel\s*0\s*/\s*0\s*/\s*(\d+)", s)
    if m: return f"vtun{m.group(1)}"
    if s.startswith("tun"): return f"v{s}"
    m = re.search(r"(\d+)$", raw)
    if m: return f"vtun{m.group(1)}"
    return s

def normalize_tun(raw):
    if not raw: return ""
    raw = str(raw).strip(); s = raw.lower()
    m = re.match(r"tunnel\s*0\s*/\s*0\s*/\s*(\d+)", s)
    if m: return f"tun{m.group(1)}"
    m = re.match(r"tunnel(\d+)$", s)
    if m: return f"tun{m.group(1)}"
    if s.startswith("vtun"): return s[1:]
    if s.startswith("tun"): return s
    m = re.search(r"(\d+)$", raw)
    if m: return f"tun{m.group(1)}"
    return s

def vtun_port(tunnel_id):
    if not tunnel_id: return ""
    s = str(tunnel_id).strip().lower()
    port = s[4:] if s.startswith("vtun") else (s[3:] if s.startswith("tun") else s)
    m = re.match(r"(\d+)", port)
    return m.group(1) if m else ""

def cidr_parts(cidr):
    try:
        iface = ipaddress.ip_interface(cidr)
        net = iface.network
        return str(iface.ip), net.prefixlen, str(net.netmask), str(net.network_address)
    except Exception:
        return cidr, "", "", ""

def dhcp_range(lan_ip, prefix):
    try:
        net = ipaddress.ip_network(f"{lan_ip}/{prefix}", strict=False)
        hosts = list(net.hosts())
        return str(hosts[min(9, len(hosts)-1)]), str(hosts[min(199, len(hosts)-1)])
    except Exception:
        return "", ""

DEFAULT_WAN_CIDR   = "192.168.1.10/24"
DEFAULT_WAN_GW     = "192.168.1.1"
DEFAULT_LAN_CIDR   = "192.168.5.1/24"
DEFAULT_INNER_NETS = "192.168.0.0/16"
# WAN口/LAN口：与页签「eth」后数字一致（可视化编辑器可写入）
DEFAULT_WAN_ETH    = "0"
DEFAULT_LAN_ETH    = "5"
# 与 build_net_panel(wan_dhcp_default=False, lan_dhcp_default=True) 初始一致，可视化可改
DEFAULT_WAN_DHCP   = False
DEFAULT_LAN_DHCP   = True
# LAN 网关默认直接使用 LAN IP 主机位；保留兼容层仅处理历史保存的"同LAN IP"。
DEFAULT_GEN_RETURN_ROUTE = False
# 无掩码主机地址（模板/映射用；随 CIDR 变化由可视化合并刷新）
DEFAULT_WAN_IP_PLAIN = DEFAULT_WAN_CIDR.split("/", 1)[0].strip() if DEFAULT_WAN_CIDR else ""
DEFAULT_LAN_IP_PLAIN = DEFAULT_LAN_CIDR.split("/", 1)[0].strip() if DEFAULT_LAN_CIDR else ""
DEFAULT_LAN_GW     = DEFAULT_LAN_IP_PLAIN

# HK 页签专用默认（出厂与非 HK 相同；all_in_one 按场景分别持久化，互不覆盖）
HK_DEFAULT_WAN_CIDR   = DEFAULT_WAN_CIDR
HK_DEFAULT_WAN_GW     = DEFAULT_WAN_GW
HK_DEFAULT_LAN_CIDR   = DEFAULT_LAN_CIDR
HK_DEFAULT_INNER_NETS = DEFAULT_INNER_NETS
HK_DEFAULT_WAN_ETH    = DEFAULT_WAN_ETH
HK_DEFAULT_LAN_ETH    = DEFAULT_LAN_ETH
HK_DEFAULT_WAN_DHCP   = DEFAULT_WAN_DHCP
HK_DEFAULT_LAN_DHCP   = DEFAULT_LAN_DHCP
HK_DEFAULT_LAN_GW     = DEFAULT_LAN_GW
HK_DEFAULT_GEN_RETURN_ROUTE = False
HK_DEFAULT_WAN_IP_PLAIN = (
    HK_DEFAULT_WAN_CIDR.split("/", 1)[0].strip() if HK_DEFAULT_WAN_CIDR else ""
)
HK_DEFAULT_LAN_IP_PLAIN = (
    HK_DEFAULT_LAN_CIDR.split("/", 1)[0].strip() if HK_DEFAULT_LAN_CIDR else ""
)

# =====================================================================
# HK 模板
# =====================================================================
TEMPLATE_EPOCH_HK = """\
# ==========================================================
# Epoch HK 出口配置  Hostname: {hostname}
# 主线  PE:{main_pe}  TUNNEL:{main_tunnel}(port:{main_tunnel_port})
#       WANIP:{main_wanip}  PE侧:{main_wanip_remote}  CE侧:{main_wanip_local}
#       Docking:{main_docking}  HKIP:{hkip_nat_all}  CELOIP:{ce_loip}
#       BGP: {main_bgp1}, {main_bgp2}
# 备线  PE:{bk_pe}  TUNNEL:{bk_tunnel}(port:{bk_tunnel_port})
#       WANIP:{bk_wanip}  PE侧:{bk_wanip_remote}  CE侧:{bk_wanip_local}
#       Docking:{bk_docking}  BGP: {bk_bgp1}, {bk_bgp2}
# ───────────────────────────────────────────────────────
# BGP更新源：{ce_loip}  (CE LOIP)
# 注意：请自行增加nat/dns/mtu部分！！
# ==========================================================
set epoch file-sync task 1 local '/opt/cn.txt'
set epoch file-sync task 1 remote 'http://183.56.161.82:1909/f32x/domainlist/cn_domainlist.last'
set epoch file-sync task 2 local '/opt/oversea.txt'
set epoch file-sync task 2 remote 'http://183.56.161.82:1909/f32x/domainlist/oversea_domainlist.last'
set firewall all-ping 'enable'
set firewall broadcast-ping 'disable'
set firewall config-trap 'disable'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.117.226/32'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.119.251/32'
set firewall group network-group GROUP-FNET-Whitelist network '120.76.31.146/32'
set firewall group network-group GROUP-FNET-Whitelist network '202.104.174.178/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.236.97/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.238.8/29'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.250/32'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.10/32'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.11/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.99/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.100/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.101/32'
set firewall group network-group GROUP-FNET-Whitelist network '10.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '172.16.0.0/12'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.0.0/16'
set firewall group network-group GROUP-FNET-Whitelist network '100.68.250.0/24'
set firewall group network-group GROUP-FNET-Whitelist network '224.0.0.0/4'
set firewall ipv6-receive-redirects 'disable'
set firewall ipv6-src-route 'disable'
set firewall ip-src-route 'disable'
set firewall log-martians 'enable'
set firewall name WAN2LOCAL default-action 'drop'
set firewall name WAN2LOCAL rule 1005 action 'accept'
set firewall name WAN2LOCAL rule 1005 state established 'enable'
set firewall name WAN2LOCAL rule 1005 state related 'enable'
set firewall name WAN2LOCAL rule 1010 action 'accept'
set firewall name WAN2LOCAL rule 1010 source group network-group 'GROUP-FNET-Whitelist'
set firewall name WAN2LOCAL rule 1210 action 'accept'
set firewall name WAN2LOCAL rule 1210 protocol 'gre'
set firewall name WAN2LOCAL rule 1220 action 'accept'
set firewall name WAN2LOCAL rule 1220 protocol 'ipip'
{fw_options_block}
set firewall receive-redirects 'disable'
set firewall send-redirects 'disable'
set firewall source-validation 'disable'
set firewall syn-cookies 'enable'
set firewall twa-hazards-protection 'disable'
set interfaces ethernet {wan_if} address '{wan_addr}'
set interfaces ethernet {wan_if} description 'TO-WAN'
{lan_if_block}
set interfaces dummy dum0 address '{ce_loip}/32'
set interfaces dummy dum0 description 'CE LOIP'
set interfaces dummy dum100 address '{hkip_nat}/32'
set interfaces dummy dum100 description '{hkip_dum100_desc}'
{extra_dum_block}
set interfaces openvpn {main_tunnel} description 'MAIN_{main_pe}'
set interfaces openvpn {main_tunnel} firewall local name 'WAN2LOCAL'
set interfaces openvpn {main_tunnel} local-address {main_wanip_local} subnet-mask '255.255.255.252'
set interfaces openvpn {main_tunnel} mode 'site-to-site'
set interfaces openvpn {main_tunnel} openvpn-option '--nobind'
set interfaces openvpn {main_tunnel} openvpn-option '--ping 10'
set interfaces openvpn {main_tunnel} openvpn-option '--ping-restart 60'
set interfaces openvpn {main_tunnel} openvpn-option '--persist-tun'
set interfaces openvpn {main_tunnel} openvpn-option '--fragment 1300'
set interfaces openvpn {main_tunnel} protocol 'udp'
set interfaces openvpn {main_tunnel} remote-address '{main_wanip_remote}'
set interfaces openvpn {main_tunnel} remote-host '{main_docking}'
set interfaces openvpn {main_tunnel} remote-port '{main_tunnel_port}'
set interfaces openvpn {main_tunnel} shared-secret-key-file '/config/auth/openvpn.secret'
set interfaces openvpn {bk_tunnel} description 'BK_{bk_pe}'
set interfaces openvpn {bk_tunnel} firewall local name 'WAN2LOCAL'
set interfaces openvpn {bk_tunnel} local-address {bk_wanip_local} subnet-mask '255.255.255.252'
set interfaces openvpn {bk_tunnel} mode 'site-to-site'
set interfaces openvpn {bk_tunnel} openvpn-option '--nobind'
set interfaces openvpn {bk_tunnel} openvpn-option '--ping 10'
set interfaces openvpn {bk_tunnel} openvpn-option '--ping-restart 60'
set interfaces openvpn {bk_tunnel} openvpn-option '--persist-tun'
set interfaces openvpn {bk_tunnel} openvpn-option '--fragment 1300'
set interfaces openvpn {bk_tunnel} protocol 'udp'
set interfaces openvpn {bk_tunnel} remote-address '{bk_wanip_remote}'
set interfaces openvpn {bk_tunnel} remote-host '{bk_docking}'
set interfaces openvpn {bk_tunnel} remote-port '{bk_tunnel_port}'
set interfaces openvpn {bk_tunnel} shared-secret-key-file '/config/auth/openvpn.secret'
set nat source rule 10 outbound-interface '{wan_if}'
set nat source rule 10 translation address 'masquerade'
{overseas_nat_block}
set nat source rule 3000 destination address '8.8.0.0/16'
set nat source rule 3000 outbound-interface '{main_tunnel}'
set nat source rule 3000 translation address '{hkip_nat}'
set nat source rule 3050 destination address '8.8.0.0/16'
set nat source rule 3050 outbound-interface '{bk_tunnel}'
set nat source rule 3050 translation address '{hkip_nat}'
set openfalcon endpoint-name '{hostname}'
set openfalcon server-address '192.168.237.86'
set policy community-list 80 rule 10 action 'permit'
set policy community-list 80 rule 10 description 'to_hk'
set policy community-list 80 rule 10 regex '65000:9939'
set policy community-list 81 rule 10 action 'permit'
set policy community-list 81 rule 10 description 'to_ct'
set policy community-list 81 rule 10 regex '65000:4134'
set policy community-list 82 rule 10 action 'permit'
set policy community-list 82 rule 10 description 'to_cnc'
set policy community-list 82 rule 10 regex '65000:4837'
set policy community-list 83 rule 10 action 'permit'
set policy community-list 83 rule 10 description 'to_cn_other'
set policy community-list 83 rule 10 regex '65000:9808'
set policy community-list 85 rule 10 action 'permit'
set policy community-list 85 rule 10 description 'to_deny'
set policy community-list 85 rule 10 regex '65000:9807'
set policy community-list 88 rule 10 action 'permit'
set policy community-list 88 rule 10 description 'to_google'
set policy community-list 88 rule 10 regex '65000:9008'
set policy route-map bgp-from--RSVR rule 100 action 'permit'
set policy route-map bgp-from--RSVR rule 100 description 'to_hk'
set policy route-map bgp-from--RSVR rule 100 match community community-list '80'
set policy route-map bgp-from--RSVR rule 100 set ip-next-hop '{main_wanip_remote}'
set policy route-map bgp-from--RSVR rule 200 action 'permit'
set policy route-map bgp-from--RSVR rule 200 description 'to_ct'
set policy route-map bgp-from--RSVR rule 200 match community community-list '81'
set policy route-map bgp-from--RSVR rule 200 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 300 action 'permit'
set policy route-map bgp-from--RSVR rule 300 description 'to_cnc'
set policy route-map bgp-from--RSVR rule 300 match community community-list '82'
set policy route-map bgp-from--RSVR rule 300 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 400 action 'permit'
set policy route-map bgp-from--RSVR rule 400 description 'to_cn_other'
set policy route-map bgp-from--RSVR rule 400 match community community-list '83'
set policy route-map bgp-from--RSVR rule 400 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 100 action 'permit'
set policy route-map bgp-from--RSVR2 rule 100 description 'to_hk'
set policy route-map bgp-from--RSVR2 rule 100 match community community-list '80'
set policy route-map bgp-from--RSVR2 rule 100 set ip-next-hop '{bk_wanip_remote}'
set policy route-map bgp-from--RSVR2 rule 100 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 200 action 'permit'
set policy route-map bgp-from--RSVR2 rule 200 description 'to_ct'
set policy route-map bgp-from--RSVR2 rule 200 match community community-list '81'
set policy route-map bgp-from--RSVR2 rule 200 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 200 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 300 action 'permit'
set policy route-map bgp-from--RSVR2 rule 300 description 'to_cnc'
set policy route-map bgp-from--RSVR2 rule 300 match community community-list '82'
set policy route-map bgp-from--RSVR2 rule 300 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 300 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 400 action 'permit'
set policy route-map bgp-from--RSVR2 rule 400 description 'to_cn_other'
set policy route-map bgp-from--RSVR2 rule 400 match community community-list '83'
set policy route-map bgp-from--RSVR2 rule 400 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 400 set local-preference '50'
set protocols bgp 65000 neighbor {main_bgp1} peer-group 'RSVR'
set protocols bgp 65000 neighbor {main_bgp2} peer-group 'RSVR'
set protocols bgp 65000 neighbor {bk_bgp1} peer-group 'RSVR2'
set protocols bgp 65000 neighbor {bk_bgp2} peer-group 'RSVR2'
set protocols bgp 65000 peer-group RSVR address-family ipv4-unicast route-map import 'bgp-from--RSVR'
set protocols bgp 65000 peer-group RSVR address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp 65000 peer-group RSVR remote-as '65000'
set protocols bgp 65000 peer-group RSVR update-source '{ce_loip}'
set protocols bgp 65000 peer-group RSVR2 address-family ipv4-unicast route-map import 'bgp-from--RSVR2'
set protocols bgp 65000 peer-group RSVR2 address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp 65000 peer-group RSVR2 remote-as '65000'
set protocols bgp 65000 peer-group RSVR2 update-source '{ce_loip}'
set protocols bgp 65000 timers holdtime '15'
set protocols bgp 65000 timers keepalive '5'
set track name {main_track} failure-count '2'
set track name {main_track} success-count '2'
set track name {main_track} test 10 resp-time '5'
set track name {main_track} test 10 target '{main_wanip_remote}'
set track name {main_track} test 10 ttl-limit '1'
set track name {main_track} test 10 type 'ping'
set track name {bk_track} failure-count '2'
set track name {bk_track} success-count '2'
set track name {bk_track} test 10 resp-time '5'
set track name {bk_track} test 10 target '{bk_wanip_remote}'
set track name {bk_track} test 10 ttl-limit '1'
set track name {bk_track} test 10 type 'ping'
{wan_route_block}
set protocols static route 114.113.245.99/32 next-hop {main_wanip_remote}
set protocols static route 114.113.245.100/32 next-hop {bk_wanip_remote}
set protocols static route {main_docking}/32 next-hop 1.1.1.1
set protocols static route {bk_docking}/32 next-hop 1.1.1.1
{bgp_server_routes}
set protocols static route 192.168.55.250/32 next-hop {main_wanip_remote} track {main_track}
set protocols static route 192.168.55.250/32 next-hop {bk_wanip_remote} distance '5'
set protocols static route 192.168.237.86/32 next-hop {main_wanip_remote} track {main_track}
set protocols static route 192.168.237.86/32 next-hop {bk_wanip_remote} distance '5'
{return_routes_block}
set system host-name '{hostname}'
set service dns forwarding allow-from '0.0.0.0/0'
set service dns forwarding cache-size '1001'
set service dns forwarding dnssec 'off'
set service dns forwarding domainlist CN file '/opt/cn.txt'
set service dns forwarding domainlist CN recursion-desired
set service dns forwarding domainlist CN server '114.114.114.114'
set service dns forwarding domainlist CN server '114.114.115.115'
set service dns forwarding domainlist HK file '/opt/oversea.txt'
set service dns forwarding domainlist HK recursion-desired
set service dns forwarding domainlist HK server '8.8.8.8'
set service dns forwarding domainlist HK server '8.8.4.4'
set service dns forwarding listen-address '0.0.0.0'
set service dns forwarding name-server '8.8.8.8'
set service dns forwarding name-server '8.8.4.4'
set service dns forwarding source-address '0.0.0.0'
{dhcp_server_block}"""

# =====================================================================
# 非香港出口 模板  (v2.8修复：bk track补全 / bk固定路由补track / 删local-route)
# =====================================================================
TEMPLATE_EPOCH_US = """\
# ==========================================================
# Epoch 非香港出口配置  Hostname: {hostname}
# 主ACVPN GRE  {main_acvpn_gre_tun}  PE:{main_acvpn_gre_pe}
#   WANIP:{main_acvpn_gre_wanip}  PE侧:{main_acvpn_gre_pe_ip}  CE侧:{main_acvpn_gre_ce_ip}
#   GRE remote:{main_acvpn_gre_remote}
# 主ACVPN vtun  {main_acvpn_vtun_id}(port:{main_acvpn_vtun_port})  PE:{main_acvpn_vtun_pe}
#   local:{main_acvpn_vtun_local}  remote:{main_acvpn_vtun_remote}  docking:{main_acvpn_vtun_docking}
# 主非香港出口  {main_us_tun}  PE:{main_us_pe}
#   WANIP:{main_us_wanip}  PE侧:{main_us_pe_ip}  CE侧:{main_us_gre_ce_ip}
#   PE docking:{main_us_pe_docking}  NAT IP(FakeIP):{main_us_nat_ip_all}
#   BGP: {main_us_bgp1}, {main_us_bgp2}
# 备ACVPN GRE  {bk_acvpn_gre_tun}  PE:{bk_acvpn_gre_pe}
#   WANIP:{bk_acvpn_gre_wanip}  PE侧:{bk_acvpn_gre_pe_ip}  CE侧:{bk_acvpn_gre_ce_ip}
#   GRE remote:{bk_acvpn_gre_remote}
# 备ACVPN vtun  {bk_acvpn_vtun_id}(port:{bk_acvpn_vtun_port})  PE:{bk_acvpn_vtun_pe}
#   local:{bk_acvpn_vtun_local}  remote:{bk_acvpn_vtun_remote}  docking:{bk_acvpn_vtun_docking}
# 备非香港出口  {bk_us_tun}  PE:{bk_us_pe}
#   WANIP:{bk_us_wanip}  PE侧:{bk_us_pe_ip}  CE侧:{bk_us_gre_ce_ip}
#   PE docking:{bk_us_pe_docking}  NAT IP(FakeIP):{bk_us_nat_ip_all}
#   BGP: {bk_us_bgp1}, {bk_us_bgp2}
# ───────────────────────────────────────────────────────
# BGP更新源(主)：{main_us_nat_ip_all}  BGP更新源(备)：{bk_us_nat_ip_all}
# 注意：请自行增加nat/dns/mtu部分！！
# ==========================================================
set epoch file-sync task 1 local '/opt/cn.txt'
set epoch file-sync task 1 remote 'http://183.56.161.82:1909/f32x/domainlist/cn_domainlist.last'
set epoch file-sync task 2 local '/opt/oversea.txt'
set epoch file-sync task 2 remote 'http://183.56.161.82:1909/f32x/domainlist/oversea_domainlist.last'
set firewall all-ping 'enable'
set firewall broadcast-ping 'disable'
set firewall config-trap 'disable'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.117.226/32'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.119.251/32'
set firewall group network-group GROUP-FNET-Whitelist network '120.76.31.146/32'
set firewall group network-group GROUP-FNET-Whitelist network '202.104.174.178/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.236.97/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.238.8/29'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.250/32'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.10/32'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.55.11/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.99/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.100/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.101/32'
set firewall group network-group GROUP-FNET-Whitelist network '10.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '172.16.0.0/12'
set firewall group network-group GROUP-FNET-Whitelist network '192.168.0.0/16'
set firewall group network-group GROUP-FNET-Whitelist network '100.68.250.0/24'
set firewall group network-group GROUP-FNET-Whitelist network '224.0.0.0/4'
set firewall ipv6-receive-redirects 'disable'
set firewall ipv6-src-route 'disable'
set firewall ip-src-route 'disable'
set firewall log-martians 'enable'
set firewall name WAN2LOCAL default-action 'drop'
set firewall name WAN2LOCAL rule 1005 action 'accept'
set firewall name WAN2LOCAL rule 1005 state established 'enable'
set firewall name WAN2LOCAL rule 1005 state related 'enable'
set firewall name WAN2LOCAL rule 1010 action 'accept'
set firewall name WAN2LOCAL rule 1010 source group network-group 'GROUP-FNET-Whitelist'
set firewall name WAN2LOCAL rule 1210 action 'accept'
set firewall name WAN2LOCAL rule 1210 protocol 'gre'
set firewall name WAN2LOCAL rule 1220 action 'accept'
set firewall name WAN2LOCAL rule 1220 protocol 'ipip'
{fw_options_block}
set firewall receive-redirects 'disable'
set firewall send-redirects 'disable'
set firewall source-validation 'disable'
set firewall syn-cookies 'enable'
set firewall twa-hazards-protection 'disable'
set interfaces ethernet {wan_if} address '{wan_addr}'
set interfaces ethernet {wan_if} description 'TO-WAN'
{lan_if_block}
set interfaces dummy dum0 address '{ce_docking}/32'
set interfaces dummy dum0 description 'CE Docking'
set interfaces dummy dum100 address '{main_us_nat_ip}/32'
set interfaces dummy dum100 description '{main_us_dum100_desc}'
{extra_dum_main_block}
set interfaces dummy dum200 address '{bk_us_nat_ip}/32'
set interfaces dummy dum200 description '{bk_us_dum200_desc}'
{extra_dum_bk_block}
set interfaces openvpn {main_acvpn_vtun_id} description 'MAIN_{main_acvpn_vtun_pe}'
set interfaces openvpn {main_acvpn_vtun_id} firewall local name 'WAN2LOCAL'
set interfaces openvpn {main_acvpn_vtun_id} local-address {main_acvpn_vtun_local} subnet-mask '255.255.255.252'
set interfaces openvpn {main_acvpn_vtun_id} mode 'site-to-site'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option '--nobind'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option '--ping 10'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option '--ping-restart 60'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option '--persist-tun'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option '--fragment 1300'
set interfaces openvpn {main_acvpn_vtun_id} protocol 'udp'
set interfaces openvpn {main_acvpn_vtun_id} remote-address '{main_acvpn_vtun_remote}'
set interfaces openvpn {main_acvpn_vtun_id} remote-host '{main_acvpn_vtun_docking}'
set interfaces openvpn {main_acvpn_vtun_id} remote-port '{main_acvpn_vtun_port}'
set interfaces openvpn {main_acvpn_vtun_id} shared-secret-key-file '/config/auth/openvpn.secret'
set interfaces openvpn {bk_acvpn_vtun_id} description 'BK_{bk_acvpn_vtun_pe}'
set interfaces openvpn {bk_acvpn_vtun_id} firewall local name 'WAN2LOCAL'
set interfaces openvpn {bk_acvpn_vtun_id} local-address {bk_acvpn_vtun_local} subnet-mask '255.255.255.252'
set interfaces openvpn {bk_acvpn_vtun_id} mode 'site-to-site'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option '--nobind'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option '--ping 10'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option '--ping-restart 60'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option '--persist-tun'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option '--fragment 1300'
set interfaces openvpn {bk_acvpn_vtun_id} protocol 'udp'
set interfaces openvpn {bk_acvpn_vtun_id} remote-address '{bk_acvpn_vtun_remote}'
set interfaces openvpn {bk_acvpn_vtun_id} remote-host '{bk_acvpn_vtun_docking}'
set interfaces openvpn {bk_acvpn_vtun_id} remote-port '{bk_acvpn_vtun_port}'
set interfaces openvpn {bk_acvpn_vtun_id} shared-secret-key-file '/config/auth/openvpn.secret'
set interfaces tunnel {main_acvpn_gre_tun} address '{main_acvpn_gre_ce_ip}/30'
set interfaces tunnel {main_acvpn_gre_tun} description 'MAIN_{main_acvpn_gre_pe}'
set interfaces tunnel {main_acvpn_gre_tun} encapsulation 'gre'
set interfaces tunnel {main_acvpn_gre_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {main_acvpn_gre_tun} mtu '1476'
set interfaces tunnel {main_acvpn_gre_tun} multicast 'disable'
set interfaces tunnel {main_acvpn_gre_tun} parameters ip ttl '255'
set interfaces tunnel {main_acvpn_gre_tun} remote '{main_acvpn_gre_remote}'
set interfaces tunnel {main_acvpn_gre_tun} source-address '{main_acvpn_vtun_local}'
set interfaces tunnel {bk_acvpn_gre_tun} address '{bk_acvpn_gre_ce_ip}/30'
set interfaces tunnel {bk_acvpn_gre_tun} description 'BK_{bk_acvpn_gre_pe}'
set interfaces tunnel {bk_acvpn_gre_tun} encapsulation 'gre'
set interfaces tunnel {bk_acvpn_gre_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {bk_acvpn_gre_tun} mtu '1476'
set interfaces tunnel {bk_acvpn_gre_tun} multicast 'disable'
set interfaces tunnel {bk_acvpn_gre_tun} parameters ip ttl '255'
set interfaces tunnel {bk_acvpn_gre_tun} remote '{bk_acvpn_gre_remote}'
set interfaces tunnel {bk_acvpn_gre_tun} source-address '{bk_acvpn_vtun_local}'
set interfaces tunnel {main_us_tun} address '{main_us_gre_ce_ip}/30'
set interfaces tunnel {main_us_tun} description 'MAIN_{main_us_pe}'
set interfaces tunnel {main_us_tun} encapsulation 'gre'
set interfaces tunnel {main_us_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {main_us_tun} mtu '1452'
set interfaces tunnel {main_us_tun} multicast 'disable'
set interfaces tunnel {main_us_tun} parameters ip ttl '255'
set interfaces tunnel {main_us_tun} remote '{main_us_pe_docking}'
set interfaces tunnel {main_us_tun} source-address '{ce_docking}'
set interfaces tunnel {bk_us_tun} address '{bk_us_gre_ce_ip}/30'
set interfaces tunnel {bk_us_tun} description 'BK_{bk_us_pe}'
set interfaces tunnel {bk_us_tun} encapsulation 'gre'
set interfaces tunnel {bk_us_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {bk_us_tun} mtu '1452'
set interfaces tunnel {bk_us_tun} multicast 'disable'
set interfaces tunnel {bk_us_tun} parameters ip ttl '255'
set interfaces tunnel {bk_us_tun} remote '{bk_us_pe_docking}'
set interfaces tunnel {bk_us_tun} source-address '{ce_docking}'
set nat source rule 10 outbound-interface '{wan_if}'
set nat source rule 10 translation address 'masquerade'
{overseas_nat_block}
set nat source rule 3000 destination address '8.8.0.0/16'
set nat source rule 3000 outbound-interface '{main_us_tun}'
set nat source rule 3000 translation address '{main_us_nat_ip}'
set nat source rule 3050 destination address '8.8.0.0/16'
set nat source rule 3050 outbound-interface '{bk_us_tun}'
set nat source rule 3050 translation address '{bk_us_nat_ip}'
set openfalcon endpoint-name '{hostname}'
set openfalcon server-address '192.168.237.86'
set policy community-list 80 rule 10 action 'permit'
set policy community-list 80 rule 10 description 'to_hk'
set policy community-list 80 rule 10 regex '65000:9939'
set policy community-list 81 rule 10 action 'permit'
set policy community-list 81 rule 10 description 'to_ct'
set policy community-list 81 rule 10 regex '65000:4134'
set policy community-list 82 rule 10 action 'permit'
set policy community-list 82 rule 10 description 'to_cnc'
set policy community-list 82 rule 10 regex '65000:4837'
set policy community-list 83 rule 10 action 'permit'
set policy community-list 83 rule 10 description 'to_cn_other'
set policy community-list 83 rule 10 regex '65000:9808'
set policy community-list 85 rule 10 action 'permit'
set policy community-list 85 rule 10 description 'to_deny'
set policy community-list 85 rule 10 regex '65000:9807'
set policy community-list 88 rule 10 action 'permit'
set policy community-list 88 rule 10 description 'to_google'
set policy community-list 88 rule 10 regex '65000:9008'
set policy route-map bgp-from--RSVR rule 100 action 'permit'
set policy route-map bgp-from--RSVR rule 100 description 'to_hk'
set policy route-map bgp-from--RSVR rule 100 match community community-list '80'
set policy route-map bgp-from--RSVR rule 100 set ip-next-hop '{main_us_pe_ip}'
set policy route-map bgp-from--RSVR rule 200 action 'permit'
set policy route-map bgp-from--RSVR rule 200 description 'to_ct'
set policy route-map bgp-from--RSVR rule 200 match community community-list '81'
set policy route-map bgp-from--RSVR rule 200 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 300 action 'permit'
set policy route-map bgp-from--RSVR rule 300 description 'to_cnc'
set policy route-map bgp-from--RSVR rule 300 match community community-list '82'
set policy route-map bgp-from--RSVR rule 300 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 400 action 'permit'
set policy route-map bgp-from--RSVR rule 400 description 'to_cn_other'
set policy route-map bgp-from--RSVR rule 400 match community community-list '83'
set policy route-map bgp-from--RSVR rule 400 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 100 action 'permit'
set policy route-map bgp-from--RSVR2 rule 100 description 'to_hk'
set policy route-map bgp-from--RSVR2 rule 100 match community community-list '80'
set policy route-map bgp-from--RSVR2 rule 100 set ip-next-hop '{bk_us_pe_ip}'
set policy route-map bgp-from--RSVR2 rule 100 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 200 action 'permit'
set policy route-map bgp-from--RSVR2 rule 200 description 'to_ct'
set policy route-map bgp-from--RSVR2 rule 200 match community community-list '81'
set policy route-map bgp-from--RSVR2 rule 200 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 200 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 300 action 'permit'
set policy route-map bgp-from--RSVR2 rule 300 description 'to_cnc'
set policy route-map bgp-from--RSVR2 rule 300 match community community-list '82'
set policy route-map bgp-from--RSVR2 rule 300 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 300 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 400 action 'permit'
set policy route-map bgp-from--RSVR2 rule 400 description 'to_cn_other'
set policy route-map bgp-from--RSVR2 rule 400 match community community-list '83'
set policy route-map bgp-from--RSVR2 rule 400 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 400 set local-preference '50'
set protocols bgp 65000 neighbor {main_us_bgp1} peer-group 'RSVR'
set protocols bgp 65000 neighbor {main_us_bgp2} peer-group 'RSVR'
set protocols bgp 65000 neighbor {bk_us_bgp1} peer-group 'RSVR2'
set protocols bgp 65000 neighbor {bk_us_bgp2} peer-group 'RSVR2'
set protocols bgp 65000 peer-group RSVR address-family ipv4-unicast route-map import 'bgp-from--RSVR'
set protocols bgp 65000 peer-group RSVR address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp 65000 peer-group RSVR remote-as '65000'
set protocols bgp 65000 peer-group RSVR update-source '{main_us_nat_ip}'
set protocols bgp 65000 peer-group RSVR2 address-family ipv4-unicast route-map import 'bgp-from--RSVR2'
set protocols bgp 65000 peer-group RSVR2 address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp 65000 peer-group RSVR2 remote-as '65000'
set protocols bgp 65000 peer-group RSVR2 update-source '{bk_us_nat_ip}'
set protocols bgp 65000 timers holdtime '15'
set protocols bgp 65000 timers keepalive '5'
set track name mainupe failure-count '2'
set track name mainupe success-count '2'
set track name mainupe test 10 resp-time '5'
set track name mainupe test 10 target '{main_acvpn_gre_pe_ip}'
set track name mainupe test 10 ttl-limit '1'
set track name mainupe test 10 type 'ping'
set track name backupe failure-count '2'
set track name backupe success-count '2'
set track name backupe test 10 resp-time '5'
set track name backupe test 10 target '{bk_acvpn_gre_pe_ip}'
set track name backupe test 10 ttl-limit '1'
set track name backupe test 10 type 'ping'
set track name mainnatpe failure-count '2'
set track name mainnatpe success-count '2'
set track name mainnatpe test 10 resp-time '5'
set track name mainnatpe test 10 target '{main_us_pe_ip}'
set track name mainnatpe test 10 ttl-limit '1'
set track name mainnatpe test 10 type 'ping'
set track name backnatpe failure-count '2'
set track name backnatpe success-count '2'
set track name backnatpe test 10 resp-time '5'
set track name backnatpe test 10 target '{bk_us_pe_ip}'
set track name backnatpe test 10 ttl-limit '1'
set track name backnatpe test 10 type 'ping'
{wan_route_block}
set protocols static route {main_acvpn_vtun_docking}/32 next-hop 1.1.1.1
set protocols static route {bk_acvpn_vtun_docking}/32 next-hop 1.1.1.1
set protocols static route {main_us_pe_docking}/32 next-hop {main_acvpn_gre_pe_ip}
set protocols static route {bk_us_pe_docking}/32 next-hop {bk_acvpn_gre_pe_ip}
set protocols static route {main_acvpn_gre_remote}/32 next-hop {main_acvpn_vtun_remote}
set protocols static route {bk_acvpn_gre_remote}/32 next-hop {bk_acvpn_vtun_remote}
{us_bgp_routes}
set protocols static route 192.168.55.250/32 next-hop {main_acvpn_gre_pe_ip} track mainupe
set protocols static route 192.168.55.250/32 next-hop {bk_acvpn_gre_pe_ip} distance '5'
set protocols static route 192.168.237.86/32 next-hop {main_acvpn_gre_pe_ip} track mainupe
set protocols static route 192.168.237.86/32 next-hop {bk_acvpn_gre_pe_ip} distance '5'
set protocols static route 114.113.245.99/32 next-hop {main_acvpn_gre_pe_ip}
set protocols static route 114.113.245.100/32 next-hop {bk_acvpn_gre_pe_ip}
{return_routes_block}
set policy local-route rule 1001 set table '101'
set policy local-route rule 1001 source '{main_us_gre_ce_ip}'
set protocols static table 101 route 0.0.0.0/0 next-hop {main_us_pe_ip}
set policy local-route rule 1002 set table '102'
set policy local-route rule 1002 source '{bk_us_gre_ce_ip}'
set protocols static table 102 route 0.0.0.0/0 next-hop {bk_us_pe_ip}
set system host-name '{hostname}'
set service dns forwarding allow-from '0.0.0.0/0'
set service dns forwarding cache-size '1001'
set service dns forwarding dnssec 'off'
set service dns forwarding domainlist CN file '/opt/cn.txt'
set service dns forwarding domainlist CN recursion-desired
set service dns forwarding domainlist CN server '114.114.114.114'
set service dns forwarding domainlist CN server '114.114.115.115'
set service dns forwarding domainlist HK file '/opt/oversea.txt'
set service dns forwarding domainlist HK recursion-desired
set service dns forwarding domainlist HK server '8.8.8.8'
set service dns forwarding domainlist HK server '8.8.4.4'
set service dns forwarding listen-address '0.0.0.0'
set service dns forwarding name-server '8.8.8.8'
set service dns forwarding name-server '8.8.4.4'
set service dns forwarding source-address '0.0.0.0'
{dhcp_server_block}"""

_ER_COVER_SKIP_HK = frozenset({
    "fw_options_block", "extra_dum_block", "overseas_nat_block", "bgp_server_routes",
    "return_routes_block", "dhcp_server_block", "wan_route_block",
})
_ER_COVER_SKIP_US = frozenset({
    "fw_options_block", "extra_dum_main_block", "extra_dum_bk_block", "overseas_nat_block",
    "return_routes_block", "us_bgp_routes", "dhcp_server_block", "wan_route_block",
})

# =====================================================================
# IPSec 接入占位模板 / 数据头示例（正式模板待提供后替换）
# =====================================================================
TEMPLATE_EPOCH_HK_IPSEC = "[开发中 - HK IPSec 模板待提供]"
TEMPLATE_EPOCH_US_IPSEC = "[开发中 - 非HK IPSec 模板待提供]"
HK_EXAMPLE_IPSEC = "[开发中 - HK IPSec 数据头示例待提供]"
US_EXAMPLE_IPSEC = "[开发中 - 非HK IPSec 数据头示例待提供]"


def _notify_epoch_field_coverage(template: str, data: dict, title: str, skip: frozenset) -> None:
    if not field_coverage:
        return
    sk = set(skip)
    # 旁挂： intentionally 不生成 LAN 口块，空串不应视为「缺数据」
    if data.get("bypass_mode"):
        sk.add("lan_if_block")
    miss = field_coverage.missing_template_fields(template, data, skip=frozenset(sk))
    field_coverage.show_generation_coverage_notice(messagebox, miss, title)


# =====================================================================
# 解析器 – HK
# =====================================================================
def parse_epoch_hk(text):
    result = {k: "" for k in [
        "main_pe","main_tunnel","main_tunnel_port",
        "main_wanip","main_wanip_remote","main_wanip_local",
        "main_docking","ce_loip","hkip_nat",
        "main_bgp1","main_bgp2",
        "bk_pe","bk_tunnel","bk_tunnel_port",
        "bk_wanip","bk_wanip_remote","bk_wanip_local",
        "bk_docking","bk_bgp1","bk_bgp2",
        "bgp_server_routes","hostname",
    ]}
    result["hkip_nat_list"] = []
    blocks = re.split(r'(?=(?:MAIN|BACKUP|主|备)\s*\n|(?:MAIN|BACKUP)\s*[：:])', text, flags=re.IGNORECASE)

    def parse_one(block, prefix):
        pe = _get(r'(?:主PE|PE)\s*[：:]\s*(.+)', block)
        if pe: result[f"{prefix}_pe"] = pe.strip()
        tun_raw = _get(r'TUNNEL\s*[：:]\s*(\S+)', block)
        if tun_raw:
            tun = normalize_vtun(tun_raw)
            result[f"{prefix}_tunnel"]      = tun
            result[f"{prefix}_tunnel_port"] = vtun_port(tun)
        wanip = _get(r'WANIP\s*[：:]\s*([\d./]+)', block)
        if wanip:
            result[f"{prefix}_wanip"] = wanip
            pe_ip, ce_ip = wanip_hosts(wanip)
            result[f"{prefix}_wanip_remote"] = pe_ip
            result[f"{prefix}_wanip_local"]  = ce_ip
        docking = _get(r'Docking\s*[：:]\s*([\d.]+)', block)
        if docking: result[f"{prefix}_docking"] = docking
        loip = _get(r'CE\s*LOIP\s*[：:]\s*([\d.]+)', block)
        if loip: result["ce_loip"] = loip
        hkip_m = re.search(r'HKIP\s*[：:]\s*(.*?)(?=\n[A-Za-z\u4e00-\u9fff]|\Z)', block,
                            re.IGNORECASE | re.DOTALL)
        if hkip_m:
            hkip_raw = hkip_m.group(1)
            pairs = re.findall(r'(\d{1,3}(?:\.\d{1,3}){3})\s*(?:-->|-)\s*\d{1,3}(?:\.\d{1,3}){3}', hkip_raw)
            nat_ips = pairs if pairs else re.findall(r'\d{1,3}(?:\.\d{1,3}){3}', hkip_raw)
            if nat_ips:
                result["hkip_nat"]      = nat_ips[0]
                result["hkip_nat_list"] = nat_ips
        bgp_raw = _get(r'BGPSERVER\s*IP\s*[：:]\s*(.+)', block)
        if bgp_raw:
            bgps = [ip.strip() for ip in re.split(r'[,，\s]+', bgp_raw)
                    if re.match(r'^\d+\.\d+', ip.strip())]
            result[f"{prefix}_bgp1"] = bgps[0] if len(bgps) > 0 else ""
            result[f"{prefix}_bgp2"] = bgps[1] if len(bgps) > 1 else ""

    for block in blocks:
        bu = block.strip()
        if re.match(r'(MAIN|主)', bu, re.IGNORECASE): parse_one(bu, "main")
        elif re.match(r'(BACKUP|备)', bu, re.IGNORECASE): parse_one(bu, "bk")

    # Fallback: 如果没有 MAIN/BACKUP 标记，改用 LineID 奇偶数区分主备线
    # （和 US 解析器相同的逻辑，LineID 末位奇数=主线，偶数=备线）
    if not result.get("main_tunnel") and not result.get("bk_tunnel"):
        lineid_blocks = re.split(r'(?=LineID\s*[:：])', text, flags=re.IGNORECASE)
        for block in lineid_blocks:
            if not re.search(r'LineID', block, re.IGNORECASE):
                continue
            line_id = _get(r'LineID\s*[:：]\s*(\S+)', block)
            if not line_id:
                continue
            last = line_id[-1]
            try:
                is_main = int(last) % 2 == 1
            except ValueError:
                is_main = True
            prefix = "main" if is_main else "bk"
            parse_one(block, prefix)

    return result

def extract_lineid_hk(text):
    m = re.search(r'lineid\s*[：:]\s*(\S+)', text, re.IGNORECASE)
    return m.group(1).strip() if m else ""

# =====================================================================
# 解析器 – US 子块角色识别（三重冗余）
# =====================================================================
def _us_sub_role(sub_text):
    pe  = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub_text).lower()
    tun = _get(r'^\s*(?:Tunnel|TUNNEL)\s*[:：]\s*(\S+)', sub_text).lower()
    if re.search(r'海外出口ip', sub_text, re.IGNORECASE): return 'gre2'
    if re.search(r'acvpn|ipsecvpn|ipsecgw', pe): return 'openvpn'
    if re.search(r'natpe', pe): return 'gre2'
    if re.search(r'(?:^|[-_])upe', pe): return 'gre1'
    if tun.startswith('vtun'): return 'openvpn'
    if re.match(r'tunnel|^tun\d', tun): return 'gre_unknown'
    return None

# =====================================================================
# 解析器 – US
# =====================================================================
def parse_epoch_us(text):
    result = {k: "" for k in [
        "main_acvpn_gre_pe","main_acvpn_gre_tun","main_acvpn_gre_wanip",
        "main_acvpn_gre_pe_ip","main_acvpn_gre_ce_ip","main_acvpn_gre_remote",
        "main_acvpn_vtun_pe","main_acvpn_vtun_id","main_acvpn_vtun_port",
        "main_acvpn_vtun_local","main_acvpn_vtun_remote","main_acvpn_vtun_docking",
        "bk_acvpn_gre_pe","bk_acvpn_gre_tun","bk_acvpn_gre_wanip",
        "bk_acvpn_gre_pe_ip","bk_acvpn_gre_ce_ip","bk_acvpn_gre_remote",
        "bk_acvpn_vtun_pe","bk_acvpn_vtun_id","bk_acvpn_vtun_port",
        "bk_acvpn_vtun_local","bk_acvpn_vtun_remote","bk_acvpn_vtun_docking",
        "main_us_pe","main_us_tun","main_us_wanip",
        "main_us_pe_ip","main_us_gre_ce_ip","main_us_pe_docking",
        "main_us_nat_ip","main_us_bgp1","main_us_bgp2",
        "bk_us_pe","bk_us_tun","bk_us_wanip",
        "bk_us_pe_ip","bk_us_gre_ce_ip","bk_us_pe_docking",
        "bk_us_nat_ip","bk_us_bgp1","bk_us_bgp2",
        "ce_docking","fw_options_block","us_bgp_routes","hostname",
    ]}
    result["main_us_nat_ips"] = []
    result["bk_us_nat_ips"]   = []
    all_gre2_subs = []

    blocks = re.split(r'(?=LineID\s*[:：])', text, flags=re.IGNORECASE)
    for block in blocks:
        if not re.search(r'LineID', block, re.IGNORECASE): continue
        line_id = _get(r'LineID\s*[:：]\s*(\S+)', block)
        if not line_id: continue
        last = line_id[-1]
        try:    is_main = int(last) % 2 == 1
        except: is_main = True
        px = "main" if is_main else "bk"

        lines = block.splitlines()
        pe_line_idx = [
            i for i, l in enumerate(lines)
            if re.match(r'^\s*PE\s*[:：]\s*\S', l)
            and not re.match(r'^\s*PE\s*(?:对接|AS|Docking)', l, re.IGNORECASE)
        ]
        sub_blocks = []
        for i, start in enumerate(pe_line_idx):
            end = pe_line_idx[i+1] if i+1 < len(pe_line_idx) else len(lines)
            sub_blocks.append("\n".join(lines[start:end]))
        if not pe_line_idx and re.search(r'海外出口ip', block):
            sub_blocks = [block]

        identified, unknown_gres = {}, []
        for sub in sub_blocks:
            role = _us_sub_role(sub)
            if role == 'gre_unknown':   unknown_gres.append(sub)
            elif role == 'gre2':        all_gre2_subs.append(sub)
            elif role in ('openvpn','gre1'):
                if role not in identified: identified[role] = sub
        for sub in unknown_gres:
            if 'gre1' not in identified: identified['gre1'] = sub; break

        if 'gre1' in identified:
            sub = identified['gre1']
            result[f"{px}_acvpn_gre_pe"]     = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub)
            tun_raw                           = _get(r'^\s*(?:Tunnel|TUNNEL)\s*[:：]\s*(\S+)', sub)
            result[f"{px}_acvpn_gre_tun"]    = normalize_tun(tun_raw)
            wanip                             = _get(r'^\s*wanip\s*[:：]\s*([\d./]+)', sub)
            result[f"{px}_acvpn_gre_wanip"]  = wanip
            pe_ip, ce_ip                      = wanip_hosts(wanip)
            result[f"{px}_acvpn_gre_pe_ip"]  = pe_ip
            result[f"{px}_acvpn_gre_ce_ip"]  = ce_ip
            result[f"{px}_acvpn_gre_remote"] = _get(r'PE\s*对接\s*[:：]\s*([\d.]+)', sub)
            ce_dock = _get(r'CE\s*对接\s*[:：]+\s*([\d.]+)', sub)
            if ce_dock: result[f"{px}_acvpn_vtun_local"] = ce_dock

        if 'openvpn' in identified:
            sub = identified['openvpn']
            result[f"{px}_acvpn_vtun_pe"]      = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub)
            vtun_raw                            = _get(r'^\s*(?:Tunnel|TUNNEL)\s*[:：]\s*(\S+)', sub)
            vtun_id                             = normalize_vtun(vtun_raw)
            result[f"{px}_acvpn_vtun_id"]      = vtun_id
            result[f"{px}_acvpn_vtun_port"]    = vtun_port(vtun_id)
            vtun_wanip                          = _get(r'^\s*wanip\s*[:：]\s*([\d./]+)', sub)
            pe_ip2, _                           = wanip_hosts(vtun_wanip)
            result[f"{px}_acvpn_vtun_remote"]  = pe_ip2
            result[f"{px}_acvpn_vtun_docking"] = _get(r'PE\s*对接\s*[:：]\s*([\d.]+)', sub)
            ce_dock_vtun = _get(r'CE\s*对接\s*[:：]+\s*([\d.]+)', sub)
            if ce_dock_vtun and not result.get(f"{px}_acvpn_vtun_local"):
                result[f"{px}_acvpn_vtun_local"] = ce_dock_vtun

    def _fill_gre2(sub, px):
        result[f"{px}_us_pe"]         = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub)
        tun_raw                        = _get(r'^\s*(?:TUNNEL|Tunnel)\s*[:：]\s*(\S+)', sub)
        result[f"{px}_us_tun"]        = normalize_tun(tun_raw)
        wanip                          = _get(r'^\s*WANIP\s*[:：]\s*([\d./]+)', sub)
        result[f"{px}_us_wanip"]      = wanip
        pe_ip, ce_ip                   = wanip_hosts(wanip)
        result[f"{px}_us_pe_ip"]      = pe_ip
        result[f"{px}_us_gre_ce_ip"]  = ce_ip
        result[f"{px}_us_pe_docking"] = _get(r'PE\s*[Dd]ocking\s*[:：]+\s*([\d.]+)', sub)
        ce_dock                        = _get(r'CE\s*[Dd]ocking\s*[:：]+\s*([\d.]+)', sub)
        if px == "main" and ce_dock: result["ce_docking"] = ce_dock
        bgp_raw = _get(r'BGPSERVER\s*IP\s*[:：]\s*(.+)', sub)
        bgps = [ip.strip() for ip in re.split(r'[,，\s]+', bgp_raw)
                if re.match(r'^\d+\.\d+', ip.strip())]
        result[f"{px}_us_bgp1"] = bgps[0] if bgps else ""
        result[f"{px}_us_bgp2"] = bgps[1] if len(bgps) > 1 else ""
        oversea_m = re.search(r'海外出口ip\s*[:：]\s*(.*?)(?=\n[^\d\s]|\Z)', sub,
                              re.IGNORECASE | re.DOTALL)
        nat_ips = []
        if oversea_m:
            blob = oversea_m.group(1)
            # Prefer range patterns (start-end), but fall back to plain IPv4 list.
            pairs = re.findall(
                r'(\d{1,3}(?:\.\d{1,3}){3})\s*[-–—~]\s*(\d{1,3}(?:\.\d{1,3}){3})',
                blob
            )
            if pairs:
                nat_ips = [p[0] for p in pairs]
            else:
                nat_ips = re.findall(r'\d{1,3}(?:\.\d{1,3}){3}', blob)
            # de-dup but keep order
            seen = set()
            nat_ips = [ip for ip in nat_ips if not (ip in seen or seen.add(ip))]
        result[f"{px}_us_nat_ips"] = nat_ips
        if nat_ips: result[f"{px}_us_nat_ip"] = nat_ips[0]

    if len(all_gre2_subs) >= 1: _fill_gre2(all_gre2_subs[0], "main")
    if len(all_gre2_subs) >= 2: _fill_gre2(all_gre2_subs[1], "bk")
    return result

def extract_lineid_us(text):
    m = re.search(r'LineID\s*[:：]\s*(\S+)', text, re.IGNORECASE)
    return m.group(1).strip() if m else ""

# =====================================================================
# WAN/LAN 配置块生成器
# =====================================================================
def build_wan_lan_blocks(wan_if, wan_dhcp, wan_ip_cidr, wan_gw,
                         lan_if, lan_dhcp, lan_ip_cidr, is_us=False, bypass=False):
    if wan_dhcp:
        wan_addr = "dhcp"
        wan_route_block = f"set protocols static route 1.1.1.1/32 dhcp-interface {wan_if}"
    else:
        wan_addr = wan_ip_cidr if wan_ip_cidr else DEFAULT_WAN_CIDR
        gw = wan_gw if wan_gw else DEFAULT_WAN_GW
        wan_route_block = (f"set protocols static route 0.0.0.0/0 next-hop 1.1.1.1 distance '222'\n"
                           f"set protocols static route 1.1.1.1/32 next-hop {gw}")
    if bypass:
        return {"wan_addr": wan_addr, "wan_if": wan_if,
                "lan_if_block": "",
                "wan_route_block": wan_route_block,
                "dhcp_server_block": ""}
    lan_cidr = lan_ip_cidr if lan_ip_cidr else DEFAULT_LAN_CIDR
    lan_ip, lan_prefix, lan_mask, lan_network = cidr_parts(lan_cidr)
    lan_if_block = (f"set interfaces ethernet {lan_if} address '{lan_cidr}'\n"
                    f"set interfaces ethernet {lan_if} description 'LAN'")
    if lan_dhcp and lan_ip and lan_prefix:
        d_start, d_stop = dhcp_range(lan_ip, lan_prefix)
        dhcp_server_block = (
            f"set service dhcp-server shared-network-name LAN subnet {lan_network}/{lan_prefix} default-router {lan_ip}\n"
            f"set service dhcp-server shared-network-name LAN subnet {lan_network}/{lan_prefix} name-server {lan_ip}\n"
            f"set service dhcp-server shared-network-name LAN subnet {lan_network}/{lan_prefix} range 0 start {d_start}\n"
            f"set service dhcp-server shared-network-name LAN subnet {lan_network}/{lan_prefix} range 0 stop {d_stop}")
    else:
        dhcp_server_block = ""
    return {"wan_addr": wan_addr, "wan_if": wan_if,
            "lan_if_block": lan_if_block,
            "wan_route_block": wan_route_block,
            "dhcp_server_block": dhcp_server_block}


# =====================================================================
# GUI 主题
# =====================================================================
BG        = "#f0f4f8"
BG_PANEL  = "#ffffff"
BG_INPUT  = "#f8fafc"
BG_HDR    = "#1e3a5f"
ACCENT_HK = "#e07b2a"
ACCENT_US = "#0077b6"
FG        = "#1a2b3c"
FG_DIM    = "#7a96ad"
FG_BRT    = "#ffffff"
BORDER    = "#c8d8e8"
FONT_MONO = ("Consolas", 10)
FONT_UI   = ("微软雅黑", 10)
FONT_HDR  = ("微软雅黑", 11, "bold")
FONT_TINY = ("Consolas",  9)

root = tk.Tk()
root.title("Epoch FastIP 配置生成工具")
# 窗口尺寸不超过屏幕，居中显示，确保底部按钮可见
_sw = root.winfo_screenwidth()
_sh = root.winfo_screenheight()
_ww = min(1300, int(_sw * 0.88))
_wh = min(880,  int(_sh * 0.86))
root.geometry(f"{_ww}x{_wh}+{(_sw-_ww)//2}+{max(0,(_sh-_wh)//2-20)}")
root.minsize(900, 640)
root.configure(bg=BG)

sty = ttk.Style(root)
sty.theme_use("clam")
sty.configure("TPanedwindow", background=BG)
sty.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG,
               arrowcolor=FG_DIM, relief="flat", borderwidth=0, width=8)
sty.map("Vertical.TScrollbar", background=[("active", ACCENT_US)])
sty.configure("TNotebook", tabposition="nw", background=BG_HDR)
sty.configure("TNotebook.Tab", background=BG_HDR, foreground="#7aafd4",
               font=("微软雅黑", 11, "bold"), padding=[20, 8])
sty.map("TNotebook.Tab",
        background=[("selected", BG), ("active", "#2a4a6f")],
        foreground=[("selected", ACCENT_US), ("active", FG_BRT)])

def make_text(parent, readonly=False, **kw):
    vsb = ttk.Scrollbar(parent, orient="vertical", style="Vertical.TScrollbar")
    vsb.pack(side="right", fill="y")
    t = tk.Text(parent, font=FONT_MONO, bg=BG_INPUT, fg=FG,
                insertbackground=ACCENT_US, selectbackground=ACCENT_US,
                selectforeground=BG, relief="flat", bd=0, padx=10, pady=6,
                yscrollcommand=vsb.set,
                state=(tk.DISABLED if readonly else tk.NORMAL), **kw)
    t.pack(side="left", fill="both", expand=True)
    vsb.configure(command=t.yview)
    menu = tk.Menu(t, tearoff=0, bg=BG_PANEL, fg=FG,
                   activebackground=ACCENT_US, activeforeground=FG_BRT,
                   font=FONT_UI, bd=0, relief="flat")
    menu.add_command(label="复制",  command=lambda: t.event_generate("<<Copy>>"))
    menu.add_command(label="剪切",  command=lambda: t.event_generate("<<Cut>>"))
    menu.add_command(label="粘贴",  command=lambda: t.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="全选",  command=lambda: (t.tag_add("sel", "1.0", "end"), None))
    menu.add_separator()
    menu.add_command(label="撤销",  command=lambda: t.event_generate("<<Undo>>"))
    menu.add_command(label="重做",  command=lambda: t.event_generate("<<Redo>>"))
    def _show_menu(event):
        has_sel = bool(t.tag_ranges("sel"))
        menu.entryconfig("复制", state="normal" if has_sel else "disabled")
        menu.entryconfig("剪切", state="normal" if (has_sel and not readonly) else "disabled")
        menu.entryconfig("粘贴", state="normal" if not readonly else "disabled")
        menu.entryconfig("撤销", state="normal" if not readonly else "disabled")
        menu.entryconfig("重做", state="normal" if not readonly else "disabled")
        try: menu.tk_popup(event.x_root, event.y_root)
        finally: menu.grab_release()
    t.bind("<Button-3>", _show_menu)
    t.bind("<Button-2>", _show_menu)
    t.config(undo=True, maxundo=50)
    return t

def flat_btn(parent, text, color):
    darker = {"#e07b2a": "#b85e1a", "#0077b6": "#005f94",
              "#6c757d": "#565e64", "#16a085": "#0e7060"}.get(color, color)
    b = tk.Label(parent, text=text, font=("微软雅黑", 10, "bold"),
                 bg=color, fg=FG_BRT, padx=14, pady=7, cursor="hand2", relief="flat")
    b.bind("<Enter>", lambda e: b.config(bg=darker))
    b.bind("<Leave>", lambda e: b.config(bg=color))
    return b

def mk_entry(parent, row, col, placeholder, accent, width=20):
    e = tk.Entry(parent, font=FONT_MONO, bg=BG_INPUT, fg=FG_DIM,
                 insertbackground=accent, relief="flat", bd=0,
                 highlightthickness=1, highlightbackground=BORDER,
                 highlightcolor=accent, width=width)
    e.grid(row=row, column=col, sticky="ew", pady=3, padx=(0, 8))
    e.insert(0, placeholder)
    def _fi(ev, en=e, p=placeholder):
        if en.get() == p: en.delete(0, tk.END); en.config(fg=FG)
    def _fo(ev, en=e, p=placeholder):
        if not en.get().strip(): en.insert(0, p); en.config(fg=FG_DIM)
    e.bind("<FocusIn>",  _fi)
    e.bind("<FocusOut>", _fo)
    return e

# ── 根布局 ──────────────────────────────────────────────────────────
root.columnconfigure(0, weight=1)
root.rowconfigure(1, weight=1)

hdr = tk.Frame(root, bg=BG_HDR, height=46)
hdr.grid(row=0, column=0, sticky="ew"); hdr.grid_propagate(False)
tk.Frame(hdr, bg="#16a085", width=4).pack(side="left", fill="y")
tk.Label(hdr, text="  Epoch FastIP", font=("微软雅黑", 13, "bold"),
         bg=BG_HDR, fg=FG_BRT).pack(side="left")
tk.Label(hdr, text=" 配置生成工具-单机", font=FONT_HDR, bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=4)
right_badges = tk.Frame(hdr, bg=BG_HDR)
right_badges.pack(side="right", padx=14, pady=10)
badge_font = ("寰蒋闆呴粦", 9, "bold")
tk.Label(right_badges, text=" v8 ", font=badge_font, bg="#16a085", fg=FG_BRT,
         padx=12, pady=4).pack(side="right")
tk.Label(right_badges, text=" 深圳工程部系列宝典 ", font=badge_font, bg="#6c757d", fg=FG_BRT,
         padx=10, pady=4).pack(side="right", padx=(0, 8))

main_nb = ttk.Notebook(root)
main_nb.grid(row=1, column=0, sticky="nsew")
tab_hk = tk.Frame(main_nb, bg=BG)
tab_us = tk.Frame(main_nb, bg=BG)
tab_fl = tk.Frame(main_nb, bg=BG)
main_nb.add(tab_hk, text="  🇭🇰 HK 出口  ")
main_nb.add(tab_us, text="  非香港出口  ")
main_nb.add(tab_fl, text="  🔗 其他小功能  ")

# =====================================================================
# 初始化配置面板（紧凑版 - 含内网段/LAN网关/回程路由）
# =====================================================================
def build_net_panel(parent, accent, wan_dhcp_default=False, lan_dhcp_default=True,
                    is_hk: bool = False):
    hdr_f = tk.Frame(parent, bg=accent, height=26)
    hdr_f.pack(fill="x"); hdr_f.pack_propagate(False)
    tk.Frame(hdr_f, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(hdr_f, text="  初始化配置", font=("微软雅黑",10,"bold"), bg=accent, fg=FG_BRT).pack(side="left", pady=2)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

    body = tk.Frame(parent, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=2, pady=2)

    def GK(dname: str):
        """dname 为 DEFAULT_WAN_CIDR 形式。HK 页读 HK_DEFAULT_*，US 页读 DEFAULT_*。"""
        g = globals()
        if is_hk:
            hk = "HK_" + dname
            if hk in g:
                return g[hk]
        return g.get(dname)

    # 使用 6 列紧凑布局
    # col: 0=label  1=value  2=label  3=value  4=label  5=value
    body.columnconfigure(1, weight=1)
    body.columnconfigure(2, minsize=92)  # 保证 WAN网关/LAN网关 标签完整显示
    body.columnconfigure(3, weight=1)
    # 初始化区域所有标签统一使用黑色，旁挂/禁用时再单独置灰
    LBL = dict(font=("微软雅黑",9), bg=BG_PANEL, fg=FG, anchor="e")
    PAD = dict(padx=(2,4), pady=2)

    def small_entry(row, col, ph_factory, w=14, sticky_override=None):
        if not callable(ph_factory):
            _fixed = "" if ph_factory is None else str(ph_factory)
            ph_factory = lambda: _fixed

        def _ph():
            p = ph_factory()
            return "" if p is None else str(p)

        e = tk.Entry(body, font=("Consolas",9), bg=BG_INPUT, fg=FG_DIM,
                     insertbackground=accent, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=accent, width=w)
        e.grid(row=row, column=col, sticky=sticky_override or "ew", padx=(0,4), pady=2)
        e.insert(0, _ph())

        def _fi(_ev, en=e):
            p = _ph()
            if en.get() == p:
                en.delete(0, tk.END)
                en.config(fg=FG)

        def _fo(_ev, en=e):
            if not en.get().strip():
                en.insert(0, _ph())
                en.config(fg=FG_DIM)

        e.bind("<FocusIn>", _fi)
        e.bind("<FocusOut>", _fo)
        return e

    def toggle_btn(row, col):
        b = tk.Label(body, font=("微软雅黑",8,"bold"),
                     padx=8, pady=3, cursor="hand2", relief="flat")
        b.grid(row=row, column=col, sticky="w", padx=(0,4), pady=2)
        return b

    r = 0
    # ── Hostname（跨全行）
    tk.Label(body, text="Hostname", **LBL, width=8).grid(row=r, column=0, sticky="e", **PAD)
    e_host = small_entry(r, 1, "留空则用LineID", 18)
    e_host.grid(columnspan=3); r += 1

    # ── WAN 口 + DHCP（同行）
    tk.Frame(body, bg=BORDER, height=1).grid(row=r, column=0, columnspan=4, sticky="ew", pady=(3,1)); r += 1
    tk.Label(body, text="WAN口", **LBL, width=8).grid(row=r, column=0, sticky="e", **PAD)
    wan_eth_var = tk.StringVar(value=str(GK("DEFAULT_WAN_ETH") or "0").strip() or "0")
    wan_row = tk.Frame(body, bg=BG_PANEL); wan_row.grid(row=r, column=1, sticky="w", pady=2)
    tk.Label(wan_row, text="eth", font=("Consolas",9), bg=BG_PANEL, fg=FG_DIM).pack(side="left")
    e_wan_eth = tk.Entry(wan_row, textvariable=wan_eth_var, font=("Consolas",9),
                         bg=BG_INPUT, fg=FG, width=3, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=accent)
    e_wan_eth.pack(side="left", padx=(0,6))
    tk.Label(body, text="DHCP", **LBL, width=5).grid(row=r, column=2, sticky="e", **PAD)
    _wd = GK("DEFAULT_WAN_DHCP")
    wan_dhcp_var = tk.BooleanVar(value=bool(_wd) if isinstance(_wd, bool) else wan_dhcp_default)
    wan_dhcp_btn = toggle_btn(r, 3); r += 1

    # ── WAN IP + WAN网关（同行，输入框缩短且不拉伸，保证右侧标签可见）
    tk.Label(body, text="WAN IP", **LBL, width=8).grid(row=r, column=0, sticky="e", **PAD)
    e_wan_ip = small_entry(r, 1, lambda: str(GK("DEFAULT_WAN_CIDR") or ""), 24, sticky_override="w")
    tk.Label(body, text="WAN网关", **LBL).grid(row=r, column=2, sticky="e", **PAD)
    e_wan_gw = small_entry(r, 3, lambda: str(GK("DEFAULT_WAN_GW") or ""), 20, sticky_override="w"); r += 1

    # ── LAN 口 + DHCP + 是否旁挂（同行）
    tk.Frame(body, bg=BORDER, height=1).grid(row=r, column=0, columnspan=4, sticky="ew", pady=(3,1)); r += 1
    lbl_lan_port = tk.Label(body, text="LAN口", **LBL, width=8)
    lbl_lan_port.grid(row=r, column=0, sticky="e", **PAD)
    lan_eth_var = tk.StringVar(value=str(GK("DEFAULT_LAN_ETH") or "5").strip() or "5")
    lan_row = tk.Frame(body, bg=BG_PANEL); lan_row.grid(row=r, column=1, sticky="w", pady=2)
    tk.Label(lan_row, text="eth", font=("Consolas",9), bg=BG_PANEL, fg=FG_DIM).pack(side="left")
    e_lan_eth = tk.Entry(lan_row, textvariable=lan_eth_var, font=("Consolas",9),
                         bg=BG_INPUT, fg=FG, width=3, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=accent)
    e_lan_eth.pack(side="left", padx=(0,6))
    lbl_lan_dhcp = tk.Label(body, text="DHCP", **LBL, width=5)
    lbl_lan_dhcp.grid(row=r, column=2, sticky="e", **PAD)
    _ld = GK("DEFAULT_LAN_DHCP")
    lan_dhcp_var = tk.BooleanVar(value=bool(_ld) if isinstance(_ld, bool) else lan_dhcp_default)
    lan_dhcp_btn = toggle_btn(r, 3)
    tk.Label(body, text="旁挂", **LBL, width=4).grid(row=r, column=4, sticky="e", padx=(8,2), pady=2)
    bypass_var = tk.BooleanVar(value=False)
    bypass_btn = toggle_btn(r, 5); r += 1

    # ── LAN IP + LAN网关（同行，旁挂时变灰）
    lbl_lan_ip = tk.Label(body, text="LAN IP", **LBL, width=8)
    lbl_lan_ip.grid(row=r, column=0, sticky="e", **PAD)
    e_lan_ip = small_entry(r, 1, lambda: str(GK("DEFAULT_LAN_CIDR") or ""), 24, sticky_override="w")
    lbl_lan_gw = tk.Label(body, text="LAN网关", **LBL)
    lbl_lan_gw.grid(row=r, column=2, sticky="e", **PAD)
    e_lan_gw = small_entry(
        r, 3,
        lambda: (str(GK("DEFAULT_LAN_GW") or "").strip() or _normalize_lan_gw_from_cidr(str(GK("DEFAULT_LAN_CIDR") or ""))),
        20, sticky_override="w")
    r += 1

    # ── 客户内网段
    tk.Frame(body, bg=BORDER, height=1).grid(row=r, column=0, columnspan=4, sticky="ew", pady=(3,1)); r += 1
    tk.Label(body, text="内网段", font=("微软雅黑",9), bg=BG_PANEL, fg=FG_DIM, anchor="ne", width=8).grid(row=r, column=0, sticky="ne", **PAD)
    inner_wrap = tk.Frame(body, bg=BG_INPUT, highlightthickness=1,
                          highlightbackground=BORDER, highlightcolor=accent)
    inner_wrap.grid(row=r, column=1, columnspan=3, sticky="ew", padx=(0,4), pady=1)
    e_inner = tk.Text(inner_wrap, font=("Consolas",9), bg=BG_INPUT, fg=FG,
                      height=3, relief="flat", bd=0, padx=4, pady=2,
                      insertbackground=accent)
    e_inner.pack(fill="both", expand=True)
    e_inner.insert("1.0", str(GK("DEFAULT_INNER_NETS") or ""))
    tk.Label(body, text="换行或逗号分隔多条", font=("Consolas",7),
             bg=BG_PANEL, fg=FG_DIM, anchor="w").grid(
             row=r+1, column=1, columnspan=3, sticky="w", padx=(0,4))
    r += 2

    # ── 内网段状态 + 回程路由（同一行：提示在左、开关在右，省一行高度）
    rr_strip = tk.Frame(body, bg=BG_PANEL)
    rr_strip.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(0, 0))
    rr_strip.columnconfigure(0, weight=1)
    r += 1

    status_inner_var = tk.StringVar(value="")
    lbl_inner = tk.Label(
        rr_strip, textvariable=status_inner_var,
        font=("微软雅黑", 8), bg=BG_PANEL,
        anchor="w", wraplength=260, justify="left",
    )
    lbl_inner.grid(row=0, column=0, sticky="w", padx=(4, 4))

    rr_tail = tk.Frame(rr_strip, bg=BG_PANEL)
    rr_tail.grid(row=0, column=1, sticky="e", padx=(4, 4))
    tk.Label(rr_tail, text="回程路由", **LBL, width=8).pack(side="left", padx=(0, 4))
    _rr0 = GK("DEFAULT_GEN_RETURN_ROUTE")
    return_route_var = tk.BooleanVar(value=bool(_rr0) if isinstance(_rr0, bool) else False)
    rr_btn = tk.Label(rr_tail, font=("微软雅黑", 8, "bold"), padx=8, pady=3, cursor="hand2", relief="flat")
    rr_btn.pack(side="left")
    rr_tail.grid_remove()  # 默认隐藏，有"需回程"网段时再显示

    # ── 逻辑函数 ──────────────────────────────────────────────────
    def _real_wan_cidr():
        v = e_wan_ip.get().strip()
        if v in ("", "dhcp"):
            return ""
        return v

    def _real_wan_gw():
        v = e_wan_gw.get().strip()
        if v in ("", "dhcp"):
            return ""
        return v

    def _lan_ph():
        return str(GK("DEFAULT_LAN_CIDR") or "")

    def _lan_gw_ph():
        raw = str(GK("DEFAULT_LAN_GW") or "").strip()
        if raw:
            return _normalize_lan_gw_from_cidr(_lan_ph(), raw) or raw
        return _normalize_lan_gw_from_cidr(_lan_ph(), _lan_ph())

    def _real_lan_cidr():
        v = e_lan_ip.get().strip()
        pl = _lan_ph()
        return "" if v in (pl, "") else v

    def _real_lan_gw():
        v = e_lan_gw.get().strip()
        if not v:
            raw = _real_lan_cidr() or _lan_ph()
            try:
                return str(ipaddress.ip_interface(raw).ip)
            except Exception:
                return ""
        return _normalize_lan_gw_from_cidr(_real_lan_cidr() or _lan_ph(), v) or v

    def _update_bypass_ui():
        on = bypass_var.get()
        bypass_btn.config(text="● 旁挂" if on else "○ 非旁挂",
                         bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)
        state = tk.DISABLED if on else tk.NORMAL
        fg = FG_DIM if on else FG
        # 旁挂时清空 LAN 相关输入并禁用；非旁挂时如为空则恢复默认占位
        if on:
            for w in (e_lan_eth, e_lan_ip, e_lan_gw):
                w.config(state=tk.NORMAL)
                w.delete(0, tk.END)
                w.config(state=tk.DISABLED)
        else:
            e_lan_eth.config(state=tk.NORMAL)
            if not e_lan_eth.get().strip():
                e_lan_eth.insert(0, "5")
            e_lan_ip.config(state=tk.NORMAL)
            if not e_lan_ip.get().strip():
                e_lan_ip.insert(0, _lan_ph())
                e_lan_ip.config(fg=FG_DIM)
            e_lan_gw.config(state=tk.NORMAL)
            if not e_lan_gw.get().strip():
                e_lan_gw.insert(0, _lan_gw_ph()); e_lan_gw.config(fg=FG_DIM)
        for lbl in (lbl_lan_port, lbl_lan_dhcp, lbl_lan_ip, lbl_lan_gw):
            lbl.config(fg=fg)
        if on:
            lan_dhcp_btn.config(fg=FG_DIM)
        else:
            _update_lan_dhcp()

    def _update_rr_btn():
        on = return_route_var.get()
        rr_btn.config(text="● 生成回程路由" if on else "○ 不生成",
                      bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)

    def _check_inner(*_):
        inner_raw = e_inner.get("1.0", tk.END)
        nets      = _parse_inner_nets(inner_raw)
        if not nets:
            status_inner_var.set("⚠  未填写有效内网段")
            lbl_inner.config(fg="#c0392b"); rr_tail.grid_remove(); return
        if bypass_var.get():
            wan_raw = _real_wan_cidr() or str(GK("DEFAULT_WAN_CIDR") or "")
            outside = _nets_needing_return_by_network(wan_raw, nets)
            if not outside:
                status_inner_var.set("✓  WAN IP 在所有内网段内")
                lbl_inner.config(fg="#16a085"); rr_tail.grid_remove()
            else:
                preview = " ".join(outside[:2]) + ("…" if len(outside) > 2 else "")
                status_inner_var.set(f"⚠  需回程路由 {len(outside)} 条（下一跳 WAN 网关）：{preview}")
                lbl_inner.config(fg="#e07b2a")
                rr_tail.grid(); _update_rr_btn()
        else:
            lan_raw = _real_lan_cidr() or _lan_ph()
            outside = _nets_needing_return_by_network(lan_raw, nets)
            if not outside:
                status_inner_var.set("✓  LAN IP 在所有内网段内")
                lbl_inner.config(fg="#16a085"); rr_tail.grid_remove()
            else:
                preview = " ".join(outside[:2]) + ("…" if len(outside) > 2 else "")
                status_inner_var.set(f"⚠  需回程路由 {len(outside)} 条：{preview}")
                lbl_inner.config(fg="#e07b2a")
                rr_tail.grid(); _update_rr_btn()

    rr_btn.bind("<Button-1>", lambda e: (
        return_route_var.set(not return_route_var.get()), _update_rr_btn()))

    bypass_btn.bind("<Button-1>", lambda e: (
        bypass_var.set(not bypass_var.get()), _update_bypass_ui(), _check_inner()))

    e_lan_ip.bind("<FocusOut>",  _check_inner)
    e_lan_ip.bind("<KeyRelease>", _check_inner)
    e_wan_ip.bind("<FocusOut>",  _check_inner)
    e_wan_ip.bind("<KeyRelease>", _check_inner)
    e_inner.bind("<KeyRelease>",  _check_inner)
    e_inner.bind("<FocusOut>",    _check_inner)
    root.after(120, _check_inner)

    wan_saved = {"ip": "", "gw": ""}

    def _set_entry_value(entry, value, dim=False):
        entry.config(state=tk.NORMAL)
        entry.delete(0, tk.END)
        entry.insert(0, value)
        entry.config(fg=FG_DIM if dim else FG)

    def _update_wan_dhcp():
        on = wan_dhcp_var.get()
        wan_dhcp_btn.config(text="● 开" if on else "○ 关",
                            bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)
        if on:
            cur_ip = e_wan_ip.get().strip()
            if cur_ip and cur_ip not in (str(GK("DEFAULT_WAN_CIDR") or ""), "dhcp"):
                wan_saved["ip"] = cur_ip
            cur_gw = e_wan_gw.get().strip()
            if cur_gw and cur_gw not in (str(GK("DEFAULT_WAN_GW") or ""), "dhcp"):
                wan_saved["gw"] = cur_gw
            _set_entry_value(e_wan_ip, "dhcp", dim=True)
            _set_entry_value(e_wan_gw, "dhcp", dim=True)
            e_wan_ip.config(state=tk.DISABLED)
            e_wan_gw.config(state=tk.DISABLED)
        else:
            ip_restore = wan_saved["ip"] if wan_saved["ip"] else str(GK("DEFAULT_WAN_CIDR") or "")
            gw_restore = wan_saved["gw"] if wan_saved["gw"] else str(GK("DEFAULT_WAN_GW") or "")
            _set_entry_value(e_wan_ip, ip_restore, dim=not bool(wan_saved["ip"]))
            _set_entry_value(e_wan_gw, gw_restore, dim=not bool(wan_saved["gw"]))
            e_wan_ip.config(state=tk.NORMAL)
            e_wan_gw.config(state=tk.NORMAL)

    def _update_lan_dhcp():
        on = lan_dhcp_var.get()
        lan_dhcp_btn.config(text="● 开" if on else "○ 关",
                            bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)

    _update_wan_dhcp(); _update_lan_dhcp(); _update_rr_btn(); _update_bypass_ui()
    wan_dhcp_btn.bind("<Button-1>", lambda e: (wan_dhcp_var.set(not wan_dhcp_var.get()), _update_wan_dhcp()))
    lan_dhcp_btn.bind("<Button-1>", lambda e: (lan_dhcp_var.set(not lan_dhcp_var.get()), _update_lan_dhcp()))

    # ── 对外接口 ──────────────────────────────────────────────────
    def _pv(entry, placeholder):
        v = entry.get().strip(); return "" if v == placeholder else v

    def get_hostname():
        v = e_host.get().strip(); return "" if v in ("留空则用LineID","") else v

    def get_raw_for_validate():
        """返回 (wan_ip, wan_gw, lan_ip, lan_gw, inner_raw) 供 v6 网络格式校验。"""
        # When WAN is DHCP, the input boxes show "dhcp" (non-IP string).
        # For v6 format validation, treat WAN IP/GW as placeholders to skip checks.
        if wan_dhcp_var.get():
            wan_ip = str(GK("DEFAULT_WAN_CIDR") or "")
            wan_gw = str(GK("DEFAULT_WAN_GW") or "")
        else:
            wan_ip = e_wan_ip.get().strip()
            wan_gw = e_wan_gw.get().strip()
        return (wan_ip, wan_gw,
                e_lan_ip.get().strip(), e_lan_gw.get().strip(),
                e_inner.get("1.0", tk.END))

    def get_net_cfg(is_us=False):
        wan_eth = wan_eth_var.get().strip() or "0"
        lan_eth = lan_eth_var.get().strip() or "5"
        bypass = bypass_var.get()
        ph_w, ph_wg = str(GK("DEFAULT_WAN_CIDR") or ""), str(GK("DEFAULT_WAN_GW") or "")
        ph_l = _lan_ph()
        cfg = build_wan_lan_blocks(
            f"eth{wan_eth}", wan_dhcp_var.get(),
            _pv(e_wan_ip, ph_w), _pv(e_wan_gw, ph_wg),
            f"eth{lan_eth}", lan_dhcp_var.get(),
            _pv(e_lan_ip, ph_l), is_us=is_us, bypass=bypass)
        inner_raw = e_inner.get("1.0", tk.END)
        nets      = _parse_inner_nets(inner_raw)
        rr_lines  = []
        if bypass:
            wan_raw = _real_wan_cidr() or str(GK("DEFAULT_WAN_CIDR") or "")
            gw = _real_wan_gw() or str(GK("DEFAULT_WAN_GW") or "")
            outside = _nets_needing_return_by_network(wan_raw, nets)
            if outside and return_route_var.get():
                if wan_dhcp_var.get():
                    for net in outside:
                        rr_lines.append(f"set protocols static route {net} dhcp-interface eth{wan_eth}")
                elif gw:
                    for net in outside:
                        rr_lines.append(f"set protocols static route {net} next-hop {gw}")
            cfg["lan_cidr"] = wan_raw
            cfg["lan_gw"] = gw
            cfg["wan_cidr"] = wan_raw
            cfg["wan_gw"] = gw
        else:
            lan_raw = _real_lan_cidr() or _lan_ph()
            outside = _nets_needing_return_by_network(lan_raw, nets)
            if outside and return_route_var.get():
                gw = _real_lan_gw()
                if gw:
                    for net in outside:
                        rr_lines.append(f"set protocols static route {net} next-hop {gw}")
            cfg["lan_cidr"] = lan_raw
            cfg["lan_gw"] = _real_lan_gw()
            cfg["wan_cidr"] = _real_wan_cidr() or str(GK("DEFAULT_WAN_CIDR") or "")
            cfg["wan_gw"] = _real_wan_gw()
        cfg["return_routes_block"] = "\n".join(rr_lines)
        cfg["inner_nets"] = nets
        cfg["return_route_enabled"] = return_route_var.get()
        cfg["bypass_mode"] = bypass
        cfg["wan_eth_num"] = wan_eth
        cfg["lan_eth_num"] = lan_eth
        return cfg

    def reset_net():
        g0 = globals()
        px = "HK_DEFAULT_" if is_hk else "DEFAULT_"
        e_host.delete(0,tk.END); e_host.insert(0,"留空则用LineID"); e_host.config(fg=FG_DIM)
        wan_eth_var.set(str(g0.get(px + "WAN_ETH", "0")).strip() or "0")
        lan_eth_var.set(str(g0.get(px + "LAN_ETH", "5")).strip() or "5")
        wan_dhcp_var.set(bool(g0.get(px + "WAN_DHCP", wan_dhcp_default)))
        lan_dhcp_var.set(bool(g0.get(px + "LAN_DHCP", lan_dhcp_default)))
        _update_wan_dhcp(); _update_lan_dhcp()
        bypass_var.set(False); _update_bypass_ui()
        for e, ph in (
            (e_wan_ip, str(GK("DEFAULT_WAN_CIDR") or "")),
            (e_wan_gw, str(GK("DEFAULT_WAN_GW") or "")),
            (e_lan_ip, _lan_ph()),
        ):
            e.delete(0, tk.END)
            e.insert(0, ph)
            e.config(fg=FG_DIM)
        _lgw = str(g0.get(px + "LAN_GW", "")).strip() or _lan_gw_ph()
        e_lan_gw.delete(0, tk.END)
        e_lan_gw.insert(0, _lgw)
        e_lan_gw.config(fg=FG_DIM)
        _inner = str(g0.get(px + "INNER_NETS", "") or "")
        e_inner.delete("1.0", tk.END)
        e_inner.insert("1.0", _inner)
        _rrk = px + "GEN_RETURN_ROUTE"
        return_route_var.set(bool(g0.get(_rrk, False)))
        _update_rr_btn()
        rr_tail.grid_remove()
        root.after(50, _check_inner)

    return get_hostname, get_net_cfg, reset_net, get_raw_for_validate


# =====================================================================
# 接入方式胶囊切换条（风格与飞连/新增出口/域名分流三段式保持一致）
# =====================================================================
def _add_mode_bar(parent, accent, mode_var, row=0):
    """在 parent 的 grid row=row 处插入「接入方式」OpenVPN / IPSec 胶囊切换条。"""
    bar = tk.Frame(parent, bg=accent, height=34)
    bar.grid(row=row, column=0, sticky="ew", padx=6, pady=(4, 0))
    bar.grid_propagate(False)
    tk.Frame(bar, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(bar, text="  接入方式", font=("微软雅黑", 10, "bold"),
             bg=accent, fg=FG_BRT).pack(side="left", padx=(8, 8))
    capsule = tk.Frame(bar, bg=BORDER, padx=2, pady=2)
    capsule.pack(side="left")
    btn_open = tk.Label(capsule, text="OpenVPN", font=("微软雅黑", 10, "bold"),
                        bg=BG_INPUT, fg=FG, padx=14, pady=3, cursor="hand2")
    btn_open.pack(side="left")
    btn_ips = tk.Label(capsule, text="IPSec", font=("微软雅黑", 10, "bold"),
                       bg=BG_INPUT, fg=FG, padx=14, pady=3, cursor="hand2")
    btn_ips.pack(side="left", padx=(2, 0))

    def _refresh(*_):
        m = mode_var.get()
        btn_open.config(bg=accent if m == "OpenVPN" else BG_INPUT,
                        fg=FG_BRT if m == "OpenVPN" else FG)
        btn_ips.config(bg=accent if m == "IPSec" else BG_INPUT,
                       fg=FG_BRT if m == "IPSec" else FG)

    btn_open.bind("<Button-1>", lambda e: mode_var.set("OpenVPN"))
    btn_ips.bind("<Button-1>", lambda e: mode_var.set("IPSec"))
    mode_var.trace_add("write", _refresh)
    _refresh()
    return bar


# =====================================================================
# Tab 框架构建器（四象限可拖动布局）
# 左上：备注/示例  右上：初始化配置  左下：数据输入  右下：生成结果
# =====================================================================
def build_tab_shell(tab, accent, note_text, example_text, init_parent):
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(0, weight=1)   # 主PanedWindow占满

    # 垂直 PanedWindow（上半 | 下半）
    v_pane = ttk.PanedWindow(tab, orient="vertical")
    v_pane.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4,0))

    # 上半：水平 PanedWindow（备注 | 初始化）
    top_h = ttk.PanedWindow(v_pane, orient="horizontal")
    v_pane.add(top_h, weight=1)

    # 左上：备注/示例
    notes_f = tk.Frame(top_h, bg=BG_PANEL,
                       highlightbackground=BORDER, highlightthickness=1)
    top_h.add(notes_f, weight=1)
    notes_f.rowconfigure(0, weight=1); notes_f.columnconfigure(0, weight=1)
    nb = ttk.Notebook(notes_f); nb.grid(row=0, column=0, sticky="nsew")
    tn = tk.Frame(nb, bg=BG_PANEL); nb.add(tn, text="  备注说明  ")
    nt = tk.Text(tn, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat",
                 bd=0, padx=10, pady=4)
    nt.pack(fill="both", expand=True); nt.insert(tk.END, note_text); nt.config(state="disabled")
    te = tk.Frame(nb, bg=BG_PANEL); nb.add(te, text="  填写示例  ")
    ew = tk.Frame(te, bg=BG_PANEL); ew.pack(fill="both", expand=True)
    evsb = ttk.Scrollbar(ew, orient="vertical", style="Vertical.TScrollbar"); evsb.pack(side="right", fill="y")
    et = tk.Text(ew, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat",
                 bd=0, padx=10, pady=4, yscrollcommand=evsb.set)
    et.pack(side="left", fill="both", expand=True); evsb.config(command=et.yview)
    et.insert(tk.END, example_text); et.config(state="disabled")

    # 右上：初始化配置
    init_f = tk.Frame(top_h, bg=BG_PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
    top_h.add(init_f, weight=2)
    init_parent[0] = init_f

    # 下半：水平 PanedWindow（数据输入 | 生成结果）
    bot_h = ttk.PanedWindow(v_pane, orient="horizontal")
    v_pane.add(bot_h, weight=1)   # 上下各占50%

    def make_bot_side(label_text):
        f = tk.Frame(bot_h, bg=BG_PANEL,
                     highlightbackground=BORDER, highlightthickness=1)
        bot_h.add(f, weight=1)
        f.rowconfigure(1, weight=1); f.columnconfigure(0, weight=1)
        h = tk.Frame(f, bg=accent, height=26); h.grid(row=0, column=0, sticky="ew")
        h.grid_propagate(False)
        tk.Frame(h, bg=FG_BRT, width=3).pack(side="left", fill="y")
        tk.Label(h, text=f"  {label_text}", font=FONT_HDR, bg=accent, fg=FG_BRT, pady=2).pack(side="left")
        inner = tk.Frame(f, bg=BG_INPUT); inner.grid(row=1, column=0, sticky="nsew")
        return inner

    li = make_bot_side("数据头输入")
    ri = make_bot_side("生成结果")
    left_text    = make_text(li)
    right_output = make_text(ri, readonly=False)

    # 限制上半区最小高度，避免嵌套在 hk_content/us_content 内时首次 sash 计算过小，
    # 导致下半区「生成结果」条上移遮挡「初始化配置」底部（内网段等）。
    try:
        v_pane.pane(top_h, minsize=280)
    except tk.TclError:
        pass

    # 上 55% / 下 45%：上下区高度分配（备注/初始化 | 数据头/生成结果）
    def _init_sash(vp=v_pane, _tab=tab):
        try:
            _tab.update_idletasks()
            total = vp.winfo_height()
            if total > 100:
                vp.sashpos(0, int(total * 0.55))
        except Exception:
            pass

    for _delay in (50, 150, 400, 800):
        tab.after(_delay, _init_sash)

    # 状态栏（固定，始终在底部可见）
    tk.Frame(tab, bg=BORDER, height=1).grid(row=1, column=0, sticky="ew")
    btm = tk.Frame(tab, bg=BG_HDR, height=42)
    btm.grid(row=2, column=0, sticky="ew"); btm.grid_propagate(False)
    tab.rowconfigure(1, weight=0); tab.rowconfigure(2, weight=0)
    status_var = tk.StringVar(value="就绪  ·  等待输入业务数据")
    tk.Label(btm, textvariable=status_var, font=FONT_TINY, bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=12)
    btn_exp = flat_btn(btm, "导出 TXT", "#16a085"); btn_exp.pack(side="right", padx=(0,12), pady=7)
    btn_gen = flat_btn(btm, "⚡  生成配置", accent);  btn_gen.pack(side="right", padx=(0,5), pady=7)
    btn_rst = flat_btn(btm, "↺  恢复初始", "#6c757d"); btn_rst.pack(side="right", padx=(0,5), pady=7)
    return left_text, right_output, status_var, btn_gen, btn_exp, btn_rst, et

# =====================================================================
# Tab HK
# =====================================================================
HK_NOTE = (
    "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
    "• lan的dhcp是你开给别人的。\n"
    "• BGP更新源：默认使用 CE LOIP 。 如果要建公网的，请自行调整。\n"
    "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
    "• 请自行修改nat/dns/mtu等部分。\n"
    "• nat只会打第一个出口ip的。其余ip请自行添加。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)
HK_EXAMPLE = (
    "MAIN\nlineid: 603642Ar3\n主PE： szd-natflr2\nWANIP: 10.40.25.188/30\n"
    "TUNNEL: vtun40826\nDocking：121.12.81.3\nCE LOIP: 10.20.186.235\n"
    "HKIP：10.60.241.250 --> 103.48.141.157\nBGPSERVER IP： 10.10.99.168,10.10.99.169\n\n"
    "BACKUP\nPE：szc-natbk10\nWANIP: 10.41.25.188/30\nTUNNEL: vtun50826\n"
    "Docking： 120.133.129.72\nCE LOIP: 10.20.186.235\nHKIP：10.60.241.250 --> 103.48.141.157\n"
    "BGPSERVER IP：10.10.99.198,10.10.99.199\n"
)

hk_access_mode_var = tk.StringVar(value="OpenVPN")
tab_hk.columnconfigure(0, weight=1)
tab_hk.rowconfigure(0, weight=0)
tab_hk.rowconfigure(1, weight=1)
_add_mode_bar(tab_hk, ACCENT_HK, hk_access_mode_var, row=0)
hk_content = tk.Frame(tab_hk, bg=BG)
hk_content.grid(row=1, column=0, sticky="nsew")
hk_init_container = [None]
hk_left, hk_right, hk_status, hk_gen, hk_exp, hk_rst, hk_example_et = build_tab_shell(
    hk_content, ACCENT_HK, HK_NOTE, HK_EXAMPLE, hk_init_container)
hk_get_hostname, hk_get_net, hk_reset_net, hk_get_raw = build_net_panel(
    hk_init_container[0], ACCENT_HK, wan_dhcp_default=False, lan_dhcp_default=True,
    is_hk=True)

def _hk_update_example(*_):
    m = hk_access_mode_var.get()
    txt = HK_EXAMPLE_IPSEC if m == "IPSec" else HK_EXAMPLE
    hk_example_et.config(state="normal")
    hk_example_et.delete("1.0", tk.END)
    hk_example_et.insert(tk.END, txt)
    hk_example_et.config(state="disabled")

hk_access_mode_var.trace_add("write", _hk_update_example)


def build_epoch_hk_format_dict(raw: str):
    """
    组装与 hk_generate 中 TEMPLATE_EPOCH_HK.format(**d) 相同的 dict。
    成功返回 (d, None)；失败返回 (None, (kind, payload))：
      kind == "network" → payload 为 errs 列表；
      "empty" / "tunnel" → payload 为说明用字符串或列表。
    供 all_in_one 可视化预览与 hk_generate 共用。
    """
    wan_ip, wan_gw, lan_ip, lan_gw, inner_raw = hk_get_raw()
    ok, errs = validate_net_panel_values(
        wan_ip, wan_gw, lan_ip, lan_gw, inner_raw,
        str(globals().get("HK_DEFAULT_WAN_CIDR", DEFAULT_WAN_CIDR)),
        str(globals().get("HK_DEFAULT_WAN_GW", DEFAULT_WAN_GW)),
        str(globals().get("HK_DEFAULT_LAN_CIDR", DEFAULT_LAN_CIDR)))
    if not ok:
        return None, ("network", errs)
    raw = raw.strip()
    if not raw:
        return None, ("empty", None)
    d = parse_epoch_hk(raw)
    hn = hk_get_hostname()
    if not hn:
        hn = extract_lineid_hk(raw) or "（请填写Hostname）"
    d["hostname"] = hn
    net = hk_get_net(is_us=False)
    d.update(net)
    inject_er_netpanel_init_aliases(d)

    bad_tuns = [f"{k}={d[k]!r}" for k in ("main_tunnel", "bk_tunnel")
                if d.get(k) and not d[k].startswith("vtun")]
    if bad_tuns:
        return None, ("tunnel", bad_tuns)

    fw_lines = [f"set firewall options interface {t} adjust-mss '1300'"
                for t in (d.get("main_tunnel", ""), d.get("bk_tunnel", "")) if t]
    d["fw_options_block"] = "\n".join(fw_lines)

    hkip_list = d.get("hkip_nat_list", [])
    d["hkip_nat_all"] = ", ".join(hkip_list) if hkip_list else d.get("hkip_nat", "")
    d["hkip_dum100_desc"] = "HKIP" if len(hkip_list) <= 1 else "HKIP_01"
    extra = []
    for idx, ip in enumerate(hkip_list[1:], start=2):
        dum = 99 + idx
        desc = "HKIP" if len(hkip_list) <= 1 else f"HKIP_{idx:02d}"
        extra += [f"set interfaces dummy dum{dum} address '{ip}/32'",
                  f"set interfaces dummy dum{dum} description '{desc}'"]
    d["extra_dum_block"] = "\n".join(extra)

    d["main_track"] = (d.get("main_tunnel") or "").lower()
    d["bk_track"] = (d.get("bk_tunnel") or "").lower()

    lines = []
    for bgp in [d["main_bgp1"], d["main_bgp2"]]:
        if bgp:
            lines += [f"set protocols static route {bgp}/32 blackhole distance '10'",
                      f"set protocols static route {bgp}/32 next-hop {d['main_wanip_remote']} track {d['main_track']}"]
    for bgp in [d["bk_bgp1"], d["bk_bgp2"]]:
        if bgp:
            lines += [f"set protocols static route {bgp}/32 blackhole distance '10'",
                      f"set protocols static route {bgp}/32 next-hop {d['bk_wanip_remote']} track {d['bk_track']}"]
    d["bgp_server_routes"] = "\n".join(lines)

    inner_nets = d.get("inner_nets") or []
    overseas_lines = []
    for i, net in enumerate(inner_nets):
        r_main = 100 + i
        r_bk = 200 + i
        overseas_lines.append(f"set nat source rule {r_main} outbound-interface '{d['main_tunnel']}'")
        overseas_lines.append(f"set nat source rule {r_main} source address '{net}'")
        overseas_lines.append(f"set nat source rule {r_main} translation address '{d['hkip_nat']}'")
        overseas_lines.append(f"set nat source rule {r_bk} outbound-interface '{d['bk_tunnel']}'")
        overseas_lines.append(f"set nat source rule {r_bk} source address '{net}'")
        overseas_lines.append(f"set nat source rule {r_bk} translation address '{d['hkip_nat']}'")
    d["overseas_nat_block"] = "\n".join(overseas_lines)
    return d, None


def hk_generate():
    raw = hk_left.get("1.0", tk.END).strip()
    d, fail = build_epoch_hk_format_dict(raw)
    if fail:
        kind, payload = fail
        if kind == "network":
            messagebox.showwarning(
                "网络格式校验未通过",
                "以下输入不符合网络标准，请修正后再生成：\n\n" + "\n".join(payload))
            hk_status.set("⚠  请修正网络格式后再生成")
        elif kind == "empty":
            hk_status.set("⚠  请先输入业务数据")
        elif kind == "tunnel":
            messagebox.showerror(
                "隧道命名错误",
                "HK 隧道名称异常，track 只允许 vtun 接口：\n" + "\n".join(payload))
            hk_status.set("⚠  隧道命名错误，请检查输入")
        return

    _tpl_hk = TEMPLATE_EPOCH_HK_IPSEC if hk_access_mode_var.get() == "IPSec" else TEMPLATE_EPOCH_HK
    _notify_epoch_field_coverage(_tpl_hk, d, "Epoch FastIP · 香港出口", _ER_COVER_SKIP_HK)
    try:
        output = _tpl_hk.format(**d)
    except KeyError as e:
        hk_status.set(f"⚠  字段缺失：{e}"); return
    hk_right.delete("1.0", tk.END)
    hk_right.insert(tk.END, output)
    rr_cnt = d.get("return_routes_block","").count("\n") + (1 if d.get("return_routes_block","").strip() else 0)
    _hks = d.get("hkip_nat_list") or []
    hk_status.set(f"✓  HK配置已生成  ·  {output.count(chr(10))}行  "
                  f"·  Hostname:{d.get('hostname','')}  ·  出口IP:{len(_hks)}个  ·  BGP源:{d['ce_loip']}"
                  + (f"  ·  回程路由:{rr_cnt}条" if rr_cnt else ""))
    log_generate_config(
        tool="epoch_fastip", variant="hk", input_text=raw, output_text=output)

def hk_export():
    c = hk_right.get("1.0", tk.END).strip()
    if not c: hk_status.set("⚠  尚无配置"); return
    p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text","*.txt")])
    if p: open(p,"w",encoding="utf-8").write(c); hk_status.set(f"✓  已导出：{p}")

def hk_reset():
    hk_left.delete("1.0", tk.END); hk_right.delete("1.0", tk.END)
    hk_reset_net(); hk_status.set("↺  已恢复初始")

hk_gen.bind("<Button-1>", lambda e: hk_generate())
hk_exp.bind("<Button-1>", lambda e: hk_export())
hk_rst.bind("<Button-1>", lambda e: hk_reset())

# =====================================================================
# Tab US
# =====================================================================
US_NOTE = (
    "• 奇数尾号 = 主线，偶数尾号 = 备线\n"
    "• 块内 PE 顺序不限，通过 PE 名称自动识别角色：\n"
    "    acvpn/ipsecvpn → OpenVPN 接入（vtun 接口）\n"
    "    upe            → ACVPN GRE 接入（tun 接口）\n"
    "    natpe          → 非香港出口 GRE（tun 接口）\n"
    "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
    "• lan的dhcp是你开给别人的。\n"
    "• BGP更新源：默认使用 假ip 。 如果要建内网的，请自行调整。\n"
    "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
    "• 请自行修改nat/dns/mtu等部分。\n"
    "• nat只会打第一个出口ip的。其余ip请自行添加。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)
US_EXAMPLE = (
    "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\n"
    "PE 对接:192.168.247.17\nCE 对接:10.23.0.122\n"
    "PE:gzd-acvpnpe2\nTunnel:vtun17953\nwanip:10.23.0.120/30\nPE 对接:183.63.68.171\n\n"
    "LineID:609169A2\nPE:dgb-upebk2\nTunnel:Tunnel0/0/1998\nwanip:10.40.209.220/30\n"
    "PE 对接:192.168.251.100\nCE 对接:10.30.167.202\n"
    "PE:dgb-acvpnpe2\nTunnel:vtun50057\nwanip:10.30.167.200/30\nPE 对接:121.12.128.254\n\n"
    "LineID:609169A5\nPE： twb-natpe2\nWANIP: 10.21.32.124/30\nTUNNEL: tun1267\n"
    "PE Docking：192.168.239.12\nCE Docking：: 10.22.241.232\n"
    "BGPSERVER IP：103.252.19.25,43.229.117.226\n海外出口ip：\n10.60.44.28-218.32.88.83\n\n"
    "LineID:609169A6\nPE： twb-natpe1\nWANIP: 10.21.31.120/30\nTUNNEL: tun2366\n"
    "PE Docking：192.168.239.14\nCE Docking：: 10.22.241.232\n"
    "BGPSERVER IP：103.252.19.99,43.229.119.251\n海外出口ip：\n10.60.18.22-150.116.112.236\n"
)

us_access_mode_var = tk.StringVar(value="OpenVPN")
tab_us.columnconfigure(0, weight=1)
tab_us.rowconfigure(0, weight=0)
tab_us.rowconfigure(1, weight=1)
_add_mode_bar(tab_us, ACCENT_US, us_access_mode_var, row=0)
us_content = tk.Frame(tab_us, bg=BG)
us_content.grid(row=1, column=0, sticky="nsew")
us_init_container = [None]
us_left, us_right, us_status, us_gen, us_exp, us_rst, us_example_et = build_tab_shell(
    us_content, ACCENT_US, US_NOTE, US_EXAMPLE, us_init_container)
us_get_hostname, us_get_net, us_reset_net, us_get_raw = build_net_panel(
    us_init_container[0], ACCENT_US, wan_dhcp_default=False, lan_dhcp_default=True,
    is_hk=False)

def _us_update_example(*_):
    m = us_access_mode_var.get()
    txt = US_EXAMPLE_IPSEC if m == "IPSec" else US_EXAMPLE
    us_example_et.config(state="normal")
    us_example_et.delete("1.0", tk.END)
    us_example_et.insert(tk.END, txt)
    us_example_et.config(state="disabled")

us_access_mode_var.trace_add("write", _us_update_example)


def build_epoch_us_format_dict(raw: str):
    """
    组装与 us_generate 中 TEMPLATE_EPOCH_US.format(**d) 相同的 dict。
    成功返回 (d, None, warn_msgs)；失败返回 (None, (kind, payload), [])。
    kind 同 HK；额外 "natmiss" → payload 为 miss 列表。
    """
    wan_ip, wan_gw, lan_ip, lan_gw, inner_raw = us_get_raw()
    ok, errs = validate_net_panel_values(
        wan_ip, wan_gw, lan_ip, lan_gw, inner_raw,
        DEFAULT_WAN_CIDR, DEFAULT_WAN_GW, DEFAULT_LAN_CIDR)
    if not ok:
        return None, ("network", errs), []
    raw = raw.strip()
    if not raw:
        return None, ("empty", None), []
    d = parse_epoch_us(raw)
    hn = us_get_hostname()
    if not hn:
        hn = extract_lineid_us(raw) or "（请填写Hostname）"
    d["hostname"] = hn
    net = us_get_net(is_us=True)
    d.update(net)
    inject_er_netpanel_init_aliases(d)

    fw_lines = [f"set firewall options interface {t} adjust-mss '1300'"
                for t in [d.get("main_acvpn_vtun_id", ""), d.get("bk_acvpn_vtun_id", ""),
                          d.get("main_acvpn_gre_tun", ""), d.get("bk_acvpn_gre_tun", ""),
                          d.get("main_us_tun", ""), d.get("bk_us_tun", "")] if t]
    d["fw_options_block"] = "\n".join(fw_lines)

    main_nat_ips = list(d.get("main_us_nat_ips", []) or [])
    bk_nat_ips = list(d.get("bk_us_nat_ips", []) or [])
    warn_msgs = []
    if len(main_nat_ips) > 9:
        warn_msgs.append(f"主出口IP共{len(main_nat_ips)}个，超出dum100-dum108限制（最多9个），已截断！")
        main_nat_ips = main_nat_ips[:9]
    if len(bk_nat_ips) > 10:
        warn_msgs.append(f"备出口IP共{len(bk_nat_ips)}个，超出dum200-dum209限制（最多10个），已截断！")
        bk_nat_ips = bk_nat_ips[:10]

    if not main_nat_ips or not bk_nat_ips:
        miss = []
        if not main_nat_ips:
            miss.append("主线海外出口ip")
        if not bk_nat_ips:
            miss.append("备线海外出口ip")
        return None, ("natmiss", miss), []

    d["main_us_nat_ips"] = main_nat_ips
    d["bk_us_nat_ips"] = bk_nat_ips
    if main_nat_ips:
        d["main_us_nat_ip"] = main_nat_ips[0]
    if bk_nat_ips:
        d["bk_us_nat_ip"] = bk_nat_ips[0]
    d["main_us_nat_ip_all"] = ", ".join(main_nat_ips) if main_nat_ips else d.get("main_us_nat_ip", "")
    d["bk_us_nat_ip_all"] = ", ".join(bk_nat_ips) if bk_nat_ips else d.get("bk_us_nat_ip", "")
    d["main_us_dum100_desc"] = "MAIN_OUTIP" if len(main_nat_ips) <= 1 else "MAIN_OUTIP_01"
    d["bk_us_dum200_desc"] = "BK_OUTIP" if len(bk_nat_ips) <= 1 else "BK_OUTIP_01"

    extra_main = []
    for idx, ip in enumerate(main_nat_ips[1:], start=2):
        dum = 99 + idx
        desc = "MAIN_OUTIP" if len(main_nat_ips) <= 1 else f"MAIN_OUTIP_{idx:02d}"
        extra_main += [f"set interfaces dummy dum{dum} address '{ip}/32'",
                       f"set interfaces dummy dum{dum} description '{desc}'"]
    d["extra_dum_main_block"] = "\n".join(extra_main)
    extra_bk = []
    for idx, ip in enumerate(bk_nat_ips[1:], start=2):
        dum = 199 + idx
        desc = "BK_OUTIP" if len(bk_nat_ips) <= 1 else f"BK_OUTIP_{idx:02d}"
        extra_bk += [f"set interfaces dummy dum{dum} address '{ip}/32'",
                     f"set interfaces dummy dum{dum} description '{desc}'"]
    d["extra_dum_bk_block"] = "\n".join(extra_bk)

    bgp_lines = []
    main_peip = d.get("main_us_pe_ip", "")
    bk_peip = d.get("bk_us_pe_ip", "")
    for bgp in [d.get("main_us_bgp1", ""), d.get("main_us_bgp2", "")]:
        if bgp:
            bgp_lines += [f"set protocols static route {bgp}/32 blackhole distance '10'",
                          f"set protocols static route {bgp}/32 next-hop {main_peip} track mainnatpe"]
    for bgp in [d.get("bk_us_bgp1", ""), d.get("bk_us_bgp2", "")]:
        if bgp:
            bgp_lines += [f"set protocols static route {bgp}/32 blackhole distance '10'",
                          f"set protocols static route {bgp}/32 next-hop {bk_peip} track backnatpe"]
    d["us_bgp_routes"] = "\n".join(bgp_lines)

    inner_nets = d.get("inner_nets") or []
    overseas_lines = []
    for i, net in enumerate(inner_nets):
        r_main = 100 + i
        r_bk = 200 + i
        overseas_lines.append(f"set nat source rule {r_main} outbound-interface '{d['main_us_tun']}'")
        overseas_lines.append(f"set nat source rule {r_main} source address '{net}'")
        overseas_lines.append(f"set nat source rule {r_main} translation address '{d['main_us_nat_ip']}'")
        overseas_lines.append(f"set nat source rule {r_bk} outbound-interface '{d['bk_us_tun']}'")
        overseas_lines.append(f"set nat source rule {r_bk} source address '{net}'")
        overseas_lines.append(f"set nat source rule {r_bk} translation address '{d['bk_us_nat_ip']}'")
    d["overseas_nat_block"] = "\n".join(overseas_lines)
    return d, None, warn_msgs


def us_generate():
    raw = us_left.get("1.0", tk.END).strip()
    d, fail, warn_msgs = build_epoch_us_format_dict(raw)
    if fail:
        kind, payload = fail
        if kind == "network":
            messagebox.showwarning(
                "网络格式校验未通过",
                "以下输入不符合网络标准，请修正后再生成：\n\n" + "\n".join(payload))
            us_status.set("⚠  请修正网络格式后再生成")
        elif kind == "empty":
            us_status.set("⚠  请先输入业务数据")
        elif kind == "natmiss":
            messagebox.showwarning(
                "海外出口IP缺失",
                "未解析到以下字段，请检查业务数据里「海外出口ip」是否为 IP 或 IP段(如 1.1.1.1-2.2.2.2)：\n\n"
                + "\n".join(payload),
            )
            us_status.set("! 海外出口IP缺失，已终止生成")
        return

    _tpl_us = TEMPLATE_EPOCH_US_IPSEC if us_access_mode_var.get() == "IPSec" else TEMPLATE_EPOCH_US
    _notify_epoch_field_coverage(_tpl_us, d, "Epoch FastIP · 非香港出口", _ER_COVER_SKIP_US)
    try:
        output = _tpl_us.format(**d)
    except KeyError as e:
        us_status.set(f"⚠  字段缺失：{e}"); return
    us_right.delete("1.0", tk.END)
    us_right.insert(tk.END, output)

    _mip = d.get("main_us_nat_ips") or []
    _bip = d.get("bk_us_nat_ips") or []
    total_ips = len(_mip) + len(_bip)
    rr_cnt = d.get("return_routes_block","").count("\n") + (1 if d.get("return_routes_block","").strip() else 0)
    base_msg = (f"✓  非香港出口配置已生成  ·  {output.count(chr(10))}行  "
                f"·  Hostname:{d.get('hostname','')}  ·  出口IP共{total_ips}个  "
                f"·  BGP源(主):{d.get('main_us_nat_ip','')}  BGP源(备):{d.get('bk_us_nat_ip','')}"
                + (f"  ·  回程路由:{rr_cnt}条" if rr_cnt else ""))
    if warn_msgs:
        us_status.set("⚠  " + "  |  ".join(warn_msgs))
        messagebox.showwarning("出口IP超限", "\n".join(warn_msgs))
    else:
        us_status.set(base_msg)
    log_generate_config(
        tool="epoch_fastip", variant="us", input_text=raw, output_text=output)

def us_export():
    c = us_right.get("1.0", tk.END).strip()
    if not c: us_status.set("⚠  尚无配置"); return
    p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text","*.txt")])
    if p: open(p,"w",encoding="utf-8").write(c); us_status.set(f"✓  已导出：{p}")

def us_reset():
    us_left.delete("1.0", tk.END); us_right.delete("1.0", tk.END)
    us_reset_net(); us_status.set("↺  已恢复初始")

us_gen.bind("<Button-1>", lambda e: us_generate())
us_exp.bind("<Button-1>", lambda e: us_export())
us_rst.bind("<Button-1>", lambda e: us_reset())

# =====================================================================
# Tab 飞连（ER）
# =====================================================================
ER_FL_DEFAULT_HEADERS = (
    "PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.1.0/29\n"
    "PE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.1.0/29\n"
    "PE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.1.0/29\n"
)
ER_FL_MAIN_NH_DEFAULT = "10.1.1.1"
ER_FL_BACKUP_NH_DEFAULT = "10.2.1.1"
TEMPLATE_ER_FLINK_VISUAL = """\
set track name flink failure-count '2'
set track name flink success-count '2'
set track name flink test 0 resp-time '5'
set track name flink test 0 target {ER_FL_MAIN_NH_DEFAULT}
set track name flink test 0 ttl-limit '1'
set track name flink test 0 type 'ping'

set protocols static route {route1} next-hop {ER_FL_MAIN_NH_DEFAULT} track flink
set protocols static route {route2} next-hop {ER_FL_MAIN_NH_DEFAULT} track flink
set protocols static route {route3} next-hop {ER_FL_MAIN_NH_DEFAULT} track flink

set protocols static route {route1} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 5
set protocols static route {route2} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 5
set protocols static route {route3} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 5
"""
ER_NE_MAIN_PE_NH_DEFAULT = "192.168.1.1"
ER_NE_BK_PE_NH_DEFAULT = "192.168.1.2"
ER_NE_MAIN_DUM_DEFAULT = "300"
ER_NE_BK_DUM_DEFAULT = "400"
# NAT：与 dum 号独立；出接口取数据头 TUNNEL；每条「海外出口ip」一对生成一条 rule，translation 为本端(dum)IP
ER_NE_MAIN_NAT_RULE_DEFAULT = "300"
ER_NE_BK_NAT_RULE_DEFAULT = "400"
# NAT 源网段（初始化）；与内网 dum 段可不同，仅用于 set nat source rule … source address
ER_NE_NAT_SOURCE_CIDR_DEFAULT = "192.168.0.0/24"
TEMPLATE_ER_NEW_EXIT_VISUAL = """\
set interfaces tunnel {main_tun} address '{main_tun_addr}'
set interfaces tunnel {main_tun} description 'main-{main_pe}'
set interfaces tunnel {main_tun} encapsulation 'gre'
set interfaces tunnel {main_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {main_tun} mtu '1400'
set interfaces tunnel {main_tun} multicast 'disable'
set interfaces tunnel {main_tun} parameters ip ttl '255'
set interfaces tunnel {main_tun} remote '{main_pe_docking}'
set interfaces tunnel {main_tun} source-address '{main_ce_docking}'

set protocols static route {main_pe_docking}/32 next-hop {ER_NE_MAIN_PE_NH_DEFAULT}
{ER_NE_MAIN_DUM_BLOCK}
	{ER_NE_BK_BLOCK}
{ER_NE_NAT_HEADER_BLOCK}
{ER_NE_NAT_BLOCK}
{ER_NE_FNET_BLOCK}"""
ER_NEW_EXIT_EXAMPLE = (
    "LineID:609353B7\n"
    "PE： tyo2-natpe4\n"
    "WANIP: 10.22.86.196/30\n"
    "TUNNEL: tun1083\n"
    "PE Docking：192.168.205.67\n"
    "CE Docking：: 10.22.242.21\n"
    "BGPSERVER IP：103.252.19.25,43.229.117.226\n"
    "海外出口ip：\n"
    "10.60.21.185-103.57.50.44\n"
    "10.60.21.186-103.57.50.45\n\n"
    "LineID:609353B8\n"
    "PE： tyo4-natpe2\n"
    "WANIP: 10.22.100.120/30\n"
    "TUNNEL: tun1033\n"
    "PE Docking：10.33.54.78\n"
    "CE Docking：: 10.22.242.21\n"
    "BGPSERVER IP：103.252.19.99,43.229.119.251\n"
    "海外出口ip：\n"
    "10.60.72.44-172.16.13.46\n"
    "10.60.72.45-172.16.13.47\n"
)

# ── ER 域名分流 示例数据头（每行一个域名，驱动 build_er_domain_split_script）──
ER_DOMAIN_SPLIT_EXAMPLE = (
    "google.com\n"
    "youtube.com\n"
    "facebook.com\n"
)

# ── ER 新增出口 FNET Whitelist（track 100.100 / NAT 探测段；三项须同填或同空；仅双线时生效）──
ER_NE_FNET_PROBE_DEFAULT = ""
ER_NE_FNET_EXIT_TUNNEL_DEFAULT = ""
ER_NE_FNET_NAT_RULE_DEFAULT = ""

# ── ER 域名分流（与「我来定模板」初始化占位键一致，后缀 _DEFAULT）────────────────
ER_DS_DOMAINS_DEFAULT = "google.com"
ER_DS_ADDR_GROUP_DEFAULT = "to-US"
ER_DS_RULE_NUM_DEFAULT = "100"
ER_DS_TABLE_NUM_DEFAULT = "139"
ER_DS_SOURCE_CIDR_DEFAULT = "192.168.5.0/24"
ER_DS_DNS1_DEFAULT = "209.244.0.3"
ER_DS_DNS2_DEFAULT = ""
ER_DS_ETH_DEFAULT = "eth0"
ER_DS_TABLE_NH_PRIMARY_DEFAULT = "2.2.2.2"
ER_DS_TRACK_NAME_DEFAULT = "tooutbound1"
ER_DS_STATIC32_PRIMARY_NH_DEFAULT = "10.22.15.185"
ER_DS_STATIC32_BACKUP_NH_DEFAULT = "10.22.24.157"
# track 100.100 / NAT 探测段：可空，三项须同填或同空
ER_DS_EXIT_TUNNEL_DEFAULT = ""
ER_DS_EXIT_SNAT_IP_DEFAULT = ""
ER_DS_FNET_NAT_RULE_DEFAULT = ""
ER_DS_FNET_PROBE_DEFAULT = "100.100.100.1"

TEMPLATE_ER_DOMAIN_SPLIT_VISUAL = """# ER 域名分流 · 完整模板（占位符与「我来定模板」初始化一致；{ER_DS_DOMAINLIST_COMPUTED}、{ER_DS_POLICY_ROUTE_COMPUTED} 等由预览根据 address-group 推导；domainlist=/opt 文件名均为 A+组名）
# --- 写入域名列表（shell）---
sudo tee /opt/{ER_DS_DOMAINLIST_COMPUTED}.txt >/dev/null <<'EOF'
{ER_DS_DOMAINS_DEFAULT}
EOF
sudo chmod 777 /opt/{ER_DS_DOMAINLIST_COMPUTED}.txt

set firewall group address-group {ER_DS_ADDR_GROUP_DEFAULT}

set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} address-group '{ER_DS_ADDR_GROUP_DEFAULT}'
set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} file '/opt/{ER_DS_DOMAINLIST_COMPUTED}.txt'
set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} recursion-desired
set service dns forwarding domainlist {ER_DS_DOMAINLIST_COMPUTED} server '{ER_DS_DNS1_DEFAULT}'
{ER_DS_OPT_DNS2_LINE}
{ER_DS_OPT_POLICY_ROUTE_BLOCK}set protocols static route {ER_DS_TABLE_NH_PRIMARY_DEFAULT}/32 next-hop {ER_DS_STATIC32_PRIMARY_NH_DEFAULT}{ER_DS_OPT_TRACK_SUFFIX}
{ER_DS_OPT_S32BAK_LINE}
{ER_DS_OPT_FNET_BLOCK}"""


def _er_ds_normalize_addr_group(raw: str) -> str:
    """去掉首尾空白；支持「address-group : abc」写法，取冒号后组名。"""
    s = (raw or "").strip()
    if not s:
        return ""
    m = re.match(r"(?i)address-group\s*:\s*(.+)$", s)
    if m:
        return m.group(1).strip()
    return s


def _er_ds_domainlist_name(addr_group: str) -> str:
    """规范化后的 address-group 前加 A，用作 domainlist 名及 /opt/<名>.txt。"""
    ag = _er_ds_normalize_addr_group(addr_group or "")
    return ("A" + ag) if ag else ""


def _er_ds_policy_route_name(addr_group: str) -> str:
    ag = _er_ds_normalize_addr_group(addr_group or "")
    return "LAN-MAP-" + ag


def _er_ds_track_suffix(track_name: str) -> str:
    t = (track_name or "").strip()
    return f" track {t}" if t else ""


def er_ds_template_preview_extras(init_row: dict) -> dict:
    """「我来定模板」预览：由初始化字段推导模板专有占位符。"""
    ag_raw = str(init_row.get("ER_DS_ADDR_GROUP_DEFAULT", "")).strip()
    ag = _er_ds_normalize_addr_group(ag_raw)
    dl = _er_ds_domainlist_name(ag)
    pr = ("LAN-MAP-" + ag) if ag else ""
    d2 = str(init_row.get("ER_DS_DNS2_DEFAULT", "")).strip()
    if d2 and dl:
        dns2_line = f"set service dns forwarding domainlist {dl} server '{d2}'"
    else:
        dns2_line = ""
    nh = str(init_row.get("ER_DS_TABLE_NH_PRIMARY_DEFAULT", "")).strip()
    sb = str(init_row.get("ER_DS_STATIC32_BACKUP_NH_DEFAULT", "")).strip()
    trn = str(init_row.get("ER_DS_TRACK_NAME_DEFAULT", "")).strip()
    track_suffix = _er_ds_track_suffix(trn)
    if nh and sb:
        s32bak = f"set protocols static route {nh}/32 next-hop {sb} distance '20'"
    else:
        s32bak = ""
    sc = str(init_row.get("ER_DS_SOURCE_CIDR_DEFAULT", "")).strip()
    _sc_ok = ""
    if sc:
        try:
            _sc_ok = str(ipaddress.ip_network(sc, strict=False))
        except ValueError:
            _sc_ok = ""
    rn = str(init_row.get("ER_DS_RULE_NUM_DEFAULT", "")).strip()
    tn = str(init_row.get("ER_DS_TABLE_NUM_DEFAULT", "")).strip()
    eth = str(init_row.get("ER_DS_ETH_DEFAULT", "")).strip()
    nh_pri = str(init_row.get("ER_DS_TABLE_NH_PRIMARY_DEFAULT", "")).strip()
    policy_blk = ""
    if pr and rn and tn and eth and ag and nh_pri:
        source_line = f"set policy route {pr} rule {rn} source address {_sc_ok}\n" if _sc_ok else ""
        policy_blk = (
            "\n"
            f"set policy route {pr} rule {rn} destination group address-group '{ag}'\n"
            f"{source_line}"
            f"set policy route {pr} rule {rn} set table '{tn}'\n"
            f"set protocols static table {tn} route 0.0.0.0/0 next-hop  {nh_pri}\n"
            f"set interfaces ethernet {eth} policy route '{pr}'\n"
            "\n"
        )
    nr0 = str(init_row.get("ER_DS_FNET_NAT_RULE_DEFAULT", "")).strip()
    tun0 = str(init_row.get("ER_DS_EXIT_TUNNEL_DEFAULT", "")).strip()
    sn0 = str(init_row.get("ER_DS_EXIT_SNAT_IP_DEFAULT", "")).strip()
    fnet_grp = _ER_DS_FNET_NETGROUP
    fnet_probe_raw = str(init_row.get("ER_DS_FNET_PROBE_DEFAULT", "100.100.100.1")).strip()
    pri32 = str(init_row.get("ER_DS_STATIC32_PRIMARY_NH_DEFAULT", "")).strip()
    _ds_if_ok = re.compile(r"^[A-Za-z0-9._-]+$")
    fnet_blk = ""
    f_filled = (bool(nr0), bool(tun0), bool(sn0))
    if all(f_filled) and pri32:
        if (
            nr0.isdigit()
            and 1 <= int(nr0) <= 999999
            and _ds_if_ok.match(tun0)
        ):
            try:
                ipaddress.ip_address(sn0)
            except ValueError:
                pass
            else:
                try:
                    fnet_probe = str(ipaddress.ip_address(fnet_probe_raw))
                except ValueError:
                    fnet_blk = ""
                else:
                    fnet_blk = (
                        f"\nset firewall group network-group {fnet_grp} network {_ER_DS_FNET_NET}\n\n"
                        f"set nat source rule {nr0} destination address {fnet_probe}/32\n"
                        f"set nat source rule {nr0} outbound-interface '{tun0}'\n"
                        f"set nat source rule {nr0} translation address '{sn0}'\n\n"
                        f"set protocols static route {fnet_probe}/32 next-hop {pri32}\n\n"
                        + (
                            ""
                            if not trn
                            else (
                                f"set track name {trn} failure-count '5'\n"
                                f"set track name {trn} success-count '5'\n"
                                f"set track name {trn} test 10 resp-time '5'\n"
                                f"set track name {trn} test 10 target '{fnet_probe}'\n"
                                f"set track name {trn} test 10 ttl-limit '1'\n"
                                f"set track name {trn} test 10 type 'ping'\n"
                            )
                        )
                    )
    ex: dict = {
        "ER_DS_DOMAINLIST_COMPUTED": dl,
        "ER_DS_POLICY_ROUTE_COMPUTED": pr,
        "ER_DS_OPT_DNS2_LINE": dns2_line,
        "ER_DS_OPT_S32BAK_LINE": s32bak,
        "ER_DS_OPT_TRACK_SUFFIX": track_suffix,
        "ER_DS_OPT_POLICY_ROUTE_BLOCK": policy_blk,
        "ER_DS_OPT_FNET_BLOCK": fnet_blk,
    }
    if ag:
        ex["ER_DS_ADDR_GROUP_DEFAULT"] = ag
    return ex

_DS_SAFE_DOMAINLIST = re.compile(r"^[A-Za-z0-9._-]+$")
_DS_SAFE_IFACE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_ER_DS_BACKUP_STATIC_DISTANCE = "20"
_ER_DS_FNET_NETGROUP = "GROUP-FNET-Whitelist"
_ER_DS_FNET_NET = "100.100.100.0/24"


def _er_ds_parse_domain_lines(raw: str):
    lines = []
    for ln in (raw or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.search(r"[\s#;|&$`<>]", s):
            return None, f"域名含非法字符或空白：{s!r}"
        lines.append(s)
    return lines, None


def _er_ds_validate_ipv4(s: str, label: str):
    s = (s or "").strip()
    if not s:
        return None, f"{label}不能为空"
    try:
        ipaddress.ip_address(s)
    except ValueError as e:
        return None, f"{label}「{s}」非法：{e}"
    return s, None


def build_er_domain_split_script(cfg: dict):
    """根据表单字典生成 shell + VyOS；cfg 键与 ER_DS_* 逻辑字段对应（无 _DEFAULT 后缀）。"""
    dom_lines, de = _er_ds_parse_domain_lines(cfg.get("domains_text", ""))
    if de:
        return None, de
    if not dom_lines:
        return None, "请至少填写一行域名"

    addr_group = _er_ds_normalize_addr_group(cfg.get("addr_group") or "")
    domainlist_name = _er_ds_domainlist_name(addr_group)
    policy_route = _er_ds_policy_route_name(addr_group)
    eth = (cfg.get("eth") or "").strip()
    track_name = (cfg.get("track_name") or "").strip()
    src_raw = (cfg.get("source_cidr") or "").strip()
    src_cidr = None
    if src_raw:
        try:
            src_cidr = str(ipaddress.ip_network(src_raw, strict=False))
        except ValueError as e:
            return None, f"源网段非法：{e}"

    if not addr_group:
        return None, "请填写 address-group"
    if track_name and not _DS_SAFE_IFACE_NAME.match(track_name):
        return None, "Track 名称仅允许字母数字及 ._-（与 VyOS 无引号写法一致）"
    if not eth:
        return None, "应用接口不能为空"
    if not _DS_SAFE_DOMAINLIST.match(domainlist_name):
        return None, "address-group（及其推导出的 A+组名 domainlist）仅允许字母数字及 ._- ，用于 VyOS 与 /opt 下 .txt 文件名"

    rule_s = (cfg.get("rule_num") or "").strip()
    table_s = (cfg.get("table_num") or "").strip()
    if not rule_s.isdigit() or not (1 <= int(rule_s) <= 999999):
        return None, "LAN-MAP rule 须为正整数"
    if not table_s.isdigit() or not (0 <= int(table_s) <= 4294967295):
        return None, "static table 号须为合法非负整数"

    dns1, e1 = _er_ds_validate_ipv4(cfg.get("dns1"), "DNS 主")
    if e1:
        return None, e1
    dns2_raw = (cfg.get("dns2") or "").strip()
    dns2 = None
    if dns2_raw:
        dns2, e2 = _er_ds_validate_ipv4(dns2_raw, "DNS 备")
        if e2:
            return None, e2

    nh_pri = (cfg.get("table_nh_primary") or "").strip()
    s32_pri = (cfg.get("static32_primary_nh") or "").strip()
    s32_bak = (cfg.get("static32_backup_nh") or "").strip()
    for ip, lab in ((nh_pri, "递归下一跳"), (s32_pri, "主下一跳")):
        _, err = _er_ds_validate_ipv4(ip, lab)
        if err:
            return None, err
    if s32_bak:
        _, err = _er_ds_validate_ipv4(s32_bak, "备下一跳")
        if err:
            return None, err

    nr_raw = (cfg.get("fnet_nat_rule") or "").strip()
    exit_tunnel = (cfg.get("exit_tunnel") or "").strip()
    exit_snat = (cfg.get("exit_snat_ip") or "").strip()
    fnet_group = _ER_DS_FNET_NETGROUP
    fnet_probe_raw = (cfg.get("fnet_probe") or "").strip()
    f_filled = (bool(nr_raw), bool(exit_tunnel), bool(exit_snat))
    if any(f_filled) and not all(f_filled):
        return None, "NAT rule、NAT 出口 tunnel、主线出口 IP 须同时填写或全部留空"
    emit_fnet = all(f_filled)
    if emit_fnet:
        if not nr_raw.isdigit() or not (1 <= int(nr_raw) <= 999999):
            return None, "NAT rule 号须为 1～999999 的整数"
        if not _DS_SAFE_IFACE_NAME.match(exit_tunnel):
            return None, "NAT 出口 tunnel 名称仅允许字母数字及 ._-"
        exit_snat, es_err = _er_ds_validate_ipv4(exit_snat, "主线出口 IP")
        if es_err:
            return None, es_err
        try:
            fnet_probe = str(ipaddress.ip_address(fnet_probe_raw))
        except ValueError as e:
            return None, f"track 100.100 探测 IP 非法：{e}"
    else:
        fnet_probe = fnet_probe_raw
    nat_rule_s = nr_raw

    file_path = f"/opt/{domainlist_name}.txt"
    domains_body = "\n".join(dom_lines)
    sh = [
        f"# 等价于 touch + vi 写入 {file_path}（以下为可直接执行的 heredoc）",
        f"sudo tee {file_path} >/dev/null <<'EOF'",
        domains_body,
        "EOF",
        f"sudo chmod 777 {file_path}",
        "",
    ]
    vy = [
        f"set firewall group address-group {addr_group}",
        "",
        f"set service dns forwarding domainlist {domainlist_name} address-group '{addr_group}'",
        f"set service dns forwarding domainlist {domainlist_name} file '{file_path}'",
        f"set service dns forwarding domainlist {domainlist_name} recursion-desired",
        f"set service dns forwarding domainlist {domainlist_name} server '{dns1}'",
    ]
    if dns2:
        vy.append(f"set service dns forwarding domainlist {domainlist_name} server '{dns2}'")
    vy.extend([
        "",
        f"set policy route {policy_route} rule {rule_s} destination group address-group '{addr_group}'",
    ])
    if src_cidr:
        vy.append(f"set policy route {policy_route} rule {rule_s} source address {src_cidr}")
    vy.extend([
        f"set policy route {policy_route} rule {rule_s} set table '{table_s}'",
        f"set protocols static table {table_s} route 0.0.0.0/0 next-hop  {nh_pri}",
        f"set interfaces ethernet {eth} policy route '{policy_route}'",
        "",
    ])
    vy.append(f"set protocols static route {nh_pri}/32 next-hop {s32_pri}{_er_ds_track_suffix(track_name)}")
    if s32_bak:
        vy.append(
            f"set protocols static route {nh_pri}/32 next-hop {s32_bak} distance '{_ER_DS_BACKUP_STATIC_DISTANCE}'"
        )
    if emit_fnet:
        vy.extend([
            "",
            f"set firewall group network-group {fnet_group} network {_ER_DS_FNET_NET}",
            "",
            f"set nat source rule {nat_rule_s} destination address {fnet_probe}/32",
            f"set nat source rule {nat_rule_s} outbound-interface '{exit_tunnel}'",
            f"set nat source rule {nat_rule_s} translation address '{exit_snat}'",
            "",
            f"set protocols static route {fnet_probe}/32 next-hop {s32_pri}",
            "",
        ])
        if track_name:
            vy.extend([
                f"set track name {track_name} failure-count '5'",
                f"set track name {track_name} success-count '5'",
                f"set track name {track_name} test 10 resp-time '5'",
                f"set track name {track_name} test 10 target '{fnet_probe}'",
                f"set track name {track_name} test 10 ttl-limit '1'",
                f"set track name {track_name} test 10 type 'ping'",
            ])
        vy.append("")
    return "\n".join(sh + vy).rstrip() + "\n", None


def er_ds_cfg_from_globals_dict() -> dict:
    g = globals()
    return {
        "domains_text": str(g.get("ER_DS_DOMAINS_DEFAULT", "")),
        "addr_group": str(g.get("ER_DS_ADDR_GROUP_DEFAULT", "")),
        "rule_num": str(g.get("ER_DS_RULE_NUM_DEFAULT", "")),
        "table_num": str(g.get("ER_DS_TABLE_NUM_DEFAULT", "")),
        "source_cidr": str(g.get("ER_DS_SOURCE_CIDR_DEFAULT", "")),
        "dns1": str(g.get("ER_DS_DNS1_DEFAULT", "")),
        "dns2": str(g.get("ER_DS_DNS2_DEFAULT", "")),
        "eth": str(g.get("ER_DS_ETH_DEFAULT", "")),
        "table_nh_primary": str(g.get("ER_DS_TABLE_NH_PRIMARY_DEFAULT", "")),
        "track_name": str(g.get("ER_DS_TRACK_NAME_DEFAULT", "")),
        "static32_primary_nh": str(g.get("ER_DS_STATIC32_PRIMARY_NH_DEFAULT", "")),
        "static32_backup_nh": str(g.get("ER_DS_STATIC32_BACKUP_NH_DEFAULT", "")),
        "exit_tunnel": str(g.get("ER_DS_EXIT_TUNNEL_DEFAULT", "")),
        "exit_snat_ip": str(g.get("ER_DS_EXIT_SNAT_IP_DEFAULT", "")),
        "fnet_nat_rule": str(g.get("ER_DS_FNET_NAT_RULE_DEFAULT", "")),
        "fnet_probe": str(g.get("ER_DS_FNET_PROBE_DEFAULT", "100.100.100.1")),
    }


def er_ds_cfg_from_widgets() -> dict:
    return {
        "domains_text": er_fl_ds_domains_t.get("1.0", tk.END),
        "addr_group": er_fl_ds_addr_group.get(),
        "rule_num": er_fl_ds_rule_num.get(),
        "table_num": er_fl_ds_table_num.get(),
        "source_cidr": er_fl_ds_source_cidr.get(),
        "dns1": er_fl_ds_dns1.get(),
        "dns2": er_fl_ds_dns2.get(),
        "eth": er_fl_ds_eth.get(),
        "table_nh_primary": er_fl_ds_nh_primary.get(),
        "track_name": er_fl_ds_track.get(),
        "static32_primary_nh": er_fl_ds_s32_pri.get(),
        "static32_backup_nh": er_fl_ds_s32_bak.get(),
        "exit_tunnel": er_fl_ds_exit_tun.get(),
        "exit_snat_ip": er_fl_ds_exit_snat.get(),
        "fnet_nat_rule": er_fl_ds_fnet_nat_rule.get(),
        "fnet_probe": er_fl_ds_fnet_probe.get(),
    }


def er_ds_apply_globals_to_widgets() -> None:
    g = globals()
    er_fl_ds_domains_t.delete("1.0", tk.END)
    er_fl_ds_domains_t.insert("1.0", str(g.get("ER_DS_DOMAINS_DEFAULT", "")).strip())
    pairs = (
        (er_fl_ds_addr_group, "ER_DS_ADDR_GROUP_DEFAULT"),
        (er_fl_ds_rule_num, "ER_DS_RULE_NUM_DEFAULT"),
        (er_fl_ds_table_num, "ER_DS_TABLE_NUM_DEFAULT"),
        (er_fl_ds_source_cidr, "ER_DS_SOURCE_CIDR_DEFAULT"),
        (er_fl_ds_dns1, "ER_DS_DNS1_DEFAULT"),
        (er_fl_ds_dns2, "ER_DS_DNS2_DEFAULT"),
        (er_fl_ds_eth, "ER_DS_ETH_DEFAULT"),
        (er_fl_ds_nh_primary, "ER_DS_TABLE_NH_PRIMARY_DEFAULT"),
        (er_fl_ds_track, "ER_DS_TRACK_NAME_DEFAULT"),
        (er_fl_ds_s32_pri, "ER_DS_STATIC32_PRIMARY_NH_DEFAULT"),
        (er_fl_ds_s32_bak, "ER_DS_STATIC32_BACKUP_NH_DEFAULT"),
        (er_fl_ds_fnet_nat_rule, "ER_DS_FNET_NAT_RULE_DEFAULT"),
        (er_fl_ds_exit_tun, "ER_DS_EXIT_TUNNEL_DEFAULT"),
        (er_fl_ds_exit_snat, "ER_DS_EXIT_SNAT_IP_DEFAULT"),
        (er_fl_ds_fnet_probe, "ER_DS_FNET_PROBE_DEFAULT"),
    )
    for ent, gk in pairs:
        ent.delete(0, tk.END)
        ent.insert(0, str(g.get(gk, "")).strip())
    hint = g.get("er_fl_ds_domainlist_hint")
    if hint is not None:
        ag = str(g.get("ER_DS_ADDR_GROUP_DEFAULT", "")).strip()
        if ag:
            dl = _er_ds_domainlist_name(ag)
            pr = _er_ds_policy_route_name(ag)
            hint.config(
                text=f"domainlist「{dl}」= A+组名 · /opt/{dl}.txt · policy-route「{pr}」"
            )
        else:
            hint.config(
                text="填写 address-group（可写「address-group : 名称」）后：domainlist 与 /opt 下 .txt 均用 A+组名；policy-route 为 LAN-MAP+组名"
            )


def parse_er_flink_headers(raw_text: str):
    """解析飞连数据头，返回 ([(name, cidr), ...], err_msg_or_none)。

    支持两种格式：
    1. 新格式：PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.1.0/29
    2. 旧格式：name:cidr 或纯 cidr

    放宽策略：遇到无法解析的行跳过（不报错）；预留 IP 无 /掩码 自动补 /32。
    只要能提取到至少 1 个有效网段就返回成功。不足 3 个时返回提示（不阻断）。
    """
    routes = []
    for ln in (raw_text or "").splitlines():
        line = ln.strip()
        if not line:
            continue
        # 尝试新格式：匹配 PE / FPE / 预留IP
        pe_m = re.search(r"PE[：:]\s*(\S+)", line)
        fpe_m = re.search(r"FPE[：:]\s*(\S+)", line)
        ip_m = re.search(r"预留IP[：:]\s*(\S+)", line)
        if ip_m:
            cidr = ip_m.group(1)
            pe_val = pe_m.group(1) if pe_m else ""
            fpe_val = fpe_m.group(1) if fpe_m else ""
            name = f"{pe_val} / {fpe_val}".strip(" /") or "预留IP"
        elif ":" in line or "：" in line:
            # 旧格式：name:cidr
            name, cidr = re.split(r"[：:]", line, 1)
            name = name.strip() or "预留IP"
            cidr = cidr.strip()
        else:
            # 纯 IP/CIDR 行
            name = "预留IP"
            cidr = line
        if not cidr:
            continue  # 跳过无法提取的行
        # 无 /掩码 时自动补 /32
        if "/" not in cidr:
            # 确认是合法 IP 才补 /32，否则跳过
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", cidr):
                cidr = cidr + "/32"
            else:
                continue  # 不是 IP/CIDR，跳过
        try:
            cidr_norm = str(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue  # CIDR 非法，跳过不报错
        routes.append((name, cidr_norm))
    if not routes:
        return [], "请先填写飞连数据头（至少 1 行有效的预留IP/网段）"
    if len(routes) < 3:
        return routes, f"仅识别到 {len(routes)} 个飞连网段，不足 3 个，已按有效网段生成（不足部分需手动补充）"
    return routes, None


def build_er_flink_config(routes, main_nh: str, backup_nh: str):
    """按标准模板生成 ER 飞连配置。"""
    lines = [
        "set track name flink failure-count '2'",
        "set track name flink success-count '2'",
        "set track name flink test 0 resp-time '5'",
        f"set track name flink test 0 target {main_nh}",
        "set track name flink test 0 ttl-limit '1'",
        "set track name flink test 0 type 'ping'",
        "",
    ]
    for _name, cidr in routes:
        lines.append(f"set protocols static route {cidr} next-hop {main_nh} track flink")
    lines.append("")
    for _name, cidr in routes:
        lines.append(f"set protocols static route {cidr} next-hop {backup_nh} distance 5")
    return "\n".join(lines)


def _build_er_flink_format_dict(routes, main_nh: str, backup_nh: str) -> dict:
    cidrs = [cidr for _name, cidr in routes]
    names = [name for name, _cidr in routes]
    while len(cidrs) < 3:
        cidrs.append("0.0.0.0/32")
        names.append("")
    return {
        "ER_FL_MAIN_NH_DEFAULT": main_nh,
        "ER_FL_BACKUP_NH_DEFAULT": backup_nh,
        "route1": cidrs[0], "name1": names[0],
        "route2": cidrs[1], "name2": names[1],
        "route3": cidrs[2], "name3": names[2],
    }


def _parse_oversea_pairs(raw_blob: str):
    pairs = re.findall(
        r"(\d{1,3}(?:\.\d{1,3}){3})\s*[-–—~]\s*(\d{1,3}(?:\.\d{1,3}){3})",
        raw_blob or "",
    )
    if pairs:
        return pairs
    ips = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", raw_blob or "")
    return [(ip, ip) for ip in ips]


def parse_er_new_exit_blocks(raw_text: str):
    """解析新增出口输入，返回 ({"main":{}, "bk":{}}, err_msg_or_none)。

    支持单线输入（只有 1 个 LineID block），此时 parsed 只含 "main"，不报错。
    双线时按 LineID 尾号奇偶分主/备。
    """
    blocks = [b.strip() for b in re.split(r"(?=LineID\s*[:：])", raw_text or "", flags=re.IGNORECASE) if b.strip()]
    if not blocks:
        return None, "未找到任何 LineID 数据块"
    parsed = {}
    for block in blocks:
        line_id = _get(r"LineID\s*[:：]\s*(\S+)", block)
        if not line_id:
            continue
        # 仅 1 个 block 时统一视为主线；多个 block 时按 LineID 尾号奇偶分主/备
        if len(blocks) == 1:
            key = "main"
        else:
            try:
                key = "main" if int(line_id[-1]) % 2 == 1 else "bk"
            except Exception:
                key = "main"
        wanip = _get(r"WANIP\s*[:：]\s*([\d./]+)", block)
        tun = normalize_tun(_get(r"TUNNEL\s*[:：]\s*(\S+)", block))
        pe = _get(r"^\s*PE\s*[:：]\s*(.+?)$", block)
        pe_docking = _get(r"PE\s*[Dd]ocking\s*[:：]+\s*([\d.]+)", block)
        ce_docking = _get(r"CE\s*[Dd]ocking\s*[:：]+\s*([\d.]+)", block)
        oversea_blob_m = re.search(
            r"海外出口ip\s*[:：]\s*(.*?)(?=\nLineID\s*[:：]|\Z)",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        oversea_blob = oversea_blob_m.group(1) if oversea_blob_m else ""
        oversea_pairs = _parse_oversea_pairs(oversea_blob)
        if not (wanip and tun and pe and pe_docking and ce_docking):
            return None, f"{line_id} 数据不完整，请检查 WANIP/TUNNEL/PE/PE Docking/CE Docking"
        pe_ip, ce_ip = wanip_hosts(wanip)
        if not ce_ip:
            return None, f"{line_id} WANIP 无法解析：{wanip}"
        if not oversea_pairs:
            return None, f"{line_id} 未解析到海外出口ip"
        parsed[key] = {
            "line_id": line_id,
            "pe": pe.strip(),
            "tun": tun,
            "tun_addr": f"{ce_ip}/30",
            "pe_docking": pe_docking,
            "ce_docking": ce_docking,
            "oversea_pairs": oversea_pairs,
        }
    if "main" not in parsed:
        return None, "未解析到主线数据（LineID 尾号为奇或仅提供单条数据时视为主线）"
    # 双线但只有 1 个 block → 不报错（用户只输入了主线）
    return parsed, None


def _er_ne_nat_source_normalized(raw: str):
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return str(ipaddress.ip_network(s, strict=False))
    except ValueError:
        return None


def build_er_new_exit_nat_header_block(parsed: dict, init_cfg: dict) -> str:
    """源网段与 rule 数量说明（供模板/脚本注释；无源网段时返回空）。"""
    src = _er_ne_nat_source_normalized(init_cfg.get("nat_source_cidr", ""))
    if not src:
        return ""
    m = parsed.get("main") or {}
    b = parsed.get("bk") or {}
    m_pairs = list(m.get("oversea_pairs") or [])
    b_pairs = list(b.get("oversea_pairs") or [])
    if not m_pairs:
        return ""
    mr = str(init_cfg.get("main_nat_rule", "")).strip()
    br = str(init_cfg.get("bk_nat_rule", "")).strip()
    if not mr.isdigit():
        return ""
    nm, nb = len(m_pairs), len(b_pairs)
    b_info = f"；备线自 {br} 起共 {nb} 条" if b_pairs and br.isdigit() else ""
    lines = [
        f"# SNAT 源网段(初始化 ER_NE_NAT_SOURCE_CIDR_DEFAULT): {src}",
        f"# NAT rule: 主线自 {mr} 起共 {nm} 条{b_info}（每条海外「本端-对端」一条，translation=本端(dum)IP）",
        "",
    ]
    return "\n".join(lines)


def build_er_new_exit_nat_block(parsed: dict, init_cfg: dict) -> str:
    """每条海外出口一对 IP 一条 NAT rule：同出口 tunnel、同一源网段，translation 为本端(dum)IP；rule 号自初始化主/备起始递增。"""
    src = _er_ne_nat_source_normalized(init_cfg.get("nat_source_cidr", ""))
    mr = str(init_cfg.get("main_nat_rule", "")).strip()
    br = str(init_cfg.get("bk_nat_rule", "")).strip()
    if not mr.isdigit():
        return ""
    im = int(mr)
    ib = int(br) if br.isdigit() else 0
    if not (1 <= im <= 999999):
        return ""
    m = parsed.get("main") or {}
    b = parsed.get("bk") or {}
    m_pairs = list(m.get("oversea_pairs") or [])
    b_pairs = list(b.get("oversea_pairs") or [])
    if not m_pairs:
        return ""
    mt = (m.get("tun") or "").strip()
    bt = (b.get("tun") or "").strip() if b_pairs else ""
    if not mt:
        return ""
    lines: list[str] = []
    for i, (left, _right) in enumerate(m_pairs):
        tr = (left or "").strip()
        if not tr:
            return ""
        rid = im + i
        lines.extend([
            f"set nat source rule {rid} outbound-interface '{mt}'",
            *([f"set nat source rule {rid} source address '{src}'"] if src else []),
            f"set nat source rule {rid} translation address '{tr}'",
            "",
        ])
    for i, (left, _right) in enumerate(b_pairs):
        tr = (left or "").strip()
        if not tr:
            return ""
        rid = ib + i
        lines.extend([
            f"set nat source rule {rid} outbound-interface '{bt}'",
            *([f"set nat source rule {rid} source address '{src}'"] if src else []),
            f"set nat source rule {rid} translation address '{tr}'",
            "",
        ])
    return "\n".join(lines)


def _build_er_ne_fnet_block(parsed: dict, init_cfg: dict) -> str:
    """生成新增出口的 FNET whitelist 块（探测 IP / NAT / track）。

    仅双线 + 三元组（probe、tunnel、nat_rule）齐全时生成。
    单线或三元组不全时返回空字符串。
    translation address 取主线第一条海外出口左 IP；
    next-hop 取主 PE 对接下一跳（ER_NE_MAIN_PE_NH_DEFAULT）。
    track 名称固定为 tooutbound1。
    """
    if "bk" not in parsed or not parsed.get("bk"):
        return ""
    probe = str(init_cfg.get("fnet_probe", "")).strip()
    tunnel = str(init_cfg.get("fnet_exit_tunnel", "")).strip()
    nat_rule = str(init_cfg.get("fnet_nat_rule", "")).strip()
    f_filled = (bool(probe), bool(tunnel), bool(nat_rule))
    if not any(f_filled):
        return ""
    if not all(f_filled):
        return ""  # 三元组不完整 → 不生成（调用方应提前校验报错）
    m = parsed.get("main") or {}
    pairs = list(m.get("oversea_pairs") or [])
    if not pairs:
        return ""
    trans_ip = (pairs[0][0] or "").strip()
    if not trans_ip:
        return ""
    main_nh = str(init_cfg.get("main_pe_next_hop", "")).strip()
    track_name = "tooutbound1"
    lines = [
        "",
        f"set firewall group network-group {_ER_DS_FNET_NETGROUP} network {_ER_DS_FNET_NET}",
        "",
        f"set nat source rule {nat_rule} destination address {probe}/32",
        f"set nat source rule {nat_rule} outbound-interface '{tunnel}'",
        f"set nat source rule {nat_rule} translation address '{trans_ip}'",
        "",
        f"set protocols static route {probe}/32 next-hop {main_nh}",
        "",
        f"set track name {track_name} failure-count '5'",
        f"set track name {track_name} success-count '5'",
        f"set track name {track_name} test 10 resp-time '5'",
        f"set track name {track_name} test 10 target '{probe}'",
        f"set track name {track_name} test 10 ttl-limit '1'",
        f"set track name {track_name} test 10 type 'ping'",
        "",
    ]
    return "\n".join(lines)


def er_new_exit_nat_rule_span_error(parsed: dict, init_cfg: dict) -> str | None:
    """启用 SNAT 时校验 rule 区间不越界且主/备不重叠；否则返回错误文案。单线时跳过。"""
    if "bk" not in parsed or not parsed.get("bk"):
        return None
    if not _er_ne_nat_source_normalized(init_cfg.get("nat_source_cidr", "")):
        return None
    mr = str(init_cfg.get("main_nat_rule", "")).strip()
    br = str(init_cfg.get("bk_nat_rule", "")).strip()
    if not mr.isdigit() or not br.isdigit():
        return None
    im, ib = int(mr), int(br)
    m_pairs = list((parsed.get("main") or {}).get("oversea_pairs") or [])
    b_pairs = list((parsed.get("bk") or {}).get("oversea_pairs") or [])
    nm, nb = len(m_pairs), len(b_pairs)
    if nm < 1 or nb < 1:
        return None
    m_end, b_end = im + nm - 1, ib + nb - 1
    if m_end > 999999 or b_end > 999999:
        return (
            f"NAT rule 超出 1～999999（主线末号 {m_end}，备线末号 {b_end}），"
            "请提高起始 rule 号或减少海外出口行数"
        )
    if not (m_end < ib or b_end < im):
        return (
            f"主/备 NAT rule 区间重叠：主线 [{im},{m_end}]，备线 [{ib},{b_end}]，"
            "请调整起始号使两区间不相交"
        )
    return None


def build_er_new_exit_config(parsed, init_cfg):
    """按主/备模板生成新增出口配置。单线时仅生成主线。"""
    lines = []
    has_bk = "bk" in parsed and parsed.get("bk")
    items = [("main", "main", "main_pe_next_hop", "main_dum_start")]
    if has_bk:
        items.append(("bk", "backup", "bk_pe_next_hop", "bk_dum_start"))
    for key, prefix, next_hop_key, dum_start_key in items:
        item = parsed[key]
        lines.extend([
            f"set interfaces tunnel {item['tun']} address '{item['tun_addr']}'",
            f"set interfaces tunnel {item['tun']} description '{prefix}-{item['pe']}'",
            f"set interfaces tunnel {item['tun']} encapsulation 'gre'",
            f"set interfaces tunnel {item['tun']} firewall local name 'WAN2LOCAL'",
            f"set interfaces tunnel {item['tun']} mtu '1400'",
            f"set interfaces tunnel {item['tun']} multicast 'disable'",
            f"set interfaces tunnel {item['tun']} parameters ip ttl '255'",
            f"set interfaces tunnel {item['tun']} remote '{item['pe_docking']}'",
            f"set interfaces tunnel {item['tun']} source-address '{item['ce_docking']}'",
            "",
            f"set protocols static route {item['pe_docking']}/32 next-hop {init_cfg[next_hop_key]}",
        ])
        dum_id = init_cfg[dum_start_key]
        for left_ip, right_ip in item["oversea_pairs"]:
            lines.append(f"set interface dummy dum{dum_id} address   {left_ip}/32")
            lines.append(
                f"set interface dummy dum{dum_id} description {prefix}-outip-{left_ip}-{right_ip}"
            )
            dum_id += 1
        lines.append("")
    # NAT blocks - 单线时也生成主线的出口NAT规则
    nat_hdr = build_er_new_exit_nat_header_block(parsed, init_cfg)
    nat_blk = build_er_new_exit_nat_block(parsed, init_cfg)
    nat_parts = [p for p in (nat_hdr.rstrip(), nat_blk.rstrip()) if p]
    if nat_parts:
        lines.append("\n".join(nat_parts))
    fnet_blk = _build_er_ne_fnet_block(parsed, init_cfg)
    if fnet_blk.strip():
        lines.append(fnet_blk.rstrip())
    return "\n".join(lines).strip() + "\n"


def _build_er_new_exit_format_dict(parsed, init_cfg) -> dict:
    def _dum_block(key: str, prefix: str, start_key: str) -> str:
        item = parsed.get(key)
        if not item:
            return ""
        dum_id = int(init_cfg.get(start_key, 300))
        out = []
        for left_ip, right_ip in item.get("oversea_pairs", []):
            out.append(f"set interface dummy dum{dum_id} address   {left_ip}/32")
            out.append(
                f"set interface dummy dum{dum_id} description {prefix}-outip-{left_ip}-{right_ip}"
            )
            dum_id += 1
        return "\n".join(out)

    m = parsed.get("main") or {}
    b = parsed.get("bk")  # None for single line

    # 备线块：双线时生成完整备线配置，单线时为空
    bk_block = ""
    if b:
        bk_lines = [
            f"set interfaces tunnel {b['tun']} address '{b['tun_addr']}'",
            f"set interfaces tunnel {b['tun']} description 'backup-{b['pe']}'",
            f"set interfaces tunnel {b['tun']} encapsulation 'gre'",
            f"set interfaces tunnel {b['tun']} firewall local name 'WAN2LOCAL'",
            f"set interfaces tunnel {b['tun']} mtu '1400'",
            f"set interfaces tunnel {b['tun']} multicast 'disable'",
            f"set interfaces tunnel {b['tun']} parameters ip ttl '255'",
            f"set interfaces tunnel {b['tun']} remote '{b['pe_docking']}'",
            f"set interfaces tunnel {b['tun']} source-address '{b['ce_docking']}'",
            "",
            f"set protocols static route {b['pe_docking']}/32 next-hop {init_cfg.get('bk_pe_next_hop', '')}",
            _dum_block("bk", "backup", "bk_dum_start"),
        ]
        bk_block = "\n".join(bk_lines)

    # NAT blocks - 单线时也生成主线的出口NAT规则
    nat_hdr = build_er_new_exit_nat_header_block(parsed, init_cfg)
    nat_blk = build_er_new_exit_nat_block(parsed, init_cfg)


    return {
        "main_tun": m.get("tun", ""),
        "main_tun_addr": m.get("tun_addr", ""),
        "main_pe": m.get("pe", ""),
        "main_pe_docking": m.get("pe_docking", ""),
        "main_ce_docking": m.get("ce_docking", ""),
        "ER_NE_MAIN_PE_NH_DEFAULT": init_cfg.get("main_pe_next_hop", ""),
        "ER_NE_MAIN_DUM_BLOCK": _dum_block("main", "main", "main_dum_start"),
        "ER_NE_BK_BLOCK": bk_block,
        "ER_NE_NAT_HEADER_BLOCK": nat_hdr,
        "ER_NE_NAT_BLOCK": nat_blk,
        "ER_NE_FNET_BLOCK": _build_er_ne_fnet_block(parsed, init_cfg),
        "ER_NE_MAIN_NAT_RULE_DEFAULT": str(init_cfg.get("main_nat_rule", "")).strip(),
        "ER_NE_BK_NAT_RULE_DEFAULT": str(init_cfg.get("bk_nat_rule", "")).strip(),
        "ER_NE_NAT_SOURCE_CIDR_DEFAULT": str(init_cfg.get("nat_source_cidr", "")).strip(),
        "ER_NE_FNET_PROBE_DEFAULT": str(init_cfg.get("fnet_probe", "")).strip(),
        "ER_NE_FNET_EXIT_TUNNEL_DEFAULT": str(init_cfg.get("fnet_exit_tunnel", "")).strip(),
        "ER_NE_FNET_NAT_RULE_DEFAULT": str(init_cfg.get("fnet_nat_rule", "")).strip(),
    }


tab_fl.columnconfigure(0, weight=1)
tab_fl.rowconfigure(1, weight=1)

# 固定模式栏：始终显示在页签顶部（不受分割条影响）
er_fl_mode_var = tk.StringVar(value="flink")
er_fl_mode_fixed = tk.Frame(tab_fl, bg=ACCENT_US, height=34)
er_fl_mode_fixed.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 0))
er_fl_mode_fixed.grid_propagate(False)
tk.Frame(er_fl_mode_fixed, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(er_fl_mode_fixed, text="  模式", font=("微软雅黑", 10, "bold"), bg=ACCENT_US, fg=FG_BRT).pack(
    side="left", padx=(8, 8)
)

# 高级分段按钮风格（替代原生单选）
er_fl_mode_capsule = tk.Frame(er_fl_mode_fixed, bg=BORDER, padx=2, pady=2)
er_fl_mode_capsule.pack(side="left")
er_fl_btn_mode_flink = tk.Label(
    er_fl_mode_capsule, text="飞连", font=("微软雅黑", 10, "bold"),
    bg=BG_INPUT, fg=FG, padx=14, pady=3, cursor="hand2"
)
er_fl_btn_mode_flink.pack(side="left")
er_fl_btn_mode_new = tk.Label(
    er_fl_mode_capsule, text="新增出口", font=("微软雅黑", 10, "bold"),
    bg=BG_INPUT, fg=FG, padx=14, pady=3, cursor="hand2"
)
er_fl_btn_mode_new.pack(side="left", padx=(2, 0))
er_fl_btn_mode_ds = tk.Label(
    er_fl_mode_capsule, text="域名分流", font=("微软雅黑", 10, "bold"),
    bg=BG_INPUT, fg=FG, padx=14, pady=3, cursor="hand2"
)
er_fl_btn_mode_ds.pack(side="left", padx=(2, 0))

er_fl_vpane = ttk.PanedWindow(tab_fl, orient="vertical")
er_fl_vpane.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 0))

# 上半：左示范数据，右下一跳输入
er_fl_top = ttk.PanedWindow(er_fl_vpane, orient="horizontal")
er_fl_vpane.add(er_fl_top, weight=1)

er_fl_demo = tk.Frame(er_fl_top, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
er_fl_top.add(er_fl_demo, weight=1)
er_fl_demo_h = tk.Frame(er_fl_demo, bg=ACCENT_US, height=26)
er_fl_demo_h.pack(fill="x")
er_fl_demo_h.pack_propagate(False)
tk.Frame(er_fl_demo_h, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(er_fl_demo_h, text="  示范数据", font=FONT_HDR, bg=ACCENT_US, fg=FG_BRT).pack(side="left")
er_fl_demo_t = tk.Text(er_fl_demo, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat", bd=0, padx=10, pady=6)
er_fl_demo_t.pack(fill="both", expand=True)
er_fl_demo_t.insert("1.0", ER_FL_DEFAULT_HEADERS)
er_fl_demo_t.config(state="disabled")

er_fl_cfg = tk.Frame(er_fl_top, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
er_fl_top.add(er_fl_cfg, weight=1)
er_fl_cfg_h = tk.Frame(er_fl_cfg, bg=ACCENT_US, height=26)
er_fl_cfg_h.pack(fill="x")
er_fl_cfg_h.pack_propagate(False)
tk.Frame(er_fl_cfg_h, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(er_fl_cfg_h, text="  参数输入", font=FONT_HDR, bg=ACCENT_US, fg=FG_BRT).pack(side="left")

er_fl_cfg_body = tk.Frame(er_fl_cfg, bg=BG_PANEL)
er_fl_cfg_body.pack(fill="both", expand=True, padx=10, pady=8)
er_fl_cfg_body.columnconfigure(1, weight=1)

er_fl_cfg_flink = tk.Frame(er_fl_cfg_body, bg=BG_PANEL)
er_fl_cfg_flink.grid(row=0, column=0, columnspan=2, sticky="ew")
er_fl_cfg_flink.columnconfigure(1, weight=1)
tk.Label(er_fl_cfg_flink, text="主回程下一跳", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e", width=12).grid(
    row=0, column=0, sticky="e", padx=(0, 8), pady=(2, 6)
)
er_fl_main_nh = tk.Entry(
    er_fl_cfg_flink, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US
)
er_fl_main_nh.grid(row=0, column=1, sticky="ew", pady=(2, 6))
er_fl_main_nh.insert(0, ER_FL_MAIN_NH_DEFAULT)
tk.Label(er_fl_cfg_flink, text="备回程下一跳", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e", width=12).grid(
    row=1, column=0, sticky="e", padx=(0, 8), pady=(2, 6)
)
er_fl_backup_nh = tk.Entry(
    er_fl_cfg_flink, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US
)
er_fl_backup_nh.grid(row=1, column=1, sticky="ew", pady=(2, 6))
er_fl_backup_nh.insert(0, ER_FL_BACKUP_NH_DEFAULT)

# 新增出口：参数区左右两列（左主线 / 右备线），底部 NAT 源网段通栏
er_fl_cfg_new = tk.Frame(er_fl_cfg_body, bg=BG_PANEL)
er_fl_cfg_new.grid(row=0, column=0, columnspan=2, sticky="nsew")
er_fl_cfg_new.columnconfigure(0, minsize=118)
er_fl_cfg_new.columnconfigure(1, weight=1)
er_fl_cfg_new.columnconfigure(2, minsize=118)
er_fl_cfg_new.columnconfigure(3, weight=1)

tk.Label(er_fl_cfg_new, text="主线 · PE 下一跳", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=0, column=0, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_main_pe_nh = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_main_pe_nh.grid(row=0, column=1, sticky="ew", padx=(0, 14), pady=(3, 4))
tk.Label(er_fl_cfg_new, text="备线 · PE 下一跳", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=0, column=2, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_bk_pe_nh = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_bk_pe_nh.grid(row=0, column=3, sticky="ew", pady=(3, 4))

tk.Label(er_fl_cfg_new, text="主线 · dum 起始", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=1, column=0, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_main_dum = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_main_dum.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=(3, 4))
er_fl_main_dum.insert(0, "300")
tk.Label(er_fl_cfg_new, text="备线 · dum 起始", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=1, column=2, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_bk_dum = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_bk_dum.grid(row=1, column=3, sticky="ew", pady=(3, 4))
er_fl_bk_dum.insert(0, "400")

tk.Label(er_fl_cfg_new, text="主线 · NAT rule 起始", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=2, column=0, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_main_nat_rule = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_main_nat_rule.grid(row=2, column=1, sticky="ew", padx=(0, 14), pady=(3, 4))
er_fl_main_nat_rule.insert(0, ER_NE_MAIN_NAT_RULE_DEFAULT)
tk.Label(er_fl_cfg_new, text="备线 · NAT rule 起始", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=2, column=2, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_bk_nat_rule = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_bk_nat_rule.grid(row=2, column=3, sticky="ew", pady=(3, 4))
er_fl_bk_nat_rule.insert(0, ER_NE_BK_NAT_RULE_DEFAULT)

tk.Label(er_fl_cfg_new, text="NAT 源网段 (CIDR)", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=3, column=0, sticky="e", padx=(0, 8), pady=(6, 4)
)
er_fl_ne_nat_src = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_ne_nat_src.grid(row=3, column=1, columnspan=3, sticky="ew", pady=(6, 4))
er_fl_ne_nat_src.insert(0, ER_NE_NAT_SOURCE_CIDR_DEFAULT)

# FNET whitelist 100.100 探测段（三项须同填或同空）
tk.Label(er_fl_cfg_new, text="── FNET Whitelist（可空）──", font=("微软雅黑", 8, "bold"),
         bg=BG_PANEL, fg=ACCENT_US, anchor="w").grid(
    row=4, column=0, columnspan=4, sticky="ew", padx=(0, 0), pady=(10, 2)
)

tk.Label(er_fl_cfg_new, text="100.100 探测 IP", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=5, column=0, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_ne_fnet_probe = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_ne_fnet_probe.grid(row=5, column=1, sticky="ew", padx=(0, 14), pady=(3, 4))
er_fl_ne_fnet_probe.insert(0, ER_NE_FNET_PROBE_DEFAULT)
tk.Label(er_fl_cfg_new, text="NAT 出口 Tunnel", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=5, column=2, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_ne_fnet_tunnel = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_ne_fnet_tunnel.grid(row=5, column=3, sticky="ew", pady=(3, 4))

tk.Label(er_fl_cfg_new, text="NAT Rule 号", font=FONT_UI, bg=BG_PANEL, fg=FG, anchor="e").grid(
    row=6, column=0, sticky="e", padx=(0, 8), pady=(3, 4)
)
er_fl_ne_fnet_nat_rule = tk.Entry(
    er_fl_cfg_new, font=FONT_MONO, bg=BG_INPUT, fg=FG,
    insertbackground=ACCENT_US, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
)
er_fl_ne_fnet_nat_rule.grid(row=6, column=1, sticky="ew", padx=(0, 14), pady=(3, 4))

# 下半：左数据头输入，右生成结果（结果外壳可拆到「域名分流」横向窗格）
er_fl_bottom = ttk.PanedWindow(er_fl_vpane, orient="horizontal")
er_fl_vpane.add(er_fl_bottom, weight=1)


def _er_fl_build_pane_card(paned, label_text):
    f = tk.Frame(paned, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
    paned.add(f, weight=1)
    f.rowconfigure(1, weight=1)
    f.columnconfigure(0, weight=1)
    h = tk.Frame(f, bg=ACCENT_US, height=26)
    h.grid(row=0, column=0, sticky="ew")
    h.grid_propagate(False)
    tk.Frame(h, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(h, text=f"  {label_text}", font=FONT_HDR, bg=ACCENT_US, fg=FG_BRT).pack(side="left")
    inner = tk.Frame(f, bg=BG_INPUT)
    inner.grid(row=1, column=0, sticky="nsew")
    return f, inner


_, er_fl_input_wrap = _er_fl_build_pane_card(er_fl_bottom, "数据头输入")
er_fl_result_shell, er_fl_output_wrap = _er_fl_build_pane_card(er_fl_bottom, "生成结果")
er_fl_left = make_text(er_fl_input_wrap)
er_fl_right = make_text(er_fl_output_wrap, readonly=False)

# ── 域名分流：顶行整体横向分割（左初始化 / 右脚本生成）
er_fl_domain_hpane = ttk.PanedWindow(tab_fl, orient="horizontal")
er_fl_domain_left = tk.Frame(er_fl_domain_hpane, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
er_fl_domain_hpane.add(er_fl_domain_left, weight=1)
er_fl_domain_h = tk.Frame(er_fl_domain_left, bg=ACCENT_US, height=26)
er_fl_domain_h.pack(fill="x")
er_fl_domain_h.pack_propagate(False)
tk.Frame(er_fl_domain_h, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(er_fl_domain_h, text="  初始化", font=FONT_HDR, bg=ACCENT_US, fg=FG_BRT).pack(side="left")
er_fl_domain_body = tk.Frame(er_fl_domain_left, bg=BG_PANEL)
er_fl_domain_body.pack(fill="both", expand=True, padx=6, pady=6)
# 标签列保留最小宽度，避免窄窗下「主线出口」等长标签左侧被裁切
er_fl_domain_body.columnconfigure(0, minsize=118)
er_fl_domain_body.columnconfigure(1, weight=1)
er_fl_domain_body.columnconfigure(2, minsize=138)
er_fl_domain_body.columnconfigure(3, weight=1)

er_fl_domain_out = tk.Frame(er_fl_domain_hpane, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
er_fl_domain_hpane.add(er_fl_domain_out, weight=1)
er_fl_domain_out_h = tk.Frame(er_fl_domain_out, bg=ACCENT_US, height=26)
er_fl_domain_out_h.pack(fill="x")
er_fl_domain_out_h.pack_propagate(False)
tk.Frame(er_fl_domain_out_h, bg=FG_BRT, width=3).pack(side="left", fill="y")
tk.Label(er_fl_domain_out_h, text="  生成结果", font=FONT_HDR, bg=ACCENT_US, fg=FG_BRT).pack(side="left")
er_fl_domain_out_body = tk.Frame(er_fl_domain_out, bg=BG_INPUT)
er_fl_domain_out_body.pack(fill="both", expand=True)
er_fl_ds_right = make_text(er_fl_domain_out_body, readonly=False)

_pr = {"pady": (1, 3)}


def _er_ds_ds_lab(r: int, c: int, text: str, width=None) -> None:
    """域名分流表单标签：勿设过小 width，中文在 Tk 里按「字符格」计量易被裁成 … 或缺字。"""
    kw: dict = {
        "text": text,
        "font": FONT_UI,
        "bg": BG_PANEL,
        "fg": FG,
        "anchor": "e",
    }
    if width is not None:
        kw["width"] = width
    tk.Label(er_fl_domain_body, **kw).grid(row=r, column=c, sticky="e", padx=(0, 4), **_pr)


def _er_ds_ds_ent():
    return tk.Entry(
        er_fl_domain_body, font=FONT_MONO, bg=BG_INPUT, fg=FG,
        insertbackground=ACCENT_US, relief="flat", bd=0,
        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT_US,
    )


r = 0
_er_ds_ds_lab(r, 0, "域名(每行一个)")
er_fl_ds_domains_t = tk.Text(
    er_fl_domain_body, font=FONT_MONO, bg=BG_INPUT, fg=FG, relief="flat", bd=0,
    highlightthickness=1, highlightbackground=BORDER, height=5, wrap="none",
)
er_fl_ds_domains_t.grid(row=r, column=1, columnspan=3, sticky="ew", **_pr)
er_fl_ds_domains_t.insert("1.0", str(globals().get("ER_DS_DOMAINS_DEFAULT", "")).strip())
r += 1
_er_ds_ds_lab(r, 0, "address-group")
er_fl_ds_addr_group = _er_ds_ds_ent()
er_fl_ds_addr_group.grid(row=r, column=1, columnspan=3, sticky="ew", **_pr)
er_fl_ds_addr_group.insert(0, ER_DS_ADDR_GROUP_DEFAULT)
r += 1
er_fl_ds_domainlist_hint = tk.Label(
    er_fl_domain_body, text="", font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="w",
)
_dl0 = _er_ds_domainlist_name(ER_DS_ADDR_GROUP_DEFAULT)
_pr0 = _er_ds_policy_route_name(ER_DS_ADDR_GROUP_DEFAULT)
er_fl_ds_domainlist_hint.config(
    text=f"domainlist「{_dl0}」= A+组名 · /opt/{_dl0}.txt · policy-route「{_pr0}」"
)
er_fl_ds_domainlist_hint.grid(row=r, column=1, columnspan=3, sticky="ew", pady=(0, 2))
r += 1


def _er_fl_ds_refresh_domainlist_hint(_evt=None):
    ag = er_fl_ds_addr_group.get().strip()
    if ag:
        dl = _er_ds_domainlist_name(ag)
        pr = _er_ds_policy_route_name(ag)
        er_fl_ds_domainlist_hint.config(
            text=f"domainlist「{dl}」= A+组名 · /opt/{dl}.txt · policy-route「{pr}」"
        )
    else:
        er_fl_ds_domainlist_hint.config(
            text="填写 address-group（可写「address-group : 名称」）后：domainlist 与 /opt 下 .txt 均用 A+组名；policy-route 为 LAN-MAP+组名"
        )


for _ev in ("<KeyRelease>", "<FocusOut>"):
    er_fl_ds_addr_group.bind(_ev, _er_fl_ds_refresh_domainlist_hint)

_er_ds_ds_lab(r, 0, "LAN-MAP rule")
er_fl_ds_rule_num = _er_ds_ds_ent()
er_fl_ds_rule_num.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_rule_num.insert(0, ER_DS_RULE_NUM_DEFAULT)
_er_ds_ds_lab(r, 2, "table 号")
er_fl_ds_table_num = _er_ds_ds_ent()
er_fl_ds_table_num.grid(row=r, column=3, sticky="ew", **_pr)
er_fl_ds_table_num.insert(0, ER_DS_TABLE_NUM_DEFAULT)
r += 1
_er_ds_ds_lab(r, 0, "源网段(可空)")
er_fl_ds_source_cidr = _er_ds_ds_ent()
er_fl_ds_source_cidr.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_source_cidr.insert(0, ER_DS_SOURCE_CIDR_DEFAULT)
_er_ds_ds_lab(r, 2, "应用接口")
er_fl_ds_eth = _er_ds_ds_ent()
er_fl_ds_eth.grid(row=r, column=3, sticky="ew", **_pr)
er_fl_ds_eth.insert(0, ER_DS_ETH_DEFAULT)
r += 1
_er_ds_ds_lab(r, 0, "DNS 主")
er_fl_ds_dns1 = _er_ds_ds_ent()
er_fl_ds_dns1.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_dns1.insert(0, ER_DS_DNS1_DEFAULT)
_er_ds_ds_lab(r, 2, "DNS 备(可空)")
er_fl_ds_dns2 = _er_ds_ds_ent()
er_fl_ds_dns2.grid(row=r, column=3, sticky="ew", **_pr)
er_fl_ds_dns2.insert(0, ER_DS_DNS2_DEFAULT)
r += 1
_er_ds_ds_lab(r, 0, "递归下一跳")
er_fl_ds_nh_primary = _er_ds_ds_ent()
er_fl_ds_nh_primary.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_nh_primary.insert(0, ER_DS_TABLE_NH_PRIMARY_DEFAULT)
_er_ds_ds_lab(r, 2, "主下一跳")
er_fl_ds_s32_pri = _er_ds_ds_ent()
er_fl_ds_s32_pri.grid(row=r, column=3, sticky="ew", **_pr)
er_fl_ds_s32_pri.insert(0, ER_DS_STATIC32_PRIMARY_NH_DEFAULT)
r += 1
_sep_track = tk.Frame(er_fl_domain_body, bg=BG_PANEL)
_sep_track.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(8, 2))
_sep_track.columnconfigure(0, weight=1)
_ds_sep_track_cv = tk.Canvas(_sep_track, height=20, bg=BG_PANEL, highlightthickness=0)
_ds_sep_track_cv.grid(row=0, column=0, sticky="ew")


def _ds_draw_track100_sep(_evt=None):
    _ds_sep_track_cv.delete("all")
    w = max(_ds_sep_track_cv.winfo_width(), 2)
    _ds_sep_track_cv.create_line(0, 12, w, 12, dash=(4, 3), fill=BORDER, width=1)
    _ds_sep_track_cv.create_text(
        w // 2, 6, text="track 100.100",
        font=("微软雅黑", 8), fill=FG_DIM,
    )


_ds_sep_track_cv.bind("<Configure>", _ds_draw_track100_sep)
er_fl_domain_body.after(80, _ds_draw_track100_sep)
r += 1
_er_ds_ds_lab(r, 0, "Track 名称(可空)")
er_fl_ds_track = _er_ds_ds_ent()
er_fl_ds_track.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_track.insert(0, ER_DS_TRACK_NAME_DEFAULT)
_er_ds_ds_lab(r, 2, "备下一跳")
er_fl_ds_s32_bak = _er_ds_ds_ent()
er_fl_ds_s32_bak.grid(row=r, column=3, sticky="ew", **_pr)
er_fl_ds_s32_bak.insert(0, ER_DS_STATIC32_BACKUP_NH_DEFAULT)
r += 1
_er_ds_ds_lab(r, 0, "100.100 探测IP")
er_fl_ds_fnet_probe = _er_ds_ds_ent()
er_fl_ds_fnet_probe.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_fnet_probe.insert(0, ER_DS_FNET_PROBE_DEFAULT)
r += 1
_er_ds_ds_lab(r, 0, "NAT rule(可空)")
er_fl_ds_fnet_nat_rule = _er_ds_ds_ent()
er_fl_ds_fnet_nat_rule.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_fnet_nat_rule.insert(0, ER_DS_FNET_NAT_RULE_DEFAULT)
r += 1
_er_ds_ds_lab(r, 0, "NAT 出口 tunnel(可空)")
er_fl_ds_exit_tun = _er_ds_ds_ent()
er_fl_ds_exit_tun.grid(row=r, column=1, sticky="ew", **_pr)
er_fl_ds_exit_tun.insert(0, ER_DS_EXIT_TUNNEL_DEFAULT)
_er_ds_ds_lab(r, 2, "主线出口 IP(可空)")
er_fl_ds_exit_snat = _er_ds_ds_ent()
er_fl_ds_exit_snat.grid(row=r, column=3, sticky="ew", **_pr)
er_fl_ds_exit_snat.insert(0, ER_DS_EXIT_SNAT_IP_DEFAULT)
r += 1
er_fl_ds_bak_hint = tk.Label(
    er_fl_domain_body,
    text="Track 可空：为空时主 /32 静态路由不带 track。当 NAT rule / tunnel / 主线出口 IP 三项同填时生成 100.100 段；组名固定 GROUP-FNET-Whitelist，网段固定 100.100.100.0/24，并使用上方 100.100 探测IP变量。Track 为空则不下发 set track name。",
    font=FONT_UI, bg=BG_PANEL, fg=FG_DIM, anchor="w",
)
er_fl_ds_bak_hint.grid(row=r, column=1, columnspan=3, sticky="ew", pady=(0, 1))


def _er_ds_refresh_hint_wrap(_evt=None):
    try:
        body_w = max(int(er_fl_domain_body.winfo_width()), 1)
    except tk.TclError:
        return
    wl = max(160, body_w - 28)
    try:
        er_fl_ds_domainlist_hint.config(wraplength=wl)
        er_fl_ds_bak_hint.config(wraplength=wl)
    except tk.TclError:
        pass


er_fl_domain_body.bind("<Configure>", lambda _e: _er_ds_refresh_hint_wrap())
er_fl_domain_body.after(120, _er_ds_refresh_hint_wrap)


def er_fl_generate_flink():
    main_nh = er_fl_main_nh.get().strip() or str(globals().get("ER_FL_MAIN_NH_DEFAULT", "")).strip()
    backup_nh = er_fl_backup_nh.get().strip() or str(globals().get("ER_FL_BACKUP_NH_DEFAULT", "")).strip()
    if not main_nh or not backup_nh:
        messagebox.showwarning("参数缺失", "请先填写「主回程下一跳」和「备回程下一跳」。")
        er_fl_status.set("⚠  缺少主/备回程下一跳")
        return
    routes, err = parse_er_flink_headers(er_fl_left.get("1.0", tk.END))
    if err:
        messagebox.showwarning("数据头格式错误", err)
        er_fl_status.set("⚠  飞连数据头格式错误")
        return
    try:
        output = TEMPLATE_ER_FLINK_VISUAL.format(**_build_er_flink_format_dict(routes, main_nh, backup_nh))
    except Exception:
        output = build_er_flink_config(routes, main_nh, backup_nh)
    out = _er_fl_output_text()
    out.delete("1.0", tk.END)
    out.insert(tk.END, output)
    er_fl_status.set(f"✓  飞连配置已生成  ·  网段:{len(routes)}条")
    log_generate_config(
        tool="er_flink_tab",
        variant="flink",
        input_text=er_fl_left.get("1.0", tk.END).strip(),
        output_text=output,
    )


def _parse_dum_start(entry, name):
    s = entry.get().strip()
    if not s:
        return None, f"{name}不能为空"
    if not re.match(r"^\d+$", s):
        return None, f"{name}必须是整数"
    return int(s), None


def er_fl_generate_new_exit():
    main_nh = er_fl_main_pe_nh.get().strip() or str(globals().get("ER_NE_MAIN_PE_NH_DEFAULT", "")).strip()
    if not main_nh:
        messagebox.showwarning("参数缺失", "请先填写「主pe对接下一跳」。")
        er_fl_status.set("⚠  缺少主pe对接下一跳")
        return
    if not er_fl_main_dum.get().strip():
        er_fl_main_dum.insert(0, str(globals().get("ER_NE_MAIN_DUM_DEFAULT", "300")).strip())
    main_dum, err_main_dum = _parse_dum_start(er_fl_main_dum, "主新增ip dum号")
    if err_main_dum:
        messagebox.showwarning("参数错误", err_main_dum)
        er_fl_status.set("⚠  主新增ip dum号不合法")
        return
    main_nat = er_fl_main_nat_rule.get().strip() or str(globals().get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300")).strip()
    nat_src = er_fl_ne_nat_src.get().strip() or str(
        globals().get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "192.168.0.0/24")
    ).strip()

    parsed, err = parse_er_new_exit_blocks(er_fl_left.get("1.0", tk.END))
    if err:
        messagebox.showwarning("输入格式错误", err)
        er_fl_status.set("⚠  新增出口输入格式错误")
        return
    has_bk = "bk" in parsed and parsed.get("bk")

    # 备线参数 — 仅双线时需要
    bk_nh = ""
    bk_dum = 400
    bk_nat = "400"
    if has_bk:
        if not er_fl_bk_dum.get().strip():
            er_fl_bk_dum.insert(0, str(globals().get("ER_NE_BK_DUM_DEFAULT", "400")).strip())
        bk_nh = er_fl_bk_pe_nh.get().strip() or str(globals().get("ER_NE_BK_PE_NH_DEFAULT", "")).strip()
        if not bk_nh:
            messagebox.showwarning("参数缺失", "双线模式下请填写「备pe对接下一跳」。")
            er_fl_status.set("⚠  缺少备pe对接下一跳")
            return
        bk_dum_raw, err_bk_dum = _parse_dum_start(er_fl_bk_dum, "备新增IPdum号")
        if err_bk_dum:
            messagebox.showwarning("参数错误", err_bk_dum)
            er_fl_status.set("⚠  备新增IPdum号不合法")
            return
        bk_dum = bk_dum_raw
        bk_nat = er_fl_bk_nat_rule.get().strip() or str(globals().get("ER_NE_BK_NAT_RULE_DEFAULT", "400")).strip()

    if has_bk and nat_src.strip():
        for lab, nr in (("主 NAT rule 起始", main_nat), ("备 NAT rule 起始", bk_nat)):
            if not nr.isdigit() or not (1 <= int(nr) <= 999999):
                messagebox.showwarning("参数错误", f"{lab}须为 1～999999 的整数")
                er_fl_status.set(f"⚠  {lab}不合法")
                return
        if _er_ne_nat_source_normalized(nat_src) is None:
            messagebox.showwarning("参数错误", f"源网段非法：{nat_src!r}")
            er_fl_status.set("⚠  源网段 CIDR 不合法")
            return

    # FNET whitelist 参数
    fnet_probe = er_fl_ne_fnet_probe.get().strip() or str(globals().get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")).strip()
    fnet_tunnel = er_fl_ne_fnet_tunnel.get().strip() or str(globals().get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")).strip()
    fnet_nat_rule = er_fl_ne_fnet_nat_rule.get().strip() or str(globals().get("ER_NE_FNET_NAT_RULE_DEFAULT", "")).strip()

    # 三元组校验（仅双线时）
    f_filled = (bool(fnet_tunnel), bool(fnet_nat_rule))
    if has_bk and any(f_filled) and not all(f_filled):
        messagebox.showwarning("参数缺失", "NAT rule 号、NAT 出口 tunnel 须同时填写或全部留空")
        er_fl_status.set("⚠  FNET whitelist 参数不完整")
        return

    init_cfg = {
        "main_pe_next_hop": main_nh,
        "bk_pe_next_hop": bk_nh,
        "main_dum_start": main_dum,
        "bk_dum_start": bk_dum,
        "main_nat_rule": main_nat,
        "bk_nat_rule": bk_nat,
        "nat_source_cidr": nat_src,
        "fnet_probe": fnet_probe,
        "fnet_exit_tunnel": fnet_tunnel,
        "fnet_nat_rule": fnet_nat_rule,
    }
    if has_bk and nat_src.strip():
        span_err = er_new_exit_nat_rule_span_error(parsed, init_cfg)
        if span_err:
            messagebox.showwarning("NAT rule 冲突", span_err)
            er_fl_status.set("⚠  NAT rule 区间不合法")
            return
    try:
        output = TEMPLATE_ER_NEW_EXIT_VISUAL.format(**_build_er_new_exit_format_dict(parsed, init_cfg))
    except Exception:
        output = build_er_new_exit_config(parsed, init_cfg)
    out = _er_fl_output_text()
    out.delete("1.0", tk.END)
    out.insert(tk.END, output)
    oversea_total = len(parsed["main"]["oversea_pairs"])
    line_count = 2 if has_bk else 1
    if has_bk:
        oversea_total += len(parsed["bk"]["oversea_pairs"])
    er_fl_status.set(f"✓  新增出口配置已生成  ·  线路:{line_count}  ·  海外IP:{oversea_total}条")
    log_generate_config(
        tool="er_flink_tab",
        variant="new_exit",
        input_text=er_fl_left.get("1.0", tk.END).strip(),
        output_text=output,
    )


def er_fl_generate_domain_split():
    cfg = er_ds_cfg_from_widgets()
    out, err = build_er_domain_split_script(cfg)
    if err:
        messagebox.showwarning("参数错误", err)
        er_fl_status.set(f"⚠  {err}")
        return
    out_w = _er_fl_output_text()
    out_w.delete("1.0", tk.END)
    out_w.insert(tk.END, out)
    er_fl_status.set("✓  域名分流脚本已生成")
    log_generate_config(
        tool="er_flink_tab",
        variant="domain_split",
        input_text=cfg["domains_text"].strip()[:2000],
        output_text=out,
    )


def er_fl_generate():
    m = er_fl_mode_var.get()
    if m == "domain_split":
        er_fl_generate_domain_split()
    elif m == "new_exit":
        er_fl_generate_new_exit()
    else:
        er_fl_generate_flink()


def _er_fl_output_text():
    return er_fl_ds_right if er_fl_mode_var.get() == "domain_split" else er_fl_right


def er_fl_export():
    c = _er_fl_output_text().get("1.0", tk.END).strip()
    if not c:
        er_fl_status.set("⚠  尚无配置")
        return
    p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
    if p:
        open(p, "w", encoding="utf-8").write(c)
        er_fl_status.set(f"✓  已导出：{p}")


def er_fl_reset():
    _er_fl_output_text().delete("1.0", tk.END)
    if er_fl_mode_var.get() == "domain_split":
        er_ds_apply_globals_to_widgets()
        er_fl_status.set("↺  域名分流已恢复为当前初始化默认")
        return
    er_fl_left.delete("1.0", tk.END)
    er_fl_main_nh.delete(0, tk.END)
    er_fl_main_nh.insert(0, str(globals().get("ER_FL_MAIN_NH_DEFAULT", "")).strip())
    er_fl_backup_nh.delete(0, tk.END)
    er_fl_backup_nh.insert(0, str(globals().get("ER_FL_BACKUP_NH_DEFAULT", "")).strip())
    er_fl_main_pe_nh.delete(0, tk.END)
    er_fl_main_pe_nh.insert(0, str(globals().get("ER_NE_MAIN_PE_NH_DEFAULT", "")).strip())
    er_fl_bk_pe_nh.delete(0, tk.END)
    er_fl_bk_pe_nh.insert(0, str(globals().get("ER_NE_BK_PE_NH_DEFAULT", "")).strip())
    er_fl_main_dum.delete(0, tk.END)
    er_fl_bk_dum.delete(0, tk.END)
    er_fl_main_dum.insert(0, str(globals().get("ER_NE_MAIN_DUM_DEFAULT", "300")).strip())
    er_fl_bk_dum.insert(0, str(globals().get("ER_NE_BK_DUM_DEFAULT", "400")).strip())
    er_fl_main_nat_rule.delete(0, tk.END)
    er_fl_main_nat_rule.insert(0, str(globals().get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300")).strip())
    er_fl_bk_nat_rule.delete(0, tk.END)
    er_fl_bk_nat_rule.insert(0, str(globals().get("ER_NE_BK_NAT_RULE_DEFAULT", "400")).strip())
    er_fl_ne_nat_src.delete(0, tk.END)
    er_fl_ne_nat_src.insert(
        0, str(globals().get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "192.168.0.0/24")).strip()
    )
    er_fl_ne_fnet_probe.delete(0, tk.END)
    er_fl_ne_fnet_probe.insert(0, str(globals().get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")).strip())
    er_fl_ne_fnet_tunnel.delete(0, tk.END)
    er_fl_ne_fnet_tunnel.insert(0, str(globals().get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")).strip())
    er_fl_ne_fnet_nat_rule.delete(0, tk.END)
    er_fl_ne_fnet_nat_rule.insert(0, str(globals().get("ER_NE_FNET_NAT_RULE_DEFAULT", "")).strip())
    er_fl_status.set("↺  已恢复当前模式初始内容")


def _er_fl_grid_remove_safe(widget):
    try:
        if widget.winfo_manager() == "grid":
            widget.grid_remove()
    except tk.TclError:
        pass


def _er_fl_domain_init_sash():
    try:
        w = er_fl_domain_hpane.winfo_width()
        if w > 120:
            er_fl_domain_hpane.sashpos(0, int(w * 0.48))
    except Exception:
        pass


def er_fl_refresh_mode(*_args):
    mode = er_fl_mode_var.get()
    if mode == "flink":
        er_fl_btn_mode_flink.config(bg=FG_BRT, fg=ACCENT_US)
        er_fl_btn_mode_new.config(bg=BG_INPUT, fg=FG_DIM)
        er_fl_btn_mode_ds.config(bg=BG_INPUT, fg=FG_DIM)
    elif mode == "new_exit":
        er_fl_btn_mode_flink.config(bg=BG_INPUT, fg=FG_DIM)
        er_fl_btn_mode_new.config(bg=FG_BRT, fg=ACCENT_US)
        er_fl_btn_mode_ds.config(bg=BG_INPUT, fg=FG_DIM)
    else:
        er_fl_btn_mode_flink.config(bg=BG_INPUT, fg=FG_DIM)
        er_fl_btn_mode_new.config(bg=BG_INPUT, fg=FG_DIM)
        er_fl_btn_mode_ds.config(bg=FG_BRT, fg=ACCENT_US)
    if mode == "domain_split":
        _er_fl_grid_remove_safe(er_fl_vpane)
        er_fl_domain_hpane.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 0))
        tab_fl.after(120, _er_fl_domain_init_sash)
        tab_fl.after(500, _er_fl_domain_init_sash)
        er_fl_status.set("就绪  ·  域名分流：左侧填初始化项，右侧生成脚本")
        return
    _er_fl_grid_remove_safe(er_fl_domain_hpane)
    er_fl_vpane.grid(row=1, column=0, sticky="nsew", padx=6, pady=(4, 0))
    tab_fl.after(120, _er_fl_init_sash)
    tab_fl.after(500, _er_fl_init_sash)
    if mode == "new_exit":
        er_fl_cfg_flink.grid_remove()
        er_fl_cfg_new.grid()
        er_fl_left.delete("1.0", tk.END)
        er_fl_demo_t.config(state="normal")
        er_fl_demo_t.delete("1.0", tk.END)
        er_fl_demo_t.insert("1.0", ER_NEW_EXIT_EXAMPLE)
        er_fl_demo_t.config(state="disabled")
        er_fl_cfg_h.configure(bg=ACCENT_US)
        for w in er_fl_cfg_h.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(text="  新增出口 · 左主线 / 右备线")
        er_fl_status.set("就绪  ·  新增出口：右上参数左主线右备线，左下粘贴数据头后生成")
    else:
        er_fl_cfg_new.grid_remove()
        er_fl_cfg_flink.grid()
        er_fl_left.delete("1.0", tk.END)
        er_fl_demo_t.config(state="normal")
        er_fl_demo_t.delete("1.0", tk.END)
        er_fl_demo_t.insert("1.0", ER_FL_DEFAULT_HEADERS)
        er_fl_demo_t.config(state="disabled")
        er_fl_cfg_h.configure(bg=ACCENT_US)
        for w in er_fl_cfg_h.winfo_children():
            if isinstance(w, tk.Label):
                w.configure(text="  回程下一跳")
        er_fl_status.set("就绪  ·  飞连模式：左上示范，左下输入，填写主/备回程下一跳")


def _er_fl_init_sash(vp=er_fl_vpane):
    try:
        total = vp.winfo_height()
        if total > 100:
            vp.sashpos(0, int(total * 0.46))
    except Exception:
        pass


tab_fl.after(150, _er_fl_init_sash)
tab_fl.after(600, _er_fl_init_sash)

tk.Frame(tab_fl, bg=BORDER, height=1).grid(row=2, column=0, sticky="ew")
er_fl_btm = tk.Frame(tab_fl, bg=BG_HDR, height=42)
er_fl_btm.grid(row=3, column=0, sticky="ew")
er_fl_btm.grid_propagate(False)
tab_fl.rowconfigure(2, weight=0)
tab_fl.rowconfigure(3, weight=0)
er_fl_status = tk.StringVar(value="就绪  ·  飞连模式：左上示范，左下输入，填写主/备回程下一跳")
tk.Label(er_fl_btm, textvariable=er_fl_status, font=FONT_TINY, bg=BG_HDR, fg="#7aafd4").pack(
    side="left", padx=12
)
er_fl_btn_exp = flat_btn(er_fl_btm, "导出 TXT", "#16a085")
er_fl_btn_exp.pack(side="right", padx=(0, 12), pady=7)
er_fl_btn_gen = flat_btn(er_fl_btm, "⚡  生成配置", ACCENT_US)
er_fl_btn_gen.pack(side="right", padx=(0, 5), pady=7)
er_fl_btn_rst = flat_btn(er_fl_btm, "↺  恢复初始", "#6c757d")
er_fl_btn_rst.pack(side="right", padx=(0, 5), pady=7)
er_fl_btn_gen.bind("<Button-1>", lambda e: er_fl_generate())
er_fl_btn_exp.bind("<Button-1>", lambda e: er_fl_export())
er_fl_btn_rst.bind("<Button-1>", lambda e: er_fl_reset())
er_fl_btn_mode_flink.bind("<Button-1>", lambda e: er_fl_mode_var.set("flink"))
er_fl_btn_mode_new.bind("<Button-1>", lambda e: er_fl_mode_var.set("new_exit"))
er_fl_btn_mode_ds.bind("<Button-1>", lambda e: er_fl_mode_var.set("domain_split"))
er_fl_mode_var.trace_add("write", er_fl_refresh_mode)
er_fl_refresh_mode()


def _visual_merge_er_init(profile: str, updates: dict) -> None:
    """all_in_one：仅刷新对应页签（hk / us），互不覆盖另一页的 globals。"""
    g = globals()
    _BOOL_KEYS = frozenset({
        "DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP", "DEFAULT_GEN_RETURN_ROUTE",
    })

    def _pb(val) -> bool:
        s = str(val).strip().lower()
        return s in ("1", "true", "yes", "on", "开")

    def _dest(k: str) -> str:
        if profile == "hk" and k.startswith("DEFAULT_"):
            return "HK_" + k
        return k

    for k, v in updates.items():
        dk = _dest(k)
        if dk not in g:
            continue
        if k in _BOOL_KEYS:
            g[dk] = _pb(v)
        else:
            g[dk] = str(v).strip()
    if profile == "flink":
        try:
            er_fl_main_nh.delete(0, tk.END)
            er_fl_main_nh.insert(0, str(g.get("ER_FL_MAIN_NH_DEFAULT", "")).strip())
            er_fl_backup_nh.delete(0, tk.END)
            er_fl_backup_nh.insert(0, str(g.get("ER_FL_BACKUP_NH_DEFAULT", "")).strip())
        except Exception:
            pass
        return
    if profile == "new_exit":
        try:
            er_fl_main_pe_nh.delete(0, tk.END)
            er_fl_main_pe_nh.insert(0, str(g.get("ER_NE_MAIN_PE_NH_DEFAULT", "")).strip())
            er_fl_bk_pe_nh.delete(0, tk.END)
            er_fl_bk_pe_nh.insert(0, str(g.get("ER_NE_BK_PE_NH_DEFAULT", "")).strip())
            er_fl_main_dum.delete(0, tk.END)
            er_fl_main_dum.insert(0, str(g.get("ER_NE_MAIN_DUM_DEFAULT", "300")).strip())
            er_fl_bk_dum.delete(0, tk.END)
            er_fl_bk_dum.insert(0, str(g.get("ER_NE_BK_DUM_DEFAULT", "400")).strip())
            er_fl_main_nat_rule.delete(0, tk.END)
            er_fl_main_nat_rule.insert(0, str(g.get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300")).strip())
            er_fl_bk_nat_rule.delete(0, tk.END)
            er_fl_bk_nat_rule.insert(0, str(g.get("ER_NE_BK_NAT_RULE_DEFAULT", "400")).strip())
            er_fl_ne_nat_src.delete(0, tk.END)
            er_fl_ne_nat_src.insert(
                0, str(g.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "192.168.0.0/24")).strip()
            )
            er_fl_ne_fnet_probe.delete(0, tk.END)
            er_fl_ne_fnet_probe.insert(0, str(g.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")).strip())
            er_fl_ne_fnet_tunnel.delete(0, tk.END)
            er_fl_ne_fnet_tunnel.insert(0, str(g.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")).strip())
            er_fl_ne_fnet_nat_rule.delete(0, tk.END)
            er_fl_ne_fnet_nat_rule.insert(0, str(g.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")).strip())
        except Exception:
            pass
        return
    if profile == "domain_split":
        try:
            er_ds_apply_globals_to_widgets()
        except Exception:
            pass
        return
    try:
        if profile == "hk":
            hk_reset_net()
        else:
            us_reset_net()
    except Exception:
        pass


root.mainloop()
