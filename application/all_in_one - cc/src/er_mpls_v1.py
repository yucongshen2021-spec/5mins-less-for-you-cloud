#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""er_mpls_v1 正式试用版  MPLS 配置生成工具
  国内：主/备均为 GRE+VPN 双 PE
  海外：主线 vtun 直连骨干，备线 GRE+VPN
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
# 网络格式校验
# =====================================================================
def _validate_cidr(value, name="CIDR"):
    if not value or not value.strip():
        return True, None
    s = value.strip()
    try:
        ipaddress.ip_network(s, strict=False)
    except ValueError as e:
        return False, f"{name}「{s}」格式错误：{e}"
    return True, None

def _validate_ip(value, name="IP"):
    if not value or not value.strip():
        return True, None
    s = value.strip()
    try:
        ipaddress.ip_address(s)
    except ValueError as e:
        return False, f"{name}「{s}」格式错误：{e}（每段须 0～255）"
    return True, None

def _validate_inner_nets(raw):
    nets, errors = [], []
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
DEFAULT_WAN_ETH    = "0"
DEFAULT_LAN_ETH    = "5"
# 与 ER FastIP 可视化 / 页签字段对齐（user_init 可写）
DEFAULT_WAN_DHCP   = False
DEFAULT_LAN_DHCP   = True
DEFAULT_GEN_RETURN_ROUTE = False
DEFAULT_WAN_IP_PLAIN = DEFAULT_WAN_CIDR.split("/", 1)[0].strip() if DEFAULT_WAN_CIDR else ""
DEFAULT_LAN_IP_PLAIN = DEFAULT_LAN_CIDR.split("/", 1)[0].strip() if DEFAULT_LAN_CIDR else ""
DEFAULT_LAN_GW     = DEFAULT_LAN_IP_PLAIN

_MPLS_INIT_ETH_WAN_VARS: list[tk.StringVar] = []
_MPLS_INIT_ETH_LAN_VARS: list[tk.StringVar] = []

# 国内/海外 Tab 各有一套网络面板 reset，嵌入后由此列表统一刷新
_MPLS_TAB_RESET_NET_FUNCS: list = []


# =====================================================================
# 动态配置段构建器
# =====================================================================
def _build_vtun_section(px, d):
    vid = d.get(f"{px}_vtun_id", "")
    if not vid:
        return ""
    pe   = d.get(f"{px}_vtun_pe", "")
    loc  = d.get(f"{px}_vtun_local", "")
    rem  = d.get(f"{px}_vtun_remote", "")
    dock = d.get(f"{px}_vtun_docking", "")
    port = d.get(f"{px}_vtun_port", "")
    tag  = "MAIN" if px == "main" else "BK"
    return "\n".join([
        f"set interfaces openvpn {vid} description '{tag}_{pe}'",
        f"set interfaces openvpn {vid} firewall local name 'WAN2LOCAL'",
        f"set interfaces openvpn {vid} local-address {loc} subnet-mask '255.255.255.252'",
        f"set interfaces openvpn {vid} mode 'site-to-site'",
        f"set interfaces openvpn {vid} openvpn-option '--nobind'",
        f"set interfaces openvpn {vid} openvpn-option '--ping 10'",
        f"set interfaces openvpn {vid} openvpn-option '--ping-restart 60'",
        f"set interfaces openvpn {vid} openvpn-option '--persist-tun'",
        f"set interfaces openvpn {vid} openvpn-option '--fragment 1300'",
        f"set interfaces openvpn {vid} protocol 'udp'",
        f"set interfaces openvpn {vid} remote-address '{rem}'",
        f"set interfaces openvpn {vid} remote-host '{dock}'",
        f"set interfaces openvpn {vid} remote-port '{port}'",
        f"set interfaces openvpn {vid} shared-secret-key-file '/config/auth/openvpn.secret'",
    ])


def _build_gre_section(px, d):
    tun = d.get(f"{px}_gre_tun", "")
    if not tun:
        return ""
    pe       = d.get(f"{px}_gre_pe", "")
    ce_ip    = d.get(f"{px}_gre_ce_ip", "")
    remote   = d.get(f"{px}_gre_remote", "")
    src_addr = d.get(f"{px}_vtun_local", "")
    tag      = "MAIN" if px == "main" else "BK"
    return "\n".join([
        f"set interfaces tunnel {tun} address '{ce_ip}/30'",
        f"set interfaces tunnel {tun} description '{tag}_{pe}'",
        f"set interfaces tunnel {tun} encapsulation 'gre'",
        f"set interfaces tunnel {tun} firewall local name 'WAN2LOCAL'",
        f"set interfaces tunnel {tun} mtu '1476'",
        f"set interfaces tunnel {tun} multicast 'disable'",
        f"set interfaces tunnel {tun} parameters ip ttl '255'",
        f"set interfaces tunnel {tun} remote '{remote}'",
        f"set interfaces tunnel {tun} source-address '{src_addr}'",
    ])


def _build_tunnel_routes(d):
    lines = []
    has_main_vtun = bool(d.get("main_vtun_id"))
    has_bk_vtun   = bool(d.get("bk_vtun_id"))

    if has_main_vtun and d.get("main_vtun_docking"):
        lines.append(f"set protocols static route {d['main_vtun_docking']}/32 next-hop 1.1.1.1")
    if has_bk_vtun and d.get("bk_vtun_docking"):
        lines.append(f"set protocols static route {d['bk_vtun_docking']}/32 next-hop 1.1.1.1")

    main_gre_remote = d.get("main_gre_remote", "")
    bk_gre_remote   = d.get("bk_gre_remote", "")

    if main_gre_remote:
        if has_main_vtun and d.get("main_vtun_remote"):
            nh = d["main_vtun_remote"]
        else:
            nh = "1.1.1.1"
        lines.append(f"set protocols static route {main_gre_remote}/32 next-hop {nh}")
    if bk_gre_remote:
        if has_bk_vtun and d.get("bk_vtun_remote"):
            nh = d["bk_vtun_remote"]
        else:
            nh = "1.1.1.1"
        lines.append(f"set protocols static route {bk_gre_remote}/32 next-hop {nh}")
    return "\n".join(lines)


def _build_header_comment(d):
    lines = [
        f"# ==========================================================",
        f"# er_mpls_v1 正式试用版  {d.get('config_type','')}配置  Hostname: {d.get('hostname','')}",
    ]
    for px, label in [("main", "主线"), ("bk", "备线")]:
        lt = d.get(f"{px}_line_type", "")
        if lt == "vtun_only":
            vid = d.get(f"{px}_vtun_id", "")
            lines.append(f"# {label}(vtun直连)  PE:{d.get(f'{px}_vtun_pe','')}  TUNNEL:{vid}(port:{d.get(f'{px}_vtun_port','')})")
            lines.append(f"#       WANIP:{d.get(f'{px}_vtun_wanip','')}  PE侧:{d.get(f'{px}_vtun_remote','')}  CE侧:{d.get(f'{px}_vtun_local','')}")
            lines.append(f"#       Docking:{d.get(f'{px}_vtun_docking','')}")
        else:
            gre_tun = d.get(f"{px}_gre_tun", "")
            if gre_tun:
                lines.append(f"# {label}  GRE PE:{d.get(f'{px}_gre_pe','')}  TUNNEL:{gre_tun}")
                lines.append(f"#       WANIP:{d.get(f'{px}_gre_wanip','')}  PE侧:{d.get(f'{px}_gre_pe_ip','')}  CE侧:{d.get(f'{px}_gre_ce_ip','')}")
                lines.append(f"#       GRE remote:{d.get(f'{px}_gre_remote','')}")
            vtun_id = d.get(f"{px}_vtun_id", "")
            if vtun_id:
                lines.append(f"#   VPN PE:{d.get(f'{px}_vtun_pe','')}  TUNNEL:{vtun_id}(port:{d.get(f'{px}_vtun_port','')})")
                lines.append(f"#       local:{d.get(f'{px}_vtun_local','')}  remote:{d.get(f'{px}_vtun_remote','')}  docking:{d.get(f'{px}_vtun_docking','')}")
    lines += [
        f"# ───────────────────────────────────────────────────────",
        f"# CE AS:{d.get('ce_as','')}  主PE AS:{d.get('main_pe_as','')}  备PE AS:{d.get('bk_pe_as','')}",
        f"# 注意：请自行增加nat/dns/mtu部分！！",
        f"# ==========================================================",
    ]
    return "\n".join(lines)


# =====================================================================
# MPLS 配置生成
# =====================================================================
# ═══ MPLS 模板常量（从 editor_defaults .tpl 文件生成） ═══
TEMPLATE_MPLS_DOMESTIC = """# ==========================================================
# er_mpls_v1 可视化模板  {config_type}配置  Hostname: {hostname}
# 主线  line_type:{main_line_type}  GRE:{main_gre_tun}  VTUN:{main_vtun_id}
#       GRE PE:{main_gre_pe}  WANIP:{main_gre_wanip}  PE侧:{main_gre_pe_ip}  CE侧:{main_gre_ce_ip}
#       VTUN PE:{main_vtun_pe} local:{main_vtun_local} remote:{main_vtun_remote} docking:{main_vtun_docking}
# 备线  line_type:{bk_line_type}  GRE:{bk_gre_tun}  VTUN:{bk_vtun_id}
#       GRE PE:{bk_gre_pe}  WANIP:{bk_gre_wanip}  PE侧:{bk_gre_pe_ip}  CE侧:{bk_gre_ce_ip}
#       VTUN PE:{bk_vtun_pe} local:{bk_vtun_local} remote:{bk_vtun_remote} docking:{bk_vtun_docking}
# CE AS:{ce_as}  主PE AS:{main_pe_as}  备PE AS:{bk_pe_as}
# ==========================================================
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
{gre_fw_mss_block}
set firewall receive-redirects 'disable'
set firewall send-redirects 'disable'
set firewall source-validation 'disable'
set firewall syn-cookies 'enable'
set firewall twa-hazards-protection 'disable'
set interfaces ethernet {wan_if} address '{wan_addr}'
set interfaces ethernet {wan_if} description 'TO-WAN'
{lan_if_block}
{main_vtun_section}
{bk_vtun_section}
{main_gre_section}
{bk_gre_section}
set openfalcon endpoint-name '{hostname}'
set openfalcon server-address '192.168.237.86'
{return_routes_block}
{prefix_list_block}
{dhcp_server_block}
set policy route-map AS{ce_as}-OUT rule 10 action 'permit'
set policy route-map AS{ce_as}-OUT rule 10 match ip address prefix-list 'AS{ce_as}-OUT'
set policy route-map AS{ce_as}-OUT rule 20 action 'deny'
set policy route-map bgp-from--BACKUP rule 10 action 'permit'
set policy route-map bgp-from--BACKUP rule 10 set local-preference '50'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute connected route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute static route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} remote-as '{main_pe_as}'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} update-source '{main_bgp_update_source}'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast route-map import 'bgp-from--BACKUP'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} remote-as '{bk_pe_as}'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} update-source '{bk_bgp_update_source}'
set protocols bgp {ce_as} timers holdtime '15'
set protocols bgp {ce_as} timers keepalive '5'
{main_track_block}
{wan_route_block}
{mpls_static_routes_block}
set system host-name '{hostname}'
"""
TEMPLATE_MPLS_OVERSEAS = """# ==========================================================
# er_mpls_v1 可视化模板  {config_type}配置  Hostname: {hostname}
# 主线  line_type:{main_line_type}  GRE:{main_gre_tun}  VTUN:{main_vtun_id}
#       GRE PE:{main_gre_pe}  WANIP:{main_gre_wanip}  PE侧:{main_gre_pe_ip}  CE侧:{main_gre_ce_ip}
#       VTUN PE:{main_vtun_pe} local:{main_vtun_local} remote:{main_vtun_remote} docking:{main_vtun_docking}
# 备线  line_type:{bk_line_type}  GRE:{bk_gre_tun}  VTUN:{bk_vtun_id}
#       GRE PE:{bk_gre_pe}  WANIP:{bk_gre_wanip}  PE侧:{bk_gre_pe_ip}  CE侧:{bk_gre_ce_ip}
#       VTUN PE:{bk_vtun_pe} local:{bk_vtun_local} remote:{bk_vtun_remote} docking:{bk_vtun_docking}
# CE AS:{ce_as}  主PE AS:{main_pe_as}  备PE AS:{bk_pe_as}
# ==========================================================
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
{gre_fw_mss_block}
set firewall receive-redirects 'disable'
set firewall send-redirects 'disable'
set firewall source-validation 'disable'
set firewall syn-cookies 'enable'
set firewall twa-hazards-protection 'disable'
set interfaces ethernet {wan_if} address '{wan_addr}'
set interfaces ethernet {wan_if} description 'TO-WAN'
{lan_if_block}
{main_vtun_section}
{bk_vtun_section}
{main_gre_section}
{bk_gre_section}
set openfalcon endpoint-name '{hostname}'
set openfalcon server-address '192.168.237.86'
set policy route-map AS{ce_as}-OUT rule 10 action 'permit'
set policy route-map AS{ce_as}-OUT rule 10 match ip address prefix-list 'AS{ce_as}-OUT'
set policy route-map AS{ce_as}-OUT rule 20 action 'deny'
set policy route-map bgp-from--BACKUP rule 10 action 'permit'
set policy route-map bgp-from--BACKUP rule 10 set local-preference '50'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute connected route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute static route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} remote-as '{main_pe_as}'
set protocols bgp {ce_as} neighbor {main_bgp_neighbor} update-source '{main_bgp_update_source}'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast route-map import 'bgp-from--BACKUP'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} remote-as '{bk_pe_as}'
set protocols bgp {ce_as} neighbor {bk_bgp_neighbor} update-source '{bk_bgp_update_source}'
set protocols bgp {ce_as} timers holdtime '15'
set protocols bgp {ce_as} timers keepalive '5'
{main_track_block}
{wan_route_block}
{mpls_static_routes_block}
{return_routes_block}
{prefix_list_block}
{dhcp_server_block}
set system host-name '{hostname}'
"""


# ═══ MPLS builder 函数（模板驱动） ═══

def _mpls_inject_init_defaults(d):
    g = globals()
    for k in ("DEFAULT_WAN_ETH", "DEFAULT_WAN_CIDR", "DEFAULT_WAN_GW",
              "DEFAULT_LAN_ETH", "DEFAULT_LAN_CIDR", "DEFAULT_LAN_GW",
              "DEFAULT_INNER_NETS", "DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP",
              "DEFAULT_GEN_RETURN_ROUTE", "DEFAULT_BYPASS",
              "DEFAULT_DNS1", "DEFAULT_DNS2"):
        v = g.get(k)
        if v is not None:
            d.setdefault(k, str(v) if not isinstance(v, bool) else v)
    if d.get("DEFAULT_BYPASS") in (True, "True", "true", "1"):
        d["DEFAULT_LAN_ETH"] = ""
        d["DEFAULT_LAN_CIDR"] = ""
        d["DEFAULT_LAN_GW"] = ""
        d["DEFAULT_LAN_DHCP"] = False


def _mpls_compute_track_names(d):
    """Compute {px}_track name based on line_type.

    vtun_only lines have no GRE tunnel, so the track object name is derived
    from the VTUN id (e.g. 'vtun1104' -> 'Track-vtun1104'). This matches the
    desktop generate_mpls_config behaviour where m_tun falls back to vtun_id
    when line_type is vtun_only.
    """
    for px in ("main", "bk"):
        gre_tun = d.get(f"{px}_gre_tun", "")
        if gre_tun:
            d.setdefault(f"{px}_track",
                gre_tun.replace("Tunnel", "Track-"))
        else:
            vtun_id = d.get(f"{px}_vtun_id", "")
            d.setdefault(f"{px}_track",
                f"Track-{vtun_id}" if vtun_id else "")


def _mpls_line_pe_ce(d, px):
    """Return (pe_ip, ce_ip, tun_name) for line `px` based on line_type.

    For vtun_only lines, the BGP peer / track target is the VTUN remote /
    local IP rather than the GRE PE/CE IP. Mirrors the logic in
    generate_mpls_config (lines 792-825).
    """
    lt = d.get(f"{px}_line_type", "")
    if lt == "vtun_only":
        return (d.get(f"{px}_vtun_remote", ""),
                d.get(f"{px}_vtun_local", ""),
                d.get(f"{px}_vtun_id", ""))
    return (d.get(f"{px}_gre_pe_ip", ""),
            d.get(f"{px}_gre_ce_ip", ""),
            d.get(f"{px}_gre_tun", ""))


def _mpls_compute_section_blocks(d):
    """Pre-compute conditional template blocks so the disk template can be
    rendered with a plain ``str.format(**d)`` call.

    These block placeholders let the overseas/domestic templates omit GRE
    tunnel / track / static-route lines when a line is ``vtun_only`` (the
    overseas main-line design: only a VTUN is used, no GRE tunnel).
    """
    # 1) firewall options adjust-mss -- only for tunnels that actually exist
    mss_lines = []
    for tun in (d.get("main_gre_tun", ""), d.get("bk_gre_tun", "")):
        if tun:
            mss_lines.append(f"set firewall options interface {tun} adjust-mss '1400'")
    d["gre_fw_mss_block"] = "\n".join(mss_lines)

    # 2) VTUN (OpenVPN) interface sections
    d["main_vtun_section"] = _build_vtun_section("main", d)
    d["bk_vtun_section"]   = _build_vtun_section("bk", d)

    # 3) GRE tunnel interface sections (empty when line is vtun_only)
    d["main_gre_section"] = _build_gre_section("main", d)
    d["bk_gre_section"]   = _build_gre_section("bk", d)

    # 4) Track object block (only when there is a tun to track).
    #    The track object name is m_tun / b_tun (the raw vtun_id for vtun_only
    #    lines, or the gre_tun for vtun_gre lines) -- this mirrors the desktop
    #    generate_mpls_config logic (m_tun / b_tun are passed straight to the
    #    `set track name` line).
    m_pe_ip, _m_ce, m_tun = _mpls_line_pe_ce(d, "main")
    b_pe_ip, _b_ce, b_tun = _mpls_line_pe_ce(d, "bk")
    d["main_track_block"] = ""
    if m_tun:
        d["main_track_block"] = "\n".join([
            f"set track name {m_tun} failure-count '2'",
            f"set track name {m_tun} success-count '2'",
            f"set track name {m_tun} test 10 resp-time '5'",
            f"set track name {m_tun} test 10 target '{m_pe_ip}'",
            f"set track name {m_tun} test 10 ttl-limit '1'",
            f"set track name {m_tun} test 10 type 'ping'",
        ])

    # 5) Static routes that depend on line_type (PE-IP next-hop / track name).
    #    Empty next-hop / track lines are skipped to avoid broken config.
    route_lines = []
    if m_pe_ip:
        route_lines.append(f"set protocols static route 114.113.245.99/32 next-hop {m_pe_ip}")
    if b_pe_ip:
        route_lines.append(f"set protocols static route 114.113.245.100/32 next-hop {b_pe_ip}")
    # Tunnel docking routes (vtun_docking -> 1.1.1.1) and gre_remote -> vtun_remote
    route_lines.append(_build_tunnel_routes(d))
    # Tracked / backup routes to the monitoring targets (only when pe_ip exists)
    if m_pe_ip and m_tun:
        route_lines.append(f"set protocols static route 192.168.55.250/32 next-hop {m_pe_ip} track {m_tun}")
    if b_pe_ip:
        route_lines.append(f"set protocols static route 192.168.55.250/32 next-hop {b_pe_ip} distance '5'")
    if m_pe_ip and m_tun:
        route_lines.append(f"set protocols static route 192.168.237.86/32 next-hop {m_pe_ip} track {m_tun}")
    if b_pe_ip:
        route_lines.append(f"set protocols static route 192.168.237.86/32 next-hop {b_pe_ip} distance '5'")
    d["mpls_static_routes_block"] = "\n".join(l for l in route_lines if l)


def _mpls_compute_bgp_vars(d):
    """Set {px}_bgp_neighbor and {px}_bgp_update_source for template BGP lines.
    For vtun_only lines, BGP peer is the VTUN remote/local IP (not GRE PE/CE IP)."""
    for px in ("main", "bk"):
        line_type = d.get(f"{px}_line_type", "")
        if line_type == "vtun_only":
            d[f"{px}_bgp_neighbor"] = d.get(f"{px}_vtun_remote", "")
            d[f"{px}_bgp_update_source"] = d.get(f"{px}_vtun_local", "")
        else:
            d[f"{px}_bgp_neighbor"] = d.get(f"{px}_gre_pe_ip", "")
            d[f"{px}_bgp_update_source"] = d.get(f"{px}_gre_ce_ip", "")


def build_mpls_domestic_format_dict(raw: str):
    d = parse_epoch_mpls(raw)
    d["config_type"] = "国内"
    if not d.get("hostname"):
        d["hostname"] = extract_lineid_mpls(raw) or "（请填写Hostname）"
    _mpls_inject_init_defaults(d)
    d.setdefault("return_routes_block", "")
    d.setdefault("prefix_list_block", "")
    # Ensure WAN/LAN template keys always exist
    _wan_dhcp = d.get("DEFAULT_WAN_DHCP", False)
    _lan_dhcp = d.get("DEFAULT_LAN_DHCP", True)
    _bypass  = d.get("DEFAULT_BYPASS", False)
    _wan_if  = f"eth{str(d.get('DEFAULT_WAN_ETH', '0')).strip() or '0'}"
    _lan_if  = f"eth{str(d.get('DEFAULT_LAN_ETH', '5')).strip() or '5'}"
    _wan_cidr = str(d.get("DEFAULT_WAN_CIDR", "192.168.1.10/24"))
    _wan_gw   = str(d.get("DEFAULT_WAN_GW", "192.168.1.1"))
    _lan_cidr = str(d.get("DEFAULT_LAN_CIDR", "192.168.5.1/24"))
    blocks = build_wan_lan_blocks(_wan_if, bool(_wan_dhcp) if not isinstance(_wan_dhcp, bool) else _wan_dhcp,
                                  _wan_cidr, _wan_gw, _lan_if,
                                  bool(_lan_dhcp) if not isinstance(_lan_dhcp, bool) else _lan_dhcp,
                                  _lan_cidr, bypass=bool(_bypass) if not isinstance(_bypass, bool) else _bypass)
    d.update(blocks)
    _mpls_compute_track_names(d)
    _mpls_compute_bgp_vars(d)
    _mpls_compute_section_blocks(d)
    return d, None


def build_mpls_overseas_format_dict(raw: str):
    d = parse_epoch_mpls(raw)
    d["config_type"] = "海外"
    if not d.get("hostname"):
        d["hostname"] = extract_lineid_mpls(raw) or "（请填写Hostname）"
    _mpls_inject_init_defaults(d)
    d.setdefault("return_routes_block", "")
    d.setdefault("prefix_list_block", "")
    # Ensure WAN/LAN template keys always exist
    _wan_dhcp = d.get("DEFAULT_WAN_DHCP", False)
    _lan_dhcp = d.get("DEFAULT_LAN_DHCP", True)
    _bypass  = d.get("DEFAULT_BYPASS", False)
    _wan_if  = f"eth{str(d.get('DEFAULT_WAN_ETH', '0')).strip() or '0'}"
    _lan_if  = f"eth{str(d.get('DEFAULT_LAN_ETH', '5')).strip() or '5'}"
    _wan_cidr = str(d.get("DEFAULT_WAN_CIDR", "192.168.1.10/24"))
    _wan_gw   = str(d.get("DEFAULT_WAN_GW", "192.168.1.1"))
    _lan_cidr = str(d.get("DEFAULT_LAN_CIDR", "192.168.5.1/24"))
    blocks = build_wan_lan_blocks(_wan_if, bool(_wan_dhcp) if not isinstance(_wan_dhcp, bool) else _wan_dhcp,
                                  _wan_cidr, _wan_gw, _lan_if,
                                  bool(_lan_dhcp) if not isinstance(_lan_dhcp, bool) else _lan_dhcp,
                                  _lan_cidr, bypass=bool(_bypass) if not isinstance(_bypass, bool) else _bypass)
    d.update(blocks)
    _mpls_compute_track_names(d)
    _mpls_compute_bgp_vars(d)
    _mpls_compute_section_blocks(d)
    return d, None


def generate_mpls_config(d):
    parts = []

    parts.append(_build_header_comment(d))

    parts.append("""\
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
set firewall name WAN2LOCAL rule 1220 protocol 'ipip'""")

    fw_mss = [f"set firewall options interface {t} adjust-mss '1400'"
              for t in (d.get("main_gre_tun",""), d.get("bk_gre_tun","")) if t]
    if fw_mss:
        parts.append("\n".join(fw_mss))

    parts.append("""\
set firewall receive-redirects 'disable'
set firewall send-redirects 'disable'
set firewall source-validation 'disable'
set firewall syn-cookies 'enable'
set firewall twa-hazards-protection 'disable'""")

    parts.append(f"set interfaces ethernet {d['wan_if']} address '{d['wan_addr']}'")
    parts.append(f"set interfaces ethernet {d['wan_if']} description 'TO-WAN'")
    if d.get("lan_if_block"):
        parts.append(d["lan_if_block"])

    for px in ("main", "bk"):
        sec = _build_vtun_section(px, d)
        if sec:
            parts.append(sec)

    for px in ("main", "bk"):
        sec = _build_gre_section(px, d)
        if sec:
            parts.append(sec)

    hn = d.get("hostname", "")
    parts.append(f"set openfalcon endpoint-name '{hn}'")
    parts.append("set openfalcon server-address '192.168.237.86'")

    if d.get("prefix_list_block"):
        parts.append(d["prefix_list_block"])

    ce = d.get("ce_as", "")
    parts.append(f"set policy route-map AS{ce}-OUT rule 10 action 'permit'")
    parts.append(f"set policy route-map AS{ce}-OUT rule 10 match ip address prefix-list 'AS{ce}-OUT'")
    parts.append(f"set policy route-map AS{ce}-OUT rule 20 action 'deny'")
    parts.append("set policy route-map bgp-from--BACKUP rule 10 action 'permit'")
    parts.append("set policy route-map bgp-from--BACKUP rule 10 set local-preference '50'")

    parts.append(f"set protocols bgp {ce} address-family ipv4-unicast redistribute connected route-map 'AS{ce}-OUT'")
    parts.append(f"set protocols bgp {ce} address-family ipv4-unicast redistribute static route-map 'AS{ce}-OUT'")

    main_type = d.get("main_line_type", "vtun_gre")
    bk_type = d.get("bk_line_type", "vtun_gre")

    if main_type == "vtun_only":
        m_pe_ip = d.get("main_vtun_remote", "")
        m_ce_ip = d.get("main_vtun_local", "")
    else:
        m_pe_ip = d.get("main_gre_pe_ip", "")
        m_ce_ip = d.get("main_gre_ce_ip", "")
    m_pe_as = d.get("main_pe_as", "")

    if bk_type == "vtun_only":
        b_pe_ip = d.get("bk_vtun_remote", "")
        b_ce_ip = d.get("bk_vtun_local", "")
    else:
        b_pe_ip = d.get("bk_gre_pe_ip", "")
        b_ce_ip = d.get("bk_gre_ce_ip", "")
    b_pe_as = d.get("bk_pe_as", "")

    parts.append(f"set protocols bgp {ce} neighbor {m_pe_ip} address-family ipv4-unicast prefix-list export 'AS{ce}-OUT'")
    parts.append(f"set protocols bgp {ce} neighbor {m_pe_ip} address-family ipv4-unicast soft-reconfiguration inbound")
    parts.append(f"set protocols bgp {ce} neighbor {m_pe_ip} remote-as '{m_pe_as}'")
    parts.append(f"set protocols bgp {ce} neighbor {m_pe_ip} update-source '{m_ce_ip}'")

    parts.append(f"set protocols bgp {ce} neighbor {b_pe_ip} address-family ipv4-unicast prefix-list export 'AS{ce}-OUT'")
    parts.append(f"set protocols bgp {ce} neighbor {b_pe_ip} address-family ipv4-unicast route-map import 'bgp-from--BACKUP'")
    parts.append(f"set protocols bgp {ce} neighbor {b_pe_ip} address-family ipv4-unicast soft-reconfiguration inbound")
    parts.append(f"set protocols bgp {ce} neighbor {b_pe_ip} remote-as '{b_pe_as}'")
    parts.append(f"set protocols bgp {ce} neighbor {b_pe_ip} update-source '{b_ce_ip}'")

    parts.append(f"set protocols bgp {ce} timers holdtime '15'")
    parts.append(f"set protocols bgp {ce} timers keepalive '5'")

    m_tun = d.get("main_vtun_id", "") if main_type == "vtun_only" else d.get("main_gre_tun", "")
    parts.append(f"set track name {m_tun} failure-count '2'")
    parts.append(f"set track name {m_tun} success-count '2'")
    parts.append(f"set track name {m_tun} test 10 resp-time '5'")
    parts.append(f"set track name {m_tun} test 10 target '{m_pe_ip}'")
    parts.append(f"set track name {m_tun} test 10 ttl-limit '1'")
    parts.append(f"set track name {m_tun} test 10 type 'ping'")

    if d.get("wan_route_block"):
        parts.append(d["wan_route_block"])

    parts.append(f"set protocols static route 114.113.245.99/32 next-hop {m_pe_ip}")
    parts.append(f"set protocols static route 114.113.245.100/32 next-hop {b_pe_ip}")

    tunnel_routes = _build_tunnel_routes(d)
    if tunnel_routes:
        parts.append(tunnel_routes)

    parts.append(f"set protocols static route 192.168.55.250/32 next-hop {m_pe_ip} track {m_tun}")
    parts.append(f"set protocols static route 192.168.55.250/32 next-hop {b_pe_ip} distance '5'")
    parts.append(f"set protocols static route 192.168.237.86/32 next-hop {m_pe_ip} track {m_tun}")
    parts.append(f"set protocols static route 192.168.237.86/32 next-hop {b_pe_ip} distance '5'")

    if d.get("return_routes_block"):
        parts.append(d["return_routes_block"])

    parts.append(f"set system host-name '{hn}'")

    if d.get("dhcp_server_block"):
        parts.append(d["dhcp_server_block"])

    return "\n".join(parts)


# =====================================================================
# 解析器 – MPLS
# =====================================================================
def parse_epoch_mpls(text):
    result = {k: "" for k in [
        "main_gre_pe", "main_gre_tun", "main_gre_wanip",
        "main_gre_pe_ip", "main_gre_ce_ip", "main_gre_remote",
        "main_vtun_pe", "main_vtun_id", "main_vtun_port",
        "main_vtun_local", "main_vtun_remote", "main_vtun_docking",
        "bk_gre_pe", "bk_gre_tun", "bk_gre_wanip",
        "bk_gre_pe_ip", "bk_gre_ce_ip", "bk_gre_remote",
        "bk_vtun_pe", "bk_vtun_id", "bk_vtun_port",
        "bk_vtun_local", "bk_vtun_remote", "bk_vtun_docking",
        "main_pe_as", "bk_pe_as", "ce_as",
        "main_line_type", "bk_line_type",
        "main_vtun_wanip", "bk_vtun_wanip",
        "hostname",
    ]}

    blocks = re.split(r'(?=LineID\s*[:：])', text, flags=re.IGNORECASE)
    for block in blocks:
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

        for sub in sub_blocks:
            pe_name    = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub)
            tun_raw    = _get(r'^\s*(?:Tunnel|TUNNEL)\s*[:：]\s*(\S+)', sub)
            wanip      = _get(r'^\s*wanip\s*[:：]\s*([\d./]+)', sub)
            pe_docking = _get(r'PE\s*对接\s*[:：]\s*([\d.]+)', sub)
            ce_docking = _get(r'CE\s*对接\s*[:：]+\s*([\d.]+)', sub)
            pe_as_val  = _get(r'PE\s*AS号?\s*[:：]\s*(\d+)', sub)
            ce_as_val  = _get(r'CE\s*AS号?\s*[:：]\s*(\d+)', sub)

            tun_lower = tun_raw.lower() if tun_raw else ""
            pe_lower  = pe_name.lower() if pe_name else ""
            is_vtun   = tun_lower.startswith("vtun") or re.search(r'acvpn|ipsecvpn|ipsecgw', pe_lower)

            if is_vtun:
                vtun_id = normalize_vtun(tun_raw)
                result[f"{px}_vtun_pe"]   = pe_name
                result[f"{px}_vtun_id"]   = vtun_id
                result[f"{px}_vtun_port"] = vtun_port(vtun_id)
                result[f"{px}_vtun_wanip"] = wanip
                if wanip:
                    pe_ip, ce_ip = wanip_hosts(wanip)
                    result[f"{px}_vtun_remote"] = pe_ip
                    if ce_ip and not result[f"{px}_vtun_local"]:
                        result[f"{px}_vtun_local"] = ce_ip
                result[f"{px}_vtun_docking"] = pe_docking
                if pe_as_val:
                    result[f"{px}_pe_as"] = pe_as_val
                if ce_as_val:
                    result["ce_as"] = ce_as_val
            else:
                result[f"{px}_gre_pe"]  = pe_name
                result[f"{px}_gre_tun"] = normalize_tun(tun_raw)
                result[f"{px}_gre_wanip"] = wanip
                if wanip:
                    pe_ip, ce_ip = wanip_hosts(wanip)
                    result[f"{px}_gre_pe_ip"] = pe_ip
                    result[f"{px}_gre_ce_ip"] = ce_ip
                result[f"{px}_gre_remote"] = pe_docking
                if ce_docking:
                    result[f"{px}_vtun_local"] = ce_docking
                if pe_as_val:
                    result[f"{px}_pe_as"] = pe_as_val
                if ce_as_val:
                    result["ce_as"] = ce_as_val

        has_gre = bool(result.get(f"{px}_gre_tun"))
        has_vtun = bool(result.get(f"{px}_vtun_id"))
        if has_gre and has_vtun:
            result[f"{px}_line_type"] = "vtun_gre"
        elif has_vtun:
            result[f"{px}_line_type"] = "vtun_only"
        elif has_gre:
            result[f"{px}_line_type"] = "gre_only"

    return result


def extract_lineid_mpls(text):
    ids = re.findall(r'LineID\s*[:：]\s*(\S+)', text, re.IGNORECASE)
    if ids:
        base = re.sub(r'\d+$', '', ids[0].strip())
        return base if base else ids[0].strip()
    return ""


def _cidr_plain(cidr: str) -> str:
    s = str(cidr).strip()
    return s.split("/", 1)[0].strip() if "/" in s else s


def _cidr_host_pair(cidr: str) -> tuple[str, str, str]:
    try:
        iface = ipaddress.ip_interface(str(cidr).strip())
        hosts = list(iface.network.hosts())
        if len(hosts) >= 2:
            return str(hosts[0]), str(hosts[1]), str(iface.network.prefixlen)
    except Exception:
        pass
    return "", "", ""


def _build_mpls_prefix_list_block(d: dict) -> str:
    ce_as = str(d.get("ce_as", "")).strip()
    inner_nets = d.get("inner_nets") or []
    lines = []
    for i, n in enumerate(inner_nets):
        rule_num = 10 * (i + 1)
        lines.append(f"set policy prefix-list AS{ce_as}-OUT rule {rule_num} action 'permit'")
        lines.append(f"set policy prefix-list AS{ce_as}-OUT rule {rule_num} prefix '{n}'")
    return "\n".join(lines)


def _build_mpls_return_routes_block(d: dict) -> str:
    inner_nets_for_rr = d.get("inner_nets") or []
    lan_cidr_rr = d.get("lan_cidr") or ""
    lan_gw_rr = d.get("lan_gw") or ""
    rr_on = d.get("return_route_enabled", False)
    outside_rr = _nets_needing_return_by_network(lan_cidr_rr, inner_nets_for_rr) if lan_cidr_rr else []
    rr_lines = []
    if outside_rr and rr_on and lan_gw_rr:
        rr_lines = [f"set protocols static route {n} next-hop {lan_gw_rr}" for n in outside_rr]
    return "\n".join(rr_lines)


def _normalize_lan_gw_value(lan_cidr: str, lan_gw: str) -> str:
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


def parse_epoch_mpls_ipsec(text):
    result = dict(parse_epoch_mpls(text) or {})
    for key in (
        "main_dial_pe", "main_ipsec_peer_ip", "main_loop_ip", "main_public_ip", "main_ipsec_psk",
        "bk_dial_pe", "bk_ipsec_peer_ip", "bk_loop_ip", "bk_public_ip", "bk_ipsec_psk",
    ):
        result.setdefault(key, "")

    blocks = re.split(r'(?=LineID\s*[:：])', text, flags=re.IGNORECASE)
    for block in blocks:
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
        px = "main" if is_main else "bk"

        dial_pe = _get(r'^\s*拨号PE\s*[:：]\s*(.+?)$', block)
        peer_ip = _get(r'^\s*对接IP\s*[:：]\s*([\d.]+)', block)
        loop_ip = _get(r'^\s*LoopIP\s*[:：]\s*([\d.]+)', block)
        public_ip = _get(r'^\s*拨号IP\s*[:：]\s*([\d.]+)', block)
        psk = _get(r'^\s*(?:密钥|秘钥)\s*[:：]\s*(\S+)', block)

        if not peer_ip:
            peer_ip = _get(r'^\s*PE\s*对接\s*[:：]\s*([\d.]+)', block)
        if not loop_ip:
            loop_ip = _get(r'^\s*CE\s*对接\s*[:：]\s*([\d.]+)', block)

        if dial_pe:
            result[f"{px}_dial_pe"] = dial_pe
        if peer_ip:
            result[f"{px}_ipsec_peer_ip"] = peer_ip
        if loop_ip:
            result[f"{px}_loop_ip"] = loop_ip
        if public_ip:
            result[f"{px}_public_ip"] = public_ip
        if psk:
            result[f"{px}_ipsec_psk"] = psk
    return result


def build_mpls_ipsec_format_dict(raw: str, hostname: str = "", net: dict | None = None) -> dict:
    d = parse_epoch_mpls_ipsec(raw)
    d["hostname"] = hostname or extract_lineid_mpls(raw) or "（请填写Hostname）"
    if net:
        d.update(net)
    d["lan_gw"] = _normalize_lan_gw_value(str(d.get("lan_cidr", "")), str(d.get("lan_gw", "")))
    inject_er_netpanel_init_aliases(d)
    d["return_routes_block"] = _build_mpls_return_routes_block(d)
    d["prefix_list_block"] = _build_mpls_prefix_list_block(d)
    d["wan_addr_plain"] = _cidr_plain(str(d.get("wan_addr", "")))
    for px in ("main", "bk"):
        tun_peer, tun_local, tun_prefix = _cidr_host_pair(str(d.get(f"{px}_gre_wanip", "")))
        d[f"{px}_tun_peer"] = tun_peer
        d[f"{px}_tun_local"] = tun_local
        d[f"{px}_tun_addr"] = f"{tun_local}/{tun_prefix}" if tun_local and tun_prefix else ""
        loop_ip = str(d.get(f"{px}_loop_ip", "")).strip()
        d[f"{px}_loop_ip_cidr"] = f"{loop_ip}/32" if loop_ip else ""
        d[f"{px}_track_name"] = str(d.get(f"{px}_gre_tun", "")).strip()
    return d


# =====================================================================
# WAN/LAN 配置块生成器
# =====================================================================
def build_wan_lan_blocks(wan_if, wan_dhcp, wan_ip_cidr, wan_gw,
                         lan_if, lan_dhcp, lan_ip_cidr, bypass=False):
    if wan_dhcp:
        wan_addr = "dhcp"
        wan_route_block = f"set protocols static route 1.1.1.1/32 dhcp-interface {wan_if}"
    else:
        wan_addr = wan_ip_cidr if wan_ip_cidr else DEFAULT_WAN_CIDR
        gw = wan_gw if wan_gw else DEFAULT_WAN_GW
        wan_route_block = (f"set protocols static route 0.0.0.0/0 next-hop {gw} distance '222'\n"
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
ACCENT_CN = "#e07b2a"
ACCENT_OV = "#0077b6"
FG        = "#1a2b3c"
FG_DIM    = "#7a96ad"
FG_BRT    = "#ffffff"
BORDER    = "#c8d8e8"
FONT_MONO = ("Consolas", 10)
FONT_UI   = ("微软雅黑", 10)
FONT_HDR  = ("微软雅黑", 11, "bold")
FONT_TINY = ("Consolas",  9)

root = tk.Tk()
root.title("Epoch MPLS 配置生成工具")
_sw = root.winfo_screenwidth()
_sh = root.winfo_screenheight()
_ww = min(1300, int(_sw * 0.88))
_wh = min(860,  int(_sh * 0.85))
root.geometry(f"{_ww}x{_wh}+{(_sw-_ww)//2}+{max(0,(_sh-_wh)//2-20)}")
root.minsize(900, 620)
root.configure(bg=BG)

sty = ttk.Style(root)
sty.theme_use("clam")
sty.configure("TPanedwindow", background=BG)
sty.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG,
               arrowcolor=FG_DIM, relief="flat", borderwidth=0, width=8)
sty.map("Vertical.TScrollbar", background=[("active", ACCENT_OV)])
sty.configure("TNotebook", tabposition="nw", background=BG_HDR)
sty.configure("TNotebook.Tab", background=BG_HDR, foreground="#7aafd4",
               font=("微软雅黑", 11, "bold"), padding=[20, 8])
sty.map("TNotebook.Tab",
        background=[("selected", BG), ("active", "#2a4a6f")],
        foreground=[("selected", ACCENT_OV), ("active", FG_BRT)])

def make_text(parent, readonly=False, **kw):
    vsb = ttk.Scrollbar(parent, orient="vertical", style="Vertical.TScrollbar")
    vsb.pack(side="right", fill="y")
    t = tk.Text(parent, font=FONT_MONO, bg=BG_INPUT, fg=FG,
                insertbackground=ACCENT_OV, selectbackground=ACCENT_OV,
                selectforeground=BG, relief="flat", bd=0, padx=10, pady=6,
                yscrollcommand=vsb.set,
                state=(tk.DISABLED if readonly else tk.NORMAL), **kw)
    t.pack(side="left", fill="both", expand=True)
    vsb.configure(command=t.yview)
    menu = tk.Menu(t, tearoff=0, bg=BG_PANEL, fg=FG,
                   activebackground=ACCENT_OV, activeforeground=FG_BRT,
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

# ── 根布局 ──────────────────────────────────────────────────────────
root.columnconfigure(0, weight=1)
root.rowconfigure(1, weight=1)

hdr = tk.Frame(root, bg=BG_HDR, height=46)
hdr.grid(row=0, column=0, sticky="ew"); hdr.grid_propagate(False)
tk.Frame(hdr, bg="#16a085", width=4).pack(side="left", fill="y")
tk.Label(hdr, text="  Epoch MPLS", font=("微软雅黑", 13, "bold"),
         bg=BG_HDR, fg=FG_BRT).pack(side="left")
tk.Label(hdr, text=" 配置生成工具", font=FONT_HDR, bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=4)
right_badges = tk.Frame(hdr, bg=BG_HDR)
right_badges.pack(side="right", padx=14, pady=10)
badge_font = ("微软雅黑", 9, "bold")
tk.Label(right_badges, text=" v1 正式试用 ", font=badge_font, bg="#16a085", fg=FG_BRT,
         padx=12, pady=4).pack(side="right")
tk.Label(right_badges, text=" 深圳工程部系列宝典 ", font=badge_font, bg="#6c757d", fg=FG_BRT,
         padx=10, pady=4).pack(side="right", padx=(0, 8))

main_nb = ttk.Notebook(root)
main_nb.grid(row=1, column=0, sticky="nsew")
tab_cn = tk.Frame(main_nb, bg=BG)
tab_ov = tk.Frame(main_nb, bg=BG)
tab_ipsec = tk.Frame(main_nb, bg=BG)
main_nb.add(tab_cn, text="  🏠 国内 出口  ")
main_nb.add(tab_ov, text="  🌏 海外 出口  ")
main_nb.add(tab_ipsec, text="  🔐 IPSec  ")

# =====================================================================
# 初始化配置面板
# =====================================================================
def build_net_panel(parent, accent, wan_dhcp_default=False, lan_dhcp_default=True):
    hdr_f = tk.Frame(parent, bg=accent, height=26)
    hdr_f.pack(fill="x"); hdr_f.pack_propagate(False)
    tk.Frame(hdr_f, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(hdr_f, text="  初始化配置", font=("微软雅黑",10,"bold"), bg=accent, fg=FG_BRT).pack(side="left", pady=2)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

    body = tk.Frame(parent, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=2, pady=2)
    body.columnconfigure(1, weight=1)
    body.columnconfigure(2, minsize=92)
    body.columnconfigure(3, weight=1)
    LBL = dict(font=("微软雅黑",9), bg=BG_PANEL, fg=FG, anchor="e")
    PAD = dict(padx=(2,4), pady=2)

    def small_entry(row, col, ph, w=14, sticky_override=None):
        e = tk.Entry(body, font=("Consolas",9), bg=BG_INPUT, fg=FG_DIM,
                     insertbackground=accent, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=accent, width=w)
        e.grid(row=row, column=col, sticky=sticky_override or "ew", padx=(0,4), pady=2)
        e.insert(0, ph)
        def _fi(ev, en=e, p=ph):
            if en.get()==p: en.delete(0,tk.END); en.config(fg=FG)
        def _fo(ev, en=e, p=ph):
            if not en.get().strip(): en.insert(0,p); en.config(fg=FG_DIM)
        e.bind("<FocusIn>", _fi); e.bind("<FocusOut>", _fo)
        return e

    def toggle_btn(row, col):
        b = tk.Label(body, font=("微软雅黑",8,"bold"),
                     padx=8, pady=3, cursor="hand2", relief="flat")
        b.grid(row=row, column=col, sticky="w", padx=(0,4), pady=2)
        return b

    r = 0
    tk.Label(body, text="Hostname", **LBL, width=8).grid(row=r, column=0, sticky="e", **PAD)
    e_host = small_entry(r, 1, "留空则用LineID", 18)
    e_host.grid(columnspan=3); r += 1

    tk.Frame(body, bg=BORDER, height=1).grid(row=r, column=0, columnspan=4, sticky="ew", pady=(3,1)); r += 1
    tk.Label(body, text="WAN口", **LBL, width=8).grid(row=r, column=0, sticky="e", **PAD)
    wan_eth_var = tk.StringVar(value=str(DEFAULT_WAN_ETH).strip() or "0")
    wan_row = tk.Frame(body, bg=BG_PANEL); wan_row.grid(row=r, column=1, sticky="w", pady=2)
    tk.Label(wan_row, text="eth", font=("Consolas",9), bg=BG_PANEL, fg=FG_DIM).pack(side="left")
    e_wan_eth = tk.Entry(wan_row, textvariable=wan_eth_var, font=("Consolas",9),
                         bg=BG_INPUT, fg=FG, width=3, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=accent)
    e_wan_eth.pack(side="left", padx=(0,6))
    _MPLS_INIT_ETH_WAN_VARS.append(wan_eth_var)
    tk.Label(body, text="DHCP", **LBL, width=5).grid(row=r, column=2, sticky="e", **PAD)
    wan_dhcp_var = tk.BooleanVar(
        value=bool(globals().get("DEFAULT_WAN_DHCP", wan_dhcp_default)))
    wan_dhcp_btn = toggle_btn(r, 3); r += 1

    tk.Label(body, text="WAN IP", **LBL, width=8).grid(row=r, column=0, sticky="e", **PAD)
    e_wan_ip = small_entry(r, 1, DEFAULT_WAN_CIDR, 24, sticky_override="w")
    tk.Label(body, text="WAN网关", **LBL).grid(row=r, column=2, sticky="e", **PAD)
    e_wan_gw = small_entry(r, 3, DEFAULT_WAN_GW, 20, sticky_override="w"); r += 1

    tk.Frame(body, bg=BORDER, height=1).grid(row=r, column=0, columnspan=4, sticky="ew", pady=(3,1)); r += 1
    lbl_lan_port = tk.Label(body, text="LAN口", **LBL, width=8)
    lbl_lan_port.grid(row=r, column=0, sticky="e", **PAD)
    lan_eth_var = tk.StringVar(value=str(DEFAULT_LAN_ETH).strip() or "5")
    lan_row = tk.Frame(body, bg=BG_PANEL); lan_row.grid(row=r, column=1, sticky="w", pady=2)
    tk.Label(lan_row, text="eth", font=("Consolas",9), bg=BG_PANEL, fg=FG_DIM).pack(side="left")
    e_lan_eth = tk.Entry(lan_row, textvariable=lan_eth_var, font=("Consolas",9),
                         bg=BG_INPUT, fg=FG, width=3, relief="flat", bd=0,
                         highlightthickness=1, highlightbackground=BORDER, highlightcolor=accent)
    e_lan_eth.pack(side="left", padx=(0,6))
    _MPLS_INIT_ETH_LAN_VARS.append(lan_eth_var)
    lbl_lan_dhcp = tk.Label(body, text="DHCP", **LBL, width=5)
    lbl_lan_dhcp.grid(row=r, column=2, sticky="e", **PAD)
    lan_dhcp_var = tk.BooleanVar(
        value=bool(globals().get("DEFAULT_LAN_DHCP", lan_dhcp_default)))
    lan_dhcp_btn = toggle_btn(r, 3)
    tk.Label(body, text="旁挂", **LBL, width=4).grid(row=r, column=4, sticky="e", padx=(8,2), pady=2)
    bypass_var = tk.BooleanVar(value=False)
    bypass_btn = toggle_btn(r, 5); r += 1

    lbl_lan_ip = tk.Label(body, text="LAN IP", **LBL, width=8)
    lbl_lan_ip.grid(row=r, column=0, sticky="e", **PAD)
    e_lan_ip = small_entry(r, 1, DEFAULT_LAN_CIDR, 24, sticky_override="w")
    lbl_lan_gw = tk.Label(body, text="LAN网关", **LBL)
    lbl_lan_gw.grid(row=r, column=2, sticky="e", **PAD)
    e_lan_gw = small_entry(r, 3, DEFAULT_LAN_GW, 20, sticky_override="w"); r += 1

    tk.Frame(body, bg=BORDER, height=1).grid(row=r, column=0, columnspan=4, sticky="ew", pady=(3,1)); r += 1
    tk.Label(body, text="内网段", font=("微软雅黑",9), bg=BG_PANEL, fg=FG_DIM, anchor="ne", width=8).grid(row=r, column=0, sticky="ne", **PAD)
    inner_wrap = tk.Frame(body, bg=BG_INPUT, highlightthickness=1,
                          highlightbackground=BORDER, highlightcolor=accent)
    inner_wrap.grid(row=r, column=1, columnspan=3, sticky="ew", padx=(0,4), pady=1)
    e_inner = tk.Text(inner_wrap, font=("Consolas",9), bg=BG_INPUT, fg=FG,
                      height=2, relief="flat", bd=0, padx=4, pady=2, insertbackground=accent)
    e_inner.pack(fill="both", expand=True)
    e_inner.insert("1.0", DEFAULT_INNER_NETS)
    tk.Label(body, text="换行或逗号分隔多条（同时作为prefix-list宣告）", font=("Consolas",7),
             bg=BG_PANEL, fg=FG_DIM, anchor="w").grid(row=r+1, column=1, columnspan=3, sticky="w", padx=(0,4))
    r += 2

    # 内网段状态 + 回程路由（同一行：提示左、开关右，省一行高度）
    rr_strip = tk.Frame(body, bg=BG_PANEL)
    rr_strip.grid(row=r, column=0, columnspan=4, sticky="ew", pady=(0, 0))
    rr_strip.columnconfigure(0, weight=1)
    r += 1

    status_inner_var = tk.StringVar(value="")
    lbl_inner = tk.Label(
        rr_strip, textvariable=status_inner_var, font=("微软雅黑", 8), bg=BG_PANEL,
        anchor="w", wraplength=260, justify="left",
    )
    lbl_inner.grid(row=0, column=0, sticky="w", padx=(4, 4))

    rr_tail = tk.Frame(rr_strip, bg=BG_PANEL)
    rr_tail.grid(row=0, column=1, sticky="e", padx=(4, 4))
    tk.Label(rr_tail, text="回程路由", **LBL, width=8).pack(side="left", padx=(0, 4))
    return_route_var = tk.BooleanVar(value=False)
    rr_btn = tk.Label(rr_tail, font=("微软雅黑", 8, "bold"), padx=8, pady=3, cursor="hand2", relief="flat")
    rr_btn.pack(side="left")
    rr_tail.grid_remove()

    def _real_wan_cidr():
        v = e_wan_ip.get().strip()
        return "" if v in ("", "dhcp") else v
    def _real_wan_gw():
        v = e_wan_gw.get().strip()
        return "" if v in ("", "dhcp") else v
    def _lan_ph():
        return str(globals().get("DEFAULT_LAN_CIDR", DEFAULT_LAN_CIDR) or DEFAULT_LAN_CIDR)
    def _lan_gw_ph():
        raw = str(globals().get("DEFAULT_LAN_GW", DEFAULT_LAN_GW) or "").strip()
        if raw:
            norm = _normalize_lan_gw_value(_lan_ph(), raw)
            if norm:
                return norm
        return _normalize_lan_gw_value(_lan_ph(), _lan_ph())
    def _real_lan_cidr():
        v = e_lan_ip.get().strip()
        return "" if v in (_lan_ph(), "") else v
    def _real_lan_gw():
        v = e_lan_gw.get().strip()
        if not v:
            raw = _real_lan_cidr() or _lan_ph()
            try: return str(ipaddress.ip_interface(raw).ip)
            except Exception: return ""
        return _normalize_lan_gw_value(_real_lan_cidr() or _lan_ph(), v) or v

    def _update_bypass_ui():
        on = bypass_var.get()
        bypass_btn.config(text="● 旁挂" if on else "○ 非旁挂",
                         bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)
        fg = FG_DIM if on else FG
        if on:
            for w in (e_lan_eth, e_lan_ip, e_lan_gw):
                w.config(state=tk.NORMAL); w.delete(0, tk.END); w.config(state=tk.DISABLED)
        else:
            e_lan_eth.config(state=tk.NORMAL)
            if not e_lan_eth.get().strip(): e_lan_eth.insert(0, "5")
            e_lan_ip.config(state=tk.NORMAL)
            if not e_lan_ip.get().strip(): e_lan_ip.insert(0, _lan_ph()); e_lan_ip.config(fg=FG_DIM)
            e_lan_gw.config(state=tk.NORMAL)
            if not e_lan_gw.get().strip(): e_lan_gw.insert(0, _lan_gw_ph()); e_lan_gw.config(fg=FG_DIM)
        for lbl in (lbl_lan_port, lbl_lan_dhcp, lbl_lan_ip, lbl_lan_gw):
            lbl.config(fg=fg)
        if on: lan_dhcp_btn.config(fg=FG_DIM)
        else:  _update_lan_dhcp()

    def _update_rr_btn():
        on = return_route_var.get()
        rr_btn.config(text="● 生成回程路由" if on else "○ 不生成",
                      bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)

    def _check_inner(*_):
        inner_raw = e_inner.get("1.0", tk.END)
        nets = _parse_inner_nets(inner_raw)
        if not nets:
            status_inner_var.set("⚠  未填写有效内网段")
            lbl_inner.config(fg="#c0392b"); rr_tail.grid_remove(); return
        if bypass_var.get():
            wan_raw = _real_wan_cidr() or DEFAULT_WAN_CIDR
            outside = _nets_needing_return_by_network(wan_raw, nets)
        else:
            lan_raw = _real_lan_cidr() or DEFAULT_LAN_CIDR
            outside = _nets_needing_return_by_network(lan_raw, nets)
        if not outside:
            label = "WAN IP" if bypass_var.get() else "LAN IP"
            status_inner_var.set(f"✓  {label} 在所有内网段内")
            lbl_inner.config(fg="#16a085"); rr_tail.grid_remove()
        else:
            preview = " ".join(outside[:2]) + ("…" if len(outside) > 2 else "")
            status_inner_var.set(f"⚠  需回程路由 {len(outside)} 条：{preview}")
            lbl_inner.config(fg="#e07b2a"); rr_tail.grid(); _update_rr_btn()

    rr_btn.bind("<Button-1>", lambda e: (return_route_var.set(not return_route_var.get()), _update_rr_btn()))
    bypass_btn.bind("<Button-1>", lambda e: (bypass_var.set(not bypass_var.get()), _update_bypass_ui(), _check_inner()))
    for w in (e_lan_ip, e_wan_ip):
        w.bind("<FocusOut>", _check_inner); w.bind("<KeyRelease>", _check_inner)
    e_inner.bind("<KeyRelease>", _check_inner); e_inner.bind("<FocusOut>", _check_inner)
    root.after(120, _check_inner)

    wan_saved = {"ip": "", "gw": ""}
    def _set_entry_value(entry, value, dim=False):
        entry.config(state=tk.NORMAL); entry.delete(0, tk.END); entry.insert(0, value)
        entry.config(fg=FG_DIM if dim else FG)

    def _update_wan_dhcp():
        on = wan_dhcp_var.get()
        wan_dhcp_btn.config(text="● 开" if on else "○ 关",
                            bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)
        if on:
            cur_ip = e_wan_ip.get().strip()
            if cur_ip and cur_ip not in (DEFAULT_WAN_CIDR, "dhcp"): wan_saved["ip"] = cur_ip
            cur_gw = e_wan_gw.get().strip()
            if cur_gw and cur_gw not in (DEFAULT_WAN_GW, "dhcp"): wan_saved["gw"] = cur_gw
            _set_entry_value(e_wan_ip, "dhcp", dim=True); _set_entry_value(e_wan_gw, "dhcp", dim=True)
            e_wan_ip.config(state=tk.DISABLED); e_wan_gw.config(state=tk.DISABLED)
        else:
            _set_entry_value(e_wan_ip, wan_saved["ip"] or DEFAULT_WAN_CIDR, dim=not bool(wan_saved["ip"]))
            _set_entry_value(e_wan_gw, wan_saved["gw"] or DEFAULT_WAN_GW, dim=not bool(wan_saved["gw"]))
            e_wan_ip.config(state=tk.NORMAL); e_wan_gw.config(state=tk.NORMAL)

    def _update_lan_dhcp():
        on = lan_dhcp_var.get()
        lan_dhcp_btn.config(text="● 开" if on else "○ 关",
                            bg=accent if on else BORDER, fg=FG_BRT if on else FG_DIM)

    _update_wan_dhcp(); _update_lan_dhcp(); _update_rr_btn(); _update_bypass_ui()
    wan_dhcp_btn.bind("<Button-1>", lambda e: (wan_dhcp_var.set(not wan_dhcp_var.get()), _update_wan_dhcp()))
    lan_dhcp_btn.bind("<Button-1>", lambda e: (lan_dhcp_var.set(not lan_dhcp_var.get()), _update_lan_dhcp()))

    def _pv(entry, placeholder):
        v = entry.get().strip(); return "" if v == placeholder else v
    def get_hostname():
        v = e_host.get().strip(); return "" if v in ("留空则用LineID","") else v
    def get_raw_for_validate():
        if wan_dhcp_var.get(): return (DEFAULT_WAN_CIDR, DEFAULT_WAN_GW, e_lan_ip.get().strip(), e_lan_gw.get().strip(), e_inner.get("1.0",tk.END))
        return (e_wan_ip.get().strip(), e_wan_gw.get().strip(), e_lan_ip.get().strip(), e_lan_gw.get().strip(), e_inner.get("1.0",tk.END))

    def get_net_cfg():
        wan_eth = wan_eth_var.get().strip() or "0"
        lan_eth = lan_eth_var.get().strip() or "5"
        bypass = bypass_var.get()
        cfg = build_wan_lan_blocks(
            f"eth{wan_eth}", wan_dhcp_var.get(),
            _pv(e_wan_ip, DEFAULT_WAN_CIDR), _pv(e_wan_gw, DEFAULT_WAN_GW),
            f"eth{lan_eth}", lan_dhcp_var.get(),
            _pv(e_lan_ip, DEFAULT_LAN_CIDR), bypass=bypass)
        inner_raw = e_inner.get("1.0", tk.END)
        nets = _parse_inner_nets(inner_raw)
        rr_lines = []
        if bypass:
            wan_raw = _real_wan_cidr() or DEFAULT_WAN_CIDR
            gw = _real_wan_gw() or DEFAULT_WAN_GW
            outside = _nets_needing_return_by_network(wan_raw, nets)
            if outside and return_route_var.get():
                if wan_dhcp_var.get():
                    wan_if = f"eth{wan_eth}"
                    rr_lines = [f"set protocols static route {n} dhcp-interface {wan_if}" for n in outside]
                elif gw:
                    rr_lines = [f"set protocols static route {n} next-hop {gw}" for n in outside]
            cfg["lan_cidr"] = wan_raw; cfg["lan_gw"] = gw
            cfg["wan_cidr"] = wan_raw; cfg["wan_gw"] = gw
        else:
            lan_raw = _real_lan_cidr() or DEFAULT_LAN_CIDR
            outside = _nets_needing_return_by_network(lan_raw, nets)
            if outside and return_route_var.get():
                gw = _real_lan_gw()
                if gw: rr_lines = [f"set protocols static route {n} next-hop {gw}" for n in outside]
            cfg["lan_cidr"] = lan_raw; cfg["lan_gw"] = _real_lan_gw()
            cfg["wan_cidr"] = _real_wan_cidr() or DEFAULT_WAN_CIDR; cfg["wan_gw"] = _real_wan_gw()
        cfg["return_routes_block"] = "\n".join(rr_lines)
        cfg["inner_nets"] = nets
        cfg["return_route_enabled"] = return_route_var.get()
        cfg["bypass_mode"] = bypass
        cfg["wan_eth_num"] = wan_eth
        cfg["lan_eth_num"] = lan_eth
        return cfg

    def reset_net():
        e_host.delete(0,tk.END); e_host.insert(0,"留空则用LineID"); e_host.config(fg=FG_DIM)
        wan_eth_var.set(str(DEFAULT_WAN_ETH).strip() or "0")
        lan_eth_var.set(str(DEFAULT_LAN_ETH).strip() or "5")
        wan_dhcp_var.set(bool(globals().get("DEFAULT_WAN_DHCP", wan_dhcp_default)))
        _update_wan_dhcp()
        lan_dhcp_var.set(bool(globals().get("DEFAULT_LAN_DHCP", lan_dhcp_default)))
        _update_lan_dhcp()
        bypass_var.set(False); _update_bypass_ui()
        for e,ph in [(e_wan_ip,DEFAULT_WAN_CIDR),(e_wan_gw,DEFAULT_WAN_GW),(e_lan_ip,_lan_ph())]:
            e.delete(0,tk.END); e.insert(0,ph); e.config(fg=FG_DIM)
        _lgw = _lan_gw_ph()
        e_lan_gw.delete(0,tk.END); e_lan_gw.insert(0, _lgw); e_lan_gw.config(fg=FG_DIM)
        e_inner.delete("1.0",tk.END); e_inner.insert("1.0",DEFAULT_INNER_NETS)
        return_route_var.set(bool(globals().get("DEFAULT_GEN_RETURN_ROUTE", False)))
        _update_rr_btn()
        rr_tail.grid_remove()
        root.after(50, _check_inner)

    return get_hostname, get_net_cfg, reset_net, get_raw_for_validate


# =====================================================================
# Tab 框架构建器（四象限可拖动布局）
# =====================================================================
# =====================================================================
# IPSec 单场景：统一数据头示例与模板
# =====================================================================
MPLS_IPSEC_NOTE = (
    "er_mpls_v1 IPSec 正式页\n\n"
    "• IPSec 不再区分国内/海外，使用统一数据头与统一模板\n"
    "• 初始化面板、WAN/LAN/旁挂/回程路由 与 OpenVPN MPLS 保持一致\n"
    "• 业务数据需包含 LineID / PE / Tunnel / wanip / PE对接 / CE对接 / AS号\n"
    "• 同时需补充 拨号PE / 对接IP / LoopIP / 拨号IP / 密钥(或秘钥)\n"
    "• 配置仅供参考，使用仍需谨慎。"
)

MPLS_IPSEC_EXAMPLE = """\
LineID:602520P1
PE:hza-upe1
Tunnel:Tunnel0/0/1518
wanip:10.120.9.72/30
CE 对接:10.200.200.5
PE 对接:10.120.29.194
PE AS号:65120
CE AS号:65216

拨号PE：hza-upe1
对接IP:10.200.200.5
LoopIP:10.120.29.194
拨号IP:115.227.6.113
密钥：both-win

LineID:602520P2
PE:wha-upebk3
Tunnel:Tunnel0/0/1334
wanip:10.120.54.128/30
PE 对接:10.200.200.79
CE 对接:10.50.138.36
PE AS号:65185
CE AS号:65216

拨号PE:wha-upebk3
对接IP:10.200.200.79
LoopIP:10.50.138.36
拨号ip:116.211.87.92
秘钥:both-win
"""

TEMPLATE_MPLS_IPSEC = """\
# ==========================================================
# Epoch MPLS IPSec 配置  Hostname: {hostname}
# 主线 Tunnel:{main_gre_tun}  PE:{main_gre_pe}  Public:{main_public_ip}
# 备线 Tunnel:{bk_gre_tun}  PE:{bk_gre_pe}  Public:{bk_public_ip}
# ==========================================================
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
set firewall options interface {bk_gre_tun} adjust-mss '1400'
set firewall options interface {main_gre_tun} adjust-mss '1400'
set firewall receive-redirects 'disable'
set firewall send-redirects 'disable'
set firewall source-validation 'disable'
set firewall syn-cookies 'enable'
set firewall twa-hazards-protection 'disable'
set interfaces dummy dum0 address '{main_loop_ip_cidr}'
set interfaces dummy dum0 description 'MAIN-loip'
set interfaces dummy dum1 address '{bk_loop_ip_cidr}'
set interfaces dummy dum1 description 'BK-loip'
set interfaces ethernet {wan_if} address '{wan_addr_plain}'
{lan_if_block}
set interfaces tunnel {bk_gre_tun} address '{bk_tun_addr}'
set interfaces tunnel {bk_gre_tun} description 'BK_{bk_gre_pe}'
set interfaces tunnel {bk_gre_tun} encapsulation 'gre'
set interfaces tunnel {bk_gre_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {bk_gre_tun} mtu '1476'
set interfaces tunnel {bk_gre_tun} multicast 'disable'
set interfaces tunnel {bk_gre_tun} parameters ip ttl '255'
set interfaces tunnel {bk_gre_tun} remote '{bk_ipsec_peer_ip}'
set interfaces tunnel {bk_gre_tun} source-address '{bk_loop_ip}'
set interfaces tunnel {main_gre_tun} address '{main_tun_addr}'
set interfaces tunnel {main_gre_tun} description 'MAIN_{main_gre_pe}'
set interfaces tunnel {main_gre_tun} encapsulation 'gre'
set interfaces tunnel {main_gre_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {main_gre_tun} mtu '1476'
set interfaces tunnel {main_gre_tun} multicast 'disable'
set interfaces tunnel {main_gre_tun} parameters ip ttl '255'
set interfaces tunnel {main_gre_tun} remote '{main_ipsec_peer_ip}'
set interfaces tunnel {main_gre_tun} source-address '{main_loop_ip}'
set openfalcon endpoint-name '{hostname}'
set openfalcon server-address '192.168.237.86'
{prefix_list_block}
set policy route-map AS{ce_as}-OUT rule 10 action 'permit'
set policy route-map AS{ce_as}-OUT rule 10 match ip address prefix-list 'AS{ce_as}-OUT'
set policy route-map AS{ce_as}-OUT rule 20 action 'deny'
set policy route-map bgp-from--BACKUP rule 10 action 'permit'
set policy route-map bgp-from--BACKUP rule 10 set local-preference '50'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute connected route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} address-family ipv4-unicast redistribute static route-map 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_tun_peer} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {main_tun_peer} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {main_tun_peer} remote-as '{main_pe_as}'
set protocols bgp {ce_as} neighbor {main_tun_peer} update-source '{main_tun_local}'
set protocols bgp {ce_as} neighbor {bk_tun_peer} address-family ipv4-unicast prefix-list export 'AS{ce_as}-OUT'
set protocols bgp {ce_as} neighbor {bk_tun_peer} address-family ipv4-unicast route-map import 'bgp-from--BACKUP'
set protocols bgp {ce_as} neighbor {bk_tun_peer} address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp {ce_as} neighbor {bk_tun_peer} remote-as '{bk_pe_as}'
set protocols bgp {ce_as} neighbor {bk_tun_peer} update-source '{bk_tun_local}'
set protocols bgp {ce_as} timers holdtime '15'
set protocols bgp {ce_as} timers keepalive '5'
{wan_route_block}
set protocols static route {main_ipsec_peer_ip}/32 next-hop 1.1.1.1
set protocols static route {bk_ipsec_peer_ip}/32 next-hop 1.1.1.1
set protocols static route 114.113.245.99/32 next-hop {main_tun_peer}
set protocols static route 114.113.245.100/32 next-hop {bk_tun_peer}
set protocols static route {main_public_ip}/32 next-hop 1.1.1.1
set protocols static route {bk_public_ip}/32 next-hop 1.1.1.1
set protocols static route 192.168.55.250/32 next-hop {main_tun_peer} track '{main_track_name}'
set protocols static route 192.168.55.250/32 next-hop {bk_tun_peer} distance '5'
set protocols static route 192.168.237.86/32 next-hop {main_tun_peer} track '{main_track_name}'
set protocols static route 192.168.237.86/32 next-hop {bk_tun_peer} distance '5'
{return_routes_block}
set service ssh disable-host-validation
set service ssh port '2707'
set system config-management commit-revisions '100'
set system conntrack modules ftp
set system conntrack modules h323
set system conntrack modules nfs
set system conntrack modules pptp
set system conntrack modules sip
set system conntrack modules sqlnet
set system conntrack modules tftp
set system console device ttyS0 speed '115200'
set system host-name '{hostname}'
set system ipv6 disable
set system login user bothwin authentication plaintext-password 'Tfe28@w%'
set system name-server '{wan_if}'
set system ntp server 192.168.55.250
set system ntp server ntp.aliyun.com
set system ntp server time1.vyos.net
set system option performance 'throughput'
set system option reboot-on-panic
set system syslog global facility all level 'info'
set system syslog global facility protocols level 'debug'
set system time-zone 'Asia/Shanghai'
set track name {main_track_name} failure-count '2'
set track name {main_track_name} success-count '2'
set track name {main_track_name} test 10 resp-time '5'
set track name {main_track_name} test 10 target '{main_tun_peer}'
set track name {main_track_name} test 10 ttl-limit '1'
set track name {main_track_name} test 10 type 'ping'
set vpn ipsec esp-group ESP-1E compression 'disable'
set vpn ipsec esp-group ESP-1E lifetime '3600'
set vpn ipsec esp-group ESP-1E mode 'tunnel'
set vpn ipsec esp-group ESP-1E pfs 'dh-group2'
set vpn ipsec esp-group ESP-1E proposal 1 encryption '3des'
set vpn ipsec esp-group ESP-1E proposal 1 hash 'sha1'
set vpn ipsec ike-group IKE-1E close-action 'none'
set vpn ipsec ike-group IKE-1E dead-peer-detection action 'restart'
set vpn ipsec ike-group IKE-1E dead-peer-detection interval '30'
set vpn ipsec ike-group IKE-1E dead-peer-detection timeout '120'
set vpn ipsec ike-group IKE-1E ikev2-reauth 'no'
set vpn ipsec ike-group IKE-1E key-exchange 'ikev1'
set vpn ipsec ike-group IKE-1E lifetime '28800'
set vpn ipsec ike-group IKE-1E proposal 1 dh-group '2'
set vpn ipsec ike-group IKE-1E proposal 1 encryption '3des'
set vpn ipsec ike-group IKE-1E proposal 1 hash 'sha1'
set vpn ipsec ipsec-interfaces interface '{wan_if}'
set vpn ipsec nat-traversal 'enable'
set vpn ipsec site-to-site peer {main_public_ip} authentication mode 'pre-shared-secret'
set vpn ipsec site-to-site peer {main_public_ip} authentication pre-shared-secret '{main_ipsec_psk}'
set vpn ipsec site-to-site peer {main_public_ip} authentication remote-id '{main_public_ip}'
set vpn ipsec site-to-site peer {main_public_ip} connection-type 'initiate'
set vpn ipsec site-to-site peer {main_public_ip} default-esp-group 'ESP-1E'
set vpn ipsec site-to-site peer {main_public_ip} ike-group 'IKE-1E'
set vpn ipsec site-to-site peer {main_public_ip} ikev2-reauth 'inherit'
set vpn ipsec site-to-site peer {main_public_ip} local-address '{wan_addr_plain}'
set vpn ipsec site-to-site peer {main_public_ip} tunnel 1 allow-nat-networks 'disable'
set vpn ipsec site-to-site peer {main_public_ip} tunnel 1 allow-public-networks 'disable'
set vpn ipsec site-to-site peer {main_public_ip} tunnel 1 local prefix '{main_loop_ip_cidr}'
set vpn ipsec site-to-site peer {main_public_ip} tunnel 1 remote prefix '{main_ipsec_peer_ip}/32'
set vpn ipsec site-to-site peer {bk_public_ip} authentication mode 'pre-shared-secret'
set vpn ipsec site-to-site peer {bk_public_ip} authentication pre-shared-secret '{bk_ipsec_psk}'
set vpn ipsec site-to-site peer {bk_public_ip} authentication remote-id '{bk_public_ip}'
set vpn ipsec site-to-site peer {bk_public_ip} connection-type 'initiate'
set vpn ipsec site-to-site peer {bk_public_ip} default-esp-group 'ESP-1E'
set vpn ipsec site-to-site peer {bk_public_ip} ike-group 'IKE-1E'
set vpn ipsec site-to-site peer {bk_public_ip} ikev2-reauth 'inherit'
set vpn ipsec site-to-site peer {bk_public_ip} local-address '{wan_addr_plain}'
set vpn ipsec site-to-site peer {bk_public_ip} tunnel 1 allow-nat-networks 'disable'
set vpn ipsec site-to-site peer {bk_public_ip} tunnel 1 allow-public-networks 'disable'
set vpn ipsec site-to-site peer {bk_public_ip} tunnel 1 local prefix '{bk_loop_ip_cidr}'
set vpn ipsec site-to-site peer {bk_public_ip} tunnel 1 remote prefix '{bk_ipsec_peer_ip}/32'
{dhcp_server_block}"""


def generate_mpls_ipsec_config(d):
    return TEMPLATE_MPLS_IPSEC.format(**d)


# =====================================================================
# 接入方式胶囊切换条（风格与 er_fastip_2in1_v8.py 保持一致）
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


def build_tab_shell(tab, accent, note_text, example_text, init_parent):
    tab.columnconfigure(0, weight=1); tab.rowconfigure(0, weight=1)
    v_pane = ttk.PanedWindow(tab, orient="vertical")
    v_pane.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4,0))
    top_h = ttk.PanedWindow(v_pane, orient="horizontal"); v_pane.add(top_h, weight=1)

    notes_f = tk.Frame(top_h, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
    top_h.add(notes_f, weight=1)
    notes_f.rowconfigure(0, weight=1); notes_f.columnconfigure(0, weight=1)
    nb = ttk.Notebook(notes_f); nb.grid(row=0, column=0, sticky="nsew")
    tn = tk.Frame(nb, bg=BG_PANEL); nb.add(tn, text="  备注说明  ")
    nt = tk.Text(tn, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat", bd=0, padx=10, pady=4)
    nt.pack(fill="both", expand=True); nt.insert(tk.END, note_text); nt.config(state="disabled")
    te = tk.Frame(nb, bg=BG_PANEL); nb.add(te, text="  填写示例  ")
    ew = tk.Frame(te, bg=BG_PANEL); ew.pack(fill="both", expand=True)
    evsb = ttk.Scrollbar(ew, orient="vertical", style="Vertical.TScrollbar"); evsb.pack(side="right", fill="y")
    et = tk.Text(ew, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat", bd=0, padx=10, pady=4, yscrollcommand=evsb.set)
    et.pack(side="left", fill="both", expand=True); evsb.config(command=et.yview)
    et.insert(tk.END, example_text); et.config(state="disabled")

    init_f = tk.Frame(top_h, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
    top_h.add(init_f, weight=2); init_parent[0] = init_f

    bot_h = ttk.PanedWindow(v_pane, orient="horizontal"); v_pane.add(bot_h, weight=1)
    def make_bot_side(label_text):
        f = tk.Frame(bot_h, bg=BG_PANEL, highlightbackground=BORDER, highlightthickness=1)
        bot_h.add(f, weight=1)
        f.rowconfigure(1, weight=1); f.columnconfigure(0, weight=1)
        h = tk.Frame(f, bg=accent, height=26); h.grid(row=0, column=0, sticky="ew"); h.grid_propagate(False)
        tk.Frame(h, bg=FG_BRT, width=3).pack(side="left", fill="y")
        tk.Label(h, text=f"  {label_text}", font=FONT_HDR, bg=accent, fg=FG_BRT, pady=2).pack(side="left")
        inner = tk.Frame(f, bg=BG_INPUT); inner.grid(row=1, column=0, sticky="nsew")
        return inner
    li = make_bot_side("数据头输入"); ri = make_bot_side("生成结果")
    left_text = make_text(li); right_output = make_text(ri, readonly=False)

    # 嵌套在 content_frame 内时须保证上半区最小高度，避免下半「生成结果」遮挡初始化区底部。
    try:
        v_pane.pane(top_h, minsize=280)
    except tk.TclError:
        pass

    def _init_sash(vp=v_pane, _tab=tab):
        # 上 55% / 下 45%：上下区高度分配（备注/初始化 | 数据头/生成结果）
        try:
            _tab.update_idletasks()
            total = vp.winfo_height()
            if total > 100:
                vp.sashpos(0, int(total * 0.55))
        except Exception:
            pass

    for _delay in (50, 150, 400, 800):
        tab.after(_delay, _init_sash)

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
# MPLS Tab 构建器
# =====================================================================
CN_NOTE = (
    "er_mpls_v1 正式试用版\n\n"
    "• 总体只有单机+open接入的，海外主线是单open接入的，其他的数据不处理\n"
    "• 奇数尾号LineID = 主线，偶数尾号 = 备线\n"
    "• 每条线需要 GRE PE + VPN PE 两个子块\n"
    "• 需要 PE AS号 和 CE AS号（从业务数据自动识别）\n"
    "• 内网段同时作为 prefix-list 中宣告的路由\n"
    "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
    "• lan的dhcp是你开给别人的。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)

OV_NOTE = (
    "er_mpls_v1 正式试用版\n\n"
    "• 总体只有单机+open接入的，海外主线是单open接入的，其他的数据不处理\n"
    "• 奇数尾号LineID = 主线，偶数尾号 = 备线\n"
    "• 主线仅需一个 vtun 直连骨干（无 GRE）\n"
    "• 备线为标准 VPN+GRE 双隧道接入骨干\n"
    "• 需要 PE AS号 和 CE AS号（从业务数据自动识别）\n"
    "• 内网段同时作为 prefix-list 中宣告的路由\n"
    "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
    "• lan的dhcp是你开给别人的。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)

CN_EXAMPLE = (
    "##广西##\nLineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\n"
    "wanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\n"
    "PE AS号:65512\nCE AS号:65201\n\n"
    "PE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\n"
    "PE 对接:180.142.110.241\n\n"
    "LineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\n"
    "wanip:10.40.195.188/30\nPE 对接:192.168.253.80\nCE 对接:10.120.52.30\n"
    "PE AS号:65531\nCE AS号:65201\n\n"
    "PE:szd-acvpnpe2\nTunnel:vtun10209\nwanip:10.120.52.28/30\n"
    "PE 对接:202.46.225.106\n"
)

OV_EXAMPLE = (
    "##越南##\nLineID:609291B1\nPE:han2-vupe1\nTunnel:vtun1104\n"
    "wanip:10.40.252.148/30\nPE 对接:42.115.85.51\n"
    "PE AS号:65179\nCE AS号:65202\n\n"
    "LineID:609291B2\nPE:hkj-upe2\nTunnel:Tunnel0/0/1618\n"
    "wanip:10.33.62.160/30\nPE 对接:192.168.236.21\nCE 对接:10.55.18.78\n"
    "PE AS号:65532\nCE AS号:65202\n\n"
    "PE:hkj-ipsecgw2\nTunnel:vtun1176\nwanip:10.55.18.76/30\n"
    "PE 对接:103.48.141.29\n"
)


def build_mpls_tab(tab, accent, config_type, note_text, example_text):
    init_container = [None]
    left, right, status, gen_btn, exp_btn, rst_btn, example_et = build_tab_shell(
        tab, accent, note_text, example_text, init_container)
    get_hostname, get_net, reset_net, get_raw = build_net_panel(
        init_container[0], accent, wan_dhcp_default=False, lan_dhcp_default=True)
    _MPLS_TAB_RESET_NET_FUNCS.append(reset_net)
    example_et.config(state="normal")
    example_et.delete("1.0", tk.END)
    example_et.insert(tk.END, example_text)
    example_et.config(state="disabled")

    def generate():
        wan_ip, wan_gw, lan_ip, lan_gw, inner_raw = get_raw()
        ok, errs = validate_net_panel_values(
            wan_ip, wan_gw, lan_ip, lan_gw, inner_raw,
            DEFAULT_WAN_CIDR, DEFAULT_WAN_GW, DEFAULT_LAN_CIDR)
        if not ok:
            messagebox.showwarning("网络格式校验未通过",
                "以下输入不符合网络标准，请修正后再生成：\n\n" + "\n".join(errs))
            status.set("⚠  请修正网络格式后再生成"); return

        raw = left.get("1.0", tk.END).strip()
        if not raw:
            status.set("⚠  请先输入业务数据"); return
        d = parse_epoch_mpls(raw)
        hn = get_hostname()
        if not hn:
            hn = extract_lineid_mpls(raw) or "（请填写Hostname）"
        d["hostname"] = hn
        d["config_type"] = config_type
        d["access_mode"] = "OpenVPN"
        net = get_net()
        d.update(net)
        inject_er_netpanel_init_aliases(d)

        ce_as = d.get("ce_as", "")
        if not ce_as:
            messagebox.showwarning("CE AS号缺失", "未从业务数据中解析到 CE AS号，请检查输入。")
            status.set("⚠  CE AS号缺失"); return

        inner_nets_for_rr = d.get("inner_nets") or []
        lan_cidr_rr = d.get("lan_cidr") or ""
        lan_gw_rr   = d.get("lan_gw") or ""
        rr_on       = d.get("return_route_enabled", False)
        outside_rr  = _nets_needing_return_by_network(lan_cidr_rr, inner_nets_for_rr) if lan_cidr_rr else []
        rr_lines = []
        if outside_rr and rr_on and lan_gw_rr:
            rr_lines = [f"set protocols static route {n} next-hop {lan_gw_rr}" for n in outside_rr]
        d["return_routes_block"] = "\n".join(rr_lines)

        inner_nets = d.get("inner_nets") or []
        prefix_lines = []
        for i, n in enumerate(inner_nets):
            rule_num = 10 * (i + 1)
            prefix_lines.append(f"set policy prefix-list AS{ce_as}-OUT rule {rule_num} action 'permit'")
            prefix_lines.append(f"set policy prefix-list AS{ce_as}-OUT rule {rule_num} prefix '{n}'")
        d["prefix_list_block"] = "\n".join(prefix_lines)

        if field_coverage:
            miss = field_coverage.mpls_missing_for_generate(d)
            field_coverage.show_generation_coverage_notice(
                messagebox, miss, f"Epoch MPLS · {config_type}")

        try:
            output = generate_mpls_config(d)
        except KeyError as e:
            status.set(f"⚠  字段缺失：{e}"); return

        right.delete("1.0", tk.END)
        right.insert(tk.END, output)

        _lt_map = {"vtun_only": "vtun直连", "vtun_gre": "VPN+GRE", "gre_only": "GRE直连"}
        m_lt = _lt_map.get(d.get("main_line_type", ""), "未知")
        b_lt = _lt_map.get(d.get("bk_line_type", ""), "未知")
        line_info = f"主线:{m_lt}  备线:{b_lt}"
        rr_cnt = d.get("return_routes_block","").count("\n") + (1 if d.get("return_routes_block","").strip() else 0)
        status.set(f"✓  {config_type}配置已生成  ·  {output.count(chr(10))}行  "
                   f"·  Hostname:{hn}  ·  CE AS:{ce_as}  ·  {line_info}"
                   + (f"  ·  回程路由:{rr_cnt}条" if rr_cnt else ""))
        log_generate_config(
            tool="mpls",
            variant=config_type,
            input_text=raw,
            output_text=output,
        )

    def export():
        c = right.get("1.0", tk.END).strip()
        if not c:
            status.set("⚠  尚无配置"); return
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text","*.txt")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(c)
            status.set(f"✓  已导出：{p}")

    def reset():
        left.delete("1.0", tk.END); right.delete("1.0", tk.END)
        reset_net(); status.set("↺  已恢复初始")

    gen_btn.bind("<Button-1>", lambda e: generate())
    exp_btn.bind("<Button-1>", lambda e: export())
    rst_btn.bind("<Button-1>", lambda e: reset())


def build_mpls_ipsec_tab(tab, accent):
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(0, weight=1)
    init_container = [None]
    left, right, status, gen_btn, exp_btn, rst_btn, _example_et = build_tab_shell(
        tab, accent, MPLS_IPSEC_NOTE, MPLS_IPSEC_EXAMPLE, init_container)
    get_hostname, get_net, reset_net, get_raw = build_net_panel(
        init_container[0], accent, wan_dhcp_default=False, lan_dhcp_default=True)
    _MPLS_TAB_RESET_NET_FUNCS.append(reset_net)

    def generate():
        wan_ip, wan_gw, lan_ip, lan_gw, inner_raw = get_raw()
        ok, errs = validate_net_panel_values(
            wan_ip, wan_gw, lan_ip, lan_gw, inner_raw,
            DEFAULT_WAN_CIDR, DEFAULT_WAN_GW, DEFAULT_LAN_CIDR)
        if not ok:
            messagebox.showwarning(
                "网络格式校验未通过",
                "以下输入不符合网络标准，请修正后再生成：\n\n" + "\n".join(errs))
            status.set("⚠  请修正网络格式后再生成")
            return

        raw = left.get("1.0", tk.END).strip()
        if not raw:
            status.set("⚠  请先输入业务数据")
            return

        # ── 与 OpenVPN MPLS generate() 保持完全一致的处理流程 ──────────────
        d = parse_epoch_mpls_ipsec(raw)
        hn = get_hostname() or extract_lineid_mpls(raw) or "（请填写Hostname）"
        d["hostname"] = hn
        d["access_mode"] = "IPSec"

        # net 由 get_net_cfg() 提供，其中 lan_gw 已由 _real_lan_gw() 正确转换
        # 历史保存的 "同LAN IP" 等别名仍兼容读取为实际 LAN 主机地址
        net = get_net()
        d.update(net)

        # 在 inject_er_netpanel_init_aliases 前二次确认 lan_gw 已去别名/去掩码
        d["lan_gw"] = _normalize_lan_gw_value(
            str(d.get("lan_cidr", "")), str(d.get("lan_gw", "")))

        inject_er_netpanel_init_aliases(d)

        ce_as = str(d.get("ce_as", "")).strip()
        if not ce_as:
            messagebox.showwarning("CE AS号缺失", "未从业务数据中解析到 CE AS号，请检查输入。")
            status.set("⚠  CE AS号缺失")
            return

        # 回程路由（与 OpenVPN 分支逻辑完全一致）
        inner_nets_for_rr = d.get("inner_nets") or []
        lan_cidr_rr = d.get("lan_cidr") or ""
        lan_gw_rr   = d.get("lan_gw") or ""
        rr_on       = d.get("return_route_enabled", False)
        outside_rr  = _nets_needing_return_by_network(lan_cidr_rr, inner_nets_for_rr) if lan_cidr_rr else []
        rr_lines = []
        if outside_rr and rr_on and lan_gw_rr:
            rr_lines = [f"set protocols static route {n} next-hop {lan_gw_rr}" for n in outside_rr]
        d["return_routes_block"] = "\n".join(rr_lines)

        # prefix-list（与 OpenVPN 分支逻辑完全一致）
        inner_nets = d.get("inner_nets") or []
        prefix_lines = []
        for i, n in enumerate(inner_nets):
            rule_num = 10 * (i + 1)
            prefix_lines.append(f"set policy prefix-list AS{ce_as}-OUT rule {rule_num} action 'permit'")
            prefix_lines.append(f"set policy prefix-list AS{ce_as}-OUT rule {rule_num} prefix '{n}'")
        d["prefix_list_block"] = "\n".join(prefix_lines)

        # IPSec 额外字段（wan_addr_plain、tun 地址对、loop_ip_cidr、track_name）
        d["wan_addr_plain"] = _cidr_plain(str(d.get("wan_addr", "")))
        for px in ("main", "bk"):
            tun_peer, tun_local, tun_prefix = _cidr_host_pair(str(d.get(f"{px}_gre_wanip", "")))
            d[f"{px}_tun_peer"]  = tun_peer
            d[f"{px}_tun_local"] = tun_local
            d[f"{px}_tun_addr"]  = f"{tun_local}/{tun_prefix}" if tun_local and tun_prefix else ""
            loop_ip = str(d.get(f"{px}_loop_ip", "")).strip()
            d[f"{px}_loop_ip_cidr"] = f"{loop_ip}/32" if loop_ip else ""
            d[f"{px}_track_name"]   = str(d.get(f"{px}_gre_tun", "")).strip()

        if field_coverage:
            miss = field_coverage.mpls_ipsec_missing_for_generate(d)
            field_coverage.show_generation_coverage_notice(
                messagebox, miss, "Epoch MPLS · IPSec")

        try:
            output = generate_mpls_ipsec_config(d)
        except KeyError as e:
            status.set(f"⚠  字段缺失：{e}")
            return

        right.delete("1.0", tk.END)
        right.insert(tk.END, output)
        rr_cnt = len(rr_lines)
        status.set(
            f"✓  IPSec配置已生成  ·  {output.count(chr(10))}行"
            f"  ·  Hostname:{hn}  ·  CE AS:{ce_as}"
            + (f"  ·  回程路由:{rr_cnt}条" if rr_cnt else "")
        )
        log_generate_config(
            tool="mpls",
            variant="ipsec",
            input_text=raw,
            output_text=output,
        )

    def export():
        c = right.get("1.0", tk.END).strip()
        if not c:
            status.set("⚠  尚无配置")
            return
        p = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text", "*.txt")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(c)
            status.set(f"✓  已导出：{p}")

    def reset():
        left.delete("1.0", tk.END)
        left.insert("1.0", MPLS_IPSEC_EXAMPLE)
        right.delete("1.0", tk.END)
        reset_net()
        status.set("↺  已恢复初始")

    gen_btn.bind("<Button-1>", lambda e: generate())
    exp_btn.bind("<Button-1>", lambda e: export())
    rst_btn.bind("<Button-1>", lambda e: reset())


# =====================================================================
# 构建所有 Tab
# =====================================================================
build_mpls_tab(tab_cn, ACCENT_CN, "国内", CN_NOTE, CN_EXAMPLE)
build_mpls_tab(tab_ov, ACCENT_OV, "海外", OV_NOTE, OV_EXAMPLE)
build_mpls_ipsec_tab(tab_ipsec, ACCENT_OV)

def _visual_merge_init_defaults(updates: dict) -> None:
    """all_in_one 可视化编辑器：合并 DEFAULT_* 并刷新国内/海外网络面板。"""
    g = globals()
    for k, v in updates.items():
        if k not in g:
            continue
        cur = g[k]
        if isinstance(cur, bool):
            g[k] = str(v).strip().lower() in ("1", "true", "yes", "on", "开")
        else:
            g[k] = str(v).strip()
    weth = str(g.get("DEFAULT_WAN_ETH", "0")).strip() or "0"
    leth = str(g.get("DEFAULT_LAN_ETH", "5")).strip() or "5"
    for sv in _MPLS_INIT_ETH_WAN_VARS:
        try:
            sv.set(weth)
        except Exception:
            pass
    for sv in _MPLS_INIT_ETH_LAN_VARS:
        try:
            sv.set(leth)
        except Exception:
            pass
    for fn in _MPLS_TAB_RESET_NET_FUNCS:
        try:
            fn()
        except Exception:
            pass


root.mainloop()
