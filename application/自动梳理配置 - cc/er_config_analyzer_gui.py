# -*- coding: utf-8 -*-
import csv
import ipaddress
import re
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple


IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b")
# 与 analyze 中海外 NAT 备注一致：显式 (BK- / BK_m）优先于含 main 的英文子串
_RE_BK_PAREN = re.compile(r"[\[(（]\s*bk[-_]", re.I)
_RE_BK_TOKEN = re.compile(r"\bbk[-_][a-z0-9]", re.I)
_RE_BK_WORD = re.compile(r"\bbk\b", re.I)
_RE_BK_COMPACT = re.compile(r"(^|[^a-z0-9])bk\d+([^a-z0-9]|$)", re.I)
_RE_BACK_WORD = re.compile(r"\bback(?:up)?\b", re.I)
_RE_PRI_WORD = re.compile(r"\bpri(?:mary)?\b", re.I)
_RE_MAIN_WORD = re.compile(r"\bmain\b", re.I)
_RE_PRI_TOKEN = re.compile(r"(^|[^a-z0-9])pri(?:mary)?(?:[-_]|$)", re.I)
_RE_MAIN_TOKEN = re.compile(r"(^|[^a-z0-9])main(?:[-_]|$)", re.I)


def _line_remark_is_backup(*parts: str) -> bool:
    """接口备注/隧道名中是否显式标为备线（BK-/BK）。用于主/备线判定，不依赖其它规则。"""
    blob = " ".join(p for p in parts if p)
    if not blob.strip():
        return False
    if (
        _RE_BK_PAREN.search(blob)
        or _RE_BK_TOKEN.search(blob)
        or _RE_BK_WORD.search(blob)
        or _RE_BK_COMPACT.search(blob)
        or _RE_BACK_WORD.search(blob)
    ):
        return True
    return blob.strip().lower().startswith("bk-")


def _line_remark_is_main(*parts: str) -> bool:
    """接口备注/隧道名中是否显式标为主线（PRI/main/主）。"""
    blob = " ".join(p for p in parts if p)
    if not blob.strip():
        return False
    if _RE_PRI_WORD.search(blob) or _RE_MAIN_WORD.search(blob) or _RE_PRI_TOKEN.search(blob) or _RE_MAIN_TOKEN.search(blob):
        return True
    return any(k in blob for k in ("主", "主线"))


@dataclass
class NatRule:
    rule_id: str
    source_prefixes: List[str] = field(default_factory=list)
    destination_prefixes: List[str] = field(default_factory=list)
    outbound_interface: Optional[str] = None
    translation_address: Optional[str] = None

    def pick_prefixes(self) -> List[str]:
        # User requested NAT-based parsing with source IP only.
        return self.source_prefixes


@dataclass
class DnatRule:
    rule_id: str
    inbound_interface: Optional[str] = None
    destination_prefixes: List[str] = field(default_factory=list)
    translation_address: Optional[str] = None


@dataclass
class UsgNatRule:
    rule_name: str
    egress_interface: Optional[str] = None
    source_address_set: Optional[str] = None
    source_prefixes: List[str] = field(default_factory=list)
    action_type: Optional[str] = None
    action_address_group: Optional[str] = None


# Site-to-site overlay underlay for domestic GRE: OpenVPN, VyOS VTI, or policy IPsec (dummy/eth addr = IPsec local TS).
ACCESS_TRANSPORT_ROLES: Tuple[str, ...] = ("openvpn", "ipsec-vti", "ipsec-policy")
IPSEC_TS_DESC_MARK = "IPsec site-to-site local TS"

# 解析并梳理：无 NAT 命中时在 NAT 表格中展示的单行占位（不弹窗）。
NAT_TABLE_PLACEHOLDER_NO_NAT: Dict[str, str] = {
    "rule": "无NAT",
    "source_ip": "",
    "egress_name": "",
    "egress_remark": "",
    "fake_ip": "",
    "real_ip": "",
}


@dataclass
class TunnelNode:
    name: str
    kind: str
    source: str = ""
    remote: str = ""
    address: str = ""
    description: str = ""
    inferred_role: str = "unknown"
    side: str = "unknown"  # 解析得到的「主/备」线索之一（与 description 关键词等一致）
    canvas_side: str = "unknown"  # 同上；画布上下半区只看 topology_line_side_for_node() 的合并结果
    evidence: List[str] = field(default_factory=list)


@dataclass
class RouteEdge:
    destination: str
    next_hop: str
    route_table: str = "main"
    via_tunnel: str = ""
    origin: str = "unknown"  # static | bgp-config | unknown (FIB line may still be learned at runtime)
    preference: str = ""
    track_name: str = ""
    evidence: str = ""


@dataclass
class PolicyRule:
    policy_name: str
    rule_id: str
    source: str = ""
    destination_group: str = ""
    table: str = ""
    interface: str = ""
    policy_type: str = "unknown"
    evidence: List[str] = field(default_factory=list)


@dataclass
class BgpBinding:
    neighbor: str
    peer_group: str
    update_source: str = ""
    egress_hint: str = ""
    remote_as: str = ""
    export_prefix_list: str = ""
    advertised_prefixes: List[str] = field(default_factory=list)
    lane_side: str = ""  # main | backup | unknown — filled in analyze_er_topology for canvas placement
    anchor_tunnel: str = ""  # local tunnel iface this BGP session binds to (under which we draw the BGP block)
    transport_tunnel: str = ""  # neighbor/* 静态递归得到的承载隧道（可与 update-source 所在 lo 不同）


@dataclass
class LedgerItem:
    topic: str
    count: int = 0
    example_lines: List[str] = field(default_factory=list)
    detail: str = ""


@dataclass
class RemarkConflict:
    tunnel: str
    remark_hint: str
    resolved_role: str
    strong_basis: str
    reference: str = ""


def _clean_value(raw: str) -> str:
    value = raw.strip().strip("'").strip('"')
    return value


def parse_fake_real_mapping(mapping_text: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    normalized = mapping_text.replace("\r", "\n")
    segments = re.split(r"[;\n；]+", normalized)

    for segment in segments:
        s = segment.strip()
        if not s:
            continue

        # Handle various separators: ->, =>, =, :, ：, -, —
        parts = re.split(r"\s*(?:->|=>|=|:|：|-|—)\s*", s, maxsplit=1)
        left = ""
        right = ""
        if len(parts) == 2:
            left, right = parts[0], parts[1]
            left_ips = IP_PATTERN.findall(left)
            right_ips = IP_PATTERN.findall(right)
            if left_ips and right_ips:
                mapping[left_ips[0].split("/")[0]] = right_ips[0].split("/")[0]
                continue

        ips = IP_PATTERN.findall(s)
        if len(ips) >= 2:
            mapping[ips[0].split("/")[0]] = ips[1].split("/")[0]

    return mapping


def parse_er_config(config_text: str) -> Dict[str, object]:
    rules: Dict[str, NatRule] = {}
    dnat_rules: Dict[str, DnatRule] = {}
    iface_desc: Dict[str, str] = {}

    nat_field_re = re.compile(
        r"^set\s+nat\s+source\s+rule\s+(\d+)\s+"
        r"(source|destination)\s+address\s+'?([^'\s]+)'?",
        re.IGNORECASE,
    )
    nat_outbound_re = re.compile(
        r"^set\s+nat\s+source\s+rule\s+(\d+)\s+outbound-interface\s+'?([^'\s]+)'?",
        re.IGNORECASE,
    )
    nat_translation_re = re.compile(
        r"^set\s+nat\s+source\s+rule\s+(\d+)\s+translation\s+address\s+'?([^'\s]+)'?",
        re.IGNORECASE,
    )
    dnat_dst_re = re.compile(
        r"^set\s+nat\s+destination\s+rule\s+(\d+)\s+destination\s+address\s+'?([^'\s]+)'?",
        re.IGNORECASE,
    )
    dnat_in_re = re.compile(
        r"^set\s+nat\s+destination\s+rule\s+(\d+)\s+inbound-interface\s+'?([^'\s]+)'?",
        re.IGNORECASE,
    )
    dnat_trans_re = re.compile(
        r"^set\s+nat\s+destination\s+rule\s+(\d+)\s+translation\s+address\s+'?([^'\s]+)'?",
        re.IGNORECASE,
    )
    iface_desc_re = re.compile(
        r"^set\s+interfaces\s+(?:tunnel|openvpn|dummy|ethernet)\s+([^\s]+)\s+description\s+'([^']+)'",
        re.IGNORECASE,
    )
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        m_field = nat_field_re.match(line)
        if m_field:
            rule_id, direction, addr = m_field.groups()
            rule = rules.setdefault(rule_id, NatRule(rule_id=rule_id))
            addr = _clean_value(addr)
            if direction.lower() == "source":
                rule.source_prefixes.append(addr)
            else:
                rule.destination_prefixes.append(addr)
            continue

        m_out = nat_outbound_re.match(line)
        if m_out:
            rule_id, iface = m_out.groups()
            rules.setdefault(rule_id, NatRule(rule_id=rule_id)).outbound_interface = _clean_value(iface)
            continue

        m_trans = nat_translation_re.match(line)
        if m_trans:
            rule_id, fake_ip = m_trans.groups()
            rules.setdefault(rule_id, NatRule(rule_id=rule_id)).translation_address = _clean_value(fake_ip)
            continue

        m_desc = iface_desc_re.match(line)
        if m_desc:
            iface, desc = m_desc.groups()
            iface_desc[_clean_value(iface)] = _clean_value(desc)
            continue

        m_dnat_dst = dnat_dst_re.match(line)
        if m_dnat_dst:
            rid, dst = m_dnat_dst.groups()
            dnat_rules.setdefault(rid, DnatRule(rule_id=_clean_value(rid))).destination_prefixes.append(_clean_value(dst))
            continue
        m_dnat_in = dnat_in_re.match(line)
        if m_dnat_in:
            rid, iface = m_dnat_in.groups()
            dnat_rules.setdefault(rid, DnatRule(rule_id=_clean_value(rid))).inbound_interface = _clean_value(iface)
            continue
        m_dnat_trans = dnat_trans_re.match(line)
        if m_dnat_trans:
            rid, ip = m_dnat_trans.groups()
            dnat_rules.setdefault(rid, DnatRule(rule_id=_clean_value(rid))).translation_address = _clean_value(ip)
            continue

    return {
        "rules": list(sorted(rules.values(), key=lambda r: int(r.rule_id))),
        "dnat_rules": list(sorted(dnat_rules.values(), key=lambda r: int(r.rule_id))),
        "iface_desc": iface_desc,
    }


def mask_to_prefix(mask_text: str) -> Optional[str]:
    mask = mask_text.strip()
    if not mask:
        return None
    if mask.isdigit():
        n = int(mask)
        if 0 <= n <= 32:
            return str(n)
        return None

    parts = mask.split(".")
    if len(parts) != 4:
        return None
    bits = ""
    for p in parts:
        if not p.isdigit():
            return None
        n = int(p)
        if n < 0 or n > 255:
            return None
        bits += f"{n:08b}"
    if "01" in bits:
        return None
    return str(bits.count("1"))


def parse_usg_config(config_text: str) -> Dict[str, object]:
    address_sets: Dict[str, List[str]] = {}
    nat_address_groups: Dict[str, List[str]] = {}
    interface_desc: Dict[str, str] = {}
    rules: List[UsgNatRule] = []

    current_address_set: Optional[str] = None
    current_nat_group: Optional[str] = None
    current_interface: Optional[str] = None
    current_rule: Optional[UsgNatRule] = None

    address_set_start_re = re.compile(r"^ip\s+address-set\s+([^\s]+)\s+type\s+object$", re.IGNORECASE)
    address_entry_re = re.compile(r"^address\s+\d+\s+([0-9.]+)\s+mask\s+([0-9.]+|\d+)$", re.IGNORECASE)
    nat_group_start_re = re.compile(r"^nat\s+address-group\s+([^\s]+)(?:\s+\d+)?$", re.IGNORECASE)
    nat_group_section_re = re.compile(r"^section\s+\d+\s+([0-9.]+)\s+([0-9.]+)$", re.IGNORECASE)
    interface_start_re = re.compile(r"^interface\s+([^\s]+)$", re.IGNORECASE)
    interface_desc_re = re.compile(r"^description\s+(.+)$", re.IGNORECASE)
    rule_name_re = re.compile(r"^rule\s+name\s+(.+)$", re.IGNORECASE)
    egress_re = re.compile(r"^egress-interface\s+([^\s]+)$", re.IGNORECASE)
    src_addr_set_re = re.compile(r"^source-address\s+address-set\s+([^\s]+)$", re.IGNORECASE)
    src_addr_direct_re = re.compile(r"^source-address\s+([0-9.]+)\s+mask\s+([0-9.]+|\d+)$", re.IGNORECASE)
    src_addr_range_re = re.compile(r"^source-address\s+range\s+([0-9.]+)\s+([0-9.]+)$", re.IGNORECASE)
    action_group_re = re.compile(r"^action\s+source-nat\s+address-group\s+([^\s]+)(?:\s+.*)?$", re.IGNORECASE)
    action_easy_ip_re = re.compile(r"^action\s+source-nat\s+easy-ip$", re.IGNORECASE)
    action_no_nat_re = re.compile(r"^action\s+no-nat$", re.IGNORECASE)

    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        m_addr_set = address_set_start_re.match(line)
        if m_addr_set:
            current_address_set = _clean_value(m_addr_set.group(1))
            address_sets.setdefault(current_address_set, [])
            current_nat_group = None
            continue

        m_addr_entry = address_entry_re.match(line)
        if m_addr_entry and current_address_set:
            ip, mask = m_addr_entry.groups()
            prefix = mask_to_prefix(mask)
            if prefix is not None:
                address_sets[current_address_set].append(f"{ip}/{prefix}")
            continue

        m_nat_group = nat_group_start_re.match(line)
        if m_nat_group:
            current_nat_group = _clean_value(m_nat_group.group(1))
            nat_address_groups.setdefault(current_nat_group, [])
            current_address_set = None
            continue

        m_nat_section = nat_group_section_re.match(line)
        if m_nat_section and current_nat_group:
            start_ip, end_ip = m_nat_section.groups()
            # Use concrete start IP as fake IP; if range exists, include both endpoints.
            nat_address_groups[current_nat_group].append(start_ip)
            if end_ip != start_ip:
                nat_address_groups[current_nat_group].append(end_ip)
            continue

        m_if_start = interface_start_re.match(line)
        if m_if_start:
            current_interface = _clean_value(m_if_start.group(1))
            current_address_set = None
            current_nat_group = None
            continue

        m_if_desc = interface_desc_re.match(line)
        if m_if_desc and current_interface:
            interface_desc[current_interface] = _clean_value(m_if_desc.group(1))
            continue

        m_rule_name = rule_name_re.match(line)
        if m_rule_name:
            current_rule = UsgNatRule(rule_name=_clean_value(m_rule_name.group(1)))
            rules.append(current_rule)
            continue

        if not current_rule:
            continue

        m_egress = egress_re.match(line)
        if m_egress:
            current_rule.egress_interface = _clean_value(m_egress.group(1))
            continue

        m_src_set = src_addr_set_re.match(line)
        if m_src_set:
            current_rule.source_address_set = _clean_value(m_src_set.group(1))
            continue

        m_src_direct = src_addr_direct_re.match(line)
        if m_src_direct:
            ip, mask = m_src_direct.groups()
            prefix = mask_to_prefix(mask)
            if prefix is not None:
                current_rule.source_prefixes.append(f"{ip}/{prefix}")
            continue

        m_src_range = src_addr_range_re.match(line)
        if m_src_range:
            start_ip, end_ip = m_src_range.groups()
            # Keep source range explicit for NAT traceability.
            current_rule.source_prefixes.append(f"{start_ip}-{end_ip}")
            continue

        m_action_group = action_group_re.match(line)
        if m_action_group:
            current_rule.action_type = "source-nat-address-group"
            current_rule.action_address_group = _clean_value(m_action_group.group(1))
            continue

        if action_easy_ip_re.match(line):
            current_rule.action_type = "source-nat-easy-ip"
            continue

        if action_no_nat_re.match(line):
            current_rule.action_type = "no-nat"
            continue

    return {
        "rules": rules,
        "address_sets": address_sets,
        "nat_address_groups": nat_address_groups,
        "iface_desc": interface_desc,
    }


def infer_egress_label(interface_name: str, iface_desc: Dict[str, str]) -> str:
    if not interface_name:
        return "(未识别)"
    if interface_name in iface_desc:
        return iface_desc[interface_name]

    s = interface_name.lower()
    if "main" in s:
        return "MAIN"
    if "backup" in s or s.startswith("bk") or "_bk" in s:
        return "BACKUP"
    if s.startswith("tun"):
        return "TUNNEL"
    return interface_name


def build_output_rows(config_text: str, mapping_text: str) -> List[Dict[str, str]]:
    cfg = parse_er_config(config_text)
    mapping = parse_fake_real_mapping(mapping_text)
    rows: List[Dict[str, str]] = []

    rules: List[NatRule] = cfg["rules"]  # type: ignore[assignment]
    dnat_rules: List[DnatRule] = cfg.get("dnat_rules", [])  # type: ignore[assignment]
    iface_desc: Dict[str, str] = cfg["iface_desc"]  # type: ignore[assignment]

    for rule in rules:
        outbound = rule.outbound_interface or "(未指定)"
        egress_remark = iface_desc.get(outbound, "(无备注)")
        fake_ip = (rule.translation_address or "").split("/")[0]
        if fake_ip.lower() == "masquerade":
            # Skip default WAN masquerade rules; focus on FastIP export mapping.
            continue
        real_ip = mapping.get(fake_ip, "")
        prefixes = rule.pick_prefixes()
        if prefixes:
            for prefix in prefixes:
                rows.append(
                    {
                        "rule": f"SNAT-{rule.rule_id}",
                        "source_ip": prefix,
                        "egress_name": outbound,
                        "egress_remark": egress_remark,
                        "fake_ip": fake_ip or "(无)",
                        "real_ip": real_ip or "(未提供)",
                    }
                )
        elif rule.outbound_interface and fake_ip:
            # VyOS 允许不写 source-address：仍输出一行，source 列标明「未在配置中限定」。
            rows.append(
                {
                    "rule": f"SNAT-{rule.rule_id}",
                    "source_ip": "(配置未限定 source-address/network)",
                    "egress_name": outbound,
                    "egress_remark": egress_remark,
                    "fake_ip": fake_ip or "(无)",
                    "real_ip": real_ip or "(未提供)",
                }
            )

    for dr in dnat_rules:
        inbound = dr.inbound_interface or "(未指定)"
        remark = iface_desc.get(inbound, "(无备注)")
        fake_ip = (dr.destination_prefixes[0].split("/")[0] if dr.destination_prefixes else "(无)")
        real_ip = (dr.translation_address or "").split("/")[0] or "(无)"
        dst_text = ",".join(dr.destination_prefixes) if dr.destination_prefixes else "(无)"
        rows.append(
            {
                "rule": f"DNAT-{dr.rule_id}",
                "source_ip": f"DST:{dst_text}",
                "egress_name": inbound,
                "egress_remark": remark,
                "fake_ip": fake_ip,
                "real_ip": real_ip,
            }
        )

    return rows


def build_output_rows_usg(config_text: str, mapping_text: str) -> List[Dict[str, str]]:
    parsed = parse_usg_config(config_text)
    mapping = parse_fake_real_mapping(mapping_text)
    rows: List[Dict[str, str]] = []

    rules: List[UsgNatRule] = parsed["rules"]  # type: ignore[assignment]
    address_sets: Dict[str, List[str]] = parsed["address_sets"]  # type: ignore[assignment]
    nat_address_groups: Dict[str, List[str]] = parsed["nat_address_groups"]  # type: ignore[assignment]
    iface_desc: Dict[str, str] = parsed["iface_desc"]  # type: ignore[assignment]

    for rule in rules:
        if rule.action_type in (None, "no-nat"):
            continue
        if rule.action_type == "source-nat-easy-ip":
            # Keep focus on FastIP export mapping rules.
            continue

        egress = rule.egress_interface or "(未指定)"
        egress_remark = iface_desc.get(egress, "(无备注)")
        prefixes = list(rule.source_prefixes)
        prefixes.extend(address_sets.get(rule.source_address_set or "", []))
        prefixes = sorted(set(prefixes))
        if not prefixes:
            continue

        fake_ips: List[str] = []
        if rule.action_type == "source-nat-address-group":
            group_name = rule.action_address_group or ""
            fake_ips = nat_address_groups.get(group_name, [])
            if not fake_ips:
                fake_ips = address_sets.get(group_name, [])
        if not fake_ips:
            continue

        for prefix in prefixes:
            for fake in fake_ips:
                fake_key = fake.split("/")[0].strip()
                if not fake_key:
                    fake_key = "(未识别)"
                real_ip = mapping.get(fake_key, "")
                rows.append(
                    {
                        "rule": rule.rule_name,
                        "source_ip": prefix,
                        "egress_name": egress,
                        "egress_remark": egress_remark,
                        "fake_ip": fake_key,
                        "real_ip": real_ip or "(未提供)",
                    }
                )

    return rows


def _peer_ip_from_cidr(cidr: str) -> str:
    try:
        iface = ipaddress.ip_interface(cidr)
        network = iface.network
        hosts = list(network.hosts())
        if len(hosts) == 2:
            return str(hosts[1] if str(hosts[0]) == str(iface.ip) else hosts[0])
    except Exception:
        return ""
    return ""


def _local_ip_from_cidr(cidr: str) -> str:
    try:
        return str(ipaddress.ip_interface(cidr).ip)
    except Exception:
        return ""


def _host_ip_from_pfx_or_addr(s: str) -> str:
    """Host IP from VyOS iface address or IPsec local/remote prefix (with or without /len)."""
    s = _clean_value(s).strip() if s else ""
    if not s:
        return ""
    try:
        return str(ipaddress.ip_interface(s).ip)
    except Exception:
        try:
            return str(ipaddress.ip_address(s))
        except Exception:
            return ""


def _infer_side(*texts: str) -> str:
    """主/备线文字线索。须先认 BK- / 备，再认 main，避免 '...main...' 英文词先于 'bk' 命中。"""
    joined = " ".join(t for t in texts if t)
    if _line_remark_is_backup(joined):
        return "backup"
    joined_l = joined.lower()
    if any(k in joined_l for k in ("backup", "备", "rsvr2", "_b", "bk")):
        return "backup"
    if _line_remark_is_main(joined):
        return "main"
    if any(k in joined_l for k in ("main", "主", "_a", "rsvr ")):
        return "main"
    return "unknown"


def _remark_gre_role_from_desc(description: str) -> str:
    """Weak role hint from interface description only (gre-upe / gre-overseas / '')."""
    desc_l = (description or "").lower()
    if "natpe" in desc_l:
        return "gre-overseas"
    if "upe" in desc_l:
        return "gre-upe"
    return ""


def _canvas_side_evidence(description: str, iface_extra_desc: str = "", remote: str = "") -> str:
    """主线 vs 备线的证据之一（关键词）：备注、接口 description、remote；不用接口名与 SNAT。"""
    return _infer_side("", description or "", iface_extra_desc or "", remote or "")


def topology_line_side_for_node(
    n: TunnelNode,
    tunnels: Dict[str, TunnelNode],
    overseas_parent: Dict[str, str],
) -> str:
    """唯一对外判定：这条链路是「主线」还是「备线」。

    画布规则仅此一条映射：主线 → 上半区，备线 → 下半区。
    备注、BK-、BGP 命名、canvas_side/side、海外 NATPE 上游继承等均在 analyze 中写入节点字段；
    此处只做合并与冲突消解（例如备注判备优先于误判的主线画布关键词）。
    """
    if _line_remark_is_backup(n.description or "", n.name or ""):
        return "backup"
    if _line_remark_is_main(n.description or "", n.name or ""):
        return "main"

    def _merge_one(node: TunnelNode) -> str:
        if _line_remark_is_backup(node.description or "", node.name or ""):
            return "backup"
        if _line_remark_is_main(node.description or "", node.name or ""):
            return "main"
        cs = (getattr(node, "canvas_side", "") or "").strip()
        sd = (node.side or "").strip()
        if sd == "backup" and cs == "main":
            return "backup"
        if cs in ("main", "backup"):
            return cs
        if sd in ("main", "backup"):
            return sd
        return "unknown"

    r = _merge_one(n)
    if r != "unknown":
        return r
    if getattr(n, "inferred_role", "") != "gre-overseas":
        return "unknown"
    cur = str(overseas_parent.get(n.name, "") or "")
    seen: set[str] = set()
    while cur and cur not in seen and cur != "host":
        seen.add(cur)
        pn = tunnels.get(cur)
        if not pn:
            break
        r = _merge_one(pn)
        if r != "unknown":
            return r
        cur = str(overseas_parent.get(pn.name, "") or "")
    return "unknown"


def _peer_group_lane_hint(peer_group: str) -> str:
    """与 bgp_canvas_lane_side 一致：RSVR→main，RSVR2/backup 后缀→backup。"""
    pg = (peer_group or "").lower()
    if pg and ("rsvr2" in pg or "backup" in pg or pg.endswith("2")):
        return "backup"
    if pg and "rsvr" in pg:
        return "main"
    return "unknown"


def _access_ip_to_tunnel_name(tunnels: Dict[str, TunnelNode], openvpn_local_ips: Dict[str, str]) -> Dict[str, str]:
    """Map local underlay IP -> tunnel iface name for access transports (structural)."""
    idx: Dict[str, str] = {}
    for n in tunnels.values():
        if n.kind == "openvpn":
            lip = (openvpn_local_ips.get(n.name) or "").strip() or _local_ip_from_cidr(n.address or "")
            if lip:
                idx[lip] = n.name
        elif n.kind == "vti":
            lip = _local_ip_from_cidr(n.address or "")
            if lip:
                idx[lip] = n.name
        elif n.kind in ("dummy", "ethernet", "loopback") and IPSEC_TS_DESC_MARK in (n.description or ""):
            lip = _local_ip_from_cidr(n.address or "")
            if lip:
                idx[lip] = n.name
    return idx


def _tunnel_source_strong_underlay(
    source: str,
    access_ip_index: Dict[str, str],
    transport_underlay_ips: set,
) -> Tuple[bool, str]:
    """True if source-address binds to a resolved access transport IP (strong), with evidence text."""
    src = (source or "").strip()
    if not src:
        return False, ""
    sip = src.split("/")[0].strip()
    if sip in access_ip_index:
        return True, f"source-address={sip} 绑定接入层 {access_ip_index[sip]}（接口地址表）"
    if sip in transport_underlay_ips:
        return True, f"source-address={sip} 命中接入层 underlay IP 集合"
    return False, ""


def _format_parse_ledger(ledger: Dict[str, object]) -> str:
    lines: List[str] = []
    lines.append("=== 解析备注（证据与未覆盖项）===")
    for title, key in (
        ("已解析（摘要）", "read_ok"),
        ("部分解析", "read_partial"),
        ("未消费配置行（抽样）", "not_read"),
        ("未判定对象", "unresolved"),
        ("备注与结构化结论冲突", "remark_conflicts"),
    ):
        block = ledger.get(key)
        if not block:
            continue
        lines.append(f"\n--- {title} ---")
        if key == "remark_conflicts":
            for rc in block:
                if isinstance(rc, RemarkConflict):
                    lines.append(
                        f"- 隧道 {rc.tunnel}: 备注暗示 [{rc.remark_hint}] "
                        f"vs 采用 [{rc.resolved_role}] 依据={rc.strong_basis}"
                    )
                    if rc.reference:
                        lines.append(f"  引用: {rc.reference[:240]}")
                elif isinstance(rc, dict):
                    lines.append(str(rc))
            continue
        for item in block:
            if isinstance(item, LedgerItem):
                ex = "; ".join(item.example_lines[:3]) if item.example_lines else ""
                lines.append(f"- [{item.topic}] n={item.count} {item.detail}" + (f" 例: {ex}" if ex else ""))
            else:
                lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def bgp_canvas_lane_side(
    b: BgpBinding,
    tunnel_by_name: Dict[str, TunnelNode],
    overseas_parent: Dict[str, str],
    routes: List[RouteEdge],
) -> str:
    """Classify BGP neighbor into main/backup canvas lane from egress_hint + tunnel side + static routes (no guessing beyond stated rules)."""

    pg = (b.peer_group or "").lower()
    if pg and ("rsvr2" in pg or "backup" in pg or pg.endswith("2")):
        return "backup"
    if pg and "rsvr" in pg:
        return "main"

    def eff_out_side(out: TunnelNode) -> str:
        cs = getattr(out, "canvas_side", None) or out.side
        if cs in ("main", "backup"):
            return cs
        parent = str(overseas_parent.get(out.name, ""))
        if parent in tunnel_by_name:
            pn = tunnel_by_name[parent]
            pside = getattr(pn, "canvas_side", None) or pn.side
            if pside in ("main", "backup"):
                return pside
        return "unknown"

    hint0 = str(b.egress_hint or "")
    if hint0 == "main":
        return "main"
    if hint0 == "backup":
        return "backup"
    if hint0 in tunnel_by_name:
        tn0 = tunnel_by_name[hint0]
        ts0 = getattr(tn0, "canvas_side", None) or tn0.side
        if ts0 in ("main", "backup"):
            return ts0
        if tn0.inferred_role == "gre-overseas":
            es0 = eff_out_side(tn0)
            if es0 in ("main", "backup"):
                return es0
        if tn0.inferred_role in ACCESS_TRANSPORT_ROLES:
            ts1 = getattr(tn0, "canvas_side", None) or tn0.side
            if ts1 in ("main", "backup"):
                return ts1
    for r0 in routes:
        if not isinstance(r0, RouteEdge):
            continue
        if r0.origin == "bgp-config":
            continue
        if not r0.destination.startswith(f"{b.neighbor}/"):
            continue
        if not r0.via_tunnel:
            continue
        vn0 = tunnel_by_name.get(r0.via_tunnel)
        if vn0:
            vns = getattr(vn0, "canvas_side", None) or vn0.side
            if vns in ("main", "backup"):
                return vns
        if vn0 and vn0.inferred_role == "gre-overseas":
            es0 = eff_out_side(vn0)
            if es0 in ("main", "backup"):
                return es0
        if vn0 and vn0.inferred_role in ACCESS_TRANSPORT_ROLES:
            vns2 = getattr(vn0, "canvas_side", None) or vn0.side
            if vns2 in ("main", "backup"):
                return vns2
    return "unknown"


def analyze_er_topology(config_text: str, accept_remark_heuristic: bool = False) -> Dict[str, object]:
    tunnels: Dict[str, TunnelNode] = {}
    routes: List[RouteEdge] = []
    policies: List[PolicyRule] = []
    bgp_by_neighbor: Dict[str, BgpBinding] = {}
    peer_group_update_source: Dict[str, str] = {}
    peer_group_remote_as: Dict[str, str] = {}
    peer_group_export_prefix: Dict[str, str] = {}
    prefix_list_rules: Dict[str, Dict[str, Dict[str, str]]] = {}
    policy_route_by_name: Dict[str, PolicyRule] = {}
    local_route_by_rule: Dict[str, PolicyRule] = {}
    interface_policy_bind: Dict[str, List[str]] = {}
    nat_outbounds: List[str] = []
    nat_rule_outbound: Dict[str, str] = {}
    nat_rule_translation: Dict[str, str] = {}
    nat_rule_sources: Dict[str, List[str]] = {}
    dnat_rule_prefixes: Dict[str, List[str]] = {}
    dnat_rule_count = 0
    openvpn_local_ips: Dict[str, str] = {}
    openvpn_remote_ips: Dict[str, str] = {}
    iface_addr_book: Dict[str, List[str]] = {}
    iface_desc_book: Dict[str, str] = {}
    static_route_index: Dict[Tuple[str, str, str], RouteEdge] = {}
    bgp_neighbor_in_routemap: Dict[str, str] = {}
    bgp_peer_group_in_routemap: Dict[str, str] = {}
    route_map_rule_match80: Dict[Tuple[str, str], bool] = {}
    route_map_rule_next_hop: Dict[Tuple[str, str], str] = {}
    route_map_rule_comm_ref: Dict[Tuple[str, str], str] = {}
    hostname = "本机"
    ipsec_tunnels_by_key: Dict[Tuple[str, str], Dict[str, str]] = {}

    re_tunnel_desc = re.compile(r"^set interfaces (openvpn|tunnel)\s+([^\s]+)\s+description\s+'([^']+)'", re.I)
    re_tunnel_source = re.compile(r"^set interfaces (openvpn|tunnel)\s+([^\s]+)\s+source-address\s+'?([^'\s]+)'?", re.I)
    re_tunnel_remote = re.compile(r"^set interfaces (openvpn|tunnel)\s+([^\s]+)\s+remote(?:-address)?\s+'?([^'\s]+)'?", re.I)
    re_tunnel_addr = re.compile(r"^set interfaces (openvpn|tunnel)\s+([^\s]+)\s+address\s+'?([^'\s]+)'?", re.I)
    re_openvpn_local = re.compile(
        r"^set interfaces openvpn\s+([^\s]+)\s+local-address\s+([^\s]+)\s+subnet-mask\s+'?([^'\s]+)'?", re.I
    )
    re_openvpn_remote_addr = re.compile(r"^set interfaces openvpn\s+([^\s]+)\s+remote-address\s+'?([^'\s]+)'?", re.I)
    re_vti_desc = re.compile(r"^set interfaces vti\s+([^\s]+)\s+description\s+'([^']+)'", re.I)
    re_vti_addr = re.compile(r"^set interfaces vti\s+([^\s]+)\s+address\s+'?([^'\s]+)'?", re.I)
    re_ipsec_local_prefix = re.compile(
        r"^set vpn ipsec site-to-site peer\s+([^\s]+)\s+tunnel\s+(\d+)\s+local\s+prefix\s+'?([^'\s]+)'?",
        re.I,
    )
    re_ipsec_remote_prefix = re.compile(
        r"^set vpn ipsec site-to-site peer\s+([^\s]+)\s+tunnel\s+(\d+)\s+remote\s+prefix\s+'?([^'\s]+)'?",
        re.I,
    )
    re_iface_addr = re.compile(
        r"^set interfaces (ethernet|bridge|dummy|loopback)\s+([^\s]+)\s+address\s+'?([^'\s]+)'?",
        re.I,
    )
    re_iface_desc = re.compile(
        r"^set interfaces (ethernet|bridge|dummy|loopback)\s+([^\s]+)\s+description\s+'?([^']+)'?",
        re.I,
    )
    re_static = re.compile(r"^set protocols static route\s+([^\s]+)\s+next-hop\s+([^\s]+)", re.I)
    re_static_table = re.compile(r"^set protocols static table\s+([^\s]+)\s+route\s+([^\s]+)\s+next-hop\s+([^\s]+)", re.I)
    re_static_pref = re.compile(
        r"^set protocols static route\s+([^\s]+)\s+next-hop\s+([^\s]+)\s+(?:distance|preference)\s+'?([^'\s]+)'?",
        re.I,
    )
    re_static_track = re.compile(
        r"^set protocols static route\s+([^\s]+)\s+next-hop\s+([^\s]+)\s+track\s+'?([^'\s]+)'?",
        re.I,
    )
    re_static_table_pref = re.compile(
        r"^set protocols static table\s+([^\s]+)\s+route\s+([^\s]+)\s+next-hop\s+([^\s]+)\s+(?:distance|preference)\s+'?([^'\s]+)'?",
        re.I,
    )
    re_static_table_track = re.compile(
        r"^set protocols static table\s+([^\s]+)\s+route\s+([^\s]+)\s+next-hop\s+([^\s]+)\s+track\s+'?([^'\s]+)'?",
        re.I,
    )
    re_local_src = re.compile(r"^set policy local-route rule\s+([^\s]+)\s+source\s+'?([^'\s]+)'?", re.I)
    re_local_table = re.compile(r"^set policy local-route rule\s+([^\s]+)\s+set table\s+'?([^'\s]+)'?", re.I)
    re_pol_dest = re.compile(r"^set policy route\s+([^\s]+)\s+rule\s+([^\s]+)\s+destination group address-group\s+'?([^'\s]+)'?", re.I)
    re_pol_src = re.compile(r"^set policy route\s+([^\s]+)\s+rule\s+([^\s]+)\s+source address\s+'?([^'\s]+)'?", re.I)
    re_pol_table = re.compile(r"^set policy route\s+([^\s]+)\s+rule\s+([^\s]+)\s+set table\s+'?([^'\s]+)'?", re.I)
    re_if_pol = re.compile(
        r"^set interfaces (?:ethernet|bridge|pppoe)\s+([^\s]+)\s+policy route\s+'?([^'\s]+)'?",
        re.I,
    )
    re_bgp_neighbor = re.compile(r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+peer-group\s+'?([^'\s]+)'?", re.I)
    re_bgp_update = re.compile(r"^set protocols bgp \d+ peer-group\s+([^\s]+)\s+update-source\s+'?([^'\s]+)'?", re.I)
    re_bgp_neighbor_route_map = re.compile(
        r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+route-map\s+(?:import|in)\s+'?([^'\s]+)'?",
        re.I,
    )
    re_bgp_neighbor_af_route_map = re.compile(
        r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+address-family\s+ipv4-unicast\s+route-map\s+(?:import|in)\s+'?([^'\s]+)'?",
        re.I,
    )
    re_bgp_peer_group_af_route_map = re.compile(
        r"^set protocols bgp \d+ peer-group\s+([^\s]+)\s+address-family\s+ipv4-unicast\s+route-map\s+(?:import|in)\s+'?([^'\s]+)'?",
        re.I,
    )
    re_bgp_peer_group_remote_as = re.compile(
        r"^set protocols bgp \d+ peer-group\s+([^\s]+)\s+remote-as\s+'?([^'\s]+)'?",
        re.I,
    )
    re_bgp_peer_group_af_prefix_export = re.compile(
        r"^set protocols bgp \d+ peer-group\s+([^\s]+)\s+address-family\s+ipv4-unicast\s+prefix-list\s+export\s+'?([^'\s]+)'?",
        re.I,
    )
    re_rm_match_community = re.compile(
        r"^set policy route-map\s+([^\s]+)\s+rule\s+([^\s]+)\s+match\s+community\s+(.+)$",
        re.I,
    )
    re_rm_set_next_hop = re.compile(
        r"^set policy route-map\s+([^\s]+)\s+rule\s+([^\s]+)\s+set\s+(?:ip-)?next-hop\s+'?([^'\s]+)'?",
        re.I,
    )
    # BGP config lines that *often* correlate with default-route behavior (still cross-checked against 0.0.0.0/0 routes).
    re_bgp_nbr_af_default_originate = re.compile(
        r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+address-family\s+ipv4-unicast\s+default-originate", re.I
    )
    re_bgp_nbr_af_network = re.compile(
        r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+address-family\s+ipv4-unicast\s+network\s+([^\s]+)", re.I
    )
    re_bgp_af_network = re.compile(r"^set protocols bgp \d+ address-family\s+ipv4-unicast\s+network\s+([^\s]+)", re.I)
    re_bgp_nbr_remote_as = re.compile(
        r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+remote-as\s+'?([^'\s]+)'?",
        re.I,
    )
    re_bgp_nbr_update_source = re.compile(
        r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+update-source\s+'?([^'\s]+)'?",
        re.I,
    )
    re_bgp_nbr_af_prefix_export = re.compile(
        r"^set protocols bgp \d+ neighbor\s+([^\s]+)\s+address-family\s+ipv4-unicast\s+prefix-list\s+export\s+'?([^'\s]+)'?",
        re.I,
    )
    re_pl_prefix = re.compile(
        r"^set policy prefix-list\s+([^\s]+)\s+rule\s+([^\s]+)\s+prefix\s+'?([^'\s]+)'?",
        re.I,
    )
    re_pl_action = re.compile(
        r"^set policy prefix-list\s+([^\s]+)\s+rule\s+([^\s]+)\s+action\s+'?([^'\s]+)'?",
        re.I,
    )
    re_nat_out = re.compile(r"^set nat source rule\s+(\d+)\s+outbound-interface\s+'?([^'\s]+)'?", re.I)
    re_nat_trans = re.compile(r"^set nat source rule\s+(\d+)\s+translation address\s+'?([^'\s]+)'?", re.I)
    re_nat_source = re.compile(r"^set nat source rule\s+(\d+)\s+source address\s+'?([^'\s]+)'?", re.I)
    re_dnat_rule = re.compile(r"^set nat destination rule\s+(\d+)\s+", re.I)
    re_dnat_dst = re.compile(r"^set nat destination rule\s+(\d+)\s+destination address\s+'?([^'\s]+)'?", re.I)
    re_hostname = re.compile(r"^set system host-name\s+'?([^'\s]+)'?", re.I)

    def get_bgp(nbr: str) -> BgpBinding:
        nk = _clean_value(nbr)
        if nk not in bgp_by_neighbor:
            bgp_by_neighbor[nk] = BgpBinding(neighbor=nk, peer_group="")
        return bgp_by_neighbor[nk]

    raw_lines = config_text.splitlines()
    line_consumed: Dict[int, str] = {}

    def consume(line_idx: int, tag: str) -> None:
        line_consumed[line_idx] = tag

    for line_idx, raw in enumerate(raw_lines):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = re_hostname.match(line)
        if m:
            hostname = _clean_value(m.group(1))
            consume(line_idx, "system.host-name")
            continue

        m = re_tunnel_desc.match(line)
        if m:
            kind, name, desc = m.groups()
            node = tunnels.setdefault(name, TunnelNode(name=name, kind=kind.lower()))
            node.description = _clean_value(desc)
            consume(line_idx, "interfaces.tunnel_desc")
            continue
        m = re_tunnel_source.match(line)
        if m:
            kind, name, src = m.groups()
            node = tunnels.setdefault(name, TunnelNode(name=name, kind=kind.lower()))
            node.source = _clean_value(src)
            consume(line_idx, "interfaces.tunnel_source")
            continue
        m = re_tunnel_remote.match(line)
        if m:
            kind, name, remote = m.groups()
            node = tunnels.setdefault(name, TunnelNode(name=name, kind=kind.lower()))
            r_clean = _clean_value(remote)
            node.remote = r_clean
            if kind.lower() == "openvpn":
                openvpn_remote_ips[name] = r_clean
            consume(line_idx, "interfaces.tunnel_remote")
            continue
        m = re_tunnel_addr.match(line)
        if m:
            kind, name, addr = m.groups()
            node = tunnels.setdefault(name, TunnelNode(name=name, kind=kind.lower()))
            node.address = _clean_value(addr)
            consume(line_idx, "interfaces.tunnel_addr")
            continue
        m = re_openvpn_local.match(line)
        if m:
            name, ip, mask = m.groups()
            node = tunnels.setdefault(name, TunnelNode(name=name, kind="openvpn"))
            prefix = mask_to_prefix(_clean_value(mask))
            node.address = f"{_clean_value(ip)}/{prefix}" if prefix else _clean_value(ip)
            openvpn_local_ips[name] = _clean_value(ip)
            consume(line_idx, "interfaces.openvpn_local")
            continue
        m = re_openvpn_remote_addr.match(line)
        if m:
            name, ip = m.groups()
            openvpn_remote_ips[name] = _clean_value(ip)
            node = tunnels.setdefault(name, TunnelNode(name=name, kind="openvpn"))
            node.remote = _clean_value(ip)
            consume(line_idx, "interfaces.openvpn_remote")
            continue
        m = re_vti_desc.match(line)
        if m:
            name, desc = m.groups()
            node = tunnels.setdefault(name, TunnelNode(name=name, kind="vti"))
            node.description = _clean_value(desc)
            consume(line_idx, "interfaces.vti_desc")
            continue
        m = re_vti_addr.match(line)
        if m:
            name, addr = m.groups()
            node = tunnels.setdefault(name, TunnelNode(name=name, kind="vti"))
            node.address = _clean_value(addr)
            consume(line_idx, "interfaces.vti_addr")
            continue
        m = re_ipsec_local_prefix.match(line)
        if m:
            peer, tid, lpfx = m.groups()
            key = (_clean_value(peer), _clean_value(tid))
            ipsec_tunnels_by_key.setdefault(key, {})["local_prefix"] = _clean_value(lpfx)
            consume(line_idx, "vpn.ipsec_local")
            continue
        m = re_ipsec_remote_prefix.match(line)
        if m:
            peer, tid, rpfx = m.groups()
            key = (_clean_value(peer), _clean_value(tid))
            ipsec_tunnels_by_key.setdefault(key, {})["remote_prefix"] = _clean_value(rpfx)
            consume(line_idx, "vpn.ipsec_remote")
            continue
        m = re_iface_addr.match(line)
        if m:
            _, name, addr = m.groups()
            iface_addr_book.setdefault(_clean_value(name), []).append(_clean_value(addr))
            consume(line_idx, "interfaces.address")
            continue
        m = re_iface_desc.match(line)
        if m:
            _, name, desc = m.groups()
            iface_desc_book[_clean_value(name)] = _clean_value(desc)
            consume(line_idx, "interfaces.description")
            continue
        m = re_static_track.match(line)
        if m:
            dst, nh, tr = m.groups()
            r = RouteEdge(
                destination=_clean_value(dst),
                next_hop=_clean_value(nh),
                origin="static",
                track_name=_clean_value(tr),
                evidence=line,
            )
            routes.append(r)
            static_route_index[(r.route_table, r.destination, r.next_hop)] = r
            consume(line_idx, "static.route_track")
            continue
        m = re_static.match(line)
        if m:
            dst, nh = m.groups()
            r = RouteEdge(destination=_clean_value(dst), next_hop=_clean_value(nh), origin="static", evidence=line)
            routes.append(r)
            static_route_index[(r.route_table, r.destination, r.next_hop)] = r
            consume(line_idx, "static.route")
            continue
        m = re_static_table_track.match(line)
        if m:
            table, dst, nh, tr = m.groups()
            r = RouteEdge(
                destination=_clean_value(dst),
                next_hop=_clean_value(nh),
                route_table=_clean_value(table),
                origin="static",
                track_name=_clean_value(tr),
                evidence=line,
            )
            routes.append(r)
            static_route_index[(r.route_table, r.destination, r.next_hop)] = r
            consume(line_idx, "static.table_route_track")
            continue
        m = re_static_table.match(line)
        if m:
            table, dst, nh = m.groups()
            r = RouteEdge(
                destination=_clean_value(dst),
                next_hop=_clean_value(nh),
                route_table=_clean_value(table),
                origin="static",
                evidence=line,
            )
            routes.append(r)
            static_route_index[(r.route_table, r.destination, r.next_hop)] = r
            consume(line_idx, "static.table_route")
            continue
        m = re_static_pref.match(line)
        if m:
            dst, nh, pref = m.groups()
            key = ("main", _clean_value(dst), _clean_value(nh))
            if key in static_route_index:
                static_route_index[key].preference = _clean_value(pref)
            consume(line_idx, "static.route_pref")
            continue
        m = re_static_table_pref.match(line)
        if m:
            table, dst, nh, pref = m.groups()
            key = (_clean_value(table), _clean_value(dst), _clean_value(nh))
            if key in static_route_index:
                static_route_index[key].preference = _clean_value(pref)
            consume(line_idx, "static.table_route_pref")
            continue
        m = re_local_src.match(line)
        if m:
            rid, source = m.groups()
            p = local_route_by_rule.setdefault(rid, PolicyRule(policy_name="local-route", rule_id=rid))
            p.source = _clean_value(source)
            p.evidence.append(line)
            consume(line_idx, "policy.local-route")
            continue
        m = re_local_table.match(line)
        if m:
            rid, table = m.groups()
            p = local_route_by_rule.setdefault(rid, PolicyRule(policy_name="local-route", rule_id=rid))
            p.table = _clean_value(table)
            p.policy_type = "source-ip"
            p.evidence.append(line)
            consume(line_idx, "policy.local-route")
            continue
        m = re_pol_dest.match(line)
        if m:
            pname, rid, dgroup = m.groups()
            key = f"{pname}:{rid}"
            p = policy_route_by_name.setdefault(key, PolicyRule(policy_name=pname, rule_id=rid))
            p.destination_group = _clean_value(dgroup)
            p.evidence.append(line)
            consume(line_idx, "policy.route")
            continue
        m = re_pol_src.match(line)
        if m:
            pname, rid, source = m.groups()
            key = f"{pname}:{rid}"
            p = policy_route_by_name.setdefault(key, PolicyRule(policy_name=pname, rule_id=rid))
            p.source = _clean_value(source)
            p.evidence.append(line)
            consume(line_idx, "policy.route")
            continue
        m = re_pol_table.match(line)
        if m:
            pname, rid, table = m.groups()
            key = f"{pname}:{rid}"
            p = policy_route_by_name.setdefault(key, PolicyRule(policy_name=pname, rule_id=rid))
            p.table = _clean_value(table)
            p.evidence.append(line)
            consume(line_idx, "policy.route")
            continue
        m = re_if_pol.match(line)
        if m:
            eth, pname = m.groups()
            interface_policy_bind.setdefault(_clean_value(pname), []).append(_clean_value(eth))
            consume(line_idx, "interfaces.policy-route")
            continue
        m = re_pl_prefix.match(line)
        if m:
            pln, rid, pfx = m.groups()
            pln, rid, pfx = _clean_value(pln), _clean_value(rid), _clean_value(pfx)
            prefix_list_rules.setdefault(pln, {}).setdefault(rid, {})["prefix"] = pfx
            consume(line_idx, "policy.prefix-list")
            continue
        m = re_pl_action.match(line)
        if m:
            pln, rid, act = m.groups()
            pln, rid, act = _clean_value(pln), _clean_value(rid), _clean_value(act)
            prefix_list_rules.setdefault(pln, {}).setdefault(rid, {})["action"] = act
            consume(line_idx, "policy.prefix-list")
            continue
        m = re_bgp_neighbor.match(line)
        if m:
            n, pg = m.groups()
            get_bgp(n).peer_group = _clean_value(pg)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_update.match(line)
        if m:
            pg, src = m.groups()
            peer_group_update_source[_clean_value(pg)] = _clean_value(src)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_nbr_remote_as.match(line)
        if m:
            n, ra = m.groups()
            get_bgp(n).remote_as = _clean_value(ra)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_nbr_update_source.match(line)
        if m:
            n, src = m.groups()
            get_bgp(n).update_source = _clean_value(src)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_nbr_af_prefix_export.match(line)
        if m:
            n, plname = m.groups()
            get_bgp(n).export_prefix_list = _clean_value(plname)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_neighbor_route_map.match(line)
        if m:
            nbr, rm = m.groups()
            bgp_neighbor_in_routemap[_clean_value(nbr)] = _clean_value(rm)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_neighbor_af_route_map.match(line)
        if m:
            nbr, rm = m.groups()
            bgp_neighbor_in_routemap[_clean_value(nbr)] = _clean_value(rm)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_peer_group_af_route_map.match(line)
        if m:
            pg, rm = m.groups()
            bgp_peer_group_in_routemap[_clean_value(pg)] = _clean_value(rm)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_peer_group_remote_as.match(line)
        if m:
            pg, ra = m.groups()
            peer_group_remote_as[_clean_value(pg)] = _clean_value(ra)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_peer_group_af_prefix_export.match(line)
        if m:
            pg, pln = m.groups()
            peer_group_export_prefix[_clean_value(pg)] = _clean_value(pln)
            consume(line_idx, "protocols.bgp")
            continue
        m = re_rm_match_community.match(line)
        if m:
            rm, rid, ctxt = m.groups()
            ctx_clean = _clean_value(ctxt)
            has80 = bool(re.search(r"(?<!\d)80(?!\d)", ctx_clean))
            if has80:
                route_map_rule_match80[(_clean_value(rm), _clean_value(rid))] = True
            else:
                # Keep community reference name for second-pass resolution via community-list definitions.
                mref = re.search(r"community-list\s+'?([^'\s]+)'?", ctx_clean, re.I)
                if mref:
                    route_map_rule_comm_ref[(_clean_value(rm), _clean_value(rid))] = _clean_value(mref.group(1))
                else:
                    parts = [p for p in re.split(r"[\s,]+", ctx_clean) if p]
                    if parts:
                        route_map_rule_comm_ref[(_clean_value(rm), _clean_value(rid))] = parts[-1]
            consume(line_idx, "policy.route-map")
            continue
        m = re_rm_set_next_hop.match(line)
        if m:
            rm, rid, nh = m.groups()
            route_map_rule_next_hop[(_clean_value(rm), _clean_value(rid))] = _clean_value(nh)
            consume(line_idx, "policy.route-map")
            continue
        m = re_bgp_nbr_af_default_originate.match(line)
        if m:
            n = _clean_value(m.group(1))
            routes.append(RouteEdge(destination="0.0.0.0/0", next_hop=n, origin="bgp-config", evidence=line))
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_nbr_af_network.match(line)
        if m:
            n, net = m.groups()
            routes.append(RouteEdge(destination=_clean_value(net), next_hop=_clean_value(n), origin="bgp-config", evidence=line))
            consume(line_idx, "protocols.bgp")
            continue
        m = re_bgp_af_network.match(line)
        if m:
            net = _clean_value(m.group(1))
            routes.append(RouteEdge(destination=net, next_hop="", origin="bgp-config", evidence=line))
            consume(line_idx, "protocols.bgp")
            continue
        m = re_nat_out.match(line)
        if m:
            rid, outbound = m.groups()
            nat_rule_outbound[_clean_value(rid)] = _clean_value(outbound)
            nat_outbounds.append(_clean_value(outbound))
            consume(line_idx, "nat.source")
            continue
        m = re_nat_trans.match(line)
        if m:
            rid, ip = m.groups()
            nat_rule_translation[_clean_value(rid)] = _clean_value(ip).split("/")[0]
            consume(line_idx, "nat.source")
            continue
        m = re_nat_source.match(line)
        if m:
            rid, src = m.groups()
            nat_rule_sources.setdefault(_clean_value(rid), []).append(_clean_value(src))
            consume(line_idx, "nat.source")
            continue
        m = re_dnat_rule.match(line)
        if m:
            dnat_rule_count += 1
            consume(line_idx, "nat.destination")
            continue
        m = re_dnat_dst.match(line)
        if m:
            rid, pfx = m.groups()
            dnat_rule_prefixes.setdefault(_clean_value(rid), []).append(_clean_value(pfx))
            consume(line_idx, "nat.destination")
            continue

        if line.lower().startswith("set "):
            consume(line_idx, "unparsed_set")

    bgp_bindings = sorted(bgp_by_neighbor.values(), key=lambda b: b.neighbor)

    dev_ip_to_iface: Dict[str, str] = {}
    for iname, addrs in iface_addr_book.items():
        for a in addrs:
            hip = _host_ip_from_pfx_or_addr(_clean_value(a))
            if hip:
                dev_ip_to_iface[hip] = iname

    def collect_prefix_list_permits(pln: str) -> List[str]:
        rules = prefix_list_rules.get(pln, {})
        out: List[str] = []

        def rid_key(rid: str) -> Tuple[int, str]:
            try:
                return (int(rid), rid)
            except ValueError:
                return (10**9, rid)

        for rid in sorted(rules.keys(), key=rid_key):
            meta = rules[rid]
            if meta.get("action", "").lower() != "permit":
                continue
            pfx = (meta.get("prefix") or "").strip()
            if pfx:
                out.append(pfx)
        return out

    for b in bgp_bindings:
        if not b.update_source and b.peer_group:
            b.update_source = peer_group_update_source.get(b.peer_group, "")
        if not b.remote_as and b.peer_group:
            ra_pg = peer_group_remote_as.get(b.peer_group, "")
            if ra_pg:
                b.remote_as = ra_pg
        if not b.export_prefix_list and b.peer_group:
            pl_pg = peer_group_export_prefix.get(b.peer_group, "")
            if pl_pg:
                b.export_prefix_list = pl_pg
        en = (b.export_prefix_list or "").strip()
        if en:
            b.advertised_prefixes = collect_prefix_list_permits(en)

    bgp_anchor_iface_set: set[str] = set()
    for b in bgp_bindings:
        us0 = (b.update_source or "").strip()
        if us0 and us0 in dev_ip_to_iface:
            bgp_anchor_iface_set.add(dev_ip_to_iface[us0])

    # Second pass: route-map may match a named community-list instead of literal "80".
    full_text = "\n".join([ln.strip() for ln in config_text.splitlines() if ln.strip()])
    for key, cref in route_map_rule_comm_ref.items():
        if key in route_map_rule_match80:
            continue
        if re.search(rf"community-list\s+'?{re.escape(cref)}'?.*?(?<!\d)80(?!\d)", full_text, re.I):
            route_map_rule_match80[key] = True

    # local-route only controls local generated traffic. It is not customer PBR.
    for p in policy_route_by_name.values():
        if p.destination_group and p.source:
            p.policy_type = "domain+source-ip"
        elif p.destination_group:
            p.policy_type = "destination-group"
        elif p.source:
            p.policy_type = "source-ip"
        else:
            p.policy_type = "unknown"
        p.interface = ",".join(sorted(set(interface_policy_bind.get(p.policy_name, []))))
        policies.append(p)

    ipsec_local_hosts: set[str] = set()
    for meta in ipsec_tunnels_by_key.values():
        lp = (meta.get("local_prefix") or "").strip()
        hip = _host_ip_from_pfx_or_addr(lp)
        if hip:
            ipsec_local_hosts.add(hip)

    for iname, addrs in iface_addr_book.items():
        for a in addrs:
            host_ip = _host_ip_from_pfx_or_addr(a)
            if not host_ip or host_ip not in ipsec_local_hosts:
                continue
            extras: List[str] = []
            for (peer, tid), m in sorted(ipsec_tunnels_by_key.items()):
                lp0 = (m.get("local_prefix") or "").strip()
                if not lp0 or _host_ip_from_pfx_or_addr(lp0) != host_ip:
                    continue
                rp = (m.get("remote_prefix") or "").strip()
                extras.append(f"{peer} tun{tid} L={lp0}" + (f" R={rp}" if rp else ""))
            desc_extra = IPSEC_TS_DESC_MARK + " " + "; ".join(extras[:8])
            if len(extras) > 8:
                desc_extra += " …"
            a_clean = _clean_value(a).strip()
            try:
                addr_norm = str(ipaddress.ip_interface(a_clean if "/" in a_clean else f"{a_clean}/32"))
            except Exception:
                addr_norm = f"{host_ip}/32"
            kind_g = (
                "dummy"
                if "dum" in iname.lower()
                else ("loopback" if iname.lower().startswith("lo") else "ethernet")
            )
            node = tunnels.setdefault(iname, TunnelNode(name=iname, kind=kind_g))
            if not (node.address or "").strip():
                node.address = addr_norm
            desc0 = (node.description or "").strip()
            node.description = f"{desc0} | {desc_extra}".strip(" |")[:500] if desc0 else desc_extra[:500]

    for ifn in sorted(bgp_anchor_iface_set):
        if ifn in tunnels:
            continue
        addrs = iface_addr_book.get(ifn, [])
        if not addrs:
            continue
        match_addr = _clean_value(addrs[0])
        for b in bgp_bindings:
            us_bind = (b.update_source or "").strip()
            if us_bind and dev_ip_to_iface.get(us_bind) == ifn:
                for a in addrs:
                    if _host_ip_from_pfx_or_addr(_clean_value(a)) == us_bind:
                        match_addr = _clean_value(a)
                        break
        try:
            ma = match_addr.strip()
            addr_norm = str(ipaddress.ip_interface(ma if "/" in ma else f"{ma}/32"))
        except Exception:
            addr_norm = match_addr
        kind_g = (
            "loopback"
            if ifn.lower().startswith("lo")
            else (
                "dummy"
                if "dum" in ifn.lower()
                else ("bridge" if ifn.lower().startswith("br") else "ethernet")
            )
        )
        desc_iface = iface_desc_book.get(ifn, "")
        tunnels[ifn] = TunnelNode(
            name=ifn,
            kind=kind_g,
            address=addr_norm,
            description=(desc_iface + " (BGP update-source)").strip(),
        )

    transport_underlay_ips = {n.source for n in tunnels.values() if n.kind == "openvpn" and n.source}
    transport_underlay_ips.update(openvpn_local_ips.values())
    transport_underlay_ips.update(ipsec_local_hosts)
    for n in tunnels.values():
        if n.kind != "vti":
            continue
        lip = _local_ip_from_cidr(n.address or "")
        if lip:
            transport_underlay_ips.add(lip)
    for node in tunnels.values():
        name_l = node.name.lower()
        desc_l = node.description.lower()
        remote_l = node.remote.lower()

        # Strong business rule:
        # - vtun/acvpn/ipsecgw => openvpn access layer
        # - VyOS route-based IPsec: interfaces vti ... => ipsec-vti (same domestic-GRE underlay role as vtun)
        # - upe => domestic GRE
        # - natpe => overseas GRE
        if node.kind == "openvpn" or name_l.startswith("vtun"):
            node.inferred_role = "openvpn"
            node.side = _infer_side(node.name, node.description, node.remote)
            node.canvas_side = _canvas_side_evidence(
                node.description, iface_desc_book.get(node.name, ""), node.remote
            )
            continue
        if node.kind == "vti":
            node.inferred_role = "ipsec-vti"
            node.side = _infer_side(node.name, node.description, node.remote or node.address)
            node.canvas_side = _canvas_side_evidence(
                node.description, iface_desc_book.get(node.name, ""), node.remote or node.address
            )
            continue
        if node.kind in ("dummy", "ethernet", "loopback") and IPSEC_TS_DESC_MARK in (node.description or ""):
            node.inferred_role = "ipsec-policy"
            node.side = _infer_side(node.name, node.description, "")
            node.canvas_side = _canvas_side_evidence(node.description, iface_desc_book.get(node.name, ""), "")
            continue
        if node.name in bgp_anchor_iface_set and node.kind in ("loopback", "ethernet", "dummy", "bridge"):
            node.inferred_role = "local-iface"
            node.side = _infer_side(node.name, iface_desc_book.get(node.name, ""), "")
            node.canvas_side = _canvas_side_evidence(iface_desc_book.get(node.name, ""), "", "")
            continue

        if node.kind == "tunnel":
            node.inferred_role = "gre-unknown"
            node.evidence = []
            node.side = _infer_side(node.name, node.description, node.remote)
            node.canvas_side = _canvas_side_evidence(
                node.description, iface_desc_book.get(node.name, ""), node.remote
            )

    tunnel_peer_ip_index: Dict[str, str] = {}
    for name, node in tunnels.items():
        peer = _peer_ip_from_cidr(node.address)
        if peer:
            tunnel_peer_ip_index[peer] = name
        if node.remote:
            tunnel_peer_ip_index[node.remote] = name

    def _route_pref(r: RouteEdge) -> int:
        return int(r.preference) if r.preference.isdigit() else 100

    def _route_contains_ip(r: RouteEdge, ip: str) -> bool:
        try:
            net = ipaddress.ip_network(r.destination, strict=False)
            return ipaddress.ip_address(ip) in net
        except Exception:
            return False

    def _resolve_next_hop_chain(
        ip: str,
        table_hint: str,
        depth: int = 0,
        seen: Optional[set[str]] = None,
    ) -> Tuple[str, List[str], bool]:
        # returns (final_tunnel, hop_trace, depth_exceeded)
        if seen is None:
            seen = set()
        if depth >= 3:
            return "", [ip], True
        if ip in seen:
            return "", [ip], False
        seen.add(ip)

        if ip in tunnel_peer_ip_index:
            return tunnel_peer_ip_index[ip], [ip], False

        cands = [r for r in routes if r.origin != "bgp-config" and r.destination != "0.0.0.0/0" and _route_contains_ip(r, ip)]
        if not cands:
            return "", [ip], False

        def _table_score(r: RouteEdge) -> int:
            if table_hint and r.route_table == table_hint:
                return 0
            if r.route_table == "main":
                return 1
            return 2

        def _prefix_len(r: RouteEdge) -> int:
            try:
                return ipaddress.ip_network(r.destination, strict=False).prefixlen
            except Exception:
                return 0

        cands = sorted(cands, key=lambda r: (_table_score(r), _route_pref(r), -_prefix_len(r)))
        for r in cands:
            if r.next_hop in tunnel_peer_ip_index:
                return tunnel_peer_ip_index[r.next_hop], [ip, r.next_hop], False
            tun, chain, over = _resolve_next_hop_chain(r.next_hop, r.route_table, depth + 1, seen.copy())
            if tun:
                return tun, [ip] + chain, over
            if over:
                return "", [ip] + chain, True
        return "", [ip], False

    route_depth_exceeded: List[str] = []
    for r in routes:
        # These are configuration hints, not necessarily FIB next-hops on this box.
        if r.origin == "bgp-config":
            continue
        if r.next_hop in tunnel_peer_ip_index:
            r.via_tunnel = tunnel_peer_ip_index[r.next_hop]
        elif r.next_hop:
            tun, chain, over = _resolve_next_hop_chain(r.next_hop, r.route_table)
            if tun:
                r.via_tunnel = tun
                r.evidence = f"{r.evidence} | recursive:{'->'.join(chain)}"
            elif over:
                route_depth_exceeded.append(f"table={r.route_table} {r.destination} via {'->'.join(chain)}")

    # Route-driven inference for unannotated tunnels:
    # 1) GRE-UPE requires BOTH:
    #    - route <tunnel.remote>/32 next-hop points to openvpn remote-address
    #    - source-address is anchored to access underlay local IP
    # This prevents overseas NATPE (public source-address) from being misclassified as UPE.
    access_ip_index = _access_ip_to_tunnel_name(tunnels, openvpn_local_ips)
    ovpn_remote_set = set(openvpn_remote_ips.values())
    for node in tunnels.values():
        if node.inferred_role != "gre-unknown" or not node.remote:
            continue
        src0 = (node.source or "").strip()
        src_is_access_local = bool(src0 and (src0 in access_ip_index or src0 in transport_underlay_ips))
        # Only skip when there IS a source-address that is NOT access-local
        # (could be overseas NATPE with public source). Allow route evidence
        # when no source-address is configured at all.
        if not src_is_access_local and src0:
            continue
        for r in routes:
            if r.destination.startswith(f"{node.remote}/32") and r.next_hop in ovpn_remote_set:
                node.inferred_role = "gre-upe"
                node.evidence.append("route(remote/32)->next-hop 命中 openvpn remote-address")
                break

    nat_iface_set = set(nat_outbounds)

    for node in tunnels.values():
        if node.kind != "tunnel" or node.inferred_role != "gre-unknown":
            continue
        if node.name in nat_iface_set:
            node.inferred_role = "gre-overseas"
            node.evidence.append("NAT source rule outbound-interface 引用本隧道名")

    for node in tunnels.values():
        if node.kind != "tunnel" or node.inferred_role != "gre-unknown":
            continue
        ok, ev = _tunnel_source_strong_underlay(node.source, access_ip_index, transport_underlay_ips)
        if ok:
            node.inferred_role = "gre-upe"
            node.evidence.append(ev)

    # 2) if route <tunnel.remote>/32 next-hop points to a gre-upe peer, mark as overseas (after NAT/source UPE).
    upe_peers = {_peer_ip_from_cidr(n.address) for n in tunnels.values() if n.inferred_role == "gre-upe" and n.address}
    upe_peers = {p for p in upe_peers if p}
    for node in tunnels.values():
        if node.inferred_role != "gre-unknown" or not node.remote:
            continue
        for r in routes:
            if r.destination.startswith(f"{node.remote}/32") and r.next_hop in upe_peers:
                node.inferred_role = "gre-overseas"
                node.evidence.append("route(remote/32)->next-hop 命中 UPE 对端IP")
                break

    remark_conflicts: List[RemarkConflict] = []
    gre_read_partial: List[str] = []

    def _basis_from_evidence(evs: List[str]) -> str:
        s = " ".join(evs)
        if "route(remote/32)" in s or "命中 openvpn" in s:
            return "route"
        if "NAT source" in s or "outbound" in s:
            return "nat_outbound"
        if "绑定接入层" in s or "underlay IP" in s:
            return "source_ip"
        return "merged"

    for node in tunnels.values():
        if node.kind != "tunnel":
            continue
        remark_role = _remark_gre_role_from_desc(node.description)
        desc_ref = f"interfaces tunnel {node.name} description '{(node.description or '')[:160]}'"
        if node.inferred_role == "gre-unknown":
            sl = (node.source or "").lower()
            if ("vtun" in sl or "vti" in sl) and (node.source or "").strip():
                gre_read_partial.append(
                    f"{node.name}: source-address 含 vtun/vti 字样但未绑定到接入层接口 IP（当前值: {node.source}）"
                )
            if remark_role and accept_remark_heuristic:
                node.inferred_role = remark_role
                node.evidence.append("interfaces description 备注启发（已勾选「接受备注启发」）")
        if remark_role in ("gre-upe", "gre-overseas") and node.inferred_role in ("gre-upe", "gre-overseas"):
            if remark_role != node.inferred_role:
                remark_conflicts.append(
                    RemarkConflict(
                        tunnel=node.name,
                        remark_hint=remark_role,
                        resolved_role=node.inferred_role,
                        strong_basis=_basis_from_evidence(node.evidence),
                        reference=desc_ref,
                    )
                )

    # Build explicit vtun -> gre-upe links（仅配置/地址证据，不用侧别启发）.
    vtun_to_upe: List[Tuple[str, str]] = []
    access_transport_nodes = [n for n in tunnels.values() if n.inferred_role in ACCESS_TRANSPORT_ROLES]
    upe_nodes = [n for n in tunnels.values() if n.inferred_role == "gre-upe"]
    for upe in upe_nodes:
        linked = None
        for vt in access_transport_nodes:
            if vt.address and upe.source and vt.address in upe.source:
                linked = vt
                break
            vt_lip = _local_ip_from_cidr(vt.address or "")
            if vt_lip and vt_lip in (upe.source or ""):
                linked = vt
                break
            if vt.name in (upe.source or "") or (upe.source and upe.source in vt.name):
                linked = vt
                break
        if linked:
            vtun_to_upe.append((linked.name, upe.name))

    # UPE「主/备线」线索：与已绑定接入层一致（接入未标主/备则 UPE 亦 unknown，由 topology_line_side_for_node 再判）。
    for vt_name, upe_name in vtun_to_upe:
        vt_n = tunnels.get(vt_name)
        un_n = tunnels.get(upe_name)
        if not vt_n or not un_n or getattr(un_n, "inferred_role", "") != "gre-upe":
            continue
        vt_cs = (getattr(vt_n, "canvas_side", "") or "").strip()
        if vt_cs not in ("main", "backup"):
            continue
        u_cs = (getattr(un_n, "canvas_side", "") or "").strip()
        if u_cs not in ("main", "backup"):
            un_n.canvas_side = vt_cs
        elif u_cs != vt_cs:
            un_n.canvas_side = "unknown"

    # Source/destination driven parent inference for overseas GRE:
    # - source-address anchored to vtun/upe local IP indicates transport parent
    # - route(remote/32) next-hop can also indicate parent
    # - direct host GRE is only accepted when source-address equals a public WAN IP
    uplink_public_ips: set[str] = set()
    loop_dummy_public_ips: set[str] = set()
    for iname, addrs in iface_addr_book.items():
        idesc = iface_desc_book.get(iname, "").lower()
        if "wan" not in idesc and not iname.lower().startswith("eth"):
            # Keep collecting loopback/dummy public addresses for vtun->natpe direct mode evidence.
            pass
        for a in addrs:
            ip = a.split("/")[0]
            try:
                ipa = ipaddress.ip_address(ip)
            except Exception:
                continue
            if not ipa.is_private:
                if "wan" in idesc or iname.lower().startswith("eth"):
                    uplink_public_ips.add(ip)
                if iname.lower().startswith("dum") or iname.lower().startswith("lo"):
                    loop_dummy_public_ips.add(ip)

    overseas_parent: Dict[str, str] = {}
    ovpn_ip_to_name: Dict[str, str] = {}
    upe_ip_to_name: Dict[str, str] = {}
    local_ip_to_iface_name: Dict[str, str] = {}
    for n in tunnels.values():
        if n.kind in ("openvpn", "vti") or n.inferred_role in ACCESS_TRANSPORT_ROLES:
            ip = _local_ip_from_cidr(n.address)
            if ip:
                ovpn_ip_to_name[ip] = n.name
        if n.inferred_role == "gre-upe":
            ip = _local_ip_from_cidr(n.address)
            if ip:
                upe_ip_to_name[ip] = n.name
    for iname, addrs in iface_addr_book.items():
        for a in addrs:
            ip_loc = _local_ip_from_cidr(str(a))
            if ip_loc:
                local_ip_to_iface_name[ip_loc] = iname

    # NAT translation evidence: source loopback IP may be translated out via a tunnel/openvpn interface.
    nat_translation_to_tunnel: Dict[str, List[str]] = {}
    for rid, tr_ip in nat_rule_translation.items():
        out_if = (nat_rule_outbound.get(rid, "") or "").strip()
        if not out_if or out_if not in tunnels:
            continue
        out_node = tunnels.get(out_if)
        if not out_node:
            continue
        if out_node.inferred_role not in ACCESS_TRANSPORT_ROLES and out_node.inferred_role not in ("gre-upe", "gre-overseas"):
            continue
        ip0 = (tr_ip or "").strip()
        if not ip0:
            continue
        nat_translation_to_tunnel.setdefault(ip0, []).append(out_if)
    for k in list(nat_translation_to_tunnel.keys()):
        nat_translation_to_tunnel[k] = sorted(set(nat_translation_to_tunnel[k]))

    def _node_side_hint_by_remark(node_name: str) -> str:
        n0 = tunnels.get(node_name)
        if not n0:
            return "unknown"
        exd = iface_desc_book.get(node_name, "") if isinstance(iface_desc_book, dict) else ""
        if _line_remark_is_backup(n0.description or "", exd, n0.name or ""):
            return "backup"
        if _line_remark_is_main(n0.description or "", exd, n0.name or ""):
            return "main"
        return "unknown"

    # Connected prefixes on local interfaces (strict config evidence).
    connected_if_nets: List[ipaddress._BaseNetwork] = []
    physical_if_nets: List[ipaddress._BaseNetwork] = []
    local_public_ips: set[str] = set()
    for _iname, addrs in iface_addr_book.items():
        is_physical = _iname.lower().startswith("eth")
        for a in addrs:
            ip0 = str(a).split("/")[0].strip()
            try:
                ipa0 = ipaddress.ip_address(ip0)
                if not ipa0.is_private:
                    local_public_ips.add(ip0)
            except Exception:
                pass
            try:
                nw = ipaddress.ip_network(str(a).strip(), strict=False)
            except Exception:
                continue
            connected_if_nets.append(nw)
            if is_physical:
                physical_if_nets.append(nw)

    def _is_direct_next_hop(ip: str) -> bool:
        try:
            ipa = ipaddress.ip_address(ip)
        except Exception:
            return False
        for nw in connected_if_nets:
            try:
                if ipa in nw:
                    return True
            except Exception:
                continue
        return False

    def _best_main_route_for_ip(ip: str) -> Optional[RouteEdge]:
        cands = [r for r in routes if r.origin != "bgp-config" and r.route_table == "main" and _route_contains_ip(r, ip)]
        if not cands:
            return None

        def _prefix_len(r: RouteEdge) -> int:
            try:
                return ipaddress.ip_network(r.destination, strict=False).prefixlen
            except Exception:
                return 0

        cands = sorted(cands, key=lambda r: (_route_pref(r), -_prefix_len(r)))
        return cands[0]

    def _is_host_direct_by_user_rule(remote_ip: str) -> bool:
        # Rule-1: tunnel remote and local physical interface IP are in same /30 network.
        try:
            rip = ipaddress.ip_address(remote_ip)
        except Exception:
            return False
        for nw in physical_if_nets:
            try:
                if nw.prefixlen == 30 and rip in nw:
                    return True
            except Exception:
                continue

        # Rule-2: local has public IP, remote is public, and remote is reachable via local default route.
        if rip.is_private or not local_public_ips:
            return False
        br = _best_main_route_for_ip(remote_ip)
        if not br:
            return False
        if br.destination != "0.0.0.0/0":
            return False
        if (br.via_tunnel or "").strip():
            return False
        return True

    def _next_hop_on_ethernet_segment(nh: str) -> bool:
        """下一跳 IP 落在某个 ethernet 接口地址所在网段内（配置证据，用于专线侧 /32 静态路由）。"""
        nh = (nh or "").strip()
        if not nh:
            return False
        try:
            nh_ip = ipaddress.ip_address(nh)
        except Exception:
            return False
        for ifn, addrs in iface_addr_book.items():
            if not str(ifn).lower().startswith("eth"):
                continue
            for a in addrs:
                try:
                    nw = ipaddress.ip_network(str(a).strip(), strict=False)
                except Exception:
                    continue
                try:
                    if nh_ip in nw:
                        return True
                except Exception:
                    continue
        return False

    def _remote32_static_egress_via_eth_only(remote_ip: str) -> bool:
        """存在 set protocols static route <remote>/32 ... next-hop <nh>，且所有该目的地的静态路由均无 via_tunnel，
        且至少一条的 next-hop 落在 eth* 接口直连网段（典型：专线对端或运营商网关）。"""
        rip = (remote_ip or "").strip()
        if not rip:
            return False
        dst = f"{rip}/32"
        cands = [
            r
            for r in routes
            if r.origin != "bgp-config" and str(r.destination or "").strip() == dst
        ]
        if not cands:
            return False
        if any((r.via_tunnel or "").strip() for r in cands):
            return False
        for r in cands:
            nh = (r.next_hop or "").strip()
            if nh and _next_hop_on_ethernet_segment(nh):
                return True
        return False

    for n in tunnels.values():
        if n.inferred_role != "gre-overseas":
            continue
        parent = ""
        src_ip = n.source
        if src_ip in ovpn_ip_to_name:
            parent = ovpn_ip_to_name[src_ip]
        elif src_ip in upe_ip_to_name:
            parent = upe_ip_to_name[src_ip]
        else:
            src_iface = local_ip_to_iface_name.get(src_ip, "")
            if src_iface.lower().startswith("lo"):
                # Rule: source is loopback IP -> must resolve via NAT translation to concrete vtun/tun egress.
                cand = nat_translation_to_tunnel.get(src_ip, [])
                if len(cand) == 1:
                    parent = cand[0]
                elif len(cand) > 1:
                    n_side = _node_side_hint_by_remark(n.name)
                    side_matched = [
                        cn for cn in cand if _node_side_hint_by_remark(cn) == n_side and n_side in ("main", "backup")
                    ]
                    if len(side_matched) == 1:
                        parent = side_matched[0]
            # source on physical/local non-loopback interface: keep unresolved here,
            # and only accept host-direct by explicit direct-connect rules below.
        if not parent and n.remote:
            for r in routes:
                if not r.destination.startswith(f"{n.remote}/32"):
                    continue
                vt = (r.via_tunnel or "").strip()
                if not vt:
                    continue
                if vt == n.name:
                    continue
                parent = vt
                break
        has_nat_access_evidence = bool(src_ip and nat_translation_to_tunnel.get(src_ip, []))
        # Host-direct is accepted ONLY by explicit user rules.
        # If source-address is already evidenced as NAT translation for access transport,
        # never downgrade to host-direct; keep strict transport-parent inference only.
        if not parent and not has_nat_access_evidence and n.remote:
            if _is_host_direct_by_user_rule(n.remote):
                parent = "host"
            elif _remote32_static_egress_via_eth_only(n.remote):
                parent = "host"
                n.evidence.append("route(remote/32)->next-hop 落在 eth* 直连网段且无 via_tunnel（专线/以太侧静态路由证据）")
        # Evidence-based direct-vtun mode（无「同侧 vtun 二选一」启发；仅唯一接入层时绑定）.
        if not parent and src_ip and src_ip in loop_dummy_public_ips:
            vt_nodes = [t for t in tunnels.values() if t.inferred_role in ACCESS_TRANSPORT_ROLES]
            if len(vt_nodes) == 1:
                parent = vt_nodes[0].name
        overseas_parent[n.name] = parent

    # Chain-first side selection is computed after BGP/route binding is ready.

    for b in bgp_bindings:
        for r in routes:
            if r.origin == "bgp-config":
                continue
            if not r.destination.startswith(f"{b.neighbor}/"):
                continue
            if r.via_tunnel:
                b.transport_tunnel = r.via_tunnel
                break

    overseas_tunnels = [n.name for n in tunnels.values() if n.inferred_role == "gre-overseas"]
    default_targets: List[Tuple[str, str, List[str]]] = []  # (label, final_tunnel, nh_ip_chain)
    default_route_resolution: Optional[Dict[str, object]] = None

    policy_targets: List[Tuple[str, str, str]] = []
    table_to_tunnel = {}
    for r in routes:
        if r.destination != "0.0.0.0/0" or not r.via_tunnel or r.origin == "bgp-config":
            continue
        if r.route_table not in table_to_tunnel:
            table_to_tunnel[r.route_table] = r.via_tunnel
    for p in policies:
        if not p.table:
            continue
        tun = table_to_tunnel.get(p.table, "")
        if tun:
            iface_hint = f"@{p.interface}" if p.interface else ""
            pname = f"{p.policy_name}{iface_hint}:{p.rule_id}"
            policy_targets.append((pname, p.policy_type, tun))
        elif p.table:
            # If policy table does not resolve to a tunnel after recursive lookup, keep as unresolved.
            p.evidence.append("table未解析到最终出口")

    policy_local_targets: List[Tuple[str, str, str]] = []

    def _route_pref2(x: RouteEdge) -> int:
        return int(x.preference) if (x.preference or "").isdigit() else 999999

    for p in policies:
        if not p.table:
            continue
        if table_to_tunnel.get(p.table, ""):
            continue
        r0s = [
            r
            for r in routes
            if r.route_table == p.table and r.destination == "0.0.0.0/0" and r.origin != "bgp-config"
        ]
        if not r0s:
            continue
        r0 = sorted(r0s, key=_route_pref2)[0]
        tun2, ch, _ov = _resolve_next_hop_chain(r0.next_hop, p.table)
        if tun2:
            continue
        last_ip = (ch[-1] if ch else r0.next_hop).strip()
        gw_iface = dev_ip_to_iface.get(r0.next_hop, "") or dev_ip_to_iface.get(last_ip, "")
        iface_hint = gw_iface or "本地"
        iface_part = f"@{p.interface}" if p.interface else ""
        pname = f"{p.policy_name}{iface_part}:{p.rule_id}"
        brief = f"table {p.table} default nh={r0.next_hop}"
        if ch:
            brief += " chain:" + "->".join(ch[:6])
            if len(ch) > 6:
                brief += "..."
        policy_local_targets.append((pname, iface_hint, brief))

    update_source_to_tunnel: Dict[str, str] = {}
    for rid, trans_ip in nat_rule_translation.items():
        out = nat_rule_outbound.get(rid, "")
        if out and trans_ip and trans_ip.lower() != "masquerade":
            update_source_to_tunnel[trans_ip] = out

    tunnel_local_ip_index: Dict[str, str] = {}
    for tname, tnode in tunnels.items():
        lip = _local_ip_from_cidr(tnode.address or "")
        if lip:
            tunnel_local_ip_index[lip] = tname

    # For each import route-map, pick a deterministic next-hop rule (smallest numeric rule id).
    route_map_any_next_hop: Dict[str, str] = {}
    route_map_any_next_hop_rank: Dict[str, int] = {}
    for (rm, rid), nh in route_map_rule_next_hop.items():
        rm0 = (rm or "").strip()
        rid0 = (rid or "").strip()
        nh0 = (nh or "").strip()
        if not rm0 or not nh0:
            continue
        try:
            rank = int(rid0)
        except Exception:
            rank = 10**9
        prev_rank = route_map_any_next_hop_rank.get(rm0)
        if prev_rank is None or rank < prev_rank:
            route_map_any_next_hop_rank[rm0] = rank
            route_map_any_next_hop[rm0] = nh0

    for b in bgp_bindings:
        # Strict evidence priority:
        # 1) BGP import route-map set ip-next-hop -> resolve to local tunnel
        # 2) update-source bound local iface / NAT translation / tunnel local IP
        rm = bgp_neighbor_in_routemap.get(b.neighbor, "") or bgp_peer_group_in_routemap.get(b.peer_group, "")
        nh_rm = (route_map_any_next_hop.get(rm, "") or "").strip() if rm else ""
        if nh_rm:
            t_rm = tunnel_peer_ip_index.get(nh_rm, "")
            if not t_rm:
                t_rm, _ch_rm, _ov_rm = _resolve_next_hop_chain(nh_rm, "main")
            if t_rm:
                b.egress_hint = t_rm
                continue
        us = (b.update_source or "").strip()
        if us and us in dev_ip_to_iface:
            b.egress_hint = dev_ip_to_iface[us]
        elif us in update_source_to_tunnel:
            b.egress_hint = update_source_to_tunnel[us]
        elif us in tunnel_local_ip_index:
            b.egress_hint = tunnel_local_ip_index[us]
        else:
            for r in routes:
                if r.origin == "bgp-config":
                    continue
                if not r.destination.startswith(f"{b.neighbor}/"):
                    continue
                if r.via_tunnel:
                    b.egress_hint = r.via_tunnel
                    break

    tunnel_by_name_lane = {n.name: n for n in tunnels.values()}
    for b in bgp_bindings:
        b.lane_side = bgp_canvas_lane_side(b, tunnel_by_name_lane, overseas_parent, routes)

    for b in bgp_bindings:
        et = str(b.egress_hint or "")
        if et in tunnel_by_name_lane:
            b.anchor_tunnel = et
        else:
            b.anchor_tunnel = ""
            for r in routes:
                if r.origin == "bgp-config":
                    continue
                if not r.destination.startswith(f"{b.neighbor}/"):
                    continue
                vt = (r.via_tunnel or "").strip()
                if vt in tunnel_by_name_lane:
                    b.anchor_tunnel = vt
                    break

    # Build tunnel chains first (without main/backup decision).
    eligible_roles = set(ACCESS_TRANSPORT_ROLES) | {"gre-upe", "gre-overseas"}
    chain_nodes = [n.name for n in tunnels.values() if n.inferred_role in eligible_roles]
    chain_adj: Dict[str, set[str]] = {n: set() for n in chain_nodes}
    chain_edges: List[Tuple[str, str, str]] = []  # structural edges for chain connectivity
    chain_route_hints: List[Tuple[str, str, str]] = []  # route recursive hints (no merge)

    def _add_chain_edge(a: str, b: str, ev: str) -> None:
        if a == b:
            return
        if a not in chain_adj or b not in chain_adj:
            return
        if b not in chain_adj[a]:
            chain_adj[a].add(b)
            chain_adj[b].add(a)
            chain_edges.append((a, b, ev))

    # source/route parent links for overseas tunnels
    for child, parent in overseas_parent.items():
        if parent and parent in chain_adj and child in chain_adj:
            _add_chain_edge(parent, child, "overseas_parent")
    # vtun -> upe structural links
    for vt_name, upe_name in vtun_to_upe:
        if vt_name in chain_adj and upe_name in chain_adj:
            _add_chain_edge(vt_name, upe_name, "vtun_to_upe")
    # recursive route evidence: keep as hints only, do NOT merge chains
    for r in routes:
        if r.origin == "bgp-config":
            continue
        vt = (r.via_tunnel or "").strip()
        if not vt or vt not in chain_adj:
            continue
        dst = r.destination.split("/")[0]
        tn = tunnel_peer_ip_index.get(dst, "")
        if tn and tn in chain_adj:
            chain_route_hints.append((vt, tn, f"route:{r.destination}"))

    tunnel_chain_id_by_name: Dict[str, str] = {}
    tunnel_chains: Dict[str, List[str]] = {}
    cid_idx = 1
    for n0 in sorted(chain_adj.keys()):
        if n0 in tunnel_chain_id_by_name:
            continue
        cid = f"chain{cid_idx}"
        cid_idx += 1
        stack = [n0]
        comp: List[str] = []
        tunnel_chain_id_by_name[n0] = cid
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in sorted(chain_adj.get(cur, set())):
                if nxt in tunnel_chain_id_by_name:
                    continue
                tunnel_chain_id_by_name[nxt] = cid
                stack.append(nxt)
        tunnel_chains[cid] = sorted(comp)

    # Ordered labeling pipeline: BGP name -> Track name -> Tunnel remark.
    chain_side_map: Dict[str, str] = {cid: "unknown" for cid in tunnel_chains}
    chain_side_reason: Dict[str, str] = {cid: "unknown" for cid in tunnel_chains}
    line_side_map: Dict[str, str] = {}
    line_side_reason: Dict[str, str] = {}
    side_conflicts: List[str] = []

    def _name_hint_side(name: str) -> str:
        s = (name or "").lower()
        if not s:
            return "unknown"
        if any(k in s for k in ("rsvr2", "backup", "bk")):
            return "backup"
        if any(k in s for k in ("rsvr", "main", "pri")):
            return "main"
        return "unknown"

    def _apply_chain_side(cid: str, side: str, reason: str) -> None:
        cur = chain_side_map.get(cid, "unknown")
        if side not in ("main", "backup"):
            return
        if cur == "unknown":
            chain_side_map[cid] = side
            chain_side_reason[cid] = reason
            return
        if cur != side:
            side_conflicts.append(f"{cid}:{cur} vs {side} ({reason})")

    # Step 2: BGP naming
    for b in bgp_bindings:
        side = _name_hint_side((b.neighbor or "") + " " + (b.peer_group or ""))
        if side == "unknown":
            continue
        tbind = (b.anchor_tunnel or "").strip() or (b.egress_hint or "").strip() or (b.transport_tunnel or "").strip()
        if tbind and tbind in tunnel_chain_id_by_name:
            cid = tunnel_chain_id_by_name[tbind]
            _apply_chain_side(cid, side, f"bgp_name:{b.neighbor or b.peer_group}")

    # Step 3: track naming (only unknown chains)
    for r in routes:
        tr = (r.track_name or "").strip()
        if not tr:
            continue
        side = _name_hint_side(tr)
        if side == "unknown":
            continue
        tbind = (r.via_tunnel or "").strip()
        if not tbind or tbind not in tunnel_chain_id_by_name:
            continue
        cid = tunnel_chain_id_by_name[tbind]
        if chain_side_map.get(cid, "unknown") == "unknown":
            _apply_chain_side(cid, side, f"track_name:{tr}")

    # Step 4: tunnel remark fallback (only unknown chains)
    for cid, members in tunnel_chains.items():
        if chain_side_map.get(cid, "unknown") != "unknown":
            continue
        picked_side = "unknown"
        picked_reason = ""
        for nm in members:
            n0 = tunnels.get(nm)
            if not n0:
                continue
            exd = iface_desc_book.get(nm, "") if isinstance(iface_desc_book, dict) else ""
            if _line_remark_is_backup(n0.description or "", exd, n0.name or ""):
                picked_side, picked_reason = "backup", f"remark_fallback:{nm}"
                break
            if _line_remark_is_main(n0.description or "", exd, n0.name or ""):
                picked_side, picked_reason = "main", f"remark_fallback:{nm}"
                break
        if picked_side in ("main", "backup"):
            _apply_chain_side(cid, picked_side, picked_reason)

    # expand chain side to tunnel side (strict chain-based, no tunnel-level override/guess).
    for nm in sorted(tunnels.keys()):
        cid = tunnel_chain_id_by_name.get(nm, "")
        if cid and chain_side_map.get(cid, "unknown") in ("main", "backup"):
            line_side_map[nm] = chain_side_map[cid]
            line_side_reason[nm] = f"{cid}:{chain_side_reason.get(cid, 'unknown')}"
        else:
            line_side_map[nm] = "unknown"
            line_side_reason[nm] = "unknown"

    # Re-bind BGP lane strictly from finalized tunnel chain side.
    # No heuristic fallback: if anchor tunnel has no finalized side, keep unknown.
    for b in bgp_bindings:
        at = (b.anchor_tunnel or "").strip()
        if at and line_side_map.get(at, "unknown") in ("main", "backup", "unknown"):
            b.lane_side = line_side_map.get(at, "unknown")
        else:
            b.lane_side = "unknown"

    bgp_neighbor_ips = {b.neighbor for b in bgp_bindings if b.neighbor}
    for r in routes:
        if r.origin != "unknown":
            continue
        if r.destination != "0.0.0.0/0":
            continue
        if not r.next_hop:
            continue
        if r.next_hop in bgp_neighbor_ips:
            r.origin = "bgp-fib"

    outbound_sources: Dict[str, List[str]] = {}
    outbound_rule_info: Dict[str, List[str]] = {}
    for rid, out in nat_rule_outbound.items():
        srcs = nat_rule_sources.get(rid, [])
        if srcs:
            outbound_rule_info.setdefault(out, []).append(f"rule{rid}:{','.join(srcs)}")
        else:
            outbound_rule_info.setdefault(out, []).append(f"rule{rid}:未限定源")
        if srcs:
            outbound_sources.setdefault(out, []).extend(srcs)
    for k in list(outbound_sources.keys()):
        outbound_sources[k] = sorted(set(outbound_sources[k]))
    for k in list(outbound_rule_info.keys()):
        outbound_rule_info[k] = sorted(set(outbound_rule_info[k]))

    # Default egress inference (single-route policy from user):
    # 1) Route-map accepting community 80 (BGP) has highest priority.
    # 2) Fallback to static main-table 0.0.0.0/0 next-hop.
    route_map_80_next_hops: Dict[str, str] = {}
    for (rm, rid), ok80 in route_map_rule_match80.items():
        if not ok80:
            continue
        nh = route_map_rule_next_hop.get((rm, rid), "")
        if nh:
            route_map_80_next_hops[rm] = nh

    bgp_default_candidates: List[Tuple[str, str, str]] = []  # (neighbor, rm, nh)
    for b in bgp_bindings:
        rm = bgp_neighbor_in_routemap.get(b.neighbor, "") or bgp_peer_group_in_routemap.get(b.peer_group, "")
        if not rm or rm not in route_map_80_next_hops:
            continue
        bgp_default_candidates.append((b.neighbor, rm, route_map_80_next_hops[rm]))

    if bgp_default_candidates:
        nbr, rm, nh = sorted(bgp_default_candidates)[0]
        via_tun = tunnel_peer_ip_index.get(nh, "")
        nh_chain: List[str] = []
        if not via_tun:
            for r in routes:
                if r.destination.startswith(f"{nh}/32") and r.via_tunnel:
                    via_tun = r.via_tunnel
                    break
        if not via_tun:
            via_tun, ch0, _over = _resolve_next_hop_chain(nh, "main")
            nh_chain = list(ch0)
        else:
            _, ch1, _ = _resolve_next_hop_chain(nh, "main")
            nh_chain = list(ch1) if ch1 else ([nh] if nh else [])
        if via_tun:
            if not nh_chain and nh:
                nh_chain = [nh]
            default_targets.append((f"BGP默认(comm=80,rm={rm},nh={nh})", via_tun, nh_chain))

    if not default_targets:
        static_defaults = [r for r in routes if r.destination == "0.0.0.0/0" and r.route_table == "main" and r.origin == "static"]
        if static_defaults:
            def _pref_weight(x: RouteEdge) -> int:
                return int(x.preference) if x.preference.isdigit() else 999999

            chosen = sorted(static_defaults, key=lambda x: (_pref_weight(x), x.next_hop))[0]
            nh_chain2: List[str] = []
            if not chosen.via_tunnel and chosen.next_hop:
                via, ch2, _over = _resolve_next_hop_chain(chosen.next_hop, "main")
                if via:
                    chosen.via_tunnel = via
                nh_chain2 = list(ch2)
            elif chosen.next_hop:
                _, ch3, _ = _resolve_next_hop_chain(chosen.next_hop, "main")
                nh_chain2 = list(ch3)
            pref_txt = f",pref={chosen.preference}" if chosen.preference else ""
            if chosen.via_tunnel:
                default_targets.append(
                    (f"静态默认(main,nh={chosen.next_hop}{pref_txt})", chosen.via_tunnel, nh_chain2)
                )
    # Do not use policy-table (101/102/...) fallback for default route.
    # Default must come from:
    # 1) BGP community80 next-hop chain
    # 2) main table 0.0.0.0/0

    # A device has at most one default route in this analyzer policy.
    if len(default_targets) > 1:
        default_targets = [default_targets[0]]

    if default_targets:
        row0 = default_targets[0]
        k0, t0 = row0[0], row0[1]
        c0 = list(row0[2]) if len(row0) > 2 and isinstance(row0[2], list) else []
        default_route_resolution = {"kind": k0, "tunnel": t0, "nh_chain": c0}
    else:
        default_route_resolution = None

    fastip_bgp = any("rsvr" in (b.peer_group or "").lower() for b in bgp_bindings)
    bgp_service_type = "fastip" if fastip_bgp else "overlay"

    graph_nodes: List[Dict[str, str]] = []
    graph_edges: List[Dict[str, str]] = []

    def add_node(node_id: str, label: str, node_type: str) -> None:
        if not any(n["id"] == node_id for n in graph_nodes):
            graph_nodes.append({"id": node_id, "label": label, "type": node_type})

    def add_edge(src: str, dst: str, label: str, edge_type: str) -> None:
        graph_edges.append({"src": src, "dst": dst, "label": label, "type": edge_type})

    add_node("openvpn_core", "接入层(OpenVPN/IPsec-VTI/策略IPsec)", "core")

    for node in sorted(tunnels.values(), key=lambda n: n.name):
        nid = re.sub(r"[^a-zA-Z0-9_]", "_", node.name)
        role = node.inferred_role
        desc = (node.description or "").strip()
        node_lbl = f"{node.name} [{role}]"
        if desc:
            node_lbl += f"\n({desc})"
        add_node(nid, node_lbl, role)
        if role in ACCESS_TRANSPORT_ROLES:
            if role == "ipsec-vti":
                lbl = "vti"
            elif role == "ipsec-policy":
                lbl = "ipsec-s2s"
            else:
                lbl = "vtun"
            add_edge("openvpn_core", nid, lbl, "link")

    # Link domestic GRE to overseas GRE using pe-docking / next-hop correlation.
    remote_to_tunnel = {n.remote: n.name for n in tunnels.values() if n.remote}
    for r in routes:
        dst_ip = r.destination.split("/")[0]
        if dst_ip in remote_to_tunnel and r.via_tunnel:
            overseas = remote_to_tunnel[dst_ip]
            src_id = re.sub(r"[^a-zA-Z0-9_]", "_", r.via_tunnel)
            dst_id = re.sub(r"[^a-zA-Z0-9_]", "_", overseas)
            add_edge(src_id, dst_id, "pe_docking", "link")

    for vt_name, upe_name in vtun_to_upe:
        add_edge(
            re.sub(r"[^a-zA-Z0-9_]", "_", vt_name),
            re.sub(r"[^a-zA-Z0-9_]", "_", upe_name),
            "vtun->upe",
            "link",
        )

    for kind, tun, _ch in default_targets:
        did = re.sub(r"[^a-zA-Z0-9_]", "_", f"default_{kind}_{tun}")
        add_node(did, f"Default:{kind}", "default")
        add_edge(did, re.sub(r"[^a-zA-Z0-9_]", "_", tun), "0.0.0.0/0", "default")

    for pname, ptype, tun in policy_targets:
        pid = re.sub(r"[^a-zA-Z0-9_]", "_", f"policy_{pname}")
        add_node(pid, f"Policy:{pname}", "policy")
        add_edge(pid, re.sub(r"[^a-zA-Z0-9_]", "_", tun), ptype, "policy")

    seen_lgw: set[str] = set()
    for plname, liface, _brief in policy_local_targets:
        pid = re.sub(r"[^a-zA-Z0-9_]", "_", f"plocal_{plname}")
        add_node(pid, f"PBR本地:{plname}", "policy_local")
        gw_id = re.sub(r"[^a-zA-Z0-9_]", "_", f"gw_{liface}")
        if gw_id not in seen_lgw:
            add_node(gw_id, f"本地网关({liface})", "local_gw")
            seen_lgw.add(gw_id)
        add_edge(pid, gw_id, "table→nh", "policy")

    for b in bgp_bindings:
        pg_tag = b.peer_group or "direct"
        bid = re.sub(r"[^a-zA-Z0-9_]", "_", f"bgp_{pg_tag}_{b.neighbor}")
        adv_brief = ""
        if b.advertised_prefixes:
            adv_brief = "\\nexport:" + ",".join(b.advertised_prefixes[:4])
            if len(b.advertised_prefixes) > 4:
                adv_brief += "…"
        ra_txt = f" AS{b.remote_as}" if b.remote_as else ""
        add_node(bid, f"BGP{ra_txt}\n{b.neighbor}{adv_brief}", "bgp")
        target = b.egress_hint
        if target in tunnels:
            tun_id = re.sub(r"[^a-zA-Z0-9_]", "_", target)
            add_edge(bid, tun_id, f"update-source={b.update_source or '-'}", "bgp")
        else:
            add_edge(bid, "openvpn_core", f"update-source={b.update_source or '-'}", "bgp")

    mermaid_lines = ["flowchart LR"]
    for n in graph_nodes:
        mermaid_lines.append(f'{n["id"]}["{n["label"]}"]')
    for e in graph_edges:
        if e["label"]:
            mermaid_lines.append(f'{e["src"]} -->|"{e["label"]}"| {e["dst"]}')
        else:
            mermaid_lines.append(f'{e["src"]} --> {e["dst"]}')

    warnings: List[str] = []
    if not access_transport_nodes:
        warnings.append(
            "未识别到接入层（OpenVPN/vtun、VyOS `interfaces vti` IPsec-VTI、或策略 IPsec 的 local prefix 与 dummy/eth 地址对齐），请确认配置。"
        )
    if not upe_nodes and any(n.inferred_role == "gre-overseas" for n in tunnels.values()):
        warnings.append("未识别到 UPE 也可能是正常场景：已按隧道 source-address/remote 推断为直连 NATPE。")
    if not overseas_tunnels:
        warnings.append("未识别到海外出口 GRE 节点，请确认 NAT outbound-interface 或 pe_docking 路由。")
    unresolved_parent = [n for n, p in overseas_parent.items() if not p]
    if unresolved_parent:
        warnings.append(f"以下 NATPE 未判定上游链路(无证据不猜测): {', '.join(unresolved_parent)}")
    if route_depth_exceeded:
        warnings.append("检测到策略路由递归超过3跳，以下LAN-MAP未展示: " + "; ".join(route_depth_exceeded[:6]))
    if any(
        p and p in tunnels and tunnels[p].inferred_role in ACCESS_TRANSPORT_ROLES for p in overseas_parent.values()
    ):
        warnings.append(
            "检测到 接入层(vtun/VTI)->NATPE 直连场景（源IP来自本机 dummy/loopback 公网IP 且命中 SNAT translation）。"
        )
    unlane_bgp = [b.neighbor for b in bgp_bindings if getattr(b, "lane_side", "") == "unknown"]
    if unlane_bgp:
        warnings.append(
            "以下 BGP 邻居未能判定主/备画布区（仅文字摘要中保留，不在拓扑上绘制该邻居节点）: "
            + ", ".join(unlane_bgp[:16])
        )
    unanchor_bgp = [b.neighbor for b in bgp_bindings if not (getattr(b, "anchor_tunnel", "") or "").strip()]
    if unanchor_bgp:
        warnings.append(
            "以下 BGP 邻居未能绑定到本机隧道接口（egress 非隧道名且无 neighbor/* 的 via_tunnel 证据），不在拓扑上绘制: "
            + ", ".join(unanchor_bgp[:16])
        )
    if not default_targets:
        warnings.append(
            "未从配置中解析到默认路由（优先：community80 route-map next-hop；回退：static main 0/0）。"
            "因此拓扑上不会把 NAT outbound 误标成“默认路由”；如你确认存在默认路由，请检查是否使用了未覆盖的 VyOS 语法。"
        )
    # Same comm80 route-map may bind to multiple neighbors in one peer-group.
    # This is a normal redundancy pattern, so do not warn.

    summary_lines = [
        f"- Tunnel 总数: {len(tunnels)} (OpenVPN={sum(1 for t in tunnels.values() if t.inferred_role == 'openvpn')}, "
        f"IPsec-VTI={sum(1 for t in tunnels.values() if t.inferred_role == 'ipsec-vti')}, "
        f"策略IPsec={sum(1 for t in tunnels.values() if t.inferred_role == 'ipsec-policy')}, "
        f"国内GRE={sum(1 for t in tunnels.values() if t.inferred_role == 'gre-upe')}, "
        f"海外GRE={sum(1 for t in tunnels.values() if t.inferred_role == 'gre-overseas')}, "
        f"待判定={sum(1 for t in tunnels.values() if t.inferred_role == 'gre-unknown')})",
        f"- 默认出口链路: {len(default_targets)} 条，策略出口链路(隧道): {len(policy_targets)} 条，"
        f"策略出口(本地网关/LAN-MAP): {len(policy_local_targets)} 条",
        f"- BGP 邻居: {len(bgp_bindings)}，含 update-source 绑定: {sum(1 for b in bgp_bindings if b.update_source)}，"
        f"含 export prefix-list: {sum(1 for b in bgp_bindings if b.export_prefix_list)}，"
        f"已展开宣告前缀条目: {sum(len(b.advertised_prefixes) for b in bgp_bindings)}",
        f"- 海外出口隧道: {', '.join(overseas_tunnels) if overseas_tunnels else '(未识别)'}",
    ]
    if bgp_bindings:
        summary_lines.insert(
            3, f"- BGP 业务归类: {'ER FastIP(RSVR)' if bgp_service_type == 'fastip' else 'GRE组网/非RSVR'}"
        )
    if dnat_rule_count:
        dnat_prefixes = sorted({p for v in dnat_rule_prefixes.values() for p in v})
        if len(dnat_prefixes) > 4:
            summary_lines.append(f"- DNAT 网段: {len(dnat_prefixes)} 条（详见NAT梳理）")
        elif dnat_prefixes:
            summary_lines.append(f"- DNAT 网段: {','.join(dnat_prefixes)}")
        else:
            summary_lines.append(f"- DNAT 配置命中: {dnat_rule_count} 行（未提取到 destination address）")

    if default_route_resolution:
        chx = default_route_resolution.get("nh_chain") or []
        tun_x = str(default_route_resolution.get("tunnel") or "")
        kdx = str(default_route_resolution.get("kind") or "")
        if isinstance(chx, list) and chx:
            tail = " → ".join(str(x) for x in chx)
            summary_lines.append(f"- 默认路由递归: {kdx} | {tail} → 隧道 {tun_x}")
        elif tun_x:
            summary_lines.append(f"- 默认路由: {kdx} → 隧道 {tun_x}")

    not_read_sample = [
        raw_lines[i].strip()
        for i in range(len(raw_lines))
        if line_consumed.get(i) == "unparsed_set"
    ]
    read_ok_list: List[LedgerItem] = [
        LedgerItem(
            "隧道与接口",
            len(tunnels),
            [],
            f"含 interfaces tunnel/openvpn/vti 及推导对象",
        ),
        LedgerItem(
            "路由",
            len([r for r in routes if r.origin != "bgp-config"]),
            [r.evidence for r in routes[:2] if r.evidence and r.origin == "static"],
            "static / table / 递归 via_tunnel",
        ),
        LedgerItem("BGP 邻居", len(bgp_bindings), [], "peer-group / update-source / route-map 等"),
        LedgerItem("NAT source", len(nat_rule_outbound), [], "outbound-interface / translation / source"),
        LedgerItem("策略路由 PBR", len(policies), [], "policy route + local-route"),
    ]
    read_partial_list = [LedgerItem("GRE source-address 弱命中", 1, [], g) for g in gre_read_partial[:24]]
    unresolved_list: List[LedgerItem] = []
    for t in tunnels.values():
        if t.kind == "tunnel" and t.inferred_role == "gre-unknown":
            unresolved_list.append(
                LedgerItem(
                    f"tunnel:{t.name}",
                    1,
                    [],
                    "角色未判定：无 route/NAT/source 强证据" + ("；可勾选「接受备注启发」试用 description" if not accept_remark_heuristic else ""),
                )
            )
    for on, op in overseas_parent.items():
        if not op:
            unresolved_list.append(LedgerItem(f"NATPE:{on}", 1, [], "未解析上游父链路（无 source/路由证据）"))
    not_read_block: List[LedgerItem] = []
    if not_read_sample:
        not_read_block.append(
            LedgerItem("未解析的 set 行", len(not_read_sample), not_read_sample[:20], "当前解析器未匹配下列前缀（抽样）")
        )
    parse_ledger: Dict[str, object] = {
        "read_ok": read_ok_list,
        "read_partial": read_partial_list,
        "not_read": not_read_block,
        "unresolved": unresolved_list,
        "remark_conflicts": remark_conflicts,
    }
    parse_ledger_text = _format_parse_ledger(parse_ledger)
    chain_diag: List[str] = ["\n=== 隧道链构建结果 ==="]
    for cid in sorted(tunnel_chains.keys()):
        members = ",".join(tunnel_chains.get(cid, []))
        chain_diag.append(f"{cid}: {members}")
    for a, b, ev in chain_edges[:200]:
        chain_diag.append(f"edge {a} <-> {b} ({ev})")
    for a, b, ev in chain_route_hints[:200]:
        chain_diag.append(f"hint {a} -> {b} ({ev})")

    line_diag: List[str] = ["\n=== 主备判定（顺序2→3→4） ==="]
    for cid in sorted(tunnel_chains.keys()):
        line_diag.append(f"{cid} -> {chain_side_map.get(cid, 'unknown')} ({chain_side_reason.get(cid, 'unknown')})")
    for tn in sorted(tunnels.values(), key=lambda x: x.name):
        if tn.inferred_role not in ACCESS_TRANSPORT_ROLES and tn.inferred_role not in ("gre-upe", "gre-overseas"):
            continue
        ls = line_side_map.get(tn.name, "unknown")
        rs = line_side_reason.get(tn.name, "unknown")
        line_diag.append(f"{tn.name:<18} -> {ls:<7} ({rs}) role={tn.inferred_role}")
    if side_conflicts:
        line_diag.append("conflicts: " + "; ".join(side_conflicts[:32]))
    parse_ledger_text += "\n" + "\n".join(chain_diag) + "\n" + "\n".join(line_diag)

    # IP digest: count where interface IPs are referenced (excluding declaration/remark lines).
    ip_to_ifaces: Dict[str, List[str]] = {}
    for iname, addrs in iface_addr_book.items():
        for a in addrs:
            hip = _host_ip_from_pfx_or_addr(str(a))
            if not hip:
                continue
            ip_to_ifaces.setdefault(hip, []).append(iname)
    for k in list(ip_to_ifaces.keys()):
        ip_to_ifaces[k] = sorted(set(ip_to_ifaces[k]))
    iface_ips: set[str] = set(ip_to_ifaces.keys())
    ip_occ: Dict[str, List[Tuple[int, str, str]]] = {ip: [] for ip in sorted(iface_ips)}
    bgp_update_source_ips = sorted({(b.update_source or "").strip() for b in bgp_bindings if (b.update_source or "").strip()})
    excluded_decl_tags = {
        "interfaces.address",
        "interfaces.tunnel_addr",
        "interfaces.openvpn_local",
        "interfaces.vti_addr",
        "interfaces.description",
        "interfaces.tunnel_desc",
        "interfaces.vti_desc",
    }
    for i, raw in enumerate(raw_lines):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if line_consumed.get(i, "") in excluded_decl_tags:
            continue
        tag = line_consumed.get(i, "")
        for tok in IP_PATTERN.findall(s):
            ip0 = str(tok).split("/")[0]
            if ip0 in ip_occ:
                ip_occ[ip0].append((i + 1, tag or "unparsed", s))

    ip_digest_lines: List[str] = ["=== IP梳理（不计算声明和备注的应用次数）===", ""]
    ip_digest_rows: List[Dict[str, object]] = []
    ranked_ips = sorted(ip_occ.keys(), key=lambda x: (-len(ip_occ.get(x, [])), x))
    for ipx in ranked_ips:
        hits = ip_occ.get(ipx, [])
        ifaces = ip_to_ifaces.get(ipx, [])
        ifn = ifaces[0] if ifaces else "unknown-iface"
        desc = iface_desc_book.get(ifn, "") if isinstance(iface_desc_book, dict) else ""
        desc = desc if (desc or "").strip() else "无"
        head = f"- {ifn} {ipx} | 引用 {len(hits)} 次 | description: {desc}"
        ip_digest_lines.append(head)
        if hits:
            for ln, tg, txt in hits:
                ip_digest_lines.append(f"  · L{ln} [{tg}] {txt}")
        else:
            ip_digest_lines.append("  · (无引用)")
        ip_digest_lines.append("")
        ip_digest_rows.append(
            {
                "iface": ifn,
                "ip": ipx,
                "count": len(hits),
                "description": desc,
                "is_bgp_update_source": ipx in bgp_update_source_ips,
                "hits": [{"line": ln, "tag": tg, "text": txt} for ln, tg, txt in hits],
            }
        )
    ip_digest_text = "\n".join(ip_digest_lines)

    # Unused config digest
    # Scope: lo/dum zero usage, non-policy+non-default tunnels, NAT on unused tunnels, 以及 QoS/route-map 等块。
    def _collect_related_lines(iface_name: str, ip_list: List[str]) -> List[str]:
        out: List[str] = []
        nm_pat = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(iface_name)}(?![A-Za-z0-9_-])", re.I)
        ip_set = set(ip_list)
        for i, raw in enumerate(raw_lines):
            s = raw.strip()
            if not s:
                continue
            tg = line_consumed.get(i, "")
            if tg in excluded_decl_tags:
                continue
            hit = bool(nm_pat.search(s))
            if not hit and ip_set:
                for tok in IP_PATTERN.findall(s):
                    if str(tok).split("/")[0] in ip_set:
                        hit = True
                        break
            if hit:
                out.append(f"L{i+1} [{tg or 'unparsed'}] {s}")
        return out

    policy_tun_set = {str(tn) for _pn, _pt, tn in policy_targets}
    default_tun_set = {str(tn) for _k, tn, _ch in default_targets}
    unused_lines: List[str] = ["=== 无用配置（候选）===", ""]
    any_unused = False

    # 1) lo/dum with zero usage (excluding declaration/remark lines)
    # Must iterate iface_addr_book directly so we do not miss interfaces that were not materialized into tunnels dict.
    lo_dum_ifaces = sorted(
        [iname for iname in iface_addr_book.keys() if iname.lower().startswith("lo") or iname.lower().startswith("dum")]
    )
    for iname in lo_dum_ifaces:
        kind = "loopback" if iname.lower().startswith("lo") else "dummy"
        ips_n: List[str] = []
        for a in iface_addr_book.get(iname, []):
            ip0 = _host_ip_from_pfx_or_addr(str(a))
            if ip0 and ip0 not in ips_n:
                ips_n.append(ip0)
        refs = _collect_related_lines(iname, ips_n)
        if len(refs) == 0:
            any_unused = True
            n0 = tunnels.get(iname)
            desc = ""
            if n0 and (n0.description or "").strip():
                desc = (n0.description or "").strip()
            else:
                desc = (iface_desc_book.get(iname, "") or "").strip()
            desc = desc or "无"
            unused_lines.append(f"- {iname} ({kind}) 可能无用：应用次数 0 | description: {desc}")
            decls = []
            for i, raw in enumerate(raw_lines):
                s = raw.strip()
                if re.search(rf"^set interfaces (?:dummy|loopback)\s+{re.escape(iname)}\b", s, re.I):
                    decls.append(f"L{i+1} [{line_consumed.get(i, '') or 'unparsed'}] {s}")
            for row in decls:
                unused_lines.append(f"  · {row}")
            unused_lines.append("")

    # 2) Unused tunnel candidates
    unused_tunnels: set[str] = set()
    for n in sorted(tunnels.values(), key=lambda x: x.name):
        if n.kind != "tunnel":
            continue
        # 2) 仅按「无策略调用且非默认出口」筛候选；不以「链上仅单节点」判无用（星型专线+多 GRE 为常态）。
        if n.name not in policy_tun_set and n.name not in default_tun_set:
            unused_tunnels.add(n.name)

    for tn in sorted(unused_tunnels):
        n = tunnels.get(tn)
        if not n:
            continue
        any_unused = True
        reasons: List[str] = []
        if tn not in policy_tun_set and tn not in default_tun_set:
            reasons.append("无策略调用且非默认隧道")
        if not reasons:
            reasons.append("候选无用")
        desc = (n.description or "").strip() or "无"
        unused_lines.append(f"- {tn} (tunnel) 可能无用：{'；'.join(reasons)} | description: {desc}")
        ips_t: List[str] = []
        for v in (n.address, n.source, n.remote):
            ip0 = _host_ip_from_pfx_or_addr(str(v or ""))
            if ip0 and ip0 not in ips_t:
                ips_t.append(ip0)
        refs = _collect_related_lines(tn, ips_t)
        for row in refs:
            unused_lines.append(f"  · {row}")
        unused_lines.append("")

    # 3) NAT calls on unused tunnels
    for rid, out_if in sorted(nat_rule_outbound.items(), key=lambda kv: (int(kv[0]) if str(kv[0]).isdigit() else 10**9, kv[0])):
        if out_if not in unused_tunnels:
            continue
        any_unused = True
        unused_lines.append(f"- NAT 调用可能无用隧道: rule {rid} -> {out_if}")
        pat = re.compile(rf"^set nat source rule {re.escape(str(rid))}\b", re.I)
        for i, raw in enumerate(raw_lines):
            s = raw.strip()
            if pat.search(s):
                unused_lines.append(f"  · L{i+1} [{line_consumed.get(i, '') or 'unparsed'}] {s}")
        unused_lines.append("")

    def _collect_lines_by_regex(pattern: str) -> List[str]:
        rx = re.compile(pattern, re.I)
        rows: List[str] = []
        for i, raw in enumerate(raw_lines):
            s = raw.strip()
            if not s:
                continue
            if rx.search(s):
                rows.append(f"L{i+1} [{line_consumed.get(i, '') or 'unparsed'}] {s}")
        return rows

    # 4) QoS (traffic-policy) definitions that are not referenced.
    shaper_defs: set[str] = set()
    shaper_uses: set[str] = set()
    re_shaper_def = re.compile(r"^set traffic-policy shaper\s+([^\s]+)\b", re.I)
    re_shaper_use = re.compile(r"traffic-policy\s+(?:in|out)\s+'?([^'\s]+)'?", re.I)
    for raw in raw_lines:
        s = raw.strip()
        md = re_shaper_def.match(s)
        if md:
            shaper_defs.add(_clean_value(md.group(1)))
        for mu in re_shaper_use.finditer(s):
            if mu.group(1):
                shaper_uses.add(_clean_value(mu.group(1)))
    for name in sorted(shaper_defs):
        if name in shaper_uses:
            continue
        any_unused = True
        unused_lines.append(f"- QoS/traffic-policy 可能无用：{name}（定义存在但未被接口调用）")
        for row in _collect_lines_by_regex(rf"^set traffic-policy shaper\s+{re.escape(name)}\b"):
            unused_lines.append(f"  · {row}")
        unused_lines.append("")

    # 5) route-map definitions not referenced by BGP/redistribute hooks.
    route_map_defs: set[str] = set()
    route_map_used: set[str] = set()
    re_rm_def = re.compile(r"^set policy route-map\s+([^\s]+)\s+rule\b", re.I)
    re_rm_use = re.compile(
        r"route-map\s+(?:import|export|in|out)\s+'?([^'\s]+)'?|redistribute\s+\S+\s+route-map\s+'?([^'\s]+)'?",
        re.I,
    )
    for raw in raw_lines:
        s = raw.strip()
        md = re_rm_def.match(s)
        if md:
            route_map_defs.add(_clean_value(md.group(1)))
        for mu in re_rm_use.finditer(s):
            g1 = mu.group(1) if mu.lastindex and mu.lastindex >= 1 else None
            g2 = mu.group(2) if mu.lastindex and mu.lastindex >= 2 else None
            if g1:
                route_map_used.add(_clean_value(g1))
            if g2:
                route_map_used.add(_clean_value(g2))
    for name in sorted(route_map_defs):
        if name in route_map_used:
            continue
        any_unused = True
        unused_lines.append(f"- route-map 可能无用：{name}（定义存在但未被BGP/重分发调用）")
        for row in _collect_lines_by_regex(rf"^set policy route-map\s+{re.escape(name)}\s+rule\b"):
            unused_lines.append(f"  · {row}")
        unused_lines.append("")

    # 6) policy route definitions not bound to any interface.
    policy_route_defs: set[str] = set()
    policy_route_used: set[str] = set()
    re_pr_def = re.compile(r"^set policy route\s+([^\s]+)\s+rule\b", re.I)
    re_pr_use = re.compile(r"^set interfaces [^\s]+(?:\s+vif\s+[^\s]+)?\s+policy route\s+'?([^'\s]+)'?", re.I)
    for raw in raw_lines:
        s = raw.strip()
        md = re_pr_def.match(s)
        if md:
            policy_route_defs.add(_clean_value(md.group(1)))
        mu = re_pr_use.match(s)
        if mu and mu.group(1):
            policy_route_used.add(_clean_value(mu.group(1)))
    for name in sorted(policy_route_defs):
        if name in policy_route_used:
            continue
        any_unused = True
        unused_lines.append(f"- policy-route 可能无用：{name}（定义存在但未绑定接口）")
        for row in _collect_lines_by_regex(rf"^set policy route\s+{re.escape(name)}\s+rule\b"):
            unused_lines.append(f"  · {row}")
        unused_lines.append("")

    # 7) IPsec objects present but unused.
    ike_defs: set[str] = set()
    esp_defs: set[str] = set()
    ike_used: set[str] = set()
    esp_used: set[str] = set()
    ipsec_peers: set[str] = set()
    ipsec_peer_has_tunnel: set[str] = set()
    re_ike_def = re.compile(r"^set vpn ipsec ike-group\s+([^\s]+)\b", re.I)
    re_esp_def = re.compile(r"^set vpn ipsec esp-group\s+([^\s]+)\b", re.I)
    re_peer_any = re.compile(r"^set vpn ipsec site-to-site peer\s+([^\s]+)\b", re.I)
    re_peer_ike = re.compile(r"^set vpn ipsec site-to-site peer\s+([^\s]+)\s+ike-group\s+'?([^'\s]+)'?", re.I)
    re_peer_esp = re.compile(r"^set vpn ipsec site-to-site peer\s+([^\s]+)\s+default-esp-group\s+'?([^'\s]+)'?", re.I)
    re_peer_tunnel = re.compile(r"^set vpn ipsec site-to-site peer\s+([^\s]+)\s+tunnel\s+\d+\b", re.I)
    for raw in raw_lines:
        s = raw.strip()
        md = re_ike_def.match(s)
        if md:
            ike_defs.add(_clean_value(md.group(1)))
        md = re_esp_def.match(s)
        if md:
            esp_defs.add(_clean_value(md.group(1)))
        mp = re_peer_any.match(s)
        if mp:
            ipsec_peers.add(_clean_value(mp.group(1)))
        mi = re_peer_ike.match(s)
        if mi and mi.group(2):
            ike_used.add(_clean_value(mi.group(2)))
        me = re_peer_esp.match(s)
        if me and me.group(2):
            esp_used.add(_clean_value(me.group(2)))
        mt = re_peer_tunnel.match(s)
        if mt and mt.group(1):
            ipsec_peer_has_tunnel.add(_clean_value(mt.group(1)))

    for name in sorted(ike_defs):
        if name in ike_used:
            continue
        any_unused = True
        unused_lines.append(f"- IPsec IKE 组可能无用：{name}（定义存在但未被peer调用）")
        for row in _collect_lines_by_regex(rf"^set vpn ipsec ike-group\s+{re.escape(name)}\b"):
            unused_lines.append(f"  · {row}")
        unused_lines.append("")

    for name in sorted(esp_defs):
        if name in esp_used:
            continue
        any_unused = True
        unused_lines.append(f"- IPsec ESP 组可能无用：{name}（定义存在但未被peer调用）")
        for row in _collect_lines_by_regex(rf"^set vpn ipsec esp-group\s+{re.escape(name)}\b"):
            unused_lines.append(f"  · {row}")
        unused_lines.append("")

    for peer in sorted(ipsec_peers):
        if peer in ipsec_peer_has_tunnel:
            continue
        any_unused = True
        unused_lines.append(f"- IPsec peer 可能无用：{peer}（存在peer定义但未发现tunnel条目）")
        for row in _collect_lines_by_regex(rf"^set vpn ipsec site-to-site peer\s+{re.escape(peer)}\b"):
            unused_lines.append(f"  · {row}")
        unused_lines.append("")

    if not any_unused:
        unused_lines.append("未识别到符合当前规则的无用配置候选。")
    unused_config_text = "\n".join(unused_lines)

    node_side = {n.name: n.side for n in tunnels.values()}
    return {
        "tunnels": tunnels,
        "routes": routes,
        "policies": policies,
        "bgp": bgp_bindings,
        "graph_nodes": graph_nodes,
        "graph_edges": graph_edges,
        "node_side": node_side,
        "line_side_map": line_side_map,
        "line_side_reason": line_side_reason,
        "tunnel_chain_id_by_name": tunnel_chain_id_by_name,
        "tunnel_chains": tunnel_chains,
        "chain_side_map": chain_side_map,
        "chain_side_reason": chain_side_reason,
        "overseas_parent": overseas_parent,
        "vtun_to_upe": list(vtun_to_upe),
        "bgp_service_type": bgp_service_type,
        "default_targets": default_targets,
        "default_route_resolution": default_route_resolution,
        "policy_targets": policy_targets,
        "policy_local_targets": policy_local_targets,
        "outbound_sources": outbound_sources,
        "outbound_rule_info": outbound_rule_info,
        "dnat_prefixes": sorted({p for v in dnat_rule_prefixes.values() for p in v}),
        "warnings": warnings,
        "hostname": hostname,
        "mermaid": "\n".join(mermaid_lines),
        "summary": "\n".join(summary_lines),
        "parse_ledger": parse_ledger,
        "parse_ledger_text": parse_ledger_text,
        "ip_digest_text": ip_digest_text,
        "ip_digest_rows": ip_digest_rows,
        "unused_config_text": unused_config_text,
        "line_consumed_count": len(line_consumed),
    }


class ERAnalyzerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ER 配置梳理工具")
        self.root.geometry("1520x900")

        self.rows: List[Dict[str, str]] = []
        self.topology_details: List[Dict[str, str]] = []
        self.topology_zoom: float = 1.0
        self.topology_min_zoom: float = 0.4
        self.topology_max_zoom: float = 2.5
        self.ip_digest_mode: str = "concise"
        self._last_er_topology: Optional[Dict[str, object]] = None
        self._topology_wheel_capture = False
        self._topology_wheel_all_bound = False

        self._build_widgets()

    def _build_widgets(self) -> None:
        style = ttk.Style()
        # Result notebook color coding for faster visual distinction.
        style.configure("Result.TNotebook.Tab", padding=(10, 6))
        style.map(
            "Result.TNotebook.Tab",
            background=[
                ("selected", "#dbeafe"),  # blue when selected
                ("!selected", "#f3f4f6"),
            ],
            foreground=[
                ("selected", "#1e3a8a"),
                ("!selected", "#374151"),
            ],
        )

        top_frame = ttk.Frame(self.root, padding=8)
        top_frame.pack(fill=tk.BOTH, expand=False)

        ttk.Button(top_frame, text="导入配置文件", command=self.load_config_file).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_frame, text="解析并梳理", command=self.analyze).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_frame, text="映射智能换行", command=self.normalize_mapping_text).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_frame, text="导出", command=self.export_csv).pack(side=tk.LEFT, padx=4)
        ttk.Button(top_frame, text="清空", command=self.clear_all).pack(side=tk.LEFT, padx=4)
        self.accept_remark_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(top_frame, text="GRE 接受备注启发", variable=self.accept_remark_var).pack(side=tk.LEFT, padx=8)

        main_split = tk.PanedWindow(
            self.root,
            orient=tk.VERTICAL,
            sashwidth=10,
            sashrelief=tk.RAISED,
            bg="#cbd5e1",
            bd=1,
        )
        main_split.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.notebook = ttk.Notebook(main_split)
        main_split.add(self.notebook, stretch="always", minsize=220)

        self.scene_widgets: Dict[str, Dict[str, tk.Text]] = {}
        self._create_scene_tab("ER", "ER配置脚本（粘贴完整配置）")
        self._create_scene_tab("USG", "USG配置脚本（粘贴完整配置）")

        result_frame = ttk.Labelframe(main_split, text="梳理结果")
        main_split.add(result_frame, stretch="always", minsize=220)

        self.result_notebook = ttk.Notebook(result_frame, style="Result.TNotebook")
        self.result_notebook.pack(fill=tk.BOTH, expand=True)

        nat_tab = ttk.Frame(self.result_notebook)
        topo_tab = ttk.Frame(self.result_notebook)
        ledger_tab = ttk.Frame(self.result_notebook)
        ip_tab = ttk.Frame(self.result_notebook)
        unused_tab = ttk.Frame(self.result_notebook)
        self.result_notebook.add(nat_tab, text="🟠 NAT梳理")
        self.result_notebook.add(topo_tab, text="🔵 ER拓扑分析")
        ledger_lf = ttk.Labelframe(ledger_tab, text="证据链 / 未消费行 / 备注冲突")
        ledger_lf.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.parse_ledger_text = self._add_text_scrollbars(ledger_lf, wrap=tk.WORD, height=16, enable_x=True)
        self._attach_text_context_menu(self.parse_ledger_text)
        self.result_notebook.add(ledger_tab, text="🟣 解析备注")
        ip_lf = ttk.Labelframe(ip_tab, text="接口IP引用统计（不计算声明和备注的应用次数）")
        ip_lf.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        ip_toolbar = ttk.Frame(ip_lf)
        ip_toolbar.pack(fill=tk.X, padx=4, pady=(2, 0))
        ttk.Button(ip_toolbar, text="简洁模式", command=lambda: self._set_ip_digest_mode("concise")).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(ip_toolbar, text="完全模式", command=lambda: self._set_ip_digest_mode("full")).pack(
            side=tk.LEFT, padx=2
        )
        self.ip_digest_text = self._add_text_scrollbars(ip_lf, wrap=tk.NONE, height=16, enable_x=True)
        self.ip_digest_text.tag_configure("ip_zero_count", foreground="#b91c1c")
        self.ip_digest_text.tag_configure("ip_bgp_source", foreground="#166534")
        self._attach_text_context_menu(self.ip_digest_text)
        self.result_notebook.add(ip_tab, text="🟢 IP梳理")
        unused_lf = ttk.Labelframe(unused_tab, text="无用配置候选（请人工复核）")
        unused_lf.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.unused_config_text = self._add_text_scrollbars(unused_lf, wrap=tk.WORD, height=16, enable_x=True)
        self._attach_text_context_menu(self.unused_config_text)
        self.result_notebook.add(unused_tab, text="🔴 无用配置")

        columns = (
            "rule",
            "source_ip",
            "egress_name",
            "egress_remark",
            "fake_ip",
            "real_ip",
        )
        self.tree = ttk.Treeview(nat_tab, columns=columns, show="headings", height=14)
        headers = {
            "rule": "规则",
            "source_ip": "源IP/网段",
            "egress_name": "出口名字",
            "egress_remark": "出口备注",
            "fake_ip": "假IP",
            "real_ip": "真IP",
        }
        widths = {
            "rule": 150,
            "source_ip": 220,
            "egress_name": 180,
            "egress_remark": 260,
            "fake_ip": 140,
            "real_ip": 140,
        }
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar_y = ttk.Scrollbar(nat_tab, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar_x = ttk.Scrollbar(nat_tab, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._attach_tree_context_menu(self.tree)

        self._build_topology_tab(topo_tab)

        self.status_var = tk.StringVar(value="就绪")
        status_label = ttk.Label(self.root, textvariable=self.status_var, anchor=tk.W, padding=(8, 4))
        status_label.pack(fill=tk.X, expand=False)

    def _build_topology_tab(self, parent: ttk.Frame) -> None:
        top_split = tk.PanedWindow(
            parent,
            orient=tk.VERTICAL,
            sashwidth=8,
            sashrelief=tk.RAISED,
            bg="#cbd5e1",
            bd=1,
        )
        top_split.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        canvas_frame = ttk.Labelframe(top_split, text="ER链路拓扑图（大图）")
        top_split.add(canvas_frame, stretch="always", minsize=220)

        toolbar = ttk.Frame(canvas_frame)
        toolbar.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Button(toolbar, text="放大 +", command=lambda: self._zoom_topology(1.15)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="缩小 -", command=lambda: self._zoom_topology(1 / 1.15)).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="重置 100%", command=self._reset_topology_zoom).pack(side=tk.LEFT, padx=6)
        self.topology_zoom_var = tk.StringVar(
            value="缩放: 100%（Ctrl+滚轮缩放，滚轮纵向滚动，Shift+滚轮横向滚动，左键拖拽平移）"
        )
        ttk.Label(toolbar, textvariable=self.topology_zoom_var).pack(side=tk.LEFT, padx=8)

        viewer = ttk.Frame(canvas_frame)
        viewer.pack(fill=tk.BOTH, expand=True)
        self.topology_canvas = tk.Canvas(viewer, background="white")
        self.topology_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cy = ttk.Scrollbar(viewer, orient=tk.VERTICAL, command=self.topology_canvas.yview)
        cx = ttk.Scrollbar(viewer, orient=tk.HORIZONTAL, command=self.topology_canvas.xview)
        self.topology_canvas.configure(yscrollcommand=cy.set, xscrollcommand=cx.set)
        cy.pack(side=tk.RIGHT, fill=tk.Y)
        cx.pack(side=tk.BOTTOM, fill=tk.X)
        self.topology_canvas.bind("<Enter>", self._enable_topology_wheel_capture)
        self.topology_canvas.bind("<Leave>", self._disable_topology_wheel_capture)
        self.topology_canvas.bind("<ButtonPress-1>", self._topology_pan_start)
        self.topology_canvas.bind("<B1-Motion>", self._topology_pan_move)
        self.topology_canvas.bind("<ButtonRelease-1>", self._topology_pan_end)

        lower = tk.PanedWindow(
            top_split,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief=tk.RAISED,
            bg="#cbd5e1",
            bd=1,
        )
        top_split.add(lower, stretch="always", minsize=140)

        summary_frame = ttk.Labelframe(lower, text="文字说明")
        self.topology_summary = self._add_text_scrollbars(summary_frame, wrap=tk.WORD, height=8, enable_x=False)
        self._attach_text_context_menu(self.topology_summary)
        lower.add(summary_frame, stretch="always", minsize=180)

        mermaid_frame = ttk.Labelframe(lower, text="Mermaid导出")
        self.topology_mermaid = self._add_text_scrollbars(mermaid_frame, wrap=tk.NONE, height=8, enable_x=True)
        self._attach_text_context_menu(self.topology_mermaid)
        lower.add(mermaid_frame, stretch="always", minsize=220)

    def _update_topology_scrollregion(self) -> None:
        bbox = self.topology_canvas.bbox("all")
        if bbox:
            self.topology_canvas.configure(scrollregion=bbox)

    def _zoom_topology(self, factor: float, center_x: Optional[float] = None, center_y: Optional[float] = None) -> None:
        if factor <= 0:
            return
        target_zoom = self.topology_zoom * factor
        target_zoom = max(self.topology_min_zoom, min(self.topology_max_zoom, target_zoom))
        if abs(target_zoom - self.topology_zoom) < 1e-6:
            return
        self.topology_zoom = target_zoom
        self.topology_zoom_var.set(f"缩放: {int(self.topology_zoom * 100)}%（Ctrl+缩放，纵向/Shift+横向）")
        top = getattr(self, "_last_er_topology", None)
        if top is not None:
            self._draw_topology_canvas(top)
        else:
            self._update_topology_scrollregion()

    def _reset_topology_zoom(self) -> None:
        if abs(self.topology_zoom - 1.0) < 1e-6:
            return
        self._zoom_topology(1.0 / self.topology_zoom)

    def _topology_wheel_on_canvas(self, event: tk.Event) -> str:
        """Topology canvas: Ctrl+滚轮缩放；Shift+滚轮横向；否则纵向滚动。"""
        if not getattr(self, "_topology_wheel_capture", False):
            return ""
        if event.widget != self.topology_canvas:
            return ""
        state = getattr(event, "state", 0)
        ctrl = (state & 0x0004) != 0
        shift = (state & 0x0001) != 0
        delta = getattr(event, "delta", 0)
        if ctrl:
            if not delta:
                return ""
            factor = 1.15 if delta > 0 else 1 / 1.15
            cx = self.topology_canvas.canvasx(event.x)
            cy = self.topology_canvas.canvasy(event.y)
            self._zoom_topology(factor, center_x=cx, center_y=cy)
            return "break"
        step = int(-1 * (delta / 120)) if delta else 0
        if not step:
            return ""
        if shift:
            self.topology_canvas.xview_scroll(step, "units")
            return "break"
        self.topology_canvas.yview_scroll(step, "units")
        return "break"

    def _topology_wheel_linux_on_canvas(self, event: tk.Event) -> str:
        if not getattr(self, "_topology_wheel_capture", False):
            return ""
        if event.widget != self.topology_canvas:
            return ""
        state = getattr(event, "state", 0)
        ctrl = (state & 0x0004) != 0
        shift = (state & 0x0001) != 0
        num = int(getattr(event, "num", 0))
        if ctrl:
            factor = 1.15 if num == 4 else 1 / 1.15
            cx = self.topology_canvas.canvasx(getattr(event, "x", 0))
            cy = self.topology_canvas.canvasy(getattr(event, "y", 0))
            self._zoom_topology(factor, center_x=cx, center_y=cy)
            return "break"
        if shift:
            if num == 4:
                self.topology_canvas.xview_scroll(-3, "units")
            else:
                self.topology_canvas.xview_scroll(3, "units")
            return "break"
        if num == 4:
            self.topology_canvas.yview_scroll(-3, "units")
        else:
            self.topology_canvas.yview_scroll(3, "units")
        return "break"

    def _topology_pan_start(self, event: tk.Event) -> None:
        self.topology_canvas.scan_mark(event.x, event.y)

    def _topology_pan_move(self, event: tk.Event) -> None:
        self.topology_canvas.scan_dragto(event.x, event.y, gain=1)

    def _topology_pan_end(self, _event: tk.Event) -> None:
        pass

    def _enable_topology_wheel_capture(self, _event: tk.Event) -> None:
        self._topology_wheel_capture = True
        try:
            self.topology_canvas.configure(cursor="fleur")
        except tk.TclError:
            pass
        if self._topology_wheel_all_bound:
            return
        # bind_all is required on Windows so wheel events reach the canvas reliably.
        self.root.bind_all("<MouseWheel>", self._topology_wheel_on_canvas)
        self.root.bind_all("<Button-4>", self._topology_wheel_linux_on_canvas)
        self.root.bind_all("<Button-5>", self._topology_wheel_linux_on_canvas)
        self._topology_wheel_all_bound = True

    def _disable_topology_wheel_capture(self, _event: tk.Event) -> None:
        self._topology_wheel_capture = False
        try:
            self.topology_canvas.configure(cursor="")
        except tk.TclError:
            pass
        if self._topology_wheel_all_bound:
            self.root.unbind_all("<MouseWheel>")
            self.root.unbind_all("<Button-4>")
            self.root.unbind_all("<Button-5>")
            self._topology_wheel_all_bound = False

    def _create_scene_tab(self, scene_name: str, config_title: str) -> None:
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text=scene_name)

        input_pane = tk.PanedWindow(
            tab,
            orient=tk.HORIZONTAL,
            sashwidth=8,
            sashrelief=tk.RAISED,
            bg="#cbd5e1",
            bd=1,
        )
        input_pane.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        config_frame = ttk.Labelframe(input_pane, text=config_title)
        config_text = self._add_text_scrollbars(config_frame, wrap=tk.NONE, height=16, enable_x=True)
        self._attach_text_context_menu(config_text)
        input_pane.add(config_frame, stretch="always", minsize=280)

        map_frame = ttk.Labelframe(
            input_pane,
            text="假IP-真IP 对应关系（示例：10.60.44.28-218.32.88.83；10.60.18.22-150.116.112.236）",
        )
        # wrap=WORD lets long pasted mapping content auto-wrap visually.
        mapping_text = self._add_text_scrollbars(map_frame, wrap=tk.WORD, height=16, enable_x=False)
        self._attach_text_context_menu(mapping_text, is_mapping_text=True)
        input_pane.add(map_frame, stretch="always", minsize=200)

        self.scene_widgets[scene_name] = {"config": config_text, "mapping": mapping_text}

    def _current_scene(self) -> str:
        idx = self.notebook.index(self.notebook.select())
        return self.notebook.tab(idx, "text")

    def _add_text_scrollbars(self, parent: ttk.Labelframe, wrap: str, height: int, enable_x: bool) -> tk.Text:
        # Put text + scrollbars in one inner container so scrollbars
        # always stay attached to the user input area.
        container = ttk.Frame(parent)
        container.pack(fill=tk.BOTH, expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        text_widget = tk.Text(container, wrap=wrap, height=height, undo=True)
        text_widget.grid(row=0, column=0, sticky="nsew")

        ybar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=text_widget.yview)
        ybar.grid(row=0, column=1, sticky="ns")
        text_widget.configure(yscrollcommand=ybar.set)

        if enable_x:
            xbar = ttk.Scrollbar(container, orient=tk.HORIZONTAL, command=text_widget.xview)
            xbar.grid(row=1, column=0, sticky="ew")
            text_widget.configure(xscrollcommand=xbar.set)
        return text_widget

    def _attach_text_context_menu(self, widget: tk.Text, is_mapping_text: bool = False) -> None:
        def select_all() -> None:
            widget.tag_add(tk.SEL, "1.0", tk.END)
            widget.mark_set(tk.INSERT, "1.0")
            widget.see(tk.INSERT)

        menu = tk.Menu(widget, tearoff=0)
        menu.add_command(label="撤销", command=lambda: widget.event_generate("<<Undo>>"))
        menu.add_command(label="重做", command=lambda: widget.event_generate("<<Redo>>"))
        menu.add_separator()
        menu.add_command(label="剪切", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="复制", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="粘贴", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_command(label="全选", command=select_all)
        if is_mapping_text:
            menu.add_separator()
            menu.add_command(label="智能换行", command=self.normalize_mapping_text)

        def show_menu(event: tk.Event) -> None:
            menu.tk_popup(event.x_root, event.y_root)

        widget.bind("<Button-3>", show_menu)

    def _attach_tree_context_menu(self, widget: ttk.Treeview) -> None:
        menu = tk.Menu(widget, tearoff=0)

        def copy_row() -> None:
            selected = widget.focus()
            if not selected:
                return
            values = widget.item(selected, "values")
            self.root.clipboard_clear()
            self.root.clipboard_append("\t".join(str(v) for v in values))

        menu.add_command(label="复制当前行", command=copy_row)

        def show_menu(event: tk.Event) -> None:
            row_id = widget.identify_row(event.y)
            if row_id:
                widget.selection_set(row_id)
                widget.focus(row_id)
            menu.tk_popup(event.x_root, event.y_root)

        widget.bind("<Button-3>", show_menu)

    def normalize_mapping_text(self) -> None:
        scene = self._current_scene()
        mapping_widget = self.scene_widgets[scene]["mapping"]
        text = mapping_widget.get("1.0", tk.END).strip()
        if not text:
            return

        normalized = text.replace("\r", "\n")
        normalized = normalized.replace("；", "；\n").replace(";", ";\n")
        normalized = re.sub(r"\n{2,}", "\n", normalized).strip()
        mapping_widget.delete("1.0", tk.END)
        mapping_widget.insert("1.0", normalized)
        self.status_var.set(f"{scene} 映射文本已智能换行。")

    def load_config_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择 ER 配置文件",
            filetypes=[("Text Files", "*.txt *.cfg *.conf *.tpl"), ("All Files", "*.*")],
        )
        if not file_path:
            return

        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
            scene = self._current_scene()
            self.scene_widgets[scene]["config"].delete("1.0", tk.END)
            self.scene_widgets[scene]["config"].insert("1.0", content)
            self.status_var.set(f"已加载 {scene} 配置文件: {file_path}")
        except Exception as exc:
            messagebox.showerror("读取失败", f"无法读取文件:\n{exc}")

    def analyze(self) -> None:
        scene = self._current_scene()
        config = self.scene_widgets[scene]["config"].get("1.0", tk.END).strip()
        mapping = self.scene_widgets[scene]["mapping"].get("1.0", tk.END).strip()

        if not config:
            self.status_var.set(f"请先输入或导入 {scene} 配置内容。")
            self._refresh_table([])
            return

        try:
            if scene == "USG":
                self.rows = build_output_rows_usg(config, mapping)
                if hasattr(self, "parse_ledger_text"):
                    self.parse_ledger_text.delete("1.0", tk.END)
                    self.parse_ledger_text.insert("1.0", "USG 场景无 ER parse_ledger；请切换到 ER 页签解析。")
                if hasattr(self, "ip_digest_text"):
                    self.ip_digest_text.delete("1.0", tk.END)
                    self.ip_digest_text.insert("1.0", "USG 场景无 ER 接口IP梳理；请切换到 ER 页签解析。")
                if hasattr(self, "unused_config_text"):
                    self.unused_config_text.delete("1.0", tk.END)
                    self.unused_config_text.insert("1.0", "USG 场景无 ER 无用配置候选；请切换到 ER 页签解析。")
            else:
                self.rows = build_output_rows(config, mapping)
                topology = analyze_er_topology(config, accept_remark_heuristic=bool(self.accept_remark_var.get()))
                self._refresh_topology(topology)
                warnings = topology.get("warnings", [])
                if isinstance(warnings, list) and warnings:
                    self.topology_summary.insert(
                        tk.END, "\n\n--- 拓扑提示 ---\n" + "\n".join(str(w) for w in warnings)
                    )

            if not self.rows:
                self.rows = []
                self._refresh_table([NAT_TABLE_PLACEHOLDER_NO_NAT])
                self.status_var.set(f"{scene} 解析完成，无 NAT 规则。")
            else:
                self._refresh_table(self.rows)
                self.status_var.set(f"{scene} 解析完成，共 {len(self.rows)} 条记录。")
        except Exception as exc:
            self.rows = []
            self._refresh_table([])
            if hasattr(self, "parse_ledger_text"):
                self.parse_ledger_text.delete("1.0", tk.END)
            if hasattr(self, "ip_digest_text"):
                self.ip_digest_text.delete("1.0", tk.END)
            if hasattr(self, "unused_config_text"):
                self.unused_config_text.delete("1.0", tk.END)
            self.status_var.set(f"解析失败: {exc}")

    def _refresh_table(self, rows: List[Dict[str, str]]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row["rule"],
                    row["source_ip"],
                    row["egress_name"],
                    row["egress_remark"],
                    row["fake_ip"],
                    row["real_ip"],
                ),
            )

    def _refresh_topology(self, topology: Dict[str, object]) -> None:
        self._last_er_topology = topology
        self.topology_zoom = 1.0
        if hasattr(self, "topology_zoom_var"):
            self.topology_zoom_var.set(
                "缩放: 100%（Ctrl+滚轮缩放，滚轮纵向滚动，Shift+滚轮横向滚动，左键拖拽平移）"
            )
        self._draw_topology_canvas(topology)
        self.topology_mermaid.delete("1.0", tk.END)
        self.topology_mermaid.insert("1.0", str(topology.get("mermaid", "")))
        self.topology_summary.delete("1.0", tk.END)
        self.topology_summary.insert("1.0", str(topology.get("summary", "")))
        if hasattr(self, "parse_ledger_text"):
            self.parse_ledger_text.delete("1.0", tk.END)
            self.parse_ledger_text.insert("1.0", str(topology.get("parse_ledger_text", "")))
        self._render_ip_digest(topology)
        if hasattr(self, "unused_config_text"):
            self.unused_config_text.delete("1.0", tk.END)
            self.unused_config_text.insert("1.0", str(topology.get("unused_config_text", "")))

    def _set_ip_digest_mode(self, mode: str) -> None:
        self.ip_digest_mode = "full" if mode == "full" else "concise"
        top = getattr(self, "_last_er_topology", None)
        if isinstance(top, dict):
            self._render_ip_digest(top)

    def _render_ip_digest(self, topology: Dict[str, object]) -> None:
        if not hasattr(self, "ip_digest_text"):
            return
        self.ip_digest_text.delete("1.0", tk.END)
        rows = topology.get("ip_digest_rows", [])
        if not isinstance(rows, list) or not rows:
            self.ip_digest_text.insert("1.0", str(topology.get("ip_digest_text", "")))
            return
        mode_title = "简洁模式" if self.ip_digest_mode != "full" else "完全模式"
        self.ip_digest_text.insert(tk.END, f"=== IP梳理（{mode_title}；不计算声明和备注的应用次数）===\n\n")
        for row in rows:
            if not isinstance(row, dict):
                continue
            iface = str(row.get("iface", "unknown-iface"))
            ipx = str(row.get("ip", ""))
            cnt = int(row.get("count", 0))
            desc = str(row.get("description", "无"))
            head = f"- {iface} {ipx} | 引用 {cnt} 次 | description: {desc}\n"
            start = self.ip_digest_text.index(tk.END)
            self.ip_digest_text.insert(tk.END, head)
            end = self.ip_digest_text.index(tk.END)
            if bool(row.get("is_bgp_update_source", False)):
                self.ip_digest_text.tag_add("ip_bgp_source", start, end)
            if cnt == 0:
                self.ip_digest_text.tag_add("ip_zero_count", start, end)
            if self.ip_digest_mode == "full":
                hits = row.get("hits", [])
                if isinstance(hits, list) and hits:
                    for h in hits:
                        if not isinstance(h, dict):
                            continue
                        ln = int(h.get("line", 0))
                        tg = str(h.get("tag", "unparsed"))
                        txt = str(h.get("text", ""))
                        self.ip_digest_text.insert(tk.END, f"  · L{ln} [{tg}] {txt}\n")
                else:
                    self.ip_digest_text.insert(tk.END, "  · (无引用)\n")
            self.ip_digest_text.insert(tk.END, "\n")

    def _draw_topology_canvas(self, topology: Dict[str, object]) -> None:
        try:
            x_saved = float(self.topology_canvas.xview()[0])
            y_saved = float(self.topology_canvas.yview()[0])
        except tk.TclError:
            x_saved, y_saved = 0.0, 0.0
        self.topology_canvas.delete("all")
        tunnels = topology.get("tunnels", {})
        default_targets_raw = topology.get("default_targets", [])
        default_targets: List[Tuple[str, str, List[str]]] = []
        if isinstance(default_targets_raw, list):
            for row in default_targets_raw:
                if isinstance(row, (list, tuple)) and len(row) >= 2:
                    ch = list(row[2]) if len(row) > 2 and isinstance(row[2], list) else []
                    default_targets.append((str(row[0]), str(row[1]), ch))
        policy_targets = topology.get("policy_targets", [])
        policy_local_targets = topology.get("policy_local_targets", [])
        outbound_sources = topology.get("outbound_sources", {})
        outbound_rule_info = topology.get("outbound_rule_info", {})
        line_side_map_raw = topology.get("line_side_map", {})
        bgp = topology.get("bgp", [])
        routes = topology.get("routes", [])
        overseas_parent = topology.get("overseas_parent", {})
        vtun_to_upe_pairs = topology.get("vtun_to_upe")
        if not isinstance(vtun_to_upe_pairs, list):
            vtun_to_upe_pairs = []
        dnat_prefixes = topology.get("dnat_prefixes", [])
        hostname = str(topology.get("hostname", "本机"))
        if not isinstance(tunnels, dict):
            self.topology_canvas.configure(scrollregion=(0, 0, 400, 300))
            self.topology_canvas.xview_moveto(max(0.0, min(1.0, x_saved)))
            self.topology_canvas.yview_moveto(max(0.0, min(1.0, y_saved)))
            return

        z = max(self.topology_min_zoom, min(self.topology_max_zoom, float(getattr(self, "topology_zoom", 1.0))))

        def S(v: float) -> int:
            return int(round(v * z))

        def fz(n: int) -> int:
            return max(6, min(26, int(round(n * z))))

        fz7, fz8, fz9, fz10, fz11 = fz(7), fz(8), fz(9), fz(10), fz(11)

        # 画布分区唯一规则：topology_line_side_for_node == main → lane_main_y（上半），== backup → lane_backup_y（下半）。
        # 间距收敛：默认100%下尽量能直接看到主线与备线。
        SPACING_SCALE = 1.2
        # 顶部留白略加大，避免首行箭头/说明被裁切；主/备纵距加宽，上下半区更易区分。
        TOP_PAD = S(128)
        # LAN-MAP 列紧贴本机左侧：右缘与本机左缘相距 10px；宽度与高度收敛，避免比本机圆标更抢眼。
        # 主机与 LAN-MAP 保持适中距离
        x_lanmap, lanmap_w, gap_lanmap_host = S(16), S(232), S(16)
        x_host = x_lanmap + lanmap_w + gap_lanmap_host
        lane_main_y = TOP_PAD + S(160)
        lane_backup_y = lane_main_y + S(640)
        lane_unknown_y = lane_backup_y + S(420)
        lane_gap = S(96)
        node_w, node_h = S(172), S(46)
        note_text_width = S(440)

        def draw_node(x: int, y: int, text: str, fill: str = "#ffffff") -> None:
            self.topology_canvas.create_rectangle(x, y, x + node_w, y + node_h, fill=fill, outline="#111827", width=1)
            self.topology_canvas.create_text(
                x + node_w / 2, y + node_h / 2, text=text, width=max(S(60), node_w - S(8)), font=("Arial", fz10)
            )

        def _tunnel_node_text(tn: TunnelNode, title: str) -> str:
            desc = (tn.description or "").strip()
            if desc:
                return f"{title}\n({desc})"
            return title

        def draw_host(x: int, y: int, text: str, fill: str = "#f3f4f6") -> None:
            d = S(58)
            self.topology_canvas.create_oval(x, y, x + d, y + d, fill=fill, outline="#111827", width=1)
            self.topology_canvas.create_text(
                x + d / 2, y + d / 2, text=text, width=d + S(34), font=("Arial", fz10)
            )

        def draw_bgp_row(x: int, y: int, b_bind: BgpBinding) -> Tuple[int, int]:
            """BGP：画布仅突出邻居 IP；宣告前缀少量时一行展示，多则提示见解析备注。"""
            d = S(44)
            neighbor = b_bind.neighbor
            self.topology_canvas.create_oval(x, y, x + d, y + d, fill="#cffafe", outline="#0e7490", width=1)
            self.topology_canvas.create_text(x + d / 2, y + d / 2, text="BGP", font=("Arial", fz8, "bold"), fill="#0c4a6e")
            ty = y + d + S(6)
            self.topology_canvas.create_text(
                x + d / 2, ty, text=neighbor, anchor=tk.N, font=("Consolas", fz10, "bold"), fill="#111827"
            )
            ty += S(22)
            adv = b_bind.advertised_prefixes if isinstance(b_bind.advertised_prefixes, list) else []
            hint_bottom = ty
            if adv:
                if len(adv) <= 3:
                    adv_txt = "宣告 " + ",".join(adv)
                    self.topology_canvas.create_text(
                        x + d / 2,
                        ty,
                        text=adv_txt,
                        anchor=tk.N,
                        font=("Arial", fz7),
                        fill="#4b5563",
                        width=S(200),
                        justify=tk.CENTER,
                    )
                    hint_bottom = ty + S(36)
                else:
                    self.topology_canvas.create_text(
                        x + d / 2,
                        ty,
                        text=f"宣告 {len(adv)} 条（详见解析备注/Mermaid）",
                        anchor=tk.N,
                        font=("Arial", fz7),
                        fill="#6b7280",
                        width=S(200),
                        justify=tk.CENTER,
                    )
                    hint_bottom = ty + S(18)
            return x + d // 2, hint_bottom

        def draw_arrow(x1: int, y1: int, x2: int, y2: int, label: str = "", color: str = "#111827") -> None:
            self.topology_canvas.create_line(x1, y1, x2, y2, arrow=tk.LAST, width=max(1, S(2)), fill=color)
            if label:
                self.topology_canvas.create_text(
                    (x1 + x2) / 2, (y1 + y2) / 2 - S(12), text=label, font=("Arial", fz9), fill=color
                )

        def draw_track_fallback_arrow(x1: int, y1: int, x2: int, y2: int, track_name: str) -> None:
            dash = (max(2, S(4)), max(2, S(4)))
            self.topology_canvas.create_line(x1, y1, x2, y2, dash=dash, width=max(1, S(1)), fill="#2563eb")
            if track_name:
                self.topology_canvas.create_text(
                    (x1 + x2) / 2,
                    (y1 + y2) / 2 + S(12),
                    text=f"track:{track_name}",
                    font=("Arial", fz8),
                    fill="#1d4ed8",
                )

        def draw_bgp_dashed_to_tunnel(hx: int, hy: int, tx: int, ty: int, color: str = "#0e7490") -> None:
            """BGP 虚线：点到点折线（水平→垂直到隧道中心）。"""
            dw = max(1, S(1))
            dash = (max(2, S(4)), max(2, S(4)))
            if hx <= tx:
                self.topology_canvas.create_line(hx, hy, tx, hy, tx, ty, dash=dash, width=dw, fill=color)
            else:
                self.topology_canvas.create_line(hx, hy, hx, ty, tx, ty, dash=dash, width=dw, fill=color)

        tunnel_nodes: List[TunnelNode] = [v for v in tunnels.values() if isinstance(v, TunnelNode)]
        tunnel_by_name = {t.name: t for t in tunnel_nodes}
        _op = overseas_parent if isinstance(overseas_parent, dict) else {}
        line_side_map: Dict[str, str] = {}
        if isinstance(line_side_map_raw, dict):
            for k, v in line_side_map_raw.items():
                ks = str(k)
                vs = str(v).strip()
                line_side_map[ks] = vs if vs in ("main", "backup", "unknown") else "unknown"

        def _line_side(t: TunnelNode) -> str:
            v = line_side_map.get(t.name, "")
            if v in ("main", "backup", "unknown"):
                return v
            return topology_line_side_for_node(t, tunnel_by_name, _op)

        access_by_side = {
            "main": [t for t in tunnel_nodes if t.inferred_role in ACCESS_TRANSPORT_ROLES and _line_side(t) == "main"],
            "backup": [t for t in tunnel_nodes if t.inferred_role in ACCESS_TRANSPORT_ROLES and _line_side(t) == "backup"],
            "unknown": [t for t in tunnel_nodes if t.inferred_role in ACCESS_TRANSPORT_ROLES and _line_side(t) == "unknown"],
        }
        upe_by_side = {
            "main": [t for t in tunnel_nodes if t.inferred_role == "gre-upe" and _line_side(t) == "main"],
            "backup": [t for t in tunnel_nodes if t.inferred_role == "gre-upe" and _line_side(t) == "backup"],
            "unknown": [t for t in tunnel_nodes if t.inferred_role == "gre-upe" and _line_side(t) == "unknown"],
        }

        out_by_side = {"main": [], "backup": [], "unknown": []}
        for t in tunnel_nodes:
            if t.inferred_role != "gre-overseas":
                continue
            out_by_side[_line_side(t)].append(t)

        default_map: Dict[str, str] = {}
        for kind, tun, _ch in default_targets:
            default_map[tun] = str(kind)
        policy_map: Dict[str, List[str]] = {}
        if isinstance(policy_targets, list):
            for p in policy_targets:
                if len(p) == 3:
                    pname, _, tun = p
                    policy_map.setdefault(tun, []).append(str(pname))

        bgp_list = [b for b in (bgp or []) if isinstance(b, BgpBinding)]

        def _role_tag(role: str, kind: str) -> str:
            if role in ACCESS_TRANSPORT_ROLES:
                return {"openvpn": "OpenVPN", "ipsec-vti": "IPsec-VTI", "ipsec-policy": "策略IPsec"}.get(role, role)
            if role == "local-iface":
                return "BGP"
            return (kind or role or "iface")[:10]

        def _anchors_for_lane(lane: str) -> List[str]:
            acc: List[str] = []
            for b0 in bgp_list:
                if getattr(b0, "lane_side", "") != lane:
                    continue
                a = (getattr(b0, "anchor_tunnel", "") or "").strip()
                if a and a not in acc:
                    acc.append(a)
            return acc

        def _underlay_lane_order(lane: str, skip_upe_iface: str = "") -> List[str]:
            """左侧接入链槽位：含首接入 + BGP anchor_tunnel。

            若 anchor 与「本侧即将画在 UPE 列」的 gre-upe 为同一接口，不得重复放入链路，
            否则会出现 dum0→tun1518(灰)→tun1518(绿) 的双节点（根因：anchor 与 UPE 列重复绘制）。
            """
            lane_access = [t.name for t in access_by_side[lane]] if access_by_side.get(lane) else []
            anchors = _anchors_for_lane(lane)
            seen: set[str] = set()
            row: List[str] = []
            for vt0 in lane_access:
                if not vt0 or vt0 in seen:
                    continue
                row.append(vt0)
                seen.add(vt0)
            for a in anchors:
                if a in seen:
                    continue
                tn_a = tunnel_by_name.get(a)
                if tn_a and _line_side(tn_a) != lane:
                    # Anchor tunnel can be hinted by BGP lane; still enforce node's own line side.
                    continue
                if tn_a and getattr(tn_a, "inferred_role", "") not in ACCESS_TRANSPORT_ROLES and getattr(
                    tn_a, "inferred_role", ""
                ) != "local-iface":
                    # Underlay lane only hosts access transport anchors.
                    # Prevent gre-overseas/gre-upe nodes from being drawn twice (underlay + overseas/UPE columns).
                    continue
                if (
                    skip_upe_iface
                    and a == skip_upe_iface
                    and tn_a
                    and getattr(tn_a, "inferred_role", "") == "gre-upe"
                ):
                    continue
                row.append(a)
                seen.add(a)
            return row

        slot_w = node_w + S(28)
        max_ul = max(1, len(_underlay_lane_order("main")), len(_underlay_lane_order("backup")))
        x_chain0 = x_host + S(50)
        x_upe0 = x_chain0 + max_ul * slot_w + S(40)
        x_out0 = x_upe0 + S(250)
        x_note0 = x_out0 + S(150)

        self.topology_canvas.create_text(S(20), lane_main_y - S(18), text="主线", anchor=tk.W, font=("Arial", fz11, "bold"))
        self.topology_canvas.create_text(S(20), lane_backup_y - S(18), text="备线", anchor=tk.W, font=("Arial", fz11, "bold"))
        self.topology_canvas.create_text(S(20), lane_unknown_y - S(18), text="未知线路", anchor=tk.W, font=("Arial", fz10, "bold"), fill="#6b7280")
        if isinstance(dnat_prefixes, list) and dnat_prefixes:
            if len(dnat_prefixes) > 4:
                dnat_text = f"DNAT网段 {len(dnat_prefixes)}条（详见NAT梳理）"
            else:
                dnat_text = "DNAT网段 " + ",".join(str(x) for x in dnat_prefixes)
            self.topology_canvas.create_text(
                S(20), TOP_PAD + S(20), text=dnat_text, anchor=tk.W, font=("Arial", fz9), fill="#7c3aed"
            )
        dr = topology.get("default_route_resolution")
        if isinstance(dr, dict):
            chdr = dr.get("nh_chain") or []
            tun_dr = str(dr.get("tunnel") or "")
            if isinstance(chdr, list) and chdr and tun_dr:
                hop_txt = " → ".join(str(x) for x in chdr) + f" → {tun_dr}"
                if len(hop_txt) > 100:
                    hop_txt = hop_txt[:97] + "…"
                self.topology_canvas.create_text(
                    S(20),
                    TOP_PAD + S(44),
                    text=f"默认路由递归: {hop_txt}",
                    anchor=tk.NW,
                    font=("Arial", fz8),
                    fill="#0f766e",
                    width=S(720),
                )

        default_iface = ""
        if isinstance(dr, dict):
            default_iface = str(dr.get("tunnel") or "").strip()
        if not default_iface and default_targets:
            default_iface = str(default_targets[0][1]).strip()

        def draw_default_corner(x0: int, y0: int) -> None:
            self.topology_canvas.create_rectangle(
                x0 + node_w - S(66),
                y0 - S(18),
                x0 + node_w + S(4),
                y0 + S(2),
                fill="#fef3c7",
                outline="#b45309",
                width=1,
            )
            self.topology_canvas.create_text(
                x0 + node_w - S(31),
                y0 - S(8),
                text="default",
                anchor=tk.CENTER,
                font=("Arial", fz9, "bold"),
                fill="#b45309",
            )

        upe_y_by_name: Dict[str, int] = {}
        vt_y_by_name: Dict[str, int] = {}
        vt_x_by_name: Dict[str, int] = {}
        vt_host_segments: List[Tuple[str, int, int, int, int]] = []  # (vt_name, x1,y1,x2,y2) host→首接入
        out_y_by_name_global: Dict[str, int] = {}
        out_x_by_name_global: Dict[str, int] = {}
        tunnel_ui_box: Dict[str, Tuple[int, int, int, int]] = {}  # iface -> (x,y,w,h) top-left of drawn tunnel node
        bgp_anchor_box: Dict[str, Tuple[int, int, int, int]] = {}  # f"{iface}|{lane}" -> box for BGP layout
        # out_name -> [(fallback_parent_tunnel, track_name)]
        out_track_fallback_parents: Dict[str, List[Tuple[str, str]]] = {}
        deferred_track_fallback_edges: List[Tuple[str, str, str]] = []  # (parent_tunnel, out_tunnel, track_name)

        def _route_hits_ip(dst: str, ipx: str) -> bool:
            try:
                return ipaddress.ip_address(ipx) in ipaddress.ip_network(dst, strict=False)
            except Exception:
                return False

        for t in tunnel_nodes:
            if t.inferred_role != "gre-overseas" or not (t.remote or "").strip():
                continue
            rmt = (t.remote or "").strip()
            if not rmt:
                continue
            primary_parent = str(overseas_parent.get(t.name, "")) if isinstance(overseas_parent, dict) else ""
            if not primary_parent or primary_parent not in tunnel_by_name:
                continue
            primary_side = _line_side(tunnel_by_name[primary_parent])
            if primary_side not in ("main", "backup"):
                continue
            seen_fb: set[Tuple[str, str]] = set()
            matched_routes: List[RouteEdge] = []
            dst_remote32 = f"{rmt}/32"
            for r in routes:
                if not isinstance(r, RouteEdge):
                    continue
                if not (r.via_tunnel or "").strip():
                    continue
                rdst = str(r.destination or "").strip()
                # Strict: track fallback is only for this overseas tunnel remote /32 route.
                if rdst != dst_remote32:
                    continue
                matched_routes.append(r)
            if not matched_routes:
                continue
            has_track_control = any((mr.track_name or "").strip() for mr in matched_routes)
            if not has_track_control:
                continue
            for r in matched_routes:
                via = str(r.via_tunnel).strip()
                trn = str(r.track_name).strip() or "failover"
                if via == primary_parent:
                    continue
                if via not in tunnel_by_name:
                    continue
                via_side = _line_side(tunnel_by_name[via])
                # Draw fallback only when it is an explicit main/backup counterpart path.
                if via_side not in ("main", "backup") or via_side == primary_side:
                    continue
                key = (via, trn)
                if key in seen_fb:
                    continue
                seen_fb.add(key)
                out_track_fallback_parents.setdefault(t.name, []).append(key)

        host_y = int((lane_main_y + lane_backup_y) / 2)
        draw_host(x_host, host_y, hostname, "#f3f4f6")
        host_anchor_x = x_host + S(58)
        host_anchor_y = host_y + S(29)

        if isinstance(policy_local_targets, list) and policy_local_targets:
            nrules = len(policy_local_targets)
            cap = 180
            if nrules > cap:
                rules_show = policy_local_targets[:cap]
                lines_txt = "\n".join(f"· {str(x[0])[:72]}" for x in rules_show)
                lines_txt += f"\n· …其余 {nrules - cap} 条（详见解析备注 / 配置 policy route LAN-MAP）"
                nlines = cap + 1
            else:
                lines_txt = "\n".join(f"· {str(x[0])[:72]}" for x in policy_local_targets)
                nlines = nrules
            lg_inner_h = S(52) + nlines * S(13)
            lg_h = min(S(3200), max(S(96), lg_inner_h))
            lg_y = max(TOP_PAD // 3, int(host_y - lg_h / 2))
            self.topology_canvas.create_rectangle(
                x_lanmap, lg_y, x_lanmap + lanmap_w, lg_y + lg_h, fill="#fff7ed", outline="#c2410c", width=1
            )
            gw_title = f"本地网关({policy_local_targets[0][1]})"
            self.topology_canvas.create_text(
                x_lanmap + lanmap_w / 2,
                lg_y + S(12),
                text=gw_title,
                anchor=tk.N,
                font=("Arial", fz10, "bold"),
                fill="#9a3412",
            )
            self.topology_canvas.create_text(
                x_lanmap + lanmap_w / 2,
                lg_y + S(30),
                text="LAN-MAP / PBR（经本地表）",
                anchor=tk.N,
                font=("Arial", fz8),
                fill="#7c2d12",
            )
            self.topology_canvas.create_text(
                x_lanmap + S(10),
                lg_y + S(48),
                text=lines_txt,
                anchor=tk.NW,
                font=("Consolas", fz8),
                fill="#431407",
                width=max(S(40), lanmap_w - S(18)),
            )
            lx0 = x_lanmap + lanmap_w
            ly0 = int(lg_y + lg_h / 2)
            hxe = x_host + S(4)
            self.topology_canvas.create_line(lx0, ly0, hxe, host_anchor_y, arrow=tk.LAST, width=max(1, S(2)), fill="#c2410c")

        lane_specs: List[Tuple[str, int]] = [("main", lane_main_y), ("backup", lane_backup_y), ("unknown", lane_unknown_y)]
        lane_base_map = {k: v for k, v in lane_specs}
        lane_tops: Dict[str, int] = {}
        lane_bottoms: Dict[str, int] = {}
        for idx, (lname, lbase) in enumerate(lane_specs):
            prev_base = lane_specs[idx - 1][1] if idx > 0 else None
            next_base = lane_specs[idx + 1][1] if idx + 1 < len(lane_specs) else None
            if prev_base is None:
                top_bound = TOP_PAD + S(40)
            else:
                top_bound = int((prev_base + lbase) / 2) + S(8)
            if next_base is None:
                bottom_bound = lbase + S(1200)
            else:
                bottom_bound = int((lbase + next_base) / 2) - S(8)
            lane_tops[lname] = top_bound
            lane_bottoms[lname] = bottom_bound

        for side, base_y in lane_specs:
            out_y_by_name: Dict[str, int] = {}
            side_out = out_by_side[side]

            vt = access_by_side[side][0] if access_by_side[side] else None
            if vt is None and isinstance(overseas_parent, dict):
                for out in side_out:
                    parent = str(overseas_parent.get(out.name, ""))
                    pnode = tunnel_by_name.get(parent)
                    if pnode and pnode.inferred_role in ACCESS_TRANSPORT_ROLES and _line_side(pnode) == side:
                        vt = pnode
                        break

            upe = None
            if vt:
                for pair in vtun_to_upe_pairs:
                    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                        continue
                    if str(pair[0]) != vt.name:
                        continue
                    cand = tunnel_by_name.get(str(pair[1]))
                    if cand and getattr(cand, "inferred_role", "") == "gre-upe" and _line_side(cand) == side:
                        upe = cand
                        break
            if upe is None:
                upe = upe_by_side[side][0] if upe_by_side[side] else None
            if upe is None and isinstance(overseas_parent, dict):
                for out in side_out:
                    parent = str(overseas_parent.get(out.name, ""))
                    pnode = tunnel_by_name.get(parent)
                    if pnode and pnode.inferred_role == "gre-upe" and _line_side(pnode) == side:
                        upe = pnode
                        break

            underlays = _underlay_lane_order(side, upe.name if upe else "")
            x_upe_lane = x_upe0
            y_mid = base_y + node_h // 2
            for idx, uname in enumerate(underlays):
                tn = tunnel_by_name.get(uname)
                if not tn:
                    continue
                xu = x_chain0 + idx * slot_w
                role = getattr(tn, "inferred_role", "") or ""
                box_t = (xu, base_y, node_w, node_h)
                bgp_anchor_box[f"{uname}|{side}"] = box_t
                vt_y_by_name[uname] = base_y
                vt_x_by_name[uname] = xu
                if role == "local-iface":
                    # 仅作 BGP 圆标锚点，不画「方框 BGP」以免与圆形 BGP 重复
                    continue
                if role == "openvpn":
                    acc_fill = "#dbeafe"
                elif role == "ipsec-policy":
                    acc_fill = "#ddd6fe"
                elif role == "ipsec-vti":
                    acc_fill = "#e0e7ff"
                else:
                    acc_fill = "#e5e7eb"
                tag = _role_tag(role, tn.kind)
                draw_node(xu, base_y, _tunnel_node_text(tn, f"{uname}\n{tag}"), acc_fill)
                tunnel_ui_box[uname] = box_t
                if default_iface and uname == default_iface:
                    draw_default_corner(xu, base_y)
            visible_chain = [
                u
                for u in underlays
                if tunnel_by_name.get(u) and getattr(tunnel_by_name[u], "inferred_role", "") != "local-iface"
            ]
            if visible_chain:
                x_first = vt_x_by_name[visible_chain[0]]
                x2, y2 = int(x_first + S(10)), int(y_mid)
                self.topology_canvas.create_line(
                    int(host_anchor_x), int(host_anchor_y), x2, y2, arrow=tk.LAST, width=max(1, S(2)), fill="#111827"
                )
                vt_host_segments.append((visible_chain[0], int(host_anchor_x), int(host_anchor_y), x2, y2))
                # Do not chain peer access tunnels by layout order.
                # Additional access tunnels in the same lane are independent unless proven by structural edges.
                for uname in visible_chain[1:]:
                    x_u = vt_x_by_name.get(uname)
                    if x_u is None:
                        continue
                    x2u, y2u = int(x_u + S(10)), int(y_mid)
                    self.topology_canvas.create_line(
                        int(host_anchor_x),
                        int(host_anchor_y),
                        x2u,
                        y2u,
                        arrow=tk.LAST,
                        width=max(1, S(2)),
                        fill="#111827",
                    )
                    vt_host_segments.append((uname, int(host_anchor_x), int(host_anchor_y), x2u, y2u))

            if upe:
                draw_node(x_upe_lane, base_y, _tunnel_node_text(upe, upe.name), "#dcfce7")
                upe_box = (x_upe_lane, base_y, node_w, node_h)
                tunnel_ui_box[upe.name] = upe_box
                bgp_anchor_box[f"{upe.name}|{side}"] = upe_box
                upe_y_by_name[upe.name] = base_y
                if default_iface and upe.name == default_iface:
                    draw_default_corner(x_upe_lane, base_y)
                src_x_end = None
                for idx in range(len(underlays) - 1, -1, -1):
                    uname = underlays[idx]
                    tn2 = tunnel_by_name.get(uname)
                    if tn2 and getattr(tn2, "inferred_role", "") in ACCESS_TRANSPORT_ROLES:
                        src_x_end = x_chain0 + idx * slot_w + node_w
                        break
                if src_x_end is None and visible_chain:
                    src_x_end = vt_x_by_name[visible_chain[-1]] + node_w
                elif src_x_end is None and underlays:
                    src_x_end = x_chain0 + (len(underlays) - 1) * slot_w + node_w
                if src_x_end is not None:
                    draw_arrow(src_x_end, base_y + node_h / 2, x_upe_lane, base_y + node_h / 2)
                elif not underlays:
                    draw_arrow(host_anchor_x, host_anchor_y, x_upe_lane, base_y + node_h / 2)

            if not side_out:
                continue
            shown = side_out
            # 防重叠标准：
            # 1) 间距 >= 节点高度 + padding
            # 2) 间距 >= 备注文本块高度 + padding（有 route_label 时更高）
            # 3) 同时限制在本 lane 上下边界内，避免跨 lane 越界
            max_note_block_h = S(86)
            has_route_label = any(policy_map.get(x.name, []) for x in shown)
            if has_route_label:
                max_note_block_h = S(112)
            item_h = max(node_h, max_note_block_h)
            gap = max(lane_gap, item_h + S(12))
            start_y = int(base_y - ((len(shown) - 1) * gap) / 2)
            lane_top = lane_tops.get(side, TOP_PAD + S(20))
            lane_bottom = lane_bottoms.get(side, base_y + S(1200))
            start_min = lane_top
            start_max = lane_bottom - (len(shown) - 1) * gap - item_h
            if start_max < start_min:
                start_max = start_min
            start_y = max(start_min, min(start_max, start_y))
            # 若单列放不下，自动分列，避免跨 lane 越界重叠。
            lane_height = max(S(1), lane_bottom - lane_top)
            rows_per_col = max(1, int((lane_height - item_h) / max(S(1), gap)) + 1)
            # 动态扩列：确保“节点 + 备注块”不会压到下一列节点
            note_offset_x = node_w + S(28)
            col_step = max(S(260), note_offset_x + note_text_width + S(36))
            for i, out in enumerate(shown):
                col_idx = i // rows_per_col
                row_idx = i % rows_per_col
                ox = x_out0 + col_idx * col_step
                oy = lane_top + row_idx * gap
                out_y_by_name[out.name] = oy
                out_y_by_name_global[out.name] = oy
                out_x_by_name_global[out.name] = ox
                draw_node(ox, oy, _tunnel_node_text(out, out.name), "#fee2e2")
                out_box = (ox, oy, node_w, node_h)
                tunnel_ui_box[out.name] = out_box
                bgp_anchor_box[f"{out.name}|{side}"] = out_box
                edge_label = ""
                route_bits: List[str] = []
                pnames = policy_map.get(out.name, [])
                if pnames:
                    route_bits.append(f"策略: {pnames[0]}")
                route_label = "；".join(route_bits)
                # Keep edge label short; put detailed route label on right note panel.
                if (default_iface and out.name == default_iface) or out.name in default_map:
                    edge_label = "default"
                parent = ""
                if isinstance(overseas_parent, dict):
                    parent = str(overseas_parent.get(out.name, ""))
                y_dst = int(oy + node_h / 2)
                if parent in upe_y_by_name:
                    py = upe_y_by_name[parent]
                    y_src = int(py + node_h / 2)
                    draw_arrow(int(x_upe0 + node_w), y_src, int(ox), y_dst, edge_label)
                elif parent in vt_y_by_name:
                    py = vt_y_by_name[parent]
                    px = vt_x_by_name.get(parent, x_chain0)
                    y_src_vt = int(py + node_h / 2)
                    draw_arrow(int(px + node_w), y_src_vt, int(ox), y_dst, edge_label)
                elif parent == "host":
                    draw_arrow(int(host_anchor_x + S(4)), int(host_anchor_y), int(ox), y_dst, edge_label)
                else:
                    # No evidence => no guessed line.
                    pass
                # Extra fallback path controlled by track: draw additional dashed edge.
                for fb_parent, fb_track in out_track_fallback_parents.get(out.name, []):
                    if fb_parent in upe_y_by_name:
                        py2 = upe_y_by_name[fb_parent]
                        y_src2 = int(py2 + node_h / 2)
                        draw_track_fallback_arrow(int(x_upe0 + node_w), y_src2, int(ox), y_dst, fb_track)
                    elif fb_parent in vt_y_by_name:
                        py2 = vt_y_by_name[fb_parent]
                        px2 = vt_x_by_name.get(fb_parent, x_chain0)
                        y_src2 = int(py2 + node_h / 2)
                        draw_track_fallback_arrow(int(px2 + node_w), y_src2, int(ox), y_dst, fb_track)
                    else:
                        deferred_track_fallback_edges.append((fb_parent, out.name, fb_track))
                if (default_iface and out.name == default_iface) or out.name in default_map:
                    draw_default_corner(ox, oy)

                srcs = []
                if isinstance(outbound_sources, dict):
                    srcs = outbound_sources.get(out.name, []) or []
                rules = []
                if isinstance(outbound_rule_info, dict):
                    rules = outbound_rule_info.get(out.name, []) or []
                if rules:
                    uniq_src = sorted(set(srcs))
                    if len(uniq_src) > 4:
                        src_text = f"SNAT网段 {len(uniq_src)}条（详见NAT梳理）"
                    else:
                        src_text = "SNAT网段 " + ",".join(uniq_src) if uniq_src else "SNAT网段(未识别)"
                elif srcs:
                    uniq_src = sorted(set(srcs))
                    if len(uniq_src) > 4:
                        src_text = f"SNAT网段 {len(uniq_src)}条（详见NAT梳理）"
                    else:
                        src_text = f"SNAT网段 {','.join(uniq_src)}"
                else:
                    src_text = "SNAT网段(未识别)"
                note_x = ox + note_offset_x
                self.topology_canvas.create_text(
                    note_x,
                    oy + S(4),
                    text=src_text,
                    anchor=tk.NW,
                    font=("Arial", fz9),
                    fill="#111827",
                    width=note_text_width,
                )
                if route_label:
                    self.topology_canvas.create_text(
                        note_x,
                        oy + S(28),
                        text=route_label,
                        anchor=tk.NW,
                        font=("Arial", fz9),
                        fill="#7c3aed" if pnames else "#b45309",
                        width=note_text_width,
                    )

        # Draw deferred track-fallback edges after all lane nodes are placed.
        # This keeps "track + 主备隧道链" 关联可见 even when nodes land in different lanes.
        for fb_parent, out_name, fb_track in deferred_track_fallback_edges:
            pb = tunnel_ui_box.get(fb_parent)
            ob = tunnel_ui_box.get(out_name)
            if not pb or not ob:
                continue
            px, py, pw, ph = pb
            ox, oy, _ow, oh = ob
            draw_track_fallback_arrow(
                int(px + pw),
                int(py + ph / 2),
                int(ox),
                int(oy + oh / 2),
                fb_track,
            )

        # BGP: under the local tunnel this session is bound to (anchor_tunnel = update-source 所在隧道或 neighbor/* 的 via_tunnel).
        if isinstance(bgp, list) and bgp:

            def _draw_bgp_hint_lines(hx: int, hy: int, b0: BgpBinding) -> None:
                hint0 = (
                    str(getattr(b0, "anchor_tunnel", "") or "").strip()
                    or str(getattr(b0, "egress_hint", "") or "").strip()
                    or str(getattr(b0, "transport_tunnel", "") or "").strip()
                )
                hint_tun = ""

                def _tunnel_target_xy(tname: str) -> Optional[Tuple[int, int]]:
                    if tname in vt_y_by_name:
                        vx0 = vt_x_by_name.get(tname, x_chain0)
                        return int(vx0 + node_w // 2), int(vt_y_by_name[tname] + node_h // 2)
                    if tname in upe_y_by_name:
                        uy0 = upe_y_by_name[tname]
                        return int(x_upe0 + node_w // 2), int(uy0 + node_h // 2)
                    if tname in out_y_by_name_global:
                        oy0 = out_y_by_name_global[tname]
                        ox0 = out_x_by_name_global.get(tname, x_out0)
                        return int(ox0 + node_w // 2), int(oy0 + node_h // 2)
                    return None

                if hint0 in vt_y_by_name:
                    hint_tun = hint0
                elif hint0 in tunnel_by_name:
                    tnh = tunnel_by_name[hint0]
                    if tnh.inferred_role in ACCESS_TRANSPORT_ROLES and hint0 in vt_y_by_name:
                        hint_tun = hint0
                    elif tnh.inferred_role == "gre-upe" and hint0 in upe_y_by_name:
                        txy = _tunnel_target_xy(hint0)
                        if txy:
                            draw_bgp_dashed_to_tunnel(int(hx), int(hy), txy[0], txy[1])
                        return
                    elif tnh.inferred_role == "gre-overseas":
                        hint_tun = hint0
                if hint_tun:
                    txy = _tunnel_target_xy(hint_tun)
                    if txy:
                        draw_bgp_dashed_to_tunnel(int(hx), int(hy), txy[0], txy[1])

            def _layout_bgp_below_anchor_box(band: List[BgpBinding], box: Tuple[int, int, int, int]) -> None:
                """同一锚点下 BGP 纵向排列，避免图标与文字横向挤压重叠。"""
                if not band:
                    return
                xl, yt, w, h = box
                d0 = S(44)
                gap_below = S(20)
                y_cur = yt + h + gap_below
                cx = xl + w // 2
                for b0 in band:
                    hx0, hy_bottom = draw_bgp_row(cx - d0 // 2, y_cur, b0)
                    _draw_bgp_hint_lines(hx0, hy_bottom, b0)
                    y_cur = hy_bottom + S(26)

            def _bgp_layout_box(b0: BgpBinding) -> Optional[Tuple[int, int, int, int]]:
                """按解析结果 anchor_tunnel + lane_side 取画布方框（严格匹配，不回退）。"""
                at = str(getattr(b0, "anchor_tunnel", "") or "").strip()
                if not at:
                    return None
                ln = line_side_map.get(at, "unknown")
                if ln not in ("main", "backup", "unknown"):
                    ln = "unknown"
                k = f"{at}|{ln}"
                if k in bgp_anchor_box:
                    return bgp_anchor_box[k]
                return None

            by_key: Dict[str, List[BgpBinding]] = {}
            for b in bgp:
                if not isinstance(b, BgpBinding):
                    continue
                at = str(getattr(b, "anchor_tunnel", "") or "").strip()
                if not at:
                    continue
                ln = line_side_map.get(at, "unknown")
                if ln not in ("main", "backup", "unknown"):
                    ln = "unknown"
                key = f"{at}|{ln}"
                by_key.setdefault(key, []).append(b)
            for key in sorted(by_key.keys()):
                band0 = sorted(by_key[key], key=lambda x: x.neighbor)[:8]
                b0 = band0[0]
                box0 = _bgp_layout_box(b0)
                if not box0:
                    continue
                _layout_bgp_below_anchor_box(band0, box0)

        # If default egress is behind a vtun hop, label the host->vtun segment explicitly.
        default_vtun = ""
        if isinstance(default_targets, list) and default_targets:
            dtun = str(default_targets[0][1])
            node = tunnel_by_name.get(dtun)
            if node and node.inferred_role in ACCESS_TRANSPORT_ROLES:
                default_vtun = dtun
            elif node and node.inferred_role == "gre-overseas" and isinstance(overseas_parent, dict):
                parent = str(overseas_parent.get(dtun, ""))
                if parent in tunnel_by_name and tunnel_by_name[parent].inferred_role in ACCESS_TRANSPORT_ROLES:
                    default_vtun = parent
        if default_vtun:
            for vt_name, x1, y1, x2, y2 in vt_host_segments:
                if vt_name != default_vtun:
                    continue
                t_along = 0.55
                mx = int(x1 + t_along * (x2 - x1))
                my = int(y1 + t_along * (y2 - y1)) - S(18)
                self.topology_canvas.create_text(mx, my, text="default", font=("Arial", fz10, "bold"), fill="#b45309")
                break

        bbox_all = self.topology_canvas.bbox("all")
        pad_lr, pad_top, pad_bottom = S(120), S(150), S(200)
        remark_extra = S(220)
        remark_right = float(x_note0 + note_text_width + remark_extra)
        if bbox_all:
            left = float(bbox_all[0]) - pad_lr
            top = float(bbox_all[1]) - pad_top
            right = float(bbox_all[2]) + pad_lr
            bot = float(bbox_all[3]) + pad_bottom
            wide = max(right, remark_right + pad_lr)
            high = max(bot, float(lane_unknown_y + node_h + pad_bottom))
            self.topology_canvas.configure(scrollregion=(left, top, wide, high))
        else:
            total_width = max(float(S(2880)), remark_right + float(pad_lr))
            total_height = max(
                S(1720),
                lane_unknown_y + node_h + S(200) + max(1, len(out_by_side["unknown"])) * lane_gap + S(720),
            )
            self.topology_canvas.configure(scrollregion=(0, 0, total_width, total_height))
        self.topology_canvas.xview_moveto(max(0.0, min(1.0, x_saved)))
        self.topology_canvas.yview_moveto(max(0.0, min(1.0, y_saved)))

    def export_csv(self) -> None:
        if not self.rows:
            messagebox.showinfo("无数据", "请先执行解析，再导出 CSV。")
            return

        save_path = filedialog.asksaveasfilename(
            title="导出（输入导出文件夹名称）",
            defaultextension="",
            filetypes=[("Folder Name", "*.*")],
            initialfile="梳理结果",
        )
        if not save_path:
            return

        try:
            out_dir = Path(save_path)
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = out_dir.name

            with open(out_dir / f"{stem}.nat.csv", "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "rule",
                        "source_ip",
                        "egress_name",
                        "egress_remark",
                        "fake_ip",
                        "real_ip",
                    ],
                )
                writer.writeheader()
                writer.writerows(self.rows)

            # Export all other outputs beside NAT CSV.
            (out_dir / f"{stem}.topology_summary.txt").write_text(
                self.topology_summary.get("1.0", tk.END).strip(), encoding="utf-8"
            )
            (out_dir / f"{stem}.topology_mermaid.mmd").write_text(
                self.topology_mermaid.get("1.0", tk.END).strip(), encoding="utf-8"
            )
            if hasattr(self, "parse_ledger_text"):
                (out_dir / f"{stem}.parse_ledger.txt").write_text(
                    self.parse_ledger_text.get("1.0", tk.END).strip(), encoding="utf-8"
                )
            if hasattr(self, "ip_digest_text"):
                (out_dir / f"{stem}.ip_digest.txt").write_text(
                    self.ip_digest_text.get("1.0", tk.END).strip(), encoding="utf-8"
                )
            scene = self._current_scene()
            if scene in self.scene_widgets:
                cfg = self.scene_widgets[scene]["config"].get("1.0", tk.END).strip()
                mp = self.scene_widgets[scene]["mapping"].get("1.0", tk.END).strip()
                (out_dir / f"{stem}.input_config.txt").write_text(cfg, encoding="utf-8")
                (out_dir / f"{stem}.input_mapping.txt").write_text(mp, encoding="utf-8")

            self.status_var.set(f"导出成功: {out_dir}")
        except Exception as exc:
            messagebox.showerror("导出失败", f"无法导出结果:\n{exc}")

    def clear_all(self) -> None:
        for scene in self.scene_widgets:
            self.scene_widgets[scene]["config"].delete("1.0", tk.END)
            self.scene_widgets[scene]["mapping"].delete("1.0", tk.END)
        self._refresh_table([])
        self.topology_canvas.delete("all")
        self.topology_zoom = 1.0
        self._last_er_topology = None
        if hasattr(self, "topology_zoom_var"):
            self.topology_zoom_var.set(
                "缩放: 100%（Ctrl+滚轮缩放，滚轮纵向滚动，Shift+滚轮横向滚动，左键拖拽平移）"
            )
        self.topology_mermaid.delete("1.0", tk.END)
        self.topology_summary.delete("1.0", tk.END)
        if hasattr(self, "parse_ledger_text"):
            self.parse_ledger_text.delete("1.0", tk.END)
        if hasattr(self, "ip_digest_text"):
            self.ip_digest_text.delete("1.0", tk.END)
        if hasattr(self, "unused_config_text"):
            self.unused_config_text.delete("1.0", tk.END)
        self.rows = []
        self.status_var.set("已清空 ER/USG 输入与结果。")


def main() -> None:
    root = tk.Tk()
    app = ERAnalyzerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
