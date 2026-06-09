#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 传统组网 — 双线 BGP+GRE+IPSec 华为 AR 配置生成工具 v1

- 双线组网：主线 + 备线，每条线含基本信息和拨号信息
- GRE 隧道固定 Tunnel0/0/1000（主）/ Tunnel0/0/2000（备）
- LoopBack 固定 1000（主）/ 2000（备）
- 隧道 source = LoopBack，destination = PE 对接 IP
- 无 BGP network 宣告，通过 import-route + route-policy 控制
- 内网段同时用于 ACL 2707、BGP prefix-list、静态路由
"""

import ipaddress
import re

# =====================================================================
# 公共工具（运行于 all_in_one_v2 时由 shared_utils 注入；独立运行时使用本地副本）
# =====================================================================
try:
    _get
except NameError:
    def _get(pattern, block, flags=re.IGNORECASE | re.MULTILINE):
        m = re.search(pattern, block, flags)
        return m.group(1).strip() if m else ""


    def wanip_hosts(cidr):
        """从 CIDR 网段获取前两个可用主机地址。"""
        try:
            hosts = list(ipaddress.ip_network(cidr.strip(), strict=False).hosts())
            if len(hosts) >= 2:
                return str(hosts[0]), str(hosts[1])
        except (ValueError, ipaddress.AddressValueError):
            pass
        return "", ""


try:
    field_coverage
except NameError:
    field_coverage = None

try:
    from user_activity_log import log_generate_config
except ImportError:
    def log_generate_config(**_kwargs):
        pass


# =====================================================================
# 内部工具函数
# =====================================================================
def _ip_plain(cidr):
    if not cidr:
        return ""
    return cidr.strip().split("/")[0]


def _cidr_mask(cidr):
    if not cidr:
        return ""
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
        return str(net.netmask)
    except (ValueError, ipaddress.AddressValueError):
        return ""


def _wildcard_mask(netmask):
    if not netmask:
        return ""
    try:
        parts = netmask.strip().split(".")
        return ".".join(str(255 - int(p)) for p in parts)
    except (ValueError, AttributeError):
        return ""


def _expand_if_name(name_or_num):
    s = (name_or_num or "").strip()
    if not s:
        return "GigabitEthernet0/0/0"
    if re.match(r"^GigabitEthernet\d+/\d+/\d+$", s, re.IGNORECASE):
        return s
    if re.match(r"^\d+/\d+/\d+$", s):
        return f"GigabitEthernet{s}"
    if re.match(r"^\d+$", s):
        return f"GigabitEthernet0/0/{s}"
    return s


# =====================================================================
# 示例数据
# =====================================================================
AR_TRAD_EXAMPLE = (
    "LineID:609498A1\n"
    "PE:szd-upe3\n"
    "Tunnel:Tunnel0/0/1978\n"
    "wanip:10.55.19.236/30\n"
    "PE 对接:10.200.200.37\n"
    "CE 对接:10.50.86.18\n"
    "PE AS号:65510\n"
    "CE AS号:65201\n"
    "自环网段:100.100.100.0/30\n"
    "\n"
    "拨号PE:szd-upe3\n"
    "对接IP:10.200.200.37\n"
    "LoopIP:10.50.86.18\n"
    "拨号ip:183.56.161.86\n"
    "秘钥:both-win\n"
    "\n"
    "LineID:609498A2\n"
    "PE:szc-upe1\n"
    "Tunnel:Tunnel0/0/1136\n"
    "wanip:10.30.36.216/30\n"
    "PE 对接:10.200.200.27\n"
    "CE 对接:10.50.118.34\n"
    "PE AS号:65107\n"
    "CE AS号:65201\n"
    "自环网段:备 100.100.101.0/30\n"
    "\n"
    "拨号PE:szc-upe1\n"
    "对接IP:10.200.200.27\n"
    "LoopIP:10.50.118.34\n"
    "拨号ip:120.133.134.72\n"
    "秘钥:both-win\n"
)


# =====================================================================
# 解析器
# =====================================================================
def parse_ar_traditional_headers(text):
    """解析 AR 传统组网数据头，提取主/备两条线的字段。"""
    if not text or not text.strip():
        return None, None, ("empty", "数据为空，请先输入业务数据")

    blocks = []
    for part in re.split(r"(?=^\s*LineID\s*[:：])", text.strip(), flags=re.MULTILINE):
        s = part.strip()
        if re.match(r"LineID\s*[:：]", s, re.IGNORECASE):
            blocks.append(s)

    if len(blocks) < 2:
        return None, None, ("count", f"需要 2 条线路数据（主/备），当前找到 {len(blocks)} 条")

    def _parse_one(block):
        lineid = _get(r"LineID\s*[:：]\s*([^\n]+)", block)
        pe = _get(r"^\s*PE\s*[:：]\s*([^\n]+)", block)
        tunnel = _get(r"^\s*Tunnel\s*[:：]\s*([^\n]+)", block)
        wanip = _get(r"^\s*wanip\s*[:：]\s*([^\n]+)", block)
        pe_docking = _get(r"PE\s*对接\s*[:：]\s*([^\n]+)", block)
        ce_docking = _get(r"CE\s*对接\s*[:：]\s*([^\n]+)", block)
        pe_as = _get(r"PE\s*AS号\s*[:：]\s*([^\n]+)", block)
        ce_as = _get(r"CE\s*AS号\s*[:：]\s*([^\n]+)", block)
        zihuan = _get(r"自环网段\s*[:：]\s*([^\n]+)", block)

        dial_pe = _get(r"拨号PE\s*[:：]\s*([^\n]+)", block)
        dial_docking_ip = _get(r"对接IP\s*[:：]\s*([^\n]+)", block)
        loop_ip = _get(r"LoopIP\s*[:：]\s*([^\n]+)", block)
        dial_ip = _get(r"拨号ip\s*[:：]\s*([^\n]+)", block)
        psk = _get(r"秘钥\s*[:：]\s*([^\n]+)", block) or "both-win"

        # 从 wanip CIDR 计算隧道两端 IP
        t_local, t_remote = wanip_hosts(wanip)

        return {
            "lineid": lineid, "pe": pe, "tunnel": tunnel, "wanip": wanip,
            "wan_ip_plain": _ip_plain(wanip),
            "pe_docking": pe_docking, "ce_docking": ce_docking,
            "pe_as": pe_as, "ce_as": ce_as, "zihuan": zihuan,
            "tunnel_local_ip": t_local, "tunnel_remote_ip": t_remote,
            "dial_pe": dial_pe, "dial_docking_ip": dial_docking_ip,
            "loop_ip": loop_ip, "dial_ip": dial_ip, "psk": psk,
        }

    main_line = _parse_one(blocks[0])
    backup_line = _parse_one(blocks[1])

    required = ["lineid", "pe", "tunnel", "wanip", "pe_docking",
                "ce_docking", "pe_as", "ce_as", "dial_ip"]
    for prefix, line in [("主线", main_line), ("备线", backup_line)]:
        for field in required:
            if not line.get(field):
                return main_line, backup_line, ("missing_field",
                    f"{prefix}缺少必填字段「{field}」，请检查输入数据")

    return main_line, backup_line, None


# =====================================================================
# 构建器
# =====================================================================
def build_ar_traditional_format_dict(main_line, backup_line, network=None):
    """根据解析后的主/备线路数据 + 网络参数构建模板格式化 dict。

    Args:
        main_line: 主线字段字典
        backup_line: 备线字段字典
        network: 网络参数字典。支持的键：
            hostname, wan_if, wan_ip, wan_mask, wan_gw,
            inner_nets（内网段，用于 BGP prefix-list + 静态路由）

    Returns:
        (dict, None) — 成功时返回格式字典；失败时返回 (None, (kind, message))。
    """
    if network is None:
        network = {}

    # ── 提取网络参数 ──
    hostname = (network.get("hostname") or "").strip()
    if not hostname:
        hostname = main_line.get("lineid", "") or "AR-TRAD"

    wan_if_name = _expand_if_name(
        network.get("wan_if") or network.get("wan_if_name")
        or network.get("wan_eth") or network.get("DEFAULT_WAN_ETH") or "9"
    )

    wan_ip = (network.get("wan_ip")
              or _ip_plain(network.get("wan_cidr") or network.get("DEFAULT_WAN_CIDR") or "")
              or "")
    wan_mask = (network.get("wan_mask")
                or _cidr_mask(network.get("wan_cidr") or network.get("DEFAULT_WAN_CIDR") or "")
                or "")

    wan_gw = (network.get("wan_gw") or network.get("DEFAULT_WAN_GW") or "")

    # 内网段（用于 BGP prefix-list + 静态路由）
    inner_nets_raw = (network.get("inner_nets")
                      or network.get("DEFAULT_INNER_NETS")
                      or "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16")
    inner_nets = []
    for token in re.split(r'[\n,，\s]+', inner_nets_raw):
        t = token.strip()
        if t:
            try:
                n = ipaddress.ip_network(t, strict=False)
                inner_nets.append(n)
            except (ValueError, ipaddress.AddressValueError):
                pass

    # ── 构建模板变量 ──
    d = {}

    # 主线数据头字段
    d["main_lineid"]     = main_line.get("lineid", "")
    d["main_pe"]         = main_line.get("pe", "")
    d["main_tunnel"]     = main_line.get("tunnel", "")       # 数据头里的 Tunnel 名，用于描述
    d["main_wanip"]      = main_line.get("wanip", "")
    d["main_wan_ip_plain"] = main_line.get("wan_ip_plain", "")
    d["main_pe_docking"] = main_line.get("pe_docking", "")   # GRE 隧道 destination
    d["main_ce_docking"] = main_line.get("ce_docking", "")   # LoopBack IP
    d["main_pe_as"]      = main_line.get("pe_as", "")
    d["main_ce_as"]      = main_line.get("ce_as", "")
    d["main_tunnel_local_ip"]  = main_line.get("tunnel_local_ip", "")
    d["main_tunnel_remote_ip"] = main_line.get("tunnel_remote_ip", "")
    d["main_dial_ip"]    = main_line.get("dial_ip", "")       # IKE peer remote-address
    d["main_psk"]        = main_line.get("psk", "")
    d["main_loop_ip"]    = main_line.get("loop_ip", "") or main_line.get("ce_docking", "")
    # loop_ip 是 LoopBack 的 IP = CE 对接 IP；如果没填就用 ce_docking

    # 备线数据头字段
    d["backup_lineid"]     = backup_line.get("lineid", "")
    d["backup_pe"]         = backup_line.get("pe", "")
    d["backup_tunnel"]     = backup_line.get("tunnel", "")
    d["backup_wanip"]      = backup_line.get("wanip", "")
    d["backup_wan_ip_plain"] = backup_line.get("wan_ip_plain", "")
    d["backup_pe_docking"] = backup_line.get("pe_docking", "")
    d["backup_ce_docking"] = backup_line.get("ce_docking", "")
    d["backup_pe_as"]      = backup_line.get("pe_as", "")
    d["backup_ce_as"]      = backup_line.get("ce_as", "")
    d["backup_tunnel_local_ip"]  = backup_line.get("tunnel_local_ip", "")
    d["backup_tunnel_remote_ip"] = backup_line.get("tunnel_remote_ip", "")
    d["backup_dial_ip"]    = backup_line.get("dial_ip", "")
    d["backup_psk"]        = backup_line.get("psk", "")
    d["backup_loop_ip"]    = backup_line.get("loop_ip", "") or backup_line.get("ce_docking", "")

    # 网络参数
    d["hostname"]   = hostname
    d["wan_if"]     = wan_if_name
    d["wan_ip"]     = wan_ip
    d["wan_mask"]   = wan_mask
    d["wan_gw"]     = wan_gw
    d["ce_as"]      = main_line.get("ce_as", "")
    d["bgp_router_id"] = main_line.get("tunnel_local_ip", "")

    # BGP peer = 各线远端 tunnel IP
    d["peer_main_ip"]   = main_line.get("tunnel_remote_ip", "")
    d["peer_main_as"]   = main_line.get("pe_as", "")
    d["peer_backup_ip"] = backup_line.get("tunnel_remote_ip", "")
    d["peer_backup_as"] = backup_line.get("pe_as", "")

    # ── 计算模板块 ──

    # --- WAN 接口块 ---
    d["wan_if_block"] = (
        f"interface {wan_if_name}\n"
        f" ip address {wan_ip} {wan_mask}\n"
        f" ipsec policy S2S-IPSEC"
    )

    # --- 静态路由块 ---
    static_lines = []
    if wan_gw:
        # 建立 IPSec 的 PE 路由（PE 对接 + 拨号 ip）
        if d["main_pe_docking"]:
            static_lines.append(
                f"ip route-static {d['main_pe_docking']} 255.255.255.255 "
                f"{wan_gw} tag 7777 description To_ipsec_main"
            )
        if d["main_dial_ip"]:
            static_lines.append(
                f"ip route-static {d['main_dial_ip']} 255.255.255.255 "
                f"{wan_gw} tag 7777 description To_ipsec_main"
            )
        if d["backup_pe_docking"]:
            static_lines.append(
                f"ip route-static {d['backup_pe_docking']} 255.255.255.255 "
                f"{wan_gw} tag 7777 description To_ipsec_back"
            )
        if d["backup_dial_ip"]:
            static_lines.append(
                f"ip route-static {d['backup_dial_ip']} 255.255.255.255 "
                f"{wan_gw} tag 7777 description To_ipsec_back"
            )

        # zabbix 路由（通过主/备 tunnel 远端 IP）
        _mt = d["main_tunnel_remote_ip"]
        _bt = d["backup_tunnel_remote_ip"]
        if _mt:
            static_lines.append(
                f"ip route-static 114.113.245.99 255.255.255.255 "
                f"{_mt} tag 7777 description zabbix_main"
            )
        if _bt:
            static_lines.append(
                f"ip route-static 114.113.245.100 255.255.255.255 "
                f"{_bt} tag 7777 description zabbix_backup"
            )

        # 跳板机路由（带 track nqa）
        if _mt:
            static_lines.append(
                f"ip route-static 192.168.55.250 255.255.255.255 "
                f"{_mt} tag 7777 track nqa admin ipsecmain description To_center"
            )
        if _bt:
            static_lines.append(
                f"ip route-static 192.168.55.250 255.255.255.255 "
                f"{_bt} preference 111 tag 7777 description To_center"
            )

        # portal 路由
        if _mt:
            static_lines.append(
                f"ip route-static 192.168.237.78 255.255.255.255 "
                f"{_mt} tag 7777 track nqa admin ipsecmain description To_Syslog"
            )
        if _bt:
            static_lines.append(
                f"ip route-static 192.168.237.78 255.255.255.255 "
                f"{_bt} preference 111 tag 7777 description To_Syslog"
            )
        if _mt:
            static_lines.append(
                f"ip route-static 192.168.237.86 255.255.255.255 "
                f"{_mt} tag 7777 track nqa admin ipsecmain description To_openfalcon"
            )
        if _bt:
            static_lines.append(
                f"ip route-static 192.168.237.86 255.255.255.255 "
                f"{_bt} preference 111 tag 7777 description To_openfalcon"
            )

        # 默认路由
        static_lines.append(
            f"ip route-static 0.0.0.0 0.0.0.0 {wan_gw} tag 7777"
        )

    # 内网路由（不走 tag，由 route-policy node 300 引入 BGP）
    for net in inner_nets:
        static_lines.append(
            f"ip route-static {net.network_address} {net.netmask} {wan_gw}"
        )

    d["static_routes_block"] = "\n".join(static_lines)

    # --- BGP filter prefix-list（从 inner_nets 生成） ---
    filter_lines = []
    idx = 10
    for net in inner_nets:
        filter_lines.append(
            f"ip ip-prefix bgp-filte-pre-export index {idx} "
            f"permit {net.network_address} {net.prefixlen}"
        )
        idx += 10
    d["bgp_filter_prefix_block"] = "\n".join(filter_lines)

    return d, None


# =====================================================================
# 模板
# =====================================================================
TEMPLATE_AR_TRADITIONAL = """\
#
sysname {hostname}
#
clock timezone bj add 08:00
#
ntp-service unicast-server 192.168.55.250
#
acl number 2707
 rule 10 permit source 192.168.0.0 0.0.0.255
 rule 20 permit source 172.16.0.0 0.15.255.255
 rule 30 permit source 10.0.0.0 0.255.255.255
 rule 40 permit source 114.112.238.8 0.0.0.7
 rule 50 permit source 192.168.55.250 0
 rule 60 permit source 113.105.190.147 0
 rule 70 permit source 202.104.174.178 0
 rule 80 permit source 120.76.31.146 0
 rule 90 permit source 59.37.126.140 0
 rule 100 permit source 183.61.239.168 0
#
acl number 3333
 rule 1 permit ip source {main_loop_ip} 0 destination {main_pe_docking} 0
acl number 3334
 rule 1 permit ip source {backup_loop_ip} 0 destination {backup_pe_docking} 0
#
ike proposal 10
 encryption-algorithm 3des
 dh group2
 authentication-algorithm sha1
 sa duration 28800
 authentication-method pre-share
 integrity-algorithm hmac-sha2-256
 prf hmac-sha2-256
#
ipsec proposal ipsectran1
 esp authentication-algorithm sha1
 esp encryption-algorithm 3des
#
ike peer main
 version 1
 undo version 2
 pre-shared-key cipher {main_psk}
 ike-proposal 10
 dpd idle-time 10
 dpd type on-demand
 dpd retransmit-interval 2
 remote-address {main_dial_ip}
#
ike peer backup
 version 1
 undo version 2
 pre-shared-key cipher {backup_psk}
 ike-proposal 10
 dpd idle-time 10
 dpd type on-demand
 dpd retransmit-interval 2
 remote-address {backup_dial_ip}
#
ipsec policy S2S-IPSEC 10 isakmp
 security acl 3333
 pfs dh-group2
 ike-peer main
 proposal ipsectran1
ipsec policy S2S-IPSEC 20 isakmp
 security acl 3334
 pfs dh-group2
 ike-peer backup
 proposal ipsectran1
#
interface LoopBack1000
 description To IPSec main
 ip address {main_loop_ip} 255.255.255.255
#
interface LoopBack2000
 description To IPSec backup
 ip address {backup_loop_ip} 255.255.255.255
#
interface Tunnel0/0/1000
 description 'pri to {main_pe} {main_tunnel}'
 ip address {main_tunnel_local_ip} 255.255.255.252
 tunnel-protocol gre
 source LoopBack1000
 destination {main_pe_docking}
 mtu 1476
 tcp adjust-mss 1300
#
interface Tunnel0/0/2000
 description 'back to {backup_pe} {backup_tunnel}'
 ip address {backup_tunnel_local_ip} 255.255.255.252
 tunnel-protocol gre
 source LoopBack2000
 destination {backup_pe_docking}
 mtu 1476
 tcp adjust-mss 1300
#
{wan_if_block}
#
nqa event 1 log
nqa test-instance admin ipsecmain
 test-type icmp
 destination-address ipv4 {main_tunnel_remote_ip}
 source-address ipv4 {main_tunnel_local_ip}
 frequency 15
 probe-count 2
 alarm 1 lost-packet-ratio absolute rising-threshold 100 1
 start now
nqa test-instance admin ipsecbackup
 test-type icmp
 destination-address ipv4 {backup_tunnel_remote_ip}
 source-address ipv4 {backup_tunnel_local_ip}
 frequency 15
 probe-count 2
 alarm 1 lost-packet-ratio absolute rising-threshold 100 1
 start now
#
{static_routes_block}
#
{bgp_filter_prefix_block}
#
route-policy bgp-To--VPN-Redistribute-Static deny node 100
 description Deny Redistribution of Static Routes to MPLS VPN
 if-match tag 7777
#
route-policy bgp-To--VPN-Redistribute-Static permit node 200
 if-match tag 8888
 apply community {ce_as}:100
#
route-policy bgp-To--VPN-Redistribute-Static permit node 300
 description Redistribute All Other Static Routes Without Tag
#
route-policy bgp-route-policy-pri-import permit node 100
 apply local-preference 200
#
route-policy bgp-route-policy-back-import permit node 100
 apply local-preference 50
#
bgp {ce_as}
 router-id {bgp_router_id}
 timer keepalive 5 hold 15
 peer {peer_main_ip} as-number {peer_main_as}
 peer {peer_backup_ip} as-number {peer_backup_as}
 #
 ipv4-family unicast
  undo synchronization
  preference 70 200 200
  filter-policy ip-prefix bgp-filte-pre-export export
  import-route direct
  import-route static route-policy bgp-To--VPN-Redistribute-Static
  peer {peer_main_ip} enable
  peer {peer_main_ip} ip-prefix bgp-filte-pre-export export
  peer {peer_main_ip} route-policy bgp-route-policy-pri-import import
  peer {peer_main_ip} advertise-community
  peer {peer_backup_ip} enable
  peer {peer_backup_ip} ip-prefix bgp-filte-pre-export export
  peer {peer_backup_ip} route-policy bgp-route-policy-back-import import
  peer {peer_backup_ip} advertise-community
#
snmp-agent trap enable
snmp-agent sys-info version all
snmp-agent community read both-win
#
info-center filter-id bymodule-alias NTP PACKET_LENGTH_WRONG
info-center source default channel 2 log level warning
info-center loghost 192.168.237.78
info-center logbuffer size 256
info-center timestamp log date precision-time millisecond
info-center timestamp trap date precision-time millisecond
#
stelnet server enable
ssh server port 2707
ssh server permit interface all
#
user-interface vty 0 4
 acl 2707 inbound
 authentication-mode aaa
 user privilege level 15
#
hwtacacs-server template fnetlink_tacacs
 hwtacacs-server authentication 192.168.55.250
 hwtacacs-server authorization 192.168.55.250
 hwtacacs-server accounting 192.168.55.250
 hwtacacs-server source-ip {main_tunnel_local_ip}
 hwtacacs-server shared-key cipher both-win
#
aaa
 local-user bothwin password irreversible-cipher Tfe28@w%
 local-user bothwin privilege level 15
 local-user bothwin service-type terminal ssh http
 local-user admin service-type terminal ssh http
 local-aaa-user password policy administrator
  password history record number 0
  password expire 0
 authentication-scheme fnet_tac
  authentication-mode hwtacacs local
 authorization-scheme fnet_tac
  authorization-mode hwtacacs local
  authorization-cmd 15 hwtacacs local
 accounting-scheme fnet_tac
  accounting-mode hwtacacs
  accounting start-fail online
 recording-scheme fnet_tac
  recording-mode hwtacacs fnetlink_tacacs
 cmd recording-scheme fnet_tac
 service-scheme fnet_tac
  admin-user privilege level 15
 domain fnet_tac
  authentication-scheme fnet_tac
  accounting-scheme fnet_tac
  authorization-scheme fnet_tac
  hwtacacs-server fnetlink_tacacs
 domain fnet_tac admin
#
ftp 59.36.7.222
 cd mplstools
 get mplsmain.py
 get mplsbackup.py
 ops install file mplsmain.py
 ops install file mplsbackup.py
#
ops
 script-assistant python mplsmain.py
 script-assistant python mplsbackup.py
 environment mainip {main_dial_ip}
 environment backupip {backup_dial_ip}
#
return
"""
