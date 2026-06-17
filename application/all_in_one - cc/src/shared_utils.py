#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""all_in_one 共享工具函数（纯函数，无 tkinter 状态依赖）。

被 all_in_one_v2.py 直接导入；嵌入式模块通过 _embed() 注入的 namespace 使用。
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

# tkinter 仅用于 widget_get_value 的 isinstance 类型分发；
# 用 stub 替代真实 tkinter，避免依赖 DISPLAY/Xvfb。
try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    import tkinter_stub as tk
    from tkinter_stub import ttk


# ══════════════════════════════════════════════════════════════════════
# 字符串 / 正则工具
# ══════════════════════════════════════════════════════════════════════


def re_get(pattern: str, block: str, flags: int = re.IGNORECASE | re.MULTILINE) -> str:
    """从文本块中提取正则捕获组；无匹配返回空字符串。"""
    m = re.search(pattern, block, flags)
    return m.group(1).strip() if m else ""


def editor_safe_key(key: str) -> str:
    return re.sub(r"[^\w一-鿿]", "_", key)


def split_lines(text: str) -> list[str]:
    """统一换行符并拆分为行列表（用于 diff 等）。"""
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()


def strip_editor_template_version_header(text: str) -> str:
    """去掉第③栏顶部的版本注释块。"""
    m = re.match(
        r"^# ={10,}\r?\n"
        r"# 场景模板版本 \| version: (\d+) \| 日期: [^\r\n]+\r?\n"
        r"# ={10,}\r?\n(\r?\n)?",
        text,
    )
    if m:
        return text[m.end():]
    return text


def strip_leading_hostname_visual_line(text: str) -> str:
    """去掉首行 hostname = / hostname: 及紧随的空行，兼容历史误保存的 headers.txt。"""
    s = text.lstrip("﻿")
    lines = s.splitlines()
    if not lines:
        return text
    top = lines[0].strip()
    if re.match(r"(?i)^hostname\s*=", top) or re.match(
        r"(?i)^hostname\s*[:：]\s*\S", top
    ):
        rest = lines[1:]
        while rest and not rest[0].strip():
            rest = rest[1:]
        return "\n".join(rest)
    return text


# ══════════════════════════════════════════════════════════════════════
# IKE / 可视化工具
# ══════════════════════════════════════════════════════════════════════


def visual_ike_storage(s: str) -> str:
    t = (s or "").strip().lower().replace(" ", "")
    if t in ("v1", "1", "ikev1"):
        return "v1"
    if t in ("v2", "2", "ikev2"):
        return "v2"
    return "v1"


def visual_ike_display(std: str) -> str:
    return "IKEv2" if str(std).strip().lower() == "v2" else "IKEv1"


# ══════════════════════════════════════════════════════════════════════
# IP / CIDR 工具
# ══════════════════════════════════════════════════════════════════════


def ip_host_only(addr: str) -> str:
    """从 '192.168.1.1/24' 中提取 '192.168.1.1'。"""
    s = str(addr or "").strip()
    if not s:
        return ""
    return s.split("/", 1)[0].strip()


def wanip_hosts(cidr: str) -> tuple[str, str]:
    """从 CIDR 中返回前两个可用主机 IP。返回 (PE侧=奇数, CE侧=偶数)。"""
    try:
        hosts = list(ipaddress.ip_network(cidr.strip(), strict=False).hosts())
        if len(hosts) >= 2:
            return str(hosts[0]), str(hosts[1])
    except (ValueError, ipaddress.AddressValueError):
        pass
    return "", ""


def parse_inner_nets(raw: str) -> list[str]:
    """解析多行/逗号分隔的内网段，返回合法 CIDR 列表。"""
    nets: list[str] = []
    for token in re.split(r"[\n,，\s]+", raw or ""):
        s = token.strip()
        if not s:
            continue
        try:
            nets.append(str(ipaddress.ip_network(s, strict=False)))
        except (ValueError, ipaddress.AddressValueError):
            pass
    return nets


def nets_needing_return_by_network(base_cidr: str, inner_nets: list[str]) -> list[str]:
    """返回与 base_cidr 不在同一网段的内网段（需要生成回程路由）。"""
    try:
        base = ipaddress.ip_network(base_cidr, strict=False)
    except (ValueError, ipaddress.AddressValueError):
        return inner_nets
    res: list[str] = []
    for s in inner_nets:
        try:
            net = ipaddress.ip_network(s, strict=False)
            if net != base:
                res.append(s)
        except (ValueError, ipaddress.AddressValueError):
            res.append(s)
    return res


def normalize_lan_gw_alias(lan_ip: str, lan_gw: str) -> str:
    """LAN 网关兼容历史「同LANIP」别名。

    - 旧保存值允许「同lanip/同LAN IP」等在读取时转换为 LAN IP 实值
    - 当 LAN IP 为空时回退到空字符串（不再返回非 IP 别名文本）
    """
    lip = str(lan_ip or "").strip()
    lgw = str(lan_gw or "").strip()
    if not lgw:
        return lgw
    alias = lgw.replace(" ", "").lower()
    if alias in ("同lanip", "同lan"):
        # 如果有 LAN IP，取其纯 IP 部分；否则回退到空字符串
        if lip:
            raw = ip_host_only(lip)
            return raw if raw else ""
        return ""
    if "/" in lgw:
        return ip_host_only(lgw)
    return lgw


# ══════════════════════════════════════════════════════════════════════
# Widget 值读写（tkinter 类型分发） — 消除分散在各模块中的重复分发逻辑
# ══════════════════════════════════════════════════════════════════════


def widget_get_value(widget: Any) -> str:
    """读取任意 tkinter widget 的当前值（Entry / Text / StringVar / Combobox 等）。"""
    if isinstance(widget, str):
        return widget
    # StringVar 优先于 Text/Entry（它有 get() 但无 delete/insert）
    if isinstance(widget, tk.StringVar):
        return str(widget.get()).strip()
    if isinstance(widget, tk.Text):
        return widget.get("1.0", tk.END).replace("\r\n", "\n").strip()
    if isinstance(widget, ttk.Combobox):
        return str(widget.get()).strip()
    # 普通 Entry 或有 get() 的对象（BooleanVar 返回 bool 而非 str）
    if isinstance(widget, tk.BooleanVar):
        return "true" if widget.get() else "false"
    try:
        return str(widget.get()).strip()
    except Exception:
        return ""


def widget_set_value(widget: Any, value: str) -> None:
    """设置任意 tkinter widget 的值（StringVar / Text / Combobox / Entry）。"""
    if isinstance(widget, tk.StringVar):
        widget.set(value)
        return
    if isinstance(widget, tk.Text):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value)
        return
    if isinstance(widget, ttk.Combobox):
        vals = list(widget.cget("values") or ())
        widget.set(value if value in vals else (vals[0] if vals else value))
        return
    # tk.Entry 或兼容 .delete/.insert 的其他 widget
    try:
        widget.delete(0, tk.END)
        widget.insert(0, value)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
# 颜色 / 字体常量（统一所有模块的视觉风格）
# ══════════════════════════════════════════════════════════════════════

# 基础配色
BG         = "#f0f4f8"
BG_PANEL   = "#ffffff"
BG_INPUT   = "#ffffff"
BG_HDR     = "#1e3a5f"
BG_TXT     = "#f8fafc"
FG         = "#1a2b3c"
FG_DIM     = "#7a96ad"
FG_BRT     = "#ffffff"
ACCENT     = "#0077b6"
ACCENT_CN  = "#cf1322"
ACCENT_OV  = "#0077b6"
BORDER     = "#c8d8e8"
WARN_BG    = "#fff3cd"

# 字体
FONT_MONO = ("Consolas", 9)
FONT_UI   = ("微软雅黑", 9)
FONT_HDR  = ("微软雅黑", 10, "bold")
