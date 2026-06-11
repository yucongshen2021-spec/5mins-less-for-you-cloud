#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SD-WAN 自环组网 — OPS 脚本生成工具 v4

- 单机组网：3列布局（备注/初始化 | 数据输入 | 配置生成）
  配置生成区用 OPS/Factory 两页切换，各占满整个区域
- 双机组网：同上，配置生成区先切换主/备设备，每设备内 OPS/Factory 两页
- 各区域尺寸略增大
"""

import ipaddress
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import field_coverage
except ImportError:
    field_coverage = None  # type: ignore

try:
    from user_activity_log import log_generate_config
except ImportError:
    def log_generate_config(**_kwargs):  # type: ignore[misc]
        pass

# =====================================================================
# 南向服务（与控制器选项一致；仅用于静态路由）
# =====================================================================
SOUTH_SERVICE_OPTIONS = [
    ("public",  "Public Default South Access",  "119.145.21.126", None),
    ("private", "Private Default South Access", "172.23.3.251",  "172.23.30.251"),
    ("ct",      "CT South Access",              "119.145.21.126", None),
    ("hk",      "HK South Access",              "43.229.119.246", None),
    ("mstp",    "MSTP South Access",            "172.23.3.251",  "172.23.30.251"),
]
SOUTH_LABELS = [x[1] for x in SOUTH_SERVICE_OPTIONS]


def _south_display_label(row):
    name, pri, bak = row[1], row[2], row[3]
    if not pri:
        return name
    if bak:
        return f"{name}  [{pri} / {bak}]"
    return f"{name}  [{pri}]"


SOUTH_LABELS_DISPLAY = [_south_display_label(r) for r in SOUTH_SERVICE_OPTIONS]


def _user_init_ike_storage(s: str) -> str:
    t = (s or "").strip().lower().replace(" ", "")
    if t in ("v1", "1", "ikev1"):
        return "v1"
    if t in ("v2", "2", "ikev2"):
        return "v2"
    return "v1"


# 可视化 / user_init：南向下拉、IKE（与正式页签 reset 同步）
ZH_SOUTH_LABEL_SAVED = SOUTH_LABELS_DISPLAY[0]
DJ_SOUTH_LABEL_SAVED = SOUTH_LABELS_DISPLAY[0]
ZH_IKE_VERSION_SAVED = "v1"
DJ_IKE_VERSION_SAVED = "v1"

# 正式页「IKE 版本」单选框（供 all_in_one 初始化区切换时同步到生成所用 cfg）
_FORMAL_IKE_VAR_ZH = None
_FORMAL_IKE_VAR_DJ = None


def push_ike_to_formal_panel(which: str, v: str) -> None:
    """which: 'ZH' | 'DJ' — 将初始化区选中的 IKE 同步到 AR 正式页单选框。"""
    std = _user_init_ike_storage(str(v))
    if std not in ("v1", "v2"):
        std = "v1"
    if which == "ZH" and _FORMAL_IKE_VAR_ZH is not None:
        _FORMAL_IKE_VAR_ZH.set(std)
    elif which == "DJ" and _FORMAL_IKE_VAR_DJ is not None:
        _FORMAL_IKE_VAR_DJ.set(std)


def _south_ips_by_label(display_label):
    for i, dl in enumerate(SOUTH_LABELS_DISPLAY):
        if dl == display_label:
            row = SOUTH_SERVICE_OPTIONS[i]
            return row[2], row[3]
    for row in SOUTH_SERVICE_OPTIONS:
        if row[1] == display_label:
            return row[2], row[3]
    return None, None


# =====================================================================
# 公共解析 / 业务函数
# =====================================================================
# _get, wanip_hosts 运行于 all_in_one_v2 时由 shared_utils 注入
try:
    _get
except NameError:
    def _get(pattern, block, flags=re.IGNORECASE | re.MULTILINE):
        m = re.search(pattern, block, flags)
        return m.group(1).strip() if m else ""

try:
    wanip_hosts
    _cidr_hosts = wanip_hosts  # shared_utils 的 wanip_hosts 等同于 _cidr_hosts
except NameError:
    def _cidr_hosts(cidr):
        """从 CIDR 中返回前两个可用主机 IP。返回 (PE侧=奇数, CE侧=偶数)。"""
        try:
            hosts = list(ipaddress.ip_network(cidr.strip(), strict=False).hosts())
            if len(hosts) >= 2:
                return str(hosts[0]), str(hosts[1])
        except (ValueError, ipaddress.AddressValueError):
            pass
        return "", ""


def _first_host_from_cidr(cidr):
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
        hosts = list(net.hosts())
        return str(hosts[0]) if hosts else ""
    except Exception:
        return ""


def _first_host_mask(cidr):
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
        hosts = list(net.hosts())
        if not hosts:
            return "", ""
        return str(hosts[0]), str(net.netmask)
    except Exception:
        return "", ""


def _ip_mask_from_cidr(cidr):
    try:
        iface = ipaddress.ip_interface(cidr.strip())
        return str(iface.ip), str(iface.netmask)
    except Exception:
        return "", ""


def _validate_ipv4(ip_text, name):
    try:
        ipaddress.ip_address(ip_text.strip())
        return True, ""
    except Exception as e:
        return False, f"{name} 格式错误：{e}"


def _validate_cidr(cidr_text, name):
    try:
        ipaddress.ip_interface(cidr_text.strip())
        return True, ""
    except Exception as e:
        return False, f"{name} 格式错误：{e}"


def _validate_ge_slot(s, name):
    t = (s or "").strip()
    if not t:
        return False, f"{name} 不能为空"
    if re.match(r"^GigabitEthernet\d+/\d+/\d+$", t, re.IGNORECASE):
        return True, ""
    if re.match(r"^[Gg]\s*\(?\d+/\d+/\d+\)?\s*$", t):
        return True, ""
    if re.match(r"^\d+/\d+/\d+$", t):
        return True, ""
    if re.match(r"^[Gg]?\s*\d+$", t):
        return True, ""
    return False, f"{name} 请填端口号，如 9 或 0/0/9"


def expand_ge_port(s):
    t = (s or "").strip()
    if re.match(r"^GigabitEthernet\d+/\d+/\d+$", t, re.IGNORECASE):
        return t
    m = re.match(r"^[Gg]\s*\(?(\d+/\d+/\d+)\)?\s*$", t)
    if m:
        return f"GigabitEthernet{m.group(1)}"
    if re.match(r"^\d+/\d+/\d+$", t):
        return f"GigabitEthernet{t}"
    m2 = re.match(r"^[Gg]?\s*(\d+)$", t)
    if m2:
        return f"GigabitEthernet0/0/{m2.group(1)}"
    return t


def _cfg_ge(init_cfg: dict, key: str, default_slot: str) -> str:
    """init_cfg 缺键或空串时，用与初始化面板一致的默认槽位展开为 GigabitEthernet。"""
    v = init_cfg.get(key)
    if v is None or (isinstance(v, str) and not str(v).strip()):
        return expand_ge_port(default_slot)
    return expand_ge_port(str(v).strip())


def extract_lineid_zihuan(text):
    m = re.search(r"LineID\s*[:：]\s*(\S+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _lineid_for_filename(lineid):
    """用于文件名/FTP：移除 lineid 末尾数字，如 604604Hw1 -> 604604Hw"""
    if not lineid:
        return "lineid"
    s = re.sub(r'[\\/:*?"<>|]', '_', str(lineid).strip())
    if len(s) > 1 and s[-1].isdigit():
        return s[:-1]
    return s


def parse_ar_sdwan_text(raw):
    blocks = []
    for part in re.split(r"(?=^\s*LineID\s*[:：])", raw.strip(), flags=re.MULTILINE):
        s = part.strip()
        if s.lower().startswith("lineid"):
            blocks.append(s)
    if len(blocks) < 2:
        raise ValueError("至少需要两段 LineID（主/备）数据。")

    def parse_one(block):
        lineid      = _get(r"LineID\s*[:：]\s*([^\n]+)", block)
        pe          = _get(r"^\s*PE\s*[:：]\s*([^\n]+)", block)
        tunnel      = _get(r"^\s*Tunnel\s*[:：]\s*([^\n]+)", block)
        wanip       = _get(r"^\s*wanip\s*[:：]\s*([^\n]+)", block)
        pe_docking  = _get(r"PE\s*对接\s*[:：]\s*([^\n]+)", block)
        ce_docking  = _get(r"CE\s*对接\s*[:：]\s*([^\n]+)", block)
        pe_as       = _get(r"PE\s*AS号\s*[:：]\s*([^\n]+)", block)
        inner_route = _get(r"客户内网路由\s*[:：]\s*([^\n]+)", block)
        dial_ip     = _get(r"拨号ip\s*[:：]\s*([^\n]+)", block)
        psk         = _get(r"秘钥\s*[:：]\s*([^\n]+)", block) or "both-win"
        wan_peer_ip, wan_ce_ip = _cidr_hosts(wanip)
        return {
            "lineid": lineid, "pe": pe, "tunnel": tunnel, "wanip": wanip,
            "wan_peer_ip": wan_peer_ip, "wan_ce_ip": wan_ce_ip,
            "pe_docking": pe_docking, "ce_docking": ce_docking, "pe_as": pe_as,
            "inner_route": inner_route,
            "zihuan_ce_ip": _first_host_from_cidr(inner_route),
            "zihuan_peer_ip": _cidr_hosts(inner_route)[0],
            "dial_ip": dial_ip, "psk": psk,
        }

    main   = parse_one(blocks[0])
    backup = parse_one(blocks[1])
    return {"main": main, "backup": backup,
            "lineid": main.get("lineid", "") or backup.get("lineid", "") or "AR-SDWAN"}


# =====================================================================
# 可视化编辑器 — 平面解析器 & 模板生成
# =====================================================================

# ============================================================
# AR SD-WAN template constants (from editor_defaults .tpl files)
# ============================================================
TEMPLATE_AR_OPS_SINGLE_WAN1 = """\
# coding=utf-8
import ops
import sys
import os


def ops_condition(ops):
    value, descri_str = ops.iclog.subscribe(tag="startup", moduName="DEV", infoAlias="ENTUP", logInfo="register success")
    print('Script has being installed')
    return 0
 
def ops_execute(ops):
    handle, err_desp = ops.cli.open()
    print("\r\n err_desp:%s" % (err_desp))
    choice={"Continue?":"Y"}
    result, n11, n21 = ops.cli.execute(handle, "system-view")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_internet")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_ipsec")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3333")
    result, n11, n21 = ops.cli.execute(handle, "rule 1 permit ip vpn-instance underlay_ipsec source {main_ce_docking} 0 destination {main_pe_docking} 0")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3334")
    result, n11, n21 = ops.cli.execute(handle, "rule 1 permit ip vpn-instance underlay_ipsec source {bk_ce_docking} 0 destination {bk_pe_docking} 0")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3999")
    result, n11, n21 = ops.cli.execute(handle, "rule 10 permit ip source 100.98.1.0 0.0.0.3")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "esp authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "esp encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ike proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "dh group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "sa duration 28800")
    result, n11, n21 = ops.cli.execute(handle, "authentication-method pre-share")
    result, n11, n21 = ops.cli.execute(handle, "integrity-algorithm hmac-sha2-256")
    result, n11, n21 = ops.cli.execute(handle, "prf hmac-sha2-256")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ike peer main")
    result, n11, n21 = ops.cli.execute(handle, "version 1", choice)
    result, n11, n21 = ops.cli.execute(handle, "undo version 2", choice)
    result, n11, n21 = ops.cli.execute(handle, "pre-shared-key cipher {main_psk}")
    result, n11, n21 = ops.cli.execute(handle, "ike-proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd idle-time 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd type on-demand")
    result, n11, n21 = ops.cli.execute(handle, "dpd retransmit-interval 2")
    result, n11, n21 = ops.cli.execute(handle, "remote-address vpn-instance underlay_ipsec {main_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ike peer backup")
    result, n11, n21 = ops.cli.execute(handle, "version 1", choice)
    result, n11, n21 = ops.cli.execute(handle, "undo version 2", choice)
    result, n11, n21 = ops.cli.execute(handle, "pre-shared-key cipher {bk_psk}")
    result, n11, n21 = ops.cli.execute(handle, "ike-proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd idle-time 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd type on-demand")
    result, n11, n21 = ops.cli.execute(handle, "dpd retransmit-interval 2")
    result, n11, n21 = ops.cli.execute(handle, "remote-address vpn-instance underlay_ipsec {bk_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC 10 isakmp")
    result, n11, n21 = ops.cli.execute(handle, "security acl 3333")
    result, n11, n21 = ops.cli.execute(handle, "pfs dh-group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike-peer main")
    result, n11, n21 = ops.cli.execute(handle, "proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC 20 isakmp")
    result, n11, n21 = ops.cli.execute(handle, "security acl 3334")
    result, n11, n21 = ops.cli.execute(handle, "pfs dh-group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike-peer backup")
    result, n11, n21 = ops.cli.execute(handle, "proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}.98")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 98")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internet")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.98.1.1 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}.100")
    result, n11, n21 = ops.cli.execute(handle, "description to-ZiHuan")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 100")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ip address {z_main_ip} {z_main_mask}")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}.200")
    result, n11, n21 = ops.cli.execute(handle, "description to-ZiHuan")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 200")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ip address {z_bk_ip} {z_bk_mask}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {ipsec_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {ipsec_port}.98")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 98")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsec")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.98.1.2 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {wan1_port}")
    result, n11, n21 = ops.cli.execute(handle, "description to-internet")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internet")
    result, n11, n21 = ops.cli.execute(handle, "ip address {wan1_ip_addr} {wan1_mask}")
    result, n11, n21 = ops.cli.execute(handle, "nat outbound 3999")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface LoopBack1000")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsec")
    result, n11, n21 = ops.cli.execute(handle, "ip address {main_ce_docking} 255.255.255.255")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface LoopBack1001")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsec")
    result, n11, n21 = ops.cli.execute(handle, "ip address {bk_ce_docking} 255.255.255.255")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface Tunnel0/0/1000")
    result, n11, n21 = ops.cli.execute(handle, "description 'pri to {main_pe} {main_tunnel}'")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ip address {main_wan_ce_ip} 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "tunnel-protocol gre")
    result, n11, n21 = ops.cli.execute(handle, "source LoopBack1000")
    result, n11, n21 = ops.cli.execute(handle, "destination vpn-instance underlay_ipsec {main_pe_docking}")
    result, n11, n21 = ops.cli.execute(handle, "mtu 1476")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1300")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface Tunnel0/0/1001")
    result, n11, n21 = ops.cli.execute(handle, "description 'bk to {bk_pe} {bk_tunnel}'")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ip address {bk_wan_ce_ip} 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "tunnel-protocol gre")
    result, n11, n21 = ops.cli.execute(handle, "source LoopBack1001")
    result, n11, n21 = ops.cli.execute(handle, "destination vpn-instance underlay_ipsec {bk_pe_docking}")
    result, n11, n21 = ops.cli.execute(handle, "mtu 1476")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1300")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "nqa event 1 log")
    result, n11, n21 = ops.cli.execute(handle, "nqa test-instance admin ipsecmain")
    result, n11, n21 = ops.cli.execute(handle, "test-type icmp")
    result, n11, n21 = ops.cli.execute(handle, "destination-address ipv4 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "source-address ipv4 {main_wan_ce_ip}")
    result, n11, n21 = ops.cli.execute(handle, "frequency 15")
    result, n11, n21 = ops.cli.execute(handle, "probe-count 2")
    result, n11, n21 = ops.cli.execute(handle, "vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    result, n11, n21 = ops.cli.execute(handle, "start now")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "nqa test-instance admin ipsecbackup")
    result, n11, n21 = ops.cli.execute(handle, "test-type icmp")
    result, n11, n21 = ops.cli.execute(handle, "destination-address ipv4 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "source-address ipv4 {bk_wan_ce_ip}")
    result, n11, n21 = ops.cli.execute(handle, "frequency 15")
    result, n11, n21 = ops.cli.execute(handle, "probe-count 2")
    result, n11, n21 = ops.cli.execute(handle, "vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    result, n11, n21 = ops.cli.execute(handle, "start now")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_ipsec 0.0.0.0 0.0.0.0 100.98.1.1")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internet 0.0.0.0 0.0.0.0 {wan1_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internet {main_dial_ip} 255.255.255.255 {wan1_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internet {bk_dial_ip} 255.255.255.255 {wan1_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 0.0.0.0 0.0.0.0 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 114.113.245.99 255.255.255.255 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 192.168.55.250 255.255.255.255 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 0.0.0.0 0.0.0.0 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 114.113.245.100 255.255.255.255 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 192.168.55.250 255.255.255.255 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "aaa")
    result, n11, n21 = ops.cli.execute(handle, "local-user admin service-type terminal ssh http")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ssh server permit interface all")
    result, n11, n21 = ops.cli.execute(handle, "stelnet server enable")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 0")
    result, n11, n21 = ops.cli.execute(handle, "protocol inbound ssh")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 1 4")
    result, n11, n21 = ops.cli.execute(handle, "authentication-mode aaa")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ops")
    result, n11, n21 = ops.cli.execute(handle, "environment mainip {main_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "script-assistant python ipsecmain.py")
    result, n11, n21 = ops.cli.execute(handle, "environment backupip {bk_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "script-assistant python ipsecbackup.py")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    ops.syslog("ops:add_tunnel is success", "critical", "syslog")
    ops.cli.close(handle)
    return 0
"""

TEMPLATE_AR_FACTORY_SINGLE_WAN1 = """\
ip vpn-instance underlay_internet

ipv4-family

quit

ip vpn-instance underlay_ipsec

ipv4-family

quit

ip vpn-instance underlay_main

ipv4-family

quit

ip vpn-instance underlay_backup

ipv4-family

quit

interface {wan1_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internet

ip address {wan1_ip_addr} {wan1_mask}

tcp adjust-mss 1200

interface {zihuan_port}

undo portswitch

interface {zihuan_port}.98

interface {zihuan_port}.100

interface {zihuan_port}.200

interface {ipsec_port}

undo portswitch

interface {ipsec_port}.98

interface Tunnel0/0/1000

interface Tunnel0/0/1001

ip route-static vpn-instance underlay_internet 0.0.0.0 0.0.0.0 {wan1_gw}

aaa

 local-user admin service-type terminal ssh http
y

 quit

ssh server permit interface all

stelnet server enable

user-interface vty 0

 protocol inbound ssh

user-interface vty 1 4

 authentication-mode aaa

ftp 59.36.7.222  vpn-instance underlay_internet

ops install file {lineid_fn}.py

ops install file ipsecmain.py

ops install file ipsecbackup.py

system-view

ops

 script-assistant python {lineid_fn}.py

 script-assistant python ipsecmain.py

 script-assistant python ipsecbackup.py

ip route-static vpn-instance underlay_internet {south_primary} 255.255.255.255 {wan1_gw} tag 4400 description agile-controller

agile controller host {south_primary} port 10020 vpn-instance underlay_internet
quit

ip route-static vpn-instance underlay_internet {south_backup} 255.255.255.255 {wan1_gw} tag 4400 description agile-controller

agile controller host {south_backup} port 10020 vpn-instance underlay_internet
quit

set factory-configuration from current-configuration

y

save

Y
"""

TEMPLATE_AR_OPS_SINGLE_DUALWAN = """\
# coding=utf-8
import ops
import sys
import os


def ops_condition(ops):
    value, descri_str = ops.iclog.subscribe(tag="startup", moduName="DEV", infoAlias="ENTUP", logInfo="register success")
    print('Script has being installed')
    return 0
 
def ops_execute(ops):
    handle, err_desp = ops.cli.open()
    print("\r\n err_desp:%s" % (err_desp))
    choice={"Continue?":"Y"}
    result, n11, n21 = ops.cli.execute(handle, "system-view")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_internetA")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_internetB")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_ipsecA")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_ipsecB")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3333")
    result, n11, n21 = ops.cli.execute(handle, "rule 1 permit ip vpn-instance underlay_ipsecA source {main_ce_docking} 0 destination {main_pe_docking} 0")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3334")
    result, n11, n21 = ops.cli.execute(handle, "rule 1 permit ip vpn-instance underlay_ipsecB source {bk_ce_docking} 0 destination {bk_pe_docking} 0")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3999")
    result, n11, n21 = ops.cli.execute(handle, "rule 10 permit ip source 100.98.1.0 0.0.0.3")
    result, n11, n21 = ops.cli.execute(handle, "rule 20 permit ip source 100.99.1.0 0.0.0.3")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "esp authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "esp encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "dh group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "sa duration 28800")
    result, n11, n21 = ops.cli.execute(handle, "authentication-method pre-share")
    result, n11, n21 = ops.cli.execute(handle, "integrity-algorithm hmac-sha1-96")
    result, n11, n21 = ops.cli.execute(handle, "prf hmac-sha1")
    result, n11, n21 = ops.cli.execute(handle, "ike peer main")
    result, n11, n21 = ops.cli.execute(handle, "version 1", choice)
    result, n11, n21 = ops.cli.execute(handle, "undo version 2", choice)
    result, n11, n21 = ops.cli.execute(handle, "pre-shared-key cipher {main_psk}")
    result, n11, n21 = ops.cli.execute(handle, "ike-proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd idle-time 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd type on-demand")
    result, n11, n21 = ops.cli.execute(handle, "dpd retransmit-interval 2")
    result, n11, n21 = ops.cli.execute(handle, "remote-address vpn-instance underlay_ipsecA {main_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ike peer backup")
    result, n11, n21 = ops.cli.execute(handle, "version 1", choice)
    result, n11, n21 = ops.cli.execute(handle, "undo version 2", choice)
    result, n11, n21 = ops.cli.execute(handle, "pre-shared-key cipher {bk_psk}")
    result, n11, n21 = ops.cli.execute(handle, "ike-proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd idle-time 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd type on-demand")
    result, n11, n21 = ops.cli.execute(handle, "dpd retransmit-interval 2")
    result, n11, n21 = ops.cli.execute(handle, "remote-address vpn-instance underlay_ipsecB {bk_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC-A 10 isakmp")
    result, n11, n21 = ops.cli.execute(handle, "security acl 3333")
    result, n11, n21 = ops.cli.execute(handle, "pfs dh-group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike-peer main")
    result, n11, n21 = ops.cli.execute(handle, "proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC-B 20 isakmp")
    result, n11, n21 = ops.cli.execute(handle, "security acl 3334")
    result, n11, n21 = ops.cli.execute(handle, "pfs dh-group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike-peer backup")
    result, n11, n21 = ops.cli.execute(handle, "proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}.98")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 98")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetA")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.98.1.1 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}.99")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 99")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetB")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.99.1.1 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}.100")
    result, n11, n21 = ops.cli.execute(handle, "description to-ZiHuan")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 100")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ip address {z_main_ip} {z_main_mask}")
    result, n11, n21 = ops.cli.execute(handle, "interface {zihuan_port}.200")
    result, n11, n21 = ops.cli.execute(handle, "description to-ZiHuan")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 200")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ip address {z_bk_ip} {z_bk_mask}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {ipsec_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {ipsec_port}.98")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 98")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecA")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.98.1.2 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC-A")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {ipsec_port}.99")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 99")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecB")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.99.1.2 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC-B")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {wan1_port}")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetA")
    result, n11, n21 = ops.cli.execute(handle, "description to-wan1")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1200")
    result, n11, n21 = ops.cli.execute(handle, "ip address {wan1_ip_addr} {wan1_mask}")
    result, n11, n21 = ops.cli.execute(handle, "nat outbound 3999")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {wan2_port}")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetB")
    result, n11, n21 = ops.cli.execute(handle, "description to-wan2")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1200")
    result, n11, n21 = ops.cli.execute(handle, "ip address {wan2_ip_addr} {wan2_mask}")
    result, n11, n21 = ops.cli.execute(handle, "nat outbound 3999")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface LoopBack1000")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecA")
    result, n11, n21 = ops.cli.execute(handle, "ip address {main_ce_docking} 255.255.255.255")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface LoopBack1001")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecB")
    result, n11, n21 = ops.cli.execute(handle, "ip address {bk_ce_docking} 255.255.255.255")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface Tunnel0/0/1000")
    result, n11, n21 = ops.cli.execute(handle, "description 'pri to {main_pe} {main_tunnel}'")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ip address {main_wan_ce_ip} 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "tunnel-protocol gre")
    result, n11, n21 = ops.cli.execute(handle, "source LoopBack1000")
    result, n11, n21 = ops.cli.execute(handle, "destination vpn-instance underlay_ipsecA {main_pe_docking}")
    result, n11, n21 = ops.cli.execute(handle, "mtu 1476")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1300")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface Tunnel0/0/1001")
    result, n11, n21 = ops.cli.execute(handle, "description 'bk to {bk_pe} {bk_tunnel}'")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ip address {bk_wan_ce_ip} 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "tunnel-protocol gre")
    result, n11, n21 = ops.cli.execute(handle, "source LoopBack1001")
    result, n11, n21 = ops.cli.execute(handle, "destination vpn-instance underlay_ipsecB {bk_pe_docking}")
    result, n11, n21 = ops.cli.execute(handle, "mtu 1476")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1300")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "nqa event 1 log")
    result, n11, n21 = ops.cli.execute(handle, "nqa test-instance admin ipsecmain")
    result, n11, n21 = ops.cli.execute(handle, "test-type icmp")
    result, n11, n21 = ops.cli.execute(handle, "destination-address ipv4 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "source-address ipv4 {main_wan_ce_ip}")
    result, n11, n21 = ops.cli.execute(handle, "frequency 15")
    result, n11, n21 = ops.cli.execute(handle, "probe-count 2")
    result, n11, n21 = ops.cli.execute(handle, "vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    result, n11, n21 = ops.cli.execute(handle, "start now")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "nqa test-instance admin ipsecbackup")
    result, n11, n21 = ops.cli.execute(handle, "test-type icmp")
    result, n11, n21 = ops.cli.execute(handle, "destination-address ipv4 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "source-address ipv4 {bk_wan_ce_ip}")
    result, n11, n21 = ops.cli.execute(handle, "frequency 15")
    result, n11, n21 = ops.cli.execute(handle, "probe-count 2")
    result, n11, n21 = ops.cli.execute(handle, "vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    result, n11, n21 = ops.cli.execute(handle, "start now")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_ipsecA 0.0.0.0 0.0.0.0 100.98.1.1")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {wan1_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetA {main_dial_ip} 255.255.255.255 {wan1_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 0.0.0.0 0.0.0.0 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 114.113.245.99 255.255.255.255 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 192.168.55.250 255.255.255.255 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_ipsecB 0.0.0.0 0.0.0.0 100.99.1.1")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {wan2_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetB {bk_dial_ip} 255.255.255.255 {wan2_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 0.0.0.0 0.0.0.0 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 114.113.245.100 255.255.255.255 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 192.168.55.250 255.255.255.255 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "aaa")
    result, n11, n21 = ops.cli.execute(handle, "local-user admin service-type terminal ssh http")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ssh server permit interface all")
    result, n11, n21 = ops.cli.execute(handle, "stelnet server enable")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 0")
    result, n11, n21 = ops.cli.execute(handle, "protocol inbound ssh")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 1 4")
    result, n11, n21 = ops.cli.execute(handle, "authentication-mode aaa")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ops")
    result, n11, n21 = ops.cli.execute(handle, "environment mainip {main_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "script-assistant python ipsecmain.py")
    result, n11, n21 = ops.cli.execute(handle, "environment backupip {bk_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "script-assistant python ipsecbackup.py")
    ops.syslog("ops:add_tunnel is success", "critical", "syslog")
    ops.cli.close(handle)
    return 0
"""

TEMPLATE_AR_FACTORY_SINGLE_DUALWAN = """\
ip vpn-instance underlay_internetA

ipv4-family

quit

ip vpn-instance underlay_internetB

ipv4-family

quit

ip vpn-instance underlay_ipsecA

ipv4-family

quit

ip vpn-instance underlay_ipsecB

ipv4-family

quit

ip vpn-instance underlay_main

ipv4-family

quit

ip vpn-instance underlay_backup

ipv4-family

quit

interface {wan1_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internetA

ip address {wan1_ip_addr} {wan1_mask}

tcp adjust-mss 1200

interface {wan2_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internetB

ip address {wan2_ip_addr} {wan2_mask}

tcp adjust-mss 1200

interface {zihuan_port}

undo portswitch

interface {zihuan_port}.98

interface {zihuan_port}.99

interface {zihuan_port}.100

interface {zihuan_port}.200

interface {ipsec_port}

undo portswitch

interface {ipsec_port}.98

interface {ipsec_port}.99

interface Tunnel0/0/1000

interface Tunnel0/0/1001

ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {wan1_gw}

ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {wan2_gw}

aaa

 local-user admin service-type terminal ssh http
y

 quit

ssh server permit interface all

stelnet server enable

user-interface vty 0

 protocol inbound ssh

user-interface vty 1 4

 authentication-mode aaa

ftp 59.36.7.222  vpn-instance underlay_internetA

ops install file {lineid_fn}.py

ops install file ipsecmain.py

ops install file ipsecbackup.py

system-view

ops

 script-assistant python {lineid_fn}.py

 script-assistant python ipsecmain.py

 script-assistant python ipsecbackup.py

ip route-static vpn-instance underlay_internetA {south_primary} 255.255.255.255 {wan1_gw} tag 4400 description agile-controller

agile controller host {south_primary} port 10020 vpn-instance underlay_internetA
quit

ip route-static vpn-instance underlay_internetB {south_backup} 255.255.255.255 {wan2_gw} tag 4400 description agile-controller

agile controller host {south_backup} port 10020 vpn-instance underlay_internetB
quit

set factory-configuration from current-configuration

y

save

Y
"""

TEMPLATE_AR_OPS_DUAL_PRIMARY = """\
# coding=utf-8
import ops
import sys
import os


def ops_condition(ops):
    value, descri_str = ops.iclog.subscribe(tag="startup", moduName="DEV", infoAlias="ENTUP", logInfo="register success")
    print('Script has being installed')
    return 0
 
def ops_execute(ops):
    handle, err_desp = ops.cli.open()
    print("\r\n err_desp:%s" % (err_desp))
    choice={"Continue?":"Y"}
    result, n11, n21 = ops.cli.execute(handle, "system-view")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_internetA")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_ipsecA")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3333")
    result, n11, n21 = ops.cli.execute(handle, "rule 1 permit ip vpn-instance underlay_ipsecA source {main_ce_docking} 0 destination {main_pe_docking} 0")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3999")
    result, n11, n21 = ops.cli.execute(handle, "rule 10 permit ip source 100.98.1.0 0.0.0.3")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "esp authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "esp encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "dh group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "sa duration 28800")
    result, n11, n21 = ops.cli.execute(handle, "authentication-method pre-share")
    result, n11, n21 = ops.cli.execute(handle, "integrity-algorithm hmac-sha1-96")
    result, n11, n21 = ops.cli.execute(handle, "prf hmac-sha1")
    result, n11, n21 = ops.cli.execute(handle, "ike peer main")
    result, n11, n21 = ops.cli.execute(handle, "version 1", choice)
    result, n11, n21 = ops.cli.execute(handle, "undo version 2", choice)
    result, n11, n21 = ops.cli.execute(handle, "pre-shared-key cipher {main_psk}")
    result, n11, n21 = ops.cli.execute(handle, "ike-proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd idle-time 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd type on-demand")
    result, n11, n21 = ops.cli.execute(handle, "dpd retransmit-interval 2")
    result, n11, n21 = ops.cli.execute(handle, "remote-address vpn-instance underlay_ipsecA {main_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC 10 isakmp")
    result, n11, n21 = ops.cli.execute(handle, "security acl 3333")
    result, n11, n21 = ops.cli.execute(handle, "pfs dh-group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike-peer main")
    result, n11, n21 = ops.cli.execute(handle, "proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_zihuan1_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_zihuan1_port}.98")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 98")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetA")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.98.1.1 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_zihuan1_port}.100")
    result, n11, n21 = ops.cli.execute(handle, "description to-ZiHuan")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 100")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ip address {z_main_ip} {z_main_mask}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_ipsec1_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_ipsec1_port}.98")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 98")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecA")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.98.1.2 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_wan1_port}")
    result, n11, n21 = ops.cli.execute(handle, "description to-internet")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetA")
    result, n11, n21 = ops.cli.execute(handle, "ip address {dj_wan1_ip_addr} {dj_wan1_mask}")
    result, n11, n21 = ops.cli.execute(handle, "nat outbound 3999")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface LoopBack1000")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecA")
    result, n11, n21 = ops.cli.execute(handle, "ip address {main_ce_docking} 255.255.255.255")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface Tunnel0/0/1000")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "ip address {main_wan_ce_ip} 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "tunnel-protocol gre")
    result, n11, n21 = ops.cli.execute(handle, "source LoopBack1000")
    result, n11, n21 = ops.cli.execute(handle, "destination vpn-instance underlay_ipsecA {main_pe_docking}")
    result, n11, n21 = ops.cli.execute(handle, "mtu 1476")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1300")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "nqa event 1 log")
    result, n11, n21 = ops.cli.execute(handle, "nqa test-instance admin ipsecmain")
    result, n11, n21 = ops.cli.execute(handle, "test-type icmp")
    result, n11, n21 = ops.cli.execute(handle, "destination-address ipv4 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "source-address ipv4 {main_wan_ce_ip}")
    result, n11, n21 = ops.cli.execute(handle, "frequency 15")
    result, n11, n21 = ops.cli.execute(handle, "probe-count 2")
    result, n11, n21 = ops.cli.execute(handle, "vpn-instance underlay_main")
    result, n11, n21 = ops.cli.execute(handle, "alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    result, n11, n21 = ops.cli.execute(handle, "start now")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_ipsecA 0.0.0.0 0.0.0.0 100.98.1.1")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {dj_wan1_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetA {main_dial_ip} 255.255.255.255 {dj_wan1_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 0.0.0.0 0.0.0.0 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 114.113.245.99 255.255.255.255 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_main 192.168.55.250 255.255.255.255 {main_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "aaa")
    result, n11, n21 = ops.cli.execute(handle, "local-user admin service-type terminal ssh http")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ssh server permit interface all")
    result, n11, n21 = ops.cli.execute(handle, "stelnet server enable")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 0")
    result, n11, n21 = ops.cli.execute(handle, "protocol inbound ssh")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 1 4")
    result, n11, n21 = ops.cli.execute(handle, "authentication-mode aaa")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ops")
    result, n11, n21 = ops.cli.execute(handle, "environment mainip {main_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "script-assistant python ipsecmain.py")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    ops.syslog("ops:add_tunnel is success", "critical", "syslog")
    ops.cli.close(handle)
    return 0
"""

TEMPLATE_AR_OPS_DUAL_BACKUP = """\
# coding=utf-8
import ops
import sys
import os


def ops_condition(ops):
    value, descri_str = ops.iclog.subscribe(tag="startup", moduName="DEV", infoAlias="ENTUP", logInfo="register success")
    print('Script has being installed')
    return 0
 
def ops_execute(ops):
    handle, err_desp = ops.cli.open()
    print("\r\n err_desp:%s" % (err_desp))
    choice={"Continue?":"Y"}
    result, n11, n21 = ops.cli.execute(handle, "system-view")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_internetB")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_ipsecB")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ipv4-family")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3334")
    result, n11, n21 = ops.cli.execute(handle, "rule 1 permit ip vpn-instance underlay_ipsecB source {bk_ce_docking} 0 destination {bk_pe_docking} 0")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "acl number 3999")
    result, n11, n21 = ops.cli.execute(handle, "rule 20 permit ip source 100.99.1.0 0.0.0.3")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "esp authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "esp encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "encryption-algorithm 3des", choice)
    result, n11, n21 = ops.cli.execute(handle, "dh group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "authentication-algorithm sha1", choice)
    result, n11, n21 = ops.cli.execute(handle, "sa duration 28800")
    result, n11, n21 = ops.cli.execute(handle, "authentication-method pre-share")
    result, n11, n21 = ops.cli.execute(handle, "integrity-algorithm hmac-sha2-256")
    result, n11, n21 = ops.cli.execute(handle, "prf hmac-sha2-256")
    result, n11, n21 = ops.cli.execute(handle, "ike peer backup")
    result, n11, n21 = ops.cli.execute(handle, "version 1", choice)
    result, n11, n21 = ops.cli.execute(handle, "undo version 2", choice)
    result, n11, n21 = ops.cli.execute(handle, "pre-shared-key cipher {bk_psk}")
    result, n11, n21 = ops.cli.execute(handle, "ike-proposal 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd idle-time 10")
    result, n11, n21 = ops.cli.execute(handle, "dpd type on-demand")
    result, n11, n21 = ops.cli.execute(handle, "dpd retransmit-interval 2")
    result, n11, n21 = ops.cli.execute(handle, "remote-address vpn-instance underlay_ipsecB {bk_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC 20 isakmp")
    result, n11, n21 = ops.cli.execute(handle, "security acl 3334")
    result, n11, n21 = ops.cli.execute(handle, "pfs dh-group2", choice)
    result, n11, n21 = ops.cli.execute(handle, "ike-peer backup")
    result, n11, n21 = ops.cli.execute(handle, "proposal ipsectran1")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_zihuan2_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_zihuan2_port}.99")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 99")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetB")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.99.1.1 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_zihuan2_port}.200")
    result, n11, n21 = ops.cli.execute(handle, "description to-ZiHuan")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 200")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ip address {z_bk_ip} {z_bk_mask}")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_ipsec2_port}")
    result, n11, n21 = ops.cli.execute(handle, "undo portswitch")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_ipsec2_port}.99")
    result, n11, n21 = ops.cli.execute(handle, "description IPsec Tunnel Interface")
    result, n11, n21 = ops.cli.execute(handle, "dot1q termination vid 99")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecB")
    result, n11, n21 = ops.cli.execute(handle, "ip address 100.99.1.2 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "ipsec policy S2S-IPSEC")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface {dj_wan2_port}")
    result, n11, n21 = ops.cli.execute(handle, "description to-internet")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_internetB")
    result, n11, n21 = ops.cli.execute(handle, "ip address {dj_wan2_ip_addr} {dj_wan2_mask}")
    result, n11, n21 = ops.cli.execute(handle, "nat outbound 3999")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface LoopBack1001")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_ipsecB")
    result, n11, n21 = ops.cli.execute(handle, "ip address {bk_ce_docking} 255.255.255.255")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "interface Tunnel0/0/1001")
    result, n11, n21 = ops.cli.execute(handle, "ip binding vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "ip address {bk_wan_ce_ip} 255.255.255.252")
    result, n11, n21 = ops.cli.execute(handle, "tunnel-protocol gre")
    result, n11, n21 = ops.cli.execute(handle, "source LoopBack1001")
    result, n11, n21 = ops.cli.execute(handle, "destination vpn-instance underlay_ipsecB {bk_pe_docking}")
    result, n11, n21 = ops.cli.execute(handle, "mtu 1476")
    result, n11, n21 = ops.cli.execute(handle, "tcp adjust-mss 1300")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "nqa test-instance admin ipsecbackup")
    result, n11, n21 = ops.cli.execute(handle, "test-type icmp")
    result, n11, n21 = ops.cli.execute(handle, "destination-address ipv4 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "source-address ipv4 {bk_wan_ce_ip}")
    result, n11, n21 = ops.cli.execute(handle, "frequency 15")
    result, n11, n21 = ops.cli.execute(handle, "probe-count 2")
    result, n11, n21 = ops.cli.execute(handle, "vpn-instance underlay_backup")
    result, n11, n21 = ops.cli.execute(handle, "alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    result, n11, n21 = ops.cli.execute(handle, "start now")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_ipsecB 0.0.0.0 0.0.0.0 100.99.1.1")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {dj_wan2_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_internetB {bk_dial_ip} 255.255.255.255 {dj_wan2_gw}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 0.0.0.0 0.0.0.0 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 114.113.245.100 255.255.255.255 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "ip route-static vpn-instance underlay_backup 192.168.55.250 255.255.255.255 {bk_wan_peer_ip}")
    result, n11, n21 = ops.cli.execute(handle, "aaa")
    result, n11, n21 = ops.cli.execute(handle, "local-user admin service-type terminal ssh http")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ssh server permit interface all")
    result, n11, n21 = ops.cli.execute(handle, "stelnet server enable")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 0")
    result, n11, n21 = ops.cli.execute(handle, "protocol inbound ssh")
    result, n11, n21 = ops.cli.execute(handle, "user-interface vty 1 4")
    result, n11, n21 = ops.cli.execute(handle, "authentication-mode aaa")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    result, n11, n21 = ops.cli.execute(handle, "ops")
    result, n11, n21 = ops.cli.execute(handle, "environment mainip {bk_dial_ip}")
    result, n11, n21 = ops.cli.execute(handle, "script-assistant python ipsecbackup.py")
    result, n11, n21 = ops.cli.execute(handle, "quit")
    ops.syslog("ops:add_tunnel is success", "critical", "syslog")
    ops.cli.close(handle)
    return 0
"""

TEMPLATE_AR_FACTORY_DUAL_PRIMARY = """\
ip vpn-instance underlay_internetA

ipv4-family

quit

ip vpn-instance underlay_ipsecA

ipv4-family

quit

ip vpn-instance underlay_main

ipv4-family

quit

interface {dj_wan1_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internetA

ip address {dj_wan1_ip_addr} {dj_wan1_mask}

tcp adjust-mss 1200

interface {dj_zihuan1_port}

undo portswitch

interface {dj_zihuan1_port}.98

interface {dj_zihuan1_port}.100

interface {dj_ipsec1_port}

undo portswitch

interface {dj_ipsec1_port}.98

interface Tunnel0/0/1000

ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {dj_wan1_gw}

aaa

 local-user admin service-type terminal ssh http
y

 quit

ssh server permit interface all

stelnet server enable

user-interface vty 0

 protocol inbound ssh

user-interface vty 1 4

 authentication-mode aaa

ftp 59.36.7.222  vpn-instance underlay_internetA

ops install file {lineid_fn}main.py

ops install file ipsecmain.py

system-view

ops

 script-assistant python {lineid_fn}main.py

 script-assistant python ipsecmain.py

ip route-static vpn-instance underlay_internetA {south_primary} 255.255.255.255 {dj_wan1_gw} tag 4400 description agile-controller

agile controller host {south_primary} port 10020 vpn-instance underlay_internetA
quit

set factory-configuration from current-configuration

y

save

Y
"""

TEMPLATE_AR_FACTORY_DUAL_BACKUP = """\
ip vpn-instance underlay_internetB

ipv4-family

quit

ip vpn-instance underlay_ipsecB

ipv4-family

quit

ip vpn-instance underlay_backup

ipv4-family

quit

interface {dj_wan2_port}

description to-wan
undo ipv6 enable

ip binding vpn-instance underlay_internetB

ip address {dj_wan2_ip_addr} {dj_wan2_mask}

tcp adjust-mss 1200

interface {dj_zihuan2_port}

undo portswitch

interface {dj_zihuan2_port}.99

interface {dj_zihuan2_port}.200

interface {dj_ipsec2_port}

undo portswitch

interface {dj_ipsec2_port}.99

interface Tunnel0/0/1001

ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {dj_wan2_gw}

aaa

 local-user admin service-type terminal ssh http
y

 quit

ssh server permit interface all

stelnet server enable

user-interface vty 0

 protocol inbound ssh

user-interface vty 1 4

 authentication-mode aaa

ftp 59.36.7.222  vpn-instance underlay_internetB

ops install file {lineid_fn}backup.py

ops install file ipsecbackup.py

system-view

ops

 script-assistant python {lineid_fn}backup.py

 script-assistant python ipsecbackup.py

ip route-static vpn-instance underlay_internetB {south_backup} 255.255.255.255 {dj_wan2_gw} tag 4400 description agile-controller

agile controller host {south_backup} port 10020 vpn-instance underlay_internetB
quit

set factory-configuration from current-configuration

y

save

Y
"""


# ============================================================
# AR SD-WAN builder functions (template-driven)
# ============================================================

def _build_ar_format_dict(raw, device_type, device_role="pri",
                          dual_wan=False, mode="ops"):
    d = parse_ar_visual(raw)
    d["device_type"] = device_type
    d["device_role"] = device_role
    d["dual_wan"] = dual_wan
    d["mode"] = mode
    d.setdefault("south_primary", "Public Default South Access")
    d.setdefault("south_backup", "CT South Access")
    return d, None


def build_ar_ops_single_wan1_fd(raw):
    return _build_ar_format_dict(raw, "single", "pri", False, "ops")

def build_ar_factory_single_wan1_fd(raw):
    return _build_ar_format_dict(raw, "single", "pri", False, "factory")

def build_ar_ops_single_dualwan_fd(raw):
    return _build_ar_format_dict(raw, "single", "pri", True, "ops")

def build_ar_factory_single_dualwan_fd(raw):
    return _build_ar_format_dict(raw, "single", "pri", True, "factory")

def build_ar_ops_dual_pri_fd(raw):
    return _build_ar_format_dict(raw, "dual", "pri", False, "ops")

def build_ar_ops_dual_bak_fd(raw):
    return _build_ar_format_dict(raw, "dual", "bak", False, "ops")

def build_ar_factory_dual_pri_fd(raw):
    return _build_ar_format_dict(raw, "dual", "pri", False, "factory")

def build_ar_factory_dual_bak_fd(raw):
    return _build_ar_format_dict(raw, "dual", "bak", False, "factory")


def parse_ar_visual(raw_text):
    """可视化编辑器用解析器：返回平面 dict，key 为模板 {var} 变量名。"""
    parsed = parse_ar_sdwan_text(raw_text)
    m = parsed["main"]
    b = parsed["backup"]
    d: dict[str, str] = {}

    for prefix, src in [("main_", m), ("bk_", b)]:
        for k, v in src.items():
            d[prefix + k] = str(v) if v else ""

    d["lineid"] = parsed.get("lineid", "")
    d["lineid_fn"] = _lineid_for_filename(m.get("lineid", ""))

    z_main_ip, z_main_mask = _first_host_mask(m.get("inner_route", ""))
    if not z_main_ip:
        z_main_ip, z_main_mask = "100.88.0.1", "255.255.255.252"
    d["z_main_ip"] = z_main_ip
    d["z_main_mask"] = z_main_mask

    z_bk_ip, z_bk_mask = _first_host_mask(b.get("inner_route", ""))
    if not z_bk_ip:
        z_bk_ip, z_bk_mask = "100.88.1.1", "255.255.255.252"
    d["z_bk_ip"] = z_bk_ip
    d["z_bk_mask"] = z_bk_mask

    d["wan1_port"] = expand_ge_port(DEFAULT_WAN1_PORT)
    wan1_ip_a, wan1_mask_a = _ip_mask_from_cidr(DEFAULT_WAN1_IP)
    d["wan1_ip_addr"] = wan1_ip_a
    d["wan1_mask"] = wan1_mask_a
    d["wan1_gw"] = DEFAULT_WAN1_GW
    d["wan2_port"] = expand_ge_port(DEFAULT_WAN2_PORT)
    wan2_ip_a, wan2_mask_a = _ip_mask_from_cidr(DEFAULT_WAN2_IP)
    d["wan2_ip_addr"] = wan2_ip_a
    d["wan2_mask"] = wan2_mask_a
    d["wan2_gw"] = DEFAULT_WAN2_GW
    d["zihuan_port"] = expand_ge_port(DEFAULT_ZIHUAN_PORT)
    d["ipsec_port"] = expand_ge_port(DEFAULT_IPSEC_PORT)

    d["dj_wan1_port"] = expand_ge_port(DJ_WAN1_PORT)
    dj_w1_ip, dj_w1_m = _ip_mask_from_cidr(DJ_WAN1_IP)
    d["dj_wan1_ip_addr"] = dj_w1_ip
    d["dj_wan1_mask"] = dj_w1_m
    d["dj_wan1_gw"] = DJ_WAN1_GW
    d["dj_zihuan1_port"] = expand_ge_port(DJ_ZIHUAN1_PORT)
    d["dj_ipsec1_port"] = expand_ge_port(DJ_IPSEC1_PORT)

    d["dj_wan2_port"] = expand_ge_port(DJ_WAN2_PORT)
    dj_w2_ip, dj_w2_m = _ip_mask_from_cidr(DJ_WAN2_IP)
    d["dj_wan2_ip_addr"] = dj_w2_ip
    d["dj_wan2_mask"] = dj_w2_m
    d["dj_wan2_gw"] = DJ_WAN2_GW
    d["dj_zihuan2_port"] = expand_ge_port(DJ_ZIHUAN2_PORT)
    d["dj_ipsec2_port"] = expand_ge_port(DJ_IPSEC2_PORT)

    south_pri, _ = _south_ips_by_label(ZH_SOUTH_LABEL_SAVED)
    if south_pri:
        d["south_primary"] = south_pri
    return d


_RE_VISUAL_TPL_VERSION_HDR = re.compile(
    r"^# ={10,}\r?\n"
    r"# 场景模板版本 \| version: (\d+) \| 日期: [^\r\n]+\r?\n"
    r"# ={10,}\r?\n(\r?\n)?",
)


def _strip_visual_tpl_version_header(text: str) -> str:
    m = _RE_VISUAL_TPL_VERSION_HDR.match(text)
    if m:
        return text[m.end() :]
    return text


def _rewrite_ike_cli_execute_version_loose(text: str, want_v2: bool) -> str:
    """成对正则未命中时（换行被改、仅一行等），逐行修正 ops.cli.execute 中的 version/undo。"""
    if want_v2:
        text = re.sub(
            r'ops\.cli\.execute\(handle, "version 1"(, choice)?\)',
            lambda m: f'ops.cli.execute(handle, "version 2"{m.group(1) or ""})',
            text,
        )
        text = re.sub(
            r"ops\.cli\.execute\(handle, 'version 1'(, choice)?\)",
            lambda m: f"ops.cli.execute(handle, 'version 2'{m.group(1) or ''})",
            text,
        )
        text = re.sub(
            r'ops\.cli\.execute\(handle, "undo version 2"(, choice)?\)',
            lambda m: f'ops.cli.execute(handle, "undo version 1"{m.group(1) or ""})',
            text,
        )
        text = re.sub(
            r"ops\.cli\.execute\(handle, 'undo version 2'(, choice)?\)",
            lambda m: f"ops.cli.execute(handle, 'undo version 1'{m.group(1) or ''})",
            text,
        )
    else:
        text = re.sub(
            r'ops\.cli\.execute\(handle, "version 2"(, choice)?\)',
            lambda m: f'ops.cli.execute(handle, "version 1"{m.group(1) or ""})',
            text,
        )
        text = re.sub(
            r"ops\.cli\.execute\(handle, 'version 2'(, choice)?\)",
            lambda m: f"ops.cli.execute(handle, 'version 1'{m.group(1) or ''})",
            text,
        )
        text = re.sub(
            r'ops\.cli\.execute\(handle, "undo version 1"(, choice)?\)',
            lambda m: f'ops.cli.execute(handle, "undo version 2"{m.group(1) or ""})',
            text,
        )
        text = re.sub(
            r"ops\.cli\.execute\(handle, 'undo version 1'(, choice)?\)",
            lambda m: f"ops.cli.execute(handle, 'undo version 2'{m.group(1) or ''})",
            text,
        )
    return text


def _rewrite_ike_peer_version_blocks_in_ops_py(text: str, ike_version: str) -> str:
    """将 OPS 脚本中 ike peer 下成对的 version/undo 行改为与 init_cfg['ike_version'] 一致。

    「我来定模板」保存的内容来自 build_ar_visual_tpl（内嵌 ike v1），{var} 替换不含 IKE CLI，
    若不重写则切换 IKEv1/v2 不生效。双机备机仅一段 peer 时，成对正则可能漏网，再跑宽松行级替换。
    """
    std = _user_init_ike_storage(str(ike_version))
    want_v2 = std == "v2"
    pat = re.compile(
        r"(?P<ind>\s*)result, n11, n21 = ops\.cli\.execute\(handle, \"version (?P<va>[12])\""
        r"(?P<c1>, choice)?\)\s*\r?\n"
        r"(?P=ind)result, n11, n21 = ops\.cli\.execute\(handle, \"undo version (?P<ub>[12])\""
        r"(?P<c2>, choice)?\)",
        re.MULTILINE,
    )

    def _sub(m):
        ind = m.group("ind")
        c1 = m.group("c1") or ""
        c2 = m.group("c2") or ""
        if want_v2:
            return (
                f'{ind}result, n11, n21 = ops.cli.execute(handle, "version 2"{c1})\n'
                f'{ind}result, n11, n21 = ops.cli.execute(handle, "undo version 1"{c2})'
            )
        return (
            f'{ind}result, n11, n21 = ops.cli.execute(handle, "version 1"{c1})\n'
            f'{ind}result, n11, n21 = ops.cli.execute(handle, "undo version 2"{c2})'
        )

    out = pat.sub(_sub, text)
    return _rewrite_ike_cli_execute_version_loose(out, want_v2)


if __name__ == "__main__" and "--selftest-ike" in __import__("sys").argv:
    # 独立运行：不启 GUI，仅验证 IKEv2 改写路径确实执行（嵌入时 __name__ 为 __embedded__，本段跳过）
    _sample = (
        '    result, n11, n21 = ops.cli.execute(handle, "version 1")\n'
        '    result, n11, n21 = ops.cli.execute(handle, "undo version 2")\n'
    )
    _out = _rewrite_ike_peer_version_blocks_in_ops_py(_sample, "v2")
    _ok = 'version 2"' in _out and 'undo version 1"' in _out
    print("IKEv2 rewrite selftest:", "PASS" if _ok else f"FAIL: {_out!r}")
    raise SystemExit(0 if _ok else 1)


def _get_visual_prog_override_map():
    """读取 all_in_one 中 VISUAL_PROG_OVERRIDE。嵌入/exec 命名空间下优先用宿主注入的 __VISUAL_PROG_OVERRIDE_REF__。"""
    import sys

    ref = globals().get("__VISUAL_PROG_OVERRIDE_REF__")
    if isinstance(ref, dict):
        return ref
    mod = sys.modules.get("all_in_one_v2")
    if mod is not None:
        ov = getattr(mod, "VISUAL_PROG_OVERRIDE", None)
        if isinstance(ov, dict):
            return ov
    main = sys.modules.get("__main__")
    if main is not None:
        ov = getattr(main, "VISUAL_PROG_OVERRIDE", None)
        if isinstance(ov, dict):
            return ov
    return None


def _apply_ar_visual_template_override(tpl_key: str, raw_text: str, init_cfg: dict | None = None, lineid: str = ""):
    """all_in_one「我来定模板」保存的覆盖：用 parse_ar_visual 数据填充第③栏 {var}。"""
    ovmap = _get_visual_prog_override_map()
    if not isinstance(ovmap, dict):
        return None
    raw_ov = ovmap.get(tpl_key)
    if not raw_ov or not str(raw_ov).strip():
        return None
    tpl = _strip_visual_tpl_version_header(str(raw_ov).rstrip("\n"))
    data = parse_ar_visual(raw_text)
    cfg = init_cfg or {}
    if lineid:
        data["lineid_fn"] = _lineid_for_filename(lineid)

    # 用正式页当前初始化值覆盖默认值，确保“初始化修改”在模板覆盖路径下也生效
    if "wan1_if" in cfg:
        data["wan1_port"] = str(cfg.get("wan1_if") or "")
    if "wan2_if" in cfg:
        data["wan2_port"] = str(cfg.get("wan2_if") or "")
    if "zihuan_if" in cfg:
        data["zihuan_port"] = str(cfg.get("zihuan_if") or "")
    if "ipsec_if" in cfg:
        data["ipsec_port"] = str(cfg.get("ipsec_if") or "")
    if "wan1_ip" in cfg:
        ip, mask = _ip_mask_from_cidr(str(cfg.get("wan1_ip") or ""))
        data["wan1_ip_addr"] = ip
        data["wan1_mask"] = mask
    if "wan2_ip" in cfg:
        ip, mask = _ip_mask_from_cidr(str(cfg.get("wan2_ip") or ""))
        data["wan2_ip_addr"] = ip
        data["wan2_mask"] = mask
    if "wan1_gw" in cfg:
        data["wan1_gw"] = str(cfg.get("wan1_gw") or "")
    if "wan2_gw" in cfg:
        data["wan2_gw"] = str(cfg.get("wan2_gw") or "")
    if "south_primary" in cfg and cfg.get("south_primary"):
        data["south_primary"] = str(cfg.get("south_primary") or "")
    if "south_backup" in cfg and cfg.get("south_backup"):
        data["south_backup"] = str(cfg.get("south_backup") or "")

    if "wan1_if" in cfg:
        data["dj_wan1_port"] = str(cfg.get("wan1_if") or "")
    if "wan2_if" in cfg:
        data["dj_wan2_port"] = str(cfg.get("wan2_if") or "")
    if "zihuan_if1" in cfg:
        data["dj_zihuan1_port"] = str(cfg.get("zihuan_if1") or "")
    if "ipsec_if1" in cfg:
        data["dj_ipsec1_port"] = str(cfg.get("ipsec_if1") or "")
    if "zihuan_if2" in cfg:
        data["dj_zihuan2_port"] = str(cfg.get("zihuan_if2") or "")
    if "ipsec_if2" in cfg:
        data["dj_ipsec2_port"] = str(cfg.get("ipsec_if2") or "")
    if "wan1_ip" in cfg:
        ip, mask = _ip_mask_from_cidr(str(cfg.get("wan1_ip") or ""))
        data["dj_wan1_ip_addr"] = ip
        data["dj_wan1_mask"] = mask
    if "wan2_ip" in cfg:
        ip, mask = _ip_mask_from_cidr(str(cfg.get("wan2_ip") or ""))
        data["dj_wan2_ip_addr"] = ip
        data["dj_wan2_mask"] = mask
    if "wan1_gw" in cfg:
        data["dj_wan1_gw"] = str(cfg.get("wan1_gw") or "")
    if "wan2_gw" in cfg:
        data["dj_wan2_gw"] = str(cfg.get("wan2_gw") or "")

    def _sub(m):
        var = m.group(1)
        val = data.get(var)
        if val is None or (isinstance(val, str) and not val.strip()):
            return f"[{var}]"
        return str(val)

    out = re.sub(r"\{(\w+)(?::[^}]*)?\}", _sub, tpl)
    iv = _user_init_ike_storage(str(cfg.get("ike_version", "v1")))
    return _rewrite_ike_peer_version_blocks_in_ops_py(out, iv)


def build_ar_visual_tpl(scenario_key: str) -> str:
    """生成带 {var} 占位符的 AR 可视化模板。

    scenario_key: 'ar_ops_single', 'ar_factory_single', 'ar_ops_single_dualwan',
                  'ar_factory_single_dualwan', 'ar_ops_dual_pri', 'ar_ops_dual_bak',
                  'ar_factory_dual_pri', 'ar_factory_dual_bak'
    """
    _S: dict[str, tuple[str, str]] = {}
    _ctr = [0]

    def _unique_ip():
        _ctr[0] += 1
        a = 100 + (_ctr[0] // 250)
        b = _ctr[0] % 250 + 1
        return f"172.{a}.{b}.1"

    def _s(var_name: str, sentinel: str | None = None) -> str:
        if sentinel is None:
            sentinel = _unique_ip()
        _S[sentinel] = ("{" + var_name + "}", var_name)
        return sentinel

    _s_main_pe       = _s("main_pe", "@@MAIN_PE@@")
    _s_main_tunnel   = _s("main_tunnel", "@@MAIN_TUN@@")
    _s_main_psk      = _s("main_psk", "@@MAIN_PSK@@")
    _s_main_lineid   = _s("main_lineid", "@@MAIN_LID@@")
    _s_bk_pe         = _s("bk_pe", "@@BK_PE@@")
    _s_bk_tunnel     = _s("bk_tunnel", "@@BK_TUN@@")
    _s_bk_psk        = _s("bk_psk", "@@BK_PSK@@")
    _s_bk_lineid     = _s("bk_lineid", "@@BK_LID@@")
    _s_lineid_fn     = _s("lineid_fn", "@@LID_FN@@")
    _s_south_primary = _s("south_primary", "@@SOUTH_PRI@@")
    _s_south_backup  = _s("south_backup", "@@SOUTH_BK@@")

    _s_main_ce_dock  = _s("main_ce_docking")
    _s_main_pe_dock  = _s("main_pe_docking")
    _s_main_dial_ip  = _s("main_dial_ip")
    _s_bk_ce_dock    = _s("bk_ce_docking")
    _s_bk_pe_dock    = _s("bk_pe_docking")
    _s_bk_dial_ip    = _s("bk_dial_ip")

    _s_main_wan_peer = _s("main_wan_peer_ip")
    _s_main_wan_ce   = _s("main_wan_ce_ip")
    _s_bk_wan_peer   = _s("bk_wan_peer_ip")
    _s_bk_wan_ce     = _s("bk_wan_ce_ip")

    _s_z_main_ip     = _s("z_main_ip")
    _s_z_main_mask   = _s("z_main_mask", "255.255.241.0")
    _s_z_bk_ip       = _s("z_bk_ip")
    _s_z_bk_mask     = _s("z_bk_mask", "255.255.242.0")

    _s_wan1_port     = _s("wan1_port", "GigabitEthernet0/0/91")
    _s_wan2_port     = _s("wan2_port", "GigabitEthernet0/0/92")
    _s_zihuan_port   = _s("zihuan_port", "GigabitEthernet0/0/93")
    _s_ipsec_port    = _s("ipsec_port", "GigabitEthernet0/0/94")
    _s_wan1_ip_addr  = _s("wan1_ip_addr")
    _s_wan1_mask     = _s("wan1_mask", "255.255.243.0")
    _s_wan1_gw       = _s("wan1_gw")
    _s_wan2_ip_addr  = _s("wan2_ip_addr")
    _s_wan2_mask     = _s("wan2_mask", "255.255.244.0")
    _s_wan2_gw       = _s("wan2_gw")

    _s_dj_wan1_port     = _s("dj_wan1_port", "GigabitEthernet0/0/95")
    _s_dj_wan2_port     = _s("dj_wan2_port", "GigabitEthernet0/0/96")
    _s_dj_zihuan1_port  = _s("dj_zihuan1_port", "GigabitEthernet0/0/97")
    _s_dj_ipsec1_port   = _s("dj_ipsec1_port", "GigabitEthernet0/0/98")
    _s_dj_zihuan2_port  = _s("dj_zihuan2_port", "GigabitEthernet1/0/97")
    _s_dj_ipsec2_port   = _s("dj_ipsec2_port", "GigabitEthernet1/0/98")
    _s_dj_wan1_ip_addr  = _s("dj_wan1_ip_addr")
    _s_dj_wan1_mask     = _s("dj_wan1_mask", "255.255.245.0")
    _s_dj_wan1_gw       = _s("dj_wan1_gw")
    _s_dj_wan2_ip_addr  = _s("dj_wan2_ip_addr")
    _s_dj_wan2_mask     = _s("dj_wan2_mask", "255.255.246.0")
    _s_dj_wan2_gw       = _s("dj_wan2_gw")

    parsed_m = {
        "lineid": _s_main_lineid, "pe": _s_main_pe,
        "tunnel": _s_main_tunnel,
        "wanip": "",
        "wan_peer_ip": _s_main_wan_peer, "wan_ce_ip": _s_main_wan_ce,
        "pe_docking": _s_main_pe_dock, "ce_docking": _s_main_ce_dock,
        "pe_as": "65176",
        "inner_route": "",
        "zihuan_ce_ip": _s_z_main_ip,
        "dial_ip": _s_main_dial_ip, "psk": _s_main_psk,
    }
    parsed_b = {
        "lineid": _s_bk_lineid, "pe": _s_bk_pe,
        "tunnel": _s_bk_tunnel,
        "wanip": "",
        "wan_peer_ip": _s_bk_wan_peer, "wan_ce_ip": _s_bk_wan_ce,
        "pe_docking": _s_bk_pe_dock, "ce_docking": _s_bk_ce_dock,
        "pe_as": "65144",
        "inner_route": "",
        "zihuan_ce_ip": _s_z_bk_ip,
        "dial_ip": _s_bk_dial_ip, "psk": _s_bk_psk,
    }
    parsed = {"main": parsed_m, "backup": parsed_b, "lineid": _s_main_lineid}

    is_dj = ("dual_pri" in scenario_key or "dual_bak" in scenario_key)
    is_factory = "factory" in scenario_key
    is_dualwan = "dualwan" in scenario_key
    is_pri = "pri" in scenario_key

    if is_dj:
        if is_pri:
            init_cfg = {
                "ike_version": "v1",
                "zihuan_if1": _s_dj_zihuan1_port,
                "ipsec_if1": _s_dj_ipsec1_port,
                "wan1_if": _s_dj_wan1_port,
                "wan1_ip": _s_dj_wan1_ip_addr + "/8",
                "wan1_gw": _s_dj_wan1_gw,
                "south_primary": _s_south_primary,
                "south_backup": _s_south_backup,
            }
        else:
            init_cfg = {
                "ike_version": "v1",
                "zihuan_if2": _s_dj_zihuan2_port,
                "ipsec_if2": _s_dj_ipsec2_port,
                "wan2_if": _s_dj_wan2_port,
                "wan2_ip": _s_dj_wan2_ip_addr + "/8",
                "wan2_gw": _s_dj_wan2_gw,
                "south_primary": _s_south_primary,
                "south_backup": _s_south_backup,
            }
    else:
        init_cfg = {
            "dual_wan": is_dualwan,
            "ike_version": "v1",
            "zihuan_if": _s_zihuan_port,
            "ipsec_if": _s_ipsec_port,
            "wan1_if": _s_wan1_port,
            "wan2_if": _s_wan2_port,
            "wan1_ip": _s_wan1_ip_addr + "/8",
            "wan2_ip": _s_wan2_ip_addr + "/8",
            "wan1_gw": _s_wan1_gw,
            "wan2_gw": _s_wan2_gw,
            "south_primary": _s_south_primary,
            "south_backup": _s_south_backup,
        }

    _mask_overrides = {
        _s_wan1_ip_addr: (_s_wan1_ip_addr, _s_wan1_mask),
        _s_wan2_ip_addr: (_s_wan2_ip_addr, _s_wan2_mask),
        _s_dj_wan1_ip_addr: (_s_dj_wan1_ip_addr, _s_dj_wan1_mask),
        _s_dj_wan2_ip_addr: (_s_dj_wan2_ip_addr, _s_dj_wan2_mask),
    }
    _orig_ip_mask_from_cidr = _ip_mask_from_cidr
    _orig_first_host_mask = _first_host_mask

    def _patched_ip_mask(cidr):
        ip_part = cidr.split("/")[0]
        if ip_part in _mask_overrides:
            return _mask_overrides[ip_part]
        return _orig_ip_mask_from_cidr(cidr)

    def _patched_first_host_mask(cidr):
        return _s_z_main_ip, _s_z_main_mask

    _g = globals()
    _saved_ipm = _g["_ip_mask_from_cidr"]
    _saved_fhm = _g["_first_host_mask"]
    _saved_cfg_ge = _g["_cfg_ge"]

    def _patched_cfg_ge(ic, key, default_slot):
        v = ic.get(key)
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return expand_ge_port(default_slot)
        s = str(v).strip()
        if s.startswith("GigabitEthernet"):
            return s
        return expand_ge_port(s)

    try:
        _g["_ip_mask_from_cidr"] = _patched_ip_mask
        _g["_cfg_ge"] = _patched_cfg_ge

        if is_factory:
            lid = _s_lineid_fn
            if is_dj:
                if is_pri:
                    _g["_first_host_mask"] = lambda c: (_s_z_main_ip, _s_z_main_mask)
                    rendered = render_factory_dual_primary(init_cfg, lid)
                else:
                    _g["_first_host_mask"] = lambda c: (_s_z_bk_ip, _s_z_bk_mask)
                    rendered = render_factory_dual_backup(init_cfg, lid)
            else:
                _g["_first_host_mask"] = lambda c: (_s_z_main_ip, _s_z_main_mask)
                rendered = render_factory_single(init_cfg, lid)
        else:
            if is_dj:
                if is_pri:
                    _g["_first_host_mask"] = lambda c: (_s_z_main_ip, _s_z_main_mask)
                    rendered = render_dual_primary(parsed, init_cfg)
                else:
                    _g["_first_host_mask"] = lambda c: (_s_z_bk_ip, _s_z_bk_mask)
                    rendered = render_dual_backup(parsed, init_cfg)
            else:
                _fhm_call = [0]
                def _fhm_toggle(c):
                    _fhm_call[0] += 1
                    if _fhm_call[0] <= 1:
                        return (_s_z_main_ip, _s_z_main_mask)
                    return (_s_z_bk_ip, _s_z_bk_mask)
                _g["_first_host_mask"] = _fhm_toggle
                rendered = render_ops_script(parsed, init_cfg)
    finally:
        _g["_ip_mask_from_cidr"] = _saved_ipm
        _g["_first_host_mask"] = _saved_fhm
        _g["_cfg_ge"] = _saved_cfg_ge

    replacements = sorted(_S.items(), key=lambda x: -len(x[0]))
    for sentinel, (var_placeholder, _) in replacements:
        rendered = rendered.replace(sentinel, var_placeholder)

    return rendered


def _py_exec(cmd, use_choice=False):
    safe = cmd.replace("\\", "\\\\").replace('"', '\\"')
    if use_choice:
        return f'    result, n11, n21 = ops.cli.execute(handle, "{safe}", choice)'
    return f'    result, n11, n21 = ops.cli.execute(handle, "{safe}")'


# =====================================================================
# 单机组网 OPS 脚本生成
# =====================================================================

def render_ops_script(parsed, init_cfg):
    """
    单机：
      单WAN → 单wan双tunnel：4 VRF，共享 ipsec/internet，sha2-256，proposal 有 quit，ops 有 quit
      双WAN → 双wan双tunnel：6 VRF，独立 A/B，sha1-96，proposal 无 quit，ops 无 quit
    """
    m = parsed["main"]
    b = parsed["backup"]
    dual_wan    = bool(init_cfg.get("dual_wan"))
    ike_version = _user_init_ike_storage(str(init_cfg.get("ike_version", "v1")))
    zf  = _cfg_ge(init_cfg, "zihuan_if", DEFAULT_ZIHUAN_PORT)
    ipf = _cfg_ge(init_cfg, "ipsec_if", DEFAULT_IPSEC_PORT)
    w1  = _cfg_ge(init_cfg, "wan1_if", DEFAULT_WAN1_PORT)
    w2  = _cfg_ge(init_cfg, "wan2_if", DEFAULT_WAN2_PORT)

    wan1_ip, wan1_mask = _ip_mask_from_cidr(init_cfg.get("wan1_ip") or DEFAULT_WAN1_IP)
    wan2_ip, wan2_mask = _ip_mask_from_cidr(init_cfg.get("wan2_ip") or DEFAULT_WAN2_IP)
    wan1_gw = init_cfg.get("wan1_gw") or DEFAULT_WAN1_GW
    wan2_gw = init_cfg.get("wan2_gw") or DEFAULT_WAN2_GW
    z_main_ip, z_main_mask = _first_host_mask(m["inner_route"])
    z_bk_ip,   z_bk_mask   = _first_host_mask(b["inner_route"])
    if not z_main_ip:
        z_main_ip, z_main_mask = "100.88.0.1", "255.255.255.252"
    if not z_bk_ip:
        z_bk_ip,   z_bk_mask   = "100.88.1.1", "255.255.255.252"

    psk_main = m["psk"] or "both-win"
    psk_bk   = b["psk"] or psk_main
    gw_b = wan2_gw if dual_wan else wan1_gw

    body = []
    body.append("# coding=utf-8")
    body.append("import ops"); body.append("import sys"); body.append("import os")
    body.append(""); body.append("")
    body.append("def ops_condition(ops):")
    body.append('    value, descri_str = ops.iclog.subscribe(tag="startup", moduName="OPS",'
                ' infoAlias="ENTUP", logInfo="register success")')
    body.append("    return 0"); body.append(""); body.append("")
    body.append("def ops_execute(ops):")
    body.append("    handle, err_desp = ops.cli.open()")
    body.append('    choice={" Continue?":"Y"}' if dual_wan else '    choice={"Continue?":"Y"}')

    def add(cmd, ch=False):
        body.append(_py_exec(cmd, ch))

    add("system-view")
    if dual_wan:
        add("ip vpn-instance underlay_internetA"); add("ipv4-family"); add("quit")
        add("ip vpn-instance underlay_internetB"); add("ipv4-family"); add("quit")
        add("ip vpn-instance underlay_ipsecA");    add("ipv4-family"); add("quit")
        add("ip vpn-instance underlay_ipsecB");    add("ipv4-family"); add("quit")
    else:
        add("ip vpn-instance underlay_internet"); add("ipv4-family"); add("quit")
        add("ip vpn-instance underlay_ipsec");    add("ipv4-family"); add("quit")
    add("ip vpn-instance underlay_main");   add("ipv4-family"); add("quit")
    add("ip vpn-instance underlay_backup"); add("ipv4-family"); add("quit")
    add("quit")

    add("acl number 3333")
    if dual_wan:
        add(f"rule 1 permit ip vpn-instance underlay_ipsecA source {m['ce_docking']} 0 destination {m['pe_docking']} 0")
        add("acl number 3334")
        add(f"rule 1 permit ip vpn-instance underlay_ipsecB source {b['ce_docking']} 0 destination {b['pe_docking']} 0")
    else:
        add(f"rule 1 permit ip vpn-instance underlay_ipsec source {m['ce_docking']} 0 destination {m['pe_docking']} 0")
        add("quit")
        add("acl number 3334")
        add(f"rule 1 permit ip vpn-instance underlay_ipsec source {b['ce_docking']} 0 destination {b['pe_docking']} 0")
    add("quit")
    add("acl number 3999")
    add("rule 10 permit ip source 100.98.1.0 0.0.0.3")
    if dual_wan:
        add("rule 20 permit ip source 100.99.1.0 0.0.0.3")
    add("quit")

    add("ipsec proposal ipsectran1")
    add("esp authentication-algorithm sha1", True)
    add("esp encryption-algorithm 3des", True)
    if not dual_wan:
        add("quit")
    add("ike proposal 10")
    add("encryption-algorithm 3des", True); add("dh group2", True)
    add("authentication-algorithm sha1", True); add("sa duration 28800")
    add("authentication-method pre-share")
    if dual_wan:
        add("integrity-algorithm hmac-sha1-96"); add("prf hmac-sha1")
    else:
        add("integrity-algorithm hmac-sha2-256"); add("prf hmac-sha2-256"); add("quit")

    add("ike peer main")
    if ike_version == "v2":
        add("version 2", True); add("undo version 1", True)
    else:
        add("version 1", True); add("undo version 2", True)
    add(f"pre-shared-key cipher {psk_main}")
    add("ike-proposal 10"); add("dpd idle-time 10")
    add("dpd type on-demand"); add("dpd retransmit-interval 2")
    add(f"remote-address vpn-instance underlay_ipsecA {m['dial_ip']}" if dual_wan
        else f"remote-address vpn-instance underlay_ipsec {m['dial_ip']}")
    add("quit")
    add("ike peer backup")
    if ike_version == "v2":
        add("version 2", True); add("undo version 1", True)
    else:
        add("version 1", True); add("undo version 2", True)
    add(f"pre-shared-key cipher {psk_bk}")
    add("ike-proposal 10"); add("dpd idle-time 10")
    add("dpd type on-demand"); add("dpd retransmit-interval 2")
    add(f"remote-address vpn-instance underlay_ipsecB {b['dial_ip']}" if dual_wan
        else f"remote-address vpn-instance underlay_ipsec {b['dial_ip']}")
    add("quit")

    if dual_wan:
        add("ipsec policy S2S-IPSEC-A 10 isakmp"); add("security acl 3333")
        add("pfs dh-group2", True); add("ike-peer main"); add("proposal ipsectran1")
        add("ipsec policy S2S-IPSEC-B 20 isakmp"); add("security acl 3334")
        add("pfs dh-group2", True); add("ike-peer backup"); add("proposal ipsectran1")
    else:
        add("ipsec policy S2S-IPSEC 10 isakmp"); add("security acl 3333")
        add("pfs dh-group2", True); add("ike-peer main"); add("proposal ipsectran1")
        add("ipsec policy S2S-IPSEC 20 isakmp"); add("security acl 3334")
        add("pfs dh-group2", True); add("ike-peer backup"); add("proposal ipsectran1")
    add("quit")

    add(f"interface {zf}"); add("undo portswitch")
    add(f"interface {zf}.98")
    add("description IPsec Tunnel Interface"); add("dot1q termination vid 98")
    add("ip binding vpn-instance underlay_internetA" if dual_wan
        else "ip binding vpn-instance underlay_internet")
    add("ip address 100.98.1.1 255.255.255.252"); add("quit")
    if dual_wan:
        add(f"interface {zf}.99")
        add("description IPsec Tunnel Interface"); add("dot1q termination vid 99")
        add("ip binding vpn-instance underlay_internetB")
        add("ip address 100.99.1.1 255.255.255.252"); add("quit")
    add(f"interface {zf}.100")
    add("description to-ZiHuan"); add("dot1q termination vid 100")
    add("ip binding vpn-instance underlay_main")
    add(f"ip address {z_main_ip} {z_main_mask}")
    add(f"interface {zf}.200")
    add("description to-ZiHuan"); add("dot1q termination vid 200")
    add("ip binding vpn-instance underlay_backup")
    add(f"ip address {z_bk_ip} {z_bk_mask}"); add("quit")

    add(f"interface {ipf}"); add("undo portswitch")
    add(f"interface {ipf}.98")
    add("description IPsec Tunnel Interface"); add("dot1q termination vid 98")
    add("ip binding vpn-instance underlay_ipsecA" if dual_wan
        else "ip binding vpn-instance underlay_ipsec")
    add("ip address 100.98.1.2 255.255.255.252")
    add("ipsec policy S2S-IPSEC-A" if dual_wan else "ipsec policy S2S-IPSEC"); add("quit")
    if dual_wan:
        add(f"interface {ipf}.99")
        add("description IPsec Tunnel Interface"); add("dot1q termination vid 99")
        add("ip binding vpn-instance underlay_ipsecB")
        add("ip address 100.99.1.2 255.255.255.252")
        add("ipsec policy S2S-IPSEC-B"); add("quit")

    if dual_wan:
        add(f"interface {w1}")
        add("ip binding vpn-instance underlay_internetA"); add("description to-wan1")
        add("tcp adjust-mss 1200"); add(f"ip address {wan1_ip} {wan1_mask}")
        add("nat outbound 3999"); add("quit")
        add(f"interface {w2}")
        add("ip binding vpn-instance underlay_internetB"); add("description to-wan2")
        add("tcp adjust-mss 1200"); add(f"ip address {wan2_ip} {wan2_mask}")
        add("nat outbound 3999"); add("quit")
    else:
        add(f"interface {w1}")
        add("description to-internet")
        add("ip binding vpn-instance underlay_internet")
        add(f"ip address {wan1_ip} {wan1_mask}")
        add("nat outbound 3999"); add("quit")

    add("interface LoopBack1000")
    add("ip binding vpn-instance underlay_ipsecA" if dual_wan
        else "ip binding vpn-instance underlay_ipsec")
    add(f"ip address {m['ce_docking']} 255.255.255.255"); add("quit")
    add("interface LoopBack1001")
    add("ip binding vpn-instance underlay_ipsecB" if dual_wan
        else "ip binding vpn-instance underlay_ipsec")
    add(f"ip address {b['ce_docking']} 255.255.255.255"); add("quit")

    add("interface Tunnel0/0/1000")
    add(f"description 'pri to {m['pe']} {m['tunnel']}'")
    add("ip binding vpn-instance underlay_main")
    add(f"ip address {m['wan_ce_ip']} 255.255.255.252")
    add("tunnel-protocol gre"); add("source LoopBack1000")
    add(f"destination vpn-instance underlay_ipsecA {m['pe_docking']}" if dual_wan
        else f"destination vpn-instance underlay_ipsec {m['pe_docking']}")
    add("mtu 1476"); add("tcp adjust-mss 1300"); add("quit")
    add("interface Tunnel0/0/1001")
    add(f"description 'bk to {b['pe']} {b['tunnel']}'")
    add("ip binding vpn-instance underlay_backup")
    add(f"ip address {b['wan_ce_ip']} 255.255.255.252")
    add("tunnel-protocol gre"); add("source LoopBack1001")
    add(f"destination vpn-instance underlay_ipsecB {b['pe_docking']}" if dual_wan
        else f"destination vpn-instance underlay_ipsec {b['pe_docking']}")
    add("mtu 1476"); add("tcp adjust-mss 1300"); add("quit")

    add("nqa event 1 log")
    add("nqa test-instance admin ipsecmain"); add("test-type icmp")
    add(f"destination-address ipv4 {m['wan_peer_ip']}")
    add(f"source-address ipv4 {m['wan_ce_ip']}")
    add("frequency 15"); add("probe-count 2"); add("vpn-instance underlay_main")
    add("alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    add("start now"); add("quit")
    add("nqa test-instance admin ipsecbackup"); add("test-type icmp")
    add(f"destination-address ipv4 {b['wan_peer_ip']}")
    add(f"source-address ipv4 {b['wan_ce_ip']}")
    add("frequency 15"); add("probe-count 2"); add("vpn-instance underlay_backup")
    add("alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    add("start now"); add("quit")

    if dual_wan:
        add("ip route-static vpn-instance underlay_ipsecA 0.0.0.0 0.0.0.0 100.98.1.1")
        add(f"ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {wan1_gw}")
        add(f"ip route-static vpn-instance underlay_internetA {m['dial_ip']} 255.255.255.255 {wan1_gw}")
        add(f"ip route-static vpn-instance underlay_main 0.0.0.0 0.0.0.0 {m['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_main 114.113.245.99 255.255.255.255 {m['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_main 192.168.55.250 255.255.255.255 {m['wan_peer_ip']}")
        add("ip route-static vpn-instance underlay_ipsecB 0.0.0.0 0.0.0.0 100.99.1.1")
        add(f"ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {gw_b}")
        add(f"ip route-static vpn-instance underlay_internetB {b['dial_ip']} 255.255.255.255 {gw_b}")
        add(f"ip route-static vpn-instance underlay_backup 0.0.0.0 0.0.0.0 {b['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_backup 114.113.245.100 255.255.255.255 {b['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_backup 192.168.55.250 255.255.255.255 {b['wan_peer_ip']}")
    else:
        add("ip route-static vpn-instance underlay_ipsec 0.0.0.0 0.0.0.0 100.98.1.1")
        add(f"ip route-static vpn-instance underlay_internet 0.0.0.0 0.0.0.0 {wan1_gw}")
        add(f"ip route-static vpn-instance underlay_internet {m['dial_ip']} 255.255.255.255 {wan1_gw}")
        add(f"ip route-static vpn-instance underlay_internet {b['dial_ip']} 255.255.255.255 {wan1_gw}")
        add(f"ip route-static vpn-instance underlay_main 0.0.0.0 0.0.0.0 {m['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_main 114.113.245.99 255.255.255.255 {m['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_main 192.168.55.250 255.255.255.255 {m['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_backup 0.0.0.0 0.0.0.0 {b['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_backup 114.113.245.100 255.255.255.255 {b['wan_peer_ip']}")
        add(f"ip route-static vpn-instance underlay_backup 192.168.55.250 255.255.255.255 {b['wan_peer_ip']}")

    add("aaa"); add("local-user admin service-type terminal ssh http"); add("quit")
    add("ssh server permit interface all"); add("stelnet server enable")
    add("user-interface vty 0"); add("protocol inbound ssh")
    add("user-interface vty 1 4"); add("authentication-mode aaa"); add("quit")
    add("ops")
    add(f"environment mainip {m['dial_ip']}")
    add("script-assistant python ipsecmain.py")
    add(f"environment backupip {b['dial_ip']}")
    add("script-assistant python ipsecbackup.py")
    if not dual_wan:
        add("quit")

    body.append('    ops.syslog("ops:add_tunnel is success", "critical", "syslog")')
    body.append("    ops.cli.close(handle)")
    body.append("    return 0"); body.append("")
    return "\n".join(body)


# =====================================================================
# 双机组网 OPS 脚本生成（主设备 / 备设备各自独立）
# =====================================================================

def render_dual_primary(parsed, init_cfg):
    """双机主设备：含 main tunnel，VRF: internetA / ipsecA / main，IKE sha1-96。"""
    m = parsed["main"]
    zf  = _cfg_ge(init_cfg, "zihuan_if1", DJ_ZIHUAN1_PORT)
    ipf = _cfg_ge(init_cfg, "ipsec_if1", DJ_IPSEC1_PORT)
    w1  = _cfg_ge(init_cfg, "wan1_if", DJ_WAN1_PORT)
    wan1_ip, wan1_mask = _ip_mask_from_cidr(init_cfg.get("wan1_ip") or DJ_WAN1_IP)
    wan1_gw = init_cfg.get("wan1_gw") or DJ_WAN1_GW
    z_main_ip, z_main_mask = _first_host_mask(m["inner_route"])
    if not z_main_ip:
        z_main_ip, z_main_mask = "100.88.0.1", "255.255.255.252"
    psk_main    = m["psk"] or "both-win"
    ike_version = _user_init_ike_storage(str(init_cfg.get("ike_version", "v1")))

    body = []
    body.append("# coding=utf-8")
    body.append("import ops"); body.append("import sys"); body.append("import os")
    body.append(""); body.append("")
    body.append("def ops_condition(ops):")
    body.append('    value, descri_str = ops.iclog.subscribe(tag="startup", moduName="OPS",'
                ' infoAlias="ENTUP", logInfo="register success")')
    body.append("    return 0"); body.append(""); body.append("")
    body.append("def ops_execute(ops):")
    body.append("    handle, err_desp = ops.cli.open()")
    body.append('    choice={" Continue?":"Y"}')

    def add(cmd, ch=False):
        body.append(_py_exec(cmd, ch))

    add("system-view")
    # 3 VRFs
    add("ip vpn-instance underlay_internetA"); add("ipv4-family"); add("quit")
    add("ip vpn-instance underlay_ipsecA");    add("ipv4-family"); add("quit")
    add("ip vpn-instance underlay_main");      add("ipv4-family"); add("quit")
    add("quit")
    # ACL 3333（独立 quit）
    add("acl number 3333")
    add(f"rule 1 permit ip vpn-instance underlay_ipsecA source {m['ce_docking']} 0 destination {m['pe_docking']} 0")
    add("quit")
    # ACL 3999 仅 rule 10
    add("acl number 3999")
    add("rule 10 permit ip source 100.98.1.0 0.0.0.3")
    add("quit")
    # ipsec proposal（无 quit）
    add("ipsec proposal ipsectran1")
    add("esp authentication-algorithm sha1", True)
    add("esp encryption-algorithm 3des", True)
    # ike proposal sha1-96（无 quit）
    add("ike proposal 10")
    add("encryption-algorithm 3des", True); add("dh group2", True)
    add("authentication-algorithm sha1", True); add("sa duration 28800")
    add("authentication-method pre-share")
    add("integrity-algorithm hmac-sha1-96"); add("prf hmac-sha1")
    # ike peer main
    add("ike peer main")
    if ike_version == "v2":
        add("version 2", True); add("undo version 1", True)
    else:
        add("version 1", True); add("undo version 2", True)
    add(f"pre-shared-key cipher {psk_main}")
    add("ike-proposal 10"); add("dpd idle-time 10")
    add("dpd type on-demand"); add("dpd retransmit-interval 2")
    add(f"remote-address vpn-instance underlay_ipsecA {m['dial_ip']}")
    add("quit")
    # ipsec policy S2S-IPSEC 10
    add("ipsec policy S2S-IPSEC 10 isakmp"); add("security acl 3333")
    add("pfs dh-group2", True); add("ike-peer main"); add("proposal ipsectran1")
    add("quit")
    # zf：.98（internetA）+ .100（main）
    add(f"interface {zf}"); add("undo portswitch")
    add(f"interface {zf}.98")
    add("description IPsec Tunnel Interface"); add("dot1q termination vid 98")
    add("ip binding vpn-instance underlay_internetA")
    add("ip address 100.98.1.1 255.255.255.252"); add("quit")
    add(f"interface {zf}.100")
    add("description to-ZiHuan"); add("dot1q termination vid 100")
    add("ip binding vpn-instance underlay_main")
    add(f"ip address {z_main_ip} {z_main_mask}"); add("quit")
    # ipf：.98（ipsecA + S2S-IPSEC）
    add(f"interface {ipf}"); add("undo portswitch")
    add(f"interface {ipf}.98")
    add("description IPsec Tunnel Interface"); add("dot1q termination vid 98")
    add("ip binding vpn-instance underlay_ipsecA")
    add("ip address 100.98.1.2 255.255.255.252")
    add("ipsec policy S2S-IPSEC"); add("quit")
    # WAN：description first，无 mss
    add(f"interface {w1}")
    add("description to-internet")
    add("ip binding vpn-instance underlay_internetA")
    add(f"ip address {wan1_ip} {wan1_mask}")
    add("nat outbound 3999"); add("quit")
    # LoopBack1000
    add("interface LoopBack1000")
    add("ip binding vpn-instance underlay_ipsecA")
    add(f"ip address {m['ce_docking']} 255.255.255.255"); add("quit")
    # Tunnel0/0/1000（无 description）
    add("interface Tunnel0/0/1000")
    add("ip binding vpn-instance underlay_main")
    add(f"ip address {m['wan_ce_ip']} 255.255.255.252")
    add("tunnel-protocol gre"); add("source LoopBack1000")
    add(f"destination vpn-instance underlay_ipsecA {m['pe_docking']}")
    add("mtu 1476"); add("tcp adjust-mss 1300"); add("quit")
    # NQA（有 nqa event 1 log）
    add("nqa event 1 log")
    add("nqa test-instance admin ipsecmain"); add("test-type icmp")
    add(f"destination-address ipv4 {m['wan_peer_ip']}")
    add(f"source-address ipv4 {m['wan_ce_ip']}")
    add("frequency 15"); add("probe-count 2"); add("vpn-instance underlay_main")
    add("alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    add("start now"); add("quit")
    # 静态路由
    add("ip route-static vpn-instance underlay_ipsecA 0.0.0.0 0.0.0.0 100.98.1.1")
    add(f"ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {wan1_gw}")
    add(f"ip route-static vpn-instance underlay_internetA {m['dial_ip']} 255.255.255.255 {wan1_gw}")
    add(f"ip route-static vpn-instance underlay_main 0.0.0.0 0.0.0.0 {m['wan_peer_ip']}")
    add(f"ip route-static vpn-instance underlay_main 114.113.245.99 255.255.255.255 {m['wan_peer_ip']}")
    add(f"ip route-static vpn-instance underlay_main 192.168.55.250 255.255.255.255 {m['wan_peer_ip']}")
    # AAA / SSH
    add("aaa"); add("local-user admin service-type terminal ssh http"); add("quit")
    add("ssh server permit interface all"); add("stelnet server enable")
    add("user-interface vty 0"); add("protocol inbound ssh")
    add("user-interface vty 1 4"); add("authentication-mode aaa"); add("quit")
    # OPS（mainip → ipsecmain.py → quit）
    add("ops")
    add(f"environment mainip {m['dial_ip']}")
    add("script-assistant python ipsecmain.py")
    add("quit")

    body.append('    ops.syslog("ops:add_tunnel is success", "critical", "syslog")')
    body.append("    ops.cli.close(handle)")
    body.append("    return 0"); body.append("")
    return "\n".join(body)


def render_dual_backup(parsed, init_cfg):
    """双机备设备：含 backup tunnel，VRF: internetB / ipsecB / backup，IKE sha2-256。"""
    b = parsed["backup"]
    zf  = _cfg_ge(init_cfg, "zihuan_if2", DJ_ZIHUAN2_PORT)
    ipf = _cfg_ge(init_cfg, "ipsec_if2", DJ_IPSEC2_PORT)
    w2  = _cfg_ge(init_cfg, "wan2_if", DJ_WAN2_PORT)
    wan2_ip, wan2_mask = _ip_mask_from_cidr(init_cfg.get("wan2_ip") or DJ_WAN2_IP)
    wan2_gw = init_cfg.get("wan2_gw") or DJ_WAN2_GW
    z_bk_ip, z_bk_mask = _first_host_mask(b["inner_route"])
    if not z_bk_ip:
        z_bk_ip, z_bk_mask = "100.88.1.1", "255.255.255.252"
    psk_bk      = b["psk"] or "both-win"
    ike_version = _user_init_ike_storage(str(init_cfg.get("ike_version", "v1")))

    body = []
    body.append("# coding=utf-8")
    body.append("import ops"); body.append("import sys"); body.append("import os")
    body.append(""); body.append("")
    body.append("def ops_condition(ops):")
    body.append('    value, descri_str = ops.iclog.subscribe(tag="startup", moduName="OPS",'
                ' infoAlias="ENTUP", logInfo="register success")')
    body.append("    return 0"); body.append(""); body.append("")
    body.append("def ops_execute(ops):")
    body.append("    handle, err_desp = ops.cli.open()")
    body.append('    choice={" Continue?":"Y"}')

    def add(cmd, ch=False):
        body.append(_py_exec(cmd, ch))

    add("system-view")
    # 3 VRFs
    add("ip vpn-instance underlay_internetB"); add("ipv4-family"); add("quit")
    add("ip vpn-instance underlay_ipsecB");    add("ipv4-family"); add("quit")
    add("ip vpn-instance underlay_backup");    add("ipv4-family"); add("quit")
    add("quit")
    # ACL 3334（独立 quit）
    add("acl number 3334")
    add(f"rule 1 permit ip vpn-instance underlay_ipsecB source {b['ce_docking']} 0 destination {b['pe_docking']} 0")
    add("quit")
    # ACL 3999 仅 rule 20
    add("acl number 3999")
    add("rule 20 permit ip source 100.99.1.0 0.0.0.3")
    add("quit")
    # ipsec proposal（无 quit）
    add("ipsec proposal ipsectran1")
    add("esp authentication-algorithm sha1", True)
    add("esp encryption-algorithm 3des", True)
    # ike proposal sha2-256（无 quit）
    add("ike proposal 10")
    add("encryption-algorithm 3des", True); add("dh group2", True)
    add("authentication-algorithm sha1", True); add("sa duration 28800")
    add("authentication-method pre-share")
    add("integrity-algorithm hmac-sha2-256"); add("prf hmac-sha2-256")
    # ike peer backup
    add("ike peer backup")
    if ike_version == "v2":
        add("version 2", True); add("undo version 1", True)
    else:
        add("version 1", True); add("undo version 2", True)
    add(f"pre-shared-key cipher {psk_bk}")
    add("ike-proposal 10"); add("dpd idle-time 10")
    add("dpd type on-demand"); add("dpd retransmit-interval 2")
    add(f"remote-address vpn-instance underlay_ipsecB {b['dial_ip']}")
    add("quit")
    # ipsec policy S2S-IPSEC 20
    add("ipsec policy S2S-IPSEC 20 isakmp"); add("security acl 3334")
    add("pfs dh-group2", True); add("ike-peer backup"); add("proposal ipsectran1")
    add("quit")
    # zf：.99（internetB）+ .200（backup）
    add(f"interface {zf}"); add("undo portswitch")
    add(f"interface {zf}.99")
    add("description IPsec Tunnel Interface"); add("dot1q termination vid 99")
    add("ip binding vpn-instance underlay_internetB")
    add("ip address 100.99.1.1 255.255.255.252"); add("quit")
    add(f"interface {zf}.200")
    add("description to-ZiHuan"); add("dot1q termination vid 200")
    add("ip binding vpn-instance underlay_backup")
    add(f"ip address {z_bk_ip} {z_bk_mask}"); add("quit")
    # ipf：.99（ipsecB + S2S-IPSEC）
    add(f"interface {ipf}"); add("undo portswitch")
    add(f"interface {ipf}.99")
    add("description IPsec Tunnel Interface"); add("dot1q termination vid 99")
    add("ip binding vpn-instance underlay_ipsecB")
    add("ip address 100.99.1.2 255.255.255.252")
    add("ipsec policy S2S-IPSEC"); add("quit")
    # WAN：description first，无 mss
    add(f"interface {w2}")
    add("description to-internet")
    add("ip binding vpn-instance underlay_internetB")
    add(f"ip address {wan2_ip} {wan2_mask}")
    add("nat outbound 3999"); add("quit")
    # LoopBack1001
    add("interface LoopBack1001")
    add("ip binding vpn-instance underlay_ipsecB")
    add(f"ip address {b['ce_docking']} 255.255.255.255"); add("quit")
    # Tunnel0/0/1001（无 description，无 nqa event 1 log）
    add("interface Tunnel0/0/1001")
    add("ip binding vpn-instance underlay_backup")
    add(f"ip address {b['wan_ce_ip']} 255.255.255.252")
    add("tunnel-protocol gre"); add("source LoopBack1001")
    add(f"destination vpn-instance underlay_ipsecB {b['pe_docking']}")
    add("mtu 1476"); add("tcp adjust-mss 1300"); add("quit")
    # NQA（无 nqa event 1 log）
    add("nqa test-instance admin ipsecbackup"); add("test-type icmp")
    add(f"destination-address ipv4 {b['wan_peer_ip']}")
    add(f"source-address ipv4 {b['wan_ce_ip']}")
    add("frequency 15"); add("probe-count 2"); add("vpn-instance underlay_backup")
    add("alarm 1 lost-packet-ratio absolute rising-threshold 100 1")
    add("start now"); add("quit")
    # 静态路由
    add("ip route-static vpn-instance underlay_ipsecB 0.0.0.0 0.0.0.0 100.99.1.1")
    add(f"ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {wan2_gw}")
    add(f"ip route-static vpn-instance underlay_internetB {b['dial_ip']} 255.255.255.255 {wan2_gw}")
    add(f"ip route-static vpn-instance underlay_backup 0.0.0.0 0.0.0.0 {b['wan_peer_ip']}")
    add(f"ip route-static vpn-instance underlay_backup 114.113.245.100 255.255.255.255 {b['wan_peer_ip']}")
    add(f"ip route-static vpn-instance underlay_backup 192.168.55.250 255.255.255.255 {b['wan_peer_ip']}")
    # AAA / SSH
    add("aaa"); add("local-user admin service-type terminal ssh http"); add("quit")
    add("ssh server permit interface all"); add("stelnet server enable")
    add("user-interface vty 0"); add("protocol inbound ssh")
    add("user-interface vty 1 4"); add("authentication-mode aaa"); add("quit")
    # OPS（备设备也用 mainip 变量名，与模板一致）
    add("ops")
    add(f"environment mainip {b['dial_ip']}")
    add("script-assistant python ipsecbackup.py")
    add("quit")

    body.append('    ops.syslog("ops:add_tunnel is success", "critical", "syslog")')
    body.append("    ops.cli.close(handle)")
    body.append("    return 0"); body.append("")
    return "\n".join(body)


# =====================================================================
# Factory 脚本生成（初始化下发；VRF 与 OPS 脚本保持完全一致）
# =====================================================================

def _fvpn(*names):
    out = []
    for n in names:
        out += [f"ip vpn-instance {n}", "", "ipv4-family", "", "quit", ""]
    return out


def _fwan_blk(if_name, ip, mask, internet_vrf):
    """WAN 接口块：绑定到 internet VRF（与 OPS 脚本一致）。"""
    return [
        f"interface {if_name}",
        "",
        "description to-wan",
        "undo ipv6 enable",
        "",
        f"ip binding vpn-instance {internet_vrf}",
        "",
        f"ip address {ip} {mask}",
        "",
        "tcp adjust-mss 1200",
        "",
    ]


def _fzf_ipf(if_name, subs):
    """undo portswitch + 子接口（与 OPS 脚本子接口完全对应）。"""
    out = [f"interface {if_name}", "", "undo portswitch", ""]
    for s in subs:
        out += [f"interface {if_name}{s}", ""]
    return out


def _faaa_ssh():
    return [
        "aaa",
        "",
        " local-user admin service-type terminal ssh http",
        "y",
        "",
        " quit",
        "",
        "ssh server permit interface all",
        "",
        "stelnet server enable",
        "",
        "user-interface vty 0",
        "",
        " protocol inbound ssh",
        "",
        "user-interface vty 1 4",
        "",
        " authentication-mode aaa",
        "",
    ]


def _f_suffix(ftp_vrf, ops_files, script_files, agile_entries, lid):
    """
    Factory 脚本尾部：
      FTP → ops install → system-view/ops/script-assistant
      → south agile 路由（每条独立 VRF）→ set factory / save
    agile_entries: list of (internet_vrf, south_ip, gw) tuples
    """
    _ftp_server = globals().get("DEFAULT_FTP_SERVER", "59.36.7.222")
    L = []
    L += [
        f"ftp {_ftp_server}  vpn-instance {ftp_vrf}",
        "",
    ]
    for f in ops_files:
        L += [f"ops install file {f}", ""]
    # system-view → ops → script-assistant
    L += ["system-view", "", "ops", ""]
    for s in script_files:
        L += [f" script-assistant python {s}", ""]
    # 南向路由（tag 4400）+ agile controller（每个 VRF/IP 独立生成）
    for ivrf, south_ip, gw in (agile_entries or []):
        if south_ip and gw:
            L += [
                f"ip route-static vpn-instance {ivrf} {south_ip} 255.255.255.255"
                f" {gw} tag 4400 description agile-controller",
                "",
                f"agile controller host {south_ip} port 10020 vpn-instance {ivrf}",
                "quit",
                "",
            ]
    # 结尾固化
    L += [
        "set factory-configuration from current-configuration",
        "",
        "y",
        "",
        "save",
        "",
        "Y",
    ]
    return L


def render_factory_single(init_cfg, lineid):
    """
    单机 Factory 脚本。
    单WAN：underlay_internet / underlay_ipsec / main / backup
    双WAN：underlay_internetA/B / underlay_ipsecA/B / main / backup
    """
    dual_wan  = bool(init_cfg.get("dual_wan"))
    zf  = _cfg_ge(init_cfg, "zihuan_if", DEFAULT_ZIHUAN_PORT)
    ipf = _cfg_ge(init_cfg, "ipsec_if", DEFAULT_IPSEC_PORT)
    w1  = _cfg_ge(init_cfg, "wan1_if", DEFAULT_WAN1_PORT)
    wan1_ip, wan1_mask = _ip_mask_from_cidr(init_cfg.get("wan1_ip") or DEFAULT_WAN1_IP)
    wan1_gw   = init_cfg.get("wan1_gw") or DEFAULT_WAN1_GW
    south_pri = init_cfg.get("south_primary")
    south_bak = init_cfg.get("south_backup")
    lid = _lineid_for_filename(lineid)

    L = []

    # ── VPN 实例（与 OPS 脚本完全一致，无 escape）──────────────────
    if dual_wan:
        L += _fvpn("underlay_internetA", "underlay_internetB",
                   "underlay_ipsecA",    "underlay_ipsecB",
                   "underlay_main",      "underlay_backup")
    else:
        L += _fvpn("underlay_internet", "underlay_ipsec",
                   "underlay_main",     "underlay_backup")

    # ── WAN 接口（绑定 internet VRF）──────────────────────────────
    ivrf1 = "underlay_internetA" if dual_wan else "underlay_internet"
    L += _fwan_blk(w1, wan1_ip, wan1_mask, ivrf1)
    if dual_wan:
        w2 = _cfg_ge(init_cfg, "wan2_if", DEFAULT_WAN2_PORT)
        wan2_ip, wan2_mask = _ip_mask_from_cidr(init_cfg.get("wan2_ip") or DEFAULT_WAN2_IP)
        wan2_gw = init_cfg.get("wan2_gw") or DEFAULT_WAN2_GW
        L += _fwan_blk(w2, wan2_ip, wan2_mask, "underlay_internetB")

    # ── 自环网关口 + 子接口 ────────────────────────────────────────
    zf_subs = [".98"] + ([".99"] if dual_wan else []) + [".100", ".200"]
    L += _fzf_ipf(zf, zf_subs)

    # ── 自环(IPSec)口 + 子接口 ────────────────────────────────────
    ipf_subs = [".98"] + ([".99"] if dual_wan else [])
    L += _fzf_ipf(ipf, ipf_subs)

    # ── Tunnel ────────────────────────────────────────────────────
    L += ["interface Tunnel0/0/1000", "", "interface Tunnel0/0/1001", ""]

    # ── 默认路由（通过 internet VRF）─────────────────────────────
    if dual_wan:
        L += [f"ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {wan1_gw}", ""]
        L += [f"ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {wan2_gw}", ""]
    else:
        L += [f"ip route-static vpn-instance underlay_internet 0.0.0.0 0.0.0.0 {wan1_gw}", ""]

    # ── AAA / SSH ─────────────────────────────────────────────────
    L += _faaa_ssh()

    # ── 尾部（FTP / ops install / agile / factory save）──────────
    ftp_vrf = ivrf1
    ops_files    = [f"{lid}.py", "ipsecmain.py", "ipsecbackup.py"]
    script_files = [f"{lid}.py", "ipsecmain.py", "ipsecbackup.py"]
    # 南向 agile 条目：双WAN 仅按各自配置生成；单WAN 主备都可生成
    if dual_wan:
        agile_entries = []
        if south_pri:
            agile_entries.append(("underlay_internetA", south_pri, wan1_gw))
        if south_bak:
            agile_entries.append(("underlay_internetB", south_bak, wan2_gw))
    else:
        agile_entries = []
        if south_pri:
            agile_entries.append((ivrf1, south_pri, wan1_gw))
        if south_bak:
            agile_entries.append((ivrf1, south_bak, wan1_gw))
    L += _f_suffix(ftp_vrf, ops_files, script_files, agile_entries, lid)

    return "\n".join(L)


def render_factory_dual_primary(init_cfg, lineid):
    """
    双机主设备 Factory 脚本。
    VRF：underlay_internetA / underlay_ipsecA / underlay_main
    """
    zf  = _cfg_ge(init_cfg, "zihuan_if1", DJ_ZIHUAN1_PORT)
    ipf = _cfg_ge(init_cfg, "ipsec_if1", DJ_IPSEC1_PORT)
    w1  = _cfg_ge(init_cfg, "wan1_if", DJ_WAN1_PORT)
    wan1_ip, wan1_mask = _ip_mask_from_cidr(init_cfg.get("wan1_ip") or DJ_WAN1_IP)
    wan1_gw   = init_cfg.get("wan1_gw") or DJ_WAN1_GW
    south_pri = init_cfg.get("south_primary")
    south_bak = init_cfg.get("south_backup")
    lid = _lineid_for_filename(lineid)

    L = []
    L += _fvpn("underlay_internetA", "underlay_ipsecA", "underlay_main")
    L += _fwan_blk(w1, wan1_ip, wan1_mask, "underlay_internetA")
    L += _fzf_ipf(zf, [".98", ".100"])
    L += _fzf_ipf(ipf, [".98"])
    L += ["interface Tunnel0/0/1000", ""]
    L += [f"ip route-static vpn-instance underlay_internetA 0.0.0.0 0.0.0.0 {wan1_gw}", ""]
    L += _faaa_ssh()

    ops_files    = [f"{lid}main.py", "ipsecmain.py"]
    script_files = [f"{lid}main.py", "ipsecmain.py"]
    # 主设备仅有 internetA；南向主用IP放 internetA
    agile_entries = []
    if south_pri:
        agile_entries.append(("underlay_internetA", south_pri, wan1_gw))
    L += _f_suffix("underlay_internetA", ops_files, script_files, agile_entries, lid)

    return "\n".join(L)


def render_factory_dual_backup(init_cfg, lineid):
    """
    双机备设备 Factory 脚本。
    VRF：underlay_internetB / underlay_ipsecB / underlay_backup
    """
    zf  = _cfg_ge(init_cfg, "zihuan_if2", DJ_ZIHUAN2_PORT)
    ipf = _cfg_ge(init_cfg, "ipsec_if2", DJ_IPSEC2_PORT)
    w2  = _cfg_ge(init_cfg, "wan2_if", DJ_WAN2_PORT)
    wan2_ip, wan2_mask = _ip_mask_from_cidr(init_cfg.get("wan2_ip") or DJ_WAN2_IP)
    wan2_gw   = init_cfg.get("wan2_gw") or DJ_WAN2_GW
    south_pri = init_cfg.get("south_primary")
    south_bak = init_cfg.get("south_backup")
    lid = _lineid_for_filename(lineid)

    L = []
    L += _fvpn("underlay_internetB", "underlay_ipsecB", "underlay_backup")
    L += _fwan_blk(w2, wan2_ip, wan2_mask, "underlay_internetB")
    L += _fzf_ipf(zf, [".99", ".200"])
    L += _fzf_ipf(ipf, [".99"])
    L += ["interface Tunnel0/0/1001", ""]
    L += [f"ip route-static vpn-instance underlay_internetB 0.0.0.0 0.0.0.0 {wan2_gw}", ""]
    L += _faaa_ssh()

    ops_files    = [f"{lid}backup.py", "ipsecbackup.py"]
    script_files = [f"{lid}backup.py", "ipsecbackup.py"]
    # 备设备仅有 internetB；仅当配置了南向备用IP时才生成该条目
    eff_south = south_bak
    agile_entries = []
    if eff_south:
        agile_entries.append(("underlay_internetB", eff_south, wan2_gw))
    L += _f_suffix("underlay_internetB", ops_files, script_files, agile_entries, lid)

    return "\n".join(L)


# =====================================================================
# 初始化默认值
# =====================================================================
DEFAULT_WAN1_PORT   = "0/0/9"
DEFAULT_WAN2_PORT   = "0/0/8"
DEFAULT_ZIHUAN_PORT = "0/0/4"
DEFAULT_IPSEC_PORT  = "0/0/5"
DEFAULT_WAN1_IP     = "192.168.1.190/24"
DEFAULT_WAN2_IP     = "192.168.2.190/24"
DEFAULT_WAN1_GW     = "192.168.1.1"
DEFAULT_WAN2_GW     = "192.168.2.1"
DEFAULT_FTP_SERVER  = "59.36.7.222"

# 可视化 / user_init：单机页签「双WAN」开关（zh_reset_init 从此读取）
ZH_DUAL_WAN_SAVED = False

# 双机专用默认（主设备/备设备各自独立的物理口）
DJ_WAN1_PORT     = "0/0/9"
DJ_ZIHUAN1_PORT  = "0/0/4"
DJ_IPSEC1_PORT   = "0/0/5"
DJ_WAN1_IP       = "192.168.1.190/24"
DJ_WAN1_GW       = "192.168.1.1"

DJ_WAN2_PORT     = "0/0/9"
DJ_ZIHUAN2_PORT  = "0/0/4"
DJ_IPSEC2_PORT   = "0/0/5"
DJ_WAN2_IP       = "192.168.2.190/24"
DJ_WAN2_GW       = "192.168.2.1"

DEFAULT_WAN1_IP_PLAIN = DEFAULT_WAN1_IP.split("/", 1)[0].strip() if DEFAULT_WAN1_IP else ""
DEFAULT_WAN2_IP_PLAIN = DEFAULT_WAN2_IP.split("/", 1)[0].strip() if DEFAULT_WAN2_IP else ""
DJ_WAN1_IP_PLAIN = DJ_WAN1_IP.split("/", 1)[0].strip() if DJ_WAN1_IP else ""
DJ_WAN2_IP_PLAIN = DJ_WAN2_IP.split("/", 1)[0].strip() if DJ_WAN2_IP else ""


# =====================================================================
# 校验函数
# =====================================================================

def validate_zihuan_init(dual_wan, wan1_ip, wan2_ip, wan1_gw, wan2_gw,
                         wan1_if, wan2_if, z_if, bak_if,
                         ph_ip1, ph_ip2, ph_gw1, ph_gw2,
                         ph_p1, ph_p2, ph_pz, ph_pi):
    errs = []
    for val, ph, name in ((wan1_ip, ph_ip1, "WAN1 IP"),):
        if val and val.strip() and val.strip() != ph:
            ok, msg = _validate_cidr(val, name)
            if not ok:
                errs.append(msg)
    if dual_wan:
        for val, ph, name in ((wan2_ip, ph_ip2, "WAN2 IP"),):
            if val and val.strip() and val.strip() != ph:
                ok, msg = _validate_cidr(val, name)
                if not ok:
                    errs.append(msg)
    for val, ph, name in ((wan1_gw, ph_gw1, "WAN1网关"),):
        if val and val.strip() and val.strip() != ph:
            ok, msg = _validate_ipv4(val, name)
            if not ok:
                errs.append(msg)
    if dual_wan:
        for val, ph, name in ((wan2_gw, ph_gw2, "WAN2网关"),):
            if val and val.strip() and val.strip() != ph:
                ok, msg = _validate_ipv4(val, name)
                if not ok:
                    errs.append(msg)
    slots = [(wan1_if, ph_p1, "WAN1 G()"), (z_if, ph_pz, "自环网关 G()"), (bak_if, ph_pi, "自环(IPSec) G()")]
    if dual_wan:
        slots.append((wan2_if, ph_p2, "WAN2 G()"))
    expanded_ports = []
    for val, ph, name in slots:
        v = (val or "").strip()
        if not v or v == ph:
            v = ph
        ok, msg = _validate_ge_slot(v, name)
        if not ok:
            errs.append(msg)
        else:
            expanded_ports.append((expand_ge_port(v), name))
    seen_ports: dict = {}
    for exp, name in expanded_ports:
        if exp in seen_ports:
            errs.append(f"物理口重复：{name} 与 {seen_ports[exp]} 均配置为 {exp}，请检查")
        else:
            seen_ports[exp] = name
    return (len(errs) == 0, errs)


def validate_duoji_init(wan1_ip, wan2_ip, wan1_gw, wan2_gw,
                        wan1_if, z1_if, bak1_if,
                        wan2_if, z2_if, bak2_if):
    """双机校验：主/备设备各自独立，分别检查各自内部端口不重复。"""
    errs = []
    for val, name in [(wan1_ip, "WAN1 IP"), (wan2_ip, "WAN2 IP")]:
        if val and val.strip():
            ok, msg = _validate_cidr(val, name)
            if not ok:
                errs.append(msg)
    for val, name in [(wan1_gw, "WAN1网关"), (wan2_gw, "WAN2网关")]:
        if val and val.strip():
            ok, msg = _validate_ipv4(val, name)
            if not ok:
                errs.append(msg)
    # 各设备内部去重（主 = WAN1 线，备 = WAN2 线）
    for device, triples in [
        ("主设备", [(wan1_if, "WAN1口"), (z1_if, "自环网关口"), (bak1_if, "自环(IPSec)口")]),
        ("备设备", [(wan2_if, "WAN2口"), (z2_if, "自环网关口"), (bak2_if, "自环(IPSec)口")]),
    ]:
        seen: dict = {}
        for val, label in triples:
            v = (val or "").strip()
            if not v:
                continue
            ok, msg = _validate_ge_slot(v, f"{device}{label}")
            if not ok:
                errs.append(msg)
            else:
                exp = expand_ge_port(v)
                if exp in seen:
                    errs.append(f"{device}口重复：{label} 与 {seen[exp]} 均为 {exp}，请检查")
                else:
                    seen[exp] = label
    return (len(errs) == 0, errs)


# =====================================================================
# GUI 主题
# =====================================================================
BG       = "#f0f4f8"
BG_PANEL = "#ffffff"
BG_INPUT = "#f8fafc"
BG_HDR   = "#1e3a5f"
ACCENT_HK = "#e07b2a"
ACCENT_US = "#0077b6"
FG       = "#1a2b3c"
FG_DIM   = "#7a96ad"
FG_BRT   = "#ffffff"
BORDER   = "#c8d8e8"
FONT_MONO = ("Consolas", 10)
FONT_UI   = ("微软雅黑", 10)
FONT_HDR  = ("微软雅黑", 11, "bold")
FONT_TINY = ("Consolas", 9)

root = tk.Tk()
root.title("AR SD-WAN 配置生成工具")
_sw = root.winfo_screenwidth()
_sh = root.winfo_screenheight()
_ww = min(1520, int(_sw * 0.94))
_wh = min(920, int(_sh * 0.90))
root.geometry(f"{_ww}x{_wh}+{(_sw-_ww)//2}+{max(0,(_sh-_wh)//2-20)}")
root.minsize(1080, 680)
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
# 默认单机橘色；tab 切换时由 _on_tab_changed 更新
sty.map("TNotebook.Tab",
        background=[("selected", BG), ("active", "#2a4a6f")],
        foreground=[("selected", ACCENT_HK), ("active", FG_BRT)])


def make_text(parent, readonly=False, accent=None, **kw):
    acc = accent or ACCENT_US
    vsb = ttk.Scrollbar(parent, orient="vertical", style="Vertical.TScrollbar")
    vsb.pack(side="right", fill="y")
    t = tk.Text(parent, font=FONT_MONO, bg=BG_INPUT, fg=FG,
                insertbackground=acc, selectbackground=acc,
                selectforeground=BG, relief="flat", bd=0, padx=10, pady=6,
                yscrollcommand=vsb.set,
                state=(tk.DISABLED if readonly else tk.NORMAL), **kw)
    t.pack(side="left", fill="both", expand=True)
    vsb.configure(command=t.yview)
    menu = tk.Menu(t, tearoff=0, bg=BG_PANEL, fg=FG,
                   activebackground=acc, activeforeground=FG_BRT,
                   font=FONT_UI, bd=0, relief="flat")
    menu.add_command(label="复制", command=lambda: t.event_generate("<<Copy>>"))
    menu.add_command(label="剪切", command=lambda: t.event_generate("<<Cut>>"))
    menu.add_command(label="粘贴", command=lambda: t.event_generate("<<Paste>>"))
    menu.add_separator()
    menu.add_command(label="全选", command=lambda: (t.tag_add("sel", "1.0", "end"), None))
    menu.add_separator()
    menu.add_command(label="撤销", command=lambda: t.event_generate("<<Undo>>"))
    menu.add_command(label="重做", command=lambda: t.event_generate("<<Redo>>"))

    def _show_menu(event):
        has_sel = bool(t.tag_ranges("sel"))
        menu.entryconfig("复制", state="normal" if has_sel else "disabled")
        menu.entryconfig("剪切", state="normal" if (has_sel and not readonly) else "disabled")
        menu.entryconfig("粘贴", state="normal" if not readonly else "disabled")
        menu.entryconfig("撤销", state="normal" if not readonly else "disabled")
        menu.entryconfig("重做", state="normal" if not readonly else "disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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
hdr.grid(row=0, column=0, sticky="ew")
hdr.grid_propagate(False)
tk.Frame(hdr, bg="#16a085", width=4).pack(side="left", fill="y")
tk.Label(hdr, text="  AR SD-WAN", font=("微软雅黑", 13, "bold"),
         bg=BG_HDR, fg=FG_BRT).pack(side="left")
tk.Label(hdr, text=" 配置生成工具", font=FONT_HDR, bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=4)
right_badges = tk.Frame(hdr, bg=BG_HDR)
right_badges.pack(side="right", padx=14, pady=10)
badge_font = ("微软雅黑", 9, "bold")
tk.Label(right_badges, text=" v4 ", font=badge_font, bg="#16a085", fg=FG_BRT,
         padx=12, pady=4).pack(side="right")
tk.Label(right_badges, text=" 深圳工程部系列宝典 ", font=badge_font, bg="#6c757d", fg=FG_BRT,
         padx=10, pady=4).pack(side="right", padx=(0, 8))

main_nb = ttk.Notebook(root)
main_nb.grid(row=1, column=0, sticky="nsew")
tab_single = tk.Frame(main_nb, bg=BG)
tab_dual   = tk.Frame(main_nb, bg=BG)
main_nb.add(tab_single, text="  单机组网  ")
main_nb.add(tab_dual,   text="  双机组网  ")


# =====================================================================
# 单机初始化面板
# =====================================================================

def build_zihuan_init_panel(parent, accent):
    BG_ACTIVE = "#c8dff0"
    BG_LOCKED = "#e8edf3"

    hdr_f = tk.Frame(parent, bg=accent, height=26)
    hdr_f.pack(fill="x"); hdr_f.pack_propagate(False)
    tk.Frame(hdr_f, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(hdr_f, text="  初始化配置", font=("微软雅黑", 10, "bold"),
             bg=accent, fg=FG_BRT).pack(side="left", pady=2)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

    body = tk.Frame(parent, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=2, pady=2)
    body.columnconfigure(0, minsize=68); body.columnconfigure(1, weight=0)
    body.columnconfigure(2, minsize=8);  body.columnconfigure(3, minsize=68)
    body.columnconfigure(4, weight=0)

    LBL  = dict(font=("微软雅黑", 9), bg=BG_PANEL, fg=FG,     anchor="e")
    DLBL = dict(font=("微软雅黑", 9), bg=BG_PANEL, fg=FG_DIM, anchor="e")
    PAD  = dict(padx=(2, 4), pady=2)

    tk.Frame(body, bg=BORDER, width=1).grid(
        row=0, column=2, rowspan=20, sticky="ns", padx=3, pady=2)

    def mk_entry(parent_f, ph, w=14, enabled=True, expand=True):
        bg = BG_ACTIVE if enabled else BG_LOCKED
        e = tk.Entry(parent_f, font=("Consolas", 9), bg=bg, fg=FG_DIM,
                     insertbackground=accent, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=accent, width=w,
                     disabledbackground=BG_LOCKED, disabledforeground=FG_DIM)
        e.pack(side="left", fill="x", expand=expand)
        e.insert(0, ph)
        if not enabled:
            e.config(state=tk.DISABLED)

        def _fi(ev, en=e, p=ph):
            if str(en.cget("state")) == "normal" and en.get() == p:
                en.delete(0, tk.END); en.config(fg=FG)

        def _fo(ev, en=e, p=ph):
            if not en.get().strip():
                en.insert(0, p); en.config(fg=FG_DIM)

        e.bind("<FocusIn>", _fi); e.bind("<FocusOut>", _fo)
        return e

    def ge_frame(parent_f, ph, w=10, enabled=True):
        tk.Label(parent_f, text="G(", font=("Consolas", 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(side="left")
        e = mk_entry(parent_f, ph, w=w, enabled=enabled)
        tk.Label(parent_f, text=")", font=("Consolas", 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(side="left", padx=(0, 2))
        return e

    r = 0
    # WAN模式
    tk.Label(body, text="WAN模式", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    mode_fr = tk.Frame(body, bg=BG_PANEL)
    mode_fr.grid(row=r, column=1, columnspan=4, sticky="w", padx=(0, 4), pady=2)
    dual_wan_var = tk.BooleanVar(value=False)
    tk.Radiobutton(mode_fr, text="单WAN（仅 WAN1）", variable=dual_wan_var, value=False,
                   bg=BG_PANEL, fg=FG, font=("微软雅黑", 9),
                   command=lambda: _toggle_wan2()).pack(side="left", padx=(0, 14))
    tk.Radiobutton(mode_fr, text="双WAN（开启 WAN2）", variable=dual_wan_var, value=True,
                   bg=BG_PANEL, fg=FG, font=("微软雅黑", 9),
                   command=lambda: _toggle_wan2()).pack(side="left")
    r += 1

    tk.Label(body, text="WAN1", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_w1if = tk.Frame(body, bg=BG_PANEL)
    fr_w1if.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_wan1_if = ge_frame(fr_w1if, DEFAULT_WAN1_PORT, w=10, enabled=True)
    lbl_w2_port = tk.Label(body, text="WAN2", **DLBL)
    lbl_w2_port.grid(row=r, column=3, sticky="e", **PAD)
    fr_w2if = tk.Frame(body, bg=BG_PANEL)
    fr_w2if.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_wan2_if = ge_frame(fr_w2if, DEFAULT_WAN2_PORT, w=10, enabled=False)
    r += 1

    tk.Label(body, text="WAN1 IP", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_w1ip = tk.Frame(body, bg=BG_PANEL)
    fr_w1ip.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_wan1_ip = mk_entry(fr_w1ip, DEFAULT_WAN1_IP, w=18, enabled=True, expand=False)
    lbl_w2_ip = tk.Label(body, text="WAN2 IP", **DLBL)
    lbl_w2_ip.grid(row=r, column=3, sticky="e", **PAD)
    fr_w2ip = tk.Frame(body, bg=BG_PANEL)
    fr_w2ip.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_wan2_ip = mk_entry(fr_w2ip, DEFAULT_WAN2_IP, w=18, enabled=False, expand=False)
    r += 1

    tk.Label(body, text="WAN1网关", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_w1gw = tk.Frame(body, bg=BG_PANEL)
    fr_w1gw.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_wan1_gw = mk_entry(fr_w1gw, DEFAULT_WAN1_GW, w=14, enabled=True, expand=False)
    lbl_w2_gw = tk.Label(body, text="WAN2网关", **DLBL)
    lbl_w2_gw.grid(row=r, column=3, sticky="e", **PAD)
    fr_w2gw = tk.Frame(body, bg=BG_PANEL)
    fr_w2gw.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_wan2_gw = mk_entry(fr_w2gw, DEFAULT_WAN2_GW, w=14, enabled=False, expand=False)
    r += 1

    sty.configure("Init.TCombobox", fieldbackground=BG_ACTIVE,
                  selectbackground=accent, selectforeground=FG_BRT)
    tk.Label(body, text="南向服务", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_s = tk.Frame(body, bg=BG_PANEL)
    fr_s.grid(row=r, column=1, columnspan=4, sticky="w", padx=(0, 4), pady=2)
    cb_south = ttk.Combobox(fr_s, values=SOUTH_LABELS_DISPLAY,
                             state="readonly", style="Init.TCombobox",
                             font=("微软雅黑", 9), width=40)
    cb_south.pack(side="left", fill="x", expand=True)
    cb_south.set(SOUTH_LABELS_DISPLAY[0])
    r += 1

    # ── IKE 版本 ─────────────────────────────────────────────────────
    tk.Label(body, text="IKE版本", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    ike_fr = tk.Frame(body, bg=BG_PANEL)
    ike_fr.grid(row=r, column=1, columnspan=4, sticky="w", padx=(0, 4), pady=2)
    ike_ver_var = tk.StringVar(value="v1")
    tk.Radiobutton(ike_fr, text="IKEv1", variable=ike_ver_var, value="v1",
                   bg=BG_PANEL, fg=FG, font=("微软雅黑", 9)).pack(side="left", padx=(0, 12))
    tk.Radiobutton(ike_fr, text="IKEv2", variable=ike_ver_var, value="v2",
                   bg=BG_PANEL, fg=FG, font=("微软雅黑", 9)).pack(side="left")
    r += 1

    tk.Frame(body, bg=BORDER, height=1).grid(
        row=r, column=0, columnspan=5, sticky="ew", pady=(3, 1))
    r += 1

    tk.Label(body, text="自环网关", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_z = tk.Frame(body, bg=BG_PANEL)
    fr_z.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_zihuan_if = ge_frame(fr_z, DEFAULT_ZIHUAN_PORT, w=10, enabled=True)
    tk.Label(body, text="自环(IPSec)", **LBL).grid(row=r, column=3, sticky="e", **PAD)
    fr_i = tk.Frame(body, bg=BG_PANEL)
    fr_i.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_ipsec_if = ge_frame(fr_i, DEFAULT_IPSEC_PORT, w=10, enabled=True)
    r += 1

    tk.Label(body, text="物理口仅填槽位号；南向仅写静态路由（无 environment）。",
             font=("微软雅黑", 8), bg=BG_PANEL, fg=FG_DIM, anchor="w",
             ).grid(row=r, column=0, columnspan=5, sticky="w", padx=(4, 4), pady=(0, 2))
    r += 1

    wan2_labels  = (lbl_w2_port, lbl_w2_ip, lbl_w2_gw)
    wan2_entries = (
        (e_wan2_if, DEFAULT_WAN2_PORT),
        (e_wan2_ip, DEFAULT_WAN2_IP),
        (e_wan2_gw, DEFAULT_WAN2_GW),
    )

    def _toggle_wan2():
        on = dual_wan_var.get()
        for lb in wan2_labels:
            lb.config(fg=FG if on else FG_DIM)
        for en, ph in wan2_entries:
            if on:
                en.config(state=tk.NORMAL, bg=BG_ACTIVE)
                if not en.get().strip():
                    en.insert(0, ph)
                en.config(fg=FG)
            else:
                en.config(state=tk.DISABLED, bg=BG_LOCKED,
                          disabledbackground=BG_LOCKED, disabledforeground=FG_DIM)

    def _pv(entry, placeholder):
        v = entry.get().strip()
        return "" if v == placeholder else v

    def get_raw_for_validate():
        return (
            dual_wan_var.get(),
            e_wan1_ip.get().strip(), e_wan2_ip.get().strip(),
            e_wan1_gw.get().strip(), e_wan2_gw.get().strip(),
            e_wan1_if.get().strip(), e_wan2_if.get().strip(),
            e_zihuan_if.get().strip(), e_ipsec_if.get().strip(),
        )

    def get_init_cfg():
        sel = cb_south.get() or SOUTH_LABELS_DISPLAY[0]
        pri, bak = _south_ips_by_label(sel)
        if not pri:
            pri, bak = None, None
        return {
            "dual_wan": dual_wan_var.get(),
            "ike_version": ike_ver_var.get(),
            "wan1_if":   expand_ge_port(_pv(e_wan1_if,  DEFAULT_WAN1_PORT)  or DEFAULT_WAN1_PORT),
            "wan2_if":   expand_ge_port(_pv(e_wan2_if,  DEFAULT_WAN2_PORT)  or DEFAULT_WAN2_PORT),
            "zihuan_if": expand_ge_port(_pv(e_zihuan_if, DEFAULT_ZIHUAN_PORT) or DEFAULT_ZIHUAN_PORT),
            "ipsec_if":  expand_ge_port(_pv(e_ipsec_if, DEFAULT_IPSEC_PORT) or DEFAULT_IPSEC_PORT),
            "wan1_ip":   _pv(e_wan1_ip, DEFAULT_WAN1_IP) or DEFAULT_WAN1_IP,
            "wan2_ip":   _pv(e_wan2_ip, DEFAULT_WAN2_IP) or DEFAULT_WAN2_IP,
            "wan1_gw":   _pv(e_wan1_gw, DEFAULT_WAN1_GW) or DEFAULT_WAN1_GW,
            "wan2_gw":   _pv(e_wan2_gw, DEFAULT_WAN2_GW) or DEFAULT_WAN2_GW,
            "south_primary": pri, "south_backup": bak,
        }

    def reset_init():
        dual_wan_var.set(bool(ZH_DUAL_WAN_SAVED))
        _iv = ZH_IKE_VERSION_SAVED if ZH_IKE_VERSION_SAVED in ("v1", "v2") else "v1"
        ike_ver_var.set(_iv)
        for en, ph in wan2_entries:
            en.config(state=tk.NORMAL)
        for e, ph in [
            (e_wan1_if, DEFAULT_WAN1_PORT), (e_wan2_if, DEFAULT_WAN2_PORT),
            (e_wan1_ip, DEFAULT_WAN1_IP),   (e_wan2_ip, DEFAULT_WAN2_IP),
            (e_wan1_gw, DEFAULT_WAN1_GW),   (e_wan2_gw, DEFAULT_WAN2_GW),
            (e_zihuan_if, DEFAULT_ZIHUAN_PORT), (e_ipsec_if, DEFAULT_IPSEC_PORT),
        ]:
            e.delete(0, tk.END); e.insert(0, ph); e.config(fg=FG_DIM)
        _toggle_wan2()
        _sl = ZH_SOUTH_LABEL_SAVED if ZH_SOUTH_LABEL_SAVED in SOUTH_LABELS_DISPLAY else SOUTH_LABELS_DISPLAY[0]
        cb_south.set(_sl)

    _toggle_wan2()
    global _FORMAL_IKE_VAR_ZH
    _FORMAL_IKE_VAR_ZH = ike_ver_var
    return get_init_cfg, reset_init, get_raw_for_validate


# =====================================================================
# 双机初始化面板（主/备设备各自独立的全套口）
# =====================================================================

def build_duoji_init_panel(parent, accent):
    BG_ACTIVE = "#c8dff0"

    hdr_f = tk.Frame(parent, bg=accent, height=26)
    hdr_f.pack(fill="x"); hdr_f.pack_propagate(False)
    tk.Frame(hdr_f, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(hdr_f, text="  初始化配置（双机）", font=("微软雅黑", 10, "bold"),
             bg=accent, fg=FG_BRT).pack(side="left", pady=2)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

    body = tk.Frame(parent, bg=BG_PANEL)
    body.pack(fill="both", expand=True, padx=2, pady=2)
    # 5列: 0=主设备标签  1=主设备值  2=竖线  3=备设备标签  4=备设备值
    body.columnconfigure(0, minsize=72); body.columnconfigure(1, weight=0)
    body.columnconfigure(2, minsize=8);   body.columnconfigure(3, minsize=72)
    body.columnconfigure(4, weight=0)

    LBL = dict(font=("微软雅黑", 9), bg=BG_PANEL, fg=FG, anchor="e")
    PAD = dict(padx=(2, 4), pady=2)

    # 竖向分割线
    tk.Frame(body, bg=BORDER, width=1).grid(
        row=0, column=2, rowspan=20, sticky="ns", padx=3, pady=2)

    def mk_entry(parent_f, ph, w=14, expand=True):
        e = tk.Entry(parent_f, font=("Consolas", 9), bg=BG_ACTIVE, fg=FG_DIM,
                     insertbackground=accent, relief="flat", bd=0,
                     highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=accent, width=w)
        e.pack(side="left", fill="x", expand=expand)
        e.insert(0, ph)

        def _fi(ev, en=e, p=ph):
            if en.get() == p:
                en.delete(0, tk.END); en.config(fg=FG)

        def _fo(ev, en=e, p=ph):
            if not en.get().strip():
                en.insert(0, p); en.config(fg=FG_DIM)

        e.bind("<FocusIn>", _fi); e.bind("<FocusOut>", _fo)
        return e

    def ge_frame(parent_f, ph, w=10):
        tk.Label(parent_f, text="G(", font=("Consolas", 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(side="left")
        e = mk_entry(parent_f, ph, w=w)
        tk.Label(parent_f, text=")", font=("Consolas", 9),
                 bg=BG_PANEL, fg=FG_DIM).pack(side="left", padx=(0, 2))
        return e

    r = 0
    # ── 列标题 ───────────────────────────────────────────────────────
    tk.Label(body, text="【主设备】", font=("微软雅黑", 9, "bold"),
             bg=BG_PANEL, fg=accent, anchor="w").grid(
        row=r, column=0, columnspan=2, sticky="w", padx=(4, 4), pady=(2, 0))
    tk.Label(body, text="【备设备】", font=("微软雅黑", 9, "bold"),
             bg=BG_PANEL, fg=accent, anchor="w").grid(
        row=r, column=3, columnspan=2, sticky="w", padx=(4, 4), pady=(2, 0))
    r += 1

    # ── 主设备 = WAN1，备设备 = WAN2（与可视化初始化标签一致）────────────────
    tk.Label(body, text="WAN1", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_w1if = tk.Frame(body, bg=BG_PANEL)
    fr_w1if.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_wan1_if = ge_frame(fr_w1if, DJ_WAN1_PORT, w=10)
    tk.Label(body, text="WAN2", **LBL).grid(row=r, column=3, sticky="e", **PAD)
    fr_w2if = tk.Frame(body, bg=BG_PANEL)
    fr_w2if.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_wan2_if = ge_frame(fr_w2if, DJ_WAN2_PORT, w=10)
    r += 1

    tk.Label(body, text="WAN1 IP", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_w1ip = tk.Frame(body, bg=BG_PANEL)
    fr_w1ip.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_wan1_ip = mk_entry(fr_w1ip, DJ_WAN1_IP, w=18, expand=False)
    tk.Label(body, text="WAN2 IP", **LBL).grid(row=r, column=3, sticky="e", **PAD)
    fr_w2ip = tk.Frame(body, bg=BG_PANEL)
    fr_w2ip.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_wan2_ip = mk_entry(fr_w2ip, DJ_WAN2_IP, w=18, expand=False)
    r += 1

    tk.Label(body, text="WAN1网关", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_w1gw = tk.Frame(body, bg=BG_PANEL)
    fr_w1gw.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_wan1_gw = mk_entry(fr_w1gw, DJ_WAN1_GW, w=14, expand=False)
    tk.Label(body, text="WAN2网关", **LBL).grid(row=r, column=3, sticky="e", **PAD)
    fr_w2gw = tk.Frame(body, bg=BG_PANEL)
    fr_w2gw.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_wan2_gw = mk_entry(fr_w2gw, DJ_WAN2_GW, w=14, expand=False)
    r += 1

    # ── 自环网关口 ───────────────────────────────────────────────────
    tk.Label(body, text="自环网关", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_z1 = tk.Frame(body, bg=BG_PANEL)
    fr_z1.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_zihuan1_if = ge_frame(fr_z1, DJ_ZIHUAN1_PORT, w=10)
    tk.Label(body, text="自环网关", **LBL).grid(row=r, column=3, sticky="e", **PAD)
    fr_z2 = tk.Frame(body, bg=BG_PANEL)
    fr_z2.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_zihuan2_if = ge_frame(fr_z2, DJ_ZIHUAN2_PORT, w=10)
    r += 1

    # ── 自环(IPSec)口 ────────────────────────────────────────────────
    tk.Label(body, text="自环(IPSec)", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_i1 = tk.Frame(body, bg=BG_PANEL)
    fr_i1.grid(row=r, column=1, sticky="w", padx=(0, 4), pady=2)
    e_ipsec1_if = ge_frame(fr_i1, DJ_IPSEC1_PORT, w=10)
    tk.Label(body, text="自环(IPSec)", **LBL).grid(row=r, column=3, sticky="e", **PAD)
    fr_i2 = tk.Frame(body, bg=BG_PANEL)
    fr_i2.grid(row=r, column=4, sticky="w", padx=(0, 4), pady=2)
    e_ipsec2_if = ge_frame(fr_i2, DJ_IPSEC2_PORT, w=10)
    r += 1

    # ── 南向服务（共用）──────────────────────────────────────────────
    tk.Frame(body, bg=BORDER, height=1).grid(
        row=r, column=0, columnspan=5, sticky="ew", pady=(3, 1))
    r += 1
    sty.configure("InitDJ.TCombobox", fieldbackground=BG_ACTIVE,
                  selectbackground=accent, selectforeground=FG_BRT)
    tk.Label(body, text="南向服务", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    fr_s = tk.Frame(body, bg=BG_PANEL)
    fr_s.grid(row=r, column=1, columnspan=4, sticky="w", padx=(0, 4), pady=2)
    cb_south = ttk.Combobox(fr_s, values=SOUTH_LABELS_DISPLAY,
                             state="readonly", style="InitDJ.TCombobox",
                             font=("微软雅黑", 9), width=40)
    cb_south.pack(side="left", fill="x", expand=True)
    cb_south.set(SOUTH_LABELS_DISPLAY[0])
    r += 1

    # ── IKE 版本 ─────────────────────────────────────────────────────
    tk.Label(body, text="IKE版本", **LBL).grid(row=r, column=0, sticky="e", **PAD)
    ike_fr_dj = tk.Frame(body, bg=BG_PANEL)
    ike_fr_dj.grid(row=r, column=1, columnspan=4, sticky="w", padx=(0, 4), pady=2)
    ike_ver_var = tk.StringVar(value="v1")
    tk.Radiobutton(ike_fr_dj, text="IKEv1", variable=ike_ver_var, value="v1",
                   bg=BG_PANEL, fg=FG, font=("微软雅黑", 9)).pack(side="left", padx=(0, 12))
    tk.Radiobutton(ike_fr_dj, text="IKEv2", variable=ike_ver_var, value="v2",
                   bg=BG_PANEL, fg=FG, font=("微软雅黑", 9)).pack(side="left")
    r += 1

    tk.Label(body,
             text="主/备设备各自独立配置；两台设备口号可以相同（不同物理机）。",
             font=("微软雅黑", 8), bg=BG_PANEL, fg=FG_DIM, anchor="w",
             ).grid(row=r, column=0, columnspan=5, sticky="w", padx=(4, 4), pady=(0, 2))

    def _pv(entry, placeholder):
        v = entry.get().strip()
        return "" if v == placeholder else v

    def get_raw_for_validate():
        return (
            e_wan1_ip.get().strip(), e_wan2_ip.get().strip(),
            e_wan1_gw.get().strip(), e_wan2_gw.get().strip(),
            e_wan1_if.get().strip(), e_zihuan1_if.get().strip(), e_ipsec1_if.get().strip(),
            e_wan2_if.get().strip(), e_zihuan2_if.get().strip(), e_ipsec2_if.get().strip(),
        )

    def get_init_cfg():
        sel = cb_south.get() or SOUTH_LABELS_DISPLAY[0]
        pri, bak = _south_ips_by_label(sel)
        if not pri:
            pri, bak = None, None
        return {
            "ike_version": ike_ver_var.get(),
            "wan1_if":    expand_ge_port(_pv(e_wan1_if,    DJ_WAN1_PORT)    or DJ_WAN1_PORT),
            "zihuan_if1": expand_ge_port(_pv(e_zihuan1_if, DJ_ZIHUAN1_PORT) or DJ_ZIHUAN1_PORT),
            "ipsec_if1":  expand_ge_port(_pv(e_ipsec1_if,  DJ_IPSEC1_PORT)  or DJ_IPSEC1_PORT),
            "wan1_ip":    _pv(e_wan1_ip,  DJ_WAN1_IP)  or DJ_WAN1_IP,
            "wan1_gw":    _pv(e_wan1_gw,  DJ_WAN1_GW)  or DJ_WAN1_GW,
            "wan2_if":    expand_ge_port(_pv(e_wan2_if,    DJ_WAN2_PORT)    or DJ_WAN2_PORT),
            "zihuan_if2": expand_ge_port(_pv(e_zihuan2_if, DJ_ZIHUAN2_PORT) or DJ_ZIHUAN2_PORT),
            "ipsec_if2":  expand_ge_port(_pv(e_ipsec2_if,  DJ_IPSEC2_PORT)  or DJ_IPSEC2_PORT),
            "wan2_ip":    _pv(e_wan2_ip,  DJ_WAN2_IP)  or DJ_WAN2_IP,
            "wan2_gw":    _pv(e_wan2_gw,  DJ_WAN2_GW)  or DJ_WAN2_GW,
            "south_primary": pri, "south_backup": bak,
        }

    def reset_init():
        _iv = DJ_IKE_VERSION_SAVED if DJ_IKE_VERSION_SAVED in ("v1", "v2") else "v1"
        ike_ver_var.set(_iv)
        for e, ph in [
            (e_wan1_if,    DJ_WAN1_PORT),   (e_wan1_ip,  DJ_WAN1_IP),
            (e_wan1_gw,    DJ_WAN1_GW),     (e_zihuan1_if, DJ_ZIHUAN1_PORT),
            (e_ipsec1_if,  DJ_IPSEC1_PORT),
            (e_wan2_if,    DJ_WAN2_PORT),   (e_wan2_ip,  DJ_WAN2_IP),
            (e_wan2_gw,    DJ_WAN2_GW),     (e_zihuan2_if, DJ_ZIHUAN2_PORT),
            (e_ipsec2_if,  DJ_IPSEC2_PORT),
        ]:
            e.delete(0, tk.END); e.insert(0, ph); e.config(fg=FG_DIM)
        _sl = DJ_SOUTH_LABEL_SAVED if DJ_SOUTH_LABEL_SAVED in SOUTH_LABELS_DISPLAY else SOUTH_LABELS_DISPLAY[0]
        cb_south.set(_sl)

    global _FORMAL_IKE_VAR_DJ
    _FORMAL_IKE_VAR_DJ = ike_ver_var
    return get_init_cfg, reset_init, get_raw_for_validate


# =====================================================================
# 单机 Tab 框架构建器（4列：备注/初始化 | 数据输入 | OPS脚本 | Factory脚本）
# =====================================================================

def _make_notes_panel(parent_pane, note_text, example_text, weight=2):
    """备注 + 示例 Notebook，添加到 parent_pane。"""
    notes_f = tk.Frame(parent_pane, bg=BG_PANEL,
                       highlightbackground=BORDER, highlightthickness=1)
    parent_pane.add(notes_f, weight=weight)
    notes_f.rowconfigure(0, weight=1); notes_f.columnconfigure(0, weight=1)
    nb = ttk.Notebook(notes_f)
    nb.grid(row=0, column=0, sticky="nsew")
    tn = tk.Frame(nb, bg=BG_PANEL); nb.add(tn, text="  备注说明  ")
    nt = tk.Text(tn, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat", bd=0, padx=10, pady=4)
    nt.pack(fill="both", expand=True)
    nt.insert(tk.END, note_text); nt.config(state="disabled")
    te = tk.Frame(nb, bg=BG_PANEL); nb.add(te, text="  填写示例  ")
    ew = tk.Frame(te, bg=BG_PANEL); ew.pack(fill="both", expand=True)
    evsb = ttk.Scrollbar(ew, orient="vertical", style="Vertical.TScrollbar")
    evsb.pack(side="right", fill="y")
    et = tk.Text(ew, font=FONT_MONO, bg=BG_PANEL, fg=FG, relief="flat",
                 bd=0, padx=10, pady=4, yscrollcommand=evsb.set)
    et.pack(side="left", fill="both", expand=True)
    evsb.config(command=et.yview)
    et.insert(tk.END, example_text); et.config(state="disabled")
    return notes_f


def _make_col_panel(parent_pane, label_text, accent, weight=1, sub_label_color=None):
    """带标题栏的面板，添加到 parent_pane，返回 inner Frame。"""
    f = tk.Frame(parent_pane, bg=BG_PANEL,
                 highlightbackground=BORDER, highlightthickness=1)
    parent_pane.add(f, weight=weight)
    f.rowconfigure(1, weight=1); f.columnconfigure(0, weight=1)
    bar_bg = sub_label_color if sub_label_color else accent
    h = tk.Frame(f, bg=bar_bg, height=26)
    h.grid(row=0, column=0, sticky="ew"); h.grid_propagate(False)
    tk.Frame(h, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(h, text=f"  {label_text}", font=FONT_HDR, bg=bar_bg, fg=FG_BRT, pady=2).pack(side="left")
    inner = tk.Frame(f, bg=BG_INPUT)
    inner.grid(row=1, column=0, sticky="nsew")
    return inner


def build_tab_shell(tab, accent, note_text, example_text, init_parent):
    """
    4列布局：
      Col1（竖分）: 上=备注说明  下=初始化面板
      Col2: 数据头输入
      Col3+4（配置生成区）: OPS脚本 | Factory脚本
    """
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(0, weight=1)

    # ── 顶层水平 PanedWindow ─────────────────────────────────────────
    h_pane = ttk.PanedWindow(tab, orient="horizontal")
    h_pane.grid(row=0, column=0, sticky="nsew", padx=8, pady=(6, 0))

    # ── Col1：竖向拆分（备注 上 / 初始化 下）──────────────────────
    col1_vp = ttk.PanedWindow(h_pane, orient="vertical")
    h_pane.add(col1_vp, weight=2)

    _make_notes_panel(col1_vp, note_text, example_text, weight=1)

    init_f = tk.Frame(col1_vp, bg=BG_PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
    col1_vp.add(init_f, weight=2)
    init_parent[0] = init_f

    # ── Col2：数据头输入 ──────────────────────────────────────────
    data_inner = _make_col_panel(h_pane, "数据头输入", accent, weight=1)
    left_text = make_text(data_inner, accent=accent)

    # ── Col3：配置生成区（OPS / Factory 两页切换，各占满）────────────
    cfg_outer = tk.Frame(h_pane, bg=BG_PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
    h_pane.add(cfg_outer, weight=5)
    cfg_outer.rowconfigure(1, weight=1); cfg_outer.columnconfigure(0, weight=1)

    cfg_hdr = tk.Frame(cfg_outer, bg=accent, height=28)
    cfg_hdr.grid(row=0, column=0, sticky="ew"); cfg_hdr.grid_propagate(False)
    tk.Frame(cfg_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(cfg_hdr, text="  配置生成", font=FONT_HDR, bg=accent, fg=FG_BRT, pady=2).pack(side="left")

    sty.configure("CfgOutZH.TNotebook", tabposition="nw", background=BG_PANEL)
    sty.configure("CfgOutZH.TNotebook.Tab",
                  background=BG_PANEL, foreground=FG_DIM,
                  font=("微软雅黑", 10, "bold"), padding=[16, 6])
    sty.map("CfgOutZH.TNotebook.Tab",
            background=[("selected", accent), ("active", BG_PANEL)],
            foreground=[("selected", FG_BRT), ("active", accent)])

    cfg_nb = ttk.Notebook(cfg_outer, style="CfgOutZH.TNotebook")
    cfg_nb.grid(row=1, column=0, sticky="nsew")

    f_ops = tk.Frame(cfg_nb, bg=BG_INPUT)
    cfg_nb.add(f_ops, text="  OPS 脚本  ")
    f_ops.rowconfigure(0, weight=1); f_ops.columnconfigure(0, weight=1)
    py_output = make_text(f_ops, readonly=False, accent=accent)

    f_fact = tk.Frame(cfg_nb, bg=BG_INPUT)
    cfg_nb.add(f_fact, text="  Factory 脚本  ")
    f_fact.rowconfigure(0, weight=1); f_fact.columnconfigure(0, weight=1)
    factory_output = make_text(f_fact, readonly=False, accent=accent)

    # ── 底部状态栏 ──────────────────────────────────────────────────
    def _init_col1_sash(vp=col1_vp):
        try:
            total = vp.winfo_height()
            if total > 80:
                vp.sashpos(0, int(total * 0.35))
        except Exception:
            pass

    def _init_hsash(hp=h_pane):
        try:
            W = hp.winfo_width()
            if W > 300:
                hp.sashpos(0, int(W * 0.32))
                hp.sashpos(1, int(W * 0.50))
        except Exception:
            pass

    tab.after(150, _init_col1_sash); tab.after(150, _init_hsash)
    tab.after(500, _init_col1_sash); tab.after(500, _init_hsash)
    tab.after(1200, _init_col1_sash); tab.after(1200, _init_hsash)

    tk.Frame(tab, bg=BORDER, height=1).grid(row=1, column=0, sticky="ew")
    btm = tk.Frame(tab, bg=BG_HDR, height=44)
    btm.grid(row=2, column=0, sticky="ew"); btm.grid_propagate(False)
    tab.rowconfigure(1, weight=0); tab.rowconfigure(2, weight=0)
    status_var = tk.StringVar(value="就绪  ·  等待输入业务数据")
    tk.Label(btm, textvariable=status_var, font=FONT_TINY,
             bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=12)
    btn_exp = flat_btn(btm, "导出 TXT", "#16a085")
    btn_exp.pack(side="right", padx=(0, 12), pady=7)
    btn_gen = flat_btn(btm, "⚡  生成配置", accent)
    btn_gen.pack(side="right", padx=(0, 5), pady=7)
    btn_rst = flat_btn(btm, "↺  恢复初始", "#6c757d")
    btn_rst.pack(side="right", padx=(0, 5), pady=7)

    def _sync_layout():
        _init_col1_sash()
        _init_hsash()

    return (
        left_text,
        py_output,
        factory_output,
        status_var,
        btn_gen,
        btn_exp,
        btn_rst,
        _sync_layout,
    )


# =====================================================================
# 双机 Tab 框架构建器（4列；配置生成区含主/备设备标签切换）
# =====================================================================

def build_dual_tab_shell(tab, accent, note_text, example_text, init_parent):
    """
    4列布局：
      Col1（竖分）: 上=备注说明  下=初始化面板
      Col2: 数据头输入
      Col3+4（配置生成区）: Notebook 切换 主设备/备设备
                            每设备内部：OPS脚本 | Factory脚本
    """
    tab.columnconfigure(0, weight=1)
    tab.rowconfigure(0, weight=1)

    h_pane = ttk.PanedWindow(tab, orient="horizontal")
    h_pane.grid(row=0, column=0, sticky="nsew", padx=8, pady=(6, 0))

    # ── Col1：竖向拆分（与单机完全一致）────────────────────────────
    col1_vp = ttk.PanedWindow(h_pane, orient="vertical")
    h_pane.add(col1_vp, weight=2)

    _make_notes_panel(col1_vp, note_text, example_text, weight=1)

    init_f = tk.Frame(col1_vp, bg=BG_PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
    col1_vp.add(init_f, weight=2)
    init_parent[0] = init_f

    # ── Col2：数据头输入 ──────────────────────────────────────────
    data_inner = _make_col_panel(h_pane, "数据头输入", accent, weight=1)
    left_text = make_text(data_inner, accent=accent)

    # ── Col3+4：配置生成区（共享标题栏 + 设备 Notebook）───────────
    cfg_outer = tk.Frame(h_pane, bg=BG_PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
    h_pane.add(cfg_outer, weight=5)
    cfg_outer.rowconfigure(1, weight=1); cfg_outer.columnconfigure(0, weight=1)

    cfg_hdr = tk.Frame(cfg_outer, bg=accent, height=28)
    cfg_hdr.grid(row=0, column=0, sticky="ew"); cfg_hdr.grid_propagate(False)
    tk.Frame(cfg_hdr, bg=FG_BRT, width=3).pack(side="left", fill="y")
    tk.Label(cfg_hdr, text="  配置生成", font=FONT_HDR, bg=accent, fg=FG_BRT, pady=2).pack(side="left")

    # 设备 Notebook（主设备 / 备设备 标签）
    sty.configure("Device.TNotebook", tabposition="nw", background=BG_PANEL)
    sty.configure("Device.TNotebook.Tab",
                  background=BG_PANEL, foreground=FG_DIM,
                  font=("微软雅黑", 10, "bold"), padding=[14, 5])
    sty.map("Device.TNotebook.Tab",
            background=[("selected", accent), ("active", BG_PANEL)],
            foreground=[("selected", FG_BRT), ("active", accent)])

    sty.configure("CfgOutDJ.TNotebook", tabposition="nw", background=BG_PANEL)
    sty.configure("CfgOutDJ.TNotebook.Tab",
                  background=BG_PANEL, foreground=FG_DIM,
                  font=("微软雅黑", 10, "bold"), padding=[16, 6])
    sty.map("CfgOutDJ.TNotebook.Tab",
            background=[("selected", accent), ("active", BG_PANEL)],
            foreground=[("selected", FG_BRT), ("active", accent)])

    device_nb = ttk.Notebook(cfg_outer, style="Device.TNotebook")
    device_nb.grid(row=1, column=0, sticky="nsew")

    def make_device_tab(tab_label):
        tab_f = tk.Frame(device_nb, bg=BG_INPUT)
        device_nb.add(tab_f, text=f"  {tab_label}  ")
        tab_f.rowconfigure(0, weight=1); tab_f.columnconfigure(0, weight=1)

        inner_nb = ttk.Notebook(tab_f, style="CfgOutDJ.TNotebook")
        inner_nb.grid(row=0, column=0, sticky="nsew")

        f_ops = tk.Frame(inner_nb, bg=BG_INPUT)
        inner_nb.add(f_ops, text="  OPS 脚本  ")
        f_ops.rowconfigure(0, weight=1); f_ops.columnconfigure(0, weight=1)
        py_out = make_text(f_ops, readonly=False, accent=accent)

        f_fact = tk.Frame(inner_nb, bg=BG_INPUT)
        inner_nb.add(f_fact, text="  Factory 脚本  ")
        f_fact.rowconfigure(0, weight=1); f_fact.columnconfigure(0, weight=1)
        fact_out = make_text(f_fact, readonly=False, accent=accent)
        return py_out, fact_out

    py_pri,  fact_pri  = make_device_tab("主设备")
    py_bak,  fact_bak  = make_device_tab("备设备")

    # ── 底部状态栏（与单机一致：sash 0.35 + 水平 sash）────────────────
    def _init_col1_sash(vp=col1_vp):
        try:
            total = vp.winfo_height()
            if total > 80:
                vp.sashpos(0, int(total * 0.35))
        except Exception:
            pass

    def _init_hsash(hp=h_pane):
        try:
            W = hp.winfo_width()
            if W > 300:
                hp.sashpos(0, int(W * 0.32))
                hp.sashpos(1, int(W * 0.50))
        except Exception:
            pass

    tab.after(150, _init_col1_sash); tab.after(150, _init_hsash)
    tab.after(500, _init_col1_sash); tab.after(500, _init_hsash)
    tab.after(1200, _init_col1_sash); tab.after(1200, _init_hsash)

    tk.Frame(tab, bg=BORDER, height=1).grid(row=1, column=0, sticky="ew")
    btm = tk.Frame(tab, bg=BG_HDR, height=44)
    btm.grid(row=2, column=0, sticky="ew"); btm.grid_propagate(False)
    tab.rowconfigure(1, weight=0); tab.rowconfigure(2, weight=0)
    status_var = tk.StringVar(value="就绪  ·  等待输入业务数据")
    tk.Label(btm, textvariable=status_var, font=FONT_TINY,
             bg=BG_HDR, fg="#7aafd4").pack(side="left", padx=12)
    btn_exp = flat_btn(btm, "导出 TXT", "#16a085")
    btn_exp.pack(side="right", padx=(0, 12), pady=7)
    btn_gen = flat_btn(btm, "⚡  生成配置", accent)
    btn_gen.pack(side="right", padx=(0, 5), pady=7)
    btn_rst = flat_btn(btm, "↺  恢复初始", "#6c757d")
    btn_rst.pack(side="right", padx=(0, 5), pady=7)

    def _sync_layout():
        _init_col1_sash(); _init_hsash()

    return left_text, py_pri, fact_pri, py_bak, fact_bak, status_var, btn_gen, btn_exp, btn_rst, _sync_layout


# =====================================================================
# Tab 单机组网
# =====================================================================
ZH_NOTE = (
    "• 自己确认 IKE IPsec 参数！！！\n"
    "• 只有OPS脚本会被导出为txt，命名为lineid.py\n"

    "• 南向服务可选。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)
ZH_EXAMPLE = (
    "LineID:604604Hw1\n"
    "PE:gzd-upe5\n"
    "Tunnel:Tunnel0/0/1147\n"
    "wanip:10.40.232.248/30\n"
    "PE 对接:10.200.200.76\n"
    "CE 对接:10.50.131.16\n"
    "PE AS号:65176\n"
    "客户内网路由:100.62.5.8/30\n\n"
    "拨号PE:gzd-upe5\n"
    "对接IP:10.200.200.76\n"
    "LoopIP:10.50.131.16\n"
    "拨号ip:183.63.68.174\n"
    "秘钥:both-win\n\n"
    "LineID:604604Hw2\n"
    "PE:szd-upebk1\n"
    "Tunnel:Tunnel0/0/1605\n"
    "wanip:10.30.115.252/30\n"
    "PE 对接:10.200.200.22\n"
    "CE 对接:10.120.47.20\n"
    "PE AS号:65144\n"
    "客户内网路由:100.62.5.12/30\n\n"
    "拨号PE:szd-upebk1\n"
    "对接IP:10.200.200.22\n"
    "LoopIP:10.120.47.20\n"
    "拨号ip:183.56.163.24\n"
    "秘钥:both-win\n"
)

zh_init_container = [None]
(
    zh_left,
    zh_py_out,
    zh_factory_out,
    zh_status,
    zh_gen,
    zh_exp,
    zh_rst,
    zh_sync_layout,
) = build_tab_shell(
    tab_single, ACCENT_HK, ZH_NOTE, ZH_EXAMPLE, zh_init_container)
zh_get_init, zh_reset_init, zh_get_raw = build_zihuan_init_panel(
    zh_init_container[0], ACCENT_HK)

_zh_last_lineid = ["lineid"]   # 缓存最近一次生成的 LineID，用于导出默认文件名


def zh_generate():
    dual_wan, wan1_ip, wan2_ip, wan1_gw, wan2_gw, w1if, w2if, zif, iif = zh_get_raw()
    ok, errs = validate_zihuan_init(
        dual_wan, wan1_ip, wan2_ip, wan1_gw, wan2_gw, w1if, w2if, zif, iif,
        DEFAULT_WAN1_IP, DEFAULT_WAN2_IP, DEFAULT_WAN1_GW, DEFAULT_WAN2_GW,
        DEFAULT_WAN1_PORT, DEFAULT_WAN2_PORT, DEFAULT_ZIHUAN_PORT, DEFAULT_IPSEC_PORT,
    )
    if not ok:
        messagebox.showwarning("输入校验未通过",
            "以下项不符合要求，请修正后再生成：\n\n" + "\n".join(errs))
        zh_status.set("⚠  请修正初始化参数后再生成")
        return
    raw = zh_left.get("1.0", tk.END).strip()
    if not raw:
        zh_status.set("⚠  请先输入业务数据"); return
    try:
        parsed = parse_ar_sdwan_text(raw)
    except Exception as e:
        messagebox.showerror("解析失败", str(e))
        zh_status.set("⚠  业务数据解析失败"); return
    if field_coverage:
        miss = field_coverage.ar_sdwan_missing_parsed_fields(parsed)
        field_coverage.show_generation_coverage_notice(
            messagebox, miss, "AR SD-WAN · 单机组网")
    cfg = zh_get_init()
    dual_wan = bool(cfg.get("dual_wan"))
    ops_key = "ar_ops_single_dualwan" if dual_wan else "ar_ops_single"
    fact_key = "ar_factory_single_dualwan" if dual_wan else "ar_factory_single"
    ov_ops = _apply_ar_visual_template_override(ops_key, raw, cfg)
    output = ov_ops if ov_ops is not None else render_ops_script(parsed, cfg)
    lid = extract_lineid_zihuan(raw) or parsed["lineid"]
    ov_fact = _apply_ar_visual_template_override(fact_key, raw, cfg, lid)
    factory = ov_fact if ov_fact is not None else render_factory_single(cfg, lid)
    _zh_last_lineid[0] = lid
    zh_py_out.delete("1.0", tk.END);      zh_py_out.insert(tk.END, output)
    zh_factory_out.delete("1.0", tk.END); zh_factory_out.insert(tk.END, factory)
    zh_status.set(f"✓  配置已生成  ·  OPS {output.count(chr(10))} 行  ·  LineID:{lid}")
    _zh_out = f"=== OPS ===\n{output}\n=== Factory ===\n{factory}"
    log_generate_config(
        tool="ar_sdwan", variant="single", input_text=raw, output_text=_zh_out)


def zh_export():
    c_py = zh_py_out.get("1.0", tk.END).strip()
    if not c_py:
        zh_status.set("⚠  尚无 OPS 配置"); return
    lid = _lineid_for_filename(_zh_last_lineid[0])
    p = filedialog.asksaveasfilename(
        title="保存 OPS 脚本",
        initialfile=f"{lid}.py",
        defaultextension=".py",
        filetypes=[("Python", "*.py"), ("Text", "*.txt"), ("All", "*.*")])
    if p:
        with open(p, "w", encoding="utf-8") as f:
            f.write(c_py)
        zh_status.set(f"✓  已导出：{p}")


def zh_reset():
    zh_left.delete("1.0", tk.END)
    zh_py_out.delete("1.0", tk.END)
    zh_factory_out.delete("1.0", tk.END)
    zh_reset_init()
    zh_status.set("↺  已恢复初始")


zh_gen.bind("<Button-1>", lambda e: zh_generate())
zh_exp.bind("<Button-1>", lambda e: zh_export())
zh_rst.bind("<Button-1>", lambda e: zh_reset())


# =====================================================================
# Tab 双机组网
# =====================================================================
DJ_NOTE = (
    "• 自己确认 IKE IPsec 参数！！！\n"
    "• 只有OPS脚本会被导出为txt，命名为lineidmain/backup.py\n"
    "• 南向服务可选。\n"
    "• 配置仅供参考，使用仍需谨慎。"
)
DJ_EXAMPLE = ZH_EXAMPLE   # 数据格式相同

dj_init_container = [None]
(dj_left, dj_py_pri, dj_fact_pri, dj_py_bak, dj_fact_bak,
 dj_status, dj_gen, dj_exp, dj_rst, dj_sync_layout) = build_dual_tab_shell(
    tab_dual, ACCENT_US, DJ_NOTE, DJ_EXAMPLE, dj_init_container)
dj_get_init, dj_reset_init, dj_get_raw = build_duoji_init_panel(
    dj_init_container[0], ACCENT_US)


def _schedule_pane_sync(sync_fn):
    """
    未选中的 Notebook 子页宽高常为 1，tab.after(150) 时 sash 无法正确设置。
    在页签已显示后：update_idletasks + 多拍延迟，使单机/双机 PanedWindow 分割一致。
    """
    def _run():
        try:
            root.update_idletasks()
        except Exception:
            pass
        try:
            sync_fn()
        except Exception:
            pass

    try:
        root.after_idle(_run)
    except Exception:
        _run()
    root.after(40, _run)
    root.after(180, _run)
    root.after(420, _run)


def _on_tab_changed(_evt=None):
    try:
        idx = main_nb.index(main_nb.select())
        clr = ACCENT_US if idx == 1 else ACCENT_HK
        sty.map("TNotebook.Tab", foreground=[("selected", clr), ("active", FG_BRT)])
        if idx == 0:
            _schedule_pane_sync(zh_sync_layout)
        else:
            _schedule_pane_sync(dj_sync_layout)
    except Exception:
        pass


main_nb.bind("<<NotebookTabChanged>>", _on_tab_changed)
# 子页每次被显示时重算 sash（含首次从隐藏变为可见的双机页）
tab_single.bind("<Map>", lambda _e: _schedule_pane_sync(zh_sync_layout))
tab_dual.bind("<Map>", lambda _e: _schedule_pane_sync(dj_sync_layout))
# 启动时 <<NotebookTabChanged>> 可能尚未触发，补一次当前可见页
root.after(100, _on_tab_changed)

_dj_last_lineid = ["lineid"]   # 缓存最近一次生成的 LineID


def dj_generate():
    wan1_ip, wan2_ip, wan1_gw, wan2_gw, w1if, z1if, i1if, w2if, z2if, i2if = dj_get_raw()
    ok, errs = validate_duoji_init(
        wan1_ip, wan2_ip, wan1_gw, wan2_gw,
        w1if, z1if, i1if,
        w2if, z2if, i2if,
    )
    if not ok:
        messagebox.showwarning("输入校验未通过",
            "以下项不符合要求，请修正后再生成：\n\n" + "\n".join(errs))
        dj_status.set("⚠  请修正初始化参数后再生成")
        return
    raw = dj_left.get("1.0", tk.END).strip()
    if not raw:
        dj_status.set("⚠  请先输入业务数据"); return
    try:
        parsed = parse_ar_sdwan_text(raw)
    except Exception as e:
        messagebox.showerror("解析失败", str(e))
        dj_status.set("⚠  业务数据解析失败"); return
    if field_coverage:
        miss = field_coverage.ar_sdwan_missing_parsed_fields(parsed)
        field_coverage.show_generation_coverage_notice(
            messagebox, miss, "AR SD-WAN · 双机组网")

    cfg = dj_get_init()
    lid = extract_lineid_zihuan(raw) or parsed["lineid"]
    _dj_last_lineid[0] = lid

    ov_pri = _apply_ar_visual_template_override("ar_ops_dual_pri", raw, cfg, lid)
    out_pri = ov_pri if ov_pri is not None else render_dual_primary(parsed, cfg)
    ov_bak = _apply_ar_visual_template_override("ar_ops_dual_bak", raw, cfg, lid)
    out_bak = ov_bak if ov_bak is not None else render_dual_backup(parsed, cfg)
    ov_fp = _apply_ar_visual_template_override("ar_factory_dual_pri", raw, cfg, lid)
    fact_pri = ov_fp if ov_fp is not None else render_factory_dual_primary(cfg, lid)
    ov_fb = _apply_ar_visual_template_override("ar_factory_dual_bak", raw, cfg, lid)
    fact_bak = ov_fb if ov_fb is not None else render_factory_dual_backup(cfg, lid)

    dj_py_pri.delete("1.0", tk.END);   dj_py_pri.insert(tk.END, out_pri)
    dj_fact_pri.delete("1.0", tk.END); dj_fact_pri.insert(tk.END, fact_pri)
    dj_py_bak.delete("1.0", tk.END);   dj_py_bak.insert(tk.END, out_bak)
    dj_fact_bak.delete("1.0", tk.END); dj_fact_bak.insert(tk.END, fact_bak)

    dj_status.set(
        f"✓  双机配置已生成  ·  主设备 {out_pri.count(chr(10))} 行  "
        f"备设备 {out_bak.count(chr(10))} 行  ·  LineID:{lid}"
    )
    _dj_out = (
        f"=== 主设备 OPS ===\n{out_pri}\n=== 主设备 Factory ===\n{fact_pri}\n"
        f"=== 备设备 OPS ===\n{out_bak}\n=== 备设备 Factory ===\n{fact_bak}"
    )
    log_generate_config(
        tool="ar_sdwan", variant="dual", input_text=raw, output_text=_dj_out)


def dj_export():
    c_pri = dj_py_pri.get("1.0", tk.END).strip()
    c_bak = dj_py_bak.get("1.0", tk.END).strip()
    if not c_pri and not c_bak:
        dj_status.set("⚠  尚无配置"); return
    lid = _lineid_for_filename(_dj_last_lineid[0])
    saved = []
    if c_pri:
        p = filedialog.asksaveasfilename(
            title="保存主设备 OPS 脚本",
            initialfile=f"{lid}main.py",
            defaultextension=".py",
            filetypes=[("Python", "*.py"), ("Text", "*.txt"), ("All", "*.*")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(c_pri)
            saved.append(f"主设备→{p}")
    if c_bak:
        p = filedialog.asksaveasfilename(
            title="保存备设备 OPS 脚本",
            initialfile=f"{lid}backup.py",
            defaultextension=".py",
            filetypes=[("Python", "*.py"), ("Text", "*.txt"), ("All", "*.*")])
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(c_bak)
            saved.append(f"备设备→{p}")
    if saved:
        dj_status.set("✓  已导出：" + "  |  ".join(saved))


def dj_reset():
    dj_left.delete("1.0", tk.END)
    for w in (dj_py_pri, dj_fact_pri, dj_py_bak, dj_fact_bak):
        w.delete("1.0", tk.END)
    dj_reset_init()
    dj_status.set("↺  已恢复初始")


dj_gen.bind("<Button-1>", lambda e: dj_generate())
dj_exp.bind("<Button-1>", lambda e: dj_export())
dj_rst.bind("<Button-1>", lambda e: dj_reset())


def _visual_merge_init_defaults(updates: dict) -> None:
    """all_in_one 可视化编辑器：合并 DEFAULT_* / DJ_* 并刷新单机、双机初始化面板。"""
    g = globals()
    for k, v in updates.items():
        if k == "ZH_DUAL_WAN":
            g["ZH_DUAL_WAN_SAVED"] = str(v).strip().lower() in ("1", "true", "yes", "on", "开")
        elif k == "ZH_SOUTH_LABEL":
            g["ZH_SOUTH_LABEL_SAVED"] = str(v).strip()
        elif k == "ZH_IKE_VERSION":
            g["ZH_IKE_VERSION_SAVED"] = _user_init_ike_storage(str(v))
        elif k == "DJ_SOUTH_LABEL":
            g["DJ_SOUTH_LABEL_SAVED"] = str(v).strip()
        elif k == "DJ_IKE_VERSION":
            g["DJ_IKE_VERSION_SAVED"] = _user_init_ike_storage(str(v))
        elif k in g:
            cur = g[k]
            if isinstance(cur, bool):
                g[k] = str(v).strip().lower() in ("1", "true", "yes", "on", "开")
            else:
                g[k] = str(v).strip()
    try:
        zh_reset_init()
    except Exception:
        pass
    try:
        dj_reset_init()
    except Exception:
        pass


root.mainloop()
