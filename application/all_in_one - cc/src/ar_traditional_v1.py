#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 传统组网 — 双线 BGP+GRE+IPSec 华为 AR 配置生成工具 v1

- 双线组网：主线 + 备线，每条线含基本信息和拨号信息
- 支持 GRE 隧道（LoopBack 作为源）、BGP、IPSec、ACL、静态路由
- 可被 all_in_one_v2 通过 exec() 加载，也可独立运行
"""

import ipaddress
import re

# =====================================================================
# 公共工具（运行于 all_in_one_v2 时由 shared_utils 注入；独立运行时使用本地副本）
# =====================================================================
try:
    _get  # 已由 all_in_one_v2 / shared_utils 注入
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
    field_coverage = None  # type: ignore

try:
    from user_activity_log import log_generate_config
except ImportError:
    def log_generate_config(**_kwargs):  # type: ignore[misc]
        pass


# =====================================================================
# 内部工具函数
# =====================================================================
def _ip_plain(cidr):
    """从 CIDR 字符串提取纯 IP（去掉掩码部分）。"""
    if not cidr:
        return ""
    return cidr.strip().split("/")[0]


def _cidr_mask(cidr):
    """从 CIDR 字符串获取点分十进制掩码。"""
    if not cidr:
        return ""
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
        return str(net.netmask)
    except (ValueError, ipaddress.AddressValueError):
        return ""


def _wildcard_mask(netmask):
    """将点分十进制掩码转为反掩码（wildcard mask）。"""
    if not netmask:
        return ""
    try:
        parts = netmask.strip().split(".")
        return ".".join(str(255 - int(p)) for p in parts)
    except (ValueError, AttributeError):
        return ""


def _cidr_network_ip(cidr):
    """从 CIDR 获取网络地址（如 192.168.1.0/24 → 192.168.1.0）。"""
    if not cidr:
        return ""
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
        return str(net.network_address)
    except (ValueError, ipaddress.AddressValueError):
        return ""


def _expand_if_name(name_or_num):
    """将接口名或编号展开为标准格式（如 '9' → 'GigabitEthernet0/0/9'）。

    如果已经是完整格式则不处理。
    """
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
    "PE:szd-upe4\n"
    "Tunnel:Tunnel0/0/1979\n"
    "wanip:10.55.19.240/30\n"
    "PE 对接:10.200.200.38\n"
    "CE 对接:10.50.86.19\n"
    "PE AS号:65510\n"
    "CE AS号:65201\n"
    "自环网段:100.100.100.4/30\n"
    "\n"
    "拨号PE:szd-upe4\n"
    "对接IP:10.200.200.38\n"
    "LoopIP:10.50.86.19\n"
    "拨号ip:183.56.161.87\n"
    "秘钥:both-win\n"
)


# =====================================================================
# 解析器
# =====================================================================
def parse_ar_traditional_headers(text):
    """解析 AR 传统组网数据头，提取主/备两条线的字段。

    Args:
        text: 包含两条 LineID 记录的原始文本。

    Returns:
        (main_line, backup_line, error) — error 为 None 表示成功，
        否则为 (kind, message) 元组。
    """
    if not text or not text.strip():
        return None, None, ("empty", "数据为空，请先输入业务数据")

    # 按 LineID 分块
    blocks = []
    for part in re.split(r"(?=^\s*LineID\s*[:：])", text.strip(), flags=re.MULTILINE):
        s = part.strip()
        if re.match(r"LineID\s*[:：]", s, re.IGNORECASE):
            blocks.append(s)

    if len(blocks) < 2:
        return None, None, ("count", f"需要 2 条线路数据（主/备），当前找到 {len(blocks)} 条")

    def _parse_one(block):
        """解析单个 LineID 块，返回字段字典。"""
        lineid = _get(r"LineID\s*[:：]\s*([^\n]+)", block)
        pe = _get(r"^\s*PE\s*[:：]\s*([^\n]+)", block)
        tunnel = _get(r"^\s*Tunnel\s*[:：]\s*([^\n]+)", block)
        wanip = _get(r"^\s*wanip\s*[:：]\s*([^\n]+)", block)
        pe_docking = _get(r"PE\s*对接\s*[:：]\s*([^\n]+)", block)
        ce_docking = _get(r"CE\s*对接\s*[:：]\s*([^\n]+)", block)
        pe_as = _get(r"PE\s*AS号\s*[:：]\s*([^\n]+)", block)
        ce_as = _get(r"CE\s*AS号\s*[:：]\s*([^\n]+)", block)
        zihuan = _get(r"自环网段\s*[:：]\s*([^\n]+)", block)

        # 拨号信息
        dial_pe = _get(r"拨号PE\s*[:：]\s*([^\n]+)", block)
        dial_docking_ip = _get(r"对接IP\s*[:：]\s*([^\n]+)", block)
        loop_ip = _get(r"LoopIP\s*[:：]\s*([^\n]+)", block)
        dial_ip = _get(r"拨号ip\s*[:：]\s*([^\n]+)", block)
        psk = _get(r"秘钥\s*[:：]\s*([^\n]+)", block) or "both-win"

        # 从 wanip CIDR 计算隧道两端 IP（CE 侧 = 第一个 host，PE 侧 = 第二个 host）
        t_local, t_remote = wanip_hosts(wanip)

        return {
            "lineid": lineid,
            "pe": pe,
            "tunnel": tunnel,
            "wanip": wanip,
            "wan_ip_plain": _ip_plain(wanip),
            "pe_docking": pe_docking,
            "ce_docking": ce_docking,
            "pe_as": pe_as,
            "ce_as": ce_as,
            "zihuan": zihuan,
            "tunnel_local_ip": t_local,
            "tunnel_remote_ip": t_remote,
            "dial_pe": dial_pe,
            "dial_docking_ip": dial_docking_ip,
            "loop_ip": loop_ip,
            "dial_ip": dial_ip,
            "psk": psk,
        }

    main_line = _parse_one(blocks[0])
    backup_line = _parse_one(blocks[1])

    # 校验必需字段
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
        main_line: 主线字段字典（parse_ar_traditional_headers 返回的 main）。
        backup_line: 备线字段字典。
        network: 网络参数字典，包含：
            - hostname: 设备名
            - wan_if_name / wan_if_num: WAN 接口
            - lan_if_name / lan_if_num: LAN 接口
            - wan_ip / wan_mask: WAN IP + 掩码
            - lan_ip / lan_mask: LAN IP + 掩码
            - wan_gw / lan_gw: WAN / LAN 网关
            - bgp_networks: BGP 发布网段列表
            - bypass: 是否旁挂模式
            - gen_return_route: 是否生成回程路由
            也兼容 web app 注入的 DEFAULT_* 前缀键名。

    Returns:
        (dict, None) — 成功时返回格式字典；失败时返回 (None, (kind, message))。
    """
    if network is None:
        network = {}

    # ── 从 network dict 提取参数 ──
    hostname = (network.get("hostname") or network.get("DEFAULT_HOSTNAME") or "").strip()
    if not hostname:
        hostname = main_line.get("lineid", "") or "AR-TRAD"

    wan_if_name = (network.get("wan_if_name")
                   or network.get("wan_eth")
                   or network.get("DEFAULT_WAN_ETH")
                   or network.get("wan_if_num")
                   or "0")
    wan_if_name = _expand_if_name(wan_if_name)

    lan_if_name = (network.get("lan_if_name")
                   or network.get("lan_eth")
                   or network.get("DEFAULT_LAN_ETH")
                   or network.get("lan_if_num")
                   or "1")
    lan_if_name = _expand_if_name(lan_if_name)

    wan_cidr = (network.get("wan_cidr")
                or network.get("DEFAULT_WAN_CIDR")
                or "")
    wan_ip = _ip_plain(wan_cidr)
    wan_mask = _cidr_mask(wan_cidr)

    lan_cidr = (network.get("lan_cidr")
                or network.get("DEFAULT_LAN_CIDR")
                or "")
    lan_ip = _ip_plain(lan_cidr)
    lan_mask = _cidr_mask(lan_cidr)

    wan_gw = (network.get("wan_gw")
              or network.get("DEFAULT_WAN_GW")
              or "")
    lan_gw = (network.get("lan_gw")
              or network.get("DEFAULT_LAN_GW")
              or "")

    bypass = network.get("bypass") or network.get("DEFAULT_BYPASS") or False
    gen_return_route = (network.get("gen_return_route")
                        or network.get("DEFAULT_GEN_RETURN_ROUTE")
                        or False)

    bgp_networks = network.get("bgp_networks") or []
    inner_nets_raw = (network.get("inner_nets")
                      or network.get("DEFAULT_INNER_NETS")
                      or "")

    # ── 构建基础字段 ──
    d = {}

    # 来自数据头的字段（主线）
    d["main_lineid"] = main_line.get("lineid", "")
    d["main_pe"] = main_line.get("pe", "")
    d["main_tunnel"] = main_line.get("tunnel", "")
    d["main_wanip"] = main_line.get("wanip", "")
    d["main_wan_ip_plain"] = main_line.get("wan_ip_plain", "")
    d["main_pe_docking"] = main_line.get("pe_docking", "")
    d["main_ce_docking"] = main_line.get("ce_docking", "")
    d["main_pe_as"] = main_line.get("pe_as", "")
    d["main_ce_as"] = main_line.get("ce_as", "")
    d["main_zihuan"] = main_line.get("zihuan", "")
    d["main_tunnel_local_ip"] = main_line.get("tunnel_local_ip", "")
    d["main_tunnel_remote_ip"] = main_line.get("tunnel_remote_ip", "")
    d["main_dial_pe"] = main_line.get("dial_pe", "")
    d["main_dial_docking_ip"] = main_line.get("dial_docking_ip", "")
    d["main_loop_ip"] = main_line.get("loop_ip", "")
    d["main_dial_ip"] = main_line.get("dial_ip", "")
    d["main_psk"] = main_line.get("psk", "")

    # 来自数据头的字段（备线）
    d["backup_lineid"] = backup_line.get("lineid", "")
    d["backup_pe"] = backup_line.get("pe", "")
    d["backup_tunnel"] = backup_line.get("tunnel", "")
    d["backup_wanip"] = backup_line.get("wanip", "")
    d["backup_wan_ip_plain"] = backup_line.get("wan_ip_plain", "")
    d["backup_pe_docking"] = backup_line.get("pe_docking", "")
    d["backup_ce_docking"] = backup_line.get("ce_docking", "")
    d["backup_pe_as"] = backup_line.get("pe_as", "")
    d["backup_ce_as"] = backup_line.get("ce_as", "")
    d["backup_zihuan"] = backup_line.get("zihuan", "")
    d["backup_tunnel_local_ip"] = backup_line.get("tunnel_local_ip", "")
    d["backup_tunnel_remote_ip"] = backup_line.get("tunnel_remote_ip", "")
    d["backup_dial_pe"] = backup_line.get("dial_pe", "")
    d["backup_dial_docking_ip"] = backup_line.get("dial_docking_ip", "")
    d["backup_loop_ip"] = backup_line.get("loop_ip", "")
    d["backup_dial_ip"] = backup_line.get("dial_ip", "")
    d["backup_psk"] = backup_line.get("psk", "")

    # 网络参数字段
    d["hostname"] = hostname
    d["wan_if"] = wan_if_name
    d["lan_if"] = lan_if_name
    d["wan_ip"] = wan_ip
    d["wan_mask"] = wan_mask
    d["wan_ip_full"] = f"{wan_ip} {wan_mask}" if wan_ip and wan_mask else ""
    d["lan_ip"] = lan_ip
    d["lan_mask"] = lan_mask
    d["lan_ip_full"] = f"{lan_ip} {lan_mask}" if lan_ip and lan_mask else ""
    d["wan_gw"] = wan_gw
    d["lan_gw"] = lan_gw

    # BGP 参数（跨线交叉连接）
    d["ce_as"] = main_line.get("ce_as", "")
    d["bgp_router_id"] = main_line.get("tunnel_local_ip", "")

    # 交叉连接：主线的 BGP peer 是备线的 CE，备线的 BGP peer 是主线的 CE
    d["peer_main_ip"] = backup_line.get("tunnel_local_ip", "")
    d["peer_main_as"] = backup_line.get("pe_as", "")
    d["peer_backup_ip"] = main_line.get("tunnel_local_ip", "")
    d["peer_backup_as"] = main_line.get("pe_as", "")

    # 别名（模板兼容性）
    d["lineid_main"] = main_line.get("lineid", "")
    d["lineid_backup"] = backup_line.get("lineid", "")

    # ── 计算块 ──

    # --- BGP networks 块 ---
    bgp_net_lines = []
    for net in bgp_networks:
        net_str = str(net).strip()
        if not net_str:
            continue
        try:
            n = ipaddress.ip_network(net_str, strict=False)
            bgp_net_lines.append(f"  network {n.network_address} {n.netmask}")
        except (ValueError, ipaddress.AddressValueError):
            pass
    if not bgp_net_lines:
        # 回退：使用自环网段
        for line in [main_line, backup_line]:
            z = line.get("zihuan", "")
            if z:
                try:
                    n = ipaddress.ip_network(z.strip(), strict=False)
                    bgp_net_lines.append(f"  network {n.network_address} {n.netmask}")
                except (ValueError, ipaddress.AddressValueError):
                    pass
    d["bgp_networks_block"] = "\n".join(bgp_net_lines)

    # --- BGP filter prefix 块 ---
    filter_lines = []
    idx = 10
    for net in bgp_networks:
        net_str = str(net).strip()
        if not net_str:
            continue
        try:
            n = ipaddress.ip_network(net_str, strict=False)
            filter_lines.append(
                f"ip ip-prefix bgp-filte-pre-export index {idx} "
                f"permit {n.network_address} {n.prefixlen}"
            )
            idx += 10
        except (ValueError, ipaddress.AddressValueError):
            pass
    if not filter_lines:
        for line in [main_line, backup_line]:
            z = line.get("zihuan", "")
            if z:
                try:
                    n = ipaddress.ip_network(z.strip(), strict=False)
                    filter_lines.append(
                        f"ip ip-prefix bgp-filte-pre-export index {idx} "
                        f"permit {n.network_address} {n.prefixlen}"
                    )
                    idx += 10
                except (ValueError, ipaddress.AddressValueError):
                    pass
    d["bgp_filter_prefix_block"] = "\n".join(filter_lines)

    # --- ACL inner rules 块 ---
    acl_inner_lines = []
    # 合并 bgp_networks + inner_nets_raw
    all_inner_nets = list(bgp_networks)
    for token in re.split(r'[\n,，\s]+', inner_nets_raw or ""):
        t = token.strip()
        if t:
            all_inner_nets.append(t)

    rule_num = 10
    for net in all_inner_nets:
        net_str = str(net).strip()
        if not net_str:
            continue
        try:
            n = ipaddress.ip_network(net_str, strict=False)
            wm = _wildcard_mask(str(n.netmask))
            acl_inner_lines.append(
                f" rule {rule_num} permit ip source {n.network_address} {wm}"
            )
            rule_num += 10
        except (ValueError, ipaddress.AddressValueError):
            pass
    d["acl_inner_rules_block"] = "\n".join(acl_inner_lines)

    # --- IPSec ACL 块 ---
    _main_ce_dock = d["main_ce_docking"]
    _main_pe_dock = d["main_pe_docking"]
    d["ipsec_acl_main_block"] = (
        f"acl number 3333\n"
        f" rule 1 permit ip source {_main_ce_dock} 0 destination {_main_pe_dock} 0"
    )

    _backup_ce_dock = d["backup_ce_docking"]
    _backup_pe_dock = d["backup_pe_docking"]
    d["ipsec_acl_backup_block"] = (
        f"acl number 3334\n"
        f" rule 1 permit ip source {_backup_ce_dock} 0 destination {_backup_pe_dock} 0"
    )

    # --- IKE peer 块 ---
    d["ike_peer_main_block"] = (
        f"ike peer main\n"
        f" version 1\n"
        f" undo version 2\n"
        f" pre-shared-key cipher {d['main_psk']}\n"
        f" ike-proposal 10\n"
        f" dpd idle-time 10\n"
        f" dpd type on-demand\n"
        f" dpd retransmit-interval 2\n"
        f" remote-address {d['main_dial_ip']}"
    )

    d["ike_peer_backup_block"] = (
        f"ike peer backup\n"
        f" version 1\n"
        f" undo version 2\n"
        f" pre-shared-key cipher {d['backup_psk']}\n"
        f" ike-proposal 10\n"
        f" dpd idle-time 10\n"
        f" dpd type on-demand\n"
        f" dpd retransmit-interval 2\n"
        f" remote-address {d['backup_dial_ip']}"
    )

    # --- IPSec policy 块 ---
    d["ipsec_policy_block"] = (
        "ipsec policy S2S-IPSEC 10 isakmp\n"
        " security acl 3333\n"
        " pfs dh-group2\n"
        " ike-peer main\n"
        " proposal ipsectran1\n"
        "ipsec policy S2S-IPSEC 20 isakmp\n"
        " security acl 3334\n"
        " pfs dh-group2\n"
        " ike-peer backup\n"
        " proposal ipsectran1"
    )

    # --- LAN 接口块 ---
    if bypass:
        d["lan_if_block"] = ""
    else:
        d["lan_if_block"] = (
            f"interface {lan_if_name}\n"
            f" undo portswitch\n"
            f" ip address {lan_ip} {lan_mask}"
        )

    # --- WAN 接口块 ---
    d["wan_if_block"] = (
        f"interface {wan_if_name}\n"
        f" ip address {wan_ip} {wan_mask}\n"
        f" ipsec policy S2S-IPSEC"
    )

    # --- LoopBack 块 ---
    d["loopback_main_block"] = (
        f"interface LoopBack0\n"
        f" ip address {d['main_loop_ip']} 255.255.255.255"
    )

    d["loopback_backup_block"] = (
        f"interface LoopBack1\n"
        f" ip address {d['backup_loop_ip']} 255.255.255.255"
    )

    # --- GRE Tunnel 块（LoopBack 作为源）---
    d["tunnel_main_block"] = (
        f"interface {d['main_tunnel']}\n"
        f" description TO-{d['main_pe']}\n"
        f" ip address {d['main_tunnel_local_ip']} 255.255.255.252\n"
        f" keepalive 10 3\n"
        f" source LoopBack0\n"
        f" destination {d['main_dial_ip']}"
    )

    d["tunnel_backup_block"] = (
        f"interface {d['backup_tunnel']}\n"
        f" description TO-{d['backup_pe']}\n"
        f" ip address {d['backup_tunnel_local_ip']} 255.255.255.252\n"
        f" keepalive 10 3\n"
        f" source LoopBack1\n"
        f" destination {d['backup_dial_ip']}"
    )

    # --- 静态路由块 ---
    static_lines = []
    if wan_gw:
        static_lines.append(f" ip route-static 0.0.0.0 0.0.0.0 {wan_gw}")
    if d["main_dial_ip"] and wan_gw:
        static_lines.append(f" ip route-static {d['main_dial_ip']} 255.255.255.255 {wan_gw}")
    if d["backup_dial_ip"] and wan_gw:
        static_lines.append(f" ip route-static {d['backup_dial_ip']} 255.255.255.255 {wan_gw}")
    d["static_routes_block"] = "\n".join(static_lines)

    # --- 回程路由块（tag 8888，下一跳 = WAN 网关）---
    return_lines = []
    if gen_return_route and wan_gw:
        for net in bgp_networks:
            net_str = str(net).strip()
            if not net_str:
                continue
            try:
                n = ipaddress.ip_network(net_str, strict=False)
                return_lines.append(
                    f" ip route-static {n.network_address} {n.netmask} "
                    f"{wan_gw} tag 8888"
                )
            except (ValueError, ipaddress.AddressValueError):
                pass
    d["return_routes_block"] = "\n".join(return_lines)

    return d, None


# =====================================================================
# 模板常量
# =====================================================================
TEMPLATE_AR_TRADITIONAL = """#
hwtacacs-server template fnetlink_tacacs
 hwtacacs-server authentication 192.168.55.250
 hwtacacs-server authorization 192.168.55.250
 hwtacacs-server accounting 192.168.55.250
 hwtacacs-server source-ip {main_wan_ip_plain}
 hwtacacs-server shared-key cipher both-win
#
acl number 2707
{acl_inner_rules_block}
#
{ipsec_acl_main_block}
{ipsec_acl_backup_block}
#
ipsec proposal ipsectran1
 esp authentication-algorithm sha1
 esp encryption-algorithm 3des
#
ike proposal default
 encryption-algorithm aes-256 aes-192 aes-128 aes-gcm-256 aes-gcm-192 aes-gcm-128
 dh group14
 authentication-algorithm sha2-512 sha2-384 sha2-256
 authentication-method pre-share
 integrity-algorithm hmac-sha2-256
 prf hmac-sha2-256
ike proposal 10
 encryption-algorithm aes-128
 dh group2
 authentication-algorithm sha1
 sa duration 28800
 authentication-method pre-share
 integrity-algorithm hmac-sha2-256
 prf hmac-sha2-256
#
{ike_peer_main_block}
{ike_peer_backup_block}
#
{ipsec_policy_block}
#
aaa
 authentication-scheme default
  authentication-mode local
 authentication-scheme fnet_tac
  authentication-mode hwtacacs local
 authentication-scheme radius
  authentication-mode radius
 authorization-scheme default
  authorization-mode local
 authorization-scheme fnet_tac
  authorization-mode hwtacacs local
  authorization-cmd 15 hwtacacs local
 accounting-scheme default
  accounting-mode none
 accounting-scheme fnet_tac
  accounting-mode hwtacacs
  accounting start-fail online
 recording-scheme fnet_tac
  recording-mode hwtacacs fnetlink_tacacs
 cmd recording-scheme fnet_tac
 local-aaa-user password policy administrator
  password history record number 0
  password expire 0
 service-scheme fnet_tac
  admin-user privilege level 15
 domain default
  authentication-scheme default
  accounting-scheme default
  radius-server default
 domain default_admin
  authentication-scheme default
  accounting-scheme default
 domain fnet_tac
  authentication-scheme fnet_tac
  accounting-scheme fnet_tac
  authorization-scheme fnet_tac
  radius-server default
  hwtacacs-server fnetlink_tacacs
 local-user admin password irreversible-cipher Tfe28@w%
 local-user admin privilege level 15
 local-user admin service-type terminal ssh http
 local-user bothwin password irreversible-cipher Tfe28@w%
 local-user bothwin privilege level 15
 local-user bothwin service-type terminal ssh http
#
{lan_if_block}
{wan_if_block}
#
interface GigabitEthernet0/0/10
 description VirtualPort
#
interface Cellular0/0/0
#
interface NULL0
#
{loopback_main_block}
{loopback_backup_block}
#
{tunnel_main_block}
{tunnel_backup_block}
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
{bgp_networks_block}
  import-route direct
  import-route static route-policy bgp-To--VPN-Redistribute-Static
  peer {peer_main_ip} enable
  peer {peer_main_ip} route-policy bgp-route-policy-back-import import
  peer {peer_main_ip} route-policy bgp-route-policy-pri-export export
  peer {peer_main_ip} advertise-community
  peer {peer_main_ip} route-update-interval 10
  peer {peer_backup_ip} enable
  peer {peer_backup_ip} route-policy bgp-route-policy-pri-import import
  peer {peer_backup_ip} route-policy bgp-route-policy-back-export export
  peer {peer_backup_ip} advertise-community
  peer {peer_backup_ip} route-update-interval 10
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
route-policy bgp-route-policy-pri-export permit node 100
 if-match ip-prefix bgp-filte-pre-export
#
route-policy bgp-route-policy-pri-export deny node 999
#
route-policy bgp-route-policy-back-export permit node 100
 if-match ip-prefix bgp-filte-pre-export
#
route-policy bgp-route-policy-back-export deny node 999
#
 stelnet server enable
 ssh server port 2707
 ssh server permit interface all
#
 http secure-server ssl-policy default_policy
 http secure-server enable
 http server permit interface GigabitEthernet0/0/0
#
nqa event 1 log
#
{bgp_filter_prefix_block}
ip ip-prefix deny index 10 deny 0.0.0.0 0
ip ip-prefix BGP-permit-ex index 10 permit 173.15.50.0 24 greater-equal 24 less-equal 24
#
{static_routes_block}
{return_routes_block}
"""
