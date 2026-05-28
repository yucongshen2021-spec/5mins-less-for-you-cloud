# -*- coding: utf-8 -*-
"""生成前字段覆盖提示：列出模板中仍为空的占位符，不阻止生成。"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_DERIVED_INIT_FIELDS = frozenset({
    "DEFAULT_WAN_IP_PLAIN",
    "DEFAULT_LAN_IP_PLAIN",
    "DEFAULT_WAN1_IP_PLAIN",
    "DEFAULT_WAN2_IP_PLAIN",
    "DJ_WAN1_IP_PLAIN",
    "DJ_WAN2_IP_PLAIN",
    # 兼容历史/手工模板中的无下划线拼写
    "DEFAULT_LANIP_PLAIN",
    "DEFAULT_WANIP_PLAIN",
})


def inject_er_netpanel_init_aliases(d: dict) -> None:
    """「我来定模板」①栏里的 DEFAULT_* 与网络面板合并字段同义（Epoch FastIP / MPLS）。"""
    lc = str(d.get("lan_cidr") or "").strip()
    d["DEFAULT_LAN_CIDR"] = lc
    if lc and "/" in lc:
        d["DEFAULT_LAN_IP_PLAIN"] = lc.split("/", 1)[0].strip()
    else:
        d["DEFAULT_LAN_IP_PLAIN"] = lc
    d["DEFAULT_LANIP_PLAIN"] = d["DEFAULT_LAN_IP_PLAIN"]
    d["DEFAULT_WAN_CIDR"] = str(d.get("wan_cidr") or "").strip()
    wc = d["DEFAULT_WAN_CIDR"]
    d["DEFAULT_WAN_IP_PLAIN"] = wc.split("/", 1)[0].strip() if "/" in wc else wc
    d["DEFAULT_WANIP_PLAIN"] = d["DEFAULT_WAN_IP_PLAIN"]
    d["DEFAULT_WAN_GW"] = str(d.get("wan_gw") or "").strip()
    lgw = str(d.get("lan_gw") or "").strip()
    alias = lgw.replace(" ", "").lower()
    if alias in ("同lanip", "同lan"):
        if lc and "/" in lc:
            d["DEFAULT_LAN_GW"] = lc.split("/", 1)[0].strip()
        else:
            d["DEFAULT_LAN_GW"] = lc
    elif "/" in lgw:
        d["DEFAULT_LAN_GW"] = lgw.split("/", 1)[0].strip()
    else:
        d["DEFAULT_LAN_GW"] = lgw
    for nk, dk in (("lan_eth_num", "DEFAULT_LAN_ETH"), ("wan_eth_num", "DEFAULT_WAN_ETH")):
        v = d.get(nk)
        if v is not None and str(v).strip() != "":
            d[dk] = str(v).strip()


def inject_usg_template_init_aliases(fmt: dict, net: dict) -> None:
    """USG：模板中 DEFAULT_LAN_IP / DEFAULT_WAN_IP 等与网络面板一致。"""
    lip = str(net.get("lan_ip_cidr") or "").strip()
    if lip:
        fmt["DEFAULT_LAN_IP"] = lip
        fmt["DEFAULT_LAN_IP_PLAIN"] = lip.split("/", 1)[0].strip() if "/" in lip else lip
        fmt["DEFAULT_LANIP_PLAIN"] = fmt["DEFAULT_LAN_IP_PLAIN"]
    wip = str(net.get("wan_ip_cidr") or "").strip()
    if wip:
        fmt["DEFAULT_WAN_IP"] = wip
        fmt["DEFAULT_WAN_IP_PLAIN"] = wip.split("/", 1)[0].strip() if "/" in wip else wip
        fmt["DEFAULT_WANIP_PLAIN"] = fmt["DEFAULT_WAN_IP_PLAIN"]
    lg = str(net.get("lan_gw") or "").strip()
    if lg:
        fmt["DEFAULT_LAN_GW"] = lg
    weth = net.get("wan_eth")
    if weth:
        fmt["DEFAULT_WAN_ETH"] = str(weth).strip()
    leth = net.get("lan_eth")
    if leth:
        fmt["DEFAULT_LAN_ETH"] = str(leth).strip()


def list_template_placeholders(template: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in _PLACEHOLDER_RE.finditer(template):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _is_empty_value(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str):
        return not val.strip()
    if isinstance(val, (list, tuple, set, dict)):
        return len(val) == 0
    return False


def _looks_like_placeholder_text(val: Any, markers: tuple[str, ...]) -> bool:
    if not isinstance(val, str):
        return False
    s = val.strip()
    if not s:
        return True
    return any(m in s for m in markers)


def missing_template_fields(
    template: str,
    data: Mapping[str, Any],
    *,
    skip: Iterable[str] | None = None,
    placeholder_markers: tuple[str, ...] = ("（待填）", "待填）", "[待填", "请填写"),
) -> list[str]:
    """
    模板中 {var} 在 data 中缺失、为空串、或值含明显占位文案时，视为「未解析到」。
    """
    sk = frozenset(skip or ())
    bad: list[str] = []
    for name in list_template_placeholders(template):
        if name in sk:
            continue
        if name in _DERIVED_INIT_FIELDS:
            continue
        v = data.get(name)
        if name not in data or _is_empty_value(v):
            bad.append(name)
            continue
        if _looks_like_placeholder_text(v, placeholder_markers):
            bad.append(name)
    return bad


def show_generation_coverage_notice(
    messagebox: Any,
    missing: list[str],
    tool_title: str,
    *,
    max_lines: int = 100,
) -> None:
    if not missing:
        return
    tail = missing[:max_lines]
    extra = "" if len(missing) <= max_lines else f"\n… 共 {len(missing)} 项，仅列出前 {max_lines} 项"
    messagebox.showwarning(
        f"{tool_title} · 数据未完全解析",
        "以下字段未得到有效业务值，生成结果中可能为空、缺省或占位：\n\n"
        + "\n".join(tail)
        + extra
        + "\n\n仍将正常生成配置，请核对输出。",
    )


def mpls_empty_parsed_keys(
    d: Mapping[str, Any],
    *,
    keys: Iterable[str],
    skip: Iterable[str] | None = None,
) -> list[str]:
    """MPLS：检查 parse 相关键在合并网络后是否仍为空字符串。"""
    sk = frozenset(skip or ())
    bad: list[str] = []
    for k in keys:
        if k in sk:
            continue
        v = d.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            bad.append(k)
    return bad


def ar_sdwan_missing_parsed_fields(parsed: Mapping[str, Any]) -> list[str]:
    """AR SD-WAN：main/backup 子字典中空字段（psk 有默认，不提示）。"""
    miss: list[str] = []
    for side in ("main", "backup"):
        sub = parsed.get(side) or {}
        if not isinstance(sub, dict):
            continue
        for k, v in sub.items():
            if k == "psk":
                continue
            if v is None or (isinstance(v, str) and not str(v).strip()):
                miss.append(f"{side}.{k}")
    return miss


def mpls_missing_for_generate(d: Mapping[str, Any]) -> list[str]:
    """按主线/备线类型检查 MPLS 业务字段是否为空（生成前提示，不阻止）。"""
    miss: list[str] = []

    def empt(k: str) -> bool:
        return not str(d.get(k) or "").strip()

    mt = (d.get("main_line_type") or "").strip()
    bt = (d.get("bk_line_type") or "").strip()

    if not mt:
        miss.append("主线类型(未识别，请检查 LineID 主/备块与 PE、Tunnel、wanip)")
    if not bt:
        miss.append("备线类型(未识别，请检查 LineID 主/备块与 PE、Tunnel、wanip)")

    if mt == "vtun_only":
        for k in (
            "main_vtun_pe",
            "main_vtun_id",
            "main_vtun_remote",
            "main_vtun_local",
            "main_vtun_docking",
            "main_vtun_wanip",
        ):
            if empt(k):
                miss.append(k)
    elif mt == "gre_only":
        for k in (
            "main_gre_pe",
            "main_gre_tun",
            "main_gre_wanip",
            "main_gre_pe_ip",
            "main_gre_ce_ip",
            "main_gre_remote",
        ):
            if empt(k):
                miss.append(k)
    elif mt == "vtun_gre":
        for k in (
            "main_gre_pe",
            "main_gre_tun",
            "main_gre_wanip",
            "main_gre_pe_ip",
            "main_gre_ce_ip",
            "main_gre_remote",
            "main_vtun_pe",
            "main_vtun_id",
            "main_vtun_remote",
            "main_vtun_local",
            "main_vtun_docking",
            "main_vtun_wanip",
        ):
            if empt(k):
                miss.append(k)
    elif mt:
        miss.append(f"主线类型未知: {mt}")

    if bt == "vtun_only":
        for k in (
            "bk_vtun_pe",
            "bk_vtun_id",
            "bk_vtun_remote",
            "bk_vtun_local",
            "bk_vtun_docking",
            "bk_vtun_wanip",
        ):
            if empt(k):
                miss.append(k)
    elif bt == "gre_only":
        for k in (
            "bk_gre_pe",
            "bk_gre_tun",
            "bk_gre_wanip",
            "bk_gre_pe_ip",
            "bk_gre_ce_ip",
            "bk_gre_remote",
        ):
            if empt(k):
                miss.append(k)
    elif bt == "vtun_gre":
        for k in (
            "bk_gre_pe",
            "bk_gre_tun",
            "bk_gre_wanip",
            "bk_gre_pe_ip",
            "bk_gre_ce_ip",
            "bk_gre_remote",
            "bk_vtun_pe",
            "bk_vtun_id",
            "bk_vtun_remote",
            "bk_vtun_local",
            "bk_vtun_docking",
            "bk_vtun_wanip",
        ):
            if empt(k):
                miss.append(k)
    elif bt:
        miss.append(f"备线类型未知: {bt}")

    if empt("main_pe_as"):
        miss.append("main_pe_as")
    if empt("bk_pe_as"):
        miss.append("bk_pe_as")

    hn = str(d.get("hostname") or "")
    if not hn.strip() or "请填写" in hn:
        miss.append("hostname")

    seen: set[str] = set()
    out: list[str] = []
    for x in miss:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def mpls_ipsec_missing_for_generate(d: Mapping[str, Any]) -> list[str]:
    """MPLS IPSec：只检查必填的业务解析字段，可选计算块（lan_if_block 等）不报错。"""
    miss: list[str] = []

    def empt(k: str) -> bool:
        return not str(d.get(k) or "").strip()

    # WAN/LAN 核心字段
    if empt("wan_addr"):
        miss.append("wan_addr（WAN IP 未填写）")
    if empt("wan_gw"):
        miss.append("wan_gw（WAN 网关未填写）")

    # CE AS
    if empt("ce_as"):
        miss.append("ce_as（CE AS号未解析到）")

    # Hostname
    hn = str(d.get("hostname") or "")
    if not hn.strip() or "请填写" in hn:
        miss.append("hostname")

    # 主/备线必填 IPSec 解析字段
    for px, label in (("main", "主线"), ("bk", "备线")):
        for k in (
            f"{px}_gre_pe",       # PE 名
            f"{px}_gre_tun",      # Tunnel 名（用于 track_name / tun 地址）
            f"{px}_gre_wanip",    # wanip（用于计算 tun_peer / tun_local）
            f"{px}_loop_ip",      # LoopIP
            f"{px}_public_ip",    # 拨号IP
            f"{px}_ipsec_psk",    # 密钥
            f"{px}_pe_as",        # PE AS号
        ):
            if empt(k):
                miss.append(f"{k}（{label}字段缺失）")

    seen: set[str] = set()
    out: list[str] = []
    for x in miss:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
