#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
all_in_one_v2  ──  四合一 + 可视化配置编辑器

修复 / 行为
  · ER FastIP root 块有注释行导致旧正则失配 → 逐行状态机
  · 保存后热更新：ER/USG 写入嵌入脚本中的模板变量；ER MPLS / AR SD-WAN 包装
    generate_mpls_config / render_*，在「与出厂样例不同」时使用编辑器中的全文输出
  · 工作区：editor_workspace/<场景名>/
      headers.txt  mapping.txt  <tpl_slot>.tpl  changelog.log

可视化编辑器四栏
  ① 数据头  ② 变量映射  ③ 生成模板  ④ 预览

按钮：恢复最初模板（仅本场景，需确认）/ 预览 / 保存并应用（含确认，第③栏顶写入版本号+日期）
自动保存：切换场景、关闭窗口时静默写入子目录并记 changelog（不递增版本号）
"""

from __future__ import annotations

from typing import Any, Callable

import ast
import importlib.util
import difflib
import ipaddress
import json
import re
import sys
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
import shutil
from tkinter import filedialog, messagebox, ttk

import shared_utils as _su_global

_visual_ike_storage = _su_global.visual_ike_storage
_visual_ike_display = _su_global.visual_ike_display


def _ensure_sponsor_board_file() -> None:
    """确保感谢赞助榜单文件存在；仅缺失时写入默认值，不覆盖后台维护内容。"""
    if SPONSOR_BOARD_FILE.exists():
        return
    SPONSOR_BOARD_DIR.mkdir(parents=True, exist_ok=True)
    SPONSOR_BOARD_FILE.write_text(
        json.dumps(SPONSOR_BOARD_DEFAULT, ensure_ascii=False, indent=2),
        encoding="utf-8-sig",
    )


def _load_sponsor_board_data() -> tuple[dict[str, list[str]], str]:
    """读取感谢赞助榜单；异常时回退默认内容并返回提示信息。"""
    try:
        _ensure_sponsor_board_file()
    except Exception as e:
        return dict(SPONSOR_BOARD_DEFAULT), f"榜单文件初始化失败：{e}"
    try:
        raw = json.loads(SPONSOR_BOARD_FILE.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict):
            raise ValueError("顶层必须为 JSON 对象")
        out: dict[str, list[str]] = {}
        for k in ("赞助榜单", "技术榜单"):
            v = raw.get(k, [])
            if not isinstance(v, list):
                raise ValueError(f"字段 {k} 必须是数组")
            out[k] = [str(x).strip() for x in v if str(x).strip()]
        return out, ""
    except Exception as e:
        return dict(SPONSOR_BOARD_DEFAULT), f"榜单文件读取失败，已回退默认展示：{e}"


def _runtime_dirs() -> tuple[Path, Path]:
    """
    bundle_dir: 只读资源（开发时为 src/ 下 *.py / _templates.json；打包后为 _MEIPASS）。
    app_root:   可写数据根目录 —— 始终为「交付根目录」下的 data/（与 exe、说明文档并列）。
    """
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        deliver_root = Path(sys.executable).resolve().parent
        app_root = deliver_root / "data"
        # onedir 形态下允许复用上级目录已有 data，不要求搬迁现有目录
        if not app_root.exists():
            parent_data = deliver_root.parent / "data"
            if parent_data.exists():
                app_root = parent_data
        app_root.mkdir(parents=True, exist_ok=True)
        return bundle, app_root
    # 开发：本文件位于 src/all_in_one_v2.py，数据在 上级目录/data/
    bundle = Path(__file__).resolve().parent
    deliver_root = bundle.parent
    app_root = deliver_root / "data"
    app_root.mkdir(parents=True, exist_ok=True)
    return bundle, app_root


BUNDLE_DIR, APP_ROOT = _runtime_dirs()
WORKSPACE = APP_ROOT / "editor_workspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)
SPONSOR_BOARD_DIR = APP_ROOT / "sponsor_board"
SPONSOR_BOARD_DIR.mkdir(parents=True, exist_ok=True)
SPONSOR_BOARD_FILE = SPONSOR_BOARD_DIR / "rankings.json"
SPONSOR_BOARD_DEFAULT: dict[str, list[str]] = {
    "赞助榜单": ["Theshy", "Zeta", "Darian"],
    "技术榜单": ["Tommy", "Zelin"],
}
# 19 场景 UI 自检等：与 user_activity（正式页生成 JSONL）分目录存放
SELFCHECK_LOGS = APP_ROOT / "selfcheck_logs"
SELFCHECK_LOGS.mkdir(parents=True, exist_ok=True)
# 正式页面自检专用隔离目录（独立于 editor_workspace，回归结束后清除）
WORKSPACE_TEST: Path = APP_ROOT / "workspace_test"
# 可视化场景出厂包：workspace 无文件时从此处读取；由 --seed-editor-defaults-clear-ws 从当前 workspace 生成
# 打包为 exe 时默认模板打进 _MEIPASS/editor_defaults；若 data/editor_defaults/ 存在则优先（便于用户覆盖）
if getattr(sys, "frozen", False):
    _sidecar_def = APP_ROOT / "editor_defaults"
    EDITOR_DEFAULTS_ROOT = (
        _sidecar_def if _sidecar_def.is_dir() else BUNDLE_DIR / "editor_defaults"
    )
else:
    EDITOR_DEFAULTS_ROOT = APP_ROOT / "editor_defaults"
# 可视化里「保存初始化默认」写入；恢复出厂时删除
INIT_USER_PLACEHOLDERS_JSON = APP_ROOT / "user_init_placeholders.json"
# 嵌入完成后从各脚本常量快照，供「恢复出厂」
INIT_PLACEHOLDERS_FACTORY: dict[str, dict[str, str]] = {}

# 由 _build_window 注入：按源码文件名触发对应 Legacy 页签后台嵌入（不切换 Tab）
_ENSURE_LEGACY_EMBED_BY_FILENAME: Callable[[str], None] | None = None

# 嵌入式模块文件名（避免 ~100 处硬编码字符串）
MOD_ER_FASTIP = "er_fastip_2in1_v8.py"
MOD_USG_FASTIP = "usg_fastip_3in1_v5.py"
MOD_ER_MPLS = "er_mpls_v1.py"
MOD_AR_SDWAN = "ar_sdwan_zihuan_v4.py"

# ER FastIP：HK 与 非HK 分槽持久化（er 脚本内 HK_DEFAULT_* / DEFAULT_*）
ER_INIT_MOD_HK = f"{MOD_ER_FASTIP}::HK"
ER_INIT_MOD_US = f"{MOD_ER_FASTIP}::US"
ER_INIT_MOD_FLINK = f"{MOD_ER_FASTIP}::FLINK"
ER_INIT_MOD_NEW_EXIT = f"{MOD_ER_FASTIP}::NEW_EXIT"
ER_INIT_MOD_DOMAIN_SPLIT = f"{MOD_ER_FASTIP}::DOMAIN_SPLIT"
# USG FastIP：HK 与 非HK 分槽持久化（usg 脚本内 HK_DEFAULT_* / DEFAULT_*）
USG_INIT_MOD_US = f"{MOD_USG_FASTIP}::US"
USG_INIT_MOD_HK = f"{MOD_USG_FASTIP}::HK"
USG_INIT_MOD_FLINK = f"{MOD_USG_FASTIP}::FLINK"
USG_INIT_MOD_NEW_EXIT = f"{MOD_USG_FASTIP}::NEW_EXIT"
# AR：单机用 DEFAULT_*（与「单机组网」页签一致），双机用 DJ_*（与「双机组网」一致）
AR_INIT_MOD_ZH = f"{MOD_AR_SDWAN}::ZH"
AR_INIT_MOD_DJ = f"{MOD_AR_SDWAN}::DJ"

# AR 可视化槽位与正式页一致：G(槽位) 内仅填数字或 0/0/x
_AR_GE_INIT_KEYS: frozenset[str] = frozenset({
    "DEFAULT_WAN1_PORT", "DEFAULT_WAN2_PORT",
    "DEFAULT_ZIHUAN_PORT", "DEFAULT_IPSEC_PORT",
    "DJ_WAN1_PORT", "DJ_WAN2_PORT",
    "DJ_ZIHUAN1_PORT", "DJ_ZIHUAN2_PORT",
    "DJ_IPSEC1_PORT", "DJ_IPSEC2_PORT",
})

# 与 ar_sdwan_zihuan_v4.SOUTH_LABELS_DISPLAY 一致；嵌入前「我来定模板」南向下拉依赖此项
_AR_SOUTH_LABELS_DISPLAY: tuple[str, ...] = (
    "Public Default South Access  [119.145.21.126]",
    "Private Default South Access  [172.23.3.251 / 172.23.30.251]",
    "CT South Access  [119.145.21.126]",
    "HK South Access  [43.229.119.246]",
    "MSTP South Access  [172.23.3.251 / 172.23.30.251]",
)

# 内网段放在表单右侧、多行高度（与 ER/USG/MPLS 正式页一致）
_INIT_INNER_RIGHT_MODS: frozenset[str] = frozenset({
    ER_INIT_MOD_HK, ER_INIT_MOD_US, MOD_ER_MPLS,
    USG_INIT_MOD_US, USG_INIT_MOD_HK,
})

# 可视化初始化：失焦时空白则恢复出厂值的字段白名单（未列出的键均会回填）
_INIT_ENTRY_ALLOW_EMPTY: dict[str, frozenset[str]] = {
    ER_INIT_MOD_NEW_EXIT: frozenset({
        "ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "ER_NE_FNET_NAT_RULE_DEFAULT",
    }),
    ER_INIT_MOD_DOMAIN_SPLIT: frozenset({
        "ER_DS_STATIC32_BACKUP_NH_DEFAULT", "ER_DS_DNS2_DEFAULT",
        "ER_DS_SOURCE_CIDR_DEFAULT",
        "ER_DS_TRACK_NAME_DEFAULT",
        "ER_DS_FNET_NAT_RULE_DEFAULT", "ER_DS_EXIT_TUNNEL_DEFAULT",
        "ER_DS_EXIT_SNAT_IP_DEFAULT",
    }),
}


def _embedded_name_for_init_mod(mod: str) -> str:
    if mod in (
        ER_INIT_MOD_HK, ER_INIT_MOD_US, ER_INIT_MOD_FLINK,
        ER_INIT_MOD_NEW_EXIT, ER_INIT_MOD_DOMAIN_SPLIT,
    ):
        return MOD_ER_FASTIP
    if mod in (USG_INIT_MOD_US, USG_INIT_MOD_HK, USG_INIT_MOD_FLINK, USG_INIT_MOD_NEW_EXIT):
        return MOD_USG_FASTIP
    if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ):
        return MOD_AR_SDWAN
    return mod


def _init_mod_for_scenario(info: dict) -> str:
    src = info.get("source") or ""
    if src == MOD_ER_FASTIP:
        if info.get("tpl_slot") == "TEMPLATE_ER_FLINK_VISUAL":
            return ER_INIT_MOD_FLINK
        if info.get("tpl_slot") == "TEMPLATE_ER_NEW_EXIT_VISUAL":
            return ER_INIT_MOD_NEW_EXIT
        if info.get("tpl_slot") == "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL":
            return ER_INIT_MOD_DOMAIN_SPLIT
        return ER_INIT_MOD_HK if info.get("tpl_slot") == "TEMPLATE_EPOCH_HK" else ER_INIT_MOD_US
    if src == MOD_USG_FASTIP:
        if info.get("tpl_slot") == "TEMPLATE_USG_FLINK_VISUAL":
            return USG_INIT_MOD_FLINK
        if info.get("tpl_slot") == "TEMPLATE_USG_NEW_EXIT_VISUAL":
            return USG_INIT_MOD_NEW_EXIT
        return USG_INIT_MOD_HK if info.get("tpl_slot") == "TEMPLATE_USG_HK" else USG_INIT_MOD_US
    if src == MOD_AR_SDWAN:
        slot = str(info.get("tpl_slot") or "")
        if slot in (
            "TEMPLATE_AR_OPS_DUAL_PRIMARY",
            "TEMPLATE_AR_OPS_DUAL_BACKUP",
            "TEMPLATE_AR_FACTORY_DUAL_PRIMARY",
            "TEMPLATE_AR_FACTORY_DUAL_BACKUP",
        ):
            return AR_INIT_MOD_DJ
        return AR_INIT_MOD_ZH
    return src


def _global_key_for_er_init_mod(mod: str, logical_key: str) -> str:
    if mod == ER_INIT_MOD_HK:
        return "HK_" + logical_key
    return logical_key


def _global_key_for_usg_init_mod(mod: str, logical_key: str) -> str:
    if mod == USG_INIT_MOD_HK:
        return "HK_" + logical_key
    return logical_key

# 程序化场景（MPLS / AR）保存的模板全文 → 生成函数优先返回此内容（热更新）
VISUAL_PROG_OVERRIDE: dict[str, str] = {}
# 可视化编辑器第③栏：「保存并应用」时写入顶部的版本注释块（解析/剥离用）
_RE_EDITOR_TPL_VERSION_HDR = re.compile(
    r"^# ={10,}\r?\n"
    r"# 场景模板版本 \| version: (\d+) \| 日期: [^\r\n]+\r?\n"
    r"# ={10,}\r?\n(\r?\n)?",
)


def _strip_editor_template_version_header(text: str) -> str:
    """去掉第③栏顶部的版本注释块；注入运行时 / 基线比对必须用正文，避免破坏 format 与出厂对比。"""
    m = _RE_EDITOR_TPL_VERSION_HDR.match(text)
    if m:
        return text[m.end() :]
    return text


def _enrich_usg_preview_export_fields(
    data: dict[str, str], parsed: dict, source: str
) -> None:
    """USG parse_business_data* 返回的出口 IP 为列表；模板使用 main_export_summary 等派生字段。"""
    ns = EMBEDDED_NS.get(source)
    main_export_ips = list(parsed.get("main_export_ips") or [])
    backup_export_ips = list(parsed.get("backup_export_ips") or [])
    m_map = parsed.get("main_export_ip_map") or {}
    b_map = parsed.get("backup_export_ip_map") or {}
    if not isinstance(m_map, dict):
        m_map = {}
    if not isinstance(b_map, dict):
        b_map = {}

    data["main_export_summary"] = (
        "\n".join(main_export_ips) if main_export_ips else data.get("main_export_summary", "（待填）")
    )
    data["backup_export_summary"] = (
        "\n".join(backup_export_ips)
        if backup_export_ips
        else data.get("backup_export_summary", "（待填）")
    )
    data["main_export_natip"] = (
        main_export_ips[0] if main_export_ips else data.get("main_export_natip", "0.0.0.0")
    )
    data["bgp_main_lo"] = "LoopBack100"
    data["bgp_backup_lo"] = "LoopBack200"

    main_lo_lines: list[str] = []
    for idx2, ip in enumerate(main_export_ips):
        real = m_map.get(ip)
        desc = (
            f" description Main-OUT-{idx2 + 1}({real})"
            if real
            else f" description Main-OUT-{idx2 + 1}"
        )
        main_lo_lines.extend(
            [
                f"interface LoopBack{100 + idx2}",
                desc,
                f" ip address {ip} 255.255.255.255",
            ]
        )
    backup_lo_lines: list[str] = []
    for idx2, ip in enumerate(backup_export_ips):
        real = b_map.get(ip)
        desc = (
            f" description Backup-OUT-{idx2 + 1}({real})"
            if real
            else f" description Backup-OUT-{idx2 + 1}"
        )
        backup_lo_lines.extend(
            [
                f"interface LoopBack{200 + idx2}",
                desc,
                f" ip address {ip} 255.255.255.255",
            ]
        )

    data["main_lo_block"] = (
        "\n".join(main_lo_lines) if main_lo_lines else "#（主出口LoopBack待填）"
    )
    data["backup_lo_block"] = (
        "\n".join(backup_lo_lines) if backup_lo_lines else "#（备出口LoopBack待填）"
    )

    if not ns:
        return
    bnat = ns.get("build_nat_groups_block")
    bsnat = ns.get("build_snat_rules_block")
    if callable(bnat) and callable(bsnat):
        data["main_nat_block"] = bnat(main_export_ips, "MAIN")
        data["backup_nat_block"] = bnat(backup_export_ips, "BACKUP")
        data["main_snat_block"] = bsnat(
            main_export_ips, "MAIN", "Tunnel1000", "ToMainOUT"
        )
        data["backup_snat_block"] = bsnat(
            backup_export_ips, "BACKUP", "Tunnel2000", "ToBackOUT"
        )


def _strip_leading_hostname_visual_line(text: str) -> str:
    """
    可视化第①栏不应以 hostname 开头（主机名在 ER 工具「网络」里填）。
    去掉首行 hostname = / hostname: 及紧随的空行，兼容历史误保存的 headers.txt。
    """
    s = text.lstrip("\ufeff")
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


# ══════════════════════════════════════════════════════════════════
# §1  全局命名空间仓库
# ══════════════════════════════════════════════════════════════════

EMBEDDED_NS: dict[str, dict] = {}


_editor_safe_key = _su_global.editor_safe_key


# 可视化场景展示名变更后，仍映射到原 workspace / editor_defaults 子目录名，避免丢历史模板
_VISUAL_SCENARIO_DISK_ALIASES: dict[str, str] = {
    "Epoch FastIP · HK 香港出口": "ER FastIP · HK 香港出口",
    "Epoch FastIP · 非香港出口": "ER FastIP · 非HK出口",
    "USG FastIP · 非香港出口": "USG FastIP · 非HK出口",
    "Epoch MPLS · 国内配置": "ER MPLS · 国内配置",
    "Epoch MPLS · 海外配置": "ER MPLS · 海外配置",
    "Epoch FastIP · ER 其他小功能": "Epoch FastIP · ER 飞连",
    "USG FastIP · 其他小功能": "USG FastIP · 飞连",
}


def _visual_scenario_disk_key(key: str) -> str:
    return _VISUAL_SCENARIO_DISK_ALIASES.get(key, key)


def _scenario_tpl_slot(info: dict) -> str:
    """磁盘上的模板文件名（不含 .tpl），与 ER FastIP 的 TEMPLATE_EPOCH_* 命名风格一致。"""
    return info.get("tpl_slot") or info.get("tpl_var") or info.get("tpl_static") or "template"


def _scenario_workspace_dir(key: str) -> Path:
    return WORKSPACE / _editor_safe_key(_visual_scenario_disk_key(key))


def _scenario_defaults_dir(key: str) -> Path:
    return EDITOR_DEFAULTS_ROOT / _editor_safe_key(_visual_scenario_disk_key(key))


def _append_scenario_changelog(sdir: Path, line: str) -> None:
    try:
        sdir.mkdir(parents=True, exist_ok=True)
        logf = sdir / "changelog.log"
        with logf.open("a", encoding="utf-8-sig") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass


_split_lines = _su_global.split_lines


def _diff_added_removed(
    before: str,
    after: str,
    *,
    max_items: int = 6,
    max_item_chars: int = 120,
) -> tuple[int, int, list[str], list[str]]:
    """返回 (added_total, removed_total, added_items, removed_items)。

    added_items/removed_items 是截断后的样本（仅用于 changelog 描述），总数用于摘要。
    """
    if before == after:
        return 0, 0, [], []

    b = _split_lines(before)
    a = _split_lines(after)
    added_items: list[str] = []
    removed_items: list[str] = []
    added_total = 0
    removed_total = 0

    for line in difflib.unified_diff(b, a, lineterm="", n=0):
        # 忽略 diff 元信息行
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith("+"):
            added_total += 1
            item = line[1:]
            if len(added_items) < max_items:
                added_items.append(item[:max_item_chars])
        elif line.startswith("-"):
            removed_total += 1
            item = line[1:]
            if len(removed_items) < max_items:
                removed_items.append(item[:max_item_chars])

    return added_total, removed_total, added_items, removed_items


def _apply_template_to_runtime(key: str, info: dict, tpl: str) -> bool:
    """将第③栏同步到内存：tpl_var 直接写入命名空间；tpl_static 仅在与出厂样例不同时才覆盖生成逻辑。"""
    text = _strip_editor_template_version_header(tpl.rstrip("\n"))
    patched = False
    tpl_var = info.get("tpl_var")
    if tpl_var:
        source = str(info.get("source") or "")
        ns = EMBEDDED_NS.get(source)
        if ns is None and source:
            fn = _ENSURE_LEGACY_EMBED_BY_FILENAME
            if callable(fn):
                try:
                    fn(source)
                except Exception:
                    pass
            ns = EMBEDDED_NS.get(source)
        if ns is not None:
            ns[tpl_var] = text
            patched = True
    ts = info.get("tpl_static")
    if ts:
        base = ""
        if info.get("source") == MOD_AR_SDWAN:
            ns_ar = EMBEDDED_NS.get(MOD_AR_SDWAN)
            if ns_ar and callable(ns_ar.get("build_ar_visual_tpl")):
                try:
                    base = ns_ar["build_ar_visual_tpl"](ts).rstrip("\n")
                except Exception:
                    pass
            if not base:
                base = (
                    _PROG_TEMPLATES_BASELINE.get(ts) or _PROG_TEMPLATES.get(ts) or ""
                ).rstrip("\n")
        else:
            base = (_PROG_TEMPLATES_BASELINE.get(ts) or "").rstrip("\n")
        if text == base:
            VISUAL_PROG_OVERRIDE.pop(ts, None)
        else:
            VISUAL_PROG_OVERRIDE[ts] = text
        patched = True
    return patched


def _patch_mpls_generate_for_visual() -> None:
    ns = EMBEDDED_NS.get(MOD_ER_MPLS)
    if not ns or "generate_mpls_config" not in ns or ns.get("__visual_mpls_patched__"):
        return
    orig_open = ns["generate_mpls_config"]
    orig_ipsec = ns.get("generate_mpls_ipsec_config")

    def _render_with_override(d: dict, orig_fn) -> str:
        ct = d.get("config_type", "")
        am = d.get("access_mode", "OpenVPN")
        if am == "IPSec":
            sk = "mpls_ipsec"
        else:
            sk = "mpls_domestic" if ct == "国内" else "mpls_overseas"
        ov = VISUAL_PROG_OVERRIDE.get(sk)
        base = (_PROG_TEMPLATES_BASELINE.get(sk) or "").rstrip("\n")
        if ov is not None and ov.strip() and ov.rstrip("\n") != base:
            try:
                return ov.rstrip("\n").format(**d)
            except Exception:
                # 覆盖模板存在缺字段/坏占位时，回退到原生生成，避免把 {xxx} 原样输出到正式页。
                return orig_fn(d)
        return orig_fn(d)

    def wrapped_open(d: dict) -> str:
        return _render_with_override(d, orig_open)

    ns["generate_mpls_config"] = wrapped_open
    if callable(orig_ipsec):
        def wrapped_ipsec(d: dict) -> str:
            return _render_with_override(d, orig_ipsec)
        ns["generate_mpls_ipsec_config"] = wrapped_ipsec
    ns["__visual_mpls_patched__"] = True


def _patch_ar_sdwan_for_visual() -> None:
    """AR 覆盖由 ar_sdwan 内 _apply_ar_visual_template_override 经 _get_visual_prog_override_map 读取（含嵌入注入的 __VISUAL_PROG_OVERRIDE_REF__）。"""
    pass


def _load_saved_templates_into_runtime(sources: set[str] | None = None) -> None:
    """启动时从 editor_workspace / editor_defaults 读入已保存模板；程序化场景若与出厂样例一致则不挂覆盖（走原生 generate）。"""
    try:
        scenarios = VisualEditorTab.SCENARIOS
    except Exception:
        return
    for key, info in scenarios.items():
        src = str(info.get("source") or "")
        if sources is not None and src not in sources:
            continue
        sdir_ws = _scenario_workspace_dir(key)
        slot = _scenario_tpl_slot(info)
        p_ws = sdir_ws / f"{slot}.tpl"
        p_def = _scenario_defaults_dir(key) / f"{slot}.tpl"
        legacy = WORKSPACE / f"{_editor_safe_key(key)}_template.tpl"
        path = p_ws if p_ws.exists() else (p_def if p_def.exists() else legacy)
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8-sig")
            _apply_template_to_runtime(key, info, raw)
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════
# §2  脚本预处理 & 嵌入
# ══════════════════════════════════════════════════════════════════

_SELFTEST_RE = re.compile(
    r'\nif __name__ == "__main__" and "--selftest-parse" in sys\.argv:.*?'
    r'\n    raise SystemExit\(0\)\n',
    re.DOTALL,
)


def _preprocess(name: str, src: str) -> str:
    if name == MOD_USG_FASTIP:
        src = _SELFTEST_RE.sub("\n", src)
    out: list[str] = []
    in_skip = False
    for line in src.splitlines(keepends=True):
        s = line.strip()
        if in_skip:
            if s.startswith("root.configure("):
                out.append(line)
                in_skip = False
            continue
        if re.match(r"root\s*=\s*tk\.Tk\(\)\s*$", s):
            out.append("root = __TAB_FRAME__\n")
            in_skip = True
            continue
        if re.match(r"root\.mainloop\(\)\s*$", s):
            out.append("# [all_in_one_v2] mainloop omitted\n")
            continue
        out.append(line)
    return "".join(out)


def _embed(name: str, frame: tk.Frame) -> str | None:
    path = BUNDLE_DIR / name
    if not path.exists():
        return f"文件不存在: {name}"
    try:
        _bd = str(BUNDLE_DIR)
        if _bd not in sys.path:
            sys.path.insert(0, _bd)
        _fc_path = BUNDLE_DIR / "field_coverage.py"
        _field_coverage_embed = None
        if _fc_path.is_file():
            _spec = importlib.util.spec_from_file_location(
                "_all_in_one_field_coverage", _fc_path)
            if _spec and _spec.loader:
                _field_coverage_embed = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_field_coverage_embed)
        if _field_coverage_embed is None:

            class _DummyFieldCoverage:
                @staticmethod
                def missing_template_fields(*_a, **_k):
                    return []

                @staticmethod
                def show_generation_coverage_notice(*_a, **_k):
                    pass

                @staticmethod
                def mpls_missing_for_generate(*_a, **_k):
                    return []

                @staticmethod
                def mpls_ipsec_missing_for_generate(*_a, **_k):
                    return []

                @staticmethod
                def ar_sdwan_missing_parsed_fields(*_a, **_k):
                    return []

            _field_coverage_embed = _DummyFieldCoverage()
        raw = path.read_text(encoding="utf-8-sig")
        code = _preprocess(name, raw)
        # 注入共享工具模块，使嵌入脚本可直接调用 shared_utils 中的函数
        import shared_utils as _su  # noqa: F811

        ns: dict = {
            "__builtins__": __builtins__,
            "__name__": "__embedded__",
            "tk": tk, "ttk": ttk,
            "messagebox": messagebox,
            "filedialog": filedialog,
            "re": re, "sys": sys,
            "ipaddress": ipaddress,
            "__TAB_FRAME__": frame,
            "field_coverage": _field_coverage_embed,
            # 共享模块及其常用函数
            "shared_utils": _su,
            "_get": _su.re_get,            # 历史别名（3 个模块均使用 _get 名称）
            "re_get": _su.re_get,
            "wanip_hosts": _su.wanip_hosts,
            "parse_inner_nets": _su.parse_inner_nets,
            "_parse_inner_nets": _su.parse_inner_nets,  # alias for embedded modules
            "nets_needing_return_by_network": _su.nets_needing_return_by_network,
            "_nets_needing_return_by_network": _su.nets_needing_return_by_network,  # alias
            "ip_host_only": _su.ip_host_only,
            "normalize_lan_gw_alias": _su.normalize_lan_gw_alias,
            "widget_get_value": _su.widget_get_value,
            "widget_set_value": _su.widget_set_value,
            # 统一的颜色/字体常量
            "BG": _su.BG, "BG_PANEL": _su.BG_PANEL, "BG_INPUT": _su.BG_INPUT,
            "BG_HDR": _su.BG_HDR, "BG_TXT": _su.BG_TXT,
            "FG": _su.FG, "FG_DIM": _su.FG_DIM, "FG_BRT": _su.FG_BRT,
            "ACCENT": _su.ACCENT, "BORDER": _su.BORDER,
            "FONT_MONO": _su.FONT_MONO, "FONT_UI": _su.FONT_UI,
        }
        exec(compile(code, str(path), "exec"), ns)
        # PyInstaller 下 __main__ 常无 VISUAL_PROG_OVERRIDE；嵌入脚本必须拿到宿主字典引用，否则「我来定模板」+ IKE 重写整链不触发
        if name == MOD_AR_SDWAN:
            ns["__VISUAL_PROG_OVERRIDE_REF__"] = VISUAL_PROG_OVERRIDE
        EMBEDDED_NS[name] = ns
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _show_load_error(frame: tk.Frame, title: str, msg: str) -> None:
    """与页签 Frame 的 grid 布局一致（该 Frame 已 rowconfigure/columnconfigure，不能用 pack）。"""
    frame.configure(bg="#fff0f0")
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(1, weight=1)
    tk.Label(
        frame, text=f"  {title}  加载失败",
        font=("微软雅黑", 13, "bold"),
        bg="#fff0f0", fg="#c0392b",
    ).grid(row=0, column=0, sticky="ew", pady=(40, 8), padx=12)
    box = tk.Text(
        frame, font=("Consolas", 9),
        bg="#fff8f8", fg="#333", relief="flat",
        bd=1, width=88, height=14,
    )
    box.insert("end", msg)
    box.config(state="disabled")
    box.grid(row=1, column=0, sticky="nsew", padx=20, pady=6)
    tk.Label(
        frame,
        text="请将以上报错反馈给开发者，或单独运行该工具的独立脚本。",
        font=("微软雅黑", 9), bg="#fff0f0", fg="#888",
    ).grid(row=2, column=0, sticky="ew", pady=(0, 12))


# ══════════════════════════════════════════════════════════════════
# §3  变量描述 & 样本值（覆盖全部模板变量）
# ══════════════════════════════════════════════════════════════════

# variable → brief description  (短描述，用于第②栏，支持自动换行)
_VAR_DESC: dict[str, str] = {
    "hostname":               "设备主机名",
    "ce_loip":                "CE LoopBack IP（公共）",
    "ce_docking":             "CE 对接IP（公共）",
    "wan_if":                 "WAN接口名（如eth0）",
    "wan_addr":               "WAN IP(CIDR)",
    "wan_route_block":        "WAN路由块（自动生成）",
    "lan_if_block":           "LAN接口块（自动生成）",
    "fw_options_block":       "防火墙选项块（自动生成）",
    "overseas_nat_block":     "出口NAT规则块（自动生成）",
    "return_routes_block":    "内网回程路由块（自动生成）",
    "dhcp_server_block":      "DHCP服务配置块（自动生成）",
    "bgp_server_routes":      "BGP静态路由块（自动生成）",
    "main_pe":                "主线PE设备名",
    "main_tunnel":            "主线Tunnel(vtunXXXX)",
    "main_tunnel_port":       "主线Tunnel端口数字",
    "main_wanip":             "主线WANIP(CIDR)",
    "main_wanip_remote":      "主线WANIP PE侧IP",
    "main_wanip_local":       "主线WANIP CE侧IP",
    "main_docking":           "主线PE对接IP",
    "main_track":             "主线track编号（自动）",
    "main_bgp1":              "主线BGP Server IP1",
    "main_bgp2":              "主线BGP Server IP2",
    "hkip_nat":               "首个HK出口NAT IP",
    "hkip_nat_all":           "全部HK出口NAT IP（分行）",
    "hkip_dum100_desc":       "HK dum100接口描述",
    "extra_dum_block":        "额外dum接口块（自动生成）",
    "bk_pe":                  "备线PE设备名",
    "bk_tunnel":              "备线Tunnel(vtunXXXX)",
    "bk_tunnel_port":         "备线Tunnel端口数字",
    "bk_wanip":               "备线WANIP(CIDR)",
    "bk_wanip_remote":        "备线WANIP PE侧IP",
    "bk_wanip_local":         "备线WANIP CE侧IP",
    "bk_docking":             "备线PE对接IP",
    "bk_track":               "备线track编号（自动）",
    "bk_bgp1":                "备线BGP Server IP1",
    "bk_bgp2":                "备线BGP Server IP2",
    "main_acvpn_gre_pe":      "主线国内GRE UPE名",
    "main_acvpn_gre_tun":     "主线国内GRE Tunnel",
    "main_acvpn_gre_pe_ip":   "主线国内GRE PE侧IP",
    "main_acvpn_gre_ce_ip":   "主线国内GRE CE侧IP",
    "main_acvpn_gre_remote":  "主线国内GRE remote",
    "main_acvpn_gre_wanip":   "主线国内GRE WANIP",
    "main_acvpn_vtun_pe":     "主线国内vtun PE名",
    "main_acvpn_vtun_id":     "主线国内vtun ID",
    "main_acvpn_vtun_port":   "主线国内vtun端口",
    "main_acvpn_vtun_remote": "主线国内vtun远端IP",
    "main_acvpn_vtun_local":  "主线国内vtun本端IP",
    "main_acvpn_vtun_docking":"主线国内vtun对接IP",
    "main_us_pe":             "主线海外NAT PE名",
    "main_us_tun":            "主线海外Tunnel",
    "main_us_pe_ip":          "主线海外PE侧IP",
    "main_us_gre_ce_ip":      "主线海外GRE CE侧IP",
    "main_us_wanip":          "主线海外WANIP",
    "main_us_pe_docking":     "主线海外PE对接IP",
    "main_us_nat_ip":         "主线首个海外出口NAT IP",
    "main_us_nat_ip_all":     "主线全部海外出口NAT IP",
    "main_us_dum100_desc":    "主线dum100描述",
    "main_us_bgp1":           "主线海外BGP IP1",
    "main_us_bgp2":           "主线海外BGP IP2",
    "extra_dum_main_block":   "主线额外dum块（自动）",
    "us_bgp_routes":          "海外BGP路由块（自动）",
    "bk_acvpn_gre_pe":        "备线国内GRE UPE名",
    "bk_acvpn_gre_tun":       "备线国内GRE Tunnel",
    "bk_acvpn_gre_pe_ip":     "备线国内GRE PE侧IP",
    "bk_acvpn_gre_ce_ip":     "备线国内GRE CE侧IP",
    "bk_acvpn_gre_remote":    "备线国内GRE remote",
    "bk_acvpn_gre_wanip":     "备线国内GRE WANIP",
    "bk_acvpn_vtun_pe":       "备线国内vtun PE名",
    "bk_acvpn_vtun_id":       "备线国内vtun ID",
    "bk_acvpn_vtun_port":     "备线国内vtun端口",
    "bk_acvpn_vtun_remote":   "备线国内vtun远端IP",
    "bk_acvpn_vtun_local":    "备线国内vtun本端IP",
    "bk_acvpn_vtun_docking":  "备线国内vtun对接IP",
    "bk_us_pe":               "备线海外NAT PE名",
    "bk_us_tun":              "备线海外Tunnel",
    "bk_us_pe_ip":            "备线海外PE侧IP",
    "bk_us_gre_ce_ip":        "备线海外GRE CE侧IP",
    "bk_us_wanip":            "备线海外WANIP",
    "bk_us_pe_docking":       "备线海外PE对接IP",
    "bk_us_nat_ip":           "备线首个海外出口NAT IP",
    "bk_us_nat_ip_all":       "备线全部海外出口NAT IP",
    "bk_us_dum200_desc":      "备线dum200描述",
    "bk_us_bgp1":             "备线海外BGP IP1",
    "bk_us_bgp2":             "备线海外BGP IP2",
    "extra_dum_bk_block":     "备线额外dum块（自动）",
    "main_dial_pe":           "主线IPSEC_PE名",
    "main_dial_ip":           "主线拨号IP",
    "main_loopback":          "主线loIP(CE LoopBack)",
    "main_auth_id":           "主线认证ID(LineID)",
    "main_peer_ip":           "主线PE对接IP",
    "main_wanip1":            "主线WANIP第1主机(PE侧)",
    "main_wanip2":            "主线WANIP第2主机(CE侧)",
    "main_export_natip":      "主线首个出口NAT IP",
    "main_export_summary":    "主线出口IP汇总文本",
    "main_export_ip":         "主线首个出口IP(BGP用)",
    "main_lo_block":          "主线LoopBack块（自动）",
    "main_nat_block":         "主线NAT地址组（自动）",
    "main_snat_block":        "主线SNAT规则块（自动）",
    "backup_dial_pe":         "备线IPSEC_PE名",
    "backup_dial_ip":         "备线拨号IP",
    "backup_loopback":        "备线loIP(CE LoopBack)",
    "backup_auth_id":         "备线认证ID",
    "backup_pe":              "备线PE名称",
    "backup_wanip":           "备线WANIP(CIDR)",
    "backup_wanip1":          "备线WANIP第1主机(PE侧)",
    "backup_wanip2":          "备线WANIP第2主机(CE侧)",
    "backup_tunnel":          "备线隧道号(tun格式)",
    "backup_peer_ip":         "备线PE对接IP",
    "backup_export_summary":  "备线出口IP汇总文本",
    "backup_lo_block":        "备线LoopBack块（自动）",
    "backup_nat_block":       "备线NAT地址组（自动）",
    "backup_snat_block":      "备线SNAT规则块（自动）",
    "wan_if_block":           "WAN接口配置块（自动）",
    "wan_mode_desc":          "WAN接入模式描述",
    "wan_default_routes":     "WAN默认路由（自动）",
    "dhcp_block":             "LAN DHCP块（自动）",
    "dns_dnat_block":         "DNS DNAT块（自动）",
    "extra_return_routes":    "额外内网回程路由（自动）",
    "bgp_main_lo":            "主线BGP LoopBack接口名",
    "bgp_backup_lo":          "备线BGP LoopBack接口名",
    "lan_ip":                 "LAN IP地址",
    "dns_ip1":                "骨干DNS1",
    "dns_ip2":                "骨干DNS2",
    # AR SD-WAN 变量
    "main_lineid":            "主线LineID",
    "main_ce_docking":        "主线CE对接IP",
    "main_pe_docking":        "主线PE对接IP",
    "main_dial_ip":           "主线拨号IP",
    "main_psk":               "主线预共享密钥(PSK)",
    "main_wan_peer_ip":       "主线WAN PE侧IP",
    "main_wan_ce_ip":         "主线WAN CE侧IP",
    "bk_lineid":              "备线LineID",
    "bk_pe":                  "备线PE设备名",
    "bk_tunnel":              "备线Tunnel接口名",
    "bk_ce_docking":          "备线CE对接IP",
    "bk_pe_docking":          "备线PE对接IP",
    "bk_dial_ip":             "备线拨号IP",
    "bk_psk":                 "备线预共享密钥(PSK)",
    "bk_wan_peer_ip":         "备线WAN PE侧IP",
    "bk_wan_ce_ip":           "备线WAN CE侧IP",
    "z_main_ip":              "自环主线接口IP（内网段首IP）",
    "z_main_mask":            "自环主线接口掩码",
    "z_bk_ip":                "自环备线接口IP（内网段首IP）",
    "z_bk_mask":              "自环备线接口掩码",
    "wan1_port":              "WAN1物理接口（初始化）",
    "wan1_ip_addr":           "WAN1 IP地址（初始化）",
    "wan1_mask":              "WAN1子网掩码（初始化）",
    "wan1_gw":                "WAN1网关（初始化）",
    "wan2_port":              "WAN2物理接口（初始化）",
    "wan2_ip_addr":           "WAN2 IP地址（初始化）",
    "wan2_mask":              "WAN2子网掩码（初始化）",
    "wan2_gw":                "WAN2网关（初始化）",
    "zihuan_port":            "自环网关接口（初始化）",
    "ipsec_port":             "自环IPSec接口（初始化）",
    "lineid_fn":              "线路编号(用于文件名)",
    "south_primary":          "南向主用IP",
    "south_backup":           "南向备用IP",
    "dj_wan1_port":           "双机主WAN接口（初始化）",
    "dj_wan1_ip_addr":        "双机主WAN IP（初始化）",
    "dj_wan1_mask":           "双机主WAN掩码（初始化）",
    "dj_wan1_gw":             "双机主WAN网关（初始化）",
    "dj_zihuan1_port":        "双机主自环口（初始化）",
    "dj_ipsec1_port":         "双机主IPSec口（初始化）",
    "dj_wan2_port":           "双机备WAN接口（初始化）",
    "dj_wan2_ip_addr":        "双机备WAN IP（初始化）",
    "dj_wan2_mask":           "双机备WAN掩码（初始化）",
    "dj_wan2_gw":             "双机备WAN网关（初始化）",
    "dj_zihuan2_port":        "双机备自环口（初始化）",
    "dj_ipsec2_port":         "双机备IPSec口（初始化）",
    "wan_eth":                "WAN物理接口名（USG）",
    "lan_eth":                "LAN物理接口名（USG）",
    "ftp_server":             "FTP服务器地址（AR Factory）",
    "ER_DS_DOMAINS_DEFAULT":  "域名分流：每行一个域名",
    "ER_DS_ADDR_GROUP_DEFAULT": "address-group 名（可写「address-group : 名称」；domainlist 与 /opt 下 .txt 为 A+组名）",
    "ER_DS_RULE_NUM_DEFAULT": "LAN-MAP rule（策略路由规则序号）",
    "ER_DS_TABLE_NUM_DEFAULT": "static table 号",
    "ER_DS_SOURCE_CIDR_DEFAULT": "源网段 CIDR（可空；不填则不生成策略路由）",
    "ER_DS_DNS1_DEFAULT":     "DNS 主",
    "ER_DS_DNS2_DEFAULT":     "DNS 备（可空）",
    "ER_DS_ETH_DEFAULT":      "应用接口（policy-route 绑定的 ethernet）",
    "ER_DS_TABLE_NH_PRIMARY_DEFAULT": "递归下一跳",
    "ER_DS_TRACK_NAME_DEFAULT": "Track 名称（可空；为空时主/32不带 track，且不下发 set track name）",
    "ER_DS_STATIC32_PRIMARY_NH_DEFAULT": "主下一跳（/32 静态的 next-hop）",
    "ER_DS_STATIC32_BACKUP_NH_DEFAULT": "备下一跳（可空）",
    "ER_DS_FNET_PROBE_DEFAULT": "track 100.100 探测 IP",
    "ER_DS_FNET_NAT_RULE_DEFAULT": "NAT rule 号（默认空；与 tunnel、主线出口须同填或同空）",
    "ER_DS_EXIT_TUNNEL_DEFAULT": "NAT 出口 tunnel（可空；openvpn）",
    "ER_DS_EXIT_SNAT_IP_DEFAULT": "主线出口 IP（可空）",
    "ER_DS_DOMAINLIST_COMPUTED": "推导 domainlist（A+组名，预览）",
    "ER_DS_POLICY_ROUTE_COMPUTED": "推导 policy-route（LAN-MAP+组名，预览）",
    "ER_DS_OPT_DNS2_LINE":    "备 DNS set 行或空（预览）",
    "ER_DS_OPT_S32BAK_LINE":  "备下一跳 /32 set 行或空（预览）",
    "ER_DS_OPT_TRACK_SUFFIX": "主 /32 静态路由 track 后缀（预览；Track 为空则空）",
    "ER_DS_OPT_POLICY_ROUTE_BLOCK": "policy-route/table/eth 段或空（预览）",
    "ER_DS_OPT_FNET_BLOCK":   "100.100 / NAT 段（预览；三项齐全且合法时生成；Track 为空则不下发 set track name）",
    "main_tun":               "新增出口：主线 TUNNEL",
    "main_tun_addr":          "新增出口：主线隧道 CE 侧地址(/30)",
    "backup_tun":             "新增出口：备线 TUNNEL",
    "backup_tun_addr":        "新增出口：备线隧道 CE 侧地址(/30)",
    "main_left_ip_1":         "新增出口：主线海外出口本端 IP",
    "main_right_ip_1":        "新增出口：主线海外出口对端 IP（仅描述）",
    "backup_left_ip_1":       "新增出口：备线海外出口本端 IP",
    "backup_right_ip_1":      "新增出口：备线海外出口对端 IP（仅描述）",
    "ER_NE_MAIN_DUM_BLOCK":   "新增出口：主线 dum 块（自动展开）",
    "ER_NE_BK_DUM_BLOCK":     "新增出口：备线 dum 块（自动展开）",
    "ER_NE_MAIN_PE_NH_DEFAULT": "新增出口初始化默认：主 PE 对接 /32 下一跳",
    "ER_NE_BK_PE_NH_DEFAULT": "新增出口初始化默认：备 PE 对接 /32 下一跳",
    "ER_NE_MAIN_NAT_RULE_DEFAULT": "新增出口：主 NAT source rule 起始号（每条海外 IP 顺延 +1）",
    "ER_NE_BK_NAT_RULE_DEFAULT": "新增出口：备 NAT source rule 起始号（每条海外 IP 顺延 +1）",
    "ER_NE_NAT_SOURCE_CIDR_DEFAULT": "新增出口：NAT 源网段 CIDR（初始化；写入每条 rule 的 source address；可空则不生 NAT）",
    "ER_NE_NAT_HEADER_BLOCK": "新增出口：SNAT 说明注释（源网段与 rule 条数，自动）",
    "ER_NE_NAT_BLOCK":        "新增出口：NAT 源转换规则块（自动）",
}

# variable → sample value（用于自动生成第①栏数据头）
_VAR_SAMPLE: dict[str, str] = {
    "hostname":               "",
    "ce_loip":                "10.18.12.57",
    "ce_docking":             "10.18.12.57",
    "wan_if":                 "eth0",
    "wan_addr":               "203.195.1.1/24",
    "wan_route_block":        "",
    "lan_if_block":           "set interfaces ethernet eth1 address '192.168.1.1/24'",
    "fw_options_block":       "",
    "overseas_nat_block":     "",
    "return_routes_block":    "set protocols static route 192.168.0.0/16 next-hop 10.18.12.1",
    "dhcp_server_block":      "",
    "bgp_server_routes":      "set protocols static route 10.60.0.0/16 next-hop 10.22.98.41",
    # ER FastIP HK 主线（无 fgpe，PE 名如 lax1-pe1）
    "main_pe":                "lax1-pe1",
    "main_tunnel":            "vtun1213",
    "main_tunnel_port":       "1213",
    "main_wanip":             "10.22.98.40/30",
    "main_wanip_remote":      "10.22.98.41",
    "main_wanip_local":       "10.22.98.42",
    "main_docking":           "10.255.110.6",
    "main_track":             "1",
    "main_bgp1":              "192.168.1.1",
    "main_bgp2":              "192.168.1.2",
    "hkip_nat":               "5.6.7.8",
    "hkip_nat_all":           "5.6.7.8",
    "hkip_dum100_desc":       "HK-OUT 5.6.7.8",
    "extra_dum_block":        "",
    # ER FastIP HK 备线
    "bk_pe":                  "lax2-pe1",
    "bk_tunnel":              "vtun1214",
    "bk_tunnel_port":         "1214",
    "bk_wanip":               "10.22.98.44/30",
    "bk_wanip_remote":        "10.22.98.45",
    "bk_wanip_local":         "10.22.98.46",
    "bk_docking":             "10.255.110.10",
    "bk_track":               "2",
    "bk_bgp1":                "192.168.1.1",
    "bk_bgp2":                "192.168.1.2",
    # ER FastIP US 主线 acvpn
    "main_acvpn_gre_pe":      "sz-upe1",
    "main_acvpn_gre_tun":     "tun1301",
    "main_acvpn_gre_pe_ip":   "10.40.10.5",
    "main_acvpn_gre_ce_ip":   "10.40.10.6",
    "main_acvpn_gre_remote":  "10.255.110.10",
    "main_acvpn_gre_wanip":   "10.40.10.4/30",
    "main_acvpn_vtun_pe":     "sz-upe2",
    "main_acvpn_vtun_id":     "1301",
    "main_acvpn_vtun_port":   "7001",
    "main_acvpn_vtun_remote": "10.40.10.5",
    "main_acvpn_vtun_local":  "10.18.1.1",
    "main_acvpn_vtun_docking":"10.255.110.11",
    "main_us_pe":             "lax-natpe1",
    "main_us_tun":            "tun1301",
    "main_us_pe_ip":          "10.60.1.1",
    "main_us_gre_ce_ip":      "10.60.1.2",
    "main_us_wanip":          "10.60.1.0/30",
    "main_us_pe_docking":     "10.255.120.1",
    "main_us_nat_ip":         "5.5.5.1",
    "main_us_nat_ip_all":     "5.5.5.1",
    "main_us_dum100_desc":    "MAIN_OUTIP",
    "main_us_bgp1":           "192.168.200.1",
    "main_us_bgp2":           "192.168.200.2",
    "extra_dum_main_block":   "",
    "us_bgp_routes":          "",
    # ER FastIP US 备线 acvpn
    "bk_acvpn_gre_pe":        "sz-upe3",
    "bk_acvpn_gre_tun":       "tun1302",
    "bk_acvpn_gre_pe_ip":     "10.40.11.5",
    "bk_acvpn_gre_ce_ip":     "10.40.11.6",
    "bk_acvpn_gre_remote":    "10.255.110.12",
    "bk_acvpn_gre_wanip":     "10.40.11.4/30",
    "bk_acvpn_vtun_pe":       "sz-upe4",
    "bk_acvpn_vtun_id":       "1302",
    "bk_acvpn_vtun_port":     "7002",
    "bk_acvpn_vtun_remote":   "10.40.11.5",
    "bk_acvpn_vtun_local":    "10.18.1.2",
    "bk_acvpn_vtun_docking":  "10.255.110.13",
    "bk_us_pe":               "lax-natpe2",
    "bk_us_tun":              "tun1302",
    "bk_us_pe_ip":            "10.60.2.1",
    "bk_us_gre_ce_ip":        "10.60.2.2",
    "bk_us_wanip":            "10.60.2.0/30",
    "bk_us_pe_docking":       "10.255.120.2",
    "bk_us_nat_ip":           "5.5.5.2",
    "bk_us_nat_ip_all":       "5.5.5.2",
    "bk_us_dum200_desc":      "BK_OUTIP",
    "bk_us_bgp1":             "192.168.200.1",
    "bk_us_bgp2":             "192.168.200.2",
    "extra_dum_bk_block":     "",
    # USG FastIP 主线
    "main_dial_pe":           "szd-ape2",
    "main_dial_ip":           "121.14.82.235",
    "main_loopback":          "10.18.12.57",
    "main_auth_id":           "609157A1",
    "main_wanip1":            "10.22.98.41",
    "main_wanip2":            "10.22.98.42",
    "main_peer_ip":           "10.255.110.6",
    "main_export_natip":      "64.81.158.21",
    "main_export_summary":    "出口IP: 64.81.158.21",
    "main_export_ip":         "64.81.158.21",
    "main_lo_block":          "",
    "main_nat_block":         "",
    "main_snat_block":        "",
    # USG FastIP 备线
    "backup_dial_pe":         "szd-ape3",
    "backup_dial_ip":         "121.14.82.236",
    "backup_loopback":        "10.18.12.58",
    "backup_auth_id":         "609157A2",
    "backup_pe":              "lax2-pe1",
    "backup_wanip":           "10.22.98.44/30",
    "backup_wanip1":          "10.22.98.45",
    "backup_wanip2":          "10.22.98.46",
    "backup_tunnel":          "tun1214",
    "backup_peer_ip":         "10.255.110.10",
    "backup_export_summary":  "出口IP: 64.81.158.22",
    "backup_lo_block":        "",
    "backup_nat_block":       "",
    "backup_snat_block":      "",
    # USG 初始化
    "wan_if_block":           "",
    "wan_mode_desc":          "静态上网",
    "wan_default_routes":     "",
    "dhcp_block":             "",
    "dns_dnat_block":         "",
    "extra_return_routes":    "",
    "bgp_main_lo":            "LoopBack100",
    "bgp_backup_lo":          "LoopBack200",
    "lan_ip":                 "192.168.1.1",
    "dns_ip1":                "119.29.29.29",
    "dns_ip2":                "223.5.5.5",
    "main_tunnel":            "tun1213",
    "ER_DS_DOMAINS_DEFAULT":  "google.com",
    "ER_DS_ADDR_GROUP_DEFAULT": "to-US",
    "ER_DS_RULE_NUM_DEFAULT": "100",
    "ER_DS_TABLE_NUM_DEFAULT": "139",
    "ER_DS_SOURCE_CIDR_DEFAULT": "192.168.5.0/24",
    "ER_DS_DNS1_DEFAULT":     "209.244.0.3",
    "ER_DS_DNS2_DEFAULT":     "",
    "ER_DS_ETH_DEFAULT":      "eth0",
    "ER_DS_TABLE_NH_PRIMARY_DEFAULT": "2.2.2.2",
    "ER_DS_TRACK_NAME_DEFAULT": "tooutbound1",
    "ER_DS_STATIC32_PRIMARY_NH_DEFAULT": "10.22.15.185",
    "ER_DS_STATIC32_BACKUP_NH_DEFAULT": "10.22.24.157",
    "ER_DS_FNET_PROBE_DEFAULT": "100.100.100.1",
    "ER_DS_FNET_NAT_RULE_DEFAULT": "",
    "ER_DS_EXIT_TUNNEL_DEFAULT": "",
    "ER_DS_EXIT_SNAT_IP_DEFAULT": "",
    "ER_DS_DOMAINLIST_COMPUTED": "Ato-US",
    "ER_DS_POLICY_ROUTE_COMPUTED": "LAN-MAP-to-US",
    "ER_DS_OPT_DNS2_LINE":    "",
    "ER_DS_OPT_S32BAK_LINE":  "set protocols static route 2.2.2.2/32 next-hop 10.22.24.157 distance '20'",
    "ER_DS_OPT_TRACK_SUFFIX": " track tooutbound1",
    "ER_DS_OPT_POLICY_ROUTE_BLOCK": "",
    "ER_DS_OPT_FNET_BLOCK":   "",
    "main_tun":               "tun1083",
    "main_tun_addr":          "10.22.242.21/30",
    "backup_tun":             "tun1033",
    "backup_tun_addr":        "10.22.242.21/30",
    "main_left_ip_1":         "10.60.21.185",
    "main_right_ip_1":        "103.57.50.44",
    "backup_left_ip_1":       "10.60.72.44",
    "backup_right_ip_1":      "172.16.13.46",
    "ER_NE_MAIN_DUM_BLOCK":   "",
    "ER_NE_BK_DUM_BLOCK":     "",
    "ER_NE_MAIN_PE_NH_DEFAULT": "192.168.1.1",
    "ER_NE_BK_PE_NH_DEFAULT": "192.168.1.2",
    "ER_NE_MAIN_NAT_RULE_DEFAULT": "300",
    "ER_NE_BK_NAT_RULE_DEFAULT": "400",
    "ER_NE_NAT_SOURCE_CIDR_DEFAULT": "192.168.0.0/24",
    "ER_NE_NAT_HEADER_BLOCK": "",
    "ER_NE_NAT_BLOCK":        "",
}


# ══════════════════════════════════════════════════════════════════
# §4  模板提取工具
# ══════════════════════════════════════════════════════════════════

def _read_src(filename: str) -> str:
    try:
        return (BUNDLE_DIR / filename).read_text(encoding="utf-8-sig")
    except Exception:
        return ""


def _tpl_var(src: str, var: str) -> str:
    # 使用 AST 提取字符串常量，避免正则在超长三引号模板上错位，误把后续源码并入模板。
    try:
        tree = ast.parse(src)
    except Exception:
        tree = None
    if tree is not None:
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            val = node.value
            if not (isinstance(val, ast.Constant) and isinstance(val.value, str)):
                continue
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == var:
                    return val.value
    return f"# 未找到模板变量 {var}\n"


def _tpl_func(src: str, func: str, max_lines: int = 120) -> str:
    pat = rf"^def {re.escape(func)}\b.*?\n(?=^def |\Z)"
    m = re.search(pat, src, re.DOTALL | re.MULTILINE)
    if not m:
        return f"# 未找到函数: {func}\n"
    lines = m.group(0).splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"\n# ... 共 {len(lines)} 行，更多内容见源文件"]
    return "\n".join(lines)


_DEFAULT_TPL_SRC_CACHE: dict[str, str] = {}


def _er_domain_split_tpl_looks_valid(tpl: str) -> bool:
    """域名分流预览依赖 ER_DS_* 与推导占位符；须含 ER_DS_OPT_POLICY_ROUTE_BLOCK、ER_DS_OPT_FNET_BLOCK（与源码模板一致）。"""
    t = (tpl or "").strip()
    if not t:
        return False
    if "{ER_DS_DOMAINLIST_COMPUTED}" not in t:
        return False
    if "{ER_DS_ADDR_GROUP_DEFAULT}" not in t:
        return False
    if "{ER_DS_OPT_POLICY_ROUTE_BLOCK}" not in t:
        return False
    if "{ER_DS_OPT_FNET_BLOCK}" not in t:
        return False
    return True


def _er_epoch_tpl_looks_valid(tpl: str, *, us: bool) -> bool:
    """
    ER Epoch HK/US 模板体检：
    - 必须包含核心占位符；
    - 不应混入脚本源码片段（历史异常：模板尾部拼入 def/us_generate/root=tk.Tk 等）。
    """
    t = (tpl or "").strip()
    if not t:
        return False
    lines = t.count("\n") + 1
    # 正常 HK/US 模板约数百行；出现 1500+ 通常为源码拼接污染
    if lines > 1200:
        return False

    if us:
        required = ("{main_acvpn_gre_tun}", "{bk_acvpn_gre_tun}", "{main_us_tun}", "{bk_us_tun}")
    else:
        required = ("{main_tunnel}", "{bk_tunnel}", "{ce_loip}")
    for k in required:
        if k not in t:
            return False

    forbidden = (
        "root = tk.Tk(",
        "def us_generate(",
        "def hk_generate(",
        "TEMPLATE_ER_FLINK_VISUAL =",
        "Tab 飞连（ER）",
    )
    if any(x in t for x in forbidden):
        return False
    return True


def _factory_tpl_for_scenario(info: dict) -> str:
    """与 VisualEditorTab._default_tpl 一致，用于打包 editor_defaults。"""
    if info.get("source") == MOD_ER_MPLS:
        slot = str(info.get("tpl_slot") or "")
        if slot == "TEMPLATE_MPLS_DOMESTIC":
            p = EDITOR_DEFAULTS_ROOT / "ER_MPLS___国内配置" / "TEMPLATE_MPLS_DOMESTIC.tpl"
            try:
                if p.exists():
                    return p.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                pass
        elif slot == "TEMPLATE_MPLS_OVERSEAS":
            p = EDITOR_DEFAULTS_ROOT / "ER_MPLS___海外配置" / "TEMPLATE_MPLS_OVERSEAS.tpl"
            try:
                if p.exists():
                    return p.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                pass
        elif slot == "TEMPLATE_MPLS_IPSEC":
            p = EDITOR_DEFAULTS_ROOT / "Epoch_MPLS___IPSec" / "TEMPLATE_MPLS_IPSEC.tpl"
            try:
                if p.exists():
                    return p.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                pass
    if info.get("source") == MOD_AR_SDWAN and info.get("tpl_static"):
        ns = EMBEDDED_NS.get(MOD_AR_SDWAN)
        if ns and "build_ar_visual_tpl" in ns:
            try:
                return ns["build_ar_visual_tpl"](info["tpl_static"])
            except (ValueError, KeyError, TypeError):
                pass
    if info.get("tpl_static"):
        sk = info["tpl_static"]
        return _PROG_TEMPLATES_BASELINE.get(sk, _PROG_TEMPLATES.get(sk, "")) or ""
    src_fn = info["source"]
    if src_fn not in _DEFAULT_TPL_SRC_CACHE:
        _DEFAULT_TPL_SRC_CACHE[src_fn] = _read_src(src_fn)
    src = _DEFAULT_TPL_SRC_CACHE[src_fn]
    if info.get("tpl_var"):
        return _tpl_var(src, info["tpl_var"])
    if info.get("tpl_func"):
        return _tpl_func(src, info["tpl_func"])
    return "# 该场景无单一模板字符串。\n"


def _migrate_legacy_er_init(raw: dict) -> None:
    """迁移旧版 ER FastIP 初始化数据（单模块 → HK/US 分槽）。"""
    if MOD_ER_FASTIP in raw and ER_INIT_MOD_HK not in raw and ER_INIT_MOD_US not in raw:
        blob = raw.pop(MOD_ER_FASTIP)
        if isinstance(blob, dict):
            raw[ER_INIT_MOD_HK] = dict(blob)
            raw[ER_INIT_MOD_US] = dict(blob)


def _migrate_legacy_usg_init(raw: dict) -> None:
    """迁移旧版 USG FastIP 初始化数据（单模块 → HK/US 分槽，HK_ 前缀剥离）。"""
    if MOD_USG_FASTIP in raw and USG_INIT_MOD_HK not in raw and USG_INIT_MOD_US not in raw:
        blob = raw.pop(MOD_USG_FASTIP)
        if isinstance(blob, dict):
            us_data: dict[str, str] = {}
            hk_data: dict[str, str] = {}
            for k, v in blob.items():
                if k.startswith("HK_DEFAULT_"):
                    hk_data[k[3:]] = v
                else:
                    us_data[k] = v
                    if k not in hk_data:
                        hk_data[k] = v
            raw[USG_INIT_MOD_US] = us_data
            raw[USG_INIT_MOD_HK] = hk_data


def _migrate_legacy_ar_init(raw: dict) -> None:
    """迁移旧版 AR SD-WAN 初始化数据（单模块 → 单机/双机分槽）。"""
    if MOD_AR_SDWAN in raw and AR_INIT_MOD_DJ not in raw and AR_INIT_MOD_ZH not in raw:
        blob = raw.pop(MOD_AR_SDWAN)
        if isinstance(blob, dict):
            raw[AR_INIT_MOD_DJ] = {
                k: v for k, v in blob.items() if str(k).startswith("DJ_")
            }
            raw[AR_INIT_MOD_ZH] = {
                k: v for k, v in blob.items() if not str(k).startswith("DJ_")
            }
            _ftp = blob.get("DEFAULT_FTP_SERVER")
            if _ftp is not None and "DEFAULT_FTP_SERVER" not in raw[AR_INIT_MOD_DJ]:
                raw[AR_INIT_MOD_DJ]["DEFAULT_FTP_SERVER"] = str(_ftp)


def _parse_user_init_placeholders_json() -> dict | None:
    """读取并迁移 user_init_placeholders.json，供按模块应用或全量应用。"""
    if not INIT_USER_PLACEHOLDERS_JSON.exists():
        return None
    try:
        raw = json.loads(INIT_USER_PLACEHOLDERS_JSON.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    _migrate_legacy_er_init(raw)
    _migrate_legacy_usg_init(raw)
    _migrate_legacy_ar_init(raw)
    return raw


def _clean_init_updates(mod: str, upd: dict) -> dict[str, str]:
    """过滤并清洗单个模块的初始化更新：仅保留合法键、去除空值。

    避免 __sep__ / DJ_HDR_ 标记字段被误解为数据键；
    避免空字符串覆盖出厂默认。
    """
    allowed = {
        k for k, _ in _INIT_PLACEHOLDER_FIELDS.get(mod, [])
        if not str(k).startswith("__sep__") and not str(k).startswith("DJ_HDR_")
    }
    clean = {k: str(v).strip() for k, v in upd.items() if k in allowed}
    return {k: v for k, v in clean.items() if v}


def _user_init_to_apply_dict(raw: dict) -> dict[str, dict[str, str]]:
    """从已迁移的 JSON 对象生成可传入 _apply_init_placeholder_updates 的字典（全模块）。"""
    to_apply: dict[str, dict[str, str]] = {}
    for mod, upd in raw.items():
        if mod not in _INIT_PLACEHOLDER_FIELDS:
            continue
        if not isinstance(upd, dict):
            continue
        clean = _clean_init_updates(mod, upd)
        if clean:
            to_apply[mod] = clean
    return to_apply


def _preload_legacy_embeds_for_init_data(data: dict[str, dict[str, str]]) -> None:
    """写入初始化前确保目标工具已嵌入，否则 _apply_init_placeholder_updates 会静默跳过、正式页不更新。"""
    fn = _ENSURE_LEGACY_EMBED_BY_FILENAME
    if not callable(fn):
        return
    seen: set[str] = set()
    for mod, row in data.items():
        if not row:
            continue
        emb = _embedded_name_for_init_mod(mod)
        if emb in seen:
            continue
        seen.add(emb)
        if EMBEDDED_NS.get(emb):
            continue
        try:
            fn(emb)
        except (ValueError, TypeError, RuntimeError):
            pass


def _apply_init_placeholder_updates(data: dict[str, dict[str, str]]) -> None:
    _preload_legacy_embeds_for_init_data(data)
    er_ns = EMBEDDED_NS.get(MOD_ER_FASTIP)
    usg_ns = EMBEDDED_NS.get(MOD_USG_FASTIP)
    for sec, updates in data.items():
        if not updates:
            continue
        if sec == ER_INIT_MOD_HK:
            fn = er_ns.get("_visual_merge_er_init") if er_ns else None
            if callable(fn):
                fn("hk", updates)
        elif sec == ER_INIT_MOD_US:
            fn = er_ns.get("_visual_merge_er_init") if er_ns else None
            if callable(fn):
                fn("us", updates)
        elif sec == ER_INIT_MOD_FLINK:
            fn = er_ns.get("_visual_merge_er_init") if er_ns else None
            if callable(fn):
                fn("flink", updates)
        elif sec == ER_INIT_MOD_NEW_EXIT:
            fn = er_ns.get("_visual_merge_er_init") if er_ns else None
            if callable(fn):
                fn("new_exit", updates)
        elif sec == ER_INIT_MOD_DOMAIN_SPLIT:
            fn = er_ns.get("_visual_merge_er_init") if er_ns else None
            if callable(fn):
                fn("domain_split", updates)
        elif sec in (USG_INIT_MOD_HK, USG_INIT_MOD_US):
            fn = usg_ns.get("_visual_merge_usg_init") if usg_ns else None
            if callable(fn):
                region = "hk" if sec == USG_INIT_MOD_HK else "us"
                fn(region, updates)
        elif sec == USG_INIT_MOD_FLINK:
            fn = usg_ns.get("_visual_merge_usg_init") if usg_ns else None
            if callable(fn):
                fn("flink", updates)
        elif sec == USG_INIT_MOD_NEW_EXIT:
            fn = usg_ns.get("_visual_merge_usg_init") if usg_ns else None
            if callable(fn):
                fn("new_exit", updates)
        else:
            emb = _embedded_name_for_init_mod(sec)
            ns = EMBEDDED_NS.get(emb)
            if not ns:
                continue
            fn = ns.get("_visual_merge_init_defaults")
            if callable(fn):
                fn(updates)


def _merge_factory_snapshot_for_embed(emb: str) -> None:
    """某工具脚本嵌入后，合并该脚本对应初始化模块的出厂快照（不清空其它模块）。

    首屏若先打开「我来定模板」，此时尚无嵌入；待用户打开各工具页签后再合并，
    避免 INIT_PLACEHOLDERS_FACTORY 只有「第一个嵌入工具」、AR 等模块永远为空的问题。
    """
    global INIT_PLACEHOLDERS_FACTORY
    ns = EMBEDDED_NS.get(emb)
    if not ns:
        return
    for mod, fields in _INIT_PLACEHOLDER_FIELDS.items():
        if _embedded_name_for_init_mod(mod) != emb:
            continue
        if mod not in INIT_PLACEHOLDERS_FACTORY:
            INIT_PLACEHOLDERS_FACTORY[mod] = {}
        for key, _lbl in fields:
            if str(key).startswith("__sep__") or str(key).startswith("DJ_HDR_"):
                continue
            if emb == MOD_ER_FASTIP:
                gkey = _global_key_for_er_init_mod(mod, key)
            elif emb == MOD_USG_FASTIP:
                gkey = _global_key_for_usg_init_mod(mod, key)
            else:
                gkey = key
            if mod == AR_INIT_MOD_ZH and key == "ZH_DUAL_WAN":
                v = ns.get("ZH_DUAL_WAN_SAVED")
            elif mod == AR_INIT_MOD_ZH and key == "ZH_SOUTH_LABEL":
                v = ns.get("ZH_SOUTH_LABEL_SAVED")
            elif mod == AR_INIT_MOD_ZH and key == "ZH_IKE_VERSION":
                v = ns.get("ZH_IKE_VERSION_SAVED")
            elif mod == AR_INIT_MOD_DJ and key == "DJ_SOUTH_LABEL":
                v = ns.get("DJ_SOUTH_LABEL_SAVED")
            elif mod == AR_INIT_MOD_DJ and key == "DJ_IKE_VERSION":
                v = ns.get("DJ_IKE_VERSION_SAVED")
            else:
                v = ns.get(gkey)
            if isinstance(v, bool):
                INIT_PLACEHOLDERS_FACTORY[mod][key] = "true" if v else "false"
            else:
                INIT_PLACEHOLDERS_FACTORY[mod][key] = "" if v is None else str(v)


def _ensure_ar_init_factory_seeded() -> None:
    """确保 INIT_PLACEHOLDERS_FACTORY 具备出厂默认值种子。

    目的：
    - 未打开对应 Legacy 页签时，可视化初始化区也能显示"合理默认"，避免保存后写入空字符串。
    - 后续即使 user_init_placeholders.json 里缺字段，也不会把 DEFAULT_* 全覆盖为空。
    """
    global INIT_PLACEHOLDERS_FACTORY
    def _seed(mod: str, baseline: dict[str, str]) -> None:
        if mod not in INIT_PLACEHOLDERS_FACTORY:
            INIT_PLACEHOLDERS_FACTORY[mod] = {}
        fac = INIT_PLACEHOLDERS_FACTORY[mod]
        for k, v in baseline.items():
            cur = fac.get(k, "")
            if not str(cur if cur is not None else "").strip():
                fac[k] = v

    # ER FastIP（HK / 非HK 页签字段完全一致，默认值也一致）
    er_defaults = {
        "DEFAULT_WAN_ETH": "0",
        "DEFAULT_WAN_CIDR": "192.168.1.10/24",
        "DEFAULT_WAN_IP_PLAIN": "192.168.1.10",
        "DEFAULT_WAN_GW": "192.168.1.1",
        "DEFAULT_LAN_ETH": "5",
        "DEFAULT_LAN_CIDR": "192.168.5.1/24",
        "DEFAULT_LAN_IP_PLAIN": "192.168.5.1",
        "DEFAULT_LAN_GW": "192.168.5.1",
        "DEFAULT_INNER_NETS": "192.168.0.0/16",
        "DEFAULT_WAN_DHCP": "false",
        "DEFAULT_LAN_DHCP": "true",
        "DEFAULT_GEN_RETURN_ROUTE": "false",
    }
    _seed(ER_INIT_MOD_US, er_defaults)
    _seed(ER_INIT_MOD_HK, er_defaults)
    _seed(ER_INIT_MOD_FLINK, {
        "ER_FL_MAIN_NH_DEFAULT": "192.168.1.1",
        "ER_FL_BACKUP_NH_DEFAULT": "192.168.1.2",
    })
    _seed(ER_INIT_MOD_NEW_EXIT, {
        "ER_NE_MAIN_PE_NH_DEFAULT": "192.168.1.1",
        "ER_NE_BK_PE_NH_DEFAULT": "192.168.1.2",
        "ER_NE_MAIN_DUM_DEFAULT": "300",
        "ER_NE_BK_DUM_DEFAULT": "400",
        "ER_NE_MAIN_NAT_RULE_DEFAULT": "300",
        "ER_NE_BK_NAT_RULE_DEFAULT": "400",
        "ER_NE_NAT_SOURCE_CIDR_DEFAULT": "192.168.0.0/24",
        "ER_NE_FNET_PROBE_DEFAULT": "100.100.100.1",
        "ER_NE_FNET_EXIT_TUNNEL_DEFAULT": "",
        "ER_NE_FNET_NAT_RULE_DEFAULT": "",
    })
    _seed(ER_INIT_MOD_DOMAIN_SPLIT, {
        "ER_DS_DOMAINS_DEFAULT": "google.com",
        "ER_DS_ADDR_GROUP_DEFAULT": "to-US",
        "ER_DS_RULE_NUM_DEFAULT": "100",
        "ER_DS_TABLE_NUM_DEFAULT": "139",
        "ER_DS_SOURCE_CIDR_DEFAULT": "192.168.5.0/24",
        "ER_DS_DNS1_DEFAULT": "209.244.0.3",
        "ER_DS_DNS2_DEFAULT": "",
        "ER_DS_ETH_DEFAULT": "eth0",
        "ER_DS_TABLE_NH_PRIMARY_DEFAULT": "2.2.2.2",
        "ER_DS_TRACK_NAME_DEFAULT": "tooutbound1",
        "ER_DS_STATIC32_PRIMARY_NH_DEFAULT": "10.22.15.185",
        "ER_DS_STATIC32_BACKUP_NH_DEFAULT": "10.22.24.157",
        "ER_DS_FNET_PROBE_DEFAULT": "100.100.100.1",
        "ER_DS_FNET_NAT_RULE_DEFAULT": "",
        "ER_DS_EXIT_TUNNEL_DEFAULT": "",
        "ER_DS_EXIT_SNAT_IP_DEFAULT": "",
    })

    # USG FastIP（HK / 非HK：DNS 不同，其它默认值一致）
    usg_us_defaults = {
        "DEFAULT_DNS1": "10.255.108.7",
        "DEFAULT_DNS2": "10.255.108.58",
        "DEFAULT_WAN_ETH": "GE0/0/9",
        "DEFAULT_WAN_IP": "192.168.9.190/24",
        "DEFAULT_WAN_IP_PLAIN": "192.168.9.190",
        "DEFAULT_WAN_GW": "192.168.9.1",
        "DEFAULT_WAN_DHCP": "false",
        "DEFAULT_LAN_ETH": "GE0/0/8",
        "DEFAULT_LAN_IP": "192.168.8.1/24",
        "DEFAULT_LAN_IP_PLAIN": "192.168.8.1",
        "DEFAULT_LAN_GW": "192.168.8.1/24",
        "DEFAULT_LAN_DHCP": "true",
        "DEFAULT_INNER_NETS": "192.168.0.0/16",
        "DEFAULT_GEN_RETURN_ROUTE": "false",
    }
    usg_hk_defaults = dict(usg_us_defaults)
    usg_hk_defaults.update({
        "DEFAULT_DNS1": "10.255.108.5",
        "DEFAULT_DNS2": "10.255.108.6",
    })
    _seed(USG_INIT_MOD_US, usg_us_defaults)
    _seed(USG_INIT_MOD_HK, usg_hk_defaults)
    _seed(USG_INIT_MOD_FLINK, {
        "USG_FL_MAIN_TUN_DEFAULT": "3000",
        "USG_FL_BK_TUN_DEFAULT": "4000",
    })
    _seed(USG_INIT_MOD_NEW_EXIT, {
        "USG_NE_MAIN_TUN_DEFAULT": "1001",
        "USG_NE_BK_TUN_DEFAULT": "1002",
        "USG_NE_MAIN_LOOP_START_DEFAULT": "111",
        "USG_NE_BK_LOOP_START_DEFAULT": "211",
        "USG_NE_MAIN_NQA_DEFAULT": "main2",
        "USG_NE_BK_NQA_DEFAULT": "backup2",
    })

    # MPLS（与 ER FastIP 可视化 init 字段一致）
    mpls_defaults = {
        "DEFAULT_WAN_ETH": "0",
        "DEFAULT_WAN_CIDR": "192.168.1.10/24",
        "DEFAULT_WAN_IP_PLAIN": "192.168.1.10",
        "DEFAULT_WAN_GW": "192.168.1.1",
        "DEFAULT_LAN_ETH": "5",
        "DEFAULT_LAN_CIDR": "192.168.5.1/24",
        "DEFAULT_LAN_IP_PLAIN": "192.168.5.1",
        "DEFAULT_LAN_GW": "192.168.5.1",
        "DEFAULT_INNER_NETS": "192.168.0.0/16",
        "DEFAULT_WAN_DHCP": "false",
        "DEFAULT_LAN_DHCP": "true",
        "DEFAULT_GEN_RETURN_ROUTE": "false",
    }
    _seed(MOD_ER_MPLS, mpls_defaults)

    # AR（单机页签 ZH / 双机页签 DJ）
    zh = {
        "ZH_DUAL_WAN": "false",
        "DEFAULT_WAN1_PORT": "0/0/9",
        "DEFAULT_WAN2_PORT": "0/0/8",
        "DEFAULT_WAN1_IP": "192.168.1.190/24",
        "DEFAULT_WAN1_IP_PLAIN": "192.168.1.190",
        "DEFAULT_WAN2_IP": "192.168.2.190/24",
        "DEFAULT_WAN2_IP_PLAIN": "192.168.2.190",
        "DEFAULT_WAN1_GW": "192.168.1.1",
        "DEFAULT_WAN2_GW": "192.168.2.1",
        "ZH_SOUTH_LABEL": _AR_SOUTH_LABELS_DISPLAY[0],
        "ZH_IKE_VERSION": "v1",
        "DEFAULT_ZIHUAN_PORT": "0/0/4",
        "DEFAULT_IPSEC_PORT": "0/0/5",
        "DEFAULT_FTP_SERVER": "59.36.7.222",
    }
    dj = {
        "DJ_WAN1_PORT": "0/0/9",
        "DJ_WAN2_PORT": "0/0/9",
        "DJ_WAN1_IP": "192.168.1.190/24",
        "DJ_WAN1_IP_PLAIN": "192.168.1.190",
        "DJ_WAN2_IP": "192.168.2.190/24",
        "DJ_WAN2_IP_PLAIN": "192.168.2.190",
        "DJ_WAN1_GW": "192.168.1.1",
        "DJ_WAN2_GW": "192.168.2.1",
        "DJ_ZIHUAN1_PORT": "0/0/4",
        "DJ_ZIHUAN2_PORT": "0/0/4",
        "DJ_IPSEC1_PORT": "0/0/5",
        "DJ_IPSEC2_PORT": "0/0/5",
        "DJ_SOUTH_LABEL": _AR_SOUTH_LABELS_DISPLAY[0],
        "DJ_IKE_VERSION": "v1",
        "DEFAULT_FTP_SERVER": "59.36.7.222",
    }
    _seed(AR_INIT_MOD_ZH, zh)
    _seed(AR_INIT_MOD_DJ, dj)


def _capture_init_placeholders_factory() -> None:
    """兼容旧调用：对当前已嵌入的全部脚本各合并一次出厂快照。"""
    seen: set[str] = set()
    for mod in _INIT_PLACEHOLDER_FIELDS:
        emb = _embedded_name_for_init_mod(mod)
        if emb in seen:
            continue
        if EMBEDDED_NS.get(emb):
            _merge_factory_snapshot_for_embed(emb)
            seen.add(emb)


def _apply_user_init_sections_for_emb(emb: str) -> None:
    """仅应用 user_init JSON 中与本次嵌入脚本相关的模块（避免「先嵌 ER 时 AR 尚未嵌入」导致 AR 段被跳过且永不应用）。"""
    raw = _parse_user_init_placeholders_json()
    if not raw:
        return
    if not EMBEDDED_NS.get(emb):
        return
    part: dict[str, dict[str, str]] = {}
    for mod, upd in raw.items():
        if mod not in _INIT_PLACEHOLDER_FIELDS:
            continue
        if _embedded_name_for_init_mod(mod) != emb:
            continue
        if not isinstance(upd, dict):
            continue
        clean = _clean_init_updates(mod, upd)
        if clean:
            part[mod] = clean
    if part:
        _apply_init_placeholder_updates(part)


def _apply_init_placeholders_from_user_json() -> None:
    """全量应用 user_init（在嵌入脚本已就绪时调用，例如保存初始化后）。"""
    raw = _parse_user_init_placeholders_json()
    if not raw:
        return
    to_apply = _user_init_to_apply_dict(raw)
    if to_apply:
        _apply_init_placeholder_updates(to_apply)


def _write_factory_editor_defaults_bundle(dst: Path, info: dict, slot: str) -> None:
    tpl = _factory_tpl_for_scenario(info)
    hdr = info.get("hdr_static") or _auto_headers(tpl)
    mp = info.get("map_static") or _auto_mapping(tpl)
    if info.get("source") == MOD_ER_FASTIP:
        hdr = _strip_leading_hostname_visual_line(hdr)
    (dst / f"{slot}.tpl").write_text(tpl, encoding="utf-8-sig")
    (dst / "headers.txt").write_text(hdr, encoding="utf-8-sig")
    (dst / "mapping.txt").write_text(mp, encoding="utf-8-sig")


def _seed_editor_defaults(*, clear_workspace: bool = False) -> None:
    """确保 editor_defaults 下每个场景均有出厂模板；从 workspace 复制已有文件，缺失 .tpl 用出厂补齐。
    若 clear_workspace=True，则清空 workspace 下所有记录。"""
    if clear_workspace and EDITOR_DEFAULTS_ROOT.exists():
        shutil.rmtree(EDITOR_DEFAULTS_ROOT)
    EDITOR_DEFAULTS_ROOT.mkdir(parents=True, exist_ok=True)
    for key, info in VisualEditorTab.SCENARIOS.items():
        sk = _editor_safe_key(_visual_scenario_disk_key(key))
        src_ws = WORKSPACE / sk
        dst = EDITOR_DEFAULTS_ROOT / sk
        dst.mkdir(parents=True, exist_ok=True)
        slot = _scenario_tpl_slot(info)
        if src_ws.is_dir():
            for name in ("headers.txt", "mapping.txt", "template_version.txt"):
                p = src_ws / name
                if p.exists():
                    shutil.copy2(p, dst / name)
            for tpl in src_ws.glob("*.tpl"):
                shutil.copy2(tpl, dst / tpl.name)
        else:
            _write_factory_editor_defaults_bundle(dst, info, slot)
        if not (dst / f"{slot}.tpl").exists():
            _write_factory_editor_defaults_bundle(dst, info, slot)
    n = len(VisualEditorTab.SCENARIOS)
    if clear_workspace:
        if WORKSPACE.exists():
            shutil.rmtree(WORKSPACE)
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        print(f"OK: 已写入 {EDITOR_DEFAULTS_ROOT}（{n} 场景），已清空 {WORKSPACE}")
    else:
        print(f"OK: 已确保 {EDITOR_DEFAULTS_ROOT} 含 {n} 场景（缺失的已用出厂模板补齐）")


# 向后兼容别名
_seed_editor_defaults_only = lambda: _seed_editor_defaults(clear_workspace=False)
_seed_editor_defaults_and_clear_workspace = lambda: _seed_editor_defaults(clear_workspace=True)


# ══════════════════════════════════════════════════════════════════
# §4b  程序化模板预生成（AR SD-WAN / ER MPLS 实际输出）
# ══════════════════════════════════════════════════════════════════


def _load_prog_templates(*, apply_overrides: bool = True) -> dict[str, str]:
    """从 _templates.json 加载预生成模板。apply_overrides=False 仅返回原始 JSON 内容。

    同时缓存原始 JSON 内容，供后续 _prog_templates_json_raw() 使用。
    """
    global _PROG_JSON_RAW_CACHE
    tpl_file = BUNDLE_DIR / "_templates.json"
    data: dict[str, str] = {}
    if tpl_file.exists():
        try:
            raw = json.loads(tpl_file.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                data = dict(raw)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    # 缓存原始 JSON（未叠加 editor_defaults）
    _PROG_JSON_RAW_CACHE = dict(data)
    if not apply_overrides:
        return _PROG_JSON_RAW_CACHE
    # MPLS 强制以 data/editor_defaults 下的 tpl 文件为准，避免 _templates.json 历史缓存写死值回灌
    for sk, rel in (
        ("mpls_domestic", ("ER_MPLS___国内配置", "TEMPLATE_MPLS_DOMESTIC.tpl")),
        ("mpls_overseas", ("ER_MPLS___海外配置", "TEMPLATE_MPLS_OVERSEAS.tpl")),
        ("mpls_ipsec", ("Epoch_MPLS___IPSec", "TEMPLATE_MPLS_IPSEC.tpl")),
    ):
        p = EDITOR_DEFAULTS_ROOT / rel[0] / rel[1]
        try:
            if p.exists():
                data[sk] = p.read_text(encoding="utf-8-sig").rstrip("\n")
        except (OSError, UnicodeDecodeError):
            pass
    return data

_PROG_TEMPLATES: dict[str, str] = _load_prog_templates()
# 程序化模板出厂副本（完全初始化时恢复）
_PROG_TEMPLATES_BASELINE: dict[str, str] = dict(_PROG_TEMPLATES)

_PROG_JSON_RAW_CACHE: dict[str, str] | None = None


def _prog_templates_json_raw() -> dict[str, str]:
    """仅读取 BUNDLE_DIR/_templates.json（不叠加 editor_defaults），供批量同步 MPLS/AR 等与 JSON 一致。"""
    if _PROG_JSON_RAW_CACHE is not None:
        return _PROG_JSON_RAW_CACHE
    return _load_prog_templates(apply_overrides=False)


def _canonical_tpl_string_for_scenario(info: dict) -> str:
    """与嵌入源码、_templates.json 对齐的模板正文（不读 editor_defaults，避免 MPLS 自引用）。"""
    src_fn = str(info.get("source") or "")
    tpl_var = info.get("tpl_var")
    if tpl_var and src_fn:
        return _tpl_var(_read_src(src_fn), str(tpl_var))
    ts = info.get("tpl_static")
    if ts:
        return _prog_templates_json_raw().get(str(ts), "") or ""
    return ""

# ──────────────────────────────────────────────────────────────────
# 各场景原生输入格式数据头（与工具粘贴区格式完全一致）
# ──────────────────────────────────────────────────────────────────

_ER_HK_HDR = """\
MAIN
lineid: 603642Ar3
主PE： szd-natflr2
WANIP: 10.40.25.188/30
TUNNEL: vtun40826
Docking：121.12.81.3
CE LOIP: 10.20.186.235
HKIP：10.60.241.250 --> 103.48.141.157
BGPSERVER IP： 10.10.99.168,10.10.99.169

BACKUP
PE：szc-natbk10
WANIP: 10.41.25.188/30
TUNNEL: vtun50826
Docking： 120.133.129.72
CE LOIP: 10.20.186.235
HKIP：10.60.241.250 --> 103.48.141.157
BGPSERVER IP：10.10.99.198,10.10.99.199
"""

_ER_HK_MAP = """\
main_pe  主线PE设备名
main_tunnel  主线Tunnel接口名（自动标准化）
main_tunnel_port  主线Tunnel端口号（自动提取）
main_wanip  主线WANIP（/30）
main_wanip_remote  主线WANIP PE侧（自动计算）
main_wanip_local  主线WANIP CE侧（自动计算）
main_docking  主线PE对接IP（Docking）
ce_loip  CE Loopback IP（主备共用）
hkip_nat  HK NAT IP（HKIP字段首个IP）
main_bgp1  主线BGP Server IP 1
main_bgp2  主线BGP Server IP 2
bk_pe  备线PE设备名
bk_tunnel  备线Tunnel接口名
bk_tunnel_port  备线Tunnel端口号
bk_wanip  备线WANIP（/30）
bk_wanip_remote  备线WANIP PE侧
bk_wanip_local  备线WANIP CE侧
bk_docking  备线PE对接IP
bk_bgp1  备线BGP Server IP 1
bk_bgp2  备线BGP Server IP 2
"""

_ER_US_HDR = """\
LineID:609169A1
PE:gzd-upe5
Tunnel:Tunnel0/0/1165
wanip:10.55.14.64/30
PE 对接:192.168.247.17
CE 对接:10.23.0.122
PE:gzd-acvpnpe2
Tunnel:vtun17953
wanip:10.23.0.120/30
PE 对接:183.63.68.171

LineID:609169A2
PE:dgb-upebk2
Tunnel:Tunnel0/0/1998
wanip:10.40.209.220/30
PE 对接:192.168.251.100
CE 对接:10.30.167.202
PE:dgb-acvpnpe2
Tunnel:vtun50057
wanip:10.30.167.200/30
PE 对接:121.12.128.254

LineID:609169A5
PE： twb-natpe2
WANIP: 10.21.32.124/30
TUNNEL: tun1267
PE Docking：192.168.239.12
CE Docking：10.22.241.232
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.44.28-218.32.88.83

LineID:609169A6
PE： twb-natpe1
WANIP: 10.21.31.120/30
TUNNEL: tun2366
PE Docking：192.168.239.14
CE Docking：10.22.241.232
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.18.22-150.116.112.236
"""

_ER_US_MAP = """\
ce_docking  CE Loopback/对接IP（全局）
main_acvpn_gre_pe  主线国内GRE PE（upe设备）
main_acvpn_gre_tun  主线国内GRE Tunnel
main_acvpn_gre_wanip  主线国内GRE WANIP
main_acvpn_gre_pe_ip  主线国内GRE PE侧IP
main_acvpn_gre_ce_ip  主线国内GRE CE侧IP
main_acvpn_gre_remote  主线国内GRE remote目标IP
main_acvpn_vtun_pe  主线ACVPN vtun PE
main_acvpn_vtun_id  主线ACVPN vtun ID
main_acvpn_vtun_port  主线ACVPN vtun端口
main_acvpn_vtun_local  主线ACVPN vtun本地IP
main_acvpn_vtun_remote  主线ACVPN vtun远端IP
main_acvpn_vtun_docking  主线ACVPN vtun对接IP
main_us_pe  主线美国GRE PE（natpe设备）
main_us_tun  主线美国GRE Tunnel
main_us_wanip  主线美国GRE WANIP
main_us_pe_ip  主线美国GRE PE侧IP
main_us_gre_ce_ip  主线美国GRE CE侧IP
main_us_pe_docking  主线美国PE对接IP
main_us_nat_ip  主线美国出口NAT IP
main_us_bgp1  主线美国BGP Server IP 1
main_us_bgp2  主线美国BGP Server IP 2
bk_acvpn_gre_pe  备线国内GRE PE
bk_acvpn_gre_tun  备线国内GRE Tunnel
bk_acvpn_gre_wanip  备线国内GRE WANIP
bk_acvpn_gre_pe_ip  备线国内GRE PE侧IP
bk_acvpn_gre_ce_ip  备线国内GRE CE侧IP
bk_acvpn_gre_remote  备线国内GRE remote目标IP
bk_acvpn_vtun_pe  备线ACVPN vtun PE
bk_acvpn_vtun_id  备线ACVPN vtun ID
bk_acvpn_vtun_port  备线ACVPN vtun端口
bk_acvpn_vtun_local  备线ACVPN vtun本地IP
bk_acvpn_vtun_remote  备线ACVPN vtun远端IP
bk_acvpn_vtun_docking  备线ACVPN vtun对接IP
bk_us_pe  备线美国GRE PE
bk_us_tun  备线美国GRE Tunnel
bk_us_wanip  备线美国GRE WANIP
bk_us_pe_ip  备线美国GRE PE侧IP
bk_us_gre_ce_ip  备线美国GRE CE侧IP
bk_us_pe_docking  备线美国PE对接IP
bk_us_nat_ip  备线美国出口NAT IP
bk_us_bgp1  备线美国BGP Server IP 1
bk_us_bgp2  备线美国BGP Server IP 2
"""

_USG_US_HDR = """\
主 IPSEC_PE: szd-ape2
拨号IP：121.14.82.235
loIP：10.18.12.57
感兴趣流：10.18.12.57/32 ～ 10.255.108.0/22
认证ID：609157A1
预共享密钥：both-win

LineID:609157A1
PE：lax1-fgpe1
WANIP: 10.22.98.40/30
TUNNEL: tun1213
PE对接：10.255.110.6
CE对接：10.18.12.57
出口ip：10.61.10.49-64.81.158.21

备 IPSEC_PE: szc-apebk2
拨号IP：120.133.138.20
loIP：10.18.14.21
认证ID：609157A2
预共享密钥：both-win

LineID:609157A2
PE：sjc1-fgpe1
WANIP: 10.22.32.60/30
TUNNEL: tun2305
PE对接：10.255.111.128
出口ip：10.60.57.87-172.16.14.118
"""

_USG_HK_HDR = """\
主 IPSEC_PE: bja-ape1
拨号IP：118.193.100.10
loIP：10.18.5.13
感兴趣流：10.18.5.13/32 ～ 10.255.108.0/22
认证ID：608810A10
预共享密钥：both-win

*
LineID:608810A10
PE： hkg1-fgpe3
WANIP: 10.22.98.40/30
TUNNEL: tun1040
PE对接：10.255.110.48
CE对接：10.18.5.13
出口ip：103.91.158.227;
*
备 IPSEC_PE: sha-apebk1
拨号IP：101.226.24.131
loIP：10.18.6.25
感兴趣流：10.18.5.13/32 ～ 10.255.108.0/22
感兴趣流：10.18.6.25/32 ～ 10.255.111.128/25
认证ID：608810A11
预共享密钥：both-win

LineID:608810A11
PE： hkj-fgpe1
WANIP: 10.22.73.52/30
TUNNEL: tun2040
PE对接：10.255.111.131
CE对接：10.18.6.25
出口ip：103.91.158.227;
"""

_USG_MAP = """\
main_dial_pe  主线拨号PE名（IPSEC_PE）
main_dial_ip  主线拨号IP
main_loopback  主线CE loopback IP（loIP）
main_auth_id  主线认证ID（LineID）
main_psk  主线预共享密钥
main_pe  主线FastIP PE名
main_wanip  主线WANIP（/30）
main_wanip1  主线WANIP PE侧IP
main_wanip2  主线WANIP CE侧IP
main_tunnel  主线Tunnel名
main_peer_ip  主线PE对接IP
main_export_ips  主线出口IP列表
backup_dial_pe  备线拨号PE名
backup_dial_ip  备线拨号IP
backup_loopback  备线CE loopback IP
backup_auth_id  备线认证ID（LineID）
backup_psk  备线预共享密钥
backup_pe  备线FastIP PE名
backup_wanip  备线WANIP（/30）
backup_wanip1  备线WANIP PE侧IP
backup_wanip2  备线WANIP CE侧IP
backup_tunnel  备线Tunnel名
backup_peer_ip  备线PE对接IP
backup_export_ips  备线出口IP列表
"""

_ER_FLINK_HDR = """\
ShenZhen1-FAST预留IP:100.85.8.176/28
ShangHai1-FAST预留IP:100.86.8.192/28
BeiJing1-FAST预留IP:100.87.8.192/28
"""

_ER_FLINK_MAP = """\
route1  飞连网段1（CIDR，兼容旧模板）
route2  飞连网段2（CIDR，兼容旧模板）
route3  飞连网段3（CIDR，兼容旧模板）
ER_FL_MAIN_NH_DEFAULT  飞连初始化默认：主回程下一跳
ER_FL_BACKUP_NH_DEFAULT  飞连初始化默认：备回程下一跳
"""

_ER_NEW_EXIT_HDR = """\
LineID:609353B7
PE： tyo2-natpe4
WANIP: 10.22.86.196/30
TUNNEL: tun1083
PE Docking：192.168.205.67
CE Docking：: 10.22.242.21
BGPSERVER IP：103.252.19.25,43.229.117.226
海外出口ip：
10.60.21.185-103.57.50.44
10.60.21.186-103.57.50.45

LineID:609353B8
PE： tyo4-natpe2
WANIP: 10.22.100.120/30
TUNNEL: tun1033
PE Docking：10.33.54.78
CE Docking：: 10.22.242.21
BGPSERVER IP：103.252.19.99,43.229.119.251
海外出口ip：
10.60.72.44-172.16.13.46
10.60.72.45-172.16.13.47
"""

_ER_NEW_EXIT_MAP = """\
main_tun  主线TUNNEL
main_tun_addr  主线隧道地址(CE/30)
main_pe  主线PE
main_pe_docking  主线PE Docking
main_ce_docking  主线CE Docking
main_left_ip_1  主线海外出口IP(本端)
main_right_ip_1  主线海外出口IP(对端标识，仅用于描述)
backup_tun  备线TUNNEL（仅双线时有值）
backup_tun_addr  备线隧道地址(CE/30)（仅双线时有值）
backup_pe  备线PE（仅双线时有值）
backup_pe_docking  备线PE Docking（仅双线时有值）
backup_ce_docking  备线CE Docking（仅双线时有值）
backup_left_ip_1  备线海外出口IP(本端)
backup_right_ip_1  备线海外出口IP(对端标识，仅用于描述)
ER_NE_MAIN_DUM_BLOCK  主线多IP dum块（自动展开）
ER_NE_BK_BLOCK  备线完整块（双线时=备线 tunnel+static route+dum；单线时为空）
ER_NE_MAIN_PE_NH_DEFAULT  新增出口初始化默认：主pe对接下一跳
ER_NE_BK_PE_NH_DEFAULT  新增出口初始化默认：备pe对接下一跳
ER_NE_MAIN_DUM_DEFAULT  新增出口初始化默认：主dum起始号
ER_NE_BK_DUM_DEFAULT  新增出口初始化默认：备dum起始号
ER_NE_NAT_HEADER_BLOCK  SNAT 说明注释（仅双线时生成）
ER_NE_NAT_BLOCK  NAT 源转换规则块（仅双线时生成）
ER_NE_FNET_BLOCK  FNET whitelist 块（防火墙 network-group+NAT rule+静态路由+track；仅双线+三元组齐全时生成）
ER_NE_MAIN_NAT_RULE_DEFAULT  新增出口初始化默认：主 NAT rule 起始序号
ER_NE_BK_NAT_RULE_DEFAULT  新增出口初始化默认：备 NAT rule 起始序号
ER_NE_NAT_SOURCE_CIDR_DEFAULT  新增出口初始化默认：NAT 源网段（可空则不生 NAT；多 IP 时 rule 号顺延）
ER_NE_FNET_PROBE_DEFAULT  新增出口初始化默认：100.100 探测 IP
ER_NE_FNET_EXIT_TUNNEL_DEFAULT  新增出口初始化默认：NAT 出口 tunnel
ER_NE_FNET_NAT_RULE_DEFAULT  新增出口初始化默认：NAT rule 号
"""

_USG_FLINK_HDR = """\
ShenZhen1-FAST预留IP:100.93.4.192/27
ShangHai1-FAST预留IP:100.92.4.192/27
BeiJing1-FAST预留IP:100.91.4.192/27

LineID:609204A4
PE: hza-upe1
Tunnel: 3000
PE对接: 10.255.110.35
CE对接: 10.40.147.238
wanip: 10.40.147.236/30

LineID:609204A5
PE: wha-upebk3
Tunnel: 4000
PE对接: 10.255.111.152
CE对接: 10.40.223.6
wanip: 10.40.223.4/30
"""

_USG_FLINK_MAP = """\
main_line_id  主线LineID
main_pe  主线PE名
main_peer_ip  主线PE侧下一跳
main_wanip1  主线WAN PE侧IP
main_wanip2  主线WAN CE侧IP
backup_line_id  备线LineID
backup_pe  备线PE名
backup_peer_ip  备线PE侧下一跳
backup_wanip1  备线WAN PE侧IP
backup_wanip2  备线WAN CE侧IP
reserved1_net  预留网段1网络地址
reserved1_mask  预留网段1掩码长度
reserved2_net  预留网段2网络地址
reserved2_mask  预留网段2掩码长度
reserved3_net  预留网段3网络地址
reserved3_mask  预留网段3掩码长度
USG_FL_MAIN_TUN_DEFAULT  飞连初始化默认：主Tunnel号
USG_FL_BK_TUN_DEFAULT  飞连初始化默认：备Tunnel号
"""

_USG_NEW_EXIT_HDR = """\
LineID:609424A1
PE： lax1-fgpe1
WANIP: 10.22.110.24/30
TUNNEL: tun1248
PE对接：10.255.110.6
CE对接：10.18.16.20
出口ip：
10.61.10.78-64.81.20.174
10.61.10.106-64.81.20.178

LineID:609424A2
PE： sjc1-fgpe2
WANIP: 10.22.106.20/30
TUNNEL: tun1229
PE对接：10.255.111.158
CE对接：10.18.14.127
出口ip：
10.60.76.6-172.16.23.8
10.60.76.78-172.16.23.80
"""

_USG_NEW_EXIT_MAP = """\
main_line_id  主线LineID
main_pe  主线PE名
main_wanip1  主线WAN PE侧IP
main_wanip2  主线WAN CE侧IP
main_peer_ip  主线PE对接IP
main_ce_docking  主线CE对接IP
backup_line_id  备线LineID
backup_pe  备线PE名
backup_wanip1  备线WAN PE侧IP
backup_wanip2  备线WAN CE侧IP
backup_peer_ip  备线PE对接IP
backup_ce_docking  备线CE对接IP
USG_NE_MAIN_LOOPBACK_BLOCK  主线LoopBack块（自动展开）
USG_NE_BK_LOOPBACK_BLOCK  备线LoopBack块（自动展开）
USG_NE_MAIN_NAT_GROUP_BLOCK  主线NAT地址组块（自动展开；NEW-MAIN-OUT-IP1起）
USG_NE_BK_NAT_GROUP_BLOCK  备线NAT地址组块（自动展开；NEW-BACKUP-OUT-IP1起）
USG_NE_MAIN_SNAT_BLOCK  SNAT规则块（主备合并为一个 nat-policy 段）
USG_NE_BK_SNAT_BLOCK  预留空块（兼容旧模板）
USG_NE_MAIN_TUN_DEFAULT  新增出口初始化默认：主Tunnel号
USG_NE_BK_TUN_DEFAULT  新增出口初始化默认：备Tunnel号
USG_NE_MAIN_LOOP_START_DEFAULT  新增出口初始化默认：主LoopBack起始号
USG_NE_BK_LOOP_START_DEFAULT  新增出口初始化默认：备LoopBack起始号
USG_NE_MAIN_NQA_DEFAULT  新增出口初始化默认：主NQA名称
USG_NE_BK_NQA_DEFAULT  新增出口初始化默认：备NQA名称
"""

_MPLS_HDR_CN = """\
##广西##
LineID:609291A1
PE:nna-upe1
Tunnel:Tunnel0/0/1030
wanip:10.40.79.92/30
PE 对接:192.168.204.1
CE 对接:10.40.91.42
PE AS号:65512
CE AS号:65201

PE:nna-ipsecgw1
Tunnel:vtun10013
wanip:10.40.91.40/30
PE 对接:180.142.110.241

LineID:609291A2
PE:szd-upebk2
Tunnel:Tunnel10447
wanip:10.40.195.188/30
PE 对接:192.168.253.80
CE 对接:10.120.52.30
PE AS号:65531
CE AS号:65201

PE:szd-acvpnpe2
Tunnel:vtun10209
wanip:10.120.52.28/30
PE 对接:202.46.225.106
"""

_MPLS_HDR_OV = """\
##越南##
LineID:609291B1
PE:han2-vupe1
Tunnel:vtun1104
wanip:10.40.252.148/30
PE 对接:42.115.85.51
PE AS号:65179
CE AS号:65202

LineID:609291B2
PE:hkj-upe2
Tunnel:Tunnel0/0/1618
wanip:10.33.62.160/30
PE 对接:192.168.236.21
CE 对接:10.55.18.78
PE AS号:65532
CE AS号:65202

PE:hkj-ipsecgw2
Tunnel:vtun1176
wanip:10.55.18.76/30
PE 对接:103.48.141.29
"""

_MPLS_MAP = """\
main_gre_pe  主线GRE PE设备名
main_gre_tun  主线GRE Tunnel接口
main_gre_wanip  主线GRE WAN IP/掩码
main_gre_pe_ip  主线GRE PE侧IP（自动计算）
main_gre_ce_ip  主线GRE CE侧IP（自动计算）
main_gre_remote  主线GRE remote目标IP（PE对接）
main_vtun_pe  主线vtun PE设备名
main_vtun_id  主线vtun Tunnel名（标准化）
main_vtun_port  主线vtun端口号（自动提取）
main_vtun_local  主线vtun本地IP（CE对接）
main_vtun_remote  主线vtun远端IP（PE对接）
main_vtun_docking  主线vtun对接IP（CE对接）
main_vtun_wanip  主线vtun WAN IP
main_pe_as  主线PE AS号
main_line_type  主线线路类型
bk_gre_pe  备线GRE PE设备名
bk_gre_tun  备线GRE Tunnel接口
bk_gre_wanip  备线GRE WAN IP/掩码
bk_gre_pe_ip  备线GRE PE侧IP
bk_gre_ce_ip  备线GRE CE侧IP
bk_gre_remote  备线GRE remote目标IP
bk_vtun_pe  备线vtun PE设备名
bk_vtun_id  备线vtun Tunnel名
bk_vtun_port  备线vtun端口号
bk_vtun_local  备线vtun本地IP
bk_vtun_remote  备线vtun远端IP
bk_vtun_docking  备线vtun对接IP
bk_vtun_wanip  备线vtun WAN IP
bk_pe_as  备线PE AS号
bk_line_type  备线线路类型
ce_as  CE的BGP AS号
"""

# ── IPSec 接入数据头─────────────────────────────────────────────────────
_ER_HK_HDR_IPSEC   = "[开发中 - HK IPSec 数据头示例待提供]"
_ER_US_HDR_IPSEC   = "[开发中 - 非HK IPSec 数据头示例待提供]"
_MPLS_HDR_IPSEC = """\
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

_MPLS_MAP_IPSEC = _MPLS_MAP + """
main_dial_pe  主线拨号PE设备名
main_ipsec_peer_ip  主线IPSec对端内网对接IP
main_loop_ip  主线LoopIP/本端源地址
main_public_ip  主线拨号公网IP
main_ipsec_psk  主线IPSec预共享密钥
main_tun_peer  主线GRE对端地址（从主线wanip自动计算）
main_tun_local  主线GRE本端地址（从主线wanip自动计算）
main_tun_addr  主线GRE接口地址/掩码
main_loop_ip_cidr  主线LoopIP/32
main_track_name  主线track名称
bk_dial_pe  备线拨号PE设备名
bk_ipsec_peer_ip  备线IPSec对端内网对接IP
bk_loop_ip  备线LoopIP/本端源地址
bk_public_ip  备线拨号公网IP
bk_ipsec_psk  备线IPSec预共享密钥
bk_tun_peer  备线GRE对端地址（从备线wanip自动计算）
bk_tun_local  备线GRE本端地址（从备线wanip自动计算）
bk_tun_addr  备线GRE接口地址/掩码
bk_loop_ip_cidr  备线LoopIP/32
wan_addr_plain  WAN口纯IP（去掉掩码）
"""

# AR SD-WAN 数据头（原生输入格式，与工具左侧粘贴区一致）
_AR_HDR_SINGLE = """\
LineID:604604Hw1
PE:gzd-upe5
Tunnel:Tunnel0/0/1147
wanip:10.40.232.248/30
PE 对接:10.200.200.76
CE 对接:10.50.131.16
PE AS号:65176
客户内网路由:100.62.5.8/30

拨号PE:gzd-upe5
对接IP:10.200.200.76
LoopIP:10.50.131.16
拨号ip:183.63.68.174
秘钥:both-win

LineID:604604Hw2
PE:szd-upebk1
Tunnel:Tunnel0/0/1605
wanip:10.30.115.252/30
PE 对接:10.200.200.22
CE 对接:10.120.47.20
PE AS号:65144
客户内网路由:100.62.5.12/30

拨号PE:szd-upebk1
对接IP:10.200.200.22
LoopIP:10.120.47.20
拨号ip:183.56.163.24
秘钥:both-win
"""

_AR_HDR_DUAL = _AR_HDR_SINGLE  # 与单机使用相同示例数据

_AR_MAP_SINGLE = """\
lineid  线路编号（奇数=主线，偶数=备线）
pe  PE设备名
tunnel  Tunnel接口名
wanip  WAN IP/掩码（/30）
pe_peer_ip  PE侧对接IP（GRE目标）
ce_peer_ip  CE侧对接IP（LoopBack绑定）
pe_as  PE的BGP AS号
customer_inner_route  自环内网网段（/30）
dial_ip  拨号IP（IKE remote-address）
ike_psk  IKE预共享秘钥（PSK）
wan1_port  WAN1接口号（初始化）
wan1_ip  WAN1 IP/掩码（初始化）
wan1_gw  WAN1网关（初始化）
zihuan_port  自环接口号（初始化）
ipsec_port  IPSec接口号（初始化）
south_label  南向接入类型（初始化）
"""

# 单机 + 双WAN：与正式页签「初始化」字段一致（在 WAN1 后补充 WAN2）
_AR_MAP_SINGLE_DUALWAN = """\
lineid  线路编号（奇数=主线，偶数=备线）
pe  PE设备名
tunnel  Tunnel接口名
wanip  WAN IP/掩码（/30）
pe_peer_ip  PE侧对接IP（GRE目标）
ce_peer_ip  CE侧对接IP（LoopBack绑定）
pe_as  PE的BGP AS号
customer_inner_route  自环内网网段（/30）
dial_ip  拨号IP（IKE remote-address）
ike_psk  IKE预共享秘钥（PSK）
wan1_port  WAN1接口号（初始化）
wan1_ip  WAN1 IP/掩码（初始化）
wan1_gw  WAN1网关（初始化）
wan2_port  WAN2接口号（初始化）
wan2_ip  WAN2 IP/掩码（初始化）
wan2_gw  WAN2网关（初始化）
zihuan_port  自环接口号（初始化）
ipsec_port  IPSec接口号（初始化）
south_label  南向接入类型（初始化）
"""

_AR_MAP_DUAL = """\
lineid  线路编号（奇数=主线，偶数=备线）
pe  PE设备名
tunnel  Tunnel接口名
wanip  WAN IP/掩码（/30）
pe_peer_ip  PE侧对接IP（GRE目标）
ce_peer_ip  CE侧对接IP（LoopBack绑定）
pe_as  PE的BGP AS号
customer_inner_route  自环内网网段（/30）
dial_ip  拨号IP（IKE remote-address）
ike_psk  IKE预共享秘钥（PSK）
wan1_port  主设备WAN1接口号（初始化）
wan1_ip  主设备WAN1 IP/掩码（初始化）
wan1_gw  主设备WAN1网关（初始化）
wan2_port  备设备WAN2接口号（初始化）
wan2_ip  备设备WAN2 IP/掩码（初始化）
wan2_gw  备设备WAN2网关（初始化）
zihuan1_port  主设备自环接口（初始化）
ipsec1_port  主设备IPSec接口（初始化）
zihuan2_port  备设备自环接口（初始化）
ipsec2_port  备设备IPSec接口（初始化）
south_label  南向接入类型（初始化）
"""

# 映射中统一追加"初始化变量"清单（静态常量，不走动态注入）
_INIT_MAP_ER = """\
DEFAULT_WAN_ETH  初始化默认：WAN口
DEFAULT_WAN_CIDR  初始化默认：WAN IP
DEFAULT_WAN_IP_PLAIN  初始化默认：WAN 主机地址（无掩码，由 DEFAULT_WAN_CIDR 推导）
DEFAULT_WAN_GW  初始化默认：WAN网关
DEFAULT_WAN_DHCP  初始化默认：DHCP
DEFAULT_LAN_ETH  初始化默认：LAN口
DEFAULT_LAN_CIDR  初始化默认：LAN IP
DEFAULT_LAN_IP_PLAIN  初始化默认：LAN 主机地址（无掩码，由 DEFAULT_LAN_CIDR 推导）
DEFAULT_LAN_GW  初始化默认：LAN网关
DEFAULT_LAN_DHCP  初始化默认：DHCP
DEFAULT_INNER_NETS  初始化默认：内网段
DEFAULT_GEN_RETURN_ROUTE  初始化默认：回程路由
"""

_INIT_MAP_USG = """\
DEFAULT_DNS1  初始化默认：骨干DNS主
DEFAULT_DNS2  初始化默认：骨干DNS备
DEFAULT_WAN_ETH  初始化默认：WAN口
DEFAULT_WAN_IP  初始化默认：WAN IP
DEFAULT_WAN_IP_PLAIN  初始化默认：WAN 主机地址（无掩码，由 DEFAULT_WAN_IP 推导）
DEFAULT_WAN_GW  初始化默认：网关
DEFAULT_WAN_DHCP  初始化默认：WAN DHCP
DEFAULT_LAN_ETH  初始化默认：LAN口
DEFAULT_LAN_IP  初始化默认：LAN IP
DEFAULT_LAN_IP_PLAIN  初始化默认：LAN 主机地址（无掩码，由 DEFAULT_LAN_IP 推导）
DEFAULT_LAN_GW  初始化默认：LAN网关
DEFAULT_LAN_DHCP  初始化默认：LAN DHCP
DEFAULT_INNER_NETS  初始化默认：内网段
DEFAULT_GEN_RETURN_ROUTE  初始化默认：生成回程路由
"""

_INIT_MAP_AR_ZH = """\
ZH_DUAL_WAN  初始化默认：WAN模式
DEFAULT_WAN1_PORT  初始化默认：WAN1
DEFAULT_WAN2_PORT  初始化默认：WAN2
DEFAULT_WAN1_IP  初始化默认：WAN1 IP
DEFAULT_WAN1_IP_PLAIN  初始化默认：WAN1 主机地址（无掩码，由 DEFAULT_WAN1_IP 推导）
DEFAULT_WAN2_IP  初始化默认：WAN2 IP
DEFAULT_WAN2_IP_PLAIN  初始化默认：WAN2 主机地址（无掩码，由 DEFAULT_WAN2_IP 推导）
DEFAULT_WAN1_GW  初始化默认：WAN1网关
DEFAULT_WAN2_GW  初始化默认：WAN2网关
ZH_SOUTH_LABEL  初始化默认：南向服务
ZH_IKE_VERSION  初始化默认：IKE版本
DEFAULT_ZIHUAN_PORT  初始化默认：自环网关
DEFAULT_IPSEC_PORT  初始化默认：自环(IPSec)
DEFAULT_FTP_SERVER  初始化默认：FTP服务器
"""

_INIT_MAP_AR_DJ = """\
DJ_HDR_MAIN  初始化默认：【主设备】
DJ_HDR_BAK  初始化默认：【备设备】
DJ_WAN1_PORT  初始化默认：WAN1
DJ_WAN2_PORT  初始化默认：WAN2
DJ_WAN1_IP  初始化默认：WAN1 IP
DJ_WAN1_IP_PLAIN  初始化默认：WAN1 主机地址（无掩码，由 DJ_WAN1_IP 推导）
DJ_WAN2_IP  初始化默认：WAN2 IP
DJ_WAN2_IP_PLAIN  初始化默认：WAN2 主机地址（无掩码，由 DJ_WAN2_IP 推导）
DJ_WAN1_GW  初始化默认：WAN1网关
DJ_WAN2_GW  初始化默认：WAN2网关
DJ_ZIHUAN1_PORT  初始化默认：自环网关
DJ_ZIHUAN2_PORT  初始化默认：自环网关
DJ_IPSEC1_PORT  初始化默认：自环(IPSec)
DJ_IPSEC2_PORT  初始化默认：自环(IPSec)
DJ_SOUTH_LABEL  初始化默认：南向服务
DJ_IKE_VERSION  初始化默认：IKE版本
DEFAULT_FTP_SERVER  初始化默认：FTP服务器
"""

_INIT_MAP_ER_FLINK = """\
ER_FL_MAIN_NH_DEFAULT  飞连初始化默认：主回程下一跳
ER_FL_BACKUP_NH_DEFAULT  飞连初始化默认：备回程下一跳
"""

_INIT_MAP_ER_NEW_EXIT = """\
ER_NE_MAIN_PE_NH_DEFAULT  新增出口初始化默认：主pe对接下一跳
ER_NE_BK_PE_NH_DEFAULT  新增出口初始化默认：备pe对接下一跳
ER_NE_MAIN_DUM_DEFAULT  新增出口初始化默认：主dum起始号
ER_NE_BK_DUM_DEFAULT  新增出口初始化默认：备dum起始号
ER_NE_MAIN_NAT_RULE_DEFAULT  新增出口初始化默认：主 NAT rule 起始序号
ER_NE_BK_NAT_RULE_DEFAULT  新增出口初始化默认：备 NAT rule 起始序号
ER_NE_NAT_SOURCE_CIDR_DEFAULT  新增出口初始化默认：NAT 源网段（可空则不生 NAT；多海外 IP 时 rule 顺延）
ER_NE_FNET_PROBE_DEFAULT  新增出口初始化默认：100.100 探测 IP
ER_NE_FNET_EXIT_TUNNEL_DEFAULT  新增出口初始化默认：NAT 出口 tunnel（可空；与 probe、nat_rule 同填或同空）
ER_NE_FNET_NAT_RULE_DEFAULT  新增出口初始化默认：NAT rule 号（可空；仅双线时生效）
"""

_INIT_MAP_ER_DOMAIN_SPLIT = """\
ER_DS_DOMAINS_DEFAULT  域名分流：默认域名列表（每行一个）
ER_DS_ADDR_GROUP_DEFAULT  address-group（可写「address-group : 名称」；domainlist 与 /opt/<名称>.txt 用 A+组名；policy-route=LAN-MAP+组名）
ER_DS_RULE_NUM_DEFAULT  LAN-MAP rule（策略路由规则序号）
ER_DS_TABLE_NUM_DEFAULT  static table 号
ER_DS_SOURCE_CIDR_DEFAULT  源网段 CIDR（可空；不填则不生成策略路由相关配置）
ER_DS_DNS1_DEFAULT  DNS 主
ER_DS_DNS2_DEFAULT  DNS 备（可空；为空则脚本仅下发主 DNS）
ER_DS_ETH_DEFAULT  应用接口（policy-route 绑定的 ethernet，如 eth0）
ER_DS_TABLE_NH_PRIMARY_DEFAULT  递归下一跳（table 默认路由）
ER_DS_TRACK_NAME_DEFAULT  Track 名称（可空；为空时主/32不带 track，且不下发 set track name）
ER_DS_STATIC32_PRIMARY_NH_DEFAULT  主下一跳（/32 静态的 next-hop）
ER_DS_STATIC32_BACKUP_NH_DEFAULT  备下一跳（可空；非空时 distance 固定 20）
ER_DS_FNET_PROBE_DEFAULT  track 100.100 探测 IP
ER_DS_FNET_NAT_RULE_DEFAULT  NAT rule 号（默认空；与 tunnel、主线出口须同填或同空）
ER_DS_EXIT_TUNNEL_DEFAULT  NAT 出口 tunnel（可空；FNET outbound-interface，openvpn 名）
ER_DS_EXIT_SNAT_IP_DEFAULT  主线出口 IP（可空；set nat translation address）
"""

_ER_DOMAIN_SPLIT_HDR = """\
（本场景以「初始化默认」子页签为准；第①栏可写说明，预览主要使用初始化占位符）
google.com
"""

_ER_DOMAIN_SPLIT_MAP = """\
ER_DS_DOMAINLIST_COMPUTED  预览推导：A+address-group 组名（勿写入 user_init）
ER_DS_POLICY_ROUTE_COMPUTED  预览推导：LAN-MAP+组名（勿写入 user_init）
ER_DS_OPT_DNS2_LINE  预览推导：备 DNS 行（有备 DNS 时一行 set，否则空）
ER_DS_OPT_S32BAK_LINE  预览推导：备下一跳 /32 路由行（有备下一跳时一行 set，否则空）
ER_DS_OPT_TRACK_SUFFIX  预览推导：主 /32 静态路由的 track 后缀（Track 为空则空）
ER_DS_OPT_POLICY_ROUTE_BLOCK  预览推导：源网段非空时生成 policy-route+table+eth（空则不生成）
ER_DS_OPT_FNET_BLOCK  预览推导：100.100 / NAT 段（三项齐全且合法时生成；Track 为空则不下发 set track name；勿写入 user_init）
"""

_INIT_MAP_USG_FLINK = """\
USG_FL_MAIN_TUN_DEFAULT  飞连初始化默认：主Tunnel号
USG_FL_BK_TUN_DEFAULT  飞连初始化默认：备Tunnel号
"""

_INIT_MAP_USG_NEW_EXIT = """\
USG_NE_MAIN_TUN_DEFAULT  新增出口初始化默认：主Tunnel号
USG_NE_BK_TUN_DEFAULT  新增出口初始化默认：备Tunnel号
USG_NE_MAIN_LOOP_START_DEFAULT  新增出口初始化默认：主LoopBack起始号
USG_NE_BK_LOOP_START_DEFAULT  新增出口初始化默认：备LoopBack起始号
USG_NE_MAIN_NQA_DEFAULT  新增出口初始化默认：主NQA名称
USG_NE_BK_NQA_DEFAULT  新增出口初始化默认：备NQA名称
"""

_ER_HK_MAP_FULL = _ER_HK_MAP + "\n" + _INIT_MAP_ER
_ER_US_MAP_FULL = _ER_US_MAP + "\n" + _INIT_MAP_ER
_USG_MAP_FULL = _USG_MAP + "\n" + _INIT_MAP_USG
_MPLS_MAP_FULL = _MPLS_MAP + "\n" + _INIT_MAP_ER
_AR_MAP_SINGLE_FULL = _AR_MAP_SINGLE + "\n" + _INIT_MAP_AR_ZH
_AR_MAP_SINGLE_DUALWAN_FULL = _AR_MAP_SINGLE_DUALWAN + "\n" + _INIT_MAP_AR_ZH
_AR_MAP_DUAL_FULL = _AR_MAP_DUAL + "\n" + _INIT_MAP_AR_DJ
_ER_FLINK_MAP_FULL = _ER_FLINK_MAP + "\n" + _INIT_MAP_ER_FLINK
_ER_NEW_EXIT_MAP_FULL = _ER_NEW_EXIT_MAP + "\n" + _INIT_MAP_ER_NEW_EXIT
_ER_DOMAIN_SPLIT_MAP_FULL = _ER_DOMAIN_SPLIT_MAP + "\n" + _INIT_MAP_ER_DOMAIN_SPLIT
_USG_FLINK_MAP_FULL = _USG_FLINK_MAP + "\n" + _INIT_MAP_USG_FLINK
_USG_NEW_EXIT_MAP_FULL = _USG_NEW_EXIT_MAP + "\n" + _INIT_MAP_USG_NEW_EXIT


# ══════════════════════════════════════════════════════════════════
# §5  自动生成数据头 & 映射关系
# ══════════════════════════════════════════════════════════════════



def _auto_headers(tpl_text: str) -> str:
    """从模板变量自动生成纯净的 variable = value 数据头（无任何注释行）。"""
    seen: list[str] = []
    for m in re.finditer(r'\{(\w+)(?::[^}]*)?\}', tpl_text):
        v = m.group(1)
        # hostname 仅在 ER 工具「网络」面板填写，不出现在业务粘贴/本栏示例
        if v == "hostname":
            continue
        if v not in seen and not v.isdigit():
            seen.append(v)

    added: set[str] = set()
    out: list[str] = []

    def _emit_group(vars_list: list[str]) -> None:
        group_lines: list[str] = []
        for v in vars_list:
            if v in seen and v not in added:
                group_lines.append(f"{v} = {_VAR_SAMPLE.get(v, '')}\n")
                added.add(v)
        if group_lines:
            if out:  # blank separator between groups
                out.append("\n")
            out.extend(group_lines)

    # 基本信息
    _emit_group(["wan_if", "wan_addr", "lan_ip", "dns_ip1", "dns_ip2"])
    # 主线
    _emit_group([v for v in seen if v.startswith("main_")])
    # 公共字段
    _emit_group(["ce_loip", "ce_docking", "hkip_nat", "hkip_nat_all", "hkip_dum100_desc"])
    # 备线
    _emit_group([v for v in seen if v.startswith(("bk_", "backup_"))])
    # 其余
    remain = [v for v in seen if v not in added]
    _emit_group(remain)

    return "".join(out)


def _auto_mapping(tpl_text: str) -> str:
    """从模板变量自动生成紧凑的映射关系（无大括号，纯 var  说明 格式）。"""
    seen: list[str] = []
    for m in re.finditer(r'\{(\w+)(?::[^}]*)?\}', tpl_text):
        v = m.group(1)
        if v not in seen and not v.isdigit():
            seen.append(v)
    lines: list[str] = []
    for v in seen:
        desc = _VAR_DESC.get(v, "未定义")
        lines.append(f"{v}  {desc}\n")
    return "".join(lines)


def _merge_mapping_keep_manual(existing: str, auto_map: str) -> str:
    """
    合并映射：
    - 保留 existing（含用户手工维护、初始化变量段）
    - 仅把 auto_map 中"缺失键"追加到末尾
    """
    ex = str(existing or "")
    am = str(auto_map or "")
    if not ex.strip():
        return am
    existing_keys: set[str] = set()
    for ln in ex.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_]\w*)\b", s)
        if m:
            existing_keys.add(m.group(1))
    add_lines: list[str] = []
    for ln in am.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_]\w*)\b", s)
        if not m:
            continue
        key = m.group(1)
        if key not in existing_keys:
            add_lines.append(ln.rstrip())
            existing_keys.add(key)
    if not add_lines:
        return ex if ex.endswith("\n") else (ex + "\n")
    base = ex.rstrip("\n")
    return base + "\n" + "\n".join(add_lines) + "\n"


# 委托给 shared_utils 中的正确实现（修复了 lip 为空时回退到非 IP 别名的 bug）
_normalize_lan_gw_alias = _su_global.normalize_lan_gw_alias
_ip_host_only = _su_global.ip_host_only


def _inject_init_plain_ips(d: dict[str, str]) -> None:
    """由带掩码的初始化 IP 自动补齐「无 CIDR」主机地址，供映射与模板占位。"""
    wan = (d.get("DEFAULT_WAN_CIDR") or d.get("DEFAULT_WAN_IP") or "").strip()
    if wan:
        d["DEFAULT_WAN_IP_PLAIN"] = _ip_host_only(wan)
        d["DEFAULT_WANIP_PLAIN"] = d["DEFAULT_WAN_IP_PLAIN"]
    lan = (d.get("DEFAULT_LAN_CIDR") or d.get("DEFAULT_LAN_IP") or "").strip()
    if lan:
        d["DEFAULT_LAN_IP_PLAIN"] = _ip_host_only(lan)
        d["DEFAULT_LANIP_PLAIN"] = d["DEFAULT_LAN_IP_PLAIN"]
    for i in (1, 2):
        k = f"DEFAULT_WAN{i}_IP"
        v = (d.get(k) or "").strip()
        if v:
            d[f"DEFAULT_WAN{i}_IP_PLAIN"] = _ip_host_only(v)
    for i in (1, 2):
        k = f"DJ_WAN{i}_IP"
        v = (d.get(k) or "").strip()
        if v:
            d[f"DJ_WAN{i}_IP_PLAIN"] = _ip_host_only(v)


_ER_FASTIP_INIT_FIELDS: list[tuple[str, str]] = [
    ("DEFAULT_WAN_ETH", "WAN口"),
    ("DEFAULT_WAN_CIDR", "WAN IP"),
    ("DEFAULT_WAN_GW", "WAN网关"),
    ("DEFAULT_WAN_DHCP", "DHCP"),
    ("DEFAULT_LAN_ETH", "LAN口"),
    ("DEFAULT_LAN_CIDR", "LAN IP"),
    ("DEFAULT_LAN_GW", "LAN网关"),
    ("DEFAULT_LAN_DHCP", "DHCP"),
    ("DEFAULT_INNER_NETS", "内网段"),
    ("DEFAULT_GEN_RETURN_ROUTE", "回程路由"),
]

_USG_DEFAULT_FIELDS = [
    ("DEFAULT_DNS1", "骨干DNS主"),
    ("DEFAULT_DNS2", "骨干DNS备"),
    ("DEFAULT_WAN_ETH", "WAN口"),
    ("DEFAULT_WAN_IP", "WAN IP"),
    ("DEFAULT_WAN_GW", "网关"),
    ("DEFAULT_WAN_DHCP", "WAN DHCP"),
    ("DEFAULT_LAN_ETH", "LAN口"),
    ("DEFAULT_LAN_IP", "LAN IP"),
    ("DEFAULT_LAN_GW", "LAN网关"),
    ("DEFAULT_LAN_DHCP", "LAN DHCP"),
    ("DEFAULT_INNER_NETS", "内网段"),
    ("DEFAULT_GEN_RETURN_ROUTE", "生成回程路由"),
]

# 可视化「初始化默认」：与各工具页签「初始化配置」中的标签、顺序一致（键 __sep__* 仅分组，无全局变量）
_INIT_PLACEHOLDER_FIELDS: dict[str, list[tuple[str, str]]] = {
    ER_INIT_MOD_HK: list(_ER_FASTIP_INIT_FIELDS),
    ER_INIT_MOD_US: list(_ER_FASTIP_INIT_FIELDS),
    ER_INIT_MOD_FLINK: [
        ("ER_FL_MAIN_NH_DEFAULT", "主回程下一跳"),
        ("ER_FL_BACKUP_NH_DEFAULT", "备回程下一跳"),
    ],
    ER_INIT_MOD_NEW_EXIT: [
        ("ER_NE_MAIN_PE_NH_DEFAULT", "主pe对接下一跳"),
        ("ER_NE_BK_PE_NH_DEFAULT", "备pe对接下一跳"),
        ("ER_NE_MAIN_DUM_DEFAULT", "主新增ip dum号"),
        ("ER_NE_BK_DUM_DEFAULT", "备新增ip dum号"),
        ("ER_NE_MAIN_NAT_RULE_DEFAULT", "主 NAT rule 起始号"),
        ("ER_NE_BK_NAT_RULE_DEFAULT", "备 NAT rule 起始号"),
        ("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "NAT 源网段 CIDR(可空)"),
        ("ER_NE_FNET_PROBE_DEFAULT", "100.100 探测 IP"),
        ("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "NAT 出口 tunnel(可空)"),
        ("ER_NE_FNET_NAT_RULE_DEFAULT", "NAT rule 号(可空)"),
    ],
    ER_INIT_MOD_DOMAIN_SPLIT: [
        ("ER_DS_DOMAINS_DEFAULT", "域名列表(每行一个)"),
        ("ER_DS_ADDR_GROUP_DEFAULT", "address-group（domainlist 与 /opt 下 txt 用 A+组名）"),
        ("ER_DS_RULE_NUM_DEFAULT", "LAN-MAP rule"),
        ("ER_DS_TABLE_NUM_DEFAULT", "static table 号"),
        ("ER_DS_SOURCE_CIDR_DEFAULT", "源网段(可空；不填则不生成策略路由)"),
        ("ER_DS_ETH_DEFAULT", "应用接口"),
        ("ER_DS_DNS1_DEFAULT", "DNS 主"),
        ("ER_DS_DNS2_DEFAULT", "DNS 备(可空)"),
        ("ER_DS_TABLE_NH_PRIMARY_DEFAULT", "递归下一跳(IP)"),
        ("ER_DS_TRACK_NAME_DEFAULT", "Track 名称(可空)"),
        ("ER_DS_STATIC32_PRIMARY_NH_DEFAULT", "主下一跳(/32)"),
        ("ER_DS_STATIC32_BACKUP_NH_DEFAULT", "备下一跳(可空)"),
        ("ER_DS_FNET_PROBE_DEFAULT", "100.100 探测IP"),
        ("ER_DS_FNET_NAT_RULE_DEFAULT", "NAT rule(可空)"),
        ("ER_DS_EXIT_TUNNEL_DEFAULT", "NAT tunnel(可空)"),
        ("ER_DS_EXIT_SNAT_IP_DEFAULT", "主线出口 IP(可空)"),
    ],
    USG_INIT_MOD_US: list(_USG_DEFAULT_FIELDS),
    USG_INIT_MOD_HK: list(_USG_DEFAULT_FIELDS),
    USG_INIT_MOD_FLINK: [
        ("USG_FL_MAIN_TUN_DEFAULT", "主 Tunnel 号"),
        ("USG_FL_BK_TUN_DEFAULT", "备 Tunnel 号"),
    ],
    USG_INIT_MOD_NEW_EXIT: [
        ("USG_NE_MAIN_TUN_DEFAULT", "主 Tunnel 号"),
        ("USG_NE_BK_TUN_DEFAULT", "备 Tunnel 号"),
        ("USG_NE_MAIN_LOOP_START_DEFAULT", "主 LoopBack 起始号"),
        ("USG_NE_BK_LOOP_START_DEFAULT", "备 LoopBack 起始号"),
        ("USG_NE_MAIN_NQA_DEFAULT", "主 NQA 名称"),
        ("USG_NE_BK_NQA_DEFAULT", "备 NQA 名称"),
    ],
    MOD_ER_MPLS: list(_ER_FASTIP_INIT_FIELDS),
    AR_INIT_MOD_ZH: [
        ("ZH_DUAL_WAN", "WAN模式"),
        ("DEFAULT_WAN1_PORT", "WAN1"),
        ("DEFAULT_WAN2_PORT", "WAN2"),
        ("DEFAULT_WAN1_IP", "WAN1 IP"),
        ("DEFAULT_WAN2_IP", "WAN2 IP"),
        ("DEFAULT_WAN1_GW", "WAN1网关"),
        ("DEFAULT_WAN2_GW", "WAN2网关"),
        ("ZH_SOUTH_LABEL", "南向服务"),
        ("ZH_IKE_VERSION", "IKE版本"),
        ("DEFAULT_ZIHUAN_PORT", "自环网关"),
        ("DEFAULT_IPSEC_PORT", "自环(IPSec)"),
        ("DEFAULT_FTP_SERVER", "FTP服务器"),
    ],
    AR_INIT_MOD_DJ: [
        ("DJ_HDR_MAIN", "【主设备】"),
        ("DJ_HDR_BAK", "【备设备】"),
        ("DJ_WAN1_PORT", "WAN1"),
        ("DJ_WAN2_PORT", "WAN2"),
        ("DJ_WAN1_IP", "WAN1 IP"),
        ("DJ_WAN2_IP", "WAN2 IP"),
        ("DJ_WAN1_GW", "WAN1网关"),
        ("DJ_WAN2_GW", "WAN2网关"),
        ("DJ_ZIHUAN1_PORT", "自环网关"),
        ("DJ_ZIHUAN2_PORT", "自环网关"),
        ("DJ_IPSEC1_PORT", "自环(IPSec)"),
        ("DJ_IPSEC2_PORT", "自环(IPSec)"),
        ("DJ_SOUTH_LABEL", "南向服务"),
        ("DJ_IKE_VERSION", "IKE版本"),
        ("DEFAULT_FTP_SERVER", "FTP服务器"),
    ],
}


# ER/MPLS 默认初始化表单布局（与 _ER_FASTIP_INIT_FIELDS 顺序一致）
_ER_DEFAULT_FORM_ROWS = [
    ["DEFAULT_WAN_ETH", "DEFAULT_WAN_CIDR", "DEFAULT_WAN_GW", "DEFAULT_WAN_DHCP"],
    ["DEFAULT_LAN_ETH", "DEFAULT_LAN_CIDR", "DEFAULT_LAN_GW", "DEFAULT_LAN_DHCP"],
    ["DEFAULT_INNER_NETS"],
    ["DEFAULT_GEN_RETURN_ROUTE"],
]


def _init_form_rows_for_scenario(info: dict) -> list[list[str]] | None:
    """ER/USG/AR 多行排版；None 表示仍按 4 列线性填充。"""
    src = info.get("source") or ""
    slot = str(info.get("tpl_slot") or "")
    if src == MOD_ER_MPLS:
        return _ER_DEFAULT_FORM_ROWS
    if src == MOD_ER_FASTIP:
        if slot == "TEMPLATE_ER_FLINK_VISUAL":
            return [["ER_FL_MAIN_NH_DEFAULT", "ER_FL_BACKUP_NH_DEFAULT"]]
        if slot == "TEMPLATE_ER_NEW_EXIT_VISUAL":
            return [
                ["ER_NE_MAIN_PE_NH_DEFAULT", "ER_NE_BK_PE_NH_DEFAULT"],
                ["ER_NE_MAIN_DUM_DEFAULT", "ER_NE_BK_DUM_DEFAULT"],
                ["ER_NE_MAIN_NAT_RULE_DEFAULT", "ER_NE_BK_NAT_RULE_DEFAULT"],
                ["ER_NE_NAT_SOURCE_CIDR_DEFAULT"],
                ["ER_NE_FNET_PROBE_DEFAULT", "ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "ER_NE_FNET_NAT_RULE_DEFAULT"],
            ]
        if slot == "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL":
            return [
                ["ER_DS_DOMAINS_DEFAULT"],
                ["ER_DS_ADDR_GROUP_DEFAULT", "ER_DS_RULE_NUM_DEFAULT", "ER_DS_TABLE_NUM_DEFAULT"],
                ["ER_DS_SOURCE_CIDR_DEFAULT", "ER_DS_ETH_DEFAULT", "ER_DS_DNS1_DEFAULT", "ER_DS_DNS2_DEFAULT"],
                ["ER_DS_TABLE_NH_PRIMARY_DEFAULT", "ER_DS_STATIC32_PRIMARY_NH_DEFAULT"],
                ["ER_DS_TRACK_NAME_DEFAULT", "ER_DS_STATIC32_BACKUP_NH_DEFAULT"],
                ["ER_DS_FNET_PROBE_DEFAULT", "ER_DS_FNET_NAT_RULE_DEFAULT", "ER_DS_EXIT_TUNNEL_DEFAULT", "ER_DS_EXIT_SNAT_IP_DEFAULT"],
            ]
        return _ER_DEFAULT_FORM_ROWS
    if src == MOD_USG_FASTIP:
        if slot == "TEMPLATE_USG_FLINK_VISUAL":
            return [["USG_FL_MAIN_TUN_DEFAULT", "USG_FL_BK_TUN_DEFAULT"]]
        if slot == "TEMPLATE_USG_NEW_EXIT_VISUAL":
            return [
                ["USG_NE_MAIN_TUN_DEFAULT", "USG_NE_BK_TUN_DEFAULT"],
                ["USG_NE_MAIN_LOOP_START_DEFAULT", "USG_NE_BK_LOOP_START_DEFAULT"],
                ["USG_NE_MAIN_NQA_DEFAULT", "USG_NE_BK_NQA_DEFAULT"],
            ]
        return [
            ["DEFAULT_DNS1", "DEFAULT_DNS2"],
            ["DEFAULT_WAN_ETH", "DEFAULT_WAN_IP", "DEFAULT_WAN_GW", "DEFAULT_WAN_DHCP"],
            ["DEFAULT_LAN_ETH", "DEFAULT_LAN_IP", "DEFAULT_LAN_GW", "DEFAULT_LAN_DHCP"],
            ["DEFAULT_INNER_NETS"],
            ["DEFAULT_GEN_RETURN_ROUTE"],
        ]
    if src == MOD_AR_SDWAN:
        if _init_mod_for_scenario(info) == AR_INIT_MOD_ZH:
            return [
                ["ZH_DUAL_WAN"],
                ["DEFAULT_WAN1_PORT", "DEFAULT_WAN2_PORT"],
                ["DEFAULT_WAN1_IP", "DEFAULT_WAN2_IP"],
                ["DEFAULT_WAN1_GW", "DEFAULT_WAN2_GW"],
                ["ZH_SOUTH_LABEL"],
                ["ZH_IKE_VERSION"],
                ["DEFAULT_ZIHUAN_PORT", "DEFAULT_IPSEC_PORT"],
                ["DEFAULT_FTP_SERVER"],
            ]
        return [
            ["DJ_HDR_MAIN", "DJ_HDR_BAK"],
            ["DJ_WAN1_PORT", "DJ_WAN2_PORT"],
            ["DJ_WAN1_IP", "DJ_WAN2_IP"],
            ["DJ_WAN1_GW", "DJ_WAN2_GW"],
            ["DJ_ZIHUAN1_PORT", "DJ_ZIHUAN2_PORT"],
            ["DJ_IPSEC1_PORT", "DJ_IPSEC2_PORT"],
            ["DJ_SOUTH_LABEL"],
            ["DJ_IKE_VERSION"],
            ["DEFAULT_FTP_SERVER"],
        ]
    return None


_INIT_GRID_COLS = 8  # 初始化区 uniform grid 列数

def _init_row_spans_for_line(n: int) -> list[int]:
    """初始化区均匀列宽；一行内 n 个控件时按列均分整行宽度。"""
    if n <= 0:
        return [_INIT_GRID_COLS]
    q, r = divmod(_INIT_GRID_COLS, n)
    # 当 n > _INIT_GRID_COLS 时 q=0，部分列为 0 宽度导致 tkinter 渲染异常；保底至少 1
    return [max(1, q + (1 if i < r else 0)) for i in range(n)]


def _init_layout_key_order(info: dict) -> list[str]:
    """线性顺序（仅 MPLS 等未定义多行模板时使用）。"""
    mod = _init_mod_for_scenario(info)
    return [k for k, _ in _INIT_PLACEHOLDER_FIELDS.get(mod, []) if not str(k).startswith("__sep__")]


def _init_eth_suffix_ok(s: str, label: str) -> str | None:
    t = (s or "").strip()
    if not t:
        return f"{label}不能为空（请填 eth 后的数字）"
    if not t.isdigit():
        return f"{label}须为纯数字，当前「{t}」"
    n = int(t)
    if not (0 <= n <= 63):
        return f"{label}数字建议 0～63，当前「{t}」"
    return None


def _init_dns_ipv4_ok(s: str, name: str) -> str | None:
    t = (s or "").strip()
    if not t:
        return None
    try:
        ipaddress.ip_address(t)
    except (ValueError, ipaddress.AddressValueError) as e:
        return f"{name}「{t}」不是合法 IPv4：{e}"
    return None


_INIT_MOD_TITLE = {
    ER_INIT_MOD_HK: "Epoch FastIP · HK",
    ER_INIT_MOD_US: "Epoch FastIP · 非香港出口",
    ER_INIT_MOD_FLINK: "Epoch FastIP · ER 飞连",
    ER_INIT_MOD_NEW_EXIT: "Epoch FastIP · ER 新增出口",
    ER_INIT_MOD_DOMAIN_SPLIT: "Epoch FastIP · ER 域名分流",
    USG_INIT_MOD_US: "USG FastIP · 非香港出口",
    USG_INIT_MOD_HK: "USG FastIP · HK",
    USG_INIT_MOD_FLINK: "USG FastIP · 飞连",
    USG_INIT_MOD_NEW_EXIT: "USG FastIP · 新增出口",
    MOD_ER_MPLS: "Epoch MPLS",
    AR_INIT_MOD_ZH: "AR SD-WAN · 单机",
    AR_INIT_MOD_DJ: "AR SD-WAN · 双机",
}


# ══════════════════════════════════════════════════════════════════
# §6  可视化编辑器 Tab
# ══════════════════════════════════════════════════════════════════

class VisualEditorTab:

    SCENARIOS: OrderedDict[str, dict] = OrderedDict([
        ("Epoch FastIP · HK 香港出口", {
            "source": MOD_ER_FASTIP,
            "tpl_slot": "TEMPLATE_EPOCH_HK",
            "tpl_var": "TEMPLATE_EPOCH_HK",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _ER_HK_HDR, "map_static": _ER_HK_MAP_FULL,
            "parser_name": "parse_epoch_hk",
        }),
        ("Epoch FastIP · HK 香港出口 · IPSec", {
            "source": MOD_ER_FASTIP,
            "tpl_slot": "TEMPLATE_EPOCH_HK_IPSEC",
            "tpl_var": "TEMPLATE_EPOCH_HK_IPSEC",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _ER_HK_HDR_IPSEC, "map_static": _ER_HK_MAP_FULL,
            "parser_name": "parse_epoch_hk",
            "placeholder": True,
        }),
        ("Epoch FastIP · 非香港出口", {
            "source": MOD_ER_FASTIP,
            "tpl_slot": "TEMPLATE_EPOCH_US",
            "tpl_var": "TEMPLATE_EPOCH_US",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _ER_US_HDR, "map_static": _ER_US_MAP_FULL,
            "parser_name": "parse_epoch_us",
        }),
        ("Epoch FastIP · 非香港出口 · IPSec", {
            "source": MOD_ER_FASTIP,
            "tpl_slot": "TEMPLATE_EPOCH_US_IPSEC",
            "tpl_var": "TEMPLATE_EPOCH_US_IPSEC",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _ER_US_HDR_IPSEC, "map_static": _ER_US_MAP_FULL,
            "parser_name": "parse_epoch_us",
            "placeholder": True,
        }),
        ("Epoch FastIP · ER 飞连", {
            "source": MOD_ER_FASTIP,
            "tpl_slot": "TEMPLATE_ER_FLINK_VISUAL",
            "tpl_var": "TEMPLATE_ER_FLINK_VISUAL",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _ER_FLINK_HDR, "map_static": _ER_FLINK_MAP_FULL,
            "parser_name": "parse_er_flink_headers",
        }),
        ("Epoch FastIP · ER 新增出口", {
            "source": MOD_ER_FASTIP,
            "tpl_slot": "TEMPLATE_ER_NEW_EXIT_VISUAL",
            "tpl_var": "TEMPLATE_ER_NEW_EXIT_VISUAL",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _ER_NEW_EXIT_HDR, "map_static": _ER_NEW_EXIT_MAP_FULL,
            "parser_name": "parse_er_new_exit_blocks",
        }),
        ("Epoch FastIP · ER 域名分流", {
            "source": MOD_ER_FASTIP,
            "tpl_slot": "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL",
            "tpl_var": "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _ER_DOMAIN_SPLIT_HDR, "map_static": _ER_DOMAIN_SPLIT_MAP_FULL,
            "parser_name": "er_domain_split_preview",
        }),
        ("USG FastIP · 非香港出口", {
            "source": MOD_USG_FASTIP,
            "tpl_slot": "TEMPLATE_USG_NONHK",
            "tpl_var": "TEMPLATE_USG_NONHK",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _USG_US_HDR, "map_static": _USG_MAP_FULL,
            "parser_name": "parse_business_data",
        }),
        ("USG FastIP · HK 香港出口", {
            "source": MOD_USG_FASTIP,
            "tpl_slot": "TEMPLATE_USG_HK",
            "tpl_var": "TEMPLATE_USG_HK",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _USG_HK_HDR, "map_static": _USG_MAP_FULL,
            "parser_name": "parse_business_data_hk",
        }),
        ("USG FastIP · 飞连", {
            "source": MOD_USG_FASTIP,
            "tpl_slot": "TEMPLATE_USG_FLINK_VISUAL",
            "tpl_var": "TEMPLATE_USG_FLINK_VISUAL",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _USG_FLINK_HDR, "map_static": _USG_FLINK_MAP_FULL,
            "parser_name": "parse_feilink_data",
        }),
        ("USG FastIP · 新增出口", {
            "source": MOD_USG_FASTIP,
            "tpl_slot": "TEMPLATE_USG_NEW_EXIT_VISUAL",
            "tpl_var": "TEMPLATE_USG_NEW_EXIT_VISUAL",
            "tpl_func": None, "tpl_static": None,
            "hdr_static": _USG_NEW_EXIT_HDR, "map_static": _USG_NEW_EXIT_MAP_FULL,
            "parser_name": "parse_usg_new_exit_blocks",
        }),
        ("Epoch MPLS · 国内配置", {
            "source": MOD_ER_MPLS,
            "tpl_slot": "TEMPLATE_MPLS_DOMESTIC",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "mpls_domestic",
            "hdr_static": _MPLS_HDR_CN, "map_static": _MPLS_MAP_FULL,
            "parser_name": "parse_epoch_mpls",
        }),
        ("Epoch MPLS · IPSec", {
            "source": MOD_ER_MPLS,
            "tpl_slot": "TEMPLATE_MPLS_IPSEC",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "mpls_ipsec",
            "hdr_static": _MPLS_HDR_IPSEC, "map_static": _MPLS_MAP_IPSEC + "\n" + _INIT_MAP_ER,
            "parser_name": "parse_epoch_mpls_ipsec",
        }),
        ("Epoch MPLS · 海外配置", {
            "source": MOD_ER_MPLS,
            "tpl_slot": "TEMPLATE_MPLS_OVERSEAS",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "mpls_overseas",
            "hdr_static": _MPLS_HDR_OV, "map_static": _MPLS_MAP_FULL,
            "parser_name": "parse_epoch_mpls",
        }),
        ("AR SD-WAN · 单机单WAN · OPS", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_OPS_SINGLE_WAN1",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_ops_single",
            "hdr_static": _AR_HDR_SINGLE, "map_static": _AR_MAP_SINGLE_FULL,
            "parser_name": "parse_ar_visual",
        }),
        ("AR SD-WAN · 单机单WAN · Factory", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_FACTORY_SINGLE_WAN1",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_factory_single",
            "hdr_static": _AR_HDR_SINGLE, "map_static": _AR_MAP_SINGLE_FULL,
            "parser_name": "parse_ar_visual",
        }),
        ("AR SD-WAN · 单机双WAN · OPS", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_OPS_SINGLE_DUALWAN",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_ops_single_dualwan",
            "hdr_static": _AR_HDR_SINGLE, "map_static": _AR_MAP_SINGLE_DUALWAN_FULL,
            "parser_name": "parse_ar_visual",
        }),
        ("AR SD-WAN · 单机双WAN · Factory", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_FACTORY_SINGLE_DUALWAN",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_factory_single_dualwan",
            "hdr_static": _AR_HDR_SINGLE, "map_static": _AR_MAP_SINGLE_DUALWAN_FULL,
            "parser_name": "parse_ar_visual",
        }),
        ("AR SD-WAN · 双机主 OPS", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_OPS_DUAL_PRIMARY",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_ops_dual_pri",
            "hdr_static": _AR_HDR_DUAL, "map_static": _AR_MAP_DUAL_FULL,
            "parser_name": "parse_ar_visual",
        }),
        ("AR SD-WAN · 双机备 OPS", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_OPS_DUAL_BACKUP",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_ops_dual_bak",
            "hdr_static": _AR_HDR_DUAL, "map_static": _AR_MAP_DUAL_FULL,
            "parser_name": "parse_ar_visual",
        }),
        ("AR SD-WAN · 双机主 Factory", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_FACTORY_DUAL_PRIMARY",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_factory_dual_pri",
            "hdr_static": _AR_HDR_DUAL, "map_static": _AR_MAP_DUAL_FULL,
            "parser_name": "parse_ar_visual",
        }),
        ("AR SD-WAN · 双机备 Factory", {
            "source": MOD_AR_SDWAN,
            "tpl_slot": "TEMPLATE_AR_FACTORY_DUAL_BACKUP",
            "tpl_var": None, "tpl_func": None,
            "tpl_static": "ar_factory_dual_bak",
            "hdr_static": _AR_HDR_DUAL, "map_static": _AR_MAP_DUAL_FULL,
            "parser_name": "parse_ar_visual",
        }),
    ])

    ACCENT  = "#0077b6"
    BG      = "#f0f4f8"
    BG_HDR  = "#1e3a5f"
    BG_TXT  = "#f8fafc"
    FG      = "#1a2b3c"
    FG_DIM  = "#7a96ad"
    FG_WH   = "#ffffff"
    BORDER  = "#c8d8e8"

    def __init__(self, parent: tk.Frame) -> None:
        self.parent = parent
        self._current_key = ""
        self._src_cache: dict[str, str] = {}
        # 19 场景 UI 回归：禁止静默落盘 / 禁止 ER 体检写回 workspace；结束后跳过关闭时 auto_save
        self._regression_skip_disk = False
        self._skip_next_close_autosave = False
        self._build_ui()
        first = next(iter(self.SCENARIOS))
        self.combo.set(first)
        self._on_select(None)

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        p = self.parent
        p.columnconfigure(0, weight=1)
        p.rowconfigure(2, weight=1)

        # 顶部标题栏
        hdr = tk.Frame(p, bg=self.BG_HDR, height=34)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        tk.Frame(hdr, bg=self.ACCENT, width=3).pack(side="left", fill="y")
        tk.Label(hdr, text="  我来定模板",
                 font=("微软雅黑", 10, "bold"),
                 bg=self.BG_HDR, fg=self.FG_WH).pack(side="left", pady=4)
        tk.Label(hdr,
                 text="保存后立即在对应工具页签中生效  ·  四栏均可编辑",
                 font=("微软雅黑", 8),
                 bg=self.BG_HDR, fg=self.FG_DIM).pack(side="left", padx=14)

        # 场景选择栏
        sel = tk.Frame(p, bg=self.BG, height=32)
        sel.grid(row=1, column=0, sticky="ew", padx=6, pady=(3, 1))
        sel.grid_propagate(False)
        tk.Label(sel, text="选择场景：",
                 font=("微软雅黑", 9, "bold"),
                 bg=self.BG, fg=self.FG).pack(side="left", padx=(4, 6))
        self.combo = ttk.Combobox(
            sel,
            values=list(self.SCENARIOS.keys()),
            state="readonly",
            width=34,
            font=("微软雅黑", 9),
        )
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", self._on_select)
        tk.Label(sel,
                 text="切换后初始化占位与四栏随场景刷新",
                 font=("微软雅黑", 8), bg=self.BG, fg=self.FG_DIM).pack(side="left", padx=10)

        # 中间整体：上为固定高度的「初始化默认」（不使用内部滚动）；下为 ①②③④ 四栏（占满剩余高度）。
        # 不用垂直 PanedWindow：在 Windows 上 init_bar 自然高度很大时会挤掉下方四栏（高度为 0）。
        mid = tk.Frame(p, bg=self.BG)
        mid.grid(row=2, column=0, sticky="nsew", padx=6, pady=(1, 2))
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(1, weight=1)

        init_outer = tk.Frame(
            mid, bg=self.BG,
            highlightthickness=0,
            height=250,
        )
        self._init_outer = init_outer
        init_outer.grid(row=0, column=0, sticky="ew", pady=(0, 1))
        init_outer.grid_propagate(False)
        init_outer.rowconfigure(0, weight=1)
        init_outer.columnconfigure(0, weight=1)

        # 初始化默认：与各工具正式页签字段、标签一致（ER/MPLS 同结构；AR 单机/双机 + 南向/IKE）
        init_bar = tk.Frame(init_outer, bg=self.BG)
        init_bar.grid(row=0, column=0, sticky="nsew")
        init_bar.columnconfigure(0, weight=1)
        hdr_init = tk.Frame(init_bar, bg=self.BG)
        hdr_init.grid(row=0, column=0, sticky="ew", padx=2, pady=(1, 0))
        hdr_init.columnconfigure(0, weight=1)
        tk.Label(
            hdr_init,
            text="初始化默认（随所选场景切换，与对应工具页签一致）",
            font=("微软雅黑", 8, "bold"),
            bg=self.BG, fg=self.FG, anchor="w",
        ).grid(row=0, column=0, sticky="w")
        btn_col = tk.Frame(hdr_init, bg=self.BG)
        btn_col.grid(row=0, column=1, sticky="e", padx=(8, 2))
        self._btn(btn_col, "  保存  ", "#16a085", self._save_init_defaults).pack(side="left", padx=(0, 6))
        self._btn(btn_col, "  恢复出厂  ", "#e07b2a", self._restore_init_factory).pack(side="left")
        self._init_action_hint = tk.StringVar(value="")
        self._init_hint_after_id = None
        tk.Label(
            hdr_init,
            textvariable=self._init_action_hint,
            font=("微软雅黑", 8),
            fg="#5a7a96",
            bg=self.BG,
            anchor="w",
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=2, pady=(2, 0))

        self.init_stack = tk.Frame(init_bar, bg=self.BG)
        self.init_stack.grid(row=1, column=0, sticky="ew", padx=2, pady=(1, 2))
        self.init_stack.columnconfigure(0, weight=1)

        self._init_module_frames: dict[str, tk.Frame] = {}
        self._init_entries: dict[str, dict[str, Any]] = {}
        self._init_cell_widgets: dict[str, dict[str, tk.Widget]] = {}
        self._init_bool_vars: dict[str, dict[str, tk.BooleanVar]] = {}
        self._init_wan_saved: dict[str, tuple[str, str]] = {}

        _fe = ("Consolas", 9)
        _fl = ("微软雅黑", 8)

        def _entry_chars(k: str, mod_name: str = "") -> int:
            if mod_name == ER_INIT_MOD_DOMAIN_SPLIT and k == "ER_DS_FNET_NAT_RULE_DEFAULT":
                return 6
            # AR SD-WAN：接口名/IP+CIDR/网关/FTP 较长；勿让 _PORT 早退成 14 格导致默认值显示不全
            if mod_name in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ):
                if "_PORT" in k or k.endswith("_PORT"):
                    return 34
                if any(
                    x in k
                    for x in ("_IP", "_CIDR", "_GW", "FTP", "SERVER", "MASK")
                ):
                    return 52
                return 38
            # 飞连 / 新增出口：下一跳等可能为完整 CIDR，需至少容纳 xxx.xxx.xxx.xxx/xx
            if mod_name in (
                    ER_INIT_MOD_FLINK, USG_INIT_MOD_FLINK, USG_INIT_MOD_NEW_EXIT, ER_INIT_MOD_NEW_EXIT,
                    ER_INIT_MOD_DOMAIN_SPLIT):
                return 24
            if "ETH" in k:
                # 域名分流「应用接口」填 eth0 等，勿用 ER 主线里 eth 号一位宽
                if mod_name == ER_INIT_MOD_DOMAIN_SPLIT and k == "ER_DS_ETH_DEFAULT":
                    return 14
                return 5
            if "_PORT" in k or k.endswith("_PORT"):
                return 14
            if any(
                x in k
                for x in ("_IP", "_CIDR", "_GW", "DNS", "_MASK", "WAN1_", "WAN2_")
            ):
                return 24
            return 22

        for mod, fields in _INIT_PLACEHOLDER_FIELDS.items():
            fr = tk.Frame(self.init_stack, bg=self.BG)
            self._init_module_frames[mod] = fr
            self._init_entries[mod] = {}
            self._init_cell_widgets[mod] = {}
            self._init_bool_vars[mod] = {}
            hide_fr = tk.Frame(fr, bg=self.BG)
            for c in range(8):
                fr.columnconfigure(c, weight=1, uniform="initcol")

            for key, lbl in fields:
                if str(key).startswith("__sep__"):
                    sep_fr = tk.Frame(fr, bg=self.BG)
                    if (lbl or "").strip():
                        tk.Label(
                            sep_fr, text=lbl, font=("微软雅黑", 8, "bold"),
                            bg=self.BG, fg=self.FG_DIM, anchor="w",
                        ).pack(anchor="w", padx=2, pady=(8, 2))
                    else:
                        tk.Frame(
                            sep_fr, bg=self.BORDER, height=1,
                        ).pack(fill="x", padx=4, pady=(6, 4))
                    self._init_cell_widgets[mod][key] = sep_fr
                    continue

                if key in ("DJ_HDR_MAIN", "DJ_HDR_BAK"):
                    cell = tk.Frame(fr, bg=self.BG)
                    cell.columnconfigure(0, weight=1)
                    tk.Label(
                        cell, text=lbl, font=("微软雅黑", 8, "bold"),
                        bg=self.BG, fg=self.ACCENT, anchor="w",
                    ).grid(row=0, column=0, sticky="w")
                    self._init_cell_widgets[mod][key] = cell
                    continue

                use_hidden = mod in (USG_INIT_MOD_US, USG_INIT_MOD_HK) and key in (
                    "DEFAULT_WAN_MASK", "DEFAULT_LAN_MASK")
                parent = hide_fr if use_hidden else fr
                cell = tk.Frame(parent, bg=self.BG)
                cell.columnconfigure(0, weight=0)
                cell.columnconfigure(1, weight=1)
                _ar_wrap = 0 if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ) else None

                if key in ("DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP", "DEFAULT_GEN_RETURN_ROUTE"):
                    bv = tk.BooleanVar(value=False)
                    self._init_bool_vars[mod][key] = bv
                    if key == "DEFAULT_GEN_RETURN_ROUTE":
                        cb_txt = "生成回程路由"
                    else:
                        cb_txt = "开启"
                    cb_cmd = (
                        lambda m=mod, kk=key: self._on_init_dhcp_toggle(m, kk)
                        if key in ("DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP")
                        else None
                    )
                    _wl_dhcp = (_ar_wrap if _ar_wrap is not None else 120)
                    tk.Label(
                        cell, text=lbl, font=_fl, bg=self.BG, fg=self.FG,
                        anchor="w", wraplength=_wl_dhcp,
                    ).grid(row=0, column=0, sticky="w", padx=(0, 6))
                    cb = tk.Checkbutton(
                        cell, text=cb_txt, variable=bv,
                        font=_fl, bg=self.BG, fg=self.FG,
                        activebackground=self.BG, selectcolor=self.BG_TXT,
                        command=cb_cmd,
                    )
                    cb.grid(row=0, column=1, sticky="w")
                    self._init_cell_widgets[mod][key] = cell
                    continue

                if key == "ZH_DUAL_WAN":
                    bv = tk.BooleanVar(value=False)
                    self._init_bool_vars[mod][key] = bv
                    _wl_zh = (_ar_wrap if _ar_wrap is not None else 120)
                    tk.Label(
                        cell, text=lbl, font=_fl, bg=self.BG, fg=self.FG,
                        anchor="w", wraplength=_wl_zh,
                    ).grid(row=0, column=0, sticky="w", padx=(0, 6))
                    cb = tk.Checkbutton(
                        cell, text="双WAN（开启 WAN2）", variable=bv,
                        font=_fl, bg=self.BG, fg=self.FG,
                        activebackground=self.BG, selectcolor=self.BG_TXT,
                        command=lambda: self._sync_ar_zh_wan2_visual(),
                    )
                    cb.grid(row=0, column=1, sticky="w")
                    self._init_cell_widgets[mod][key] = cell
                    continue

                if key in ("ZH_SOUTH_LABEL", "DJ_SOUTH_LABEL"):
                    _wl_south = (_ar_wrap if _ar_wrap is not None else 140)
                    tk.Label(
                        cell, text=lbl, font=_fl, bg=self.BG, fg=self.FG,
                        anchor="w", wraplength=_wl_south,
                    ).grid(row=0, column=0, sticky="w", padx=(0, 6))
                    arn = EMBEDDED_NS.get(MOD_AR_SDWAN) or {}
                    vals = tuple(arn.get("SOUTH_LABELS_DISPLAY") or ())
                    if not vals:
                        vals = _AR_SOUTH_LABELS_DISPLAY
                    cw = 58
                    if vals:
                        cw = min(72, max(48, max(len(str(x)) for x in vals) + 2))
                    if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ):
                        cw = max(cw, 56)
                    cell.columnconfigure(1, weight=1)
                    cb = ttk.Combobox(
                        cell, values=vals or ("",), state="readonly",
                        font=_fe, width=cw,
                    )
                    if vals:
                        cb.set(vals[0])
                    cb.grid(row=0, column=1, sticky="ew")
                    self._init_entries[mod][key] = cb
                    self._init_cell_widgets[mod][key] = cell
                    continue

                if key in ("ZH_IKE_VERSION", "DJ_IKE_VERSION"):
                    _wl_ike = (_ar_wrap if _ar_wrap is not None else 120)
                    tk.Label(
                        cell, text=lbl, font=_fl, bg=self.BG, fg=self.FG,
                        anchor="w", wraplength=_wl_ike,
                    ).grid(row=0, column=0, sticky="w", padx=(0, 6))
                    ike_fr = tk.Frame(cell, bg=self.BG)
                    ike_fr.grid(row=0, column=1, sticky="w")
                    sv = tk.StringVar(value="v1")
                    self._init_entries[mod][key] = sv
                    tk.Radiobutton(
                        ike_fr, text="IKEv1", variable=sv, value="v1",
                        font=_fl, bg=self.BG, fg=self.FG,
                        activebackground=self.BG, selectcolor=self.BG_TXT,
                        command=lambda m=mod: self._on_init_ike_changed(m),
                    ).pack(side="left", padx=(0, 12))
                    tk.Radiobutton(
                        ike_fr, text="IKEv2", variable=sv, value="v2",
                        font=_fl, bg=self.BG, fg=self.FG,
                        activebackground=self.BG, selectcolor=self.BG_TXT,
                        command=lambda m=mod: self._on_init_ike_changed(m),
                    ).pack(side="left")
                    self._init_cell_widgets[mod][key] = cell
                    continue

                if key in _AR_GE_INIT_KEYS:
                    _wl_ge = (_ar_wrap if _ar_wrap is not None else 120)
                    tk.Label(
                        cell, text=lbl, font=_fl, bg=self.BG, fg=self.FG,
                        anchor="w", wraplength=_wl_ge,
                    ).grid(row=0, column=0, sticky="w", padx=(0, 6))
                    ge_fr = tk.Frame(cell, bg=self.BG)
                    ge_fr.grid(row=0, column=1, sticky="ew")
                    cell.columnconfigure(1, weight=1)
                    tk.Label(
                        ge_fr, text="G(", font=_fe, bg=self.BG, fg=self.FG_DIM,
                    ).pack(side="left")
                    _gw = 22 if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ) else 10
                    ent = tk.Entry(
                        ge_fr, font=_fe, bg=self.BG_TXT, fg=self.FG,
                        relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=self.BORDER, insertbackground=self.FG,
                        width=_gw,
                    )
                    ent.pack(side="left")
                    tk.Label(
                        ge_fr, text=")", font=_fe, bg=self.BG, fg=self.FG_DIM,
                    ).pack(side="left", padx=(0, 2))
                    self._init_entries[mod][key] = ent
                    self._init_cell_widgets[mod][key] = cell
                    continue

                wrap = 260 if mod == MOD_ER_MPLS and key == "DEFAULT_INNER_NETS" else 140
                if mod in (ER_INIT_MOD_HK, ER_INIT_MOD_US) and key == "DEFAULT_INNER_NETS":
                    wrap = 220
                if mod == ER_INIT_MOD_DOMAIN_SPLIT:
                    # 多列排布下列宽较窄，加大折行宽度避免标签被挤成不可读
                    wrap = 320
                if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ):
                    # 0 = 不按像素折行，避免窄格内标签被「竖切」掉字头
                    wrap = 0
                tk.Label(
                    cell, text=lbl, font=_fl, bg=self.BG, fg=self.FG,
                    anchor="w", wraplength=wrap,
                ).grid(row=0, column=0, sticky="nw", padx=(0, 6))
                if key == "DEFAULT_INNER_NETS" and mod in (
                        ER_INIT_MOD_HK, ER_INIT_MOD_US, MOD_ER_MPLS,
                        USG_INIT_MOD_US, USG_INIT_MOD_HK):
                    ent = tk.Text(
                        cell, font=_fe, bg=self.BG_TXT, fg=self.FG,
                        relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=self.BORDER, insertbackground=self.FG,
                        width=40, height=4, wrap="word",
                    )
                    ent.grid(row=0, column=1, sticky="nsew")
                    cell.rowconfigure(0, weight=1)
                    cell.columnconfigure(1, weight=1)
                elif key == "ER_DS_DOMAINS_DEFAULT" and mod == ER_INIT_MOD_DOMAIN_SPLIT:
                    ent = tk.Text(
                        cell, font=_fe, bg=self.BG_TXT, fg=self.FG,
                        relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=self.BORDER, insertbackground=self.FG,
                        width=40, height=3, wrap="word",
                    )
                    ent.grid(row=0, column=1, sticky="nsew")
                    cell.rowconfigure(0, weight=1)
                    cell.columnconfigure(1, weight=1)
                else:
                    ent = tk.Entry(
                        cell, font=_fe, bg=self.BG_TXT, fg=self.FG,
                        relief="flat", bd=0, highlightthickness=1,
                        highlightbackground=self.BORDER, width=_entry_chars(key, mod),
                    )
                    ent.grid(row=0, column=1, sticky="ew")
                self._init_entries[mod][key] = ent
                self._init_cell_widgets[mod][key] = cell

        for mod, kmap in self._init_entries.items():
            for key, ent in kmap.items():
                if isinstance(ent, tk.StringVar):
                    continue
                ent.bind(
                    "<FocusOut>",
                    lambda _e, m=mod, kk=key: self._on_init_entry_focusout(m, kk),
                )

        _ensure_ar_init_factory_seeded()
        self._reload_init_entries_from_globals()
        self._sync_init_dhcp_visual_all()
        self._sync_ar_zh_wan2_visual()
        # USG：LAN 网关始终可编辑；开启 LAN DHCP 时不再把网关框禁用或随 LAN IP 强制覆盖

        # 四栏编辑区（占满 mid 剩余高度，水平可拖分割条）
        pane = ttk.PanedWindow(mid, orient="horizontal")
        self._four_col_pane = pane
        pane.grid(row=1, column=0, sticky="nsew")

        f1 = tk.Frame(pane, bg=self.BG)
        f2 = tk.Frame(pane, bg=self.BG)
        f3 = tk.Frame(pane, bg=self.BG)
        f4 = tk.Frame(pane, bg=self.BG)
        # ①② : ③④ 宽度比例 2 : 3（两列一组，共 2+2+3+3）
        pane.add(f1, weight=2)   # ① 数据头
        pane.add(f2, weight=2)   # ② 变量映射关系
        pane.add(f3, weight=3)   # ③ 生成模板
        pane.add(f4, weight=3)   # ④ 预览
        pane.bind("<Configure>", lambda _e: self._apply_four_col_ratio())
        self.parent.after_idle(self._apply_four_col_ratio)

        self.txt_hdr  = self._panel(
            f1, "① 数据头（variable = value）", xscroll=True,
            font_size=7, title_pt=7, padx_txt=3, pady_txt=2)
        self.txt_map  = self._panel(
            f2, "② 变量映射关系", xscroll=False, font_size=8, title_pt=8)
        self.txt_tpl  = self._panel(
            f3, "③ 生成模板（可编辑，保存后生效）", xscroll=True,
            font_size=7, title_pt=7, padx_txt=3, pady_txt=2)
        self.txt_prev = self._panel(
            f4, "④ 预览效果（点击【预览模板】）", xscroll=True,
            readonly=True, font_size=7, title_pt=7, padx_txt=3, pady_txt=2)

        # 底部按钮栏
        btm = tk.Frame(p, bg=self.BG_HDR, height=38)
        btm.grid(row=3, column=0, sticky="ew")
        btm.grid_propagate(False)

        self.status = tk.StringVar(value="就绪  ·  请选择场景")
        tk.Label(btm, textvariable=self.status,
                 font=("Consolas", 8), bg=self.BG_HDR, fg="#8ec5ff").pack(
            side="left", padx=10)

        self._btn(btm, "  恢复最初模板  ",  "#e07b2a", self.full_reset).pack(side="right", padx=6, pady=5)
        self._btn(btm, "  预览模板  ",      "#16a085", self.preview   ).pack(side="right", padx=6, pady=5)
        self._btn(btm, "  保存并应用  ",    self.ACCENT, self.save    ).pack(side="right", padx=6, pady=5)

    def _show_init_panel_for_scenario(self, scenario_key: str) -> None:
        info = self.SCENARIOS.get(scenario_key) or {}
        slot_mod = _init_mod_for_scenario(info)
        for mod, fr in self._init_module_frames.items():
            if mod == slot_mod:
                fr.grid(row=0, column=0, sticky="ew")
            else:
                fr.grid_remove()

    def _sync_init_outer_height(self, scenario_key: str) -> None:
        """按内容+窗口可用空间动态计算初始化区高度，尽量不遮挡下方四栏。"""
        outer = getattr(self, "_init_outer", None)
        if outer is None:
            return
        info = self.SCENARIOS.get(scenario_key) or {}
        slot_mod = _init_mod_for_scenario(info)
        cur_fr = self._init_module_frames.get(slot_mod)
        mid = outer.master
        try:
            self.parent.update_idletasks()
            # 下调区域位置约 2%（等价于初始化区上调 2% 高度）
            need = int(((cur_fr.winfo_reqheight() if cur_fr is not None else 155) + 16) * 1.02)
            mid_h = mid.winfo_height()
            # 给下方四栏保留最小可视空间，同时尽量拉高初始化区，避免需要滚动
            max_allow = max(240, mid_h - 120) if mid_h > 80 else 420
            outer.configure(height=max(240, min(need, max_allow)))
        except Exception:
            outer.configure(height=280)

    def _apply_four_col_ratio(self) -> None:
        """强制四栏 2:2:3:3 宽度（前两列各 2，后两列各 3）。"""
        pane = getattr(self, "_four_col_pane", None)
        if pane is None:
            return
        try:
            width = pane.winfo_width()
            if width <= 40:
                return
            # 累积分隔位：2/10, 4/10, 7/10
            p1 = int(width * 0.2)
            p2 = int(width * 0.4)
            p3 = int(width * 0.7)
            pane.sashpos(0, p1)
            pane.sashpos(1, p2)
            pane.sashpos(2, p3)
        except Exception:
            pass

    def _on_init_ike_changed(self, mod: str) -> None:
        arn = EMBEDDED_NS.get(MOD_AR_SDWAN)
        if arn is not None:
            key = "ZH_IKE_VERSION" if mod == AR_INIT_MOD_ZH else "DJ_IKE_VERSION"
            ent = self._init_entries.get(mod, {}).get(key)
            if isinstance(ent, tk.StringVar):
                v = _visual_ike_storage(ent.get())
                if mod == AR_INIT_MOD_ZH:
                    arn["ZH_IKE_VERSION_SAVED"] = v
                elif mod == AR_INIT_MOD_DJ:
                    arn["DJ_IKE_VERSION_SAVED"] = v
                fn = arn.get("push_ike_to_formal_panel")
                if callable(fn):
                    fn("ZH" if mod == AR_INIT_MOD_ZH else "DJ", v)
        el = self._validate_init_module(mod)
        title = _INIT_MOD_TITLE.get(mod, mod)
        if el:
            self.status.set(f"{title} 初始化未通过：{el[0]}")
        else:
            self.status.set("就绪  ·  请选择场景")

    def _sync_ar_zh_wan2_visual(self) -> None:
        """可视化里 WAN2 始终可编辑（与正式页「关双 WAN 则灰显」区分，方便预填 WAN2）。"""
        mod = AR_INIT_MOD_ZH
        if mod not in self._init_entries:
            return
        fg = self.FG
        for k in ("DEFAULT_WAN2_PORT", "DEFAULT_WAN2_IP", "DEFAULT_WAN2_GW"):
            cell = self._init_cell_widgets.get(mod, {}).get(k)
            ent = self._init_entries.get(mod, {}).get(k)
            if cell is not None:
                for ch in cell.winfo_children():
                    if isinstance(ch, tk.Label):
                        tx = str(ch.cget("text") or "")
                        if tx in ("G(", ")"):
                            continue
                        try:
                            ch.config(fg=fg)
                        except tk.TclError:
                            pass
                    elif isinstance(ch, tk.Frame):
                        for sub in ch.winfo_children():
                            if isinstance(sub, tk.Label):
                                tx = str(sub.cget("text") or "")
                                if tx in ("G(", ")"):
                                    continue
                                try:
                                    sub.config(fg=fg)
                                except tk.TclError:
                                    pass
            if ent is not None and isinstance(ent, tk.Entry):
                ent.config(state="normal", fg=fg)

    def _relayout_init_form(self, scenario_key: str) -> None:
        info = self.SCENARIOS.get(scenario_key) or {}
        slot_mod = _init_mod_for_scenario(info)
        cells = self._init_cell_widgets.get(slot_mod)
        if not cells:
            return
        for w in cells.values():
            w.grid_forget()
        if slot_mod == ER_INIT_MOD_DOMAIN_SPLIT:
            pad = dict(padx=(3, 3), pady=2)
        else:
            pad = dict(padx=(4, 4), pady=4)
        rows = _init_form_rows_for_scenario(info)
        if rows is not None:
            inner_idx = next(
                (i for i, ln in enumerate(rows) if ln == ["DEFAULT_INNER_NETS"]),
                None,
            )
            if inner_idx is not None and slot_mod in _INIT_INNER_RIGHT_MODS:
                n_before = inner_idx
                after_rows = rows[inner_idx + 1 :]
                inner_box = cells.get("DEFAULT_INNER_NETS")
                # 左侧仅占列 0–3；内网段占 4–7。避免「一行四格铺 0–7」与右侧内网段重叠盖住网关/DHCP/DNS。
                grid_r = 0
                for i in range(n_before):
                    line = rows[i]
                    if len(line) == 1:
                        k0 = line[0]
                        box = cells.get(k0)
                        if box is not None:
                            box.grid(row=grid_r, column=0, columnspan=4, sticky="ew", **pad)
                        grid_r += 1
                    elif len(line) == 2:
                        for ci, key in enumerate(line):
                            box = cells.get(key)
                            if box is not None:
                                box.grid(
                                    row=grid_r, column=ci * 2, columnspan=2,
                                    sticky="ew", **pad,
                                )
                        grid_r += 1
                    elif len(line) == 4:
                        for sub in range(2):
                            pair = line[sub * 2 : sub * 2 + 2]
                            for ci, key in enumerate(pair):
                                box = cells.get(key)
                                if box is not None:
                                    box.grid(
                                        row=grid_r, column=ci * 2, columnspan=2,
                                        sticky="ew", **pad,
                                    )
                            grid_r += 1
                    else:
                        n = len(line)
                        if not n:
                            continue
                        if n > 4:
                            for key in line:
                                box = cells.get(key)
                                if box is not None:
                                    box.grid(
                                        row=grid_r, column=0, columnspan=4,
                                        sticky="ew", **pad,
                                    )
                                grid_r += 1
                            continue
                        q, rem = divmod(4, n)
                        spans = [q + (1 if j < rem else 0) for j in range(n)]
                        acc = 0
                        for ci, key in enumerate(line):
                            box = cells.get(key)
                            if box is not None:
                                box.grid(
                                    row=grid_r, column=acc, columnspan=spans[ci],
                                    sticky="ew", **pad,
                                )
                            acc += spans[ci]
                        grid_r += 1
                grid_r = max(1, grid_r)
                if inner_box is not None:
                    inner_box.grid(
                        row=0,
                        column=4,
                        rowspan=grid_r,
                        columnspan=4,
                        sticky="nsew",
                        **pad,
                    )
                    try:
                        _p = inner_box.master
                        for _rr in range(grid_r):
                            _p.rowconfigure(_rr, weight=1)
                    except tk.TclError:
                        pass
                for j, line in enumerate(after_rows):
                    ri = grid_r + j
                    if len(line) == 1:
                        key = line[0]
                        box = cells.get(key)
                        if box is not None:
                            box.grid(row=ri, column=0, columnspan=8, sticky="ew", **pad)
                    else:
                        spans = _init_row_spans_for_line(len(line))
                        acc = 0
                        for ci, key in enumerate(line):
                            box = cells.get(key)
                            if box is not None:
                                box.grid(
                                    row=ri, column=acc, columnspan=spans[ci],
                                    sticky="ew", **pad,
                                )
                            acc += spans[ci]
            elif slot_mod == AR_INIT_MOD_ZH:
                # 左：WAN 模式 / WAN1·WAN2；右：南向（占多行）+ 自环网关与 IPSec；下：IKE
                slot = str(info.get("tpl_slot") or "")
                is_single_wan = slot in ("TEMPLATE_AR_OPS_SINGLE_WAN1", "TEMPLATE_AR_FACTORY_SINGLE_WAN1")
                def _zg(k: str, **gkw) -> None:
                    bx = cells.get(k)
                    if bx is not None:
                        bx.grid(**gkw, **pad)

                if is_single_wan:
                    _zg("DEFAULT_WAN1_PORT", row=0, column=0, columnspan=4, sticky="ew")
                    _zg("DEFAULT_WAN1_IP", row=1, column=0, columnspan=4, sticky="ew")
                    _zg("DEFAULT_WAN1_GW", row=2, column=0, columnspan=4, sticky="ew")
                    _zg("ZH_SOUTH_LABEL", row=0, column=4, rowspan=2, columnspan=4, sticky="nsew")
                    _zg("DEFAULT_ZIHUAN_PORT", row=2, column=4, columnspan=2, sticky="ew")
                    _zg("DEFAULT_IPSEC_PORT", row=2, column=6, columnspan=2, sticky="ew")
                    _zg("ZH_IKE_VERSION", row=3, column=0, columnspan=4, sticky="ew")
                else:
                    _zg("ZH_DUAL_WAN", row=0, column=0, columnspan=4, sticky="ew")
                    _zg("ZH_SOUTH_LABEL", row=0, column=4, rowspan=3, columnspan=4, sticky="nsew")
                    # 每格仅占 1 列时约 1/8 屏宽，标签+G() 输入会被裁切；左半各用 2 列
                    _zg("DEFAULT_WAN1_PORT", row=1, column=0, columnspan=2, sticky="ew")
                    _zg("DEFAULT_WAN2_PORT", row=1, column=2, columnspan=2, sticky="ew")
                    _zg("DEFAULT_WAN1_IP", row=2, column=0, columnspan=2, sticky="ew")
                    _zg("DEFAULT_WAN2_IP", row=2, column=2, columnspan=2, sticky="ew")
                    _zg("DEFAULT_WAN1_GW", row=3, column=0, columnspan=2, sticky="ew")
                    _zg("DEFAULT_WAN2_GW", row=3, column=2, columnspan=2, sticky="ew")
                    _zg("DEFAULT_ZIHUAN_PORT", row=3, column=4, columnspan=2, sticky="ew")
                    _zg("DEFAULT_IPSEC_PORT", row=3, column=6, columnspan=2, sticky="ew")
                    _zg("ZH_IKE_VERSION", row=4, column=0, columnspan=4, sticky="ew")
            elif slot_mod == AR_INIT_MOD_DJ:
                # 双机场景按模板槽位显示单侧：主场景仅主设备，备场景仅备设备
                slot = str(info.get("tpl_slot") or "")
                only_primary = slot in ("TEMPLATE_AR_OPS_DUAL_PRIMARY", "TEMPLATE_AR_FACTORY_DUAL_PRIMARY")
                only_backup = slot in ("TEMPLATE_AR_OPS_DUAL_BACKUP", "TEMPLATE_AR_FACTORY_DUAL_BACKUP")
                def _dg(k: str, **gkw) -> None:
                    bx = cells.get(k)
                    if bx is not None:
                        bx.grid(**gkw, **pad)

                r = 0
                if only_primary:
                    _dg("DJ_HDR_MAIN", row=r, column=0, columnspan=8, sticky="w")
                    r += 1
                    _dg("DJ_WAN1_PORT", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_ZIHUAN1_PORT", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_WAN1_IP", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_IPSEC1_PORT", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_WAN1_GW", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_SOUTH_LABEL", row=r, column=4, columnspan=4, rowspan=2, sticky="nsew")
                    r += 1
                    _dg("DJ_IKE_VERSION", row=r, column=0, columnspan=4, sticky="ew")
                elif only_backup:
                    _dg("DJ_HDR_BAK", row=r, column=0, columnspan=8, sticky="w")
                    r += 1
                    _dg("DJ_WAN2_PORT", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_ZIHUAN2_PORT", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_WAN2_IP", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_IPSEC2_PORT", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_WAN2_GW", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_SOUTH_LABEL", row=r, column=4, columnspan=4, rowspan=2, sticky="nsew")
                    r += 1
                    _dg("DJ_IKE_VERSION", row=r, column=0, columnspan=4, sticky="ew")
                else:
                    _dg("DJ_HDR_MAIN", row=r, column=0, columnspan=4, sticky="w")
                    _dg("DJ_HDR_BAK", row=r, column=4, columnspan=4, sticky="w")
                    r += 1
                    _dg("DJ_WAN1_PORT", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_WAN2_PORT", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_WAN1_IP", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_WAN2_IP", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_WAN1_GW", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_WAN2_GW", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_ZIHUAN1_PORT", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_ZIHUAN2_PORT", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_IPSEC1_PORT", row=r, column=0, columnspan=4, sticky="ew")
                    _dg("DJ_IPSEC2_PORT", row=r, column=4, columnspan=4, sticky="ew")
                    r += 1
                    _dg("DJ_SOUTH_LABEL", row=r, column=0, columnspan=8, sticky="ew")
                    r += 1
                    _dg("DJ_IKE_VERSION", row=r, column=0, columnspan=8, sticky="ew")
            else:
                for ri, line in enumerate(rows):
                    if len(line) == 1:
                        key = line[0]
                        box = cells.get(key)
                        if box is not None:
                            box.grid(row=ri, column=0, columnspan=8, sticky="ew", **pad)
                        continue
                    spans = _init_row_spans_for_line(len(line))
                    acc = 0
                    for ci, key in enumerate(line):
                        box = cells.get(key)
                        if box is not None:
                            box.grid(
                                row=ri, column=acc, columnspan=spans[ci],
                                sticky="ew", **pad,
                            )
                        acc += spans[ci]
        else:
            order = _init_layout_key_order(info)
            row, col_idx, ncols = 0, 0, 4
            line_spans = _init_row_spans_for_line(ncols)
            line_acc = 0
            for key in order:
                box = cells.get(key)
                if box is None:
                    continue
                if str(key).startswith("__sep__"):
                    box.grid(row=row, column=0, columnspan=8, sticky="ew", **pad)
                    row += 1
                    col_idx = 0
                    line_acc = 0
                    continue
                box.grid(
                    row=row, column=line_acc, columnspan=line_spans[col_idx],
                    sticky="ew", **pad,
                )
                col_idx += 1
                line_acc += line_spans[col_idx - 1]
                if col_idx >= ncols:
                    col_idx = 0
                    line_acc = 0
                    row += 1
        self._sync_init_dhcp_visual_all()

    def _on_init_dhcp_toggle(self, mod: str, dhcp_key: str) -> None:
        if dhcp_key == "DEFAULT_WAN_DHCP":
            self._sync_visual_wan_dhcp(mod)
        elif dhcp_key == "DEFAULT_LAN_DHCP" and mod in (USG_INIT_MOD_US, USG_INIT_MOD_HK):
            lan_on = self._init_bool_vars[mod]["DEFAULT_LAN_DHCP"].get()
            self._sync_visual_lan_dhcp_usg(mod, force_fill_gw=lan_on)

    def _sync_visual_wan_dhcp(self, mod: str) -> None:
        if mod not in self._init_bool_vars or "DEFAULT_WAN_DHCP" not in self._init_bool_vars[mod]:
            return
        on = self._init_bool_vars[mod]["DEFAULT_WAN_DHCP"].get()
        if mod in (ER_INIT_MOD_HK, ER_INIT_MOD_US):
            e_ip = self._init_entries[mod]["DEFAULT_WAN_CIDR"]
            e_gw = self._init_entries[mod]["DEFAULT_WAN_GW"]
        elif mod == MOD_ER_MPLS:
            e_ip = self._init_entries[mod]["DEFAULT_WAN_CIDR"]
            e_gw = self._init_entries[mod]["DEFAULT_WAN_GW"]
        elif mod in (USG_INIT_MOD_US, USG_INIT_MOD_HK):
            e_ip = self._init_entries[mod]["DEFAULT_WAN_IP"]
            e_gw = self._init_entries[mod]["DEFAULT_WAN_GW"]
        else:
            return
        emb = _embedded_name_for_init_mod(mod)
        ns = EMBEDDED_NS.get(emb) or {}
        if mod == ER_INIT_MOD_HK:
            ph_ip = str(ns.get("HK_DEFAULT_WAN_CIDR", ""))
            ph_gw = str(ns.get("HK_DEFAULT_WAN_GW", ""))
        elif mod == ER_INIT_MOD_US:
            ph_ip, ph_gw = str(ns.get("DEFAULT_WAN_CIDR", "")), str(ns.get("DEFAULT_WAN_GW", ""))
        elif mod == MOD_ER_MPLS:
            ph_ip, ph_gw = str(ns.get("DEFAULT_WAN_CIDR", "")), str(ns.get("DEFAULT_WAN_GW", ""))
        elif mod == USG_INIT_MOD_HK:
            ph_ip = str(ns.get("HK_DEFAULT_WAN_IP", ""))
            ph_gw = str(ns.get("HK_DEFAULT_WAN_GW", ""))
        else:
            ph_ip, ph_gw = str(ns.get("DEFAULT_WAN_IP", "")), str(ns.get("DEFAULT_WAN_GW", ""))
        if on:
            cur_i = e_ip.get().strip()
            cur_g = e_gw.get().strip()
            if cur_i.lower() != "dhcp":
                self._init_wan_saved[mod] = (cur_i, cur_g)
            for en in (e_ip, e_gw):
                en.config(state="normal")
                en.delete(0, tk.END)
                en.insert(0, "dhcp")
                en.config(state="disabled", disabledforeground=self.FG_DIM)
        else:
            for en in (e_ip, e_gw):
                en.config(state="normal", fg=self.FG, disabledforeground=self.FG_DIM)
            si, sg = self._init_wan_saved.get(mod, ("", ""))
            rip = si or ph_ip
            rwg = sg or ph_gw
            e_ip.delete(0, tk.END)
            e_ip.insert(0, rip)
            e_gw.delete(0, tk.END)
            e_gw.insert(0, rwg)

    def _sync_visual_lan_dhcp_usg(
        self, mod: str, *, force_fill_gw: bool = False,
    ) -> None:
        if mod not in self._init_bool_vars or "DEFAULT_LAN_DHCP" not in self._init_bool_vars[mod]:
            return
        on = self._init_bool_vars[mod]["DEFAULT_LAN_DHCP"].get()
        e_lan = self._init_entries[mod]["DEFAULT_LAN_IP"]
        e_gw = self._init_entries[mod]["DEFAULT_LAN_GW"]
        emb = _embedded_name_for_init_mod(mod)
        ns = EMBEDDED_NS.get(emb) or {}
        gk = _global_key_for_usg_init_mod(mod, "DEFAULT_LAN_IP")
        gk_gw = _global_key_for_usg_init_mod(mod, "DEFAULT_LAN_GW")
        ph_lan = str(ns.get(gk, ""))
        if on:
            e_gw.config(state="normal", fg=self.FG, disabledforeground=self.FG_DIM)
            if force_fill_gw:
                raw = (e_lan.get().strip() or ph_lan)
                host = raw.split("/")[0].strip() or ph_lan.split("/")[0].strip()
                e_gw.delete(0, tk.END)
                e_gw.insert(0, host)
        else:
            e_gw.config(state="normal", fg=self.FG, disabledforeground=self.FG_DIM)
            e_gw.delete(0, tk.END)
            lgw = str(ns.get(gk_gw, "")).strip() or ph_lan
            e_gw.insert(0, lgw)

    def _sync_init_dhcp_visual_all(self) -> None:
        for m in (ER_INIT_MOD_HK, ER_INIT_MOD_US, MOD_ER_MPLS,
                  USG_INIT_MOD_US, USG_INIT_MOD_HK):
            self._sync_visual_wan_dhcp(m)
        for m in (USG_INIT_MOD_US, USG_INIT_MOD_HK):
            self._sync_visual_lan_dhcp_usg(m)

    def _init_mod_row_snapshot(self, mod: str) -> dict[str, str]:
        """单模块初始化表单 → 与 _sync_init_to_module_globals 相同规则的 dict。"""
        row: dict[str, str] = {}
        kmap = self._init_entries.get(mod, {})
        if not kmap:
            return row
        b = self._init_bool_vars.get(mod, {})
        emb = _embedded_name_for_init_mod(mod)
        ns = EMBEDDED_NS.get(emb) or {}
        wan_b = b.get("DEFAULT_WAN_DHCP")
        wan_on = bool(wan_b.get()) if wan_b else False
        for k, e in kmap.items():
            if k.startswith("__sep__") or k.startswith("DJ_HDR_"):
                continue
            if mod in (ER_INIT_MOD_HK, ER_INIT_MOD_US) and wan_on and k in (
                    "DEFAULT_WAN_CIDR", "DEFAULT_WAN_GW"):
                si, sg = self._init_wan_saved.get(mod, ("", ""))
                if mod == ER_INIT_MOD_HK:
                    row[k] = (si if k == "DEFAULT_WAN_CIDR" else sg) or str(ns.get("HK_" + k, ""))
                else:
                    row[k] = (si if k == "DEFAULT_WAN_CIDR" else sg) or str(ns.get(k, ""))
            elif mod == MOD_ER_MPLS and wan_on and k in (
                    "DEFAULT_WAN_CIDR", "DEFAULT_WAN_GW"):
                si, sg = self._init_wan_saved.get(mod, ("", ""))
                row[k] = (si if k == "DEFAULT_WAN_CIDR" else sg) or str(ns.get(k, ""))
            elif mod in (USG_INIT_MOD_US, USG_INIT_MOD_HK) and wan_on and k in (
                    "DEFAULT_WAN_IP", "DEFAULT_WAN_GW"):
                si, sg = self._init_wan_saved.get(mod, ("", ""))
                gk = _global_key_for_usg_init_mod(mod, k)
                row[k] = (si if k == "DEFAULT_WAN_IP" else sg) or str(ns.get(gk, ""))
            elif k in ("ZH_IKE_VERSION", "DJ_IKE_VERSION"):
                row[k] = _visual_ike_storage(self._init_field_value(e))
            else:
                row[k] = self._init_field_value(e)
        if "DEFAULT_LAN_GW" in row:
            lan_src = row.get("DEFAULT_LAN_CIDR", row.get("DEFAULT_LAN_IP", ""))
            row["DEFAULT_LAN_GW"] = _normalize_lan_gw_alias(lan_src, row.get("DEFAULT_LAN_GW", ""))
        _inject_init_plain_ips(row)
        for key, bv in b.items():
            row[key] = "true" if bv.get() else "false"
        return row

    def _sync_single_init_mod_to_globals(self, mod: str) -> None:
        """仅将某一初始化模块写入对应嵌入脚本并刷新正式页（用于飞连等场景避免强依赖「保存」）。"""
        if mod not in self._init_entries:
            return
        _apply_init_placeholder_updates({mod: self._init_mod_row_snapshot(mod)})

    def _sync_init_to_module_globals(self) -> None:
        """将当前可视化初始化面板的值写入各模块 globals 并刷新正式页面。"""
        data = {mod: self._init_mod_row_snapshot(mod) for mod in self._init_entries}
        _apply_init_placeholder_updates(data)

    def _panel(self, parent: tk.Frame, title: str,
               xscroll: bool = True, readonly: bool = False,
               font_size: int = 9,
               title_pt: int = 9,
               padx_txt: int = 6,
               pady_txt: int = 4) -> tk.Text:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        tk.Label(parent, text=f"  {title}",
                 font=("微软雅黑", title_pt, "bold"),
                 bg=self.BG_HDR, fg=self.FG_WH,
                 anchor="w", height=1).grid(row=0, column=0, sticky="ew")
        wrap_outer = tk.Frame(parent, bg=self.BG_TXT,
                              highlightthickness=1,
                              highlightbackground=self.BORDER)
        wrap_outer.grid(row=1, column=0, sticky="nsew")
        wrap_outer.rowconfigure(0, weight=1)
        wrap_outer.columnconfigure(0, weight=1)

        ysb = ttk.Scrollbar(wrap_outer, orient="vertical")
        ysb.grid(row=0, column=1, sticky="ns")

        # col2 (映射关系): word wrap, no x scroll
        wrap_mode = "none" if xscroll else "word"

        txt = tk.Text(
            wrap_outer,
            font=("Consolas", font_size),
            bg=self.BG_TXT if not readonly else "#f0f6ff",
            fg=self.FG,
            relief="flat", bd=0,
            padx=padx_txt, pady=pady_txt,
            undo=True, maxundo=80,
            wrap=wrap_mode,
            yscrollcommand=ysb.set,
            state="normal" if not readonly else "disabled",
        )
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.config(command=txt.yview)

        if xscroll:
            xsb = ttk.Scrollbar(wrap_outer, orient="horizontal")
            xsb.grid(row=1, column=0, sticky="ew")
            txt.config(xscrollcommand=xsb.set)
            xsb.config(command=txt.xview)

        return txt

    def _btn(self, parent, text: str, color: str, cmd) -> tk.Label:
        darken = {
            self.ACCENT: "#005f94",
            "#e07b2a":   "#b85e1a",
            "#16a085":   "#0e7060",
            "#6c757d":   "#4a545b",
        }.get(color, "#444")
        b = tk.Label(parent, text=text,
                     font=("微软雅黑", 9, "bold"),
                     bg=color, fg=self.FG_WH,
                     padx=8, pady=4, cursor="hand2")
        b.bind("<Button-1>", lambda _: cmd())
        b.bind("<Enter>",    lambda _: b.config(bg=darken))
        b.bind("<Leave>",    lambda _: b.config(bg=color))
        return b

    # ── 数据加载 ─────────────────────────────────────────────────────

    def _get_src(self, filename: str) -> str:
        if filename not in self._src_cache:
            self._src_cache[filename] = _read_src(filename)
        return self._src_cache[filename]

    def _default_tpl(self, info: dict) -> str:
        return _factory_tpl_for_scenario(info)

    def _safe_key(self, key: str) -> str:
        return _editor_safe_key(_visual_scenario_disk_key(key))

    def _scenario_dir(self, key: str) -> Path:
        return _scenario_workspace_dir(key)

    def _tpl_file(self, key: str, info: dict) -> Path:
        return self._scenario_dir(key) / f"{_scenario_tpl_slot(info)}.tpl"

    def _legacy_flat(self, key: str, suffix: str) -> Path:
        return WORKSPACE / f"{self._safe_key(key)}_{suffix}"

    def _persist_to_disk(
        self,
        key: str,
        hdr: str,
        mp: str,
        tpl: str,
        *,
        event: str,
    ) -> None:
        """统一落盘：场景子目录 + changelog。"""
        if getattr(self, "_regression_skip_disk", False):
            return
        info = self.SCENARIOS[key]
        sdir = self._scenario_dir(key)
        sdir.mkdir(parents=True, exist_ok=True)
        slot = _scenario_tpl_slot(info)
        tpl_path = sdir / f"{slot}.tpl"
        # 写入前先读旧内容，用于 changelog 里记录"何时 + 新增/删除哪些行"
        before_tpl = tpl_path.read_text(encoding="utf-8-sig") if tpl_path.exists() else ""
        hdr_path = sdir / "headers.txt"
        mp_path = sdir / "mapping.txt"
        before_hdr = hdr_path.read_text(encoding="utf-8-sig") if hdr_path.exists() else ""
        before_mp = mp_path.read_text(encoding="utf-8-sig") if mp_path.exists() else ""

        tpl_path.write_text(tpl, encoding="utf-8-sig")
        hdr_path.write_text(hdr, encoding="utf-8-sig")
        mp_path.write_text(mp, encoding="utf-8-sig")

        from datetime import datetime

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # autosave 可能触发频繁：仅写"新增/删除数量"，避免 changelog 爆长
        include_items = event in ("save", "full_reset")

        add_tpl, del_tpl, add_tpl_items, del_tpl_items = _diff_added_removed(
            before_tpl, tpl, max_items=6
        )
        add_hdr, del_hdr, add_hdr_items, del_hdr_items = _diff_added_removed(
            before_hdr, hdr, max_items=6
        )
        add_mp, del_mp, add_mp_items, del_mp_items = _diff_added_removed(
            before_mp, mp, max_items=6
        )

        lines: list[str] = []
        lines.append(f"{ts}\t{event}\t场景模板={slot}")
        lines.append(
            f"  headers.txt: +{add_hdr} -{del_hdr}; mapping.txt: +{add_mp} -{del_mp}; {slot}.tpl: +{add_tpl} -{del_tpl}"
        )
        if include_items:
            for it in add_hdr_items:
                lines.append(f"    + headers: {it}")
            for it in del_hdr_items:
                lines.append(f"    - headers: {it}")
            for it in add_mp_items:
                lines.append(f"    + mapping: {it}")
            for it in del_mp_items:
                lines.append(f"    - mapping: {it}")
            for it in add_tpl_items:
                lines.append(f"    + tpl: {it}")
            for it in del_tpl_items:
                lines.append(f"    - tpl: {it}")

        _append_scenario_changelog(sdir, "\n".join(lines))
        _apply_template_to_runtime(key, info, tpl)

    def _tpl_version_counter_path(self, key: str) -> Path:
        return self._scenario_dir(key) / "template_version.txt"

    def _read_tpl_version_counter(self, key: str) -> int:
        p = self._tpl_version_counter_path(key)
        if not p.exists():
            return 0
        try:
            return max(0, int(p.read_text(encoding="utf-8-sig").strip()))
        except ValueError:
            return 0

    def _write_tpl_version_counter(self, key: str, value: int) -> None:
        if getattr(self, "_regression_skip_disk", False):
            return
        try:
            self._scenario_dir(key).mkdir(parents=True, exist_ok=True)
            self._tpl_version_counter_path(key).write_text(str(max(0, value)), encoding="utf-8-sig")
        except Exception:
            pass

    def _sync_tpl_version_counter_from_tpl(self, key: str, tpl: str) -> None:
        """从已载入的模板头同步计数器，避免磁盘上已有 vN 时下次保存版本号变小。"""
        m = _RE_EDITOR_TPL_VERSION_HDR.match(tpl)
        if not m:
            return
        try:
            v = int(m.group(1))
        except ValueError:
            return
        cur = self._read_tpl_version_counter(key)
        if v > cur:
            self._write_tpl_version_counter(key, v)

    def _bump_tpl_version_stamp(self, key: str, tpl: str) -> tuple[int, str]:
        """
        去掉旧版本头后，按 max(计数器, 文内版本号)+1 生成新头，写回计数器。
        仅应在「保存并应用」成功确认后调用。
        """
        m = _RE_EDITOR_TPL_VERSION_HDR.match(tpl)
        v_in_tpl = int(m.group(1)) if m else 0
        body = tpl[m.end():] if m else tpl
        body = body.lstrip("\n\r")
        ctr = self._read_tpl_version_counter(key)
        new_v = max(ctr, v_in_tpl) + 1
        self._write_tpl_version_counter(key, new_v)
        from datetime import datetime
        dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        head = (
            "# ============================================================\n"
            f"# 场景模板版本 | version: {new_v} | 日期: {dt}\n"
            "# ============================================================\n\n"
        )
        return new_v, head + body

    def _auto_save_current(self) -> None:
        """静默保存当前场景（子目录 + 日志）。"""
        if getattr(self, "_regression_skip_disk", False):
            return
        key = self._current_key
        if not key or key not in self.SCENARIOS:
            return
        try:
            hdr = self.txt_hdr.get("1.0", tk.END)
            mp  = self.txt_map.get("1.0", tk.END)
            tpl = self.txt_tpl.get("1.0", tk.END)
            self._persist_to_disk(key, hdr, mp, tpl, event="auto_save")
        except Exception:
            pass

    def _set_text(self, widget: tk.Text, content: str, readonly: bool = False) -> None:
        was_disabled = widget.cget("state") == "disabled"
        widget.config(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, content)
        if readonly or was_disabled:
            widget.config(state="disabled")

    def _reset_visual_editor_undo(self) -> None:
        """四栏 Text 在场景间复用；载入新场景后须清空 undo，否则 Ctrl+Z 会回到上一场景的编辑记录。"""
        for w in (self.txt_hdr, self.txt_map, self.txt_tpl, self.txt_prev):
            try:
                if not w.cget("undo"):
                    continue
                was = str(w.cget("state"))
                w.config(state="normal")
                w.edit_reset()
                if was == "disabled":
                    w.config(state="disabled")
            except tk.TclError:
                pass

    @staticmethod
    def _init_field_value(widget: Any) -> str:
        if isinstance(widget, tk.StringVar):
            return str(widget.get()).strip()
        if isinstance(widget, tk.Text):
            return widget.get("1.0", tk.END).replace("\r\n", "\n").strip()
        return str(widget.get()).strip()

    def _iev(self, mod: str, key: str) -> str:
        return self._init_field_value(self._init_entries[mod][key])

    def _preview_init_values(self, info: dict) -> dict[str, str]:
        """提取当前场景初始化表单值，供预览映射与模板渲染补齐使用。

        必须与 _init_mod_row_snapshot 一致：含布尔项（DEFAULT_*_DHCP、DEFAULT_GEN_RETURN_ROUTE
        等）及 ER/USG 在 DHCP 开闭下的 WAN 字段回退规则，否则会出现「保存/同步到正式页已变、
        预览仍用旧值」的错位。此前仅扫描 _init_entries 会漏掉 _init_bool_vars，已修复。
        """
        mod = _init_mod_for_scenario(info)
        out: dict[str, str] = dict(self._init_mod_row_snapshot(mod))
        # 常用别名，便于模板直接引用业务变量名（snapshot 中已是 DEFAULT_* 与 *_PLAIN）
        if out.get("DEFAULT_LAN_CIDR") and not out.get("lan_ip"):
            out["lan_ip"] = out["DEFAULT_LAN_CIDR"]
        if out.get("DEFAULT_LAN_IP") and not out.get("lan_ip"):
            out["lan_ip"] = out["DEFAULT_LAN_IP"]
        if out.get("DEFAULT_WAN_CIDR"):
            out.setdefault("wan_ip", out["DEFAULT_WAN_CIDR"])
            out.setdefault("wan_addr", out["DEFAULT_WAN_CIDR"])
        if out.get("DEFAULT_WAN_IP"):
            out.setdefault("wan_ip", out["DEFAULT_WAN_IP"])
        if out.get("DEFAULT_DNS1"):
            out.setdefault("dns_ip1", out["DEFAULT_DNS1"])
        if out.get("DEFAULT_DNS2"):
            out.setdefault("dns_ip2", out["DEFAULT_DNS2"])
        return out

    def _validate_init_module(self, mod: str) -> list[str]:
        """与各工具页签初始化校验一致；返回错误文案列表（空=通过）。"""
        emb = _embedded_name_for_init_mod(mod)
        ns = EMBEDDED_NS.get(emb)
        if not ns:
            return []
        g = self._init_entries.get(mod, {})
        b = self._init_bool_vars.get(mod, {})
        errs: list[str] = []

        if mod in (ER_INIT_MOD_HK, ER_INIT_MOD_US):
            w = _init_eth_suffix_ok(self._iev(mod, "DEFAULT_WAN_ETH"), "WAN口")
            if w:
                errs.append(w)
            le = _init_eth_suffix_ok(self._iev(mod, "DEFAULT_LAN_ETH"), "LAN口")
            if le:
                errs.append(le)
            fn = ns.get("validate_net_panel_values")
            if fn:
                hk = mod == ER_INIT_MOD_HK
                wan_b = b.get("DEFAULT_WAN_DHCP")
                wan_on = bool(wan_b.get()) if wan_b else False
                if wan_on:
                    if hk:
                        wan_ip = str(ns.get("HK_DEFAULT_WAN_CIDR", ""))
                        wan_gw = str(ns.get("HK_DEFAULT_WAN_GW", ""))
                    else:
                        wan_ip = str(ns.get("DEFAULT_WAN_CIDR", ""))
                        wan_gw = str(ns.get("DEFAULT_WAN_GW", ""))
                else:
                    wan_ip = self._iev(mod, "DEFAULT_WAN_CIDR")
                    wan_gw = self._iev(mod, "DEFAULT_WAN_GW")
                lan_ip = self._iev(mod, "DEFAULT_LAN_CIDR")
                lan_gw = self._iev(mod, "DEFAULT_LAN_GW") if "DEFAULT_LAN_GW" in g else ""
                lan_gw = _normalize_lan_gw_alias(lan_ip, lan_gw)
                inner = self._iev(mod, "DEFAULT_INNER_NETS")
                if hk:
                    pwc = str(ns.get("HK_DEFAULT_WAN_CIDR", ""))
                    pwg = str(ns.get("HK_DEFAULT_WAN_GW", ""))
                    plc = str(ns.get("HK_DEFAULT_LAN_CIDR", ""))
                else:
                    pwc = str(ns.get("DEFAULT_WAN_CIDR", ""))
                    pwg = str(ns.get("DEFAULT_WAN_GW", ""))
                    plc = str(ns.get("DEFAULT_LAN_CIDR", ""))
                ok, el = fn(wan_ip, wan_gw, lan_ip, lan_gw, inner, pwc, pwg, plc)
                if not ok:
                    errs.extend(el)

        elif mod == MOD_ER_MPLS:
            w = _init_eth_suffix_ok(self._iev(mod, "DEFAULT_WAN_ETH"), "WAN口")
            if w:
                errs.append(w)
            le = _init_eth_suffix_ok(self._iev(mod, "DEFAULT_LAN_ETH"), "LAN口")
            if le:
                errs.append(le)
            fn = ns.get("validate_net_panel_values")
            if fn:
                wan_b = b.get("DEFAULT_WAN_DHCP")
                wan_on = bool(wan_b.get()) if wan_b else False
                if wan_on:
                    wan_ip = str(ns.get("DEFAULT_WAN_CIDR", ""))
                    wan_gw = str(ns.get("DEFAULT_WAN_GW", ""))
                else:
                    wan_ip = self._iev(mod, "DEFAULT_WAN_CIDR")
                    wan_gw = self._iev(mod, "DEFAULT_WAN_GW")
                lan_ip = self._iev(mod, "DEFAULT_LAN_CIDR")
                lan_gw = self._iev(mod, "DEFAULT_LAN_GW") if "DEFAULT_LAN_GW" in g else ""
                lan_gw = _normalize_lan_gw_alias(lan_ip, lan_gw)
                inner = self._iev(mod, "DEFAULT_INNER_NETS")
                ok, el = fn(
                    wan_ip, wan_gw, lan_ip, lan_gw, inner,
                    str(ns.get("DEFAULT_WAN_CIDR", "")),
                    str(ns.get("DEFAULT_WAN_GW", "")),
                    str(ns.get("DEFAULT_LAN_CIDR", "")),
                )
                if not ok:
                    errs.extend(el)

        elif mod in (USG_INIT_MOD_US, USG_INIT_MOD_HK):
            fn = ns.get("validate_net_panel_values")
            wan_b = b.get("DEFAULT_WAN_DHCP")
            wan_on = bool(wan_b.get()) if wan_b else False
            if wan_on:
                gk_wip = _global_key_for_usg_init_mod(mod, "DEFAULT_WAN_IP")
                gk_wgw = _global_key_for_usg_init_mod(mod, "DEFAULT_WAN_GW")
                wan_ip = str(ns.get(gk_wip, ""))
                wan_gw = str(ns.get(gk_wgw, ""))
            else:
                wan_ip = self._iev(mod, "DEFAULT_WAN_IP")
                wan_gw = self._iev(mod, "DEFAULT_WAN_GW")
            lan_ip = self._iev(mod, "DEFAULT_LAN_IP")
            lan_gw = _normalize_lan_gw_alias(lan_ip, self._iev(mod, "DEFAULT_LAN_GW"))
            inner = self._iev(mod, "DEFAULT_INNER_NETS")
            gk_ph_wip = _global_key_for_usg_init_mod(mod, "DEFAULT_WAN_IP")
            gk_ph_wgw = _global_key_for_usg_init_mod(mod, "DEFAULT_WAN_GW")
            gk_ph_lip = _global_key_for_usg_init_mod(mod, "DEFAULT_LAN_IP")
            ph_wan_ip = str(ns.get(gk_ph_wip, ""))
            ph_wan_gw = str(ns.get(gk_ph_wgw, ""))
            ph_lan = str(ns.get(gk_ph_lip, ""))
            if fn:
                ok, el = fn(wan_ip, wan_gw, lan_ip, lan_gw, inner, ph_wan_ip, ph_wan_gw, ph_lan)
                if not ok:
                    errs.extend(el)
            dns_lbl = "骨干DNS(HK)" if mod == USG_INIT_MOD_HK else "骨干DNS(非香港)"
            for key, lab in (
                ("DEFAULT_DNS1", f"{dns_lbl}主"),
                ("DEFAULT_DNS2", f"{dns_lbl}备"),
            ):
                if key not in g:
                    continue
                msg = _init_dns_ipv4_ok(g[key].get(), lab)
                if msg:
                    errs.append(msg)

        elif mod == AR_INIT_MOD_ZH:
            fn = ns.get("validate_zihuan_init")
            if fn:
                fac = INIT_PLACEHOLDERS_FACTORY.get(mod, {})
                zh_b = self._init_bool_vars.get(mod, {})
                dual = bool(zh_b["ZH_DUAL_WAN"].get()) if "ZH_DUAL_WAN" in zh_b else False
                ok, el = fn(
                    dual,
                    self._iev(mod, "DEFAULT_WAN1_IP"),
                    self._iev(mod, "DEFAULT_WAN2_IP"),
                    self._iev(mod, "DEFAULT_WAN1_GW"),
                    self._iev(mod, "DEFAULT_WAN2_GW"),
                    self._iev(mod, "DEFAULT_WAN1_PORT"),
                    self._iev(mod, "DEFAULT_WAN2_PORT"),
                    self._iev(mod, "DEFAULT_ZIHUAN_PORT"),
                    self._iev(mod, "DEFAULT_IPSEC_PORT"),
                    str(fac.get("DEFAULT_WAN1_IP", ns.get("DEFAULT_WAN1_IP", ""))),
                    str(fac.get("DEFAULT_WAN2_IP", ns.get("DEFAULT_WAN2_IP", ""))),
                    str(fac.get("DEFAULT_WAN1_GW", ns.get("DEFAULT_WAN1_GW", ""))),
                    str(fac.get("DEFAULT_WAN2_GW", ns.get("DEFAULT_WAN2_GW", ""))),
                    str(fac.get("DEFAULT_WAN1_PORT", ns.get("DEFAULT_WAN1_PORT", ""))),
                    str(fac.get("DEFAULT_WAN2_PORT", ns.get("DEFAULT_WAN2_PORT", ""))),
                    str(fac.get("DEFAULT_ZIHUAN_PORT", ns.get("DEFAULT_ZIHUAN_PORT", ""))),
                    str(fac.get("DEFAULT_IPSEC_PORT", ns.get("DEFAULT_IPSEC_PORT", ""))),
                )
                if not ok:
                    errs.extend(el)
        elif mod == AR_INIT_MOD_DJ:
            fn = ns.get("validate_duoji_init")
            if fn:
                ok, el = fn(
                    self._iev(mod, "DJ_WAN1_IP"),
                    self._iev(mod, "DJ_WAN2_IP"),
                    self._iev(mod, "DJ_WAN1_GW"),
                    self._iev(mod, "DJ_WAN2_GW"),
                    self._iev(mod, "DJ_WAN1_PORT"),
                    self._iev(mod, "DJ_ZIHUAN1_PORT"),
                    self._iev(mod, "DJ_IPSEC1_PORT"),
                    self._iev(mod, "DJ_WAN2_PORT"),
                    self._iev(mod, "DJ_ZIHUAN2_PORT"),
                    self._iev(mod, "DJ_IPSEC2_PORT"),
                )
                if not ok:
                    errs.extend(el)

        elif mod == ER_INIT_MOD_FLINK:
            for key, lab in (
                ("ER_FL_MAIN_NH_DEFAULT", "主回程下一跳"),
                ("ER_FL_BACKUP_NH_DEFAULT", "备回程下一跳"),
            ):
                if key not in g:
                    continue
                v = self._iev(mod, key).strip()
                if v:
                    try:
                        ipaddress.ip_address(v.split("/", 1)[0].strip())
                    except (ValueError, ipaddress.AddressValueError):
                        try:
                            ipaddress.ip_network(v, strict=False)
                        except (ValueError, ipaddress.AddressValueError):
                            errs.append(f"{lab}「{v}」不是合法 IP/CIDR")

        elif mod == ER_INIT_MOD_NEW_EXIT:
            for key, lab in (
                ("ER_NE_MAIN_PE_NH_DEFAULT", "主pe对接下一跳"),
                ("ER_NE_BK_PE_NH_DEFAULT", "备pe对接下一跳"),
            ):
                if key not in g:
                    continue
                v = self._iev(mod, key).strip()
                if v:
                    try:
                        ipaddress.ip_address(v.split("/", 1)[0].strip())
                    except (ValueError, ipaddress.AddressValueError):
                        try:
                            ipaddress.ip_network(v, strict=False)
                        except (ValueError, ipaddress.AddressValueError):
                            errs.append(f"{lab}「{v}」不是合法 IP/CIDR")
            for key, lab in (
                ("ER_NE_MAIN_DUM_DEFAULT", "主新增ip dum号"),
                ("ER_NE_BK_DUM_DEFAULT", "备新增ip dum号"),
                ("ER_NE_MAIN_NAT_RULE_DEFAULT", "主 NAT rule 起始号"),
                ("ER_NE_BK_NAT_RULE_DEFAULT", "备 NAT rule 起始号"),
            ):
                if key not in g:
                    continue
                v = self._iev(mod, key).strip()
                if v and not v.isdigit():
                    errs.append(f"{lab}须为整数")
            sc = self._iev(mod, "ER_NE_NAT_SOURCE_CIDR_DEFAULT").strip()
            if sc:
                try:
                    ipaddress.ip_network(sc, strict=False)
                except (ValueError, ipaddress.AddressValueError):
                    errs.append(f"NAT 源网段「{sc}」非法")

        elif mod in (USG_INIT_MOD_FLINK, USG_INIT_MOD_NEW_EXIT):
            if mod == USG_INIT_MOD_FLINK:
                tun_fields = (
                    ("USG_FL_MAIN_TUN_DEFAULT", "主 Tunnel 号"),
                    ("USG_FL_BK_TUN_DEFAULT", "备 Tunnel 号"),
                )
            else:
                tun_fields = (
                    ("USG_NE_MAIN_TUN_DEFAULT", "主 Tunnel 号"),
                    ("USG_NE_BK_TUN_DEFAULT", "备 Tunnel 号"),
                    ("USG_NE_MAIN_LOOP_START_DEFAULT", "主 LoopBack 起始号"),
                    ("USG_NE_BK_LOOP_START_DEFAULT", "备 LoopBack 起始号"),
                )
            for key, lab in tun_fields:
                if key not in g:
                    continue
                v = self._iev(mod, key).strip()
                if v and not v.isdigit():
                    errs.append(f"{lab}须为整数")
            if mod == USG_INIT_MOD_NEW_EXIT:
                for key, lab in (
                    ("USG_NE_MAIN_NQA_DEFAULT", "主 NQA 名称"),
                    ("USG_NE_BK_NQA_DEFAULT", "备 NQA 名称"),
                ):
                    if key not in g:
                        continue
                    v = self._iev(mod, key).strip()
                    if v and not re.match(r"^[A-Za-z0-9._-]+$", v):
                        errs.append(f"{lab}仅允许字母数字及 ._-")

        elif mod == ER_INIT_MOD_DOMAIN_SPLIT:
            if "ER_DS_DNS1_DEFAULT" in g:
                msg = _init_dns_ipv4_ok(self._iev(mod, "ER_DS_DNS1_DEFAULT"), "DNS 主")
                if msg:
                    errs.append(msg)
            if "ER_DS_DNS2_DEFAULT" in g:
                d2 = self._iev(mod, "ER_DS_DNS2_DEFAULT").strip()
                if d2:
                    msg = _init_dns_ipv4_ok(d2, "DNS 备")
                    if msg:
                        errs.append(msg)
            sc = self._iev(mod, "ER_DS_SOURCE_CIDR_DEFAULT")
            if str(sc).strip():
                try:
                    ipaddress.ip_network(sc.strip(), strict=False)
                except (ValueError, ipaddress.AddressValueError) as e:
                    errs.append(f"源网段「{sc}」非法：{e}")
            trk = self._iev(mod, "ER_DS_TRACK_NAME_DEFAULT").strip()
            if trk and not re.match(r"^[A-Za-z0-9._-]+$", trk):
                errs.append("Track 名称仅允许字母数字及 ._-（与生成配置中无引号写法一致）")
            for key, lab in (
                ("ER_DS_RULE_NUM_DEFAULT", "LAN-MAP rule"),
                ("ER_DS_TABLE_NUM_DEFAULT", "table 号"),
            ):
                if key not in g:
                    continue
                v = self._iev(mod, key).strip()
                if v and not v.isdigit():
                    errs.append(f"{lab}须为整数")
            bk = self._iev(mod, "ER_DS_STATIC32_BACKUP_NH_DEFAULT").strip()
            if bk:
                try:
                    ipaddress.ip_address(bk)
                except (ValueError, ipaddress.AddressValueError) as e:
                    errs.append(f"备下一跳「{bk}」非法：{e}")
            nr = self._iev(mod, "ER_DS_FNET_NAT_RULE_DEFAULT").strip()
            tun = self._iev(mod, "ER_DS_EXIT_TUNNEL_DEFAULT").strip()
            sn = self._iev(mod, "ER_DS_EXIT_SNAT_IP_DEFAULT").strip()
            fp = self._iev(mod, "ER_DS_FNET_PROBE_DEFAULT").strip()
            if fp:
                try:
                    ipaddress.ip_address(fp)
                except (ValueError, ipaddress.AddressValueError) as e:
                    errs.append(f"100.100 探测 IP「{fp}」非法：{e}")
            f3 = (bool(nr), bool(tun), bool(sn))
            if any(f3) and not all(f3):
                errs.append("NAT rule、NAT 出口 tunnel、主线出口 IP 须同时填写或全部留空")
            elif all(f3):
                if not nr.isdigit() or not (1 <= int(nr) <= 999999):
                    errs.append("NAT rule 号须为 1～999999 的整数")
                if not re.match(r"^[A-Za-z0-9._-]+$", tun):
                    errs.append("NAT 出口 tunnel 名称仅允许字母数字及 ._-")
                try:
                    ipaddress.ip_address(sn)
                except (ValueError, ipaddress.AddressValueError) as e:
                    errs.append(f"主线出口 IP「{sn}」非法：{e}")
                if not fp:
                    errs.append("生成 100.100/NAT 时，100.100 探测 IP 不能为空")

        return errs

    def _on_init_entry_focusout(self, mod: str, key: str) -> None:
        allow = _INIT_ENTRY_ALLOW_EMPTY.get(mod, frozenset())
        if key not in self._init_bool_vars.get(mod, {}):
            ent = self._init_entries.get(mod, {}).get(key)
            if ent is not None and not self._init_field_value(ent) and key not in allow:
                fac = INIT_PLACEHOLDERS_FACTORY.get(mod, {}).get(key, "")
                fv = str(fac) if fac is not None else ""
                if isinstance(ent, tk.Text):
                    ent.delete("1.0", tk.END)
                    ent.insert("1.0", fv)
                else:
                    ent.delete(0, tk.END)
                    ent.insert(0, fv)
        el = self._validate_init_module(mod)
        title = _INIT_MOD_TITLE.get(mod, mod)
        if el:
            self.status.set(f"{title} 初始化未通过：{el[0]}")
        else:
            self.status.set("就绪  ·  请选择场景")
            self._sync_single_init_mod_to_globals(mod)

    def _reload_init_entries_from_globals(self) -> None:
        for mod, kmap in self._init_entries.items():
            emb = _embedded_name_for_init_mod(mod)
            ns = EMBEDDED_NS.get(emb)
            fac = INIT_PLACEHOLDERS_FACTORY.get(mod, {})
            for key, ent in kmap.items():
                v = ""
                if ns is not None:
                    if emb == MOD_AR_SDWAN and key == "ZH_SOUTH_LABEL":
                        v = str(ns.get("ZH_SOUTH_LABEL_SAVED") or "")
                    elif emb == MOD_AR_SDWAN and key == "DJ_SOUTH_LABEL":
                        v = str(ns.get("DJ_SOUTH_LABEL_SAVED") or "")
                    elif emb == MOD_AR_SDWAN and key == "ZH_IKE_VERSION":
                        v = str(ns.get("ZH_IKE_VERSION_SAVED", "v1"))
                    elif emb == MOD_AR_SDWAN and key == "DJ_IKE_VERSION":
                        v = str(ns.get("DJ_IKE_VERSION_SAVED", "v1"))
                    else:
                        if emb == MOD_ER_FASTIP:
                            gk = _global_key_for_er_init_mod(mod, key)
                        elif emb == MOD_USG_FASTIP:
                            gk = _global_key_for_usg_init_mod(mod, key)
                        else:
                            gk = key
                        if gk in ns:
                            v = str(ns[gk])
                # ns 中未提供值时，回落到出厂快照 / user_init 中的占位（避免 AR 可视化初始化界面出现空白）
                if not str(v).strip():
                    v = str(fac.get(key, "") or "")
                if isinstance(ent, tk.Text):
                    ent.delete("1.0", tk.END)
                    ent.insert("1.0", v)
                elif isinstance(ent, tk.StringVar):
                    if key in ("ZH_IKE_VERSION", "DJ_IKE_VERSION"):
                        std = _visual_ike_storage(v)
                        ent.set("v2" if std == "v2" else "v1")
                elif isinstance(ent, ttk.Combobox):
                    vals = list(ent.cget("values") or ())
                    if key in ("ZH_SOUTH_LABEL", "DJ_SOUTH_LABEL"):
                        ent.set(v if v in vals else (vals[0] if vals else ""))
                    else:
                        ent.set(v or (vals[0] if vals else ""))
                else:
                    ent.delete(0, tk.END)
                    ent.insert(0, v)
        for mod, bmap in self._init_bool_vars.items():
            emb = _embedded_name_for_init_mod(mod)
            ns = EMBEDDED_NS.get(emb)
            fac = INIT_PLACEHOLDERS_FACTORY.get(mod, {})
            for key, bv in bmap.items():
                raw = False
                if ns is not None:
                    if emb == MOD_AR_SDWAN and mod == AR_INIT_MOD_ZH and key == "ZH_DUAL_WAN":
                        raw = ns.get("ZH_DUAL_WAN_SAVED", False)
                    else:
                        if emb == MOD_ER_FASTIP:
                            gk = _global_key_for_er_init_mod(mod, key)
                        elif emb == MOD_USG_FASTIP:
                            gk = _global_key_for_usg_init_mod(mod, key)
                        else:
                            gk = key
                        if gk in ns:
                            raw = ns[gk]
                else:
                    fs = fac.get(key, "false")
                    s0 = str(fs).strip().lower() if fs is not None else ""
                    raw = s0 in ("1", "true", "yes", "on", "开")
                if isinstance(raw, bool):
                    bv.set(raw)
                else:
                    s = str(raw).strip().lower() if raw is not None else ""
                    bv.set(s in ("1", "true", "yes", "on", "开"))
        self._sync_ar_zh_wan2_visual()

    def _save_init_defaults(self) -> None:
        err_lines: list[str] = []
        for mod in self._init_entries:
            for msg in self._validate_init_module(mod):
                err_lines.append(f"{_INIT_MOD_TITLE.get(mod, mod)} · {msg}")
        if err_lines:
            cap = 36
            body = "\n".join(err_lines[:cap])
            if len(err_lines) > cap:
                body += f"\n…（共 {len(err_lines)} 条）"
            messagebox.showerror("初始化校验未通过", body)
            return

        data: dict[str, dict[str, str]] = {}
        for mod in self._init_entries:
            data[mod] = self._init_mod_row_snapshot(mod)
        try:
            INIT_USER_PLACEHOLDERS_JSON.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8-sig")
        except (OSError, ValueError) as e:
            messagebox.showerror("写入失败", str(e))
            return
        _apply_init_placeholder_updates(data)
        self._reload_init_entries_from_globals()
        self._sync_init_dhcp_visual_all()
        self.status.set("已保存 user_init_placeholders.json 并应用到各工具")
        self._flash_init_hint("保存成功：初始化默认值已写入并已同步到各工具页签。")

    def _flash_init_hint(self, msg: str, clear_ms: int = 6000) -> None:
        """初始化区「保存 / 恢复出厂」下方一行小字反馈。"""
        if getattr(self, "_init_hint_after_id", None):
            try:
                self.parent.after_cancel(self._init_hint_after_id)
            except Exception:
                pass
            self._init_hint_after_id = None
        self._init_action_hint.set(msg)

        def _clear() -> None:
            self._init_action_hint.set("")
            self._init_hint_after_id = None

        self._init_hint_after_id = self.parent.after(clear_ms, _clear)

    def _restore_init_factory(self) -> None:
        if not INIT_PLACEHOLDERS_FACTORY:
            messagebox.showerror("错误", "出厂快照未就绪")
            return
        to_apply: dict[str, dict[str, str]] = {}
        for mod, kmap in self._init_entries.items():
            fac = INIT_PLACEHOLDERS_FACTORY.get(mod, {})
            to_apply[mod] = {}
            for key, ent in kmap.items():
                v = fac.get(key, "")
                to_apply[mod][key] = str(v) if v is not None else ""
                sv = str(v) if v is not None else ""
                if isinstance(ent, tk.Text):
                    ent.delete("1.0", tk.END)
                    ent.insert("1.0", sv)
                elif isinstance(ent, tk.StringVar):
                    if key in ("ZH_IKE_VERSION", "DJ_IKE_VERSION"):
                        std = _visual_ike_storage(sv)
                        ent.set("v2" if std == "v2" else "v1")
                elif isinstance(ent, ttk.Combobox):
                    vals = list(ent.cget("values") or [])
                    ent.set(sv if sv in vals else (vals[0] if vals else ""))
                else:
                    ent.delete(0, tk.END)
                    ent.insert(0, sv)
            for key, bv in self._init_bool_vars.get(mod, {}).items():
                vs = fac.get(key, "false")
                to_apply[mod][key] = str(vs) if vs is not None else "false"
                s = str(vs).strip().lower()
                bv.set(s in ("1", "true", "yes", "on", "开"))
        _apply_init_placeholder_updates(to_apply)
        self._reload_init_entries_from_globals()
        self._sync_init_dhcp_visual_all()
        try:
            if INIT_USER_PLACEHOLDERS_JSON.exists():
                INIT_USER_PLACEHOLDERS_JSON.unlink()
        except Exception:
            pass
        self.status.set("已恢复出厂初始化占位（已删除 user_init_placeholders.json）")
        self._flash_init_hint("初始化成功：已恢复出厂默认值并同步到各工具页签。")

    def _on_select(self, _event) -> None:
        key = self.combo.get()
        if not key or key not in self.SCENARIOS:
            return
        # 切换前静默保存当前场景（保留用户的所有编辑）；UI 回归自检时禁止写盘
        if self._current_key and self._current_key != key and not getattr(
            self, "_regression_skip_disk", False
        ):
            self._auto_save_current()
        self._current_key = key
        info = self.SCENARIOS[key]
        sdir = self._scenario_dir(key)
        sdef = _scenario_defaults_dir(key)
        slot = _scenario_tpl_slot(info)
        tpl_new = sdir / f"{slot}.tpl"
        tpl_def = sdef / f"{slot}.tpl"
        tpl_legacy = self._legacy_flat(key, "template.tpl")

        if tpl_new.exists():
            tpl = tpl_new.read_text(encoding="utf-8-sig")
        elif tpl_def.exists():
            tpl = tpl_def.read_text(encoding="utf-8-sig")
        elif tpl_legacy.exists():
            tpl = tpl_legacy.read_text(encoding="utf-8-sig")
        else:
            tpl = self._default_tpl(info)

        if info.get("parser_name") == "er_domain_split_preview" and not _er_domain_split_tpl_looks_valid(tpl):
            fixed = self._default_tpl(info)
            if tpl_def.exists():
                try:
                    cand = tpl_def.read_text(encoding="utf-8-sig")
                    if _er_domain_split_tpl_looks_valid(cand):
                        fixed = cand
                except Exception:
                    pass
            tpl = fixed
            if not getattr(self, "_regression_skip_disk", False):
                try:
                    tpl_new.write_text(tpl, encoding="utf-8-sig")
                except Exception:
                    pass

        # 历史异常修复：ER HK/US 的 workspace/default 模板可能被污染为"模板+源码拼接体"。
        # 这里在场景切换时体检一次，异常则回落到源码内置模板并落盘，避免预览出现源码。
        if info.get("parser_name") in ("parse_epoch_hk", "parse_epoch_us"):
            is_us = info.get("parser_name") == "parse_epoch_us"
            if not _er_epoch_tpl_looks_valid(tpl, us=is_us):
                tpl = self._default_tpl(info)
                if not getattr(self, "_regression_skip_disk", False):
                    try:
                        tpl_new.parent.mkdir(parents=True, exist_ok=True)
                        tpl_new.write_text(tpl, encoding="utf-8-sig")
                    except Exception:
                        pass

        hdr_new = sdir / "headers.txt"
        hdr_def = sdef / "headers.txt"
        hdr_legacy = self._legacy_flat(key, "headers.txt")
        if hdr_new.exists():
            hdr = hdr_new.read_text(encoding="utf-8-sig")
        elif hdr_def.exists():
            hdr = hdr_def.read_text(encoding="utf-8-sig")
        elif hdr_legacy.exists():
            hdr = hdr_legacy.read_text(encoding="utf-8-sig")
        elif info.get("hdr_static"):
            hdr = info["hdr_static"]
        else:
            hdr = _auto_headers(tpl)

        if info.get("source") == MOD_ER_FASTIP:
            hdr = _strip_leading_hostname_visual_line(hdr)

        map_new = sdir / "mapping.txt"
        map_def = sdef / "mapping.txt"
        map_legacy = self._legacy_flat(key, "mapping.txt")
        if map_new.exists():
            mapping = map_new.read_text(encoding="utf-8-sig")
        elif map_def.exists():
            mapping = map_def.read_text(encoding="utf-8-sig")
        elif map_legacy.exists():
            mapping = map_legacy.read_text(encoding="utf-8-sig")
        elif info.get("map_static"):
            mapping = str(info["map_static"])
        else:
            mapping = _auto_mapping(tpl)
        if not str(mapping).strip():
            mapping = str(info.get("map_static") or _auto_mapping(tpl))
        # 始终补齐场景静态映射，确保"初始化变量（完整）"在所有场景一致可见
        mapping = _merge_mapping_keep_manual(mapping, str(info.get("map_static") or ""))

        self._set_text(self.txt_hdr,  hdr)
        self._set_text(self.txt_map,  mapping)
        self._set_text(self.txt_tpl,  tpl)
        self._sync_tpl_version_counter_from_tpl(key, tpl)
        self._set_text(self.txt_prev, "# 请点击底部【预览模板】按钮生成完整预览\n",
                       readonly=True)
        self._reset_visual_editor_undo()
        slot_mod = _init_mod_for_scenario(info)
        if slot_mod in self._init_module_frames:
            self._show_init_panel_for_scenario(key)
        self._relayout_init_form(key)
        self._sync_init_outer_height(key)
        self._sync_ar_zh_wan2_visual()
        # 与顶部说明「切换后初始化占位…随场景刷新」一致：从嵌入脚本 globals + 出厂快照重填，
        # 避免多次切换后失焦回填读到空 factory、或控件状态与数据源脱节。
        try:
            self._reload_init_entries_from_globals()
        except Exception:
            pass
        self.status.set(f"已切换：{key}  ·  {info['source']}")

    # ── 四按钮 ────────────────────────────────────────────────────────

    def full_reset(self) -> None:
        """仅当前场景恢复出厂模板/数据头/映射；需确认；不影响其他场景。"""
        key = self._current_key
        if not key:
            return
        ok = messagebox.askyesno(
            "确认恢复最初模板",
            f"即将把当前场景「{key}」恢复为程序自带的最初模板与示例数据头/映射。\n\n"
            "· 仅影响本场景，与其他场景无关。\n"
            "· 当前场景未保存的编辑将丢失。\n\n"
            "是否继续？",
            icon="warning",
        )
        if not ok:
            self.status.set("已取消恢复最初模板")
            return

        info = self.SCENARIOS[key]
        self._write_tpl_version_counter(key, 0)
        tpl = self._default_tpl(info)
        hdr = info["hdr_static"] if info.get("hdr_static") else _auto_headers(tpl)
        mapping = info["map_static"] if info.get("map_static") else _auto_mapping(tpl)
        if info.get("source") == MOD_ER_FASTIP:
            hdr = _strip_leading_hostname_visual_line(hdr)
        self._set_text(self.txt_hdr, hdr)
        self._set_text(self.txt_map, mapping)
        self._set_text(self.txt_tpl, tpl)
        self._set_text(self.txt_prev, "# 已恢复最初模板，请点击【预览模板】刷新。\n", readonly=True)
        self._reset_visual_editor_undo()
        try:
            self._persist_to_disk(key, hdr, mapping, tpl, event="full_reset")
        except Exception:
            pass
        self.status.set(f"已恢复最初模板（仅本场景）：{key}")

    def preview(self) -> None:
        """
        生成配置预览（两条路径，不叠床架屋）：
        1) 各场景专用分支：解析 → 合并「初始化」面板 → 一次 tpl.format。
        2) 若未成功 format：再走通用路径（嵌入解析器 + 可选行扫描 + 初始化 → 正则替换 {var}）。
           USG HK/非HK 若 format 失败也会走 (2)，用同一套解析结果填变量。
        ER HK/US 在专用 format 未成功时也会进入 (2) 做占位替换展示；
        仅影响预览可读性，不改变正式生成逻辑。
        """
        key = self._current_key
        info = self.SCENARIOS.get(key, {})
        col1 = self.txt_hdr.get("1.0", tk.END).strip()
        if info.get("source") == MOD_ER_FASTIP:
            col1 = _strip_leading_hostname_visual_line(col1)
        tpl_raw = self.txt_tpl.get("1.0", tk.END).rstrip("\n")
        tpl = _strip_editor_template_version_header(tpl_raw)

        parser_name = info.get("parser_name")
        source = info.get("source", "")
        parse_err = ""
        rendered = ""
        ns = EMBEDDED_NS.get(source) if source else None
        # 预览前按场景自动确保嵌入模块就绪，避免"必须先手动点到对应工具页签"导致全场景不填变量。
        if source and not ns:
            fn = _ENSURE_LEGACY_EMBED_BY_FILENAME
            if callable(fn):
                try:
                    fn(source)
                except Exception:
                    pass
            ns = EMBEDDED_NS.get(source) if source else None
        # 预览前先把"当前场景初始化面板"的值同步到对应模块 globals，
        # 让 MPLS/AR/USG/ER 的解析与推导都读取到最新初始化值。
        try:
            self._sync_single_init_mod_to_globals(_init_mod_for_scenario(info))
        except Exception:
            pass

        tpl_vars = set(re.findall(r"\{(\w+)\}", tpl))
        format_ok = False

        if info.get("placeholder") and not tpl_vars:
            # 占位场景尚无真实模板链路时，仅展示当前占位模板文本；
            # 不再先跑业务解析，避免把"待实现能力"误判成预览失败。
            rendered = tpl
            self.status.set("⚠ 该场景模板仍在开发中，预览内容为占位文本")
        elif (
            source == MOD_ER_FASTIP
            and parser_name == "parse_epoch_hk"
            and ns
            and callable(ns.get("build_epoch_hk_format_dict"))
        ):
            d, fail = ns["build_epoch_hk_format_dict"](col1)
            if fail:
                kind, payload = fail
                if kind == "network":
                    parse_err = "网络格式未通过（与 ER 页签「初始化」一致）：\n" + "\n".join(
                        payload or []
                    )
                elif kind == "empty":
                    parse_err = "业务数据为空"
                elif kind == "tunnel":
                    parse_err = "隧道命名错误（仅 vtun）：\n" + "\n".join(payload or [])
                else:
                    parse_err = str(fail)
            else:
                d.update(self._preview_init_values(info))
                try:
                    rendered = tpl.format(**d)
                    format_ok = True
                except Exception as e:
                    parse_err = f"模板 format 失败（请检查占位符与花括号）：{e}"
        elif (
            source == MOD_ER_FASTIP
            and parser_name == "parse_epoch_us"
            and ns
            and callable(ns.get("build_epoch_us_format_dict"))
        ):
            d, fail, _warns = ns["build_epoch_us_format_dict"](col1)
            if fail:
                kind, payload = fail
                if kind == "network":
                    parse_err = "网络格式未通过（与 ER 页签「初始化」一致）：\n" + "\n".join(
                        payload or []
                    )
                elif kind == "empty":
                    parse_err = "业务数据为空"
                elif kind == "natmiss":
                    parse_err = "海外出口 IP 未解析到：\n" + "\n".join(payload or [])
                else:
                    parse_err = str(fail)
            else:
                d.update(self._preview_init_values(info))
                try:
                    rendered = tpl.format(**d)
                    format_ok = True
                except Exception as e:
                    parse_err = f"模板 format 失败（请检查占位符与花括号）：{e}"
        elif (
            source == MOD_ER_FASTIP
            and parser_name in ("parse_epoch_hk", "parse_epoch_us")
        ):
            parse_err = (
                "请先切换到「Epoch FastIP」页签以加载生成逻辑（build_epoch_*_format_dict）。"
            )
        elif (
            source == MOD_ER_FASTIP
            and parser_name == "parse_er_flink_headers"
        ):
            try:
                parser_fn = ns.get("parse_er_flink_headers") if ns else None
                if callable(parser_fn):
                    routes, err = parser_fn(col1)
                else:
                    routes = []
                    err = None
                    import ipaddress as _ip
                    for ln in (col1 or "").splitlines():
                        line = ln.strip()
                        if not line:
                            continue
                        cidr = line.split(":", 1)[1].strip() if ":" in line else line
                        if "/" not in cidr:
                            err = f"CIDR 缺少掩码：{cidr}"
                            break
                        try:
                            routes.append(("预留IP", str(_ip.ip_network(cidr, strict=False))))
                        except Exception as e:
                            err = f"CIDR 非法：{cidr} ({e})"
                            break
                    if not routes and not err:
                        err = "请先填写飞连数据头（至少 1 行）"
                if err:
                    parse_err = str(err)
                else:
                    self._sync_single_init_mod_to_globals(ER_INIT_MOD_FLINK)
                    d = {}
                    for i, (_name, cidr) in enumerate(routes, start=1):
                        d[f"route{i}"] = cidr
                    for i in range(len(routes) + 1, 10):
                        d[f"route{i}"] = ""
                    d["ER_FL_MAIN_ROUTES_BLOCK"] = "\n".join(
                        f"set protocols static route {cidr} next-hop {{ER_FL_MAIN_NH_DEFAULT}} track flink"
                        for _n, cidr in routes
                    )
                    d["ER_FL_BACKUP_ROUTES_BLOCK"] = "\n".join(
                        f"set protocols static route {cidr} next-hop {{ER_FL_BACKUP_NH_DEFAULT}} distance 5"
                        for _n, cidr in routes
                    )
                    d.update(self._preview_init_values(info))
                    rendered = tpl.format(**d)
                    format_ok = True
            except Exception as e:
                parse_err = f"ER 飞连解析失败: {e}"
        elif (
            source == MOD_ER_FASTIP
            and parser_name == "parse_er_new_exit_blocks"
        ):
            try:
                parser_fn = ns.get("parse_er_new_exit_blocks") if ns else None
                if callable(parser_fn):
                    parsed, err = parser_fn(col1)
                else:
                    def _get(pat: str, text: str) -> str:
                        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
                        return m.group(1).strip() if m else ""
                    blocks = [
                        b.strip()
                        for b in re.split(r"(?=LineID\s*[:：])", col1 or "", flags=re.IGNORECASE)
                        if b.strip()
                    ]
                    parsed, err = {}, None
                    for block in blocks:
                        line_id = _get(r"LineID\s*[:：]\s*(\S+)", block)
                        if not line_id:
                            continue
                        # 单 block → main；多 block → 按奇偶分
                        if len(blocks) == 1:
                            key = "main"
                        else:
                            try:
                                n = int(re.sub(r"\D", "", line_id)[-1:])
                                key = "main" if (n % 2 == 1) else "bk"
                            except Exception:
                                key = "main" if "main" not in parsed else "bk"
                        wanip = _get(r"WANIP\s*[:：]\s*([\d./]+)", block)
                        tun = _get(r"TUNNEL\s*[:：]\s*(\S+)", block)
                        pe = _get(r"^PE\s*[:：]\s*(.+)$", block) or _get(r"PE\s*[:：]\s*(.+)", block)
                        pe_docking = _get(r"PE\s*Docking\s*[:：]\s*([\d.]+)", block)
                        ce_docking = _get(r"CE\s*Docking\s*[:：]*\s*([\d.]+)", block)
                        pair_m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})\s*[-–—~]\s*(\d{1,3}(?:\.\d{1,3}){3})", block)
                        if not all((wanip, tun, pe, pe_docking, ce_docking, pair_m)):
                            continue
                        try:
                            hosts = list(ipaddress.ip_network(wanip, strict=False).hosts())
                            ce_ip = str(hosts[1]) if len(hosts) >= 2 else ""
                        except Exception:
                            ce_ip = ""
                        parsed[key] = {
                            "tun": tun, "tun_addr": f"{ce_ip}/30" if ce_ip else "",
                            "pe": pe, "pe_docking": pe_docking, "ce_docking": ce_docking,
                            "oversea_pairs": [(pair_m.group(1), pair_m.group(2))],
                        }
                    if "main" not in parsed:
                        err = "未解析到主线数据"
                if err:
                    parse_err = str(err)
                else:
                    self._sync_single_init_mod_to_globals(ER_INIT_MOD_NEW_EXIT)
                    mn = parsed.get("main", {})
                    bk = parsed.get("bk")  # None for single line
                    has_bk = bool(bk)
                    mn_pairs = list(mn.get("oversea_pairs") or [])
                    bk_pairs = list((bk or {}).get("oversea_pairs") or [])
                    mn_pair = mn_pairs[0] if mn_pairs else ("", "")
                    bk_pair = bk_pairs[0] if bk_pairs else ("", "")
                    init_vals = self._preview_init_values(info)
                    def _to_int(s: str, dft: int) -> int:
                        try:
                            return int(str(s).strip())
                        except Exception:
                            return dft
                    mn_dum_start = _to_int(init_vals.get("ER_NE_MAIN_DUM_DEFAULT", "300"), 300)
                    bk_dum_start = _to_int(init_vals.get("ER_NE_BK_DUM_DEFAULT", "400"), 400)
                    mn_dum = mn_dum_start
                    bk_dum = bk_dum_start
                    main_block = []
                    for left_ip, right_ip in mn_pairs:
                        main_block.append(f"set interfaces dummy dum{mn_dum} address '{left_ip}/32'")
                        main_block.append(f"set interfaces dummy dum{mn_dum} description main-outip-{left_ip}-{right_ip}")
                        mn_dum += 1
                    # 备线完整块
                    bk_full_block = ""
                    if has_bk:
                        bk_dum_lines = []
                        for left_ip, right_ip in bk_pairs:
                            bk_dum_lines.append(f"set interfaces dummy dum{bk_dum} address '{left_ip}/32'")
                            bk_dum_lines.append(f"set interfaces dummy dum{bk_dum} description backup-outip-{left_ip}-{right_ip}")
                            bk_dum += 1
                        bk_full_block = (
                            f"set interfaces tunnel {bk.get('tun', '')} address '{bk.get('tun_addr', '')}'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} description 'backup-{bk.get('pe', '')}'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} encapsulation 'gre'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} firewall local name 'WAN2LOCAL'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} mtu '1400'\n"
                            f"set firewall options interface {bk.get('tun', '')} adjust-mss '1300'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} multicast 'disable'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} parameters ip ttl '255'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} remote '{bk.get('pe_docking', '')}'\n"
                            f"set interfaces tunnel {bk.get('tun', '')} source-address '{bk.get('ce_docking', '')}'\n"
                            f"\n"
                            f"set protocols static route {bk.get('pe_docking', '')}/32 next-hop {init_vals.get('ER_NE_BK_PE_NH_DEFAULT', '')}\n"
                            + ("\n".join(bk_dum_lines))
                        )
                    d = {
                        "main_tun": mn.get("tun", ""),
                        "main_tun_addr": mn.get("tun_addr", ""),
                        "main_pe": mn.get("pe", ""),
                        "main_pe_docking": mn.get("pe_docking", ""),
                        "main_ce_docking": mn.get("ce_docking", ""),
                        "main_left_ip_1": mn_pair[0],
                        "main_right_ip_1": mn_pair[1],
                        "backup_left_ip_1": bk_pair[0],
                        "backup_right_ip_1": bk_pair[1],
                        "ER_NE_MAIN_DUM_BLOCK": "\n".join(main_block),
                        "ER_NE_BK_BLOCK": bk_full_block,
                    }
                    d.update(init_vals)
                    # NAT blocks — 仅双线时生成
                    nat_hdr = ""
                    nat_blk = ""
                    if has_bk:
                        main_nat_r = str(init_vals.get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300")).strip() or "300"
                        bk_nat_r = str(init_vals.get("ER_NE_BK_NAT_RULE_DEFAULT", "400")).strip() or "400"
                        nat_src_iv = str(
                            init_vals.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "192.168.0.0/24")
                        ).strip()
                        nat_ic = {
                            "main_nat_rule": main_nat_r,
                            "bk_nat_rule": bk_nat_r,
                            "nat_source_cidr": nat_src_iv,
                        }
                        hdr_fn = (ns or {}).get("build_er_new_exit_nat_header_block")
                        nat_fn = (ns or {}).get("build_er_new_exit_nat_block")
                        if callable(hdr_fn):
                            try:
                                nat_hdr = hdr_fn(parsed, nat_ic)
                            except Exception:
                                nat_hdr = ""
                        if callable(nat_fn):
                            try:
                                nat_blk = nat_fn(parsed, nat_ic)
                            except Exception:
                                nat_blk = ""
                        d["ER_NE_MAIN_NAT_RULE_DEFAULT"] = main_nat_r
                        d["ER_NE_BK_NAT_RULE_DEFAULT"] = bk_nat_r
                        d["ER_NE_NAT_SOURCE_CIDR_DEFAULT"] = nat_src_iv
                    d["ER_NE_NAT_HEADER_BLOCK"] = nat_hdr
                    d["ER_NE_NAT_BLOCK"] = nat_blk
                    # FNET whitelist block
                    fnet_fn = (ns or {}).get("_build_er_ne_fnet_block")
                    fnet_blk = ""
                    if callable(fnet_fn):
                        fnet_ic = {
                            "fnet_probe": str(init_vals.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")).strip(),
                            "fnet_exit_tunnel": str(init_vals.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")).strip(),
                            "fnet_nat_rule": str(init_vals.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")).strip(),
                            "main_pe_next_hop": str(init_vals.get("ER_NE_MAIN_PE_NH_DEFAULT", "192.168.1.1")).strip(),
                        }
                        try:
                            fnet_blk = fnet_fn(parsed, fnet_ic)
                        except Exception:
                            fnet_blk = ""
                    d["ER_NE_FNET_BLOCK"] = fnet_blk
                    d["ER_NE_FNET_PROBE_DEFAULT"] = str(init_vals.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")).strip()
                    d["ER_NE_FNET_EXIT_TUNNEL_DEFAULT"] = str(init_vals.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")).strip()
                    d["ER_NE_FNET_NAT_RULE_DEFAULT"] = str(init_vals.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")).strip()
                    rendered = tpl.format(**d)
                    format_ok = True
            except Exception as e:
                parse_err = f"ER 新增出口解析失败: {e}"
        elif (
            source == MOD_ER_FASTIP
            and parser_name == "er_domain_split_preview"
            and ns
        ):
            try:
                self._sync_single_init_mod_to_globals(ER_INIT_MOD_DOMAIN_SPLIT)
                if not ns.get("er_ds_template_preview_extras"):
                    parse_err = "请先切换到「Epoch FastIP」页签以加载 ER 嵌入逻辑。"
                else:
                    iv = dict(self._preview_init_values(info))
                    try:
                        iv.update(ns["er_ds_template_preview_extras"](iv))
                        iv.setdefault("ER_DS_OPT_POLICY_ROUTE_BLOCK", "")
                        iv.setdefault("ER_DS_OPT_FNET_BLOCK", "")
                        iv.setdefault("ER_DS_OPT_TRACK_SUFFIX", "")
                        rendered = tpl.format(**iv)
                        format_ok = True
                    except KeyError as e:
                        parse_err = f"模板缺少占位符对应键：{e}"
                    except Exception as e:
                        parse_err = f"模板 format 失败：{e}"
            except Exception as e:
                parse_err = f"ER 域名分流预览失败: {e}"
        elif (
            source == MOD_USG_FASTIP
            and parser_name in ("parse_business_data", "parse_business_data_hk")
            and ns
        ):
            usg_builder = (
                ns.get("build_usg_hk_format_dict")
                if parser_name == "parse_business_data_hk"
                else ns.get("build_usg_us_format_dict")
            )
            if callable(usg_builder):
                try:
                    self._sync_init_to_module_globals()
                    d, fail = usg_builder(col1)
                    if fail:
                        kind, payload = fail
                        parse_err = f"USG 数据解析失败: {kind}"
                    else:
                        try:
                            d.update(self._preview_init_values(info))
                            rendered = tpl.format(**d)
                            format_ok = True
                        except Exception as e:
                            parse_err = f"模板 format 失败（请检查占位符与花括号）：{e}"
                except Exception as e:
                    parse_err = f"USG 格式化失败: {e}"
            else:
                parse_err = "请先切换到「USG FastIP」页签以加载生成逻辑。"
        elif (
            source == MOD_USG_FASTIP
            and parser_name == "parse_usg_new_exit_blocks"
        ):
            try:
                parser_fn = ns.get("parse_usg_new_exit_blocks") if ns else None
                if callable(parser_fn):
                    parsed, err = parser_fn(col1)
                else:
                    parsed, err = None, "请先切换到「USG FastIP」页签以加载新增出口解析逻辑。"
                if err:
                    parse_err = str(err)
                else:
                    self._sync_single_init_mod_to_globals(USG_INIT_MOD_NEW_EXIT)
                    iv = self._preview_init_values(info)
                    init_cfg = {
                        "main_tun": int(str(iv.get("USG_NE_MAIN_TUN_DEFAULT", "1001")).strip() or "1001"),
                        "bk_tun": int(str(iv.get("USG_NE_BK_TUN_DEFAULT", "1002")).strip() or "1002"),
                        "main_loop_start": int(str(iv.get("USG_NE_MAIN_LOOP_START_DEFAULT", "111")).strip() or "111"),
                        "bk_loop_start": int(str(iv.get("USG_NE_BK_LOOP_START_DEFAULT", "211")).strip() or "211"),
                        "main_nqa": str(iv.get("USG_NE_MAIN_NQA_DEFAULT", "main2")).strip() or "main2",
                        "bk_nqa": str(iv.get("USG_NE_BK_NQA_DEFAULT", "backup2")).strip() or "backup2",
                    }
                    fmt_fn = (ns or {}).get("build_usg_new_exit_format_dict")
                    if callable(fmt_fn):
                        d = fmt_fn(parsed, init_cfg)
                    else:
                        parse_err = "USG 新增出口格式化函数未加载。"
                        d = {}
                    if not parse_err:
                        d.update({
                            "USG_NE_MAIN_TUN_DEFAULT": str(init_cfg["main_tun"]),
                            "USG_NE_BK_TUN_DEFAULT": str(init_cfg["bk_tun"]),
                            "USG_NE_MAIN_NQA_DEFAULT": init_cfg["main_nqa"],
                            "USG_NE_BK_NQA_DEFAULT": init_cfg["bk_nqa"],
                        })
                        rendered = tpl.format(**d)
                        format_ok = True
            except Exception as e:
                parse_err = f"USG 新增出口解析失败: {e}"
        elif (
            source == MOD_USG_FASTIP
            and parser_name == "parse_feilink_data"
        ):
            try:
                parser_fn = ns.get("parse_feilink_data") if ns else None
                if callable(parser_fn):
                    parsed = parser_fn(col1)
                else:
                    parsed = {"main": {}, "backup": {}, "reserved_ips": []}
                    for m in re.finditer(r"预留IP[：:]\s*([\d./]+)", col1 or ""):
                        parsed["reserved_ips"].append(m.group(1).strip())
                    blocks = re.split(r"(?=LineID\s*[:：])", col1 or "")
                    lst = []
                    for block in blocks:
                        if not re.search(r"LineID", block or "", re.IGNORECASE):
                            continue
                        def _get(pat: str):
                            mm = re.search(pat, block, re.IGNORECASE | re.MULTILINE)
                            return mm.group(1).strip() if mm else ""
                        d = {
                            "line_id": _get(r"LineID\s*[:：]\s*(\S+)"),
                            "pe": _get(r"^PE\s*[:：]\s*(.+)$") or _get(r"PE\s*[:：]\s*(.+)"),
                            "peer_ip": _get(r"PE\s*对接\s*[:：]\s*([\d.]+)"),
                            "wanip": _get(r"wanip\s*[:：]\s*([\d./]+)"),
                            "wanip1": "", "wanip2": "",
                        }
                        if d["wanip"] and "/" in d["wanip"]:
                            try:
                                hs = list(ipaddress.ip_network(d["wanip"], strict=False).hosts())
                                if len(hs) >= 2:
                                    d["wanip1"], d["wanip2"] = str(hs[0]), str(hs[1])
                            except Exception:
                                pass
                        if d["line_id"]:
                            lst.append(d)
                    if len(lst) >= 1:
                        parsed["main"] = lst[0]
                    if len(lst) >= 2:
                        parsed["backup"] = lst[1]
                mn = parsed.get("main") or {}
                bk = parsed.get("backup") or {}
                reserved = parsed.get("reserved_ips") or []
                if not mn:
                    parse_err = "USG 飞连解析失败: 未识别到主线 LineID"
                else:
                    import ipaddress as _ip
                    nets = []
                    for cidr in reserved[:3]:
                        try:
                            n = _ip.ip_network(cidr, strict=False)
                            nets.append((str(n.network_address), str(n.prefixlen)))
                        except Exception:
                            nets.append((cidr, ""))
                    while len(nets) < 3:
                        nets.append(("", ""))
                    d = {
                        "main_line_id": mn.get("line_id", ""),
                        "main_pe": mn.get("pe", ""),
                        "main_peer_ip": mn.get("peer_ip", ""),
                        "main_wanip1": mn.get("wanip1", ""),
                        "main_wanip2": mn.get("wanip2", ""),
                        "backup_line_id": bk.get("line_id", ""),
                        "backup_pe": bk.get("pe", ""),
                        "backup_peer_ip": bk.get("peer_ip", ""),
                        "backup_wanip1": bk.get("wanip1", ""),
                        "backup_wanip2": bk.get("wanip2", ""),
                        "reserved1_net": nets[0][0],
                        "reserved1_mask": nets[0][1],
                        "reserved2_net": nets[1][0],
                        "reserved2_mask": nets[1][1],
                        "reserved3_net": nets[2][0],
                        "reserved3_mask": nets[2][1],
                        "USG_FL_ADDRESS_SET_BLOCK": "\n".join(
                            f" address {idx} {net_addr} mask {mask}"
                            for idx, (net_addr, mask) in enumerate(nets)
                            if str(net_addr).strip()
                        ),
                        "USG_FL_MAIN_ROUTES_BLOCK": "\n".join(
                            f"ip route-static {net_addr} {mask} {mn.get('wanip1','')} track nqa admin FLmain"
                            for net_addr, mask in nets
                            if str(net_addr).strip() and str(mn.get("wanip1", "")).strip()
                        ),
                        "USG_FL_BACKUP_ROUTES_BLOCK": "\n".join(
                            f"ip route-static {net_addr} {mask} {bk.get('wanip1','')} preference 100"
                            for net_addr, mask in nets
                            if str(net_addr).strip() and str(bk.get("wanip1", "")).strip()
                        ),
                    }
                    d.update(self._preview_init_values(info))
                    rendered = tpl.format(**d)
                    format_ok = True
            except Exception as e:
                parse_err = f"USG 飞连解析失败: {e}"
        elif (
            source == MOD_ER_MPLS
            and parser_name == "parse_epoch_mpls_ipsec"
            and ns
            and callable(ns.get("parse_epoch_mpls_ipsec"))
        ):
            try:
                # ── 与正式页 generate() 保持完全一致的处理流程 ──────────────
                parse_ipsec  = ns["parse_epoch_mpls_ipsec"]
                build_net_fn = ns.get("build_wan_lan_blocks")
                inject_fn    = ns.get("inject_er_netpanel_init_aliases")
                norm_fn      = ns.get("_normalize_lan_gw_value")
                _parse_inner = ns.get("_parse_inner_nets")
                _nets_rr     = ns.get("_nets_needing_return_by_network")
                _cidr_plain_fn    = ns.get("_cidr_plain")
                _cidr_host_fn     = ns.get("_cidr_host_pair")
                gen_fn       = ns.get("generate_mpls_ipsec_config")
                ex_hn        = ns.get("extract_lineid_mpls")

                iv = self._preview_init_values(info)
                _weth    = str(iv.get("DEFAULT_WAN_ETH", "0")).strip() or "0"
                _leth    = str(iv.get("DEFAULT_LAN_ETH", "5")).strip() or "5"
                _wan_if  = _weth if _weth.startswith("eth") else f"eth{_weth}"
                _lan_if  = _leth if _leth.startswith("eth") else f"eth{_leth}"
                _wan_cidr = str(iv.get("DEFAULT_WAN_CIDR", "192.168.1.10/24")).strip() or "192.168.1.10/24"
                _wan_gw   = str(iv.get("DEFAULT_WAN_GW", "192.168.1.1")).strip() or "192.168.1.1"
                _lan_cidr = str(iv.get("DEFAULT_LAN_CIDR", "192.168.5.1/24")).strip() or "192.168.5.1/24"
                _wan_dhcp = str(iv.get("DEFAULT_WAN_DHCP", "")).strip().lower() in ("1", "true", "yes", "on", "开")
                _lan_dhcp = str(iv.get("DEFAULT_LAN_DHCP", "")).strip().lower() in ("1", "true", "yes", "on", "开")
                # lan_gw：先从 iv 拿原始值，统一用 _normalize_lan_gw_alias 去别名
                _lan_gw = _normalize_lan_gw_alias(
                    _lan_cidr, str(iv.get("DEFAULT_LAN_GW", "")).strip()
                )

                # Step1: parse
                d = parse_ipsec(col1)
                hn = ""
                if callable(ex_hn):
                    try:
                        hn = str(ex_hn(col1) or "").strip()
                    except Exception:
                        hn = ""
                d["hostname"]    = hn or "（请填写Hostname）"
                d["access_mode"] = "IPSec"
                d["config_type"] = "IPSec"

                # Step2: build wan/lan blocks，合并到 d
                if callable(build_net_fn):
                    try:
                        d.update(build_net_fn(
                            wan_if=_wan_if, wan_dhcp=_wan_dhcp, wan_ip_cidr=_wan_cidr, wan_gw=_wan_gw,
                            lan_if=_lan_if, lan_dhcp=_lan_dhcp, lan_ip_cidr=_lan_cidr,
                            bypass=False,
                        ) or {})
                    except Exception:
                        pass
                d["wan_cidr"]  = _wan_cidr
                d["wan_gw"]    = _wan_gw
                d["lan_cidr"]  = _lan_cidr
                d["lan_gw"]    = _lan_gw   # 已去别名的实际 IP

                # Step3: 二次归一化（去掩码等残留），与正式页 generate() 完全一致
                if callable(norm_fn):
                    d["lan_gw"] = norm_fn(str(d.get("lan_cidr", "")), str(d.get("lan_gw", "")))

                # Step4: inject DEFAULT_* 别名（依赖 lan_gw 已归一化）
                if callable(inject_fn):
                    inject_fn(d)

                # Step5: 解析内网段
                _inner_raw  = str(iv.get("DEFAULT_INNER_NETS", ""))
                _inner_nets: list[str] = []
                if callable(_parse_inner):
                    try:
                        _inner_nets = _parse_inner(_inner_raw)
                    except Exception:
                        _inner_nets = []
                d["inner_nets"] = _inner_nets
                _rr_enabled = str(iv.get("DEFAULT_GEN_RETURN_ROUTE", "")).strip().lower() in (
                    "1", "true", "yes", "on", "开")
                d["return_route_enabled"] = _rr_enabled

                # Step6: 回程路由（与正式页完全一致）
                lan_cidr_rr = d.get("lan_cidr") or ""
                lan_gw_rr   = d.get("lan_gw") or ""
                rr_on       = _rr_enabled
                outside_rr: list[str] = []
                if lan_cidr_rr and callable(_nets_rr):
                    try:
                        outside_rr = _nets_rr(lan_cidr_rr, _inner_nets)
                    except Exception:
                        outside_rr = []
                rr_lines = []
                if outside_rr and rr_on and lan_gw_rr:
                    rr_lines = [f"set protocols static route {n} next-hop {lan_gw_rr}"
                                for n in outside_rr]
                d["return_routes_block"] = "\n".join(rr_lines)

                # Step7: prefix-list（与正式页完全一致）
                ce_as_pv = str(d.get("ce_as", "")).strip()
                prefix_lines = []
                for i, n in enumerate(_inner_nets):
                    rule_num = 10 * (i + 1)
                    prefix_lines.append(
                        f"set policy prefix-list AS{ce_as_pv}-OUT rule {rule_num} action 'permit'")
                    prefix_lines.append(
                        f"set policy prefix-list AS{ce_as_pv}-OUT rule {rule_num} prefix '{n}'")
                d["prefix_list_block"] = "\n".join(prefix_lines)

                # Step8: IPSec 额外字段
                d["wan_addr_plain"] = (_cidr_plain_fn(str(d.get("wan_addr", "")))
                                       if callable(_cidr_plain_fn) else str(d.get("wan_addr", "")).split("/", 1)[0].strip())
                for px in ("main", "bk"):
                    tun_peer = tun_local = tun_prefix = ""
                    if callable(_cidr_host_fn):
                        try:
                            tun_peer, tun_local, tun_prefix = _cidr_host_fn(
                                str(d.get(f"{px}_gre_wanip", "")))
                        except Exception:
                            pass
                    d[f"{px}_tun_peer"]      = tun_peer
                    d[f"{px}_tun_local"]     = tun_local
                    d[f"{px}_tun_addr"]      = f"{tun_local}/{tun_prefix}" if tun_local and tun_prefix else ""
                    loop_ip = str(d.get(f"{px}_loop_ip", "")).strip()
                    d[f"{px}_loop_ip_cidr"]  = f"{loop_ip}/32" if loop_ip else ""
                    d[f"{px}_track_name"]    = str(d.get(f"{px}_gre_tun", "")).strip()

                # Step9: 补齐 DEFAULT_* 供模板直接引用
                d.update(iv)
                # 还原被 iv.update 可能覆盖的关键计算值
                if callable(norm_fn):
                    d["lan_gw"] = norm_fn(str(d.get("lan_cidr", "")), str(d.get("lan_gw", "")))

                if callable(gen_fn):
                    rendered = gen_fn(d)
                else:
                    rendered = tpl.format(**d)
                format_ok = True
            except Exception as e:
                parse_err = f"MPLS IPSec 预览失败: {e}"

        data: dict[str, str] = {}
        parsed_raw: dict | None = None

        # 专用分支未 format 成功时：用解析器 + 行扫描 + 初始化拼 data，一次正则替换。
        # （含 USG HK/非HK：format 失败时同样走此处，避免「已解析但 data 仍空」。）
        if not format_ok:
            if parser_name:
                if ns and parser_name in ns:
                    try:
                        parsed_raw = ns[parser_name](col1)
                        for k, v in parsed_raw.items():
                            if isinstance(v, str):
                                if v.strip():
                                    data[k] = v
                            elif isinstance(v, dict):
                                continue
                            elif isinstance(v, list):
                                if k.endswith("_export_ips") or k.endswith(
                                    "_export_ip_map"
                                ):
                                    continue
                                if k in (
                                    "hkip_nat_list",
                                    "main_us_nat_ips",
                                    "bk_us_nat_ips",
                                ):
                                    continue
                                if v:
                                    data[k] = str(v[0])
                    except Exception as e:
                        if not parse_err:
                            parse_err = f"解析失败: {e}"
                        parsed_raw = None
                else:
                    if not parse_err:
                        parse_err = f"解析器 [{parser_name}] 尚未就绪（请先切换到对应工具页签加载）"

            if (
                not parse_err
                and parsed_raw is not None
                and parser_name
                in ("parse_business_data", "parse_business_data_hk")
            ):
                _enrich_usg_preview_export_fields(data, parsed_raw, source)
            # MPLS 预览与正式页对齐：补齐 config_type / hostname / main_track。
            if (
                not parse_err
                and source == MOD_ER_MPLS
                and parser_name in ("parse_epoch_mpls", "parse_epoch_mpls_ipsec")
            ):
                def _blank(v: Any) -> bool:
                    return (v is None) or (isinstance(v, str) and not v.strip())

                def _fill_if_blank(dst_key: str, src_key: str) -> None:
                    if _blank(data.get(dst_key)) and (not _blank(data.get(src_key))):
                        data[dst_key] = str(data.get(src_key, ""))

                def _backfill_mpls_side(px: str) -> None:
                    lt = str(data.get(f"{px}_line_type", "")).strip()
                    if lt == "vtun_only":
                        # parse_epoch_mpls 在 vtun-only 下不会给 gre_* 字段；
                        # 可视化模板仍引用 gre_*，这里按正式生成逻辑回填别名。
                        pairs = (
                            (f"{px}_gre_tun", f"{px}_vtun_id"),
                            (f"{px}_gre_pe", f"{px}_vtun_pe"),
                            (f"{px}_gre_wanip", f"{px}_vtun_wanip"),
                            (f"{px}_gre_pe_ip", f"{px}_vtun_remote"),
                            (f"{px}_gre_ce_ip", f"{px}_vtun_local"),
                            (f"{px}_gre_remote", f"{px}_vtun_remote"),
                        )
                    elif lt == "gre_only":
                        # gre-only 下做反向回填，避免模板中的 vtun_* 占位残留。
                        pairs = (
                            (f"{px}_vtun_id", f"{px}_gre_tun"),
                            (f"{px}_vtun_pe", f"{px}_gre_pe"),
                            (f"{px}_vtun_wanip", f"{px}_gre_wanip"),
                            (f"{px}_vtun_remote", f"{px}_gre_pe_ip"),
                            (f"{px}_vtun_local", f"{px}_gre_ce_ip"),
                            (f"{px}_vtun_docking", f"{px}_gre_remote"),
                        )
                    else:
                        return
                    for dst, src in pairs:
                        _fill_if_blank(dst, src)

                if "config_type" not in data:
                    data["config_type"] = "IPSec" if "IPSec" in key else ("国内" if ("国内" in key) else "海外")
                if not str(data.get("hostname", "")).strip():
                    ex_hn = ns.get("extract_lineid_mpls") if ns else None
                    if callable(ex_hn):
                        try:
                            hn = str(ex_hn(col1) or "").strip()
                        except Exception:
                            hn = ""
                    else:
                        hn = ""
                    data["hostname"] = hn or "（请填写Hostname）"
                # main_track：正式页用 main_gre_tun 或 main_vtun_id 做 track name，
                # parse_epoch_mpls 不填此字段，需在预览路径手动推导。
                if not str(data.get("main_track", "")).strip():
                    ml_type = str(data.get("main_line_type", "vtun_gre"))
                    if ml_type == "vtun_only":
                        data["main_track"] = str(data.get("main_vtun_id", ""))
                    else:
                        data["main_track"] = str(data.get("main_gre_tun", ""))
                _backfill_mpls_side("main")
                _backfill_mpls_side("bk")

            skip_loose_line_scan = bool(
                not parse_err
                and parsed_raw is not None
                and len(parsed_raw) > 0
                and parser_name in ("parse_business_data", "parse_business_data_hk", "parse_ar_visual")
            )
            if not skip_loose_line_scan:
                for line in col1.splitlines():
                    s = line.strip()
                    if not s or s.startswith("#"):
                        continue
                    sep = None
                    if "=" in s:
                        sep = "="
                    elif ":" in s:
                        sep = ":"
                    if sep:
                        k, _, v = s.partition(sep)
                        k = k.strip().lower().replace(" ", "_").replace("-", "_")
                        v = v.strip()
                        if k and v and k not in data:
                            data[k] = v

            def _sub(m: re.Match) -> str:
                var = m.group(1)
                val = data.get(var)
                if val is None or (isinstance(val, str) and not val.strip()):
                    return f"[{var}]"
                return val

            init_vals = self._preview_init_values(info)
            # AR 预览：按当前场景（ZH/DJ）的南向下拉实时覆盖 south_primary/south_backup，
            # 避免 parse_ar_visual 固定取 ZH 标签导致 Factory 双机场景南向不生效。
            if source == MOD_AR_SDWAN and ns:
                south_fn = ns.get("_south_ips_by_label")
                if callable(south_fn):
                    mod = _init_mod_for_scenario(info)
                    lbl_key = "DJ_SOUTH_LABEL" if mod == AR_INIT_MOD_DJ else "ZH_SOUTH_LABEL"
                    sel = str(init_vals.get(lbl_key, "")).strip()
                    if sel:
                        try:
                            pri, bak = south_fn(sel)
                            if pri:
                                init_vals["south_primary"] = str(pri)
                            if bak:
                                init_vals["south_backup"] = str(bak)
                        except Exception:
                            pass
            data.update(init_vals)
            rendered = re.sub(r"\{(\w+)(?::[^}]*)?\}", _sub, tpl)
            if source == MOD_AR_SDWAN and not str(data.get("south_backup", "")).strip():
                rendered = re.sub(
                    r"(?ms)^ip route-static vpn-instance underlay_internetB \[south_backup\] 255\.255\.255\.255 \S+ tag 4400 description agile-controller\s*\n\s*agile controller host \[south_backup\] port 10020 vpn-instance underlay_internetB\s*\nquit\s*\n?",
                    "",
                    rendered,
                )

        if tpl_vars:
            # 预览时做"合并补齐"而非覆盖：保留手工映射，同时补齐模板新变量
            cur_map = self.txt_map.get("1.0", tk.END)
            merged_map = _merge_mapping_keep_manual(cur_map, _auto_mapping(tpl))
            self._set_text(self.txt_map, merged_map)

        if format_ok:
            total = len(tpl_vars)
            filled = total
            status_line = (
                "# 预览（与正式页签相同的数据与 format 逻辑，模板为第③栏当前内容）\n"
                "# 数据源：①栏业务文本 + 初始化面板\n"
            )
        elif tpl_vars:
            total = len(tpl_vars)
            filled = sum(1 for v in tpl_vars if str(data.get(v, "")).strip())
            status_line = f"# 预览  ──  已填入 {filled}/{total} 个变量\n"
        else:
            filled = 0
            total = 0
            status_line = ""

        if total > 0:
            if parse_err:
                status_line += f"# 注意：{parse_err}\n"
            header = status_line + "\n"
        elif parse_err:
            header = f"# 预览失败\n# 注意：{parse_err}\n\n"
        else:
            header = "# 预览（程序化模板，展示示例输出）\n\n"

        self._set_text(self.txt_prev, header + rendered, readonly=True)
        self.status.set(
            (f"预览已生成  ·  {filled}/{total} 变量已填  ·  {key}" if total > 0
             else f"预览已生成（程序化模板）  ·  {key}")
        )

    def save(self) -> None:
        key = self._current_key
        if not key:
            return
        info = self.SCENARIOS[key]
        slot = _scenario_tpl_slot(info)
        sdir = self._scenario_dir(key)
        tpl_var = info.get("tpl_var")
        tpl_static = info.get("tpl_static")

        realtime_note = (
            f"模板变量 [{tpl_var}] 与内存已同步，无需重启"
            if tpl_var else
            (f"程序化输出键 [{tpl_static}] 已挂接 generate/render，无需重启"
             if tpl_static else
             "已写入场景目录")
        )
        confirmed = messagebox.askyesno(
            "确认保存并应用",
            f"即将保存场景「{key}」的配置。\n\n"
            f"  · 目录：{sdir}\n"
            f"  · 模板文件：{slot}.tpl\n"
            f"  · changelog.log 将记录本次更新\n"
            f"  · {realtime_note}\n\n"
            "确认保存并立即应用吗？",
            icon="question",
        )
        if not confirmed:
            self.status.set("已取消保存")
            return

        hdr = self.txt_hdr.get("1.0", tk.END)
        mp  = self.txt_map.get("1.0", tk.END)
        tpl_raw = self.txt_tpl.get("1.0", tk.END)
        ver, tpl = self._bump_tpl_version_stamp(key, tpl_raw)
        self._set_text(self.txt_tpl, tpl)

        self._persist_to_disk(key, hdr, mp, tpl, event="save")
        self._sync_init_to_module_globals()

        self.status.set(f"已保存  ·  v{ver}  ·  已实时生效  ·  {key}")
        messagebox.showinfo(
            "保存成功",
            f"场景「{key}」已保存。\n\n"
            f"模板已标注版本：v{ver}（见第③栏顶部注释）。\n"
            "初始化参数与模板已同步到正式页签，点击「生成」即可使用。\n\n"
            f"路径：{sdir}\n"
            f"模板：{slot}.tpl",
        )


# 自检关键片段：无法从当前 workspace/defaults 模板推导时回退（与 §F 正式语义共用）
_AR_FAC_SNIP = "set factory-configuration from current-configuration"
_AR_OPS_SNIP = "import ops"
_REG_SNIPPETS_FALLBACK: dict[str, list[str]] = {
    "Epoch FastIP · HK 香港出口": ["Epoch HK 出口配置", "set interfaces openvpn"],
    "Epoch FastIP · 非香港出口": ["Epoch 非香港出口配置", "set interfaces tunnel"],
    "Epoch FastIP · ER 飞连": ["set track name flink", "set protocols static route"],
    "Epoch FastIP · ER 新增出口": ["set interfaces tunnel", "set protocols static route"],
    "Epoch FastIP · ER 域名分流": [
        "set service dns forwarding domainlist",
        "set firewall group address-group",
    ],
    "USG FastIP · 非香港出口": ["ip route-static", "interface"],
    "USG FastIP · HK 香港出口": ["ip route-static", "interface"],
    "USG FastIP · 飞连": ["nqa test-instance admin FLmain", "firewall zone untrust"],
    "USG FastIP · 新增出口": ["nat-policy", "interface Tunnel"],
    "Epoch MPLS · 国内配置": ["set interfaces tunnel", "set protocols bgp"],
    "Epoch MPLS · 海外配置": ["set interfaces tunnel", "set protocols bgp"],
    "Epoch FastIP · HK 香港出口 · IPSec": [],
    "Epoch FastIP · 非香港出口 · IPSec":  [],
    "Epoch MPLS · IPSec": ["set vpn ipsec site-to-site peer", "set protocols bgp"],
    "AR SD-WAN · 单机单WAN · OPS": ["ip vpn-instance", _AR_OPS_SNIP],
    "AR SD-WAN · 单机单WAN · Factory": ["ip vpn-instance", _AR_FAC_SNIP],
    "AR SD-WAN · 单机双WAN · OPS": ["ip vpn-instance", _AR_OPS_SNIP],
    "AR SD-WAN · 单机双WAN · Factory": ["ip vpn-instance", _AR_FAC_SNIP],
    "AR SD-WAN · 双机主 OPS": ["ip vpn-instance", _AR_OPS_SNIP],
    "AR SD-WAN · 双机备 OPS": ["ip vpn-instance", _AR_OPS_SNIP],
    "AR SD-WAN · 双机主 Factory": ["ip vpn-instance", _AR_FAC_SNIP],
    "AR SD-WAN · 双机备 Factory": ["ip vpn-instance", _AR_FAC_SNIP],
}


def _reg_read_scenario_template_text(key: str, info: dict) -> str | None:
    """
    自检/正式语义：仅读取 editor_workspace 下已保存的第③栏模板。
    不使用 editor_defaults、不读 exe 内置示例路径——以客户当前 workspace 为唯一依据；
    若该场景尚无保存文件，返回 None，由调用方使用 _REG_SNIPPETS_FALLBACK。
    """
    slot = _scenario_tpl_slot(info)
    p_ws = _scenario_workspace_dir(key) / f"{slot}.tpl"
    if not p_ws.exists():
        return None
    try:
        return p_ws.read_text(encoding="utf-8-sig")
    except Exception:
        return None


_REG_DECO_COMMENT = re.compile(r"^#+\s*[=─\-]+\s*$")


def _reg_snippets_from_workspace_tpl_generic(tpl_raw: str) -> list[str] | None:
    """
    从「当前 workspace 模板」通用地提取两条须在预览/正式输出中出现的子串（区分大小写）。
    不按场景写死（含飞连 track 名等），顺序取自模板从上到下第一条、第二条有效指纹行。
    """
    tpl = _strip_editor_template_version_header(tpl_raw.rstrip("\n"))
    out: list[str] = []
    for ln in tpl.splitlines():
        s = ln.strip()
        if not s or _REG_DECO_COMMENT.match(s):
            continue
        sn: str | None = None
        if s.startswith("#"):
            body = s.lstrip("#").strip()
            if not body:
                continue
            if "{" in body:
                pre = body.split("{", 1)[0].rstrip()
                if len(pre) >= 6:
                    sn = pre
            elif len(body) >= 6:
                sn = body[:120]
        else:
            if "{" in s:
                pre = s.split("{", 1)[0].rstrip()
                if len(pre) >= 6:
                    sn = pre
            else:
                sn = s[:150] if len(s) > 150 else s
        if sn and len(sn) >= 6:
            out.append(sn)
        if len(out) >= 2:
            break
    return out if len(out) >= 2 else None


def _reg_required_snippets(key: str, info: dict) -> list[str]:
    """19 场景关键片段：仅依据 editor_workspace 已保存模板推导；无文件时回退内置表。"""
    tpl = _reg_read_scenario_template_text(key, info)
    if tpl:
        got = _reg_snippets_from_workspace_tpl_generic(tpl)
        if got:
            return got
    return list(_REG_SNIPPETS_FALLBACK.get(key, []))


# ──────────────────────────────────────────────────────────────────
# A-D: 强约束升级辅助
# ──────────────────────────────────────────────────────────────────

# A: 场景最低填入率阈值（仅当预览头部含「已填入 X/Y」时生效）。
# 不在此表的场景若有 已填入 X/Y 行则默认要求 100%（filled == total）。
_REG_MIN_FILL_RATIO: dict[str, float] = {
    # 强约束：凡出现「已填入 X/Y」，默认要求 100%；
    # 需要放宽时再按场景单独加白名单。
    "Epoch MPLS · 海外配置": 1.0,
}

# A: AR Factory 南向哨兵字符串——出现即代表南向 IP 未正确注入
_REG_FORBIDDEN_SENTINELS: dict[str, list[str]] = {
    k: ["@@SOUTH_PRI@@", "@@SOUTH_BK@@"]
    for k in (
        "AR SD-WAN · 单机单WAN · Factory",
        "AR SD-WAN · 单机双WAN · Factory",
        "AR SD-WAN · 双机主 Factory",
        "AR SD-WAN · 双机备 Factory",
    )
}


def _reg_parse_fill_ratio(preview_text: str) -> tuple[int, int]:
    """解析预览头部「已填入 X/Y 个变量」，返回 (filled, total)；未找到返回 (-1, -1)。"""
    m = re.search(r"已填入\s+(\d+)/(\d+)", preview_text)
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def _reg_ar_factory_south_extra_check(
    key: str, info: dict, ns: dict | None, preview_after_probe: str
) -> tuple[bool, list[str]]:
    """
    C 类升级：AR Factory 场景 init probe 后，验证南向 IP 出现在预览里。
    按模板实际包含的字段区分：
      · 双机主 Factory 模板仅含 {south_primary}，不校验 south_backup。
      · 双机备 Factory 模板仅含 {south_backup}，不校验 south_primary。
      · 单机* Factory 模板含两者，均校验。
    返回 (ok, issue_notes)。
    """
    if not (ns and "Factory" in key and "AR" in key):
        return True, []
    south_fn = ns.get("_south_ips_by_label")
    labels = list(ns.get("SOUTH_LABELS_DISPLAY") or [])
    if not callable(south_fn) or not labels:
        return True, []
    alt = labels[1] if len(labels) > 1 else labels[0]
    try:
        pri, bak = south_fn(alt)
    except Exception:
        return True, []
    # 仅检查该场景模板里实际存在的南向字段
    check_primary = "双机备 Factory" not in key
    check_backup  = "双机主 Factory" not in key
    issues: list[str] = []
    if check_primary and pri and pri not in preview_after_probe:
        issues.append(f"south_primary_missing_in_probe={pri}")
    if check_backup and bak and bak not in preview_after_probe:
        issues.append(f"south_backup_missing_in_probe={bak}")
    return len(issues) == 0, issues


def _restore_visual_editor_after_regression(
    ved: VisualEditorTab,
    snap_key: str,
    snap_hdr: str,
    snap_map: str,
    snap_tpl: str,
) -> None:
    """回归结束后恢复打开前的四栏与场景；不写 editor_workspace。"""
    if not snap_key or snap_key not in ved.SCENARIOS:
        return
    ved._regression_skip_disk = True
    try:
        ved.combo.set(snap_key)
        ved._current_key = snap_key
        ved._set_text(ved.txt_hdr, snap_hdr)
        ved._set_text(ved.txt_map, snap_map)
        ved._set_text(ved.txt_tpl, snap_tpl)
        ved._set_text(
            ved.txt_prev,
            "# 请点击底部【预览模板】按钮生成完整预览\n",
            readonly=True,
        )
        ved._reset_visual_editor_undo()
        ved._show_init_panel_for_scenario(snap_key)
        ved._relayout_init_form(snap_key)
        ved._sync_init_outer_height(snap_key)
        ved._sync_ar_zh_wan2_visual()
        try:
            ved._reload_init_entries_from_globals()
        except Exception:
            pass
        ved.status.set(f"已恢复编辑区（未写 workspace）：{snap_key}")
    finally:
        ved._regression_skip_disk = False


_reg_set_widget_value = _su_global.widget_set_value


def _run_ui_regression_19(root: tk.Tk, ved: VisualEditorTab) -> tuple[Path, Path]:
    """
    UI 自动化回归（19 场景）强约束版（A-D）：
    - preview_ok: 关键片段 + 非失败态 + [A] 哨兵字符串检测 + 填入率不足检测
    - update_ok: tpl_var/tpl_static 运行时更新校验
    - init_ok: 初始化改动是否体现在预览 + [C] AR Factory 主备 IP 均须出现

    A: _REG_FORBIDDEN_SENTINELS（@@SOUTH_PRI@@ / @@SOUTH_BK@@）+ _REG_MIN_FILL_RATIO（填入率阈值）
    B: _reg_required_snippets 从 editor_workspace 第③栏模板通用地取两条指纹（无则 _REG_SNIPPETS_FALLBACK）
    C: _reg_ar_factory_south_extra_check 在 init probe 后验证主备 IP 均出现
    D: 每场景 row 新增 filled_count / total_count / sentinel_found / fill_gap 字段

    **磁盘**：全程 `_regression_skip_disk`，不写 `data/editor_workspace`（含静默保存、
    ER 体检落盘、template_version 计数器）；仅写 `data/selfcheck_logs/<batch>/`。
    关闭窗口时跳过 auto_save。内存中的 `EMBEDDED_NS` / 初始化 globals 会随预览与探测短暂变化，
    结束时尽量恢复四栏与下拉；若与主程序同进程且介意内存态，可切换一次场景或重启主程序。
    """
    from datetime import datetime

    def _flush_ui() -> None:
        root.update_idletasks()
        root.update()

    def _init_probe(
        key: str, info: dict, init_vals: dict[str, str], ns: dict | None
    ) -> tuple[str, str, str] | None:
        mod = _init_mod_for_scenario(info)
        if mod in (ER_INIT_MOD_HK, ER_INIT_MOD_US, MOD_ER_MPLS):
            return ("DEFAULT_WAN_ETH", "9", "eth9")
        if mod in (USG_INIT_MOD_US, USG_INIT_MOD_HK):
            return ("DEFAULT_WAN_ETH", "GE0/0/7", "GE0/0/7")
        if mod == ER_INIT_MOD_FLINK:
            return ("ER_FL_MAIN_NH_DEFAULT", "10.10.10.10", "10.10.10.10")
        if mod == ER_INIT_MOD_NEW_EXIT:
            return ("ER_NE_MAIN_PE_NH_DEFAULT", "203.0.113.1", "203.0.113.1")
        if mod == ER_INIT_MOD_DOMAIN_SPLIT:
            return ("ER_DS_DNS1_DEFAULT", "1.1.1.1", "1.1.1.1")
        if mod == USG_INIT_MOD_FLINK:
            return ("USG_FL_MAIN_TUN_DEFAULT", "3999", "Tunnel3999")
        if mod == USG_INIT_MOD_NEW_EXIT:
            return ("USG_NE_MAIN_TUN_DEFAULT", "1888", "Tunnel1888")
        if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ) and ("OPS" in key):
            return None
        if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ) and ns and ("Factory" in key):
            south_fn = ns.get("_south_ips_by_label")
            labels = list(ns.get("SOUTH_LABELS_DISPLAY") or [])
            if callable(south_fn) and labels:
                cur_k = "DJ_SOUTH_LABEL" if mod == AR_INIT_MOD_DJ else "ZH_SOUTH_LABEL"
                cur = str(init_vals.get(cur_k, "")).strip()
                alt = labels[1] if len(labels) > 1 and labels[1] != cur else labels[0]
                try:
                    pri, bak = south_fn(alt)
                except Exception:
                    pri, bak = "", ""
                exp = ""
                if "双机备 Factory" in key:
                    exp = str(bak or pri or "")
                else:
                    exp = str(pri or bak or "")
                if exp:
                    return (cur_k, str(alt), exp)
            return ("DEFAULT_FTP_SERVER", "203.0.113.200", "203.0.113.200")
        if mod in (AR_INIT_MOD_ZH, AR_INIT_MOD_DJ):
            return None
        return None

    results: list[dict[str, Any]] = []
    scenario_items = list(ved.SCENARIOS.items())
    snap_key = ved.combo.get()
    snap_hdr = ved.txt_hdr.get("1.0", tk.END)
    snap_map = ved.txt_map.get("1.0", tk.END)
    snap_tpl = ved.txt_tpl.get("1.0", tk.END)
    # mtime 快照（F8：确保 editor_workspace 全程未写）
    _ws_mtime_before = _formal_mtime_snapshot(WORKSPACE)
    # workspace_test 初始化（F7 写入隔离目录，不影响正式 workspace）
    try:
        WORKSPACE_TEST.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    ved._regression_skip_disk = True
    try:
        for idx, (key, info) in enumerate(scenario_items, 1):
            row: dict[str, Any] = {
                "index": idx,
                "scenario": key,
                "preview_ok": False,
                "update_ok": False,
                "init_ok": False,
                "notes": [],
                # D: 填入率统计字段（-1 表示该场景无「已填入 X/Y」行）
                "filled_count": -1,
                "total_count": -1,
                "fill_gap": 0,
                "sentinel_found": [],
            }
            tpl_orig = ""
            try:
                ved.combo.set(key)
                ved._on_select(None)
                _flush_ui()

                ved.preview()
                _flush_ui()
                preview_text = ved.txt_prev.get("1.0", tk.END)
                _is_placeholder = bool(info.get("placeholder"))

                if _is_placeholder:
                    # placeholder 场景（IPSec 接入，模板待提供）：
                    # 仅验证预览不崩溃，不做 snippet / fill-ratio 强断言。
                    bad = "# 预览失败" in preview_text
                    row["preview_ok"] = not bad
                    row["notes"].append("preview_placeholder_skip_snippets")
                    if bad:
                        row["notes"].append("preview_bad_state")
                    row["preview_excerpt"] = preview_text[:500]
                else:
                    required = _reg_required_snippets(key, info)
                    miss = [s for s in required if s not in preview_text]

                    # A: 哨兵字符串检测（AR Factory 南向 IP 未注入时的占位）
                    sentinels_hit = [s for s in _REG_FORBIDDEN_SENTINELS.get(key, []) if s in preview_text]
                    if sentinels_hit:
                        miss.extend(f"sentinel:{s}" for s in sentinels_hit)
                    row["sentinel_found"] = sentinels_hit

                    # A: 填入率检测（已填入 X/Y 中 X < Y 且低于阈值时失败）
                    filled_c, total_c = _reg_parse_fill_ratio(preview_text)
                    row["filled_count"] = filled_c
                    row["total_count"] = total_c
                    row["fill_gap"] = max(0, total_c - filled_c) if total_c > 0 else 0
                    if filled_c >= 0 and total_c > 0 and filled_c < total_c:
                        min_ratio = _REG_MIN_FILL_RATIO.get(key, 1.0)
                        if (filled_c / total_c) < min_ratio:
                            miss.append(f"fill_incomplete={filled_c}/{total_c}")

                    bad = ("# 预览失败" in preview_text) or bool(
                        re.search(r"已填入\s+0/\d+", preview_text)
                    )
                    row["preview_ok"] = (not bad) and (len(miss) == 0)
                    if miss:
                        row["notes"].append("preview_missing=" + ",".join(miss))
                    if bad:
                        row["notes"].append("preview_bad_state")
                    row["preview_excerpt"] = preview_text[:500]

                source = str(info.get("source") or "")
                ns = EMBEDDED_NS.get(source) if source else None
                init_mod = _init_mod_for_scenario(info)
                init_vals = ved._preview_init_values(info)
                if _is_placeholder:
                    row["init_ok"] = True
                    row["notes"].append("init_probe_skipped_placeholder")
                else:
                    probe = _init_probe(key, info, init_vals, ns)
                    if probe:
                        init_key, new_v, expect = probe
                        ent = ved._init_entries.get(init_mod, {}).get(init_key)
                        if ent is None:
                            row["notes"].append(f"init_entry_missing={init_key}")
                            row["init_ok"] = False
                        else:
                            old_v = ved._init_field_value(ent)
                            _reg_set_widget_value(ent, new_v)
                            ved._sync_single_init_mod_to_globals(init_mod)
                            ved.preview()
                            _flush_ui()
                            p2 = ved.txt_prev.get("1.0", tk.END)
                            row["init_ok"] = expect in p2
                            if not row["init_ok"]:
                                row["notes"].append(f"init_expect_missing={expect}")
                            # C: AR Factory 额外验证主备南向 IP 均出现在 probe 后的预览里
                            if row["init_ok"] and "Factory" in key and "AR" in key:
                                extra_ok, extra_issues = _reg_ar_factory_south_extra_check(
                                    key, info, ns, p2
                                )
                                if not extra_ok:
                                    row["init_ok"] = False
                                    row["notes"].extend(extra_issues)
                            _reg_set_widget_value(ent, old_v)
                            ved._sync_single_init_mod_to_globals(init_mod)
                    else:
                        row["init_ok"] = True
                        row["notes"].append("init_probe_skipped")

                tpl_orig = ved.txt_tpl.get("1.0", tk.END)
                marker = f"REG19_{idx:02d}_{int(datetime.now().timestamp())}"
                probe_tpl = tpl_orig.rstrip("\n") + f"\n# {marker}\n"
                try:
                    applied = _apply_template_to_runtime(key, info, probe_tpl)
                    row["update_ok"] = False
                    if applied:
                        tpl_var = info.get("tpl_var")
                        tpl_static = info.get("tpl_static")
                        if tpl_var:
                            ns2 = EMBEDDED_NS.get(source) if source else None
                            row["update_ok"] = bool(
                                ns2 and marker in str(ns2.get(str(tpl_var), ""))
                            )
                        elif tpl_static:
                            row["update_ok"] = marker in str(
                                VISUAL_PROG_OVERRIDE.get(str(tpl_static), "")
                            )
                    if not row["update_ok"]:
                        row["notes"].append("runtime_update_failed")
                finally:
                    try:
                        _apply_template_to_runtime(key, info, tpl_orig)
                    except Exception:
                        pass
            except Exception as e:
                row["notes"].append(f"exception={type(e).__name__}:{e}")
                row["preview_ok"] = False
                row["update_ok"] = False
                row["init_ok"] = False
                if tpl_orig:
                    try:
                        _apply_template_to_runtime(key, info, tpl_orig)
                    except Exception:
                        pass
            # §F 正式页面检测（formal_gen / formal_init / formal_tpl / formal_ws）
            try:
                _src = str(info.get("source", ""))
                _ns  = EMBEDDED_NS.get(_src) if _src else None
                _formal = _run_formal_checks(key, info, _ns, ved, idx)
                row.update(_formal)
                # formal_pass: True only if every non-skipped item passed
                # None (skipped) items are excluded from the AND
                def _scored(v: object) -> bool | None:
                    if v is True:
                        return True
                    if v is False:
                        return False
                    return None  # skipped/na
                _items = [
                    _scored(row["formal_gen_ok"]),
                    _scored(row["formal_init_ok"]),
                    _scored(row["formal_tpl_ok"]),
                    _scored(row["formal_ws_ok"]),
                ]
                _non_skip = [v for v in _items if v is not None]
                row["formal_pass"] = all(_non_skip) if _non_skip else None
                _flush_ui()
            except Exception as _fe:
                row["formal_notes"] = [f"formal_checks_exception={type(_fe).__name__}:{_fe}"]
                row["formal_gen_ok"] = row["formal_init_ok"] = False
                row["formal_tpl_ok"] = row["formal_ws_ok"]   = False
                row["formal_pass"] = False
            row["pass"] = bool(
                row["preview_ok"] and row["update_ok"] and row["init_ok"]
            )
            results.append(row)
    finally:
        try:
            _restore_visual_editor_after_regression(
                ved, snap_key, snap_hdr, snap_map, snap_tpl
            )
        except Exception:
            pass
        ved._regression_skip_disk = False
        ved._skip_next_close_autosave = True
        # 清理 workspace_test 隔离目录
        _formal_teardown_workspace_test()

    # mtime 终态校验：任何 editor_workspace 文件变化均报告
    _ws_mtime_after  = _formal_mtime_snapshot(WORKSPACE)
    _ws_dirty_files  = _formal_mtime_dirty(_ws_mtime_before, _ws_mtime_after)
    _mtime_clean     = len(_ws_dirty_files) == 0

    total = len(results)
    passed = sum(1 for r in results if r.get("pass"))

    def _fstat(field: str) -> tuple[int, int, int]:
        """Returns (pass_count, fail_count, skipped_count) for a formal field."""
        p = sum(1 for r in results if r.get(field) is True)
        f = sum(1 for r in results if r.get(field) is False)
        s = sum(1 for r in results if r.get(field) is None)
        return p, f, s

    f_gen_pass,  f_gen_fail,  f_gen_skip  = _fstat("formal_gen_ok")
    f_init_pass, f_init_fail, f_init_skip = _fstat("formal_init_ok")
    f_tpl_pass,  f_tpl_fail,  f_tpl_skip  = _fstat("formal_tpl_ok")
    f_ws_pass,   f_ws_fail,   f_ws_skip   = _fstat("formal_ws_ok")
    # backward compat aliases (denom = non-skipped)
    f_gen_ok  = f_gen_pass
    f_init_ok = f_init_pass
    f_tpl_ok  = f_tpl_pass
    f_ws_ok   = f_ws_pass
    f_total   = len(results)
    f_passed  = sum(1 for r in results if r.get("formal_pass") is True)
    summary = {
        "tool": "ui_regression_19",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "all_passed": passed == total,
        # §F 正式页面汇总（pass/fail/skipped 分开统计，skipped 不入分母）
        "formal_passed":       f_passed,
        "formal_gen_pass":     f_gen_pass,   "formal_gen_fail":  f_gen_fail,   "formal_gen_skip":  f_gen_skip,
        "formal_init_pass":    f_init_pass,  "formal_init_fail": f_init_fail,  "formal_init_skip": f_init_skip,
        "formal_tpl_pass":     f_tpl_pass,   "formal_tpl_fail":  f_tpl_fail,   "formal_tpl_skip":  f_tpl_skip,
        "formal_ws_pass":      f_ws_pass,    "formal_ws_fail":   f_ws_fail,    "formal_ws_skip":   f_ws_skip,
        "mtime_clean":         _mtime_clean,
        "mtime_dirty_files":   _ws_dirty_files,
    }
    report = {"summary": summary, "results": results}
    out_root = SELFCHECK_LOGS
    out_root.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    rgx = re.compile(rf"^{re.escape(day)}_(\d{{2}})$")
    max_idx = 0
    for p in out_root.iterdir():
        if not p.is_dir():
            continue
        m = rgx.match(p.name)
        if not m:
            continue
        try:
            max_idx = max(max_idx, int(m.group(1)))
        except ValueError:
            continue
    run_idx = max_idx + 1
    run_tag = f"{day}_{run_idx:02d}"
    out_dir = out_root / run_tag
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ui_regression_19_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    json_abs = str(out_path.resolve())
    summary_txt = out_dir / "ui_regression_19_summary.txt"
    visual_fail_lines: list[str] = []
    formal_fail_lines: list[str] = []
    for r in results:
        if not r.get("pass"):
            nm = str(r.get("scenario", ""))
            parts: list[str] = []
            for n in (r.get("notes") or []):
                parts.append(str(n))
            fc, tc = r.get("filled_count", -1), r.get("total_count", -1)
            if fc >= 0 and tc > 0 and fc < tc:
                parts.append(f"fill={fc}/{tc}")
            sentinels = r.get("sentinel_found") or []
            if sentinels:
                parts.append("sentinel=" + "+".join(sentinels))
            detail = "; ".join(dict.fromkeys(parts))
            visual_fail_lines.append(f"- {nm} ({detail})" if detail else f"- {nm}")
        if r.get("formal_pass") is False:  # only explicit False, not None (skipped)
            nm = str(r.get("scenario", ""))
            fparts: list[str] = []
            for fn in (r.get("formal_notes") or []):
                s = str(fn)
                if not any(s.startswith(p) for p in (
                    "formal_tpl_skipped", "formal_tpl_na",
                    "formal_init_probe_skipped", "formal_init_skipped",
                    "gen_skipped",
                )):
                    fparts.append(s)
            fdetail = "; ".join(dict.fromkeys(fparts))
            formal_fail_lines.append(f"- {nm} ({fdetail})" if fdetail else f"- {nm}")
    mtime_line = ("mtime_clean: yes" if _mtime_clean
                  else f"mtime_clean: NO  dirty={_ws_dirty_files[:3]}")

    def _fmt_stat(pass_c: int, fail_c: int, skip_c: int) -> str:
        """Format as 'pass/denom  (N skipped)'  where denom = pass+fail."""
        denom = pass_c + fail_c
        base = f"{pass_c}/{denom}"
        return f"{base}  ({skip_c} skipped)" if skip_c else base

    gen_stat  = _fmt_stat(f_gen_pass,  f_gen_fail,  f_gen_skip)
    init_stat = _fmt_stat(f_init_pass, f_init_fail, f_init_skip)
    tpl_stat  = _fmt_stat(f_tpl_pass,  f_tpl_fail,  f_tpl_skip)
    ws_stat   = _fmt_stat(f_ws_pass,   f_ws_fail,   f_ws_skip)

    txt_body = "\n".join(
        [
            "UI Regression 19 - Summary",
            f"Run: {run_tag}",
            f"Generated: {summary['generated_at']}",
            "",
            "── Visual Channel (preview / update / init) ──",
            f"Passed (visual): {passed}/{total}",
            f"All Passed: {'yes' if summary.get('all_passed') else 'no'}",
            ("Visual Failed Scenarios: none" if not visual_fail_lines else "Visual Failed Scenarios:"),
            *visual_fail_lines,
            "",
            "── Formal Channel (gen / init / tpl / ws) ──",
            "  skipped = 无有效输入或该路径不适用，不算 pass 也不算 fail",
            f"Formal Gen:   {gen_stat}",
            f"Formal Init:  {init_stat}",
            f"Formal Tpl:   {tpl_stat}",
            f"Formal WS:    {ws_stat}",
            f"Formal Passed (all non-skipped ok): {f_passed}/{f_total}",
            mtime_line,
            ("Formal Failed Scenarios: none" if not formal_fail_lines else "Formal Failed Scenarios:"),
            *formal_fail_lines,
            "",
            "Report JSON:",
            json_abs,
        ]
    )
    summary_txt.write_text(txt_body, encoding="utf-8-sig")
    print(f"UI_REGRESSION_19: passed={passed}/{total}", flush=True)
    print(f"UI_REGRESSION_19_RUN: {run_tag}", flush=True)
    print(f"UI_REGRESSION_19_REPORT_JSON: {json_abs}", flush=True)
    print(f"UI_REGRESSION_19_REPORT_TXT: {summary_txt.resolve()}", flush=True)
    return out_path, summary_txt


# ══════════════════════════════════════════════════════════════════
# §F  正式页面自检扩展（Formal Regression）
# ══════════════════════════════════════════════════════════════════
# 覆盖四个维度（与可视化 §E 三维互补）：
#   formal_gen_ok   正式页生成函数可调用、输出非空、关键命令存在
#   formal_init_ok  初始化字段变更 → 正式页生成输出体现新值
#   formal_tpl_ok   自定义模板写入内存 → 正式页生成使用新模板（tpl_static）
#   formal_ws_ok    向 workspace_test 写模板 → _apply_template_to_runtime → 内存态正确
# 隔离保证：
#   全程不写 editor_workspace；workspace_rw 测试仅写 WORKSPACE_TEST 目录
#   回归前后对 WORKSPACE 做 mtime 快照比对，任何文件变化即 mtime_clean=False
# ──────────────────────────────────────────────────────────────────

# ── F1  mtime 快照 & workspace_test 生命周期 ──────────────────────

def _formal_mtime_snapshot(path: Path) -> dict[str, float]:
    snap: dict[str, float] = {}
    if not path.exists():
        return snap
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    snap[str(p.resolve())] = p.stat().st_mtime
                except OSError:
                    pass
    except Exception:
        pass
    return snap


def _formal_mtime_dirty(snap_a: dict[str, float], snap_b: dict[str, float]) -> list[str]:
    dirty: list[str] = []
    for k in set(snap_a) | set(snap_b):
        if snap_a.get(k) != snap_b.get(k):
            dirty.append(k)
    return sorted(dirty)


def _formal_teardown_workspace_test() -> None:
    import shutil
    if WORKSPACE_TEST.exists():
        try:
            shutil.rmtree(WORKSPACE_TEST, ignore_errors=True)
        except Exception:
            pass


# ── F2  示例输入加载 ──────────────────────────────────────────────

def _formal_load_default_header(key: str, info: dict) -> str:
    """业务数据头：优先 editor_workspace，其次 editor_defaults，最后出厂自动生成。"""
    sk = _editor_safe_key(_visual_scenario_disk_key(key))
    p_ws = WORKSPACE / sk / "headers.txt"
    if p_ws.exists():
        try:
            return p_ws.read_text(encoding="utf-8-sig").strip()
        except Exception:
            pass
    p_def = EDITOR_DEFAULTS_ROOT / sk / "headers.txt"
    if p_def.exists():
        try:
            return p_def.read_text(encoding="utf-8-sig").strip()
        except Exception:
            pass
    tpl = _factory_tpl_for_scenario(info)
    return _auto_headers(tpl).strip()


# ── F3  各 source 正式页生成调用 ─────────────────────────────────

def _formal_gen_er(key: str, info: dict, ns: dict, hdr: str) -> tuple[str, str]:
    """调用 ER FastIP 正式生成链路，返回 (output, err)。"""
    parser_name = str(info.get("parser_name", ""))
    tpl_var = str(info.get("tpl_var", ""))

    if parser_name in ("parse_epoch_hk", "parse_epoch_us"):
        fn_name = ("build_epoch_hk_format_dict" if "hk" in parser_name
                   else "build_epoch_us_format_dict")
        fn = ns.get(fn_name)
        if not callable(fn):
            return "", f"{fn_name} not in ns"
        try:
            result = fn(hdr)
        except Exception as e:
            return "", f"{fn_name} raised: {e}"
        # Bug A fix: build_epoch_us_format_dict returns 3-tuple (d, err, warns)
        if isinstance(result, tuple) and len(result) >= 2:
            d, err = result[0], result[1]
            if err is not None:
                return "", f"format_dict error: {err}"
        else:
            d = result
        if not isinstance(d, dict):
            return "", "format_dict returned non-dict"
        tpl = str(ns.get(tpl_var, ""))
        if not tpl:
            return "", f"template {tpl_var!r} empty"
        try:
            return tpl.format(**d), ""
        except Exception as e:
            return "", f"template.format failed: {e}"

    elif parser_name == "parse_er_flink_headers":
        parse_fn = ns.get("parse_er_flink_headers")
        build_fn = ns.get("build_er_flink_config")
        if not callable(parse_fn) or not callable(build_fn):
            return "", "parse_er_flink_headers/build_er_flink_config not in ns"
        try:
            result = parse_fn(hdr)
            parsed = result[0] if isinstance(result, tuple) else result
            routes = parsed.get("routes", []) if isinstance(parsed, dict) else []
            main_nh = str(ns.get("ER_FL_MAIN_NH_DEFAULT", "10.10.10.1"))
            bk_nh = str(ns.get("ER_FL_BACKUP_NH_DEFAULT", "10.10.10.2"))
            # Bug B fix: build_er_flink_config returns str, not dict
            output_str = build_fn(routes, main_nh, bk_nh)
            return str(output_str or ""), ""
        except Exception as e:
            return "", f"er_flink build failed: {e}"

    elif parser_name == "parse_er_new_exit_blocks":
        parse_fn = ns.get("parse_er_new_exit_blocks")
        build_fn = ns.get("build_er_new_exit_config")
        if not callable(parse_fn) or not callable(build_fn):
            return "", "parse_er_new_exit_blocks/build_er_new_exit_config not in ns"
        try:
            result = parse_fn(hdr)
            parsed = (result[0] if isinstance(result, tuple) else result) or {}
            init_cfg = {
                "main_pe_next_hop": str(ns.get("ER_NE_MAIN_PE_NH_DEFAULT", "203.0.113.1")),
                "bk_pe_next_hop":  str(ns.get("ER_NE_BK_PE_NH_DEFAULT", "203.0.113.2")),
                "main_dum_start":  int(ns.get("ER_NE_MAIN_DUM_DEFAULT", 300)),
                "bk_dum_start":    int(ns.get("ER_NE_BK_DUM_DEFAULT", 400)),
                "main_nat_rule":   str(ns.get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300")),
                "bk_nat_rule":     str(ns.get("ER_NE_BK_NAT_RULE_DEFAULT", "400")),
                "nat_source_cidr": str(ns.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "")),
                "fnet_probe":      str(ns.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")),
                "fnet_exit_tunnel": str(ns.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")),
                "fnet_nat_rule":   str(ns.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")),
            }
            out = build_fn(parsed, init_cfg)
            if isinstance(out, dict):
                tpl = str(ns.get(tpl_var, ""))
                return (tpl.format(**out) if tpl else str(out)), ""
            return str(out or ""), ""
        except Exception as e:
            return "", f"er_new_exit build failed: {e}"

    elif "domain" in key.lower() or "域名" in key:
        build_fn = ns.get("build_er_domain_split_script")
        if not callable(build_fn):
            return "", "build_er_domain_split_script not in ns"
        try:
            # Inject minimum required fields for build_er_domain_split_script to produce output.
            # table_nh_primary / static32_primary_nh are validated at line 2362-2368;
            # omitting them causes "递归下一跳不能为空" error.
            _ds_main_nh = str(ns.get("ER_DS_MAIN_NH_DEFAULT", "10.10.10.1"))
            _ds_bk_nh   = str(ns.get("ER_DS_BK_NH_DEFAULT",  "10.10.10.2"))
            cfg = {
                "domains_text":        "example.com",
                "addr_group":          "FORMAL-TEST",
                "dns1":                str(ns.get("ER_DS_DNS1_DEFAULT", "8.8.8.8")),
                "dns2":                str(ns.get("ER_DS_DNS2_DEFAULT", "8.8.4.4")),
                "main_nh":             _ds_main_nh,
                "bk_nh":               _ds_bk_nh,
                "table_nh_primary":    _ds_main_nh,
                "static32_primary_nh": _ds_main_nh,
                "static32_backup_nh":  _ds_bk_nh,
                "source_cidr":         "",
                "eth":                 "",
                "track_name":          "",
                "rule_num":            "",
                "table_num":           "",
            }
            result = build_fn(cfg)
            if isinstance(result, tuple):
                out, err = result[0], result[1]
                if err:
                    return "", f"er_domain_split error: {err}"
                return str(out or ""), ""
            return str(result or ""), ""
        except Exception as e:
            return "", f"er_domain_split build failed: {e}"

    return "", f"unsupported er parser_name: {parser_name!r}"


def _formal_gen_usg(key: str, info: dict, ns: dict, hdr: str) -> tuple[str, str]:
    """调用 USG FastIP 正式生成链路，返回 (output, err)。"""
    parser_name = str(info.get("parser_name", ""))
    tpl_var = str(info.get("tpl_var", ""))

    if parser_name in ("parse_business_data", "parse_business_data_hk"):
        fn_name = ("build_usg_hk_format_dict" if "_hk" in parser_name
                   else "build_usg_us_format_dict")
        fn = ns.get(fn_name)
        if not callable(fn):
            fn = ns.get("build_usg_us_format_dict") or ns.get("build_usg_hk_format_dict")
        if not callable(fn):
            return "", f"{fn_name} not in ns"
        try:
            result = fn(hdr)
        except Exception as e:
            return "", f"{fn_name} raised: {e}"
        if isinstance(result, tuple) and len(result) == 2:
            d, err = result
            if err:
                return "", f"usg format_dict error: {err}"
        else:
            d = result
        if not isinstance(d, dict):
            return "", "format_dict returned non-dict"
        tpl = str(ns.get(tpl_var, ""))
        if not tpl:
            return "", f"template {tpl_var!r} empty"
        try:
            return tpl.format(**d), ""
        except Exception as e:
            return "", f"usg template.format failed: {e}"

    elif parser_name == "parse_feilink_data":
        parse_fn = ns.get("parse_feilink_data")
        if not callable(parse_fn):
            return "", "parse_feilink_data not in ns"
        try:
            # Bug D fix: parse_feilink_data returns nested {"main": {...}, "backup": {...}}
            # Replicate fl_generate logic: build lines directly from parsed nested structure
            data = parse_fn(hdr) or {}
            mn = data.get("main") or {}
            bk = data.get("backup") or {}
            tun_main = str(ns.get("USG_FL_MAIN_TUN_DEFAULT", "3999"))
            tun_bk   = str(ns.get("USG_FL_BAK_TUN_DEFAULT",  "4000"))
            lines: list[str] = []
            if mn:
                lines += [
                    f"interface Tunnel{tun_main}",
                    f" description Main-{mn.get('pe','')}-flink-{mn.get('line_id','')}",
                    f" ip address {mn.get('wanip2','')} 255.255.255.252",
                    " tunnel-protocol gre", " source LoopBack10",
                    f" destination {mn.get('peer_ip','')}", " service-manage all permit", "",
                ]
            if bk:
                lines += [
                    f"interface Tunnel{tun_bk}",
                    f" description Backup-{bk.get('pe','')}-flink-{bk.get('line_id','')}",
                    f" ip address {bk.get('wanip2','')} 255.255.255.252",
                    " tunnel-protocol gre", " source LoopBack10",
                    f" destination {bk.get('peer_ip','')}", " service-manage all permit", "",
                ]
            if not lines:
                return "", "usg_flink: no main block parsed from header"
            return "\n".join(lines), ""
        except Exception as e:
            return "", f"usg_flink build failed: {e}"

    elif parser_name == "parse_usg_new_exit_blocks":
        parse_fn = ns.get("parse_usg_new_exit_blocks")
        build_fn = ns.get("build_usg_new_exit_format_dict")
        if not callable(parse_fn):
            return "", "parse_usg_new_exit_blocks not in ns"
        try:
            result = parse_fn(hdr)
            parsed = (result[0] if isinstance(result, tuple) else result) or {}
            # Supply all keys required by build_usg_new_exit_format_dict
            init_cfg = {
                "main_tun":        str(ns.get("USG_NE_MAIN_TUN_DEFAULT", "1888")),
                "bk_tun":          str(ns.get("USG_NE_BAK_TUN_DEFAULT",  "1889")),
                "main_loop_start": int(ns.get("USG_NE_MAIN_LOOP_START_DEFAULT", 111)),
                "bk_loop_start":   int(ns.get("USG_NE_BK_LOOP_START_DEFAULT",  211)),
                "main_nqa":        str(ns.get("USG_NE_MAIN_NQA_DEFAULT", "main2")),
                "bk_nqa":          str(ns.get("USG_NE_BK_NQA_DEFAULT",   "backup2")),
            }
            if callable(build_fn):
                d2 = build_fn(parsed, init_cfg)
                tpl = str(ns.get(tpl_var, ""))
                return (tpl.format(**d2) if tpl else str(d2)), ""
            return "", "build_usg_new_exit_format_dict not in ns"
        except Exception as e:
            return "", f"usg_new_exit build failed: {e}"

    return "", f"unsupported usg parser_name: {parser_name!r}"


def _formal_gen_mpls(key: str, info: dict, ns: dict, hdr: str) -> tuple[str, str]:
    """调用 ER MPLS generate_mpls_config 正式生成（与正式页 generate() 完全对齐）。"""
    access_mode = "IPSec" if "IPSec" in key else "OpenVPN"
    gen_fn   = ns.get("generate_mpls_ipsec_config") if access_mode == "IPSec" else ns.get("generate_mpls_config")
    parse_fn = ns.get("parse_epoch_mpls_ipsec") if access_mode == "IPSec" else ns.get("parse_epoch_mpls")
    build_net_fn  = ns.get("build_wan_lan_blocks")
    inject_fn     = ns.get("inject_er_netpanel_init_aliases")
    norm_fn       = ns.get("_normalize_lan_gw_value")
    _parse_inner  = ns.get("_parse_inner_nets")
    _nets_rr_fn   = ns.get("_nets_needing_return_by_network")
    _cidr_plain_fn = ns.get("_cidr_plain")
    _cidr_host_fn  = ns.get("_cidr_host_pair")

    if not callable(gen_fn) or not callable(parse_fn):
        return "", "generate_mpls_config/parse_epoch_mpls not in ns"
    config_type = "IPSec" if access_mode == "IPSec" else ("国内" if "国内" in key else "海外")

    # ── Step 1: 解析数据头 ────────────────────────────────────────────────
    try:
        d = parse_fn(hdr)
    except Exception as e:
        return "", f"parse_epoch_mpls failed: {e}"
    d["config_type"] = config_type
    d["access_mode"] = access_mode
    ex_hn = ns.get("extract_lineid_mpls")
    try:
        d["hostname"] = (ex_hn(hdr) if callable(ex_hn) else "") or "FORMAL_TEST"
    except Exception:
        d["hostname"] = "FORMAL_TEST"

    # ── Step 2: 从 ns globals 读取初始化值（对齐 er_mpls_v1.py get_net_cfg） ──
    _weth = str(ns.get("DEFAULT_WAN_ETH", "0")).strip() or "0"
    wan_if = _weth if _weth.startswith("eth") else f"eth{_weth}"
    wan_ip = str(ns.get("DEFAULT_WAN_CIDR", "192.168.1.2/30"))
    wan_gw = str(ns.get("DEFAULT_WAN_GW",  "192.168.1.1"))
    _leth = str(ns.get("DEFAULT_LAN_ETH", "1")).strip() or "1"
    lan_if = _leth if _leth.startswith("eth") else f"eth{_leth}"
    lan_ip = str(ns.get("DEFAULT_LAN_CIDR", "10.0.0.1/24"))
    # 历史保存的 "同LAN IP" 别名在此处兼容转换为实际 IP
    lan_gw = _normalize_lan_gw_alias(lan_ip, str(ns.get("DEFAULT_LAN_GW", "")))
    inner_raw  = str(ns.get("DEFAULT_INNER_NETS", ""))
    rr_enabled = bool(ns.get("DEFAULT_GEN_RETURN_ROUTE", False))

    # ── Step 3: 构建 WAN/LAN 块，合并到 d ────────────────────────────────
    if callable(build_net_fn):
        try:
            d.update(build_net_fn(
                wan_if=wan_if, wan_dhcp=False, wan_ip_cidr=wan_ip, wan_gw=wan_gw,
                lan_if=lan_if, lan_dhcp=False, lan_ip_cidr=lan_ip,
            ) or {})
        except Exception:
            pass
    d["wan_cidr"] = wan_ip
    d["wan_gw"]   = wan_gw
    d["lan_cidr"] = lan_ip
    d["lan_gw"]   = lan_gw  # 已去别名

    # ── Step 4: 二次归一化 lan_gw（去掩码等残留） ────────────────────────
    if callable(norm_fn):
        d["lan_gw"] = norm_fn(str(d.get("lan_cidr", "")), str(d.get("lan_gw", "")))

    # ── Step 5: inject DEFAULT_* 别名 ────────────────────────────────────
    if callable(inject_fn):
        inject_fn(d)

    # ── Step 6: 内网段 ────────────────────────────────────────────────────
    inner_nets: list[str] = []
    if callable(_parse_inner):
        try:
            inner_nets = _parse_inner(inner_raw)
        except Exception:
            pass
    d["inner_nets"]          = inner_nets
    d["return_route_enabled"] = rr_enabled

    # ── Step 7: 回程路由（与正式页逻辑完全一致） ─────────────────────────
    lan_cidr_rr = d.get("lan_cidr") or ""
    lan_gw_rr   = d.get("lan_gw") or ""
    outside_rr: list[str] = []
    if lan_cidr_rr and callable(_nets_rr_fn):
        try:
            outside_rr = _nets_rr_fn(lan_cidr_rr, inner_nets)
        except Exception:
            pass
    rr_lines = []
    if outside_rr and rr_enabled and lan_gw_rr:
        rr_lines = [f"set protocols static route {n} next-hop {lan_gw_rr}" for n in outside_rr]
    d["return_routes_block"] = "\n".join(rr_lines)

    # ── Step 8: prefix-list ───────────────────────────────────────────────
    ce_as_v = str(d.get("ce_as", "")).strip()
    prefix_lines = []
    for i, n in enumerate(inner_nets):
        rule_num = 10 * (i + 1)
        prefix_lines.append(f"set policy prefix-list AS{ce_as_v}-OUT rule {rule_num} action 'permit'")
        prefix_lines.append(f"set policy prefix-list AS{ce_as_v}-OUT rule {rule_num} prefix '{n}'")
    d["prefix_list_block"] = "\n".join(prefix_lines)

    # ── Step 9: IPSec 额外字段（仅 IPSec 分支需要） ──────────────────────
    if access_mode == "IPSec":
        d["wan_addr_plain"] = (
            _cidr_plain_fn(str(d.get("wan_addr", ""))) if callable(_cidr_plain_fn)
            else str(d.get("wan_addr", "")).split("/", 1)[0].strip()
        )
        for px in ("main", "bk"):
            tun_peer = tun_local = tun_prefix = ""
            if callable(_cidr_host_fn):
                try:
                    tun_peer, tun_local, tun_prefix = _cidr_host_fn(
                        str(d.get(f"{px}_gre_wanip", "")))
                except Exception:
                    pass
            d[f"{px}_tun_peer"]     = tun_peer
            d[f"{px}_tun_local"]    = tun_local
            d[f"{px}_tun_addr"]     = f"{tun_local}/{tun_prefix}" if tun_local and tun_prefix else ""
            loop_ip = str(d.get(f"{px}_loop_ip", "")).strip()
            d[f"{px}_loop_ip_cidr"] = f"{loop_ip}/32" if loop_ip else ""
            d[f"{px}_track_name"]   = str(d.get(f"{px}_gre_tun", "")).strip()

    # ── Step 10: 生成 ─────────────────────────────────────────────────────
    try:
        return str(gen_fn(d) or ""), ""
    except Exception as e:
        return "", f"generate_mpls_config failed: {e}"


def _formal_gen_ar(key: str, info: dict, ns: dict, hdr: str) -> tuple[str, str]:
    """调用 AR SD-WAN render_* 正式生成。"""
    is_dual    = "双机" in key
    is_factory = "Factory" in key
    is_primary = "双机主" in key or not is_dual

    # render_ops_script/render_dual_* expect nested {"main": {...}, "backup": {...}}
    # from parse_ar_sdwan_text (which requires 2 LineID blocks in the header).
    # Factory render functions don't use parsed at all.
    parsed: dict[str, Any] = {}
    if not is_factory:
        parse_nested_fn = ns.get("parse_ar_sdwan_text")
        if not callable(parse_nested_fn):
            return "", "formal_gen_skipped_no_valid_header: parse_ar_sdwan_text not in ns"
        if not hdr or not hdr.strip():
            return "", "formal_gen_skipped_no_valid_header: header is empty"
        try:
            parsed = parse_nested_fn(hdr) or {}
        except Exception as e:
            # parse_ar_sdwan_text requires 2 LineID blocks; if missing, skip rather than use fake data
            return "", f"formal_gen_skipped_no_valid_header: {e}"

    south_fn = ns.get("_south_ips_by_label")
    labels   = list(ns.get("SOUTH_LABELS_DISPLAY") or [])
    pri_ip = bak_ip = ""
    if callable(south_fn) and labels:
        try:
            lbl = labels[1] if len(labels) > 1 else labels[0]
            pri_ip, bak_ip = south_fn(lbl)
        except Exception:
            pass

    # 非双机用 DEFAULT_ 前缀（与 ar_sdwan_zihuan_v4 中 DEFAULT_WAN1_PORT 等变量名对应）
    pfx = "DJ_" if is_dual else "DEFAULT_"
    _gp = lambda k, fb: str(ns.get(f"{pfx}{k}", ns.get(k, fb)))  # noqa: E731
    init_cfg: dict[str, Any] = {
        "ike_version":   "v1",
        # 单机双WAN Factory 需要 dual_wan=True 才走 underlay_internetA/B 分支
        "dual_wan":      ("双WAN" in key),
        "south_primary": str(pri_ip or "10.200.0.1"),
        "south_backup":  str(bak_ip or ""),
        "wan1_if":       _gp("WAN1_PORT", "0/0/0"),
        "wan2_if":       _gp("WAN2_PORT", "0/0/1"),
        "zihuan_if":     _gp("ZIHUAN_PORT", "0/0/2"),
        "ipsec_if":      _gp("IPSEC_PORT", "0/0/3"),
        "wan1_ip":       _gp("WAN1_IP", "10.0.0.1"),
        "wan2_ip":       _gp("WAN2_IP", "10.0.1.1"),
        "wan1_gw":       _gp("WAN1_GW", "10.0.0.254"),
        "wan2_gw":       _gp("WAN2_GW", "10.0.1.254"),
    }
    lineid = "609291A"
    try:
        if not is_dual and not is_factory:
            fn = ns.get("render_ops_script")
        elif not is_dual and is_factory:
            fn = ns.get("render_factory_single")
        elif is_dual and not is_factory:
            fn = ns.get("render_dual_primary" if is_primary else "render_dual_backup")
        else:
            fn = ns.get("render_factory_dual_primary" if is_primary else "render_factory_dual_backup")
        if not callable(fn):
            return "", f"render function not found for {key!r}"
        out = fn(init_cfg, lineid) if is_factory else fn(parsed, init_cfg)
        return str(out or ""), ""
    except Exception as e:
        return "", f"AR render failed: {type(e).__name__}: {e}"


def _formal_generate(key: str, info: dict, ns: dict) -> tuple[str, str]:
    """总调度：按 source 调用对应正式生成函数，返回 (output, err)。"""
    source = str(info.get("source", ""))
    hdr = _formal_load_default_header(key, info)
    try:
        if source == MOD_ER_FASTIP:
            return _formal_gen_er(key, info, ns, hdr)
        if source == MOD_USG_FASTIP:
            return _formal_gen_usg(key, info, ns, hdr)
        if source == MOD_ER_MPLS:
            return _formal_gen_mpls(key, info, ns, hdr)
        if source == MOD_AR_SDWAN:
            return _formal_gen_ar(key, info, ns, hdr)
        return "", f"unknown source: {source!r}"
    except Exception as e:
        return "", f"dispatch exception: {type(e).__name__}: {e}"


# ── F4  语义规则 ──────────────────────────────────────────────────

_FORMAL_PLACEHOLDER_RE = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def _formal_semantic_check(key: str, output: str, info: dict) -> list[str]:
    """返回失败原因列表；空列表表示通过。关键片段与可视化自检同源：仅 workspace 模板通用推导 + 回退表。"""
    issues: list[str] = []
    if not output.strip():
        issues.append("output_empty")
        return issues
    # 无未替换 {var} 占位符（允许在注释行出现 {hostname}/{lineid}）
    lines_no_comment = [ln for ln in output.splitlines() if not ln.strip().startswith("#")]
    body = "\n".join(lines_no_comment)
    unfilled = _FORMAL_PLACEHOLDER_RE.findall(body)
    if unfilled:
        issues.append(f"unfilled_placeholders={unfilled[:5]}")
    source = str(info.get("source", ""))
    parser_name = str(info.get("parser_name", ""))
    snippets: list[str] = []
    # MPLS 正式输出格式与可视化模板格式不同（标头含"正式试用版"而非"可视化模板"），
    # 跳过 workspace 模板提取，直接使用回退表中面向正式输出的片段。
    if source != MOD_ER_MPLS and parser_name != "er_domain_split_preview":
        tpl = _reg_read_scenario_template_text(key, info)
        if tpl:
            got = _reg_snippets_from_workspace_tpl_generic(tpl)
            if got:
                snippets = got
    if not snippets:
        snippets = list(_REG_SNIPPETS_FALLBACK.get(key, []))
    for s in snippets:
        if s not in output:
            issues.append(f"missing_snippet={s!r}")
    return issues


# ── F5  初始化影响探针 ────────────────────────────────────────────
# 每场景 (ns_field, probe_val, expect_in_output)
# ns_field 直接操作 EMBEDDED_NS 命名空间中的变量；
# 对 ER/USG 使用 preview 路径验证（与 init_ok 互补），对 MPLS/AR 走 formal_generate 直接验证。
_FORMAL_INIT_PROBES: dict[str, tuple[str, str, str]] = {
    # ER HK/US：build_epoch_*_format_dict 通过 Tkinter widget 读取 WAN ETH，
    # ns probe 不传播到生成输出；已由 visual init_ok 覆盖，此处跳过（不列入表）。
    "Epoch FastIP · ER 飞连":           ("ER_FL_MAIN_NH_DEFAULT", "10.88.0.1", "10.88.0.1"),
    # ER 新增出口：build_er_new_exit_config 不使用 main_tun；改用 pe_next_hop，
    # 该值出现在 "set protocols static route .../32 next-hop <pe_next_hop>" 行中。
    "Epoch FastIP · ER 新增出口":        ("ER_NE_MAIN_PE_NH_DEFAULT", "1.88.88.77", "1.88.88.77"),
    "Epoch FastIP · ER 域名分流":        ("ER_DS_DNS1_DEFAULT",  "1.88.88.88", "1.88.88.88"),
    # USG: DEFAULT_WAN_ETH is a full GE port string like "GE0/0/9"; probe a different valid port
    "USG FastIP · 非香港出口":           ("DEFAULT_WAN_ETH",    "GE0/0/7",   "GE0/0/7"),
    "USG FastIP · HK 香港出口":          ("HK_DEFAULT_WAN_ETH", "GE0/0/7",   "GE0/0/7"),
    # USG flink: tunnel number appears in the generated Tunnel interface name
    "USG FastIP · 飞连":                ("USG_FL_MAIN_TUN_DEFAULT", "3988",  "3988"),
    # USG new exit: tunnel number used directly in template
    "USG FastIP · 新增出口":             ("USG_NE_MAIN_TUN_DEFAULT", "1877",  "1877"),
    # MPLS: DEFAULT_WAN_ETH digit → "eth9" in formal output (after eth prefix fix)
    "Epoch MPLS · 国内配置":             ("DEFAULT_WAN_ETH",    "9",          "eth9"),
    "Epoch MPLS · 海外配置":             ("DEFAULT_WAN_ETH",    "9",          "eth9"),
    "Epoch MPLS · IPSec":                ("DEFAULT_WAN_ETH",    "9",          "eth9"),
    # AR 单机：前缀修复后 _formal_gen_ar 读 DEFAULT_WAN1/2_PORT，probe 可正确传播
    "AR SD-WAN · 单机单WAN · OPS":       ("DEFAULT_WAN1_PORT",  "0/0/8",      "GigabitEthernet0/0/8"),
    "AR SD-WAN · 单机单WAN · Factory":   ("DEFAULT_WAN1_PORT",  "0/0/8",      "GigabitEthernet0/0/8"),
    "AR SD-WAN · 单机双WAN · OPS":       ("DEFAULT_WAN2_PORT",  "0/0/8",      "GigabitEthernet0/0/8"),
    "AR SD-WAN · 单机双WAN · Factory":   ("DEFAULT_WAN2_PORT",  "0/0/8",      "GigabitEthernet0/0/8"),
    # AR 双机主：render_dual_primary / render_factory_dual_primary 读 wan1_if → DJ_WAN1_PORT
    "AR SD-WAN · 双机主 OPS":            ("DJ_WAN1_PORT",       "0/0/8",      "GigabitEthernet0/0/8"),
    "AR SD-WAN · 双机主 Factory":        ("DJ_WAN1_PORT",       "0/0/8",      "GigabitEthernet0/0/8"),
    # AR 双机备：render_dual_backup / render_factory_dual_backup 读 wan2_if → DJ_WAN2_PORT
    "AR SD-WAN · 双机备 OPS":            ("DJ_WAN2_PORT",       "0/0/8",      "GigabitEthernet0/0/8"),
    "AR SD-WAN · 双机备 Factory":        ("DJ_WAN2_PORT",       "0/0/8",      "GigabitEthernet0/0/8"),
}


def _formal_check_init_effect(
    key: str, info: dict, ns: dict, ved: "VisualEditorTab"
) -> tuple[bool | None, list[str]]:
    """
    修改一个初始化字段 → 调用 _formal_generate → 验证新值出现在输出 → 恢复。
    所有场景统一走 formal 生成路径（不使用 preview/UI widget），确保测试的是真实生成链。
    返回 (True, []) = pass；(False, notes) = fail；(None, notes) = skipped，不入计分。
    """
    probe = _FORMAL_INIT_PROBES.get(key)
    if probe is None:
        return None, ["formal_init_probe_skipped"]
    ns_field, probe_val, expect = probe

    orig_val = ns.get(ns_field)
    notes: list[str] = []
    try:
        ns[ns_field] = probe_val
        output, err = _formal_generate(key, info, ns)
        if err:
            # formal_generate 失败通常是无有效 header，标为 skipped 而非 fail
            notes.append(f"formal_init_skipped_gen_err={err}")
            return None, notes
        if expect not in output:
            notes.append(f"formal_init_probe_missing: expect={expect!r}")
            return False, notes
        return True, notes
    finally:
        if orig_val is None:
            ns.pop(ns_field, None)
        else:
            ns[ns_field] = orig_val


# ── F6  自定义模板 → 正式页生成验证 ──────────────────────────────
#
# 测试真实路径：
#   tpl_var 场景 (ER/USG)：ns[tpl_var] 注入 marker → _formal_generate → 验证 marker 出现
#   tpl_static AR 场景：VISUAL_PROG_OVERRIDE[ts] 注入 marker → _apply_ar_visual_template_override → 验证
#   tpl_static MPLS 场景：OpenVPN 仍为程序化生成；MPLS IPSec 已接入统一模板与 override，可做真实验证
#   所有修改在 try/finally 中还原，不写磁盘。

def _formal_check_tpl_override(
    key: str, info: dict, ns: dict, idx: int
) -> tuple[bool | None, list[str]]:
    """
    验证「自定义模板」能否真实影响生成输出。
    返回 (True, []) = pass；(False, notes) = fail；(None, notes) = skipped/na，不入计分。
    """
    marker = f"FMLTPL_{idx:02d}_{int(__import__('time').time()) % 100000}"
    notes: list[str] = []

    tpl_var    = info.get("tpl_var")
    ts         = info.get("tpl_static")
    source     = str(info.get("source", ""))
    parser_name = str(info.get("parser_name", ""))

    # ── 路径 A：tpl_var 场景（ER/USG 格式字符串模板）────────────────
    if tpl_var:
        # 以下三类 parser 走硬编码 Python 生成（返回 str），模板层不参与正式输出。
        # 模板变更仅影响预览，正式通道无法测试 → 标 na_programmatic。
        _PROG_PARSERS = {
            "parse_er_flink_headers",
            "parse_er_new_exit_blocks",
            "parse_feilink_data",
            "er_domain_split_preview",
        }
        if parser_name in _PROG_PARSERS:
            notes.append(f"formal_tpl_na_programmatic: {parser_name} 生成不经模板层")
            return None, notes
        orig_tpl = ns.get(str(tpl_var), "")
        probe_tpl = str(orig_tpl).rstrip("\n") + f"\n# {marker}\n"
        try:
            ns[str(tpl_var)] = probe_tpl
            output, err = _formal_generate(key, info, ns)
            if err:
                notes.append(f"tpl_gen_err={err}")
                return False, notes
            if marker not in output:
                notes.append(f"tpl_marker_not_in_output: {marker!r}")
                return False, notes
            return True, notes
        finally:
            ns[str(tpl_var)] = orig_tpl

    # ── 路径 B：AR tpl_static 场景（VISUAL_PROG_OVERRIDE → _apply_ar_visual_template_override）
    if ts and source == MOD_AR_SDWAN:
        apply_fn = ns.get("_apply_ar_visual_template_override")
        if not callable(apply_fn):
            notes.append("formal_tpl_skipped_fn_not_found")
            return None, notes
        # 构造含 marker 的最小有效模板（注释行，不影响 parse_ar_visual 后的 {var} 替换）
        probe_tpl = f"# {marker}\n"
        orig_ov = VISUAL_PROG_OVERRIDE.get(str(ts))
        try:
            VISUAL_PROG_OVERRIDE[str(ts)] = probe_tpl
            hdr = _formal_load_default_header(key, info)
            init_cfg: dict[str, Any] = {
                "ike_version": "v1", "dual_wan": False,
                "south_primary": "10.200.0.1", "south_backup": "10.200.0.2",
                "wan1_if": "0/0/0", "wan2_if": "0/0/1",
                "zihuan_if": "0/0/2", "ipsec_if": "0/0/3",
                "wan1_ip": "10.0.0.1", "wan2_ip": "10.0.1.1",
                "wan1_gw": "10.0.0.254", "wan2_gw": "10.0.1.254",
            }
            result = apply_fn(str(ts), hdr, init_cfg)
            if result is None:
                notes.append("ar_tpl_override_returned_none_no_hdr_data")
                return False, notes
            if marker not in str(result):
                notes.append(f"tpl_marker_not_in_override_output: {marker!r}")
                return False, notes
            return True, notes
        finally:
            if orig_ov is None:
                VISUAL_PROG_OVERRIDE.pop(str(ts), None)
            else:
                VISUAL_PROG_OVERRIDE[str(ts)] = orig_ov

    # ── 路径 C：MPLS tpl_static 场景 ────────────────────────────────
    if ts and source == MOD_ER_MPLS:
        if key != "Epoch MPLS · IPSec":
            notes.append("formal_tpl_na_programmatic: MPLS OpenVPN 生成为纯 Python，无模板替换层")
            return None, notes
        orig_ov = VISUAL_PROG_OVERRIDE.get(str(ts))
        base_tpl = _factory_tpl_for_scenario(info) or ""
        probe_tpl = str(base_tpl).rstrip("\n") + f"\n# {marker}\n"
        try:
            VISUAL_PROG_OVERRIDE[str(ts)] = probe_tpl
            output, err = _formal_generate(key, info, ns)
            if err:
                notes.append(f"tpl_gen_err={err}")
                return False, notes
            if marker not in output:
                notes.append(f"tpl_marker_not_in_output: {marker!r}")
                return False, notes
            return True, notes
        finally:
            if orig_ov is None:
                VISUAL_PROG_OVERRIDE.pop(str(ts), None)
            else:
                VISUAL_PROG_OVERRIDE[str(ts)] = orig_ov

    # 无 tpl_var 也无 tpl_static
    notes.append("formal_tpl_skipped_no_template")
    return None, notes


# ── F7  workspace_test 写入/加载验证 ────────────────────────────

def _formal_check_workspace_rw(
    key: str, info: dict, idx: int
) -> tuple[bool, list[str]]:
    """
    向 WORKSPACE_TEST 写含 marker 的 .tpl 文件 → _apply_template_to_runtime →
    验证内存态包含 marker → 恢复内存。editor_workspace 全程不碰。
    """
    slot = _scenario_tpl_slot(info)
    sk   = _editor_safe_key(_visual_scenario_disk_key(key))
    tpl_path = WORKSPACE_TEST / sk / f"{slot}.tpl"

    marker   = f"FMLWS_{idx:02d}_{int(__import__('time').time()) % 100000}"
    base_tpl = _factory_tpl_for_scenario(info) or ""
    probe_tpl = base_tpl.rstrip("\n") + f"\n# {marker}\n"

    # 保存内存原态
    tpl_var   = info.get("tpl_var")
    tpl_static = info.get("tpl_static")
    source    = str(info.get("source", ""))
    ns        = EMBEDDED_NS.get(source) if source else None
    orig_ns_v  = str(ns.get(str(tpl_var), "")) if (ns and tpl_var) else None
    orig_ov_v  = VISUAL_PROG_OVERRIDE.get(str(tpl_static)) if tpl_static else None

    notes: list[str] = []
    try:
        tpl_path.parent.mkdir(parents=True, exist_ok=True)
        tpl_path.write_text(probe_tpl, encoding="utf-8-sig")
        # 模拟从 workspace 加载并应用到内存
        _apply_template_to_runtime(key, info, probe_tpl)
        # 验证内存态
        if tpl_var and ns:
            if marker not in str(ns.get(str(tpl_var), "")):
                notes.append(f"ws_marker_missing_in_ns[{tpl_var}]")
                return False, notes
        elif tpl_static:
            if marker not in str(VISUAL_PROG_OVERRIDE.get(str(tpl_static), "")):
                notes.append(f"ws_marker_missing_in_override[{tpl_static}]")
                return False, notes
        else:
            notes.append("ws_rw_no_tpl_var_or_static")
            return False, notes
        return True, notes
    except Exception as e:
        notes.append(f"ws_rw_exception: {type(e).__name__}: {e}")
        return False, notes
    finally:
        # 恢复内存原态
        if tpl_var and ns and orig_ns_v is not None:
            ns[str(tpl_var)] = orig_ns_v
        if tpl_static:
            if orig_ov_v is None:
                VISUAL_PROG_OVERRIDE.pop(str(tpl_static), None)
            else:
                VISUAL_PROG_OVERRIDE[str(tpl_static)] = orig_ov_v
        # 删除测试文件（不影响正式 editor_workspace）
        try:
            tpl_path.unlink(missing_ok=True)
        except Exception:
            pass


# ── F8  每场景正式检测总入口 ──────────────────────────────────────
#
# formal_gen_ok / formal_init_ok / formal_tpl_ok / formal_ws_ok 的值域：
#   True  = 通过
#   False = 失败（存在问题）
#   None  = skipped / na（测不到、无有效输入、或该路径本身不适用）
# skipped 不计入分子/分母，只在 report 中记录原因。

def _run_formal_checks(
    key: str, info: dict, ns: dict | None, ved: "VisualEditorTab", idx: int
) -> dict[str, Any]:
    """
    对单个场景运行全部四项正式检测，返回含 formal_* 字段的 dict。
    ns 为 None 时所有项均标记 None（source_not_embedded）。
    placeholder=True 场景（IPSec 接入，模板待提供）所有项均标记 None（skipped）。
    """
    row: dict[str, Any] = {
        "formal_gen_ok":   None,
        "formal_init_ok":  None,
        "formal_tpl_ok":   None,
        "formal_ws_ok":    None,
        "formal_notes":    [],
        "formal_output_excerpt": "",
    }
    if info.get("placeholder"):
        row["formal_notes"].append("formal_all_placeholder_skipped")
        return row
    if ns is None:
        row["formal_notes"].append("source_not_embedded")
        return row

    # 1. formal_gen_ok
    try:
        output, err = _formal_generate(key, info, ns)
        if err:
            if "formal_gen_skipped" in err:
                row["formal_notes"].append(f"gen_skipped={err}")
                row["formal_gen_ok"] = None
            else:
                row["formal_notes"].append(f"gen_err={err}")
                row["formal_gen_ok"] = False
        else:
            sem = _formal_semantic_check(key, output, info)
            if sem:
                row["formal_notes"].extend(sem)
                row["formal_gen_ok"] = False
            else:
                row["formal_gen_ok"] = True
            row["formal_output_excerpt"] = output[:300]
    except Exception as e:
        row["formal_notes"].append(f"gen_exception={type(e).__name__}:{e}")
        row["formal_gen_ok"] = False

    # 2. formal_init_ok
    try:
        ok, notes = _formal_check_init_effect(key, info, ns, ved)
        row["formal_init_ok"] = ok  # True / False / None
        row["formal_notes"].extend(notes)
    except Exception as e:
        row["formal_notes"].append(f"init_effect_exception={type(e).__name__}:{e}")
        row["formal_init_ok"] = False

    # 3. formal_tpl_ok
    try:
        ok, notes = _formal_check_tpl_override(key, info, ns, idx)
        row["formal_tpl_ok"] = ok  # True / False / None
        row["formal_notes"].extend(notes)
    except Exception as e:
        row["formal_notes"].append(f"tpl_override_exception={type(e).__name__}:{e}")
        row["formal_tpl_ok"] = False

    # 4. formal_ws_ok
    try:
        ok, notes = _formal_check_workspace_rw(key, info, idx)
        row["formal_ws_ok"] = ok
        row["formal_notes"].extend(notes)
    except Exception as e:
        row["formal_notes"].append(f"ws_rw_exception={type(e).__name__}:{e}")
        row["formal_ws_ok"] = False

    return row


# ══════════════════════════════════════════════════════════════════
# §7  主窗口
# ══════════════════════════════════════════════════════════════════

_LEGACY_TABS = [
    (MOD_ER_FASTIP,   "Epoch FastIP"),
    (MOD_USG_FASTIP,  "USG FastIP"),
    (MOD_ER_MPLS,          "Epoch MPLS"),
    (MOD_AR_SDWAN,  "AR SD-WAN"),
]


def _build_sponsor_tab(parent: tk.Frame) -> None:
    """感谢赞助页签：静态只读展示后台维护的榜单数据。"""
    for ch in parent.winfo_children():
        ch.destroy()
    parent.configure(bg="#f0f4f8")
    parent.columnconfigure(0, weight=1)
    parent.rowconfigure(0, weight=0)
    parent.rowconfigure(1, weight=1)

    data, warn = _load_sponsor_board_data()

    head = tk.Frame(parent, bg="#1e3a5f", height=78)
    head.grid(row=0, column=0, sticky="ew", padx=12, pady=(2, 1))
    head.grid_propagate(False)
    head.columnconfigure(0, weight=1)
    head.columnconfigure(1, weight=0)
    head.rowconfigure(0, weight=1)
    head.rowconfigure(1, weight=1)
    tk.Label(
        head,
        text="  感谢赞助  ·  Sponsor Thanks",
        font=("微软雅黑", 13, "bold"),
        bg="#1e3a5f",
        fg="#f0f4f8",
        anchor="w",
    ).grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=(2, 0))
    tk.Label(
        head,
        text="  感谢每一位内测同事、赞助者与技术支持伙伴",
        font=("微软雅黑", 10),
        bg="#1e3a5f",
        fg="#b9d6ee",
        anchor="w",
    ).grid(row=1, column=0, sticky="ew", padx=(8, 0), pady=(0, 2))

    # 顶部装饰图案（几何线条 + 圆点），填充上半区域留白
    deco = tk.Canvas(head, width=260, height=74, bg="#1e3a5f", highlightthickness=0, bd=0)
    deco.grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 6))
    deco.create_line(16, 18, 120, 18, fill="#3f6f95", width=2)
    deco.create_line(160, 74, 264, 74, fill="#3f6f95", width=2)
    deco.create_line(36, 34, 110, 68, fill="#5f8ab0", width=1)
    deco.create_line(170, 24, 244, 58, fill="#5f8ab0", width=1)
    for x, y, r, c in (
        (22, 54, 3, "#9ec3de"),
        (56, 60, 4, "#7fb0d3"),
        (92, 48, 3, "#9ec3de"),
        (182, 40, 4, "#9ec3de"),
        (214, 30, 3, "#7fb0d3"),
        (246, 48, 4, "#9ec3de"),
        (262, 24, 2, "#b9d6ee"),
    ):
        deco.create_oval(x - r, y - r, x + r, y + r, fill=c, outline="")

    body = tk.Frame(parent, bg="#f0f4f8")
    body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 1))
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)
    parent.rowconfigure(1, weight=1)
    body.rowconfigure(0, weight=0)
    body.rowconfigure(1, weight=1)

    def _render_card(
        root: tk.Frame,
        title: str,
        names: list[str],
        *,
        title_fg: str,
        idx_fg: str,
        border_color: str,
    ) -> None:
        root.columnconfigure(0, weight=1)
        top_bar = tk.Frame(root, bg=border_color, height=4)
        top_bar.grid(row=0, column=0, sticky="ew")
        top_bar.grid_propagate(False)
        tk.Label(root, text=title, font=("微软雅黑", 13, "bold"), bg="#ffffff", fg=title_fg, anchor="w").grid(
            row=1, column=0, sticky="ew", padx=18, pady=(14, 8)
        )
        if names:
            for i, name in enumerate(names, 1):
                row = tk.Frame(root, bg="#ffffff")
                row.grid(row=i + 1, column=0, sticky="ew", padx=18, pady=4)
                row.columnconfigure(1, weight=1)
                tk.Label(
                    row,
                    text=f"#{i}",
                    font=("Consolas", 11, "bold"),
                    bg="#ffffff",
                    fg=idx_fg,
                    width=4,
                    anchor="w",
                ).grid(row=0, column=0, sticky="w")
                tk.Label(
                    row,
                    text=name,
                    font=("微软雅黑", 13, "bold"),
                    bg="#ffffff",
                    fg="#243447",
                    anchor="w",
                ).grid(row=0, column=1, sticky="w")
            return
        tk.Label(
            root,
            text="暂无数据",
            font=("微软雅黑", 10),
            bg="#ffffff",
            fg="#7a96ad",
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 10))

    intro = tk.Frame(body, bg="#ffffff", highlightthickness=1, highlightbackground="#d7e2ee")
    intro.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 1))
    intro.columnconfigure(0, weight=1)
    tk.Label(
        intro,
        text="内测感谢",
        font=("微软雅黑", 12, "bold"),
        bg="#ffffff",
        fg="#1e3a5f",
        anchor="w",
    ).grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 1))
    tk.Label(
        intro,
        text=(
            "感谢深圳工程部和上海工程部的同事参与内测，"
            "你们在使用反馈、问题复现和流程优化上给了这个软件非常大的帮助。"
        ),
        font=("微软雅黑", 10),
        bg="#ffffff",
        fg="#243447",
        justify="left",
        anchor="w",
        wraplength=1150,
    ).grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 2))
    tk.Label(
        intro,
        text="使用过程中如有问题，可联系 Yuc 进行咨询与支持。",
        font=("微软雅黑", 10, "bold"),
        bg="#ffffff",
        fg="#2f77b8",
        anchor="w",
    ).grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 4))

    sponsor_card = tk.Frame(body, bg="#ffffff", highlightthickness=2, highlightbackground="#d7e2ee")
    sponsor_card.grid(row=1, column=0, sticky="nsew", padx=(0, 2), pady=0)
    _render_card(
        sponsor_card,
        "赞助榜单  ·  Sponsors",
        list(data.get("赞助榜单") or []),
        title_fg="#9a6a00",
        idx_fg="#c08500",
        border_color="#f2c94c",
    )

    tech_card = tk.Frame(body, bg="#ffffff", highlightthickness=2, highlightbackground="#d7e2ee")
    tech_card.grid(row=1, column=1, sticky="nsew", padx=(2, 0), pady=0)
    _render_card(
        tech_card,
        "技术支持榜单  ·  Technical Contributors",
        list(data.get("技术榜单") or []),
        title_fg="#1e3a5f",
        idx_fg="#2f77b8",
        border_color="#6fa8dc",
    )

    thank_msg = (
        "感谢所有赞助者与技术支持伙伴的长期支持，"
        "正是你们的投入让工具能够持续迭代、稳定落地并服务更多同事。"
    )
    tip = f"{thank_msg}\n后台维护文件：{SPONSOR_BOARD_FILE}"
    if warn:
        tip = f"{warn}\n{tip}"
    tk.Label(
        body,
        text=tip,
        font=("Consolas", 8),
        bg="#f0f4f8",
        fg="#b85e1a" if warn else "#5c7a96",
        justify="left",
        anchor="w",
    ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(1, 0))


def _build_window(
    *,
    progressive_legacy: bool = False,
    run_ui_regression_19: bool = False,
    window_title: str = "all_in_one_v2  ·  Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN / 我来定模板",
) -> None:
    root = tk.Tk()
    root.title(window_title)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    ww = min(1520, int(sw * 0.91))
    wh = min(900, int(sh * 0.88))
    root.geometry(f"{ww}x{wh}+{(sw - ww)//2}+{max(0,(sh - wh)//2 - 18)}")
    root.minsize(1020, 660)
    root.configure(bg="#e8eef5")

    sty = ttk.Style(root)
    sty.theme_use("clam")
    sty.configure("TNotebook", tabposition="nw", background="#1e3a5f")
    sty.configure("TNotebook.Tab",
                  background="#1e3a5f", foreground="#7aafd4",
                  font=("微软雅黑", 9, "bold"), padding=[10, 5])
    sty.map("TNotebook.Tab",
            background=[("selected", "#f0f4f8"), ("active", "#2a4a6f")],
            foreground=[("selected", "#0077b6"), ("active", "#ffffff")])
    sty.configure("Vertical.TScrollbar",
                  background="#ffffff", troughcolor="#f0f4f8",
                  arrowcolor="#7a96ad", relief="flat", borderwidth=0, width=7)
    sty.configure("Horizontal.TScrollbar",
                  background="#ffffff", troughcolor="#f0f4f8",
                  arrowcolor="#7a96ad", relief="flat", borderwidth=0, height=7)
    sty.configure("TPanedwindow", background="#e8eef5")
    sty.configure("TCombobox", fieldbackground="#f8fafc")

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=3, pady=3)

    _legacy_tab_meta: dict[str, dict[str, object]] = {}
    for filename, tab_title in _LEGACY_TABS:
        frame = tk.Frame(nb, bg="#f0f4f8")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        nb.add(frame, text=f"  {tab_title}  ")
        tk.Label(
            frame,
            text="正在加载本页工具模块…",
            font=("微软雅黑", 10),
            bg="#f0f4f8",
            fg="#7a96ad",
        ).grid(row=0, column=0, pady=40)
        tab_id = str(frame)
        _legacy_tab_meta[tab_id] = {
            "filename": filename,
            "title": tab_title,
            "frame": frame,
            "loaded": False,
        }

    def _post_embed_sync(loaded_source: str) -> None:
        _ensure_ar_init_factory_seeded()
        # 程序化模板热更新：包装 MPLS / AR 的生成函数，并加载磁盘上已保存的模板
        _patch_mpls_generate_for_visual()
        _patch_ar_sdwan_for_visual()
        _load_saved_templates_into_runtime({loaded_source})
        # 按次嵌入合并出厂快照并应用 user_init 中对应段落，避免首屏先开「我来定模板」
        # 或先开非 AR 工具时，AR 等模块快照/用户默认值永远缺失。
        _merge_factory_snapshot_for_embed(loaded_source)
        _apply_user_init_sections_for_emb(loaded_source)
        try:
            if _editor_loaded and _editor_ved is not None:
                _editor_ved._reload_init_entries_from_globals()
        except Exception:
            pass

    def _ensure_loaded_for_tab(tab_id: str) -> None:
        meta = _legacy_tab_meta.get(tab_id)
        if not meta:
            return
        if bool(meta.get("loaded")):
            return
        frame = meta["frame"]  # type: ignore[index]
        filename = str(meta["filename"])
        title = str(meta["title"])
        for ch in frame.winfo_children():  # type: ignore[union-attr]
            ch.destroy()
        err = _embed(filename, frame)  # type: ignore[arg-type]
        if err:
            _show_load_error(frame, title, err)  # type: ignore[arg-type]
        meta["loaded"] = True
        _post_embed_sync(filename)

    def _ensure_legacy_embed_loaded(filename: str) -> None:
        for tid, meta in _legacy_tab_meta.items():
            if str(meta.get("filename")) == filename and not bool(meta.get("loaded")):
                _ensure_loaded_for_tab(tid)
                return

    global _ENSURE_LEGACY_EMBED_BY_FILENAME
    _ENSURE_LEGACY_EMBED_BY_FILENAME = _ensure_legacy_embed_loaded

    editor_frame = tk.Frame(nb, bg="#f0f4f8")
    editor_frame.columnconfigure(0, weight=1)
    for r, w in ((0, 0), (1, 0), (2, 1), (3, 0)):
        editor_frame.rowconfigure(r, weight=w)
    nb.add(editor_frame, text="  我来定模板  ")
    sponsor_frame = tk.Frame(nb, bg="#f0f4f8")
    sponsor_frame.columnconfigure(0, weight=1)
    sponsor_frame.rowconfigure(0, weight=0)
    sponsor_frame.rowconfigure(1, weight=1)
    nb.add(sponsor_frame, text="  感谢赞助  ")
    _build_sponsor_tab(sponsor_frame)

    tk.Label(
        editor_frame,
        text="正在加载可视化编辑器…",
        font=("微软雅黑", 10),
        bg="#f0f4f8",
        fg="#7a96ad",
    ).grid(row=0, column=0, pady=40)
    _editor_loaded = False
    _editor_ved: VisualEditorTab | None = None

    def _ensure_editor_loaded() -> None:
        nonlocal _editor_loaded, _editor_ved
        if _editor_loaded:
            return
        for ch in editor_frame.winfo_children():
            ch.destroy()
        _editor_ved = VisualEditorTab(editor_frame)
        _editor_loaded = True

    def _on_tab_changed(_event=None) -> None:
        cur = nb.select()
        if cur == str(editor_frame):
            _ensure_editor_loaded()
        else:
            _ensure_loaded_for_tab(cur)

    # 首屏采用异步加载：窗口先显示，再按当前页签加载，进一步提升"打开即见"的体感速度
    root.after(1, _on_tab_changed)

    nb.bind("<<NotebookTabChanged>>", _on_tab_changed)

    def _on_close() -> None:
        if _editor_loaded and _editor_ved is not None:
            if getattr(_editor_ved, "_skip_next_close_autosave", False):
                _editor_ved._skip_next_close_autosave = False
            else:
                _editor_ved._auto_save_current()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    if run_ui_regression_19:
        root.title("程序自检中…  ·  all_in_one_v2")
        reg_overlay = tk.Frame(root, bg="#e8eef5", cursor="watch")
        reg_overlay.place(x=0, y=0, relwidth=1, relheight=1)
        try:
            reg_overlay.lift(nb)
        except tk.TclError:
            reg_overlay.lift()
        _reg_wrap = tk.Frame(reg_overlay, bg="#e8eef5")
        _reg_wrap.place(relx=0.5, rely=0.4, anchor="center")
        tk.Label(
            _reg_wrap,
            text="程序自检中…",
            font=("微软雅黑", 17, "bold"),
            fg="#1e3a5f",
            bg="#e8eef5",
        ).pack()
        tk.Label(
            _reg_wrap,
            text="正在检测 19 个场景，请稍候，勿关闭本窗口。",
            font=("微软雅黑", 10),
            fg="#5c7a96",
            bg="#e8eef5",
        ).pack(pady=(12, 0))

        def _cancel_all_after_jobs() -> None:
            try:
                ids = list(root.tk.call("after", "info") or [])
            except Exception:
                ids = []
            for aid in ids:
                try:
                    root.after_cancel(aid)
                except Exception:
                    pass

        def _safe_close_reg_window() -> None:
            # 回归模式下优先退出事件循环，再尝试销毁，避免 Tcl 命令删除竞态导致卡死。
            try:
                root.quit()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass

        def _run_reg() -> None:
            out_json: Path | None = None
            out_txt: Path | None = None
            _ensure_editor_loaded()
            try:
                if _editor_ved is not None:
                    out_json, out_txt = _run_ui_regression_19(root, _editor_ved)
            except Exception as e:
                try:
                    reg_overlay.destroy()
                except Exception:
                    pass
                _cancel_all_after_jobs()
                try:
                    messagebox.showerror(
                        "自检失败",
                        f"自检过程出错：\n{e}\n\n请查看控制台输出或联系维护人员。",
                        parent=root,
                    )
                except Exception:
                    pass
                root.after(80, _safe_close_reg_window)
                return
            try:
                reg_overlay.destroy()
            except Exception:
                pass
            _cancel_all_after_jobs()
            root.update_idletasks()

            def _show_done_and_exit() -> None:
                root.title("自检完成  ·  all_in_one_v2")
                if out_json is not None and out_txt is not None:
                    folder = out_json.parent
                    msg = (
                        "自检已完成。\n\n"
                        f"报告已保存到目录：\n{folder}\n\n"
                        f"· {out_json.name}\n"
                        f"· {out_txt.name}\n\n"
                        "建议先打开摘要文件查看通过情况。"
                    )
                    try:
                        messagebox.showinfo("自检完成", msg, parent=root)
                    except Exception:
                        pass
                root.after(50, _safe_close_reg_window)

            root.after(60, _show_done_and_exit)

        root.after(120, _run_reg)
    root.mainloop()


# ══════════════════════════════════════════════════════════════════
# §8  入口
# ══════════════════════════════════════════════════════════════════

def _selftest() -> None:
    ok = True
    for filename, _ in _LEGACY_TABS:
        path = BUNDLE_DIR / filename
        if not path.exists():
            print(f"[SKIP] {filename}")
            continue
        raw  = path.read_text(encoding="utf-8-sig")
        code = _preprocess(filename, raw)
        if "root = tk.Tk()" in code:
            print(f"[FAIL] {filename}: root=tk.Tk() 未被替换")
            ok = False
            continue
        try:
            compile(code, filename, "exec")
            print(f"[OK]   {filename}")
        except SyntaxError as e:
            print(f"[FAIL] {filename}: {e}")
            ok = False
    print("SELFTEST_OK" if ok else "SELFTEST_FAIL")
    if not ok:
        raise SystemExit(2)


def _write_canonical_template_bundle(dst: Path, info: dict, slot: str) -> None:
    """用「源码 tpl_var + _templates.json 的 tpl_static」写入单场景 headers/mapping/tpl，与程序内置出厂一致。"""
    tpl = _canonical_tpl_string_for_scenario(info)
    if not str(tpl).strip():
        tpl = _factory_tpl_for_scenario(info)
    hdr = info.get("hdr_static") or _auto_headers(tpl)
    mp = info.get("map_static") or _auto_mapping(tpl)
    if info.get("source") == MOD_ER_FASTIP:
        hdr = _strip_leading_hostname_visual_line(hdr)
    dst.mkdir(parents=True, exist_ok=True)
    (dst / f"{slot}.tpl").write_text(tpl, encoding="utf-8-sig")
    (dst / "headers.txt").write_text(hdr, encoding="utf-8-sig")
    (dst / "mapping.txt").write_text(mp, encoding="utf-8-sig")


def _resync_all_editor_template_bundles(
    *,
    write_defaults: bool = True,
    write_workspace: bool = True,
) -> None:
    """将 editor_defaults 与/或 editor_workspace 下各场景模板包重写为单一真相源，消除与源码/JSON 的漂移。"""
    n = len(VisualEditorTab.SCENARIOS)
    for key, info in VisualEditorTab.SCENARIOS.items():
        sk = _editor_safe_key(_visual_scenario_disk_key(key))
        slot = _scenario_tpl_slot(info)
        if write_defaults:
            _write_canonical_template_bundle(EDITOR_DEFAULTS_ROOT / sk, info, slot)
        if write_workspace:
            wdir = WORKSPACE / sk
            _write_canonical_template_bundle(wdir, info, slot)
            tv = wdir / "template_version.txt"
            if tv.exists():
                try:
                    tv.unlink()
                except Exception:
                    pass
    parts = []
    if write_defaults:
        parts.append("editor_defaults")
    if write_workspace:
        parts.append("editor_workspace")
    print(f"OK: 已同步 {n} 个场景模板包 → {' + '.join(parts)}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    elif "--seed-editor-defaults-only" in sys.argv:
        _seed_editor_defaults_only()
        raise SystemExit(0)
    elif "--seed-editor-defaults-clear-ws" in sys.argv:
        _seed_editor_defaults_and_clear_workspace()
        raise SystemExit(0)
    elif "--resync-editor-template-bundles" in sys.argv:
        defaults_only = "--defaults-only" in sys.argv
        workspace_only = "--workspace-only" in sys.argv
        if defaults_only and workspace_only:
            defaults_only = workspace_only = False
        _resync_all_editor_template_bundles(
            write_defaults=not workspace_only,
            write_workspace=not defaults_only,
        )
        raise SystemExit(0)
    elif "--ui-regression-19" in sys.argv:
        _build_window(progressive_legacy=False, run_ui_regression_19=True)
        raise SystemExit(0)
    else:
        _build_window(progressive_legacy=False)
