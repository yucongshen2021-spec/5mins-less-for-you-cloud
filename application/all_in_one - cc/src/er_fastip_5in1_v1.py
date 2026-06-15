#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Epoch FastIP 5.0 配置生成工具 v1.0

  VyOS set 语法（vs 4.0 Epoch 语法）。
  数据头格式与 4.0 完全一致，仅输出模板不同。
  5.0 特有参数（ssh_port、snmp_community、ntp、dns 等）全部硬编码，
  不暴露给用户。
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
# 公共工具（fallback，独立运行时使用）
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

# =====================================================================
# 网络格式校验
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


def _nets_needing_return(base_cidr, inner_nets):
    """返回不在 base_cidr 网段内的 inner_nets（需要回程路由）。"""
    if not base_cidr:
        return list(inner_nets)
    try:
        base = ipaddress.ip_network(str(base_cidr).strip(), strict=False)
    except (ValueError, ipaddress.AddressValueError):
        return list(inner_nets)
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
# 隧道名称标准化 & 工具函数
# =====================================================================
def _normalize_vtun(raw):
    if not raw:
        return ""
    raw = str(raw).strip()
    s = raw.lower()
    if s.startswith("vtun"):
        return s
    m = re.match(r"tunnel\s*0\s*/\s*0\s*/\s*(\d+)", s)
    if m:
        return f"vtun{m.group(1)}"
    if s.startswith("tun"):
        return f"v{s}"
    m = re.search(r"(\d+)$", raw)
    if m:
        return f"vtun{m.group(1)}"
    return s


def _vtun_port(tunnel_id):
    if not tunnel_id:
        return ""
    s = str(tunnel_id).strip().lower()
    port = s[4:] if s.startswith("vtun") else (s[3:] if s.startswith("tun") else s)
    m = re.match(r"(\d+)", port)
    return m.group(1) if m else ""


def normalize_tun(raw):
    """标准化 GRE 隧道名称（保留 tun 前缀，与 _normalize_vtun 不同）。"""
    if not raw:
        return ""
    raw = str(raw).strip()
    s = raw.lower()
    m = re.match(r"tunnel\s*0\s*/\s*0\s*/\s*(\d+)", s)
    if m:
        return f"tun{m.group(1)}"
    m = re.match(r"tunnel(\d+)$", s)
    if m:
        return f"tun{m.group(1)}"
    if s.startswith("vtun"):
        return s[1:]
    if s.startswith("tun"):
        return s
    m = re.search(r"(\d+)$", raw)
    if m:
        return f"tun{m.group(1)}"
    return s


def _us_sub_role(sub_text):
    """识别 US 数据头子块角色（三重冗余：PE 名称 / 隧道前缀 / 特殊字段）。"""
    pe = _get(r'^\s*PE\s*[：:]\s*(.+?)$', sub_text).lower()
    tun = _get(r'^\s*(?:Tunnel|TUNNEL)\s*[：:]\s*(\S+)', sub_text).lower()
    if re.search(r'海外出口ip', sub_text, re.IGNORECASE):
        return 'gre2'
    if re.search(r'acvpn|ipsecvpn|ipsecgw', pe):
        return 'openvpn'
    if re.search(r'natpe', pe):
        return 'gre2'
    if re.search(r'(?:^|[-_])upe', pe):
        return 'gre1'
    if tun.startswith('vtun'):
        return 'openvpn'
    if re.match(r'tunnel|^tun\d', tun):
        return 'gre_unknown'
    return None


def parse_epoch_us(text):
    """解析 US 数据头（LineID 格式，三层隧道）。

    返回 dict，键名与 4.0 模块兼容。
    """
    result = {k: "" for k in [
        "main_acvpn_gre_pe", "main_acvpn_gre_tun", "main_acvpn_gre_wanip",
        "main_acvpn_gre_pe_ip", "main_acvpn_gre_ce_ip", "main_acvpn_gre_remote",
        "main_acvpn_vtun_pe", "main_acvpn_vtun_id", "main_acvpn_vtun_port",
        "main_acvpn_vtun_local", "main_acvpn_vtun_remote", "main_acvpn_vtun_docking",
        "bk_acvpn_gre_pe", "bk_acvpn_gre_tun", "bk_acvpn_gre_wanip",
        "bk_acvpn_gre_pe_ip", "bk_acvpn_gre_ce_ip", "bk_acvpn_gre_remote",
        "bk_acvpn_vtun_pe", "bk_acvpn_vtun_id", "bk_acvpn_vtun_port",
        "bk_acvpn_vtun_local", "bk_acvpn_vtun_remote", "bk_acvpn_vtun_docking",
        "main_us_pe", "main_us_tun", "main_us_wanip",
        "main_us_pe_ip", "main_us_gre_ce_ip", "main_us_pe_docking",
        "main_us_nat_ip", "main_us_bgp1", "main_us_bgp2",
        "bk_us_pe", "bk_us_tun", "bk_us_wanip",
        "bk_us_pe_ip", "bk_us_gre_ce_ip", "bk_us_pe_docking",
        "bk_us_nat_ip", "bk_us_bgp1", "bk_us_bgp2",
        "ce_docking", "fw_options_block", "us_bgp_routes", "hostname",
        "return_routes_block",
    ]}
    result["main_us_nat_ips"] = []
    result["bk_us_nat_ips"] = []
    all_gre2_subs = []

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
        except Exception:
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
            end = pe_line_idx[i + 1] if i + 1 < len(pe_line_idx) else len(lines)
            sub_blocks.append("\n".join(lines[start:end]))
        if not pe_line_idx and re.search(r'海外出口ip', block, re.IGNORECASE):
            sub_blocks = [block]

        identified, unknown_gres = {}, []
        for sub in sub_blocks:
            role = _us_sub_role(sub)
            if role == 'gre_unknown':
                unknown_gres.append(sub)
            elif role == 'gre2':
                all_gre2_subs.append(sub)
            elif role in ('openvpn', 'gre1'):
                if role not in identified:
                    identified[role] = sub
        for sub in unknown_gres:
            if 'gre1' not in identified:
                identified['gre1'] = sub
                break

        if 'gre1' in identified:
            sub = identified['gre1']
            result[f"{px}_acvpn_gre_pe"] = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub)
            tun_raw = _get(r'^\s*(?:Tunnel|TUNNEL)\s*[:：]\s*(\S+)', sub)
            result[f"{px}_acvpn_gre_tun"] = normalize_tun(tun_raw)
            wanip = _get(r'^\s*wanip\s*[:：]\s*([\d./]+)', sub)
            result[f"{px}_acvpn_gre_wanip"] = wanip
            pe_ip, ce_ip = wanip_hosts(wanip)
            result[f"{px}_acvpn_gre_pe_ip"] = pe_ip
            result[f"{px}_acvpn_gre_ce_ip"] = ce_ip
            result[f"{px}_acvpn_gre_remote"] = _get(r'PE\s*对接\s*[:：]\s*([\d.]+)', sub)
            ce_dock = _get(r'CE\s*对接\s*[:：]+\s*([\d.]+)', sub)
            if ce_dock:
                result[f"{px}_acvpn_vtun_local"] = ce_dock

        if 'openvpn' in identified:
            sub = identified['openvpn']
            result[f"{px}_acvpn_vtun_pe"] = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub)
            vtun_raw = _get(r'^\s*(?:Tunnel|TUNNEL)\s*[:：]\s*(\S+)', sub)
            vtun_id = _normalize_vtun(vtun_raw)
            result[f"{px}_acvpn_vtun_id"] = vtun_id
            result[f"{px}_acvpn_vtun_port"] = _vtun_port(vtun_id)
            vtun_wanip = _get(r'^\s*wanip\s*[:：]\s*([\d./]+)', sub)
            pe_ip2, _ = wanip_hosts(vtun_wanip)
            result[f"{px}_acvpn_vtun_remote"] = pe_ip2
            result[f"{px}_acvpn_vtun_docking"] = _get(r'PE\s*对接\s*[:：]\s*([\d.]+)', sub)
            ce_dock_vtun = _get(r'CE\s*对接\s*[:：]+\s*([\d.]+)', sub)
            if ce_dock_vtun and not result.get(f"{px}_acvpn_vtun_local"):
                result[f"{px}_acvpn_vtun_local"] = ce_dock_vtun

    def _fill_gre2(sub, px):
        result[f"{px}_us_pe"] = _get(r'^\s*PE\s*[:：]\s*(.+?)$', sub)
        tun_raw = _get(r'^\s*(?:TUNNEL|Tunnel)\s*[:：]\s*(\S+)', sub)
        result[f"{px}_us_tun"] = normalize_tun(tun_raw)
        wanip = _get(r'^\s*WANIP\s*[:：]\s*([\d./]+)', sub)
        result[f"{px}_us_wanip"] = wanip
        pe_ip, ce_ip = wanip_hosts(wanip)
        result[f"{px}_us_pe_ip"] = pe_ip
        result[f"{px}_us_gre_ce_ip"] = ce_ip
        result[f"{px}_us_pe_docking"] = _get(r'PE\s*(?:[Dd]ocking|对接)\s*[:：]+\s*([\d.]+)', sub)
        ce_dock = _get(r'CE\s*(?:[Dd]ocking|对接)\s*[:：]+\s*([\d.]+)', sub)
        if px == "main" and ce_dock:
            result["ce_docking"] = ce_dock
        bgp_raw = _get(r'BGPSERVER\s*IP\s*[:：]\s*(.+)', sub)
        bgps = [ip.strip() for ip in re.split(r'[,，\s]+', bgp_raw)
                if re.match(r'^\d+\.\d+', ip.strip())]
        result[f"{px}_us_bgp1"] = bgps[0] if bgps else ""
        result[f"{px}_us_bgp2"] = bgps[1] if len(bgps) > 1 else ""
        oversea_m = re.search(
            r'海外出口ip\s*[:：]\s*(.*?)(?=\n[^\d\s]|\Z)',
            sub, re.IGNORECASE | re.DOTALL
        )
        nat_ips = []
        if oversea_m:
            blob = oversea_m.group(1)
            pairs = re.findall(
                r'(\d{1,3}(?:\.\d{1,3}){3})\s*[-–—~]\s*(\d{1,3}(?:\.\d{1,3}){3})',
                blob
            )
            if pairs:
                nat_ips = [p[0] for p in pairs]
            else:
                nat_ips = re.findall(r'\d{1,3}(?:\.\d{1,3}){3}', blob)
            seen = set()
            nat_ips = [ip for ip in nat_ips if not (ip in seen or seen.add(ip))]
        result[f"{px}_us_nat_ips"] = nat_ips
        if nat_ips:
            result[f"{px}_us_nat_ip"] = nat_ips[0]

    if len(all_gre2_subs) >= 1:
        _fill_gre2(all_gre2_subs[0], "main")
    if len(all_gre2_subs) >= 2:
        _fill_gre2(all_gre2_subs[1], "bk")
    return result


# =====================================================================
# 默认值（与 4.0 模块相同，可视化编辑器会写入 globals）
# =====================================================================
DEFAULT_WAN_CIDR   = "192.168.1.10/24"
DEFAULT_WAN_GW     = "192.168.1.1"
DEFAULT_LAN_CIDR   = "192.168.5.1/24"
DEFAULT_INNER_NETS = "192.168.0.0/16, 172.16.0.0/12, 10.0.0.0/8"
DEFAULT_WAN_ETH    = "0"
DEFAULT_LAN_ETH    = "5"
DEFAULT_WAN_DHCP   = False
DEFAULT_LAN_DHCP   = True
DEFAULT_LAN_GW     = DEFAULT_LAN_CIDR.split("/", 1)[0].strip() if DEFAULT_LAN_CIDR else ""
DEFAULT_GEN_RETURN_ROUTE = False
# HK 页签默认（与非 HK 相同；all_in_one 按场景分别持久化）
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
# =====================================================================
# 5.0 硬编码参数（不暴露给用户）
# =====================================================================
_EPOCH5_PKI_SECRET_KEY  = "bc128dc962ec1c5956a642eb25b10d959e790198c6de25499ba6509cf3e2fd3a1f5334ef62335dd1f159f12614c77d6a889796c5bc237daccab9d625f8ec59f37f4fcca623ef92039a890d4b5de872741cb7ef76f2b1d7f007ee027e57113d4f351a17e4ed101f6104073bfebc840daf50fe3186e7684ab114777c19f2d1c017c426d01dcb1d28ec16b667d9abbf5061925f41b0d09a282b237668f8537cc9e1db2677d56ff740f82fa9ed370b5ca4a8f6408893e8cd15fd908eafe15599aea0cd42d72be9175d63776190ca0ffd4c04e1ac42d0ff91aeaf2c7f2ec06f813d615b9731ebe9a00ef4ebb74e92d23019e5d4c80805afe6e66b14f3066e134cc859"
_EPOCH5_DNS_GLOBAL1     = "8.8.4.4"
_EPOCH5_DNS_GLOBAL2     = "8.8.8.8"
_EPOCH5_JUMPBOX_IP      = "192.168.55.250"


# =====================================================================
# 5.0 HK 模板（VyOS set 语法）
# =====================================================================
TEMPLATE_EPOCH5_HK = """\
# ==========================================================
# Epoch 5.0 HK 出口配置  Hostname: {hostname}
# 主线  PE:{main_pe}  TUNNEL:{main_tunnel}(port:{main_tunnel_port})
#       WANIP:{main_wanip}  PE侧:{main_wanip_remote}  CE侧:{main_wanip_local}
#       Docking:{main_docking}  HKIP:{hkip}  CELOIP:{ce_loip}
#       BGP: {main_bgp1}, {main_bgp2}
# 备线  PE:{bk_pe}  TUNNEL:{bk_tunnel}(port:{bk_tunnel_port})
#       WANIP:{bk_wanip}  PE侧:{bk_wanip_remote}  CE侧:{bk_wanip_local}
#       Docking:{bk_docking}  BGP: {bk_bgp1}, {bk_bgp2}
# ==========================================================

# 防火墙白名单网络组
set firewall group network-group GROUP-FNET-Whitelist network '192.168.0.0/16'
set firewall group network-group GROUP-FNET-Whitelist network '172.16.0.0/12'
set firewall group network-group GROUP-FNET-Whitelist network '10.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '100.64.0.0/10'
set firewall group network-group GROUP-FNET-Whitelist network '224.0.0.0/4'
set firewall group network-group GROUP-FNET-Whitelist network '127.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.117.226/32'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.119.251/32'
set firewall group network-group GROUP-FNET-Whitelist network '120.76.31.146/32'
set firewall group network-group GROUP-FNET-Whitelist network '202.104.174.178/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.236.97/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.238.8/29'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.99/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.100/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.101/32'

# 防火墙本机防护
set firewall ipv4 input filter default-action 'accept'
set firewall ipv4 input filter rule 100 action 'jump'
set firewall ipv4 input filter rule 100 jump-target 'WAN2LOCAL'
set firewall ipv4 name WAN2LOCAL default-action 'drop'
set firewall ipv4 name WAN2LOCAL rule 1000 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1000 state 'established'
set firewall ipv4 name WAN2LOCAL rule 1000 state 'related'
set firewall ipv4 name WAN2LOCAL rule 1010 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1010 source group network-group 'GROUP-FNET-Whitelist'
set firewall ipv4 name WAN2LOCAL rule 1210 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1210 protocol 'gre'
set firewall ipv4 name WAN2LOCAL rule 1220 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1220 protocol 'ipip'
set firewall ipv4 name WAN2LOCAL rule 1230 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1230 protocol 'esp'

# 设备 hostname
set system host-name '{hostname}'

# SSH 端口
set service ssh disable-host-validation
set service ssh port '2707'

# 登录账户
set system login user bothwin authentication plaintext-password 'Tfe28@w%'

# 基本配置
set service snmp community both-win authorization 'ro'

# NTP 配置
set service ntp server 192.168.55.250
set service ntp server 202.104.174.178
set system time-zone 'Asia/Hong_Kong'

# WAN 和 LAN 配置
set interfaces ethernet {wan_if} description WAN1
set interfaces ethernet {wan_if} address '{wan_cidr}'
{lan_if_block}

# BGP 更新源
set interfaces dummy dum0 address '{ce_loip}/32'
set interfaces dummy dum0 description 'bgp-update-source'

# NOC 路由下来的 HKIP 假 IP
set interfaces dummy dum1 address '{hkip}/32'
set interfaces dummy dum1 description 'HKIP'

# 隧道配置

# OpenVPN 共享密钥
{pki_block}

# 主 OpenVPN
set interfaces openvpn {main_tunnel} description '{main_pe_desc}'
set interfaces openvpn {main_tunnel} local-address {main_wanip_local} subnet-mask '255.255.255.252'
set interfaces openvpn {main_tunnel} mode 'site-to-site'
set interfaces openvpn {main_tunnel} openvpn-option 'nobind'
set interfaces openvpn {main_tunnel} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {main_tunnel} openvpn-option 'fragment 1300'
set interfaces openvpn {main_tunnel} openvpn-option 'providers legacy default'
set interfaces openvpn {main_tunnel} persistent-tunnel
set interfaces openvpn {main_tunnel} protocol 'udp'
set interfaces openvpn {main_tunnel} remote-address '{main_wanip_remote}'
set interfaces openvpn {main_tunnel} remote-host '{main_docking}'
set interfaces openvpn {main_tunnel} remote-port '{main_tunnel_port}'
set interfaces openvpn {main_tunnel} shared-secret-key 'openvpn_secret'
set protocols static route {main_docking}/32 next-hop '{wan_gw}'

# 备 OpenVPN
set interfaces openvpn {bk_tunnel} description '{bk_pe_desc}'
set interfaces openvpn {bk_tunnel} local-address {bk_wanip_local} subnet-mask '255.255.255.252'
set interfaces openvpn {bk_tunnel} mode 'site-to-site'
set interfaces openvpn {bk_tunnel} openvpn-option 'nobind'
set interfaces openvpn {bk_tunnel} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {bk_tunnel} openvpn-option 'fragment 1300'
set interfaces openvpn {bk_tunnel} openvpn-option 'providers legacy default'
set interfaces openvpn {bk_tunnel} persistent-tunnel
set interfaces openvpn {bk_tunnel} protocol 'udp'
set interfaces openvpn {bk_tunnel} remote-address '{bk_wanip_remote}'
set interfaces openvpn {bk_tunnel} remote-host '{bk_docking}'
set interfaces openvpn {bk_tunnel} remote-port '{bk_tunnel_port}'
set interfaces openvpn {bk_tunnel} shared-secret-key 'openvpn_secret'
{static_route_bk_docking}

# DNS 劫持配置
set nat destination rule 50 destination port '53'
set nat destination rule 50 inbound-interface name '{dns_hijack_if}'
set nat destination rule 50 protocol 'tcp_udp'
set nat destination rule 50 translation address '{lan_ip}'

# NAT 配置
{lan_net_block}
set nat source rule 50 outbound-interface name '{wan_if}'
set nat source rule 50 source group network-group 'LAN-NET'
set nat source rule 50 translation address 'masquerade'
set nat source rule 1000 outbound-interface name '{main_tunnel}'
set nat source rule 1000 source group network-group 'LAN-NET'
set nat source rule 1000 translation address '{hkip}'
set nat source rule 2000 outbound-interface name '{bk_tunnel}'
set nat source rule 2000 source group network-group 'LAN-NET'
set nat source rule 2000 translation address '{hkip}'

# DNS-NET 地址组（配合 DNS 进程使用）
set firewall group address-group DNS-NET address {dns_ip1}
set firewall group address-group DNS-NET address {dns_ip2}
set nat source rule 5000 destination group address-group DNS-NET
set nat source rule 5000 outbound-interface name '{main_tunnel}'
set nat source rule 5000 translation address '{hkip}'
set nat source rule 6000 destination group address-group DNS-NET
set nat source rule 6000 outbound-interface name '{bk_tunnel}'
set nat source rule 6000 translation address '{hkip}'

# BGP Server 路由
{bgp_server_routes_block}

# BGP 配置
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
set policy community-list 91 rule 10 action 'permit'
set policy community-list 91 rule 10 description 'to_Microsoft'
set policy community-list 91 rule 10 regex '65000:9009'

set policy route-map bgp-from--RSVR rule 80 action 'permit'
set policy route-map bgp-from--RSVR rule 80 match community community-list '80'
set policy route-map bgp-from--RSVR rule 80 set ip-next-hop '{main_wanip_remote}'
set policy route-map bgp-from--RSVR rule 80 set local-preference '200'
set policy route-map bgp-from--RSVR rule 81 action 'permit'
set policy route-map bgp-from--RSVR rule 81 match community community-list '81'
set policy route-map bgp-from--RSVR rule 81 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 81 set local-preference '200'
set policy route-map bgp-from--RSVR rule 82 action 'permit'
set policy route-map bgp-from--RSVR rule 82 match community community-list '82'
set policy route-map bgp-from--RSVR rule 82 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 82 set local-preference '200'
set policy route-map bgp-from--RSVR rule 83 action 'permit'
set policy route-map bgp-from--RSVR rule 83 match community community-list '83'
set policy route-map bgp-from--RSVR rule 83 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 83 set local-preference '200'
set policy route-map bgp-from--RSVR2 rule 80 action 'permit'
set policy route-map bgp-from--RSVR2 rule 80 match community community-list '80'
set policy route-map bgp-from--RSVR2 rule 80 set ip-next-hop '{bk_wanip_remote}'
set policy route-map bgp-from--RSVR2 rule 80 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 81 action 'permit'
set policy route-map bgp-from--RSVR2 rule 81 match community community-list '81'
set policy route-map bgp-from--RSVR2 rule 81 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 81 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 82 action 'permit'
set policy route-map bgp-from--RSVR2 rule 82 match community community-list '82'
set policy route-map bgp-from--RSVR2 rule 82 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 82 set local-preference '50'
set policy route-map bgp-from--RSVR2 rule 83 action 'permit'
set policy route-map bgp-from--RSVR2 rule 83 match community community-list '83'
set policy route-map bgp-from--RSVR2 rule 83 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR2 rule 83 set local-preference '50'

set policy route-map deny-any-out rule 1000 action 'deny'
set policy route-map deny-any-out rule 1000 description 'to_bgpserver'

set protocols bgp neighbor {main_bgp1} peer-group 'RSVR'
set protocols bgp neighbor {main_bgp2} peer-group 'RSVR'
set protocols bgp neighbor {bk_bgp1} peer-group 'RSVR2'
set protocols bgp neighbor {bk_bgp2} peer-group 'RSVR2'
set protocols bgp parameters router-id '{ce_loip}'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map import 'bgp-from--RSVR'
set protocols bgp peer-group RSVR address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR remote-as '65000'
set protocols bgp peer-group RSVR update-source '{ce_loip}'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map import 'bgp-from--RSVR2'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR2 remote-as '65000'
set protocols bgp peer-group RSVR2 update-source '{ce_loip}'
set protocols bgp system-as '65000'
set protocols bgp timers holdtime '15'
set protocols bgp timers keepalive '5'

# 基本路由配置
{default_route_block}

# 主线监控
set protocols static route 114.113.245.99/32 next-hop {main_wanip_remote}

# 备线监控
set protocols static route 114.113.245.100/32 next-hop {bk_wanip_remote}

# 跳板机路由 & Track 配置
{track_block}

# 回程路由
{return_routes_block}

# DNS 配置
set service file-sync task 1 local '/config/user-data/cn.txt'
set service file-sync task 1 remote 'http://183.56.161.82:1909/f32x/domainlist/cn_domainlist.last'
set service file-sync task 2 local '/config/user-data/oversea.txt'
set service file-sync task 2 remote 'http://183.56.161.82:1909/f32x/domainlist/oversea_domainlist.last'

set service dns forwarding allow-from '0.0.0.0/0'
set service dns forwarding cache-size '10000'
set service dns forwarding dnssec 'off'
set service dns forwarding domain-list CN file '/config/user-data/cn.txt'
set service dns forwarding domain-list CN name-server 223.5.5.5
set service dns forwarding domain-list CN name-server 223.6.6.6
set service dns forwarding domain-list CN recursion-desired
set service dns forwarding domain-list HK file '/config/user-data/oversea.txt'
set service dns forwarding domain-list HK name-server 8.8.4.4
set service dns forwarding domain-list HK name-server 8.8.8.8
set service dns forwarding domain-list HK recursion-desired
set service dns forwarding listen-address '0.0.0.0'
set service dns forwarding name-server 8.8.4.4
set service dns forwarding name-server 8.8.8.8

# DHCP 服务
{dhcp_block}"""


# =====================================================================
# 占位模板（非 HK 变体待实现）
# =====================================================================
TEMPLATE_EPOCH5_US = """\
# ==========================================================
# Epoch 5.0 非香港出口配置  Hostname: {hostname}
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
# ------------------------------------------------------------------
# BGP更新源(主): {main_us_nat_ip}  BGP更新源(备): {bk_us_nat_ip}
# ==========================================================

# 防火墙白名单网络组
set firewall group network-group GROUP-FNET-Whitelist network '192.168.0.0/16'
set firewall group network-group GROUP-FNET-Whitelist network '172.16.0.0/12'
set firewall group network-group GROUP-FNET-Whitelist network '10.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '100.64.0.0/10'
set firewall group network-group GROUP-FNET-Whitelist network '224.0.0.0/4'
set firewall group network-group GROUP-FNET-Whitelist network '127.0.0.0/8'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.117.226/32'
set firewall group network-group GROUP-FNET-Whitelist network '43.229.119.251/32'
set firewall group network-group GROUP-FNET-Whitelist network '120.76.31.146/32'
set firewall group network-group GROUP-FNET-Whitelist network '202.104.174.178/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.236.97/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.112.238.8/29'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.99/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.100/32'
set firewall group network-group GROUP-FNET-Whitelist network '114.113.245.101/32'

# 防火墙本机防护
set firewall ipv4 input filter default-action 'accept'
set firewall ipv4 input filter rule 100 action 'jump'
set firewall ipv4 input filter rule 100 jump-target 'WAN2LOCAL'
set firewall ipv4 name WAN2LOCAL default-action 'drop'
set firewall ipv4 name WAN2LOCAL rule 1000 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1000 state 'established'
set firewall ipv4 name WAN2LOCAL rule 1000 state 'related'
set firewall ipv4 name WAN2LOCAL rule 1010 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1010 source group network-group 'GROUP-FNET-Whitelist'
set firewall ipv4 name WAN2LOCAL rule 1210 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1210 protocol 'gre'
set firewall ipv4 name WAN2LOCAL rule 1220 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1220 protocol 'ipip'
set firewall ipv4 name WAN2LOCAL rule 1230 action 'accept'
set firewall ipv4 name WAN2LOCAL rule 1230 protocol 'esp'

# 隧道 MSS 调整
{fw_options_block}

# 设备 hostname
set system host-name '{hostname}'

# SSH 端口
set service ssh disable-host-validation
set service ssh port '2707'

# 登录账户
set system login user bothwin authentication plaintext-password 'Tfe28@w%'

# 基本配置
set service snmp community both-win authorization 'ro'

# NTP 配置
set service ntp server 192.168.55.250
set service ntp server 202.104.174.178
set system time-zone 'Asia/Hong_Kong'

# WAN 和 LAN 配置
set interfaces ethernet {wan_if} description WAN1
set interfaces ethernet {wan_if} address '{wan_cidr}'
{lan_if_block}

# Dummy 接口
set interfaces dummy dum0 address '{ce_docking}/32'
set interfaces dummy dum0 description 'CE Docking'
set interfaces dummy dum100 address '{main_us_nat_ip}/32'
set interfaces dummy dum100 description '{main_us_dum100_desc}'
{extra_dum_main_block}
set interfaces dummy dum200 address '{bk_us_nat_ip}/32'
set interfaces dummy dum200 description '{bk_us_dum200_desc}'
{extra_dum_bk_block}

# 隧道配置

# OpenVPN 共享密钥
{pki_block}

# 主 ACVPN OpenVPN
set interfaces openvpn {main_acvpn_vtun_id} description 'MAIN {main_acvpn_vtun_pe} {main_acvpn_vtun_id}'
set interfaces openvpn {main_acvpn_vtun_id} local-address {main_acvpn_vtun_local} subnet-mask '255.255.255.252'
set interfaces openvpn {main_acvpn_vtun_id} mode 'site-to-site'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'nobind'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'fragment 1300'
set interfaces openvpn {main_acvpn_vtun_id} openvpn-option 'providers legacy default'
set interfaces openvpn {main_acvpn_vtun_id} persistent-tunnel
set interfaces openvpn {main_acvpn_vtun_id} protocol 'udp'
set interfaces openvpn {main_acvpn_vtun_id} remote-address '{main_acvpn_vtun_remote}'
set interfaces openvpn {main_acvpn_vtun_id} remote-host '{main_acvpn_vtun_docking}'
set interfaces openvpn {main_acvpn_vtun_id} remote-port '{main_acvpn_vtun_port}'
set interfaces openvpn {main_acvpn_vtun_id} shared-secret-key 'openvpn_secret'

# 主 ACVPN GRE 隧道
set interfaces tunnel {main_acvpn_gre_tun} address '{main_acvpn_gre_ce_ip}/30'
set interfaces tunnel {main_acvpn_gre_tun} description 'MAIN {main_acvpn_gre_pe}'
set interfaces tunnel {main_acvpn_gre_tun} encapsulation 'gre'
set interfaces tunnel {main_acvpn_gre_tun} ip adjust-mss '1300'
set interfaces tunnel {main_acvpn_gre_tun} mtu '1476'
set interfaces tunnel {main_acvpn_gre_tun} parameters ip ttl '255'
set interfaces tunnel {main_acvpn_gre_tun} remote '{main_acvpn_gre_remote}'
set interfaces tunnel {main_acvpn_gre_tun} source-address '{main_acvpn_vtun_local}'

# 主 US 隧道
set interfaces tunnel {main_us_tun} address '{main_us_gre_ce_ip}/30'
set interfaces tunnel {main_us_tun} description 'MAIN {main_us_pe}'
set interfaces tunnel {main_us_tun} encapsulation 'gre'
set interfaces tunnel {main_us_tun} ip adjust-mss '1300'
set interfaces tunnel {main_us_tun} mtu '1452'
set interfaces tunnel {main_us_tun} parameters ip ttl '255'
set interfaces tunnel {main_us_tun} remote '{main_us_pe_docking}'
set interfaces tunnel {main_us_tun} source-address '{ce_docking}'

# 备 ACVPN OpenVPN
set interfaces openvpn {bk_acvpn_vtun_id} description 'BK {bk_acvpn_vtun_pe} {bk_acvpn_vtun_id}'
set interfaces openvpn {bk_acvpn_vtun_id} local-address {bk_acvpn_vtun_local} subnet-mask '255.255.255.252'
set interfaces openvpn {bk_acvpn_vtun_id} mode 'site-to-site'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'nobind'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'tun-mtu 1500'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'fragment 1300'
set interfaces openvpn {bk_acvpn_vtun_id} openvpn-option 'providers legacy default'
set interfaces openvpn {bk_acvpn_vtun_id} persistent-tunnel
set interfaces openvpn {bk_acvpn_vtun_id} protocol 'udp'
set interfaces openvpn {bk_acvpn_vtun_id} remote-address '{bk_acvpn_vtun_remote}'
set interfaces openvpn {bk_acvpn_vtun_id} remote-host '{bk_acvpn_vtun_docking}'
set interfaces openvpn {bk_acvpn_vtun_id} remote-port '{bk_acvpn_vtun_port}'
set interfaces openvpn {bk_acvpn_vtun_id} shared-secret-key 'openvpn_secret'

# 备 ACVPN GRE 隧道
set interfaces tunnel {bk_acvpn_gre_tun} address '{bk_acvpn_gre_ce_ip}/30'
set interfaces tunnel {bk_acvpn_gre_tun} description 'BK {bk_acvpn_gre_pe}'
set interfaces tunnel {bk_acvpn_gre_tun} encapsulation 'gre'
set interfaces tunnel {bk_acvpn_gre_tun} ip adjust-mss '1300'
set interfaces tunnel {bk_acvpn_gre_tun} mtu '1476'
set interfaces tunnel {bk_acvpn_gre_tun} parameters ip ttl '255'
set interfaces tunnel {bk_acvpn_gre_tun} remote '{bk_acvpn_gre_remote}'
set interfaces tunnel {bk_acvpn_gre_tun} source-address '{bk_acvpn_vtun_local}'

# 备 US 隧道
set interfaces tunnel {bk_us_tun} address '{bk_us_gre_ce_ip}/30'
set interfaces tunnel {bk_us_tun} description 'BK {bk_us_pe}'
set interfaces tunnel {bk_us_tun} encapsulation 'gre'
set interfaces tunnel {bk_us_tun} ip adjust-mss '1300'
set interfaces tunnel {bk_us_tun} mtu '1452'
set interfaces tunnel {bk_us_tun} parameters ip ttl '255'
set interfaces tunnel {bk_us_tun} remote '{bk_us_pe_docking}'
set interfaces tunnel {bk_us_tun} source-address '{ce_docking}'

# NAT 配置
{lan_net_block}
set nat source rule 50 outbound-interface name '{wan_if}'
set nat source rule 50 source group network-group 'LAN-NET'
set nat source rule 50 translation address 'masquerade'
{overseas_nat_block}

# DNS-NET 地址组（配合 DNS 进程使用）
set firewall group address-group DNS-NET address {dns_ip1}
set firewall group address-group DNS-NET address {dns_ip2}
set nat source rule 5000 destination group address-group DNS-NET
set nat source rule 5000 outbound-interface name '{main_us_tun}'
set nat source rule 5000 translation address '{main_us_nat_ip}'
set nat source rule 6000 destination group address-group DNS-NET
set nat source rule 6000 outbound-interface name '{bk_us_tun}'
set nat source rule 6000 translation address '{bk_us_nat_ip}'

# BGP Server 路由
{us_bgp_routes}

# BGP 配置
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
set policy community-list 91 rule 10 action 'permit'
set policy community-list 91 rule 10 description 'to_Microsoft'
set policy community-list 91 rule 10 regex '65000:9009'

set policy route-map bgp-from--RSVR rule 100 action 'permit'
set policy route-map bgp-from--RSVR rule 100 description 'to_hk'
set policy route-map bgp-from--RSVR rule 100 match community community-list '80'
set policy route-map bgp-from--RSVR rule 100 set ip-next-hop '{main_us_pe_ip}'
set policy route-map bgp-from--RSVR rule 100 set local-preference '200'
set policy route-map bgp-from--RSVR rule 200 action 'permit'
set policy route-map bgp-from--RSVR rule 200 description 'to_ct'
set policy route-map bgp-from--RSVR rule 200 match community community-list '81'
set policy route-map bgp-from--RSVR rule 200 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 200 set local-preference '200'
set policy route-map bgp-from--RSVR rule 300 action 'permit'
set policy route-map bgp-from--RSVR rule 300 description 'to_cnc'
set policy route-map bgp-from--RSVR rule 300 match community community-list '82'
set policy route-map bgp-from--RSVR rule 300 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 300 set local-preference '200'
set policy route-map bgp-from--RSVR rule 400 action 'permit'
set policy route-map bgp-from--RSVR rule 400 description 'to_cn_other'
set policy route-map bgp-from--RSVR rule 400 match community community-list '83'
set policy route-map bgp-from--RSVR rule 400 set ip-next-hop '1.1.1.1'
set policy route-map bgp-from--RSVR rule 400 set local-preference '200'
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

set policy route-map deny-any-out rule 1000 action 'deny'
set policy route-map deny-any-out rule 1000 description 'to_bgpserver'

set protocols bgp neighbor {main_us_bgp1} peer-group 'RSVR'
set protocols bgp neighbor {main_us_bgp2} peer-group 'RSVR'
set protocols bgp neighbor {bk_us_bgp1} peer-group 'RSVR2'
set protocols bgp neighbor {bk_us_bgp2} peer-group 'RSVR2'
set protocols bgp parameters router-id '{main_us_nat_ip}'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR address-family ipv4-unicast route-map import 'bgp-from--RSVR'
set protocols bgp peer-group RSVR address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR remote-as '65000'
set protocols bgp peer-group RSVR update-source '{main_us_nat_ip}'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map export 'deny-any-out'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map import 'bgp-from--RSVR2'
set protocols bgp peer-group RSVR2 address-family ipv4-unicast soft-reconfiguration inbound
set protocols bgp peer-group RSVR2 remote-as '65000'
set protocols bgp peer-group RSVR2 update-source '{bk_us_nat_ip}'
set protocols bgp system-as '65000'
set protocols bgp timers holdtime '15'
set protocols bgp timers keepalive '5'

# 基本路由配置
{default_route_block}

# 主线监控
set protocols static route 114.113.245.99/32 next-hop {main_acvpn_gre_pe_ip}

# 备线监控
set protocols static route 114.113.245.100/32 next-hop {bk_acvpn_gre_pe_ip}

# 跳板机路由 & Track 配置（failover2 替代 track）
set protocols failover2 track tomain source-address '{main_acvpn_gre_ce_ip}'
set protocols failover2 track tomain target '{main_acvpn_gre_pe_ip}'
set protocols failover2 track tomain type 'icmp'
set protocols failover2 route 192.168.55.250/32 next-hop {main_acvpn_gre_pe_ip} track 'tomain'
set protocols static route 192.168.55.250/32 next-hop {bk_acvpn_gre_pe_ip} distance '10'

# 静态路由（隧道路由）
set protocols static route {main_acvpn_vtun_docking}/32 next-hop 1.1.1.1
set protocols static route {bk_acvpn_vtun_docking}/32 next-hop 1.1.1.1
set protocols static route {main_us_pe_docking}/32 next-hop {main_acvpn_gre_pe_ip}
set protocols static route {bk_us_pe_docking}/32 next-hop {bk_acvpn_gre_pe_ip}
set protocols static route {main_acvpn_gre_remote}/32 next-hop {main_acvpn_vtun_remote}
set protocols static route {bk_acvpn_gre_remote}/32 next-hop {bk_acvpn_vtun_remote}

# 本地策略路由（US 出口源地址分流）
set policy local-route rule 1001 set table '101'
set policy local-route rule 1001 source address '{main_us_gre_ce_ip}'
set protocols static table 101 route 0.0.0.0/0 next-hop {main_us_pe_ip}
set policy local-route rule 1002 set table '102'
set policy local-route rule 1002 source address '{bk_us_gre_ce_ip}'
set protocols static table 102 route 0.0.0.0/0 next-hop {bk_us_pe_ip}

# 回程路由
{return_routes_block}

# DNS 配置
set service file-sync task 1 local '/config/user-data/cn.txt'
set service file-sync task 1 remote 'http://183.56.161.82:1909/f32x/domainlist/cn_domainlist.last'
set service file-sync task 2 local '/config/user-data/oversea.txt'
set service file-sync task 2 remote 'http://183.56.161.82:1909/f32x/domainlist/oversea_domainlist.last'

set service dns forwarding allow-from '0.0.0.0/0'
set service dns forwarding cache-size '10000'
set service dns forwarding dnssec 'off'
set service dns forwarding domain-list CN file '/config/user-data/cn.txt'
set service dns forwarding domain-list CN name-server 223.5.5.5
set service dns forwarding domain-list CN name-server 223.6.6.6
set service dns forwarding domain-list CN recursion-desired
set service dns forwarding domain-list HK file '/config/user-data/oversea.txt'
set service dns forwarding domain-list HK name-server 8.8.4.4
set service dns forwarding domain-list HK name-server 8.8.8.8
set service dns forwarding domain-list HK recursion-desired
set service dns forwarding listen-address '0.0.0.0'
set service dns forwarding name-server 8.8.4.4
set service dns forwarding name-server 8.8.8.8

# DHCP 服务
{dhcp_block}"""

TEMPLATE_EPOCH5_FLINK = (
    "# [5.0 ER 飞连 — 开发中]\n"
    "# 模板待实现\n"
)

TEMPLATE_EPOCH5_NEW_EXIT = """\
set interfaces dummy dum{ER_NE_MAIN_DUM_START} address '{main_dum_first_ip}/32'
set interfaces dummy dum{ER_NE_MAIN_DUM_START} description 'USIP-Main:{main_dum_first_ip}-{main_dum_first_remote}'
{ER_NE_MAIN_DUM_BLOCK}
set interfaces tunnel {main_tun} address '{main_tun_addr}'
set interfaces tunnel {main_tun} description 'main-{main_pe}-{main_tun_num}'
set interfaces tunnel {main_tun} encapsulation 'gre'
set interfaces tunnel {main_tun} ip adjust-mss '{main_mss}'
set interfaces tunnel {main_tun} mtu '{main_mtu}'
set interfaces tunnel {main_tun} remote '{main_pe_docking}'
set interfaces tunnel {main_tun} source-address '{main_ce_docking}'
{ER_NE_BK_BLOCK}
set protocols static route {main_pe_docking}/32 next-hop {ER_NE_MAIN_PE_NH_DEFAULT}
{ER_NE_NAT_HEADER_BLOCK}{ER_NE_NAT_BLOCK}{ER_NE_FNET_BLOCK}"""

TEMPLATE_EPOCH5_FLINK = """\
set protocols failover2 track tomain source-address '{ER_FL_FAILOVER_SRC}'
set protocols failover2 track tomain target '{ER_FL_MAIN_NH_DEFAULT}'
set protocols failover2 track tomain type 'icmp'

set protocols failover2 route {route1} next-hop {ER_FL_MAIN_NH_DEFAULT} track 'tomain'
set protocols failover2 route {route2} next-hop {ER_FL_MAIN_NH_DEFAULT} track 'tomain'
set protocols failover2 route {route3} next-hop {ER_FL_MAIN_NH_DEFAULT} track 'tomain'

set protocols static route {route1} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 10
set protocols static route {route2} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 10
set protocols static route {route3} next-hop {ER_FL_BACKUP_NH_DEFAULT} distance 10

set firewall group network-group LAN-NET network {route1}
set firewall group network-group LAN-NET network {route2}
set firewall group network-group LAN-NET network {route3}"""

TEMPLATE_EPOCH5_DOMAIN_SPLIT = """# ER 5.0 域名分流 · VyOS set 语法
# --- 写入域名列表（shell）---
sudo tee /opt/{ER5_DS_DOMAINLIST_COMPUTED}.txt >/dev/null <<'EOF'
{ER5_DS_DOMAINS_DEFAULT}
EOF
sudo chmod 777 /opt/{ER5_DS_DOMAINLIST_COMPUTED}.txt

set firewall group address-group {ER5_DS_ADDR_GROUP_DEFAULT}

set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} address-group '{ER5_DS_ADDR_GROUP_DEFAULT}'
set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} file '/opt/{ER5_DS_DOMAINLIST_COMPUTED}.txt'
set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} name-server {ER5_DS_DNS1_DEFAULT}
set service dns forwarding domain-list {ER5_DS_DOMAINLIST_COMPUTED} recursion-desired
{ER5_DS_OPT_DNS2_LINE}
{ER5_DS_OPT_POLICY_ROUTE_BLOCK}set protocols static route {ER5_DS_TABLE_NH_PRIMARY_DEFAULT}/32 next-hop {ER5_DS_STATIC32_PRIMARY_NH_DEFAULT}{ER5_DS_OPT_TRACK_SUFFIX}
{ER5_DS_OPT_S32BAK_LINE}
{ER5_DS_OPT_FNET_BLOCK}"""

ER5_DS_DOMAINS_DEFAULT = "google.com"
ER5_DS_ADDR_GROUP_DEFAULT = "to-US"
ER5_DS_RULE_NUM_DEFAULT = "100"
ER5_DS_TABLE_NUM_DEFAULT = "139"
ER5_DS_SOURCE_CIDR_DEFAULT = "192.168.5.0/24"
ER5_DS_DNS1_DEFAULT = "209.244.0.3"
ER5_DS_DNS2_DEFAULT = ""
ER5_DS_ETH_DEFAULT = "eth0"
ER5_DS_TABLE_NH_PRIMARY_DEFAULT = "2.2.2.2"
ER5_DS_TRACK_NAME_DEFAULT = "tooutbound1"
ER5_DS_STATIC32_PRIMARY_NH_DEFAULT = "10.22.15.185"
ER5_DS_STATIC32_BACKUP_NH_DEFAULT = "10.22.24.157"
ER5_DS_EXIT_TUNNEL_DEFAULT = ""
ER5_DS_EXIT_SNAT_IP_DEFAULT = ""
ER5_DS_FNET_NAT_RULE_DEFAULT = ""
ER5_DS_FNET_PROBE_DEFAULT = "100.100.100.1"
ER5_DS_FAILOVER_SRC_DEFAULT = ""

def _er_ds_normalize_addr_group(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    m = re.match(r"(?i)address-group\s*:\s*(.+)$", s)
    if m:
        return m.group(1).strip()
    return s


def _er_ds_domainlist_name(addr_group: str) -> str:
    ag = _er_ds_normalize_addr_group(addr_group or "")
    return ("A" + ag) if ag else ""


def _er_ds_policy_route_name(addr_group: str) -> str:
    ag = _er_ds_normalize_addr_group(addr_group or "")
    return "LAN-MAP-" + ag


def _er_ds_track_suffix(track_name: str) -> str:
    t = (track_name or "").strip()
    return f" track {t}" if t else ""




# =====================================================================
# 5.0 新增出口 — 解析器（数据头格式与 4.0 完全一致）
# =====================================================================

def _er_ne_nat_source_normalized(raw: str):
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return str(ipaddress.ip_network(s, strict=False))
    except ValueError:
        return None


def _parse_oversea_pairs_5(raw_blob: str):
    pairs = re.findall(
        r"(\d{1,3}(?:\.\d{1,3}){3})\s*[-–—~]\s*(\d{1,3}(?:\.\d{1,3}){3})",
        raw_blob or "",
    )
    if pairs:
        return pairs
    ips = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", raw_blob or "")
    return [(ip, ip) for ip in ips]


def parse_epoch5_new_exit_blocks(raw_text: str):
    """解析 5.0 新增出口数据头，返回 ({"main":{}, "bk":{}}, err_msg_or_none)。
    支持单线输入——仅 1 个 LineID block 时视为主线。"""

    blocks = [b.strip() for b in re.split(r"(?=LineID\s*[:：])", raw_text or "", flags=re.IGNORECASE) if b.strip()]
    if not blocks:
        return None, "未找到任何 LineID 数据块"

    parsed = {}
    for block in blocks:
        line_id = _get(r"LineID\s*[:：]\s*(\S+)", block)
        if not line_id:
            continue
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
            block, re.IGNORECASE | re.DOTALL,
        )
        oversea_blob = oversea_blob_m.group(1) if oversea_blob_m else ""
        oversea_pairs = _parse_oversea_pairs_5(oversea_blob)

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
    return parsed, None


def _build_epoch5_ne_dum_block(parsed: dict, init_cfg: dict) -> str:
    """生成 5.0 新增出口 dummy 接口块（海外出口 IP LoopBack）。"""
    m = parsed.get("main") or {}
    b = parsed.get("bk") or {}
    m_pairs = list(m.get("oversea_pairs") or [])
    b_pairs = list(b.get("oversea_pairs") or [])
    md = int(init_cfg.get("main_dum_start", 300))
    bd = int(init_cfg.get("bk_dum_start", 400))

    lines = []
    for i, (left, right) in enumerate(m_pairs):
        if i == 0:
            continue  # first IP is handled inline in template
        lines.extend([
            f"set interfaces dummy dum{md + i} address '{left.strip()}/32'",
            f"set interfaces dummy dum{md + i} description 'USIP-Main:{left.strip()}-{right.strip()}'",
        ])

    bk_block_lines = []
    for i, (left, right) in enumerate(b_pairs):
        bk_block_lines.extend([
            f"set interfaces dummy dum{bd + i} address '{left.strip()}/32'",
            f"set interfaces dummy dum{bd + i} description 'USIP-BK:{left.strip()}-{right.strip()}'",
        ])

    if bk_block_lines:
        lines.append("")
        lines.extend(bk_block_lines)
    return "\n".join(lines)


def _epoch5_ne_nat_group_name(init_cfg: dict) -> str:
    return str(init_cfg.get("nat_group_name", "")).strip()


def _epoch5_ne_resolved_fnet_tunnel(parsed: dict, init_cfg: dict) -> str:
    tunnel = str(init_cfg.get("fnet_exit_tunnel", "")).strip()
    m = parsed.get("main") or {}
    main_tun = str(m.get("tun") or "").strip()
    if tunnel in ("", "tun"):
        return main_tun
    return tunnel


def _build_epoch5_ne_nat_block(parsed: dict, init_cfg: dict) -> str:
    """生成 5.0 新增出口 NAT 规则（set nat source rule 格式）。"""
    src = _er_ne_nat_source_normalized(init_cfg.get("nat_source_cidr", ""))
    if not src:
        return ""

    nat_group = _epoch5_ne_nat_group_name(init_cfg)
    if not nat_group:
        return ""

    mr = str(init_cfg.get("main_nat_rule", "")).strip()
    br = str(init_cfg.get("bk_nat_rule", "")).strip()
    if not mr.isdigit() or not br.isdigit():
        return ""

    im = int(mr); ib = int(br)
    m = parsed.get("main") or {}
    b = parsed.get("bk") or {}
    m_pairs = list(m.get("oversea_pairs") or [])
    b_pairs = list(b.get("oversea_pairs") or [])
    if not m_pairs:
        return ""

    mt = (m.get("tun") or "").strip()
    bt = (b.get("tun") or "").strip() if b else ""
    lines = [
        f"set firewall group network-group {nat_group} network '{src}'",
        "",
    ]
    for i, (left, _right) in enumerate(m_pairs):
        tr = (left or "").strip()
        if not tr:
            return ""
        rid = im + i
        lines.extend([
            f"set nat source rule {rid} outbound-interface name '{mt}'",
            f"set nat source rule {rid} source group network-group '{nat_group}'",
            f"set nat source rule {rid} translation address '{tr}'",
            "",
        ])
    if b_pairs and bt:
        for i, (left, _right) in enumerate(b_pairs):
            tr = (left or "").strip()
            if not tr:
                return ""
            rid = ib + i
            lines.extend([
                f"set nat source rule {rid} outbound-interface name '{bt}'",
                f"set nat source rule {rid} source group network-group '{nat_group}'",
                f"set nat source rule {rid} translation address '{tr}'",
                "",
            ])
    return "\n".join(lines).rstrip()


def _build_epoch5_ne_nat_header_block(parsed: dict, init_cfg: dict) -> str:
    """NAT 规则数量说明块。"""
    src = _er_ne_nat_source_normalized(init_cfg.get("nat_source_cidr", ""))
    if not src:
        return ""
    m = parsed.get("main") or {}
    b = parsed.get("bk") or {}
    m_pairs = list(m.get("oversea_pairs") or [])
    b_pairs = list(b.get("oversea_pairs") or [])
    mr = str(init_cfg.get("main_nat_rule", "")).strip()
    br = str(init_cfg.get("bk_nat_rule", "")).strip()
    if not mr.isdigit() or not br.isdigit():
        return ""
    nat_group = _epoch5_ne_nat_group_name(init_cfg)
    if not nat_group:
        return ""
    nm, nb = len(m_pairs), len(b_pairs)
    return f"# {nat_group} 源网段: {src}\n# NAT rule: 主线自 {mr} 起共 {nm} 条；备线自 {br} 起共 {nb} 条\n"


def _build_epoch5_ne_fnet_block(parsed: dict, init_cfg: dict) -> str:
    """5.0 新增出口 FNET whitelist。双线时要求 100.100 初始化参数齐全。"""
    if "bk" not in parsed or not parsed.get("bk"):
        return ""
    probe = str(init_cfg.get("fnet_probe", "")).strip()
    tunnel = _epoch5_ne_resolved_fnet_tunnel(parsed, init_cfg)
    nat_rule = str(init_cfg.get("fnet_nat_rule", "")).strip()
    if not (probe and tunnel and nat_rule and nat_rule.isdigit()):
        return ""

    m = parsed.get("main")
    main_left = (list(m.get("oversea_pairs") or [])[0][0] if m else "").strip()
    if not main_left:
        return ""

    main_nh = str(init_cfg.get("main_pe_next_hop", "")).strip()
    failover_src = _derive_epoch5_failover_source_from_main_next_hop(main_nh)
    probe_net = str(ipaddress.ip_network(f"{probe}/24", strict=False))
    lines = [
        "",
        f"set firewall group network-group GROUP-FNET-Whitelist network '{probe_net}'",
        "",
        f"set protocols failover2 track tooutbound1 source-address '{failover_src}'",
        f"set protocols failover2 track tooutbound1 target '{main_nh}'",
        "set protocols failover2 track tooutbound1 type 'icmp'",
        f"set protocols failover2 route {probe_net} next-hop {main_nh} track 'tooutbound1'",
        "",
        f"set nat source rule {nat_rule} outbound-interface name '{tunnel}'",
        f"set nat source rule {nat_rule} destination address {probe}",
        f"set nat source rule {nat_rule} translation address '{main_left}'",
    ]
    return "\n".join(lines)


def epoch5_new_exit_nat_rule_span_error(parsed: dict, init_cfg: dict) -> str | None:
    """Validate 5.0 new-exit NAT rule ranges and the 100.100 NAT rule."""
    if "bk" not in parsed or not parsed.get("bk"):
        return None

    ranges = []
    if _er_ne_nat_source_normalized(init_cfg.get("nat_source_cidr", "")):
        mr = str(init_cfg.get("main_nat_rule", "")).strip()
        br = str(init_cfg.get("bk_nat_rule", "")).strip()
        if mr.isdigit() and br.isdigit():
            im, ib = int(mr), int(br)
            nm = len(list((parsed.get("main") or {}).get("oversea_pairs") or []))
            nb = len(list((parsed.get("bk") or {}).get("oversea_pairs") or []))
            if nm > 0:
                ranges.append(("主线", im, im + nm - 1))
            if nb > 0:
                ranges.append(("备线", ib, ib + nb - 1))

    fnet_probe = str(init_cfg.get("fnet_probe", "")).strip()
    fnet_tunnel = _epoch5_ne_resolved_fnet_tunnel(parsed, init_cfg)
    fnet_nat_rule = str(init_cfg.get("fnet_nat_rule", "")).strip()
    if not fnet_probe:
        return "100.100 探测 IP 必须初始化"
    if not fnet_tunnel:
        return "100.100 NAT 出口 Tunnel 未初始化，且数据头未解析到主线 TUNNEL"
    if not fnet_nat_rule:
        return "100.100 NAT Rule 号必须初始化"
    if not fnet_nat_rule.isdigit():
        return "100.100 NAT Rule 号必须是数字"
    ranges.append(("100.100", int(fnet_nat_rule), int(fnet_nat_rule)))

    for name, start, end in ranges:
        if start < 1 or end > 999999:
            return f"{name} NAT rule 超出 1～999999：[{start},{end}]"

    for i, (left_name, left_start, left_end) in enumerate(ranges):
        for right_name, right_start, right_end in ranges[i + 1:]:
            if not (left_end < right_start or right_end < left_start):
                return (
                    f"NAT rule 区间重叠：{left_name} [{left_start},{left_end}]，"
                    f"{right_name} [{right_start},{right_end}]，请调整 rule 号"
                )
    return None


def build_epoch5_new_exit_format_dict(parsed: dict, init_cfg: dict) -> dict:
    """组装 5.0 新增出口 TEMPLATE_EPOCH5_NEW_EXIT.format(**d) 所需的 dict。"""
    m = parsed.get("main", {})
    b = parsed.get("bk", {})
    has_bk = bool(b)

    m_pairs = list(m.get("oversea_pairs") or [])
    b_pairs = list(b.get("oversea_pairs") or [])

    md = int(init_cfg.get("main_dum_start", 300))
    bd = int(init_cfg.get("bk_dum_start", 400))
    main_mtu = "1400"
    bk_mtu = "1400"
    main_mss = "1300"
    bk_mss = "1300"

    main_first_left = (m_pairs[0][0] if m_pairs else "").strip()
    main_first_right = (m_pairs[0][1] if m_pairs else "").strip()
    bk_first_left = (b_pairs[0][0] if b_pairs else "").strip() if has_bk else ""
    bk_first_right = (b_pairs[0][1] if b_pairs else "").strip() if has_bk else ""

    main_tun = (m.get("tun") or "").strip()
    main_tun_num = main_tun.replace("tun", "") if main_tun.startswith("tun") else main_tun
    bk_tun = (b.get("tun") or "").strip() if has_bk else ""
    bk_tun_num = bk_tun.replace("tun", "") if bk_tun.startswith("tun") else bk_tun

    bk_block = ""
    if has_bk:
        bk_block = f"""set interfaces tunnel {bk_tun} address '{b.get("tun_addr", "")}'
set interfaces tunnel {bk_tun} description 'back-{b.get("pe", "")}-{bk_tun_num}'
set interfaces tunnel {bk_tun} encapsulation 'gre'
set interfaces tunnel {bk_tun} ip adjust-mss '{bk_mss}'
set interfaces tunnel {bk_tun} mtu '{bk_mtu}'
set interfaces tunnel {bk_tun} remote '{b.get("pe_docking", "")}'
set interfaces tunnel {bk_tun} source-address '{b.get("ce_docking", "")}'
set protocols static route {b.get("pe_docking", "")}/32 next-hop {init_cfg.get('bk_pe_next_hop', '192.168.1.2')}
"""

    return {
        "ER_NE_MAIN_PE_NH_DEFAULT": str(init_cfg.get("main_pe_next_hop", "192.168.1.1")),
        "ER_NE_MAIN_DUM_START": str(md),
        "main_tun": main_tun,
        "main_tun_addr": m.get("tun_addr", ""),
        "main_pe": m.get("pe", ""),
        "main_tun_num": main_tun_num,
        "main_mtu": main_mtu,
        "main_mss": main_mss,
        "main_pe_docking": m.get("pe_docking", ""),
        "main_ce_docking": m.get("ce_docking", ""),
        "main_dum_first_ip": main_first_left,
        "main_dum_first_remote": main_first_right,
        "bk_dum_first_ip": bk_first_left,
        "bk_dum_first_remote": bk_first_right,
        "ER_NE_MAIN_DUM_BLOCK": _build_epoch5_ne_dum_block(parsed, init_cfg),
        "ER_NE_BK_BLOCK": bk_block,
        "ER_NE_NAT_HEADER_BLOCK": _build_epoch5_ne_nat_header_block(parsed, init_cfg),
        "ER_NE_NAT_BLOCK": _build_epoch5_ne_nat_block(parsed, init_cfg),
        "ER_NE_FNET_BLOCK": _build_epoch5_ne_fnet_block(parsed, init_cfg),
    }


# =====================================================================
# 5.0 飞连 — 解析器 + builder（数据头格式与 4.0 一致）
# =====================================================================

def parse_epoch5_flink_headers(raw_text: str):
    """解析 5.0 飞连数据头，返回 ([(name, cidr), ...], err_msg_or_none)。
    格式: PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.10.216/29"""
    import ipaddress as _ipaddress
    routes = []
    for ln in (raw_text or "").splitlines():
        line = ln.strip()
        if not line:
            continue
        pe_m = re.search(r"PE[：:]\s*(\S+)", line)
        fpe_m = re.search(r"FPE[：:]\s*(\S+)", line)
        ip_m = re.search(r"预留IP[：:]\s*(\S+)", line)
        if ip_m:
            cidr = ip_m.group(1)
            pe_val = pe_m.group(1) if pe_m else ""
            fpe_val = fpe_m.group(1) if fpe_m else ""
            name = f"{pe_val} / {fpe_val}".strip(" /") or "预留IP"
        elif ":" in line or "：" in line:
            name, cidr = re.split(r"[：:]", line, 1)
            name = name.strip() or "预留IP"
            cidr = cidr.strip()
        else:
            name = "预留IP"
            cidr = line
        if not cidr:
            return [], f"数据头格式错误：{line}"
        if "/" not in cidr:
            return [], f"CIDR 缺少掩码：{cidr}"
        try:
            cidr_norm = str(_ipaddress.ip_network(cidr, strict=False))
        except ValueError as e:
            return [], f"CIDR 非法：{cidr} ({e})"
        routes.append((name, cidr_norm))
    if not routes:
        return [], "请先填写飞连数据头（至少 1 行）"
    return routes, None


def _derive_epoch5_failover_source_from_main_next_hop(main_nh: str) -> str:
    """主下一跳为 /30 奇数位，failover source 使用同 /30 偶数位。"""
    try:
        ip = ipaddress.ip_address(str(main_nh).strip())
    except ValueError as e:
        raise ValueError(f"主回程下一跳必须是合法 IPv4 地址：{main_nh}") from e
    net = ipaddress.ip_network(f"{ip}/30", strict=False)
    hosts = list(net.hosts())
    if len(hosts) != 2 or ip != hosts[0]:
        raise ValueError(f"主回程下一跳必须是 /30 的奇数位地址：{main_nh}")
    return str(hosts[1])


def _build_epoch5_flink_format_dict(routes, main_nh: str, backup_nh: str) -> dict:
    cidrs = [cidr for _name, cidr in routes]
    names = [name for name, _cidr in routes]
    while len(cidrs) < 3:
        cidrs.append("0.0.0.0/32")
        names.append("")
    failover_src = _derive_epoch5_failover_source_from_main_next_hop(main_nh)
    return {
        "ER_FL_FAILOVER_SRC": failover_src,
        "ER_FL_MAIN_NH_DEFAULT": main_nh,
        "ER_FL_BACKUP_NH_DEFAULT": backup_nh,
        "route1": cidrs[0], "name1": names[0],
        "route2": cidrs[1], "name2": names[1],
        "route3": cidrs[2], "name3": names[2],
    }


def build_epoch5_flink_config(routes, main_nh: str, backup_nh: str):
    """按 5.0 VyOS failover2 语法生成飞连配置。"""
    failover_src = _derive_epoch5_failover_source_from_main_next_hop(main_nh)
    lines = [
        f"set protocols failover2 track tomain source-address '{failover_src}'",
        f"set protocols failover2 track tomain target '{main_nh}'",
        "set protocols failover2 track tomain type 'icmp'",
        "",
    ]
    for _name, cidr in routes:
        lines.append(f"set protocols failover2 route {cidr} next-hop {main_nh} track 'tomain'")
    lines.append("")
    for _name, cidr in routes:
        lines.append(f"set protocols static route {cidr} next-hop {backup_nh} distance 10")
    lines.append("")
    for _name, cidr in routes:
        lines.append(f"set firewall group network-group LAN-NET network {cidr}")
    return "\n".join(lines)


# 5.0 新增出口 初始化参数默认值
ER5_NE_MAIN_PE_NH_DEFAULT = "10.1.1.1"
ER5_NE_BK_PE_NH_DEFAULT = "10.2.1.1"
ER5_NE_MAIN_DUM_DEFAULT = "300"
ER5_NE_BK_DUM_DEFAULT = "400"
ER5_NE_MAIN_NAT_RULE_DEFAULT = "1001"
ER5_NE_BK_NAT_RULE_DEFAULT = "2001"
ER5_NE_NAT_GROUP_DEFAULT = "LAN-NET1"
ER5_NE_NAT_SOURCE_CIDR_DEFAULT = "192.168.0.0/24"
ER5_NE_FNET_PROBE_DEFAULT = "100.100.100.1"
ER5_NE_FNET_EXIT_TUNNEL_DEFAULT = "tun"
ER5_NE_FNET_NAT_RULE_DEFAULT = ""

# 5.0 飞连 初始化参数默认值
ER5_FL_MAIN_NH_DEFAULT = "10.1.1.1"
ER5_FL_BACKUP_NH_DEFAULT = "10.2.1.1"

# 5.0 新增出口 示例数据
ER5_NEW_EXIT_EXAMPLE = (
    "LineID:609430B5\n"
    "PE： lax1-natpe7\n"
    "WANIP: 10.22.113.36/30\n"
    "TUNNEL: tun2209\n"
    "PE Docking：192.168.215.12\n"
    "CE Docking：: 10.22.242.223\n"
    "BGPSERVER IP：103.252.19.25,43.229.117.226\n"
    "海外出口ip：\n"
    "10.60.52.46-8.3.6.111\n"
    "\n"
    "LineID:609430B6\n"
    "PE： sjc1-natpe3\n"
    "WANIP: 10.22.115.28/30\n"
    "TUNNEL: tun1080\n"
    "PE Docking：10.33.54.118\n"
    "CE Docking：: 10.22.242.223\n"
    "BGPSERVER IP：103.252.19.99,43.229.119.251\n"
    "海外出口ip：\n"
    "10.60.79.99-172.16.212.58\n"
)

# 5.0 飞连 示例数据
ER5_FLINK_EXAMPLE = (
    "PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.10.216/29\n"
    "PE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.10.216/29\n"
    "PE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.10.216/29\n"
)


# =====================================================================
# 解析器 — HK（与 4.0 完全相同的数据头格式）
# =====================================================================
def parse_epoch5_hk_headers(raw_text):
    """解析 5.0 HK 数据头，提取 MAIN/BACKUP 字段。
   数据头格式与 4.0 完全一致。
   返回 dict，键名与 4.0 兼容 + 5.0 新增字段。"""
    result = {k: "" for k in [
        "main_pe", "main_tunnel", "main_tunnel_port",
        "main_wanip", "main_wanip_remote", "main_wanip_local",
        "main_docking", "ce_loip", "hkip",
        "main_bgp1", "main_bgp2",
        "bk_pe", "bk_tunnel", "bk_tunnel_port",
        "bk_wanip", "bk_wanip_remote", "bk_wanip_local",
        "bk_docking", "bk_bgp1", "bk_bgp2",
        "hostname", "return_routes_block",
    ]}
    result["hkip_nat_list"] = []

    blocks = re.split(
        r'(?=(?:MAIN|BACKUP|主|备)\s*\n|(?:MAIN|BACKUP)\s*[：:])',
        raw_text, flags=re.IGNORECASE
    )

    def parse_one(block, prefix):
        pe = _get(r'(?:主PE|PE)\s*[：:]\s*(.+)', block)
        if pe:
            result[f"{prefix}_pe"] = pe.strip()
        tun_raw = _get(r'TUNNEL\s*[：:]\s*(\S+)', block)
        if tun_raw:
            tun = _normalize_vtun(tun_raw)
            result[f"{prefix}_tunnel"] = tun
            result[f"{prefix}_tunnel_port"] = _vtun_port(tun)
        wanip = _get(r'WANIP\s*[：:]\s*([\d./]+)', block)
        if wanip:
            result[f"{prefix}_wanip"] = wanip
            pe_ip, ce_ip = wanip_hosts(wanip)
            result[f"{prefix}_wanip_remote"] = pe_ip
            result[f"{prefix}_wanip_local"] = ce_ip
        docking = _get(r'Docking\s*[：:]\s*([\d.]+)', block)
        if docking:
            result[f"{prefix}_docking"] = docking
        loip = _get(r'CE\s*LOIP\s*[：:]\s*([\d.]+)', block)
        if loip:
            result["ce_loip"] = loip
        hkip_m = re.search(
            r'HKIP\s*[：:]\s*(.*?)(?=\n[A-Za-z一-鿿]|\Z)',
            block, re.IGNORECASE | re.DOTALL
        )
        if hkip_m:
            hkip_raw = hkip_m.group(1)
            pairs = re.findall(
                r'(\d{1,3}(?:\.\d{1,3}){3})\s*(?:-->|-)\s*\d{1,3}(?:\.\d{1,3}){3}',
                hkip_raw
            )
            nat_ips = pairs if pairs else re.findall(
                r'\d{1,3}(?:\.\d{1,3}){3}', hkip_raw
            )
            if nat_ips:
                result["hkip"] = nat_ips[0]
                result["hkip_nat_list"] = nat_ips
        bgp_raw = _get(r'BGPSERVER\s*IP\s*[：:]\s*(.+)', block)
        if bgp_raw:
            bgps = [
                ip.strip() for ip in re.split(r'[,，\s]+', bgp_raw)
                if re.match(r'^\d+\.\d+', ip.strip())
            ]
            result[f"{prefix}_bgp1"] = bgps[0] if len(bgps) > 0 else ""
            result[f"{prefix}_bgp2"] = bgps[1] if len(bgps) > 1 else ""

    for block in blocks:
        bu = block.strip()
        if re.match(r'(MAIN|主)', bu, re.IGNORECASE):
            parse_one(bu, "main")
        elif re.match(r'(BACKUP|备)', bu, re.IGNORECASE):
            parse_one(bu, "bk")

    return result


def _extract_lineid(text):
    m = re.search(r'lineid\s*[：:]\s*(\S+)', text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


# =====================================================================
# Builder — HK（5.0 VyOS 语法输出）
# =====================================================================
def build_epoch5_hk_format_dict(hdr_text):
    """组装与 TEMPLATE_EPOCH5_HK.format(**d) 相同的 dict。
    成功返回 (d, None)；失败返回 (None, (kind, payload))。
    kind: "parse" — 数据头解析/校验失败
    """
    g = globals()

    # ── 1. 解析数据头 ──
    raw = hdr_text.strip()
    if not raw:
        return None, ("parse", "请输入业务数据（MAIN/BACKUP 数据头）")
    d = parse_epoch5_hk_headers(raw)

    # ── 2. 读取网络参数（仅 4.0 兼容字段，从 globals() 读取）──
    wan_eth = str(g.get("DEFAULT_WAN_ETH", "0")).strip() or "0"
    lan_eth = str(g.get("DEFAULT_LAN_ETH", "5")).strip() or "5"
    wan_cidr = str(g.get("DEFAULT_WAN_CIDR", "")).strip()
    lan_cidr = str(g.get("DEFAULT_LAN_CIDR", "")).strip()
    wan_gw = str(g.get("DEFAULT_WAN_GW", "")).strip()
    wan_dhcp = bool(g.get("DEFAULT_WAN_DHCP", False))
    lan_dhcp = bool(g.get("DEFAULT_LAN_DHCP", True))
    bypass = bool(g.get("DEFAULT_BYPASS", False))
    inner_nets_raw = str(g.get("DEFAULT_INNER_NETS", "")).strip()

    # ── 3. 校验必要字段 ──
    if not d.get("main_pe") and not d.get("main_wanip"):
        return None, ("parse", "未找到主线 PE/WANIP 信息，请检查数据头格式")

    # ── 4. 设置基本信息 ──
    hn = d.get("hostname", "").strip()
    if not hn:
        hn = _extract_lineid(raw) or "请填写Hostname"
    d["hostname"] = hn if hn else "请填写Hostname"

    d["wan_if"] = f"eth{wan_eth}" if not wan_eth.startswith("eth") else wan_eth
    d["lan_if"] = f"eth{lan_eth}" if not lan_eth.startswith("eth") else lan_eth
    d["wan_cidr"] = wan_cidr
    d["lan_cidr"] = lan_cidr
    d["wan_gw"] = wan_gw

    # 从 CIDR 提取纯 IP
    lan_ip = ""
    if lan_cidr:
        try:
            lan_ip = str(ipaddress.ip_interface(lan_cidr.strip()).ip)
        except Exception:
            lan_ip = lan_cidr.split("/")[0].strip()
    d["lan_ip"] = lan_ip

    # LAN 接口配置（旁挂模式下跳过）
    if bypass:
        d["lan_if_block"] = "# 旁挂模式 — 跳过 LAN 接口配置"
    else:
        d["lan_if_block"] = (
            f"set interfaces ethernet {d['lan_if']} description LAN\n"
            f"set interfaces ethernet {d['lan_if']} address '{d['lan_cidr']}'"
        )

    # DNS 劫持使用的接口（旁挂时用 WAN 口）
    d["dns_hijack_if"] = d["wan_if"] if bypass else d["lan_if"]

    # PE 描述（用于 OpenVPN description）
    d["main_pe_desc"] = (
        (d.get("main_pe") or "") + " " + (d.get("main_tunnel") or "")
    ).strip()
    d["bk_pe_desc"] = (
        "to " + (d.get("bk_pe") or "") + " " + (d.get("bk_tunnel") or "")
    ).strip()

    # ── 5. 生成 {lan_net_block} ──
    inner_nets = _parse_inner_nets(inner_nets_raw)
    d["inner_nets"] = inner_nets
    d["lan_net_block"] = "\n".join(
        f"set firewall group network-group LAN-NET network '{net}'"
        for net in inner_nets
    )

    # ── 7. 生成 {default_route_block} ──
    if wan_dhcp:
        d["default_route_block"] = (
            "# WAN DHCP 模式 — 不生成默认静态路由"
        )
    else:
        d["default_route_block"] = (
            f"set protocols static route 0.0.0.0/0 next-hop 1.1.1.1 distance '220'\n"
            f"set protocols static route 1.1.1.1/32 next-hop '{wan_gw}'"
        )

    # ── 8. 生成 {pki_block} ──
    if _EPOCH5_PKI_SECRET_KEY:
        d["pki_block"] = (
            f"set pki openvpn shared-secret openvpn_secret key '{_EPOCH5_PKI_SECRET_KEY}'\n"
            f"run import pki openvpn shared-secret openvpn_secret file /opt/pki/openvpn.secret"
        )
    else:
        d["pki_block"] = (
            "# PKI secret key 未配置\n"
            "# run import pki openvpn shared-secret openvpn_secret file /opt/pki/openvpn.secret"
        )

    # ── 9. 生成 {static_route_bk_docking} ──
    bk_docking = d.get("bk_docking", "")
    if bk_docking:
        d["static_route_bk_docking"] = (
            f"set protocols static route {bk_docking}/32 next-hop '{wan_gw}'"
        )
    else:
        d["static_route_bk_docking"] = (
            "# 备线 Docking 未配置 — 无对应静态路由"
        )

    # ── 10. 生成 {track_block} ──
    main_local = d.get("main_wanip_local", "")
    main_remote = d.get("main_wanip_remote", "")
    bk_remote = d.get("bk_wanip_remote", "")

    if main_local and main_remote:
        lines = []
        lines.append(
            f"set protocols failover2 track tomain source-address '{main_local}'"
        )
        lines.append(
            f"set protocols failover2 track tomain target '{main_remote}'"
        )
        lines.append(
            f"set protocols failover2 track tomain type 'icmp'"
        )
        lines.append(
            f"set protocols failover2 route {_EPOCH5_JUMPBOX_IP}/32 "
            f"next-hop {main_remote} track 'tomain'"
        )
        # 次优跳板机路由（走备线）
        lines.append(
            f"set protocols static route {_EPOCH5_JUMPBOX_IP}/32 "
            f"next-hop {bk_remote} distance '10'"
        )
        d["track_block"] = "\n".join(lines)
    else:
        d["track_block"] = (
            "# Track 未配置 — 缺少主线 WANIP 信息"
        )

    # ── 10b. 生成 {return_routes_block} ──
    gen_rr = bool(g.get("DEFAULT_GEN_RETURN_ROUTE", False))
    if gen_rr:
        rr_lines = []
        base_cidr = wan_cidr if bypass else lan_cidr
        gw = wan_gw if bypass else (str(g.get("DEFAULT_LAN_GW", "")).strip() or (lan_cidr.split("/")[0] if lan_cidr else ""))
        outside = _nets_needing_return(base_cidr, inner_nets)
        for net in outside:
            rr_lines.append(f"set protocols static route {net} next-hop {gw}")
        d["return_routes_block"] = "\n".join(rr_lines) if rr_lines else ""
    else:
        d["return_routes_block"] = ""

    # ── 11. 生成 {dhcp_block} ──
    if lan_dhcp and lan_cidr and lan_ip and not bypass:
        try:
            net = ipaddress.ip_network(lan_cidr.strip(), strict=False)
            prefix = net.prefixlen
            network_addr = str(net.network_address)
            hosts = list(net.hosts())
            if hosts:
                d_start = str(hosts[min(9, len(hosts) - 1)])
                d_stop = str(hosts[min(199, len(hosts) - 1)])
            else:
                d_start = d_stop = ""
            prefix_id = str(prefix)

            d["dhcp_block"] = (
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} option default-router '{lan_ip}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} option name-server '{lan_ip}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} range Lan1_range start '{d_start}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} range Lan1_range stop '{d_stop}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} subnet-id '{prefix_id}'"
            )
        except Exception:
            d["dhcp_block"] = (
                "# DHCP 服务器未配置 — LAN CIDR 解析失败"
            )
    else:
        d["dhcp_block"] = (
            "# DHCP 服务器未启用"
        )

    # ── 12. 生成 {bgp_server_routes_block} ──
    bgp_routes = []
    # BGP 服务器路由（主/备分别走对应 next-hop）
    for bgp in [d.get("main_bgp1"), d.get("main_bgp2")]:
        if bgp:
            bgp_routes.append(
                f"set protocols static route {bgp}/32 next-hop {main_remote}"
            )
    for bgp in [d.get("bk_bgp1"), d.get("bk_bgp2")]:
        if bgp:
            bgp_routes.append(
                f"set protocols static route {bgp}/32 next-hop {bk_remote}"
            )
    # 黑洞保护
    for bgp in [
        d.get("main_bgp1"), d.get("main_bgp2"),
        d.get("bk_bgp1"), d.get("bk_bgp2"),
    ]:
        if bgp:
            bgp_routes.append(
                f"set protocols static route {bgp}/32 blackhole distance 10"
            )
    d["bgp_server_routes_block"] = "\n".join(bgp_routes)

    # ── 13. 硬编码 DNS-NET 地址组 IP ──
    d["dns_ip1"] = _EPOCH5_DNS_GLOBAL2  # 8.8.8.8
    d["dns_ip2"] = _EPOCH5_DNS_GLOBAL1  # 8.8.4.4

    return d, None


# =====================================================================
# 占位 Builder（非 HK 变体）
# =====================================================================
def build_epoch5_us_format_dict(hdr_text):
    """组装与 TEMPLATE_EPOCH5_US.format(**d) 相同的 dict。

    成功返回 (d, None)；失败返回 (None, (kind, payload))。
    kind: "parse" — 数据头解析/校验失败, "natmiss" — 海外出口 IP 缺失, "network" — 网络参数校验失败。
    """
    g = globals()

    # ── 0. 校验网络参数 ──
    wan_cidr = str(g.get("DEFAULT_WAN_CIDR", "")).strip()
    wan_gw = str(g.get("DEFAULT_WAN_GW", "")).strip()
    lan_cidr = str(g.get("DEFAULT_LAN_CIDR", "")).strip()
    inner_nets_raw = str(g.get("DEFAULT_INNER_NETS", "")).strip()

    ok_wan, msg_wan = _validate_cidr(wan_cidr, "WAN IP")
    ok_lan, msg_lan = _validate_cidr(lan_cidr, "LAN IP")
    ok_gw, msg_gw = _validate_ip(wan_gw, "WAN 网关")
    _, inner_errors = _validate_inner_nets(inner_nets_raw)
    errs = []
    if not ok_wan:
        errs.append(msg_wan)
    if not ok_lan:
        errs.append(msg_lan)
    if not ok_gw:
        errs.append(msg_gw)
    for frag, reason in inner_errors:
        errs.append(f"内网段「{frag}」不符合网络标准：{reason}")
    if errs:
        return None, ("network", errs)

    # ── 1. 解析数据头 ──
    raw = hdr_text.strip()
    if not raw:
        return None, ("parse", "请输入业务数据（LineID 数据头）")
    d = parse_epoch_us(raw)

    # ── 2. 读取网络参数 ──
    wan_eth = str(g.get("DEFAULT_WAN_ETH", "0")).strip() or "0"
    lan_eth = str(g.get("DEFAULT_LAN_ETH", "5")).strip() or "5"
    wan_dhcp = bool(g.get("DEFAULT_WAN_DHCP", False))
    lan_dhcp = bool(g.get("DEFAULT_LAN_DHCP", True))
    bypass = bool(g.get("DEFAULT_BYPASS", False))

    # ── 3. 校验必要字段 ──
    if not d.get("main_us_pe") and not d.get("main_acvpn_gre_pe"):
        return None, ("parse", "未找到主线 PE 信息，请检查数据头格式")

    main_nat_ips = list(d.get("main_us_nat_ips", []) or [])
    bk_nat_ips = list(d.get("bk_us_nat_ips", []) or [])
    if not main_nat_ips and not bk_nat_ips:
        miss = []
        if not main_nat_ips:
            miss.append("主线海外出口ip")
        if not bk_nat_ips:
            miss.append("备线海外出口ip")
        return None, ("natmiss", miss)

    # 截断超量 IP
    if len(main_nat_ips) > 9:
        main_nat_ips = main_nat_ips[:9]
    if len(bk_nat_ips) > 10:
        bk_nat_ips = bk_nat_ips[:10]

    d["main_us_nat_ips"] = main_nat_ips
    d["bk_us_nat_ips"] = bk_nat_ips
    d["main_us_nat_ip"] = main_nat_ips[0] if main_nat_ips else d.get("main_us_nat_ip", "")
    d["bk_us_nat_ip"] = bk_nat_ips[0] if bk_nat_ips else d.get("bk_us_nat_ip", "")
    d["main_us_nat_ip_all"] = ", ".join(main_nat_ips) if main_nat_ips else d.get("main_us_nat_ip", "")
    d["bk_us_nat_ip_all"] = ", ".join(bk_nat_ips) if bk_nat_ips else d.get("bk_us_nat_ip", "")
    d["main_us_dum100_desc"] = "MAIN_OUTIP" if len(main_nat_ips) <= 1 else "MAIN_OUTIP_01"
    d["bk_us_dum200_desc"] = "BK_OUTIP" if len(bk_nat_ips) <= 1 else "BK_OUTIP_01"

    # ── 4. 设置基本信息 ──
    hn = d.get("hostname", "").strip()
    if not hn:
        hn = _extract_lineid(raw) or "请填写Hostname"
    d["hostname"] = hn if hn else "请填写Hostname"

    d["wan_if"] = f"eth{wan_eth}" if not wan_eth.startswith("eth") else wan_eth
    d["lan_if"] = f"eth{lan_eth}" if not lan_eth.startswith("eth") else lan_eth
    d["wan_cidr"] = wan_cidr
    d["lan_cidr"] = lan_cidr
    d["wan_gw"] = wan_gw

    # 从 CIDR 提取纯 IP
    lan_ip = ""
    if lan_cidr:
        try:
            lan_ip = str(ipaddress.ip_interface(lan_cidr.strip()).ip)
        except Exception:
            lan_ip = lan_cidr.split("/")[0].strip()
    d["lan_ip"] = lan_ip

    # ── 5. LAN 接口配置（旁挂模式下跳过）──
    if bypass:
        d["lan_if_block"] = "# 旁挂模式 — 跳过 LAN 接口配置"
    else:
        d["lan_if_block"] = (
            f"set interfaces ethernet {d['lan_if']} description LAN\n"
            f"set interfaces ethernet {d['lan_if']} address '{d['lan_cidr']}'"
        )

    # ── 6. 生成 {fw_options_block} ──
    fw_lines = [
        f"set firewall options interface {t} adjust-mss '1300'"
        for t in [
            d.get("main_acvpn_vtun_id", ""), d.get("bk_acvpn_vtun_id", ""),
            d.get("main_acvpn_gre_tun", ""), d.get("bk_acvpn_gre_tun", ""),
            d.get("main_us_tun", ""), d.get("bk_us_tun", ""),
        ]
        if t
    ]
    d["fw_options_block"] = "\n".join(fw_lines) if fw_lines else ""

    # ── 8. 生成 {extra_dum_main_block} / {extra_dum_bk_block} ──
    extra_main_lines = []
    for idx, ip in enumerate(main_nat_ips[1:], start=2):
        dum = 99 + idx
        desc = "MAIN_OUTIP" if len(main_nat_ips) <= 1 else f"MAIN_OUTIP_{idx:02d}"
        extra_main_lines.append(f"set interfaces dummy dum{dum} address '{ip}/32'")
        extra_main_lines.append(f"set interfaces dummy dum{dum} description '{desc}'")
    d["extra_dum_main_block"] = "\n".join(extra_main_lines)

    extra_bk_lines = []
    for idx, ip in enumerate(bk_nat_ips[1:], start=2):
        dum = 199 + idx
        desc = "BK_OUTIP" if len(bk_nat_ips) <= 1 else f"BK_OUTIP_{idx:02d}"
        extra_bk_lines.append(f"set interfaces dummy dum{dum} address '{ip}/32'")
        extra_bk_lines.append(f"set interfaces dummy dum{dum} description '{desc}'")
    d["extra_dum_bk_block"] = "\n".join(extra_bk_lines)

    # ── 9. 生成 {overseas_nat_block} ──
    overseas_lines = [
        f"set nat source rule 100 outbound-interface name '{d['main_us_tun']}'",
        f"set nat source rule 100 source group network-group 'LAN-NET'",
        f"set nat source rule 100 translation address '{d['main_us_nat_ip']}'",
        f"set nat source rule 200 outbound-interface name '{d['bk_us_tun']}'",
        f"set nat source rule 200 source group network-group 'LAN-NET'",
        f"set nat source rule 200 translation address '{d['bk_us_nat_ip']}'",
    ]
    d["overseas_nat_block"] = "\n".join(overseas_lines)

    # ── 10. 生成 {us_bgp_routes} ──
    bgp_lines = []
    main_peip = d.get("main_us_pe_ip", "")
    bk_peip = d.get("bk_us_pe_ip", "")
    for bgp in [d.get("main_us_bgp1", ""), d.get("main_us_bgp2", "")]:
        if bgp:
            bgp_lines.append(
                f"set protocols static route {bgp}/32 blackhole distance '10'"
            )
            bgp_lines.append(
                f"set protocols static route {bgp}/32 next-hop {main_peip}"
            )
    for bgp in [d.get("bk_us_bgp1", ""), d.get("bk_us_bgp2", "")]:
        if bgp:
            bgp_lines.append(
                f"set protocols static route {bgp}/32 blackhole distance '10'"
            )
            bgp_lines.append(
                f"set protocols static route {bgp}/32 next-hop {bk_peip}"
            )
    d["us_bgp_routes"] = "\n".join(bgp_lines)

    # ── 11. 生成 {default_route_block} ──
    if wan_dhcp:
        d["default_route_block"] = (
            "# WAN DHCP 模式 — 不生成默认静态路由"
        )
    else:
        d["default_route_block"] = (
            f"set protocols static route 0.0.0.0/0 next-hop 1.1.1.1 distance '220'\n"
            f"set protocols static route 1.1.1.1/32 next-hop '{wan_gw}'"
        )

    # ── 12. 生成 {pki_block} ──
    if _EPOCH5_PKI_SECRET_KEY:
        d["pki_block"] = (
            f"set pki openvpn shared-secret openvpn_secret key '{_EPOCH5_PKI_SECRET_KEY}'\n"
            f"run import pki openvpn shared-secret openvpn_secret file /opt/pki/openvpn.secret"
        )
    else:
        d["pki_block"] = (
            "# PKI secret key 未配置\n"
            "# run import pki openvpn shared-secret openvpn_secret file /opt/pki/openvpn.secret"
        )

    # ── 13. 生成 {dhcp_block} ──
    if lan_dhcp and lan_cidr and lan_ip and not bypass:
        try:
            net = ipaddress.ip_network(lan_cidr.strip(), strict=False)
            prefix = net.prefixlen
            network_addr = str(net.network_address)
            hosts = list(net.hosts())
            if hosts:
                d_start = str(hosts[min(9, len(hosts) - 1)])
                d_stop = str(hosts[min(199, len(hosts) - 1)])
            else:
                d_start = d_stop = ""
            prefix_id = str(prefix)

            d["dhcp_block"] = (
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} option default-router '{lan_ip}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} option name-server '{lan_ip}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} range Lan1_range start '{d_start}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} range Lan1_range stop '{d_stop}'\n"
                f"set service dhcp-server shared-network-name NAT_LAN "
                f"subnet {network_addr}/{prefix} subnet-id '{prefix_id}'"
            )
        except Exception:
            d["dhcp_block"] = (
                "# DHCP 服务器未配置 — LAN CIDR 解析失败"
            )
    else:
        d["dhcp_block"] = (
            "# DHCP 服务器未启用"
        )

    # ── 14. 生成 {lan_net_block} ──
    d["lan_net_block"] = (
        "set firewall group network-group LAN-NET network '10.0.0.0/8'\n"
        "set firewall group network-group LAN-NET network '172.16.0.0/12'\n"
        "set firewall group network-group LAN-NET network '192.168.0.0/16'"
    )

    # ── 14b. 生成 {return_routes_block} ──
    gen_rr = bool(g.get("DEFAULT_GEN_RETURN_ROUTE", False))
    if gen_rr:
        rr_lines = []
        base_cidr = wan_cidr if bypass else lan_cidr
        gw = wan_gw if bypass else (str(g.get("DEFAULT_LAN_GW", "")).strip() or (lan_cidr.split("/")[0] if lan_cidr else ""))
        inner_nets = _parse_inner_nets(inner_nets_raw)
        outside = _nets_needing_return(base_cidr, inner_nets)
        for net in outside:
            rr_lines.append(f"set protocols static route {net} next-hop {gw}")
        d["return_routes_block"] = "\n".join(rr_lines) if rr_lines else ""
    else:
        d["return_routes_block"] = ""

    # ── 15. 硬编码 DNS-NET 地址组 IP ──
    d["dns_ip1"] = _EPOCH5_DNS_GLOBAL2  # 8.8.8.8
    d["dns_ip2"] = _EPOCH5_DNS_GLOBAL1  # 8.8.4.4

    return d, None


def build_epoch5_flink_format_dict(hdr_text):
    routes, err = parse_epoch5_flink_headers(hdr_text)
    if err:
        return None, ("parse", err)
    d = _build_epoch5_flink_format_dict(
        routes,
        str(globals().get("ER5_FL_MAIN_NH_DEFAULT", "10.1.1.1")),
        str(globals().get("ER5_FL_BACKUP_NH_DEFAULT", "10.2.1.1")),
    )
    return d, None


# build_epoch5_new_exit_format_dict(parsed, init_cfg) → dict (defined above, same name)


def build_epoch5_domain_split_format_dict(hdr_text):
    """5.0 ER 域名分流生成器。
    返回 (output_string, None) 或 (None, error_string)。
    """
    dom_lines = []
    for ln in (hdr_text or "").splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.search(r"[\s#;|&$`<>]", s):
            return None, f"域名含非法字符：{s!r}"
        dom_lines.append(s)
    if not dom_lines:
        return None, "请至少填写一行域名"

    g = globals()
    ag_raw = str(g.get("ER5_DS_ADDR_GROUP_DEFAULT", "")).strip()
    addr_group = _er_ds_normalize_addr_group(ag_raw)
    if not addr_group:
        return None, "请填写 address-group"

    dl = _er_ds_domainlist_name(addr_group)
    pr = _er_ds_policy_route_name(addr_group)
    if not dl:
        return None, "address-group 无效，无法推导 domain-list 名称"

    dns1 = str(g.get("ER5_DS_DNS1_DEFAULT", "")).strip()
    dns2 = str(g.get("ER5_DS_DNS2_DEFAULT", "")).strip()
    if not dns1:
        return None, "DNS 主不能为空"

    sc_raw = str(g.get("ER5_DS_SOURCE_CIDR_DEFAULT", "")).strip()
    src_cidr = ""
    if sc_raw:
        try:
            src_cidr = str(ipaddress.ip_network(sc_raw, strict=False))
        except ValueError:
            return None, f"源网段非法：{sc_raw}"
    rn = str(g.get("ER5_DS_RULE_NUM_DEFAULT", "")).strip()
    tn = str(g.get("ER5_DS_TABLE_NUM_DEFAULT", "")).strip()
    eth = str(g.get("ER5_DS_ETH_DEFAULT", "")).strip()
    if not rn.isdigit() or not tn.isdigit():
        return None, "rule/table 号须为数字"

    nh_pri = str(g.get("ER5_DS_TABLE_NH_PRIMARY_DEFAULT", "")).strip()
    s32_pri = str(g.get("ER5_DS_STATIC32_PRIMARY_NH_DEFAULT", "")).strip()
    s32_bak = str(g.get("ER5_DS_STATIC32_BACKUP_NH_DEFAULT", "")).strip()
    trn = str(g.get("ER5_DS_TRACK_NAME_DEFAULT", "")).strip()
    for ip, lab in ((nh_pri, "递归下一跳"), (s32_pri, "主下一跳")):
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return None, f"{lab}「{ip}」不是合法 IPv4"
    if s32_bak:
        try:
            ipaddress.ip_address(s32_bak)
        except ValueError:
            return None, f"备下一跳「{s32_bak}」不是合法 IPv4"

    lines = []
    lines.append(f"# 等价于 touch + vi 写入 /opt/{dl}.txt")
    lines.append(f"sudo tee /opt/{dl}.txt >/dev/null <<'EOF'")
    lines.extend(dom_lines)
    lines.append("EOF")
    lines.append(f"sudo chmod 777 /opt/{dl}.txt")
    lines.append("")
    lines.append(f"set firewall group address-group {addr_group}")
    lines.append("")
    lines.append(f"set service dns forwarding domain-list {dl} address-group '{addr_group}'")
    lines.append(f"set service dns forwarding domain-list {dl} file '/opt/{dl}.txt'")
    lines.append(f"set service dns forwarding domain-list {dl} name-server {dns1}")
    lines.append(f"set service dns forwarding domain-list {dl} recursion-desired")
    if dns2:
        lines.append(f"set service dns forwarding domain-list {dl} name-server {dns2}")
    lines.append("")

    lines.append(f"set policy route {pr} interface '{eth}'")
    lines.append(f"set policy route {pr} rule {rn} destination group address-group '{addr_group}'")
    if src_cidr:
        lines.append(f"set policy route {pr} rule {rn} source address {src_cidr}")
    lines.append(f"set policy route {pr} rule {rn} set table '{tn}'")
    lines.append(f"set protocols static table {tn} route 0.0.0.0/0 next-hop  {nh_pri}")
    lines.append("")

    track_suffix = f" track {trn}" if trn else ""
    lines.append(f"set protocols static route {nh_pri}/32 next-hop {s32_pri}{track_suffix}")
    if s32_bak:
        lines.append(f"set protocols static route {nh_pri}/32 next-hop {s32_bak} distance '20'")

    nr_raw = str(g.get("ER5_DS_FNET_NAT_RULE_DEFAULT", "")).strip()
    tun_raw = str(g.get("ER5_DS_EXIT_TUNNEL_DEFAULT", "")).strip()
    sn_raw = str(g.get("ER5_DS_EXIT_SNAT_IP_DEFAULT", "")).strip()
    fnet_probe_raw = str(g.get("ER5_DS_FNET_PROBE_DEFAULT", "100.100.100.1")).strip()
    fnet_src = str(g.get("ER5_DS_FAILOVER_SRC_DEFAULT", "")).strip()

    f_filled = (bool(nr_raw), bool(tun_raw), bool(sn_raw))
    if all(f_filled):
        nr_ok = nr_raw.isdigit() and 1 <= int(nr_raw) <= 999999
        tun_ok = bool(re.match(r"^[A-Za-z0-9._-]+$", tun_raw))
        sn_ok = True
        try:
            ipaddress.ip_address(sn_raw)
        except ValueError:
            sn_ok = False
        try:
            fnet_probe = str(ipaddress.ip_address(fnet_probe_raw))
        except ValueError:
            fnet_probe = ""
            sn_ok = False
        if nr_ok and tun_ok and sn_ok and fnet_probe:
            FNET_GRP = "GROUP-FNET-Whitelist"
            FNET_NET = "100.100.100.0/24"
            lines.append("")
            lines.append(f"set firewall group network-group {FNET_GRP} network {FNET_NET}")
            lines.append("")
            lines.append(f"set nat source rule {nr_raw} destination address {fnet_probe}/32")
            lines.append(f"set nat source rule {nr_raw} outbound-interface '{tun_raw}'")
            lines.append(f"set nat source rule {nr_raw} translation address '{sn_raw}'")
            lines.append("")
            lines.append(f"set protocols static route {fnet_probe}/32 next-hop {s32_pri}")
            lines.append("")
            if trn:
                failover_src = fnet_src if fnet_src else s32_pri
                lines.append(f"set protocols failover2 route {fnet_probe}/32 next-hop {s32_pri} track '{trn}'")
                lines.append(f"set protocols failover2 track {trn} source-address '{failover_src}'")
                lines.append(f"set protocols failover2 track {trn} target '{fnet_probe}'")
                lines.append(f"set protocols failover2 track {trn} type 'icmp'")

    return "\n".join(lines).rstrip() + "\n", None


# =====================================================================
# 示例数据
# =====================================================================
US5_EXAMPLE = (
    "LineID:603642Ar1\n"
    "PE:szd-upe5\n"
    "Tunnel:Tunnel0/0/1165\n"
    "wanip:10.55.14.64/30\n"
    "PE 对接:192.168.247.17\n"
    "CE 对接:10.23.0.122\n"
    "PE:szd-acvpnpe2\n"
    "Tunnel:vtun17953\n"
    "wanip:10.23.0.120/30\n"
    "PE 对接:183.63.68.171\n"
    "\n"
    "LineID:603642Ar2\n"
    "PE:szc-upe2\n"
    "Tunnel:Tunnel0/0/1998\n"
    "wanip:10.40.209.220/30\n"
    "PE 对接:192.168.251.100\n"
    "CE 对接:10.30.167.202\n"
    "PE:szc-acvpnpe2\n"
    "Tunnel:vtun50057\n"
    "wanip:10.30.167.200/30\n"
    "PE 对接:121.12.128.254\n"
    "\n"
    "LineID:603642Ar3\n"
    "PE：szd-natflr2\n"
    "WANIP:10.40.25.188/30\n"
    "TUNNEL:tun100\n"
    "PE Docking：121.12.81.3\n"
    "CE Docking：10.20.186.2\n"
    "BGPSERVER IP：10.10.99.168,10.10.99.169\n"
    "海外出口ip：103.48.141.157\n"
    "\n"
    "LineID:603642Ar4\n"
    "PE：szc-natbk10\n"
    "WANIP:10.41.25.188/30\n"
    "TUNNEL:tun200\n"
    "PE Docking：120.133.129.72\n"
    "CE Docking：10.25.186.3\n"
    "BGPSERVER IP：10.10.99.198,10.10.99.199\n"
    "海外出口ip：103.48.141.158\n"
)

US5_IPSEC_EXAMPLE = (
    "LineID:609430B1\n"
    "PE:szd-upe3\n"
    "Tunnel:Tunnel0/0/2013\n"
    "wanip:10.40.129.148/30\n"
    "PE 对接:10.200.200.37\n"
    "CE 对接:10.50.86.74\n"
    "PE AS号:65510\n"
    "客户内网路由:10.22.242.223\n"
    "\n"
    "拨号PE:szd-upe3\n"
    "对接IP:10.200.200.37\n"
    "LoopIP:10.50.86.74\n"
    "拨号ip:183.56.161.86\n"
    "秘钥:both-win\n"
    "\n"
    "--- IKE (ike-peer IPSEC) ---\n"
    "key-exchange: ikev1/ikev2\n"
    "proposal 1:\n"
    "  dh-group: 2\n"
    "  encryption: aes128 3des\n"
    "  hash: sha1\n"
    "  prf: hmac-sha2-256\n"
    "dead-peer-detection: no\n"
    "\n"
    "--- IPsec proposal (IPSEC) ---\n"
    "proposal 1:\n"
    "  encryption: aes128 3des\n"
    "  hash: sha1\n"
    "\n"
    "\n"
    "\n"
    "LineID:609430B2\n"
    "PE:szc-upe1\n"
    "Tunnel:Tunnel0/0/1163\n"
    "wanip:10.30.37.168/30\n"
    "PE 对接:10.200.200.27\n"
    "CE 对接:10.50.118.76\n"
    "PE AS号:65107\n"
    "客户内网路由:10.22.242.223\n"
    "\n"
    "拨号PE:szc-upe1\n"
    "对接IP:10.200.200.27\n"
    "LoopIP:10.50.118.76\n"
    "拨号ip:120.133.134.72\n"
    "秘钥:both-win\n"
    "\n"
    "--- IKE (ike-peer IPSEC) ---\n"
    "key-exchange: ikev1/ikev2\n"
    "proposal 1:\n"
    "  dh-group: 2\n"
    "  encryption: aes128 3des\n"
    "  hash: sha1\n"
    "  prf: hmac-sha2-256\n"
    "dead-peer-detection: yes\n"
    "  type: ondemand\n"
    "  idle-time: 10\n"
    "\n"
    "--- IPsec proposal (IPSEC) ---\n"
    "proposal 1:\n"
    "  encryption: aes128 3des\n"
    "  hash: sha1\n"
    "\n"
    "\n"
    "LineID:609430B5\n"
    "PE： lax1-natpe7\n"
    "WANIP: 10.22.113.36/30\n"
    "TUNNEL: tun2209\n"
    "PE Docking：192.168.215.12\n"
    "CE Docking：: 10.22.242.223\n"
    "BGPSERVER IP：103.252.19.25,43.229.117.226\n"
    "海外出口ip：\n"
    "10.60.52.46-8.3.6.111\n"
    "\n"
    "LineID:609430B6\n"
    "PE： sjc1-natpe3\n"
    "WANIP: 10.22.115.28/30\n"
    "TUNNEL: tun1080\n"
    "PE Docking：10.33.54.118\n"
    "CE Docking：: 10.22.242.223\n"
    "BGPSERVER IP：103.252.19.99,43.229.119.251\n"
    "海外出口ip：\n"
    "10.60.79.99-172.16.212.58\n"
)

HK5_EXAMPLE = (
    "MAIN\n"
    "lineid: 603642Ar3\n"
    "主PE： szd-natflr2\n"
    "WANIP: 10.40.25.188/30\n"
    "TUNNEL: vtun40826\n"
    "Docking：121.12.81.3\n"
    "CE LOIP: 10.20.186.235\n"
    "HKIP：10.60.241.250 --> 103.48.141.157\n"
    "BGPSERVER IP： 10.10.99.168,10.10.99.169\n"
    "\n"
    "BACKUP\n"
    "PE：szc-natbk10\n"
    "WANIP: 10.41.25.188/30\n"
    "TUNNEL: vtun50826\n"
    "Docking： 120.133.129.72\n"
    "CE LOIP: 10.20.186.235\n"
    "HKIP：10.60.241.250 --> 103.48.141.157\n"
    "BGPSERVER IP：10.10.99.198,10.10.99.199\n"
)


# =====================================================================
# 可视化合并函数（供 all_in_one_v2 调用）
# =====================================================================
def _visual_merge_er5_init(variant: str, updates: dict) -> None:
    """all_in_one：将可视化编辑器的持久化值写入本模块 globals()。
    variant: "hk" | "us" | "flink" | "new_exit" | "domain_split"
    updates: { "DEFAULT_WAN_CIDR": "...", "DEFAULT_WAN_ETH": "...", ... }
    """
    g = globals()
    _BOOL_KEYS = frozenset({
        "DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP", "DEFAULT_GEN_RETURN_ROUTE", "DEFAULT_BYPASS",
    })

    def _pb(val) -> bool:
        s = str(val).strip().lower()
        return s in ("1", "true", "yes", "on", "开")

    def _dest(k: str) -> str:
        if variant == "hk" and k.startswith("DEFAULT_"):
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


# =====================================================================
# IPSec 隧道类型 — 5.0 非香港出口（v2：恒定 4 LineID = 2 IPSec + 2 NAT/GRE）
# =====================================================================

_IPSEC_MTU_DEFAULT = "1400"  # tunnel MTU 无法从数据头推算，用统一值；UI 告知人工核对
_TUN_PE_HOSTNUM = 1   # /30 hosts[0] 给 PE 端
_TUN_CE_HOSTNUM = 2   # /30 hosts[1] 给 CE 端


def _ipsec_get(pat: str, text: str, default: str = "") -> str:
    """提取一行字段。兼容半角/全角冒号。"""
    m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return default
    return m.group(1).strip()


def _wan_pair(wan_cidr: str):
    """从 wanip CIDR(/30) 推算 (PE 端 IP, CE 端 IP)；无效返回 (None, None)。"""
    try:
        net = ipaddress.ip_network(wan_cidr.strip(), strict=False)
        hosts = list(net.hosts())
        if len(hosts) < 2:
            return None, None
        return str(hosts[0]), str(hosts[1])
    except (ValueError, TypeError):
        return None, None


def _parse_ipsec_lineid_block(block: str) -> dict:
    """解析单个 IPSec 拨号 LineID 块。"""
    d: dict = {"_kind": "ipsec"}
    d["lineid"] = _ipsec_get(r'^LineID\s*[:：]\s*(\S+)', block)
    d["pe"] = _ipsec_get(r'^PE\s*[:：]\s*(\S+)', block)
    tun_raw = _ipsec_get(r'^Tunnel\s*[:：]\s*(\S+)', block)
    d["tun_id"] = normalize_tun(tun_raw)
    d["tun_num"] = re.sub(r'\D', '', d["tun_id"])
    d["wanip"] = _ipsec_get(r'^wanip\s*[:：]\s*(\S+)', block)
    d["pe_docking"] = (
        _ipsec_get(r'^PE\s*对接\s*[:：]\s*(\S+)', block)
        or _ipsec_get(r'^PE\s*Docking\s*[:：]\s*(\S+)', block)
    )
    d["ce_docking"] = (
        _ipsec_get(r'^CE\s*对接\s*[:：]\s*(\S+)', block)
        or _ipsec_get(r'^CE\s*Docking\s*[:：]\s*(\S+)', block)
    )
    d["pe_as"] = _ipsec_get(r'^PE\s*AS\s*号\s*[:：]\s*(\S+)', block)
    d["ce_loip"] = _ipsec_get(r'^客户内网路由\s*[:：]\s*(\S+)', block)
    d["dial_pe"] = _ipsec_get(r'^拨号PE\s*[:：]\s*(\S+)', block) or d["pe"]
    d["dial_ip"] = _ipsec_get(r'^拨号ip\s*[:：]\s*(\S+)', block)
    d["loop_ip"] = _ipsec_get(r'^LoopIP\s*[:：]\s*(\S+)', block)
    d["docking_ip"] = (
        _ipsec_get(r'^对接IP\s*[:：]\s*(\S+)', block) or d["pe_docking"]
    )
    d["secret"] = _ipsec_get(r'^秘钥\s*[:：]\s*(\S+)', block)

    # tunnel 地址：CE 端用 wanip /30 的第二个 host
    pe_ip, ce_ip = _wan_pair(d["wanip"])
    d["tun_pe_ip"] = pe_ip or ""
    d["tun_ce_ip"] = ce_ip or ""

    # IKE 块
    ike_m = re.search(
        r'---\s*IKE\s*\(ike-peer[^)]*\)\s*---\s*\n(.*?)(?=\n\s*---|\nLineID|\Z)',
        block, re.IGNORECASE | re.DOTALL,
    )
    if ike_m:
        b = ike_m.group(1)
        d["ike_key_exchange"] = _ipsec_get(r'key-exchange\s*[:：]\s*(\S+)', b)
        d["ike_dh_group"] = _ipsec_get(r'dh-group\s*[:：]\s*(\S+)', b)
        d["ike_encryption"] = _ipsec_get(r'encryption\s*[:：]\s*(\S+)', b).replace(" ", "-")
        d["ike_hash"] = _ipsec_get(r'^\s*hash\s*[:：]\s*(\S+)', b)
        d["ike_prf"] = _ipsec_get(r'prf\s*[:：]\s*(\S+)', b)
        d["ike_dpd"] = _ipsec_get(r'dead-peer-detection\s*[:：]\s*(\S+)', b)
        d["ike_dpd_idle"] = _ipsec_get(r'idle-time\s*[:：]\s*(\S+)', b)
    else:
        d["ike_key_exchange"] = d["ike_dh_group"] = d["ike_encryption"] = ""
        d["ike_hash"] = d["ike_prf"] = d["ike_dpd"] = d["ike_dpd_idle"] = ""

    # IPsec proposal 块
    esp_m = re.search(
        r'---\s*IPsec\s*proposal[^-]*---\s*\n(.*?)(?=\n\s*---|\nLineID|\Z)',
        block, re.IGNORECASE | re.DOTALL,
    )
    if esp_m:
        b = esp_m.group(1)
        d["esp_encryption"] = _ipsec_get(r'encryption\s*[:：]\s*(\S+)', b).replace(" ", "-")
        d["esp_hash"] = _ipsec_get(r'^\s*hash\s*[:：]\s*(\S+)', b)
    else:
        d["esp_encryption"] = d["esp_hash"] = ""
    return d


def _parse_nat_lineid_block(block: str) -> dict:
    """解析单个 NAT/GRE LineID 块。"""
    d: dict = {"_kind": "nat"}
    d["lineid"] = _ipsec_get(r'^LineID\s*[:：]\s*(\S+)', block)
    d["pe"] = _ipsec_get(r'^PE\s*[:：]\s*(\S+)', block)
    d["wanip"] = _ipsec_get(r'^WANIP\s*[:：]\s*(\S+)', block)
    tun_raw = _ipsec_get(r'^TUNNEL\s*[:：]\s*(\S+)', block)
    d["tun_id"] = normalize_tun(tun_raw)
    d["tun_num"] = re.sub(r'\D', '', d["tun_id"])
    d["pe_docking"] = _ipsec_get(r'^PE\s*Docking\s*[:：]+\s*(\S+)', block)
    d["ce_docking"] = _ipsec_get(r'^CE\s*Docking\s*[:：]+\s*(\S+)', block)

    # BGPSERVER IP: 逗号分隔
    bgp_raw = _ipsec_get(r'^BGPSERVER\s*IP\s*[:：]\s*(.+?)$', block)
    bgps = [x.strip() for x in re.split(r'[,，]', bgp_raw) if x.strip()]
    d["bgp_servers"] = bgps
    d["bgp1"] = bgps[0] if len(bgps) > 0 else ""
    d["bgp2"] = bgps[1] if len(bgps) > 1 else ""

    # 海外出口ip: 形如 "10.60.52.46-8.3.6.111"
    m = re.search(r'海外出口ip\s*[:：]\s*\n?\s*(\S+)', block, re.MULTILINE)
    if m:
        pair = m.group(1).strip()
        if "-" in pair:
            usip, public = pair.split("-", 1)
            d["usip"] = usip.strip()
            d["public_ip"] = public.strip()
        else:
            d["usip"] = pair
            d["public_ip"] = ""
    else:
        d["usip"] = d["public_ip"] = ""

    # tunnel 地址：CE 端 = wanip /30 第二个 host
    pe_ip, ce_ip = _wan_pair(d["wanip"])
    d["tun_pe_ip"] = pe_ip or ""
    d["tun_ce_ip"] = ce_ip or ""
    return d


def _parse_ipsec_us(hdr_text: str):
    """解析 IPSec 数据头。

    强制：恰好 2 个 IPSec 拨号块 + 2 个 NAT/GRE 块。
    返回 ({ipsec_main, ipsec_bk, nat_main, nat_bk}, None) 或 (None, error_msg)。
    """
    raw = hdr_text.strip()
    if not raw:
        return None, "请输入业务数据（4 个 LineID 块：2 IPSec + 2 NAT/GRE）"

    # 按 LineID 切块
    parts = re.split(r'(?=^\s*LineID\s*[:：])', raw, flags=re.MULTILINE | re.IGNORECASE)
    parts = [p.strip() for p in parts if re.match(r'^\s*LineID\s*[:：]', p, re.IGNORECASE)]

    ipsec_blocks: list[dict] = []
    nat_blocks: list[dict] = []
    for p in parts:
        is_ipsec = bool(re.search(r'拨号PE\s*[:：]', p)) and bool(re.search(r'LoopIP\s*[:：]', p))
        is_nat = bool(re.search(r'BGPSERVER\s*IP\s*[:：]', p, re.IGNORECASE))
        if is_ipsec:
            ipsec_blocks.append(_parse_ipsec_lineid_block(p))
        elif is_nat:
            nat_blocks.append(_parse_nat_lineid_block(p))
        # 既不是 IPSec 也不是 NAT 的 LineID 块直接忽略（不报错，因为只校验数量约束）

    if len(ipsec_blocks) != 2:
        return None, (
            f"IPSec 数据头需要恰好 2 个 IPSec 拨号 LineID 块（含『拨号PE』『LoopIP』），"
            f"当前发现 {len(ipsec_blocks)} 个"
        )
    if len(nat_blocks) != 2:
        return None, (
            f"IPSec 数据头需要恰好 2 个 NAT/GRE LineID 块（含『BGPSERVER IP』），"
            f"当前发现 {len(nat_blocks)} 个"
        )

    return {
        "ipsec_main": ipsec_blocks[0],
        "ipsec_bk": ipsec_blocks[1],
        "nat_main": nat_blocks[0],
        "nat_bk": nat_blocks[1],
    }, None

def _ipsec_first_token(val: str, default: str = "") -> str:
    if not val:
        return default
    return val.replace("/", " ").split()[0]


def _ipsec_ike_dpd_lines(ike_dpd: str, idle: str) -> str:
    if _ipsec_first_token(ike_dpd).lower() in ("no", "false", "0"):
        return ""
    interval = idle or "10"
    return (
        "set vpn ipsec ike-group IKE-FNET-2 dead-peer-detection action 'restart'\n"
        f"set vpn ipsec ike-group IKE-FNET-2 dead-peer-detection interval '{interval}'\n"
        "set vpn ipsec ike-group IKE-FNET-2 dead-peer-detection timeout '30'\n"
    )


def _require_fields(block: dict, fields: list[tuple[str, str]], label: str):
    missing = [cn for key, cn in fields if not block.get(key)]
    if missing:
        return f"{label} 缺少字段：{', '.join(missing)}"
    return ""


TEMPLATE_EPOCH5_HK_IPSEC = ""


TEMPLATE_EPOCH5_US_IPSEC = (
    "# Epoch 5.0 非香港出口配置 (IPSec)  Hostname: {hostname}\n"
    "# MTU/MSS：IPSec(upe) GRE = 1476/1300，NAT(natpe) GRE = 1452/1300。请按链路实测调整\n"
    "\n"
    "# start\n"
    "set firewall group address-group DNS-NET address '8.8.8.8'\n"
    "set firewall group address-group DNS-NET address '8.8.4.4'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '192.168.0.0/16'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '172.16.0.0/12'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '10.0.0.0/8'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '100.64.0.0/10'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '224.0.0.0/4'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '127.0.0.0/8'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '{nat_main_bgp2}/32'\n"
    "set firewall group network-group GROUP-FNET-Whitelist network '{nat_bk_bgp2}/32'\n"
    "{lan_net_block}\n"
    "set firewall ipv4 input filter default-action 'accept'\n"
    "set firewall ipv4 input filter rule 100 action 'jump'\n"
    "set firewall ipv4 input filter rule 100 jump-target 'WAN2LOCAL'\n"
    "set firewall ipv4 name WAN2LOCAL default-action 'drop'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1000 action 'accept'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1000 state 'established'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1000 state 'related'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1010 action 'accept'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1010 source group network-group 'GROUP-FNET-Whitelist'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1210 action 'accept'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1210 protocol 'gre'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1220 action 'accept'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1220 protocol 'ipip'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1230 action 'accept'\n"
    "set firewall ipv4 name WAN2LOCAL rule 1230 protocol 'esp'\n"
    "set interfaces dummy dum0 address '{ce_loip}/32'\n"
    "set interfaces dummy dum0 description 'loopback'\n"
    "set interfaces dummy dum1 address '{main_ipsec_loop_ip}/32'\n"
    "set interfaces dummy dum1 description 'ipsec main'\n"
    "set interfaces dummy dum2 address '{bk_ipsec_loop_ip}/32'\n"
    "set interfaces dummy dum2 description 'ipsec backup'\n"
    "set interfaces dummy dum101 address '{main_nat_usip}/32'\n"
    "set interfaces dummy dum101 description 'USIP-Main:{main_nat_usip}-{main_nat_public_ip}'\n"
    "set interfaces dummy dum201 address '{bk_nat_usip}/32'\n"
    "set interfaces dummy dum201 description 'USIP-BK:{bk_nat_usip}-{bk_nat_public_ip}'\n"
    "set interfaces ethernet {wan_if} address '{wan_ip}/{wan_cidr_prefix}'\n"
    "set interfaces ethernet {wan_if} description 'WAN1'\n"
    "set interfaces ethernet {lan_if} address '{lan_ip}/{lan_cidr_prefix}'\n"
    "set interfaces ethernet {lan_if} description 'LAN1'\n"
    "set interfaces loopback lo\n"
    "set interfaces tunnel {main_nat_tun_id} address '{main_nat_tun_ce_ip}/30'\n"
    "set interfaces tunnel {main_nat_tun_id} description 'main-{main_nat_pe}-{main_nat_tun_num}'\n"
    "set interfaces tunnel {main_nat_tun_id} encapsulation 'gre'\n"
    "set interfaces tunnel {main_nat_tun_id} ip adjust-mss '1300'\n"
    "set interfaces tunnel {main_nat_tun_id} mtu '1452'\n"
    "set interfaces tunnel {main_nat_tun_id} remote '{main_nat_pe_docking}'\n"
    "set interfaces tunnel {main_nat_tun_id} source-address '{ce_loip}'\n"
    "set interfaces tunnel {bk_nat_tun_id} address '{bk_nat_tun_ce_ip}/30'\n"
    "set interfaces tunnel {bk_nat_tun_id} description 'back-{bk_nat_pe}-{bk_nat_tun_num}'\n"
    "set interfaces tunnel {bk_nat_tun_id} encapsulation 'gre'\n"
    "set interfaces tunnel {bk_nat_tun_id} ip adjust-mss '1300'\n"
    "set interfaces tunnel {bk_nat_tun_id} mtu '1452'\n"
    "set interfaces tunnel {bk_nat_tun_id} remote '{bk_nat_pe_docking}'\n"
    "set interfaces tunnel {bk_nat_tun_id} source-address '{ce_loip}'\n"
    "set interfaces tunnel {main_ipsec_tun_id} address '{main_ipsec_tun_ce_ip}/30'\n"
    "set interfaces tunnel {main_ipsec_tun_id} description 'main-{main_ipsec_pe}-{main_ipsec_tun_num}'\n"
    "set interfaces tunnel {main_ipsec_tun_id} encapsulation 'gre'\n"
    "set interfaces tunnel {main_ipsec_tun_id} ip adjust-mss '1300'\n"
    "set interfaces tunnel {main_ipsec_tun_id} mtu '1476'\n"
    "set interfaces tunnel {main_ipsec_tun_id} remote '{main_ipsec_docking_ip}'\n"
    "set interfaces tunnel {main_ipsec_tun_id} source-address '{main_ipsec_loop_ip}'\n"
    "set interfaces tunnel {bk_ipsec_tun_id} address '{bk_ipsec_tun_ce_ip}/30'\n"
    "set interfaces tunnel {bk_ipsec_tun_id} description 'backup-{bk_ipsec_pe}-{bk_ipsec_tun_num}'\n"
    "set interfaces tunnel {bk_ipsec_tun_id} encapsulation 'gre'\n"
    "set interfaces tunnel {bk_ipsec_tun_id} ip adjust-mss '1300'\n"
    "set interfaces tunnel {bk_ipsec_tun_id} mtu '1476'\n"
    "set interfaces tunnel {bk_ipsec_tun_id} remote '{bk_ipsec_docking_ip}'\n"
    "set interfaces tunnel {bk_ipsec_tun_id} source-address '{bk_ipsec_loop_ip}'\n"
    "set nat source rule 10 destination address '{main_ipsec_docking_ip}'\n"
    "set nat source rule 10 exclude\n"
    "set nat source rule 10 outbound-interface name '{wan_if}'\n"
    "set nat source rule 20 destination address '{bk_ipsec_docking_ip}'\n"
    "set nat source rule 20 exclude\n"
    "set nat source rule 20 outbound-interface name '{wan_if}'\n"
    "set nat source rule 50 outbound-interface name '{wan_if}'\n"
    "set nat source rule 50 source group network-group 'LAN-NET'\n"
    "set nat source rule 50 translation address 'masquerade'\n"
    "set nat source rule 1001 outbound-interface name '{main_nat_tun_id}'\n"
    "set nat source rule 1001 source group network-group 'LAN-NET'\n"
    "set nat source rule 1001 translation address '{main_nat_usip}'\n"
    "set nat source rule 2001 outbound-interface name '{bk_nat_tun_id}'\n"
    "set nat source rule 2001 source group network-group 'LAN-NET'\n"
    "set nat source rule 2001 translation address '{bk_nat_usip}'\n"
    "set nat source rule 5001 destination group address-group 'DNS-NET'\n"
    "set nat source rule 5001 outbound-interface name '{main_nat_tun_id}'\n"
    "set nat source rule 5001 translation address '{main_nat_usip}'\n"
    "set nat source rule 6001 destination group address-group 'DNS-NET'\n"
    "set nat source rule 6001 outbound-interface name '{bk_nat_tun_id}'\n"
    "set nat source rule 6001 translation address '{bk_nat_usip}'\n"
    "{pki_block}"
    "set policy community-list 80 rule 10 action 'permit'\n"
    "set policy community-list 80 rule 10 description 'to_hk'\n"
    "set policy community-list 80 rule 10 regex '65000:9939'\n"
    "set policy community-list 81 rule 10 action 'permit'\n"
    "set policy community-list 81 rule 10 description 'to_ct'\n"
    "set policy community-list 81 rule 10 regex '65000:4134'\n"
    "set policy community-list 82 rule 10 action 'permit'\n"
    "set policy community-list 82 rule 10 description 'to_cnc'\n"
    "set policy community-list 82 rule 10 regex '65000:4837'\n"
    "set policy community-list 83 rule 10 action 'permit'\n"
    "set policy community-list 83 rule 10 description 'to_cn_other'\n"
    "set policy community-list 83 rule 10 regex '65000:9808'\n"
    "set policy community-list 85 rule 10 action 'permit'\n"
    "set policy community-list 85 rule 10 description 'to_deny'\n"
    "set policy community-list 85 rule 10 regex '65000:9807'\n"
    "set policy community-list 88 rule 10 action 'permit'\n"
    "set policy community-list 88 rule 10 description 'to_google'\n"
    "set policy community-list 88 rule 10 regex '65000:9008'\n"
    "set policy community-list 91 rule 10 action 'permit'\n"
    "set policy community-list 91 rule 10 description 'to_Microsoft'\n"
    "set policy community-list 91 rule 10 regex '65000:9009'\n"
    "set policy local-route rule 2180 set table '180'\n"
    "set policy local-route rule 2180 source address '{main_nat_tun_ce_ip}'\n"
    "set policy local-route rule 2181 set table '181'\n"
    "set policy local-route rule 2181 source address '{bk_nat_tun_ce_ip}'\n"
    "set policy route-map bgp-from--RSVR rule 80 action 'permit'\n"
    "set policy route-map bgp-from--RSVR rule 80 match community community-list '80'\n"
    "set policy route-map bgp-from--RSVR rule 80 set ip-next-hop '{main_nat_tun_pe_ip}'\n"
    "set policy route-map bgp-from--RSVR rule 80 set local-preference '200'\n"
    "set policy route-map bgp-from--RSVR rule 81 action 'permit'\n"
    "set policy route-map bgp-from--RSVR rule 81 match community community-list '81'\n"
    "set policy route-map bgp-from--RSVR rule 81 set ip-next-hop '1.1.1.1'\n"
    "set policy route-map bgp-from--RSVR rule 81 set local-preference '200'\n"
    "set policy route-map bgp-from--RSVR rule 82 action 'permit'\n"
    "set policy route-map bgp-from--RSVR rule 82 match community community-list '82'\n"
    "set policy route-map bgp-from--RSVR rule 82 set ip-next-hop '1.1.1.1'\n"
    "set policy route-map bgp-from--RSVR rule 82 set local-preference '200'\n"
    "set policy route-map bgp-from--RSVR rule 83 action 'permit'\n"
    "set policy route-map bgp-from--RSVR rule 83 match community community-list '83'\n"
    "set policy route-map bgp-from--RSVR rule 83 set ip-next-hop '1.1.1.1'\n"
    "set policy route-map bgp-from--RSVR rule 83 set local-preference '200'\n"
    "set policy route-map bgp-from--RSVR2 rule 80 action 'permit'\n"
    "set policy route-map bgp-from--RSVR2 rule 80 match community community-list '80'\n"
    "set policy route-map bgp-from--RSVR2 rule 80 set ip-next-hop '{bk_nat_tun_pe_ip}'\n"
    "set policy route-map bgp-from--RSVR2 rule 80 set local-preference '50'\n"
    "set policy route-map bgp-from--RSVR2 rule 81 action 'permit'\n"
    "set policy route-map bgp-from--RSVR2 rule 81 match community community-list '81'\n"
    "set policy route-map bgp-from--RSVR2 rule 81 set ip-next-hop '1.1.1.1'\n"
    "set policy route-map bgp-from--RSVR2 rule 81 set local-preference '50'\n"
    "set policy route-map bgp-from--RSVR2 rule 82 action 'permit'\n"
    "set policy route-map bgp-from--RSVR2 rule 82 match community community-list '82'\n"
    "set policy route-map bgp-from--RSVR2 rule 82 set ip-next-hop '1.1.1.1'\n"
    "set policy route-map bgp-from--RSVR2 rule 82 set local-preference '50'\n"
    "set policy route-map bgp-from--RSVR2 rule 83 action 'permit'\n"
    "set policy route-map bgp-from--RSVR2 rule 83 match community community-list '83'\n"
    "set policy route-map bgp-from--RSVR2 rule 83 set ip-next-hop '1.1.1.1'\n"
    "set policy route-map bgp-from--RSVR2 rule 83 set local-preference '50'\n"
    "set policy route-map deny-any-out rule 1000 action 'deny'\n"
    "set policy route-map deny-any-out rule 1000 description 'to_bgpserver'\n"
    "set protocols bgp neighbor {nat_main_bgp2} peer-group 'RSVR'\n"
    "set protocols bgp neighbor {nat_bk_bgp2} peer-group 'RSVR2'\n"
    "set protocols bgp neighbor {nat_main_bgp1} peer-group 'RSVR'\n"
    "set protocols bgp neighbor {nat_bk_bgp1} peer-group 'RSVR2'\n"
    "set protocols bgp parameters router-id '{router_id}'\n"
    "set protocols bgp peer-group RSVR address-family ipv4-unicast route-map export 'deny-any-out'\n"
    "set protocols bgp peer-group RSVR address-family ipv4-unicast route-map import 'bgp-from--RSVR'\n"
    "set protocols bgp peer-group RSVR address-family ipv4-unicast soft-reconfiguration inbound\n"
    "set protocols bgp peer-group RSVR remote-as '65000'\n"
    "set protocols bgp peer-group RSVR update-source '{main_nat_usip}'\n"
    "set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map export 'deny-any-out'\n"
    "set protocols bgp peer-group RSVR2 address-family ipv4-unicast route-map import 'bgp-from--RSVR2'\n"
    "set protocols bgp peer-group RSVR2 address-family ipv4-unicast soft-reconfiguration inbound\n"
    "set protocols bgp peer-group RSVR2 remote-as '65000'\n"
    "set protocols bgp peer-group RSVR2 update-source '{bk_nat_usip}'\n"
    "set protocols bgp system-as '65000'\n"
    "set protocols bgp timers holdtime '15'\n"
    "set protocols bgp timers keepalive '5'\n"
    "set protocols failover2 track tomain source-address '{main_ipsec_tun_ce_ip}'\n"
    "set protocols failover2 track tomain target '{main_ipsec_tun_pe_ip}'\n"
    "set protocols failover2 track tomain type 'icmp'\n"
    "\n"
    "# Track route: UPE (track tomain) / UPE (distance 10 fallback)\n"
    "set protocols failover2 route 192.168.55.250/32 next-hop '{main_ipsec_tun_pe_ip}' track 'tomain'\n"
    "set protocols static route 192.168.55.250/32 next-hop '{bk_ipsec_tun_pe_ip}' distance '10'\n"
    "set protocols failover2 route 192.168.237.28/32 next-hop '{main_ipsec_tun_pe_ip}' track 'tomain'\n"
    "set protocols static route 192.168.237.28/32 next-hop '{bk_ipsec_tun_pe_ip}' distance '10'\n"
    "\n"
    "# ── 默认路由 ──\n"
    "{default_route_block}\n"
    "\n"
    "# ── IPSec 上游路由（拨号 IP / docking / CE loopback）──\n"
    "{ipsec_routes_block}\n"
    "\n"
    "# ── NAT/GRE 上游路由（NAT PE docking / 探测点）──\n"
    "{nat_routes_block}\n"
    "\n"
    "# ── BGP 服务器路由（next-hop + blackhole 保护）──\n"
    "{bgp_server_routes_block}\n"
    "\n"
    "# ── 内网防泄漏（来自 WAN/LAN 内网段配置）──\n"
    "{bypass_block}\n"
    "\n"
    "# ── PBR 分表默认路由 ──\n"
    "{pbr_tables_block}\n"
    "set service dns forwarding allow-from '0.0.0.0/0'\n"
    "set service dns forwarding cache-size '20000'\n"
    "set service dns forwarding dnssec 'off'\n"
    "set service dns forwarding domain-list CN file '/config/user-data/cn.txt'\n"
    "set service dns forwarding domain-list CN name-server 223.5.5.5\n"
    "set service dns forwarding domain-list CN name-server 223.6.6.6\n"
    "set service dns forwarding domain-list CN recursion-desired\n"
    "set service dns forwarding domain-list HK file '/config/user-data/oversea.txt'\n"
    "set service dns forwarding domain-list HK name-server 8.8.4.4\n"
    "set service dns forwarding domain-list HK name-server 8.8.8.8\n"
    "set service dns forwarding domain-list HK recursion-desired\n"
    "set service dns forwarding listen-address '0.0.0.0'\n"
    "set service dns forwarding name-server 8.8.4.4\n"
    "set service dns forwarding name-server 8.8.8.8\n"
    "set service file-sync task 1 local '/config/user-data/cn.txt'\n"
    "set service file-sync task 1 remote 'http://183.56.161.82:1909/f32x/domainlist/cn_domainlist.last'\n"
    "set service file-sync task 2 local '/config/user-data/oversea.txt'\n"
    "set service file-sync task 2 remote 'http://183.56.161.82:1909/f32x/domainlist/oversea_domainlist.last'\n"
    "set service ntp allow-client address '127.0.0.0/8'\n"
    "set service ntp allow-client address '169.254.0.0/16'\n"
    "set service ntp allow-client address '10.0.0.0/8'\n"
    "set service ntp allow-client address '172.16.0.0/12'\n"
    "set service ntp allow-client address '192.168.0.0/16'\n"
    "set service ntp server 192.168.55.250\n"
    "set service ntp server 202.104.174.178\n"
    "set service ntp server time1.vyos.net\n"
    "set service ntp server time2.vyos.net\n"
    "set service ntp server time3.vyos.net\n"
    "set service snmp community both-win authorization 'ro'\n"
    "set service ssh disable-host-validation\n"
    "set service ssh port '2707'\n"
    "set system config-management commit-revisions '100'\n"
    "set system console device ttyS0 speed '115200'\n"
    "set system host-name '{hostname}'\n"
    "set system login operator-group default command-policy allow '*'\n"
    "set system login user bothwin authentication plain Tfe28@w%\n"
    "set system name-server '127.0.0.1'\n"
    "set system option performance 'network-throughput'\n"
    "set system option reboot-on-upgrade-failure '5'\n"
    "set system syslog local facility all level 'info'\n"
    "set system syslog local facility local7 level 'debug'\n"
    "set system time-zone 'Asia/Hong_Kong'\n"
    "set vpn ipsec authentication psk ipsec id '0.0.0.0'\n"
    "set vpn ipsec authentication psk ipsec secret '{main_ipsec_secret}'\n"
    "set vpn ipsec esp-group ESP-FNET-1 lifetime '{esp_lifetime}'\n"
    "set vpn ipsec esp-group ESP-FNET-1 mode 'tunnel'\n"
    "set vpn ipsec esp-group ESP-FNET-1 proposal 1 encryption '{esp_encryption}'\n"
    "set vpn ipsec esp-group ESP-FNET-1 proposal 1 hash '{esp_hash}'\n"
    "set vpn ipsec esp-group ESP-FNET-2 lifetime '{esp_lifetime}'\n"
    "set vpn ipsec esp-group ESP-FNET-2 mode 'tunnel'\n"
    "set vpn ipsec esp-group ESP-FNET-2 proposal 1 encryption '{esp_encryption}'\n"
    "set vpn ipsec esp-group ESP-FNET-2 proposal 1 hash '{esp_hash}'\n"
    "set vpn ipsec ike-group IKE-FNET-1 disable-mobike\n"
    "set vpn ipsec ike-group IKE-FNET-1 key-exchange '{ike_key_exchange}'\n"
    "set vpn ipsec ike-group IKE-FNET-1 lifetime '{ike_lifetime}'\n"
    "set vpn ipsec ike-group IKE-FNET-1 proposal 1 dh-group '{ike_dh_group}'\n"
    "set vpn ipsec ike-group IKE-FNET-1 proposal 1 encryption '{ike_encryption}'\n"
    "set vpn ipsec ike-group IKE-FNET-1 proposal 1 hash '{ike_hash}'\n"
    "{bk_ike_dpd_block}"
    "set vpn ipsec ike-group IKE-FNET-2 disable-mobike\n"
    "set vpn ipsec ike-group IKE-FNET-2 key-exchange '{ike_key_exchange}'\n"
    "set vpn ipsec ike-group IKE-FNET-2 lifetime '{ike_lifetime}'\n"
    "set vpn ipsec ike-group IKE-FNET-2 proposal 1 dh-group '{ike_dh_group}'\n"
    "set vpn ipsec ike-group IKE-FNET-2 proposal 1 encryption '{ike_encryption}'\n"
    "set vpn ipsec ike-group IKE-FNET-2 proposal 1 hash '{ike_hash}'\n"
    "set vpn ipsec interface '{wan_if}'\n"
    "set vpn ipsec options retransmission base '1'\n"
    "set vpn ipsec options retransmission timeout '4'\n"
    "set vpn ipsec site-to-site peer backup authentication mode 'pre-shared-secret'\n"
    "set vpn ipsec site-to-site peer backup connection-type 'initiate'\n"
    "set vpn ipsec site-to-site peer backup default-esp-group 'ESP-FNET-2'\n"
    "set vpn ipsec site-to-site peer backup force-udp-encapsulation\n"
    "set vpn ipsec site-to-site peer backup ike-group 'IKE-FNET-2'\n"
    "set vpn ipsec site-to-site peer backup ikev2-reauth 'inherit'\n"
    "set vpn ipsec site-to-site peer backup local-address '{wan_ip}'\n"
    "set vpn ipsec site-to-site peer backup remote-address '{bk_ipsec_dial_ip}'\n"
    "set vpn ipsec site-to-site peer backup tunnel 1 local prefix '{bk_ipsec_loop_ip}/32'\n"
    "set vpn ipsec site-to-site peer backup tunnel 1 remote prefix '{bk_ipsec_docking_ip}/32'\n"
    "set vpn ipsec site-to-site peer main authentication mode 'pre-shared-secret'\n"
    "set vpn ipsec site-to-site peer main connection-type 'initiate'\n"
    "set vpn ipsec site-to-site peer main default-esp-group 'ESP-FNET-1'\n"
    "set vpn ipsec site-to-site peer main force-udp-encapsulation\n"
    "set vpn ipsec site-to-site peer main ike-group 'IKE-FNET-1'\n"
    "set vpn ipsec site-to-site peer main ikev2-reauth 'inherit'\n"
    "set vpn ipsec site-to-site peer main local-address '{wan_ip}'\n"
    "set vpn ipsec site-to-site peer main remote-address '{main_ipsec_dial_ip}'\n"
    "set vpn ipsec site-to-site peer main tunnel 1 local prefix '{main_ipsec_loop_ip}/32'\n"
    "set vpn ipsec site-to-site peer main tunnel 1 remote prefix '{main_ipsec_docking_ip}/32'\n"
    "# end\n"
)


def build_epoch5_us_ipsec_format_dict(hdr_text: str):
    """组装 TEMPLATE_EPOCH5_US_IPSEC.format(**d) 所需的 dict。"""
    g = globals()
    wan_cidr = str(g.get("DEFAULT_WAN_CIDR", "")).strip()
    lan_cidr = str(g.get("DEFAULT_LAN_CIDR", "")).strip()
    wan_gw = str(g.get("DEFAULT_WAN_GW", "")).strip()
    wan_dhcp = bool(g.get("DEFAULT_WAN_DHCP", False))
    inner_nets_raw = str(g.get("DEFAULT_INNER_NETS", "")).strip()

    ok_wan, msg_wan = _validate_cidr(wan_cidr, "WAN IP")
    ok_lan, msg_lan = _validate_cidr(lan_cidr, "LAN IP")
    inner_nets, inner_errors = _validate_inner_nets(inner_nets_raw)
    errs = []
    if not ok_wan:
        errs.append(msg_wan)
    if not ok_lan:
        errs.append(msg_lan)
    if not wan_gw and not wan_dhcp:
        errs.append("WAN 网关不能为空（除非启用 WAN DHCP）")
    for frag, reason in inner_errors:
        errs.append(f"内网段「{frag}」不符合网络标准：{reason}")
    if not inner_nets:
        errs.append("内网段不能为空：默认应包含 10.0.0.0/8、172.16.0.0/12、192.168.0.0/16")
    if errs:
        return None, ("network", errs)

    parsed, perr = _parse_ipsec_us(hdr_text)
    if perr:
        return None, ("parse", perr)

    im = parsed["ipsec_main"]
    ib = parsed["ipsec_bk"]
    nm = parsed["nat_main"]
    nb = parsed["nat_bk"]

    for label, block, fields in (
        ("IPSec 主线", im, [
            ("lineid", "LineID"), ("pe", "PE"), ("tun_id", "Tunnel"),
            ("wanip", "wanip"), ("pe_docking", "PE 对接"), ("loop_ip", "LoopIP"),
            ("dial_ip", "拨号ip"), ("secret", "秘钥"), ("tun_ce_ip", "wanip(/30 CE)"),
            ("tun_pe_ip", "wanip(/30 PE)"),
        ]),
        ("IPSec 备线", ib, [
            ("lineid", "LineID"), ("pe", "PE"), ("tun_id", "Tunnel"),
            ("wanip", "wanip"), ("pe_docking", "PE 对接"), ("loop_ip", "LoopIP"),
            ("dial_ip", "拨号ip"), ("secret", "秘钥"), ("tun_ce_ip", "wanip(/30 CE)"),
            ("tun_pe_ip", "wanip(/30 PE)"),
        ]),
        ("NAT 主线", nm, [
            ("lineid", "LineID"), ("pe", "PE"), ("tun_id", "TUNNEL"),
            ("wanip", "WANIP"), ("pe_docking", "PE Docking"), ("usip", "海外出口ip"),
            ("bgp1", "BGPSERVER IP[1]"), ("bgp2", "BGPSERVER IP[2]"),
            ("tun_ce_ip", "WANIP(/30 CE)"), ("tun_pe_ip", "WANIP(/30 PE)"),
        ]),
        ("NAT 备线", nb, [
            ("lineid", "LineID"), ("pe", "PE"), ("tun_id", "TUNNEL"),
            ("wanip", "WANIP"), ("pe_docking", "PE Docking"), ("usip", "海外出口ip"),
            ("bgp1", "BGPSERVER IP[1]"), ("bgp2", "BGPSERVER IP[2]"),
            ("tun_ce_ip", "WANIP(/30 CE)"), ("tun_pe_ip", "WANIP(/30 PE)"),
        ]),
    ):
        msg = _require_fields(block, fields, label)
        if msg:
            return None, ("parse", msg)

    ce_loip = im.get("ce_loip") or ""
    if not ce_loip:
        return None, ("parse", "IPSec 主线缺少字段：客户内网路由")

    warning = ""
    has_ike = bool(im.get("ike_key_exchange") or ib.get("ike_key_exchange"))
    has_esp = bool(im.get("esp_encryption") or ib.get("esp_encryption"))
    if not has_ike and not has_esp:
        warning = "未检测到IKE/IPSec参数，已按默认参数生成，请自行检查。"

    src = im if im.get("ike_key_exchange") else ib
    ike_key_exchange = _ipsec_first_token(src.get("ike_key_exchange"), "ikev1")
    ike_dh_group = src.get("ike_dh_group") or "2"
    ike_encryption = _ipsec_first_token(src.get("ike_encryption"), "aes128")
    ike_hash = src.get("ike_hash") or "sha1"
    esp_encryption = _ipsec_first_token(
        im.get("esp_encryption") or ib.get("esp_encryption"), "aes128"
    )
    esp_hash = (im.get("esp_hash") or ib.get("esp_hash") or "sha1")

    wan_eth = str(g.get("DEFAULT_WAN_ETH", "0")).strip() or "0"
    lan_eth = str(g.get("DEFAULT_LAN_ETH", "5")).strip() or "5"
    wan_ip = wan_cidr.split("/")[0]
    lan_ip = lan_cidr.split("/")[0]
    wan_cidr_prefix = str(ipaddress.ip_network(wan_cidr, strict=False).prefixlen)
    lan_cidr_prefix = str(ipaddress.ip_network(lan_cidr, strict=False).prefixlen)
    wan_if = f"eth{wan_eth}" if not wan_eth.startswith("eth") else wan_eth
    lan_if = f"eth{lan_eth}" if not lan_eth.startswith("eth") else lan_eth

    hn = str(g.get("DEFAULT_HOSTNAME", "")).strip()
    if not hn:
        hn = _extract_lineid(hdr_text) or "请填写Hostname"

    if _EPOCH5_PKI_SECRET_KEY:
        pki_block = (
            f"set pki openvpn shared-secret openvpn_secret key '{_EPOCH5_PKI_SECRET_KEY}'\n"
            "set pki openvpn shared-secret openvpn_secret version '1'\n"
        )
    else:
        pki_block = ""

    # ── LAN-NET：来自统一的内网段配置 ──
    lan_net_block = "\n".join(
        f"set firewall group network-group LAN-NET network '{net}'"
        for net in inner_nets
    )

    # ── 默认路由（受 WAN DHCP 影响）──
    if wan_dhcp:
        default_route_block = "# WAN DHCP 模式 — 不生成默认静态路由"
    else:
        default_route_block = (
            f"set protocols static route 0.0.0.0/0 next-hop 1.1.1.1 distance '220'\n"
            f"set protocols static route 1.1.1.1/32 next-hop {wan_gw}"
        )

    # ── IPSec 上游路由（拨号、docking、CE loopback）──
    ipsec_route_lines = [
        f"set protocols static route {im['docking_ip']}/32 next-hop 1.1.1.1",
        f"set protocols static route {ib['docking_ip']}/32 next-hop 1.1.1.1",
        f"set protocols static route {im['dial_ip']}/32 next-hop 1.1.1.1",
    ]
    if wan_gw:
        ipsec_route_lines.append(
            f"set protocols static route {ib['dial_ip']}/32 next-hop {wan_gw}"
        )
    else:
        ipsec_route_lines.append(
            f"set protocols static route {ib['dial_ip']}/32 next-hop 1.1.1.1"
        )
    ipsec_routes_block = "\n".join(ipsec_route_lines)

    # ── NAT/GRE 上游路由（NAT PE docking 走对应 IPSec PE；4.2.2.1 探测）──
    nat_routes_block = "\n".join([
        f"set protocols static route {nm['pe_docking']}/32 next-hop {im['tun_pe_ip']}",
        f"set protocols static route {nb['pe_docking']}/32 next-hop {ib['tun_pe_ip']}",
    ])

    # ── BGP 服务器路由（每个 BGP IP 一组 next-hop + blackhole 保护）──
    bgp_lines = []
    for bgp in (nm["bgp1"], nm["bgp2"]):
        if bgp:
            bgp_lines.append(f"set protocols static route {bgp}/32 next-hop {nm['tun_pe_ip']}")
            bgp_lines.append(f"set protocols static route {bgp}/32 blackhole distance '10'")
    for bgp in (nb["bgp1"], nb["bgp2"]):
        if bgp:
            bgp_lines.append(f"set protocols static route {bgp}/32 next-hop {nb['tun_pe_ip']}")
            bgp_lines.append(f"set protocols static route {bgp}/32 blackhole distance '10'")
    bgp_server_routes_block = "\n".join(bgp_lines)

    # ── 内网防泄漏：与 LAN-NET 用相同的内网段集合 ──
    bypass_block = "\n".join(
        f"set protocols static route {net} next-hop 1.1.1.1"
        for net in inner_nets
    )

    # ── PBR 分表默认路由 ──
    pbr_tables_block = "\n".join([
        f"set protocols static table 180 route 0.0.0.0/0 next-hop {nm['tun_pe_ip']}",
        f"set protocols static table 181 route 0.0.0.0/0 next-hop {nb['tun_pe_ip']}",
    ])

    d = {
        "hostname": hn,
        "ce_loip": ce_loip,
        "main_ipsec_loop_ip": im["loop_ip"],
        "bk_ipsec_loop_ip": ib["loop_ip"],
        "main_nat_usip": nm["usip"],
        "bk_nat_usip": nb["usip"],
        "main_nat_public_ip": nm.get("public_ip", ""),
        "bk_nat_public_ip": nb.get("public_ip", ""),
        "wan_if": wan_if,
        "lan_if": lan_if,
        "wan_ip": wan_ip,
        "lan_ip": lan_ip,
        "wan_cidr_prefix": wan_cidr_prefix,
        "lan_cidr_prefix": lan_cidr_prefix,
        "wan_gw": wan_gw,
        "main_ipsec_tun_id": im["tun_id"],
        "main_ipsec_tun_num": im["tun_num"],
        "main_ipsec_tun_ce_ip": im["tun_ce_ip"],
        "main_ipsec_tun_pe_ip": im["tun_pe_ip"],
        "main_ipsec_pe": im["dial_pe"],
        "main_ipsec_docking_ip": im["docking_ip"],
        "main_ipsec_dial_ip": im["dial_ip"],
        "main_ipsec_secret": im["secret"],
        "bk_ipsec_tun_id": ib["tun_id"],
        "bk_ipsec_tun_num": ib["tun_num"],
        "bk_ipsec_tun_ce_ip": ib["tun_ce_ip"],
        "bk_ipsec_tun_pe_ip": ib["tun_pe_ip"],
        "bk_ipsec_pe": ib["dial_pe"],
        "bk_ipsec_docking_ip": ib["docking_ip"],
        "bk_ipsec_dial_ip": ib["dial_ip"],
        "main_nat_tun_id": nm["tun_id"],
        "main_nat_tun_num": nm["tun_num"],
        "main_nat_tun_ce_ip": nm["tun_ce_ip"],
        "main_nat_tun_pe_ip": nm["tun_pe_ip"],
        "main_nat_pe": nm["pe"],
        "main_nat_pe_docking": nm["pe_docking"],
        "bk_nat_tun_id": nb["tun_id"],
        "bk_nat_tun_num": nb["tun_num"],
        "bk_nat_tun_ce_ip": nb["tun_ce_ip"],
        "bk_nat_tun_pe_ip": nb["tun_pe_ip"],
        "bk_nat_pe": nb["pe"],
        "bk_nat_pe_docking": nb["pe_docking"],
        "nat_main_bgp1": nm["bgp1"],
        "nat_main_bgp2": nm["bgp2"],
        "nat_bk_bgp1": nb["bgp1"],
        "nat_bk_bgp2": nb["bgp2"],
        "router_id": nm["usip"],
        "ike_key_exchange": ike_key_exchange,
        "ike_dh_group": ike_dh_group,
        "ike_encryption": ike_encryption,
        "ike_hash": ike_hash,
        "ike_lifetime": "28800",
        "esp_encryption": esp_encryption,
        "esp_hash": esp_hash,
        "esp_lifetime": "3600",
        "bk_ike_dpd_block": _ipsec_ike_dpd_lines(ib.get("ike_dpd", ""), ib.get("ike_dpd_idle", "")),
        "pki_block": pki_block,
        "lan_net_block": lan_net_block,
        "default_route_block": default_route_block,
        "ipsec_routes_block": ipsec_routes_block,
        "nat_routes_block": nat_routes_block,
        "bgp_server_routes_block": bgp_server_routes_block,
        "bypass_block": bypass_block,
        "pbr_tables_block": pbr_tables_block,
    }
    return d, warning


def build_epoch5_hk_ipsec_format_dict(hdr_text: str):
    """HK IPSec — 正在开发中。"""
    return {}, "HK IPSec 正在开发中，暂不支持。请使用 OpenVPN。"

