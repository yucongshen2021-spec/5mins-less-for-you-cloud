#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""all_in_one web — Flask backend using exec() to load business logic without tkinter mainloop."""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import tkinter_stub as tk
from tkinter_stub import ttk

from flask import Flask, jsonify, render_template, request

# Detect PyInstaller bundle
if getattr(sys, "frozen", False):
    _BUNDLE_DIR = Path(sys._MEIPASS)
    _DATA_RO_DIR = _BUNDLE_DIR / "data"
    # Linux fallback: APPDATA absent → ~/.config
    _data_parent = Path.home() / ".config" if sys.platform != "win32" else (Path.home() / "AppData" / "Roaming")
    _DATA_RW_DIR = Path(os.environ.get("APPDATA", _data_parent)) / "all_in_one" / "data"
    _DATA_RW_DIR.mkdir(parents=True, exist_ok=True)
    # Copy factory defaults on first run
    _src_defaults = _DATA_RO_DIR / "editor_defaults"
    _dst_defaults = _DATA_RW_DIR / "editor_defaults"
    if _src_defaults.is_dir() and not _dst_defaults.is_dir():
        import shutil
        shutil.copytree(str(_src_defaults), str(_dst_defaults))
else:
    _BUNDLE_DIR = Path(__file__).resolve().parent.parent
    _DATA_RO_DIR = _BUNDLE_DIR / "data"
    _DATA_RW_DIR = _BUNDLE_DIR / "data"
SRC_DIR = _BUNDLE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ── 用户 workspace 隔离 ──────────────────────────────────────────────────────
# 每用户独立目录 data/users/<user_id>/，首次访问自动创建并复制出厂模板。
# 用户身份由 portal proxy 注入的 X-User-Id header 确定（不可信）。
# 裸机/test_client（无 X-User-Id）fallback 到 _DATA_RW_DIR（兼容旧数据）。


def _get_request_username() -> str:
    """返回当前请求的 X-Username（由 portal proxy 注入），无请求上下文时返回空串。"""
    try:
        from flask import has_request_context
        if has_request_context():
            return (request.headers.get("X-Username") or "").strip()
    except Exception:
        pass
    return ""


def _get_request_user_id() -> str:
    """返回当前请求的 X-User-Id（由 portal proxy 注入），无请求上下文或访客时返回空串。"""
    try:
        from flask import has_request_context
        if has_request_context():
            return (request.headers.get("X-User-Id") or "").strip()
    except Exception:
        pass
    return ""


_TEMPLATE_ADMIN_USER = "yucs"


def _require_login() -> tuple | None:
    """检查当前用户是否已登录（X-User-Id 非空）。访客返回 (jsonify(...), 403)，已登录返回 None。"""
    uid = _get_request_user_id()
    if not uid:
        return jsonify({"ok": False, "error": "请登录后操作模板编辑器"}), 403
    return None


def _get_user_data_dir() -> Path:
    """返回当前用户的 workspace 目录。无请求上下文时返回默认 _DATA_RW_DIR。"""
    try:
        from flask import has_request_context
        if has_request_context():
            uid = (request.headers.get("X-User-Id") or "").strip()
            if uid:
                u_dir = _DATA_RW_DIR / "users" / uid
                # 首次访问：创建目录 + 复制出厂 editor_defaults
                if not (u_dir / ".init_done").exists():
                    u_dir.mkdir(parents=True, exist_ok=True)
                    src = _DATA_RO_DIR / "editor_defaults"
                    if src.is_dir():
                        import shutil as _shutil
                        dst = u_dir / "editor_defaults"
                        if not dst.is_dir():
                            _shutil.copytree(str(src), str(dst))
                    # 空 user_init_placeholders.json
                    (u_dir / "user_init_placeholders.json").write_text("{}", encoding="utf-8")
                    (u_dir / ".init_done").touch()
                return u_dir
    except Exception:
        pass
    return _DATA_RW_DIR

try:
    from user_activity_log import log_generate_config
except ImportError:
    def log_generate_config(**kwargs): pass

app = Flask(__name__,
            template_folder=str(_BUNDLE_DIR / "web" / "templates"))
app.json.sort_keys = False  # preserve dict insertion order in JSON responses
app.config["TEMPLATES_AUTO_RELOAD"] = True  # reload templates on change

@app.after_request
def _no_cache(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# ── Load embedded modules via exec() (same approach as all_in_one_v2._embed) ──

_EMBEDDED_NS: dict[str, dict] = {}
_FACTORY_INIT_DEFAULTS: dict[str, dict] = {}


def _load_module(filename: str) -> dict:
    """Load a source file via exec() with tkinter stubbed out. Returns namespace dict."""
    if filename in _EMBEDDED_NS:
        return _EMBEDDED_NS[filename]

    path = SRC_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Module not found: {filename}")

    raw = path.read_text(encoding="utf-8-sig")

    # tkinter 已被 tkinter_stub 替代：tk.Tk()/tk.Frame() 等返回 mock 对象，
    # 无需真实 Tk/DISPLAY/Xvfb。源码改写仍保留（root = tk.Tk() → root = __WEB_FRAME__），
    # 现在 __WEB_FRAME__ 是一个 _MockWidget。
    _web_frame = tk.Frame()

    # Preprocess: same as all_in_one_v2._preprocess()
    # - Replace root = tk.Tk() → root = __WEB_FRAME__ (mock widget)
    # - Skip lines between Tk() and root.configure( (title/geometry calls)
    # - Comment out root.mainloop()
    # - Strip ``import tkinter`` / ``from tkinter import ...`` — stub already in ns
    out_lines = []
    in_skip = False
    for line in raw.splitlines(keepends=True):
        s = line.strip()
        if in_skip:
            if s.startswith("root.configure("):
                out_lines.append(line)
                in_skip = False
            continue
        if re.match(r"root\s*=\s*tk\.Tk\(\)\s*$", s):
            out_lines.append("root = __WEB_FRAME__\n")
            in_skip = True
            continue
        if re.match(r"root\.mainloop\(\)\s*$", s):
            out_lines.append("# [web] mainloop omitted\n")
            continue
        # 注释掉 tkinter import（stub 已在 ns 中提供 tk/ttk/messagebox/filedialog）
        if re.match(r"^\s*import\s+tkinter\b", s) or re.match(r"^\s*from\s+tkinter\b", s):
            out_lines.append("# [web] " + line)
            continue
        out_lines.append(line)
    code = "".join(out_lines)

    # Import shared_utils
    import shared_utils as _su

    # Import field_coverage
    fc_path = SRC_DIR / "field_coverage.py"
    fc_mod = None
    if fc_path.is_file():
        spec = importlib.util.spec_from_file_location("_web_field_coverage", fc_path)
        if spec and spec.loader:
            fc_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fc_mod)

    ns = {
        "__builtins__": __builtins__,
        "__name__": "__embedded__",
        "tk": tk,
        "ttk": ttk,
        "tkinter": tk,  # 业务模块的 ``from tkinter import ttk/messagebox/filedialog`` 会走这里
        "filedialog": tk.filedialog,
        "messagebox": tk.messagebox,
        "re": re,
        "sys": sys,
        "ipaddress": __import__("ipaddress"),
        "__TAB_FRAME__": _web_frame,
        "__WEB_ROOT__": _web_frame,
        "__WEB_FRAME__": _web_frame,
        "field_coverage": fc_mod,
        "shared_utils": _su,
        "_get": _su.re_get,
        "re_get": _su.re_get,
        "wanip_hosts": _su.wanip_hosts,
        "parse_inner_nets": _su.parse_inner_nets,
        "_parse_inner_nets": _su.parse_inner_nets,  # alias for er_fastip/er_mpls
        "nets_needing_return_by_network": _su.nets_needing_return_by_network,
        "_nets_needing_return_by_network": _su.nets_needing_return_by_network,  # alias
        "widget_get_value": _su.widget_get_value,
        "widget_set_value": _su.widget_set_value,
    }

    exec(compile(code, str(path), "exec"), ns)
    _EMBEDDED_NS[filename] = ns

    return ns


def _get_er():
    return _load_module("er_fastip_2in1_v8.py")


def _get_er5():
    return _load_module("er_fastip_5in1_v1.py")


def _get_usg():
    return _load_module("usg_fastip_3in1_v5.py")


def _get_mpls():
    return _load_module("er_mpls_v1.py")


def _get_ar():
    return _load_module("ar_sdwan_zihuan_v4.py")


def _get_ar_traditional():
    return _load_module("ar_traditional_v1.py")


# ── Helpers ──────────────────────────────────────────────────────────────

def _apply_network_to_widgets(widget, ns: dict) -> None:
    """Clear Entry/Text widgets so GK() fallback uses globals().

    stub 模式下控件是 _MockEntry/_MockText，清空后 .get() 返回空串，
    闭包的 _pv(entry, placeholder) 返回空，GK("DEFAULT_*") fallback 生效。
    """
    try:
        cls_name = type(widget).__name__
        if cls_name in ("_MockEntry", "_MockCombobox"):
            widget.delete(0, tk.END)
        elif cls_name == "_MockText":
            widget.delete("1.0", tk.END)
        if hasattr(widget, 'winfo_children'):
            for child in widget.winfo_children():
                _apply_network_to_widgets(child, ns)
        if hasattr(widget, 'tabs'):
            for tab_id in widget.tabs():
                _apply_network_to_widgets(widget.nametowidget(tab_id), ns)
    except Exception:
        pass


def _inject_network_to_module(ns: dict, network: dict, *, is_usg: bool = False, is_hk: bool = False) -> None:
    """Inject web form network values into module globals before calling builder.

    The builder functions read DEFAULT_WAN_CIDR / DEFAULT_WAN_GW etc. from
    module globals(). This must be called BEFORE build_fn(hdr_text).
    """
    prefix = "HK_" if is_hk else ""
    wan_key = "DEFAULT_WAN_IP" if is_usg else "DEFAULT_WAN_CIDR"
    lan_key = "DEFAULT_LAN_IP" if is_usg else "DEFAULT_LAN_CIDR"

    def _set(k, v):
        ns[prefix + k] = v
        if is_hk:
            ns[k] = v  # also set non-prefixed for GK() fallback

    for key, val in [
        (wan_key, network.get("wan_cidr", "")),
        ("DEFAULT_WAN_GW", network.get("wan_gw", "")),
        (lan_key, network.get("lan_cidr", "")),
        ("DEFAULT_LAN_GW", network.get("lan_gw", "")),
        ("DEFAULT_WAN_ETH", network.get("wan_eth", "")),
        ("DEFAULT_LAN_ETH", network.get("lan_eth", "")),
        ("DEFAULT_INNER_NETS", network.get("inner_nets", "")),
    ]:
        # LAN fields must never be 'dhcp' — LAN DHCP means the device is the server
        if val and not (str(val).strip().lower() == 'dhcp' and key in (lan_key, "DEFAULT_LAN_GW")):
            _set(key, val)

    for bool_key in ("DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP", "DEFAULT_GEN_RETURN_ROUTE", "DEFAULT_BYPASS"):
        v = network.get(bool_key.lower().replace("default_", ""), None)
        if v is not None:
            _set(bool_key, v)
    if network.get("gen_return_route") is not None:
        _set("DEFAULT_GEN_RETURN_ROUTE", network["gen_return_route"])
    # DNS fields (especially important for USG HK vs US differentiation)
    if is_usg:
        for dns_key in ("DEFAULT_DNS1", "DEFAULT_DNS2"):
            v = network.get(dns_key.lower().replace("default_", ""), None)
            if v is not None:
                _set(dns_key, v)
    if network.get("dns1"):
        _set("DEFAULT_DNS1", network["dns1"])
    if network.get("dns2"):
        _set("DEFAULT_DNS2", network["dns2"])


def _patch_format_dict(d: dict, network: dict, is_usg: bool = False) -> None:
    """Override format dict with web form network values.

    ER 2in1 的 builder 通过 tkinter 闭包读取控件值，但在 web exec() 模式下
    控件状态不可靠（BooleanVar 等）。本函数在 builder 返回 d 后，用表单
    network 参数覆盖所有网络相关字段，确保输出与用户输入一致。
    """
    if not d or not network:
        return
    if is_usg:
        key_map = {"wan_cidr": "DEFAULT_WAN_IP", "lan_cidr": "DEFAULT_LAN_IP"}
    else:
        key_map = {"wan_cidr": "DEFAULT_WAN_CIDR", "lan_cidr": "DEFAULT_LAN_CIDR"}
    for form_key, dict_key in key_map.items():
        v = network.get(form_key)
        if v and str(v).strip():
            d[dict_key] = str(v).strip()
    for k in ("wan_gw", "lan_gw", "inner_nets", "dns1", "dns2"):
        v = network.get(k)
        if v and str(v).strip():
            sv = str(v).strip()
            # LAN fields must never be 'dhcp'
            if k == "lan_gw" and sv.lower() == "dhcp":
                continue
            map_k = {"wan_gw": "DEFAULT_WAN_GW", "lan_gw": "DEFAULT_LAN_GW",
                     "inner_nets": "DEFAULT_INNER_NETS", "dns1": "DEFAULT_DNS1", "dns2": "DEFAULT_DNS2"}[k]
            d[map_k] = sv
            # Also set d["inner_nets"] as parsed list: overseas_nat_block 等
            # 用 d.get("inner_nets") 读列表，不是 DEFAULT_INNER_NETS 字符串
            if k == "inner_nets":
                nets = []
                for part in re.split(r'[\n,，\s]+', sv):
                    part = part.strip()
                    if part and "/" in part:
                        parts = part.split("/")
                        if len(parts) == 2 and parts[0].count(".") == 3 and parts[1].isdigit():
                            nets.append(part)
                if nets:
                    d["inner_nets"] = nets
                    # 重新生成 overseas_nat_block（builder 用控件读 inner_nets，
                    # stub 模式下控件返回空，需用表单值重新生成 NAT 规则）
                    overseas_lines = []
                    main_tun = d.get("main_tunnel", "")
                    bk_tun = d.get("bk_tunnel", "")
                    nat_ip = d.get("hkip_nat", "")
                    for i, net in enumerate(nets):
                        r_main = 100 + i
                        r_bk = 200 + i
                        overseas_lines.append(
                            f"set nat source rule {r_main} outbound-interface '{main_tun}'")
                        overseas_lines.append(
                            f"set nat source rule {r_main} source address '{net}'")
                        overseas_lines.append(
                            f"set nat source rule {r_main} translation address '{nat_ip}'")
                        overseas_lines.append(
                            f"set nat source rule {r_bk} outbound-interface '{bk_tun}'")
                        overseas_lines.append(
                            f"set nat source rule {r_bk} source address '{net}'")
                        overseas_lines.append(
                            f"set nat source rule {r_bk} translation address '{nat_ip}'")
                    d["overseas_nat_block"] = "\n".join(overseas_lines)
    for dhcp_k in ("wan_dhcp", "lan_dhcp", "gen_return_route", "bypass"):
        v = network.get(dhcp_k)
        if v is not None:
            map_k = {"wan_dhcp": "DEFAULT_WAN_DHCP", "lan_dhcp": "DEFAULT_LAN_DHCP",
                     "gen_return_route": "DEFAULT_GEN_RETURN_ROUTE",
                     "bypass": "DEFAULT_BYPASS"}[dhcp_k]
            d[map_k] = bool(v)

    # Recompute wan_addr / wan_route_block from web form network values.
    # Builder 读取的 tkinter BooleanVar (wan_dhcp_var) 在 web 模式下状态不可靠，
    # 这里根据表单 wan_dhcp 重算两个分支。
    # 先用表单 wan_eth 覆盖 wan_if（builder 从 tk 控件读的是旧值）
    wan_eth = str(network.get("wan_eth", "")).strip()
    if wan_eth:
        d["wan_if"] = f"eth{wan_eth}" if not wan_eth.startswith("GE") else wan_eth
    wan_if = d.get("wan_if", "")
    if network.get("wan_dhcp"):
        if not is_usg:
            d["wan_addr"] = "dhcp"
            if wan_if:
                d["wan_route_block"] = f"set protocols static route 1.1.1.1/32 dhcp-interface {wan_if}"
        else:
            d["DEFAULT_WAN_IP"] = "dhcp"
    else:
        wan_cidr = network.get("wan_cidr") or d.get("wan_cidr") or d.get("DEFAULT_WAN_CIDR", "")
        wan_gw = network.get("wan_gw") or d.get("wan_gw") or d.get("DEFAULT_WAN_GW", "")
        if not is_usg:
            if wan_cidr:
                d["wan_addr"] = str(wan_cidr).strip()
            if wan_gw and wan_if:
                d["wan_route_block"] = (
                    f"set protocols static route 0.0.0.0/0 next-hop {wan_gw} distance '222'\n"
                    f"set protocols static route 1.1.1.1/32 next-hop {wan_gw}")
            elif not d.get("wan_route_block") or "dhcp-interface" in str(d.get("wan_route_block", "")):
                d["wan_route_block"] = ""

    # Recompute return_routes_block from form state.
    # bypass_var / return_route_var 在 web 模式下状态不可靠，这里根据表单值重算。
    if not is_usg:
        bypass = network.get("bypass", False)
        gen_rr = network.get("gen_return_route", False)

        if bypass:
            # Bypass mode: no LAN interface, no DHCP server
            d["lan_if_block"] = ""
            d["dhcp_server_block"] = ""
        else:
            # Non-bypass: always regenerate lan_if_block from form lan_eth
            # (builder closure reads stale tk widget values, must override)
            lan_eth = str(network.get("lan_eth", "")).strip() or d.get("lan_eth_num", "5")
            lan_if = f"eth{lan_eth}" if not str(lan_eth).startswith("GE") else str(lan_eth)
            # Prefer DEFAULT_LAN_CIDR over lan_cidr — the latter may be
            # corrupted to WAN CIDR when bypass BooleanVar is incorrectly set.
            lan_cidr = d.get("DEFAULT_LAN_CIDR") or d.get("lan_cidr") or "192.168.5.1/24"
            d["lan_if_block"] = (f"set interfaces ethernet {lan_if} address '{lan_cidr}'\n"
                                 f"set interfaces ethernet {lan_if} description 'LAN'")
            # Ensure dhcp_server_block is populated when LAN DHCP is ON
            if network.get("lan_dhcp") and not d.get("dhcp_server_block"):
                lan_cidr = d.get("DEFAULT_LAN_CIDR") or d.get("lan_cidr") or "192.168.5.1/24"
                if "/" in str(lan_cidr):
                    lan_ip = str(lan_cidr).split("/")[0]
                    parts = lan_ip.split(".")
                    if len(parts) == 4:
                        prefix = str(lan_cidr).split("/")[1]
                        d_start = f"{parts[0]}.{parts[1]}.{parts[2]}.10"
                        d_stop = f"{parts[0]}.{parts[1]}.{parts[2]}.200"
                        network_addr = f"{parts[0]}.{parts[1]}.{parts[2]}.0/{prefix}"
                        d["dhcp_server_block"] = (
                            f"set service dhcp-server shared-network-name LAN subnet {network_addr} default-router {lan_ip}\n"
                            f"set service dhcp-server shared-network-name LAN subnet {network_addr} name-server {lan_ip}\n"
                            f"set service dhcp-server shared-network-name LAN subnet {network_addr} range 0 start {d_start}\n"
                            f"set service dhcp-server shared-network-name LAN subnet {network_addr} range 0 stop {d_stop}")

        # Always clear stale return_routes_block from builder, then recompute if RR is ON
        d["return_routes_block"] = ""
        if gen_rr:
            inner_nets = d.get("inner_nets") or []
            if inner_nets:
                if bypass:
                    ref_cidr = d.get("wan_cidr") or d.get("DEFAULT_WAN_CIDR", "")
                    ref_gw = d.get("wan_gw") or d.get("DEFAULT_WAN_GW", "")
                else:
                    ref_cidr = d.get("lan_cidr") or d.get("DEFAULT_LAN_CIDR", "")
                    ref_gw = d.get("lan_gw") or d.get("DEFAULT_LAN_GW", "")
                # Fallback: if GW is empty, derive from CIDR host
                if not ref_gw and ref_cidr and "/" in ref_cidr:
                    ref_gw = ref_cidr.split("/")[0]
                # WAN DHCP + bypass: return routes use dhcp-interface instead of next-hop
                if bypass and network.get("wan_dhcp"):
                    wan_if = d.get("wan_if", "")
                    if wan_if and inner_nets:
                        try:
                            import ipaddress
                            base = ipaddress.ip_network(ref_cidr, strict=False) if ref_cidr and ref_cidr != "dhcp" else None
                            outside = []
                            for s in inner_nets:
                                try:
                                    net = ipaddress.ip_network(str(s), strict=False)
                                    if base is None or net != base:
                                        outside.append(str(s))
                                except Exception:
                                    if base is None:
                                        outside.append(str(s))
                            if outside:
                                d["return_routes_block"] = "\n".join(
                                    f"set protocols static route {n} dhcp-interface {wan_if}"
                                    for n in outside)
                        except Exception:
                            pass
                elif ref_cidr and ref_gw and ref_cidr != "dhcp" and ref_gw != "dhcp":
                    try:
                        import ipaddress
                        base = ipaddress.ip_network(ref_cidr, strict=False)
                        outside = []
                        for s in inner_nets:
                            try:
                                net = ipaddress.ip_network(str(s), strict=False)
                                if net != base:
                                    outside.append(str(s))
                            except Exception:
                                pass
                        if outside:
                            d["return_routes_block"] = "\n".join(
                                f"set protocols static route {n} next-hop {ref_gw}"
                                for n in outside)
                    except Exception:
                        pass


def _inject_network_to_parsed(ns: dict, d: dict) -> None:
    """Build network-derived fields (wan_if, lan_if, wan_addr, etc.) into the parsed dict.
    These fields are expected by generate_mpls_config / generate_mpls_ipsec_config.
    """
    weth = str(ns.get("DEFAULT_WAN_ETH", "0"))
    leth = str(ns.get("DEFAULT_LAN_ETH", "1"))
    wan_cidr = str(ns.get("DEFAULT_WAN_CIDR", "192.168.1.10/24"))
    lan_cidr = str(ns.get("DEFAULT_LAN_CIDR", "192.168.5.1/24"))
    wan_gw = str(ns.get("DEFAULT_WAN_GW", "192.168.1.1"))
    lan_gw = str(ns.get("DEFAULT_LAN_GW", lan_cidr.split("/")[0] if "/" in lan_cidr else lan_cidr))
    byp = ns.get("DEFAULT_BYPASS", False)
    wan_dhcp = ns.get("DEFAULT_WAN_DHCP", False)
    d.setdefault("wan_if", f"eth{weth}")
    d.setdefault("lan_if", f"eth{leth}")
    d.setdefault("wan_eth", weth)
    d.setdefault("lan_eth", leth)
    d.setdefault("wan_addr", "dhcp" if wan_dhcp else wan_cidr)
    d.setdefault("lan_addr", lan_cidr)
    d.setdefault("wan_gw", wan_gw)
    d.setdefault("lan_gw", lan_gw)
    if wan_dhcp and "wan_route_block" not in d:
        d.setdefault("wan_route_block",
                     f"set protocols static route 1.1.1.1/32 dhcp-interface {d['wan_if']}")
    if not byp:
        d.setdefault("lan_if_block", f"set interfaces ethernet eth{leth} address '{lan_cidr}'\nset interfaces ethernet eth{leth} description 'LAN'")
    d.setdefault("bypass_mode", byp)


def _log_and_return(tool: str, variant: str, header_text: str, output_text: str, result: dict) -> dict:
    """Log generation activity and return the result dict. Skipped if TEST_MODE=1."""
    try:
        if os.environ.get("TEST_MODE") != "1":
            log_generate_config(tool=tool, variant=variant, input_text=header_text, output_text=output_text)
    except Exception:
        pass
    return result


def _inject_ar_params(ns: dict, network: dict):
    """Inject AR SD-WAN init params (WAN ports, IPs, GWs, zihuan, IPSec) into module globals."""
    ar_keys = [
        "DEFAULT_WAN1_PORT", "DEFAULT_WAN1_IP", "DEFAULT_WAN1_GW",
        "DEFAULT_WAN2_PORT", "DEFAULT_WAN2_IP", "DEFAULT_WAN2_GW",
        "DEFAULT_ZIHUAN_PORT", "DEFAULT_IPSEC_PORT",
        "DJ_WAN1_PORT", "DJ_WAN1_IP", "DJ_WAN1_GW",
        "DJ_WAN2_PORT", "DJ_WAN2_IP", "DJ_WAN2_GW",
        "DJ_ZIHUAN1_PORT", "DJ_ZIHUAN2_PORT",
        "DJ_IPSEC1_PORT", "DJ_IPSEC2_PORT",
    ]
    for k in ar_keys:
        v = network.get(k)
        if v is not None and str(v).strip():
            ns[k] = str(v).strip()


def _inject_er_init_defaults(ns: dict, d: dict, hk: bool = False) -> None:
    """Inject ER network defaults from module globals into format dict (for HK/US variants only)."""
    prefix = "HK_" if hk else ""
    for key, default in [
        ("DEFAULT_WAN_CIDR", "192.168.9.190/24"),
        ("DEFAULT_WAN_GW", "192.168.9.1"),
        ("DEFAULT_WAN_ETH", "0"),
        ("DEFAULT_LAN_CIDR", "192.168.8.1/24"),
        ("DEFAULT_LAN_GW", "192.168.8.1"),
        ("DEFAULT_LAN_ETH", "1"),
        ("DEFAULT_INNER_NETS", "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16"),
        ("DEFAULT_DNS1", "10.255.108.7"),
        ("DEFAULT_DNS2", "10.255.108.58"),
    ]:
        gk = prefix + key
        val = ns.get(gk, default)
        if key == "DEFAULT_LAN_GW" and val in ("同lanip", "同lan", "同LAN"):
            lan_cidr = ns.get(prefix + "DEFAULT_LAN_CIDR", "")
            val = lan_cidr.split("/")[0] if lan_cidr else d.get("DEFAULT_LAN_IP_PLAIN", "")
        if key in ("DEFAULT_WAN_CIDR", "DEFAULT_LAN_CIDR"):
            plain_key = key.replace("_CIDR", "_IP_PLAIN")
            d[plain_key] = val.split("/")[0] if "/" in str(val) else str(val)
        d[key] = str(val)

    wan_if = d.get("DEFAULT_WAN_ETH", "0")
    lan_if = d.get("DEFAULT_LAN_ETH", "1")
    d["wan_if_block"] = f"set interfaces ethernet eth{wan_if} address '{d.get('DEFAULT_WAN_CIDR', '')}'"
    d["lan_if_block"] = f"set interfaces ethernet eth{lan_if} address '{d.get('DEFAULT_LAN_CIDR', '')}'" if d.get('DEFAULT_LAN_CIDR') else ""
    d["hostname"] = d.get("hostname", "") or "（请填写Hostname）"


def _inject_variant_init(ns: dict, d: dict, variant: str, network: dict) -> None:
    """Inject variant-specific init values from network form into format dict.
    Called for flink/new_exit/domain_split variants that don't use build_*_format_dict.
    """
    if variant == "flink":
        for k in ("ER_FL_MAIN_NH_DEFAULT", "ER_FL_BACKUP_NH_DEFAULT"):
            v = network.get(k, ns.get(k, ""))
            if v:
                d[k] = str(v)
    elif variant == "new_exit":
        for k in ("ER_NE_MAIN_PE_NH_DEFAULT", "ER_NE_BK_PE_NH_DEFAULT",
                  "ER_NE_MAIN_DUM_DEFAULT", "ER_NE_BK_DUM_DEFAULT",
                  "ER_NE_MAIN_NAT_RULE_DEFAULT", "ER_NE_BK_NAT_RULE_DEFAULT",
                  "ER_NE_NAT_SOURCE_CIDR_DEFAULT",
                  "ER_NE_FNET_PROBE_DEFAULT", "ER_NE_FNET_EXIT_TUNNEL_DEFAULT",
                  "ER_NE_FNET_NAT_RULE_DEFAULT"):
            v = network.get(k, ns.get(k, ""))
            if v:
                d[k] = str(v)
    elif variant == "domain_split":
        for k in ("ER_DS_DOMAINS_DEFAULT", "ER_DS_ADDR_GROUP_DEFAULT",
                  "ER_DS_RULE_NUM_DEFAULT", "ER_DS_TABLE_NUM_DEFAULT",
                  "ER_DS_SOURCE_CIDR_DEFAULT", "ER_DS_ETH_DEFAULT",
                  "ER_DS_DNS1_DEFAULT", "ER_DS_DNS2_DEFAULT",
                  "ER_DS_TABLE_NH_PRIMARY_DEFAULT", "ER_DS_STATIC32_PRIMARY_NH_DEFAULT",
                  "ER_DS_TRACK_NAME_DEFAULT", "ER_DS_STATIC32_BACKUP_NH_DEFAULT",
                  "ER_DS_FNET_PROBE_DEFAULT", "ER_DS_FNET_NAT_RULE_DEFAULT",
                  "ER_DS_EXIT_TUNNEL_DEFAULT", "ER_DS_EXIT_SNAT_IP_DEFAULT"):
            v = network.get(k, ns.get(k, ""))
            if v:
                d[k] = str(v)
    elif variant == "usg_flink":
        for k in ("USG_FL_MAIN_TUN_DEFAULT", "USG_FL_BK_TUN_DEFAULT"):
            v = network.get(k, ns.get(k, ""))
            if v:
                d[k] = str(v)
    elif variant == "usg_new_exit":
        for k in ("USG_NE_MAIN_TUN_DEFAULT", "USG_NE_BK_TUN_DEFAULT",
                  "USG_NE_MAIN_LOOP_START_DEFAULT", "USG_NE_BK_LOOP_START_DEFAULT",
                  "USG_NE_MAIN_NQA_DEFAULT", "USG_NE_BK_NQA_DEFAULT"):
            v = network.get(k, ns.get(k, ""))
            if v:
                d[k] = str(v)
    elif variant == "epoch5_flink":
        for k in ("ER5_FL_MAIN_NH_DEFAULT", "ER5_FL_BACKUP_NH_DEFAULT"):
            v = network.get(k, ns.get(k, ""))
            if v:
                d[k] = str(v)
    elif variant == "epoch5_new_exit":
        for k in ("ER5_NE_MAIN_PE_NH_DEFAULT", "ER5_NE_BK_PE_NH_DEFAULT",
                  "ER5_NE_MAIN_DUM_DEFAULT", "ER5_NE_BK_DUM_DEFAULT",
                  "ER5_NE_MAIN_NAT_RULE_DEFAULT", "ER5_NE_BK_NAT_RULE_DEFAULT",
                  "ER5_NE_NAT_GROUP_DEFAULT", "ER5_NE_NAT_SOURCE_CIDR_DEFAULT",
                  "ER5_NE_FNET_PROBE_DEFAULT", "ER5_NE_FNET_EXIT_TUNNEL_DEFAULT",
                  "ER5_NE_FNET_NAT_RULE_DEFAULT"):
            v = network.get(k, ns.get(k, ""))
            if v:
                d[k] = str(v)


# ── Routes ──────────────────────────────────────────────────────────────


def _humanize_error(err, variant: str = "") -> str:
    """将内部错误码转换为用户可读的中文提示。"""
    # Tuple errors from builder functions
    if isinstance(err, tuple) and len(err) >= 2:
        kind = err[0]
        payload = err[1] if len(err) > 1 else None

        if kind == "natmiss":
            items = "、".join(str(x) for x in payload) if isinstance(payload, list) else str(payload or "出口IP")
            return f"数据头缺少必要的出口IP信息（{items}）。\n请检查：\n  1. 数据头是否包含完整的「海外出口ip」字段\n  2. 主线和备线数据是否都已填写"

        if kind == "network":
            if isinstance(payload, list) and payload:
                msgs = "\n".join(f"  · {m}" for m in payload)
                return f"网络参数格式不正确：\n{msgs}\n\n请修正参数设置中的 IP 地址、子网掩码等格式后重试。"
            return "网络参数格式不正确，请在参数设置中修正 IP 地址、子网掩码等格式后重试。"

        if kind == "empty":
            return '请输入业务数据头后重试。请在左侧「数据头输入」区域粘贴业务信息。'

        if kind == "tunnel":
            info = ", ".join(str(x) for x in payload) if isinstance(payload, list) else str(payload or "")
            return f"隧道名称格式不符合要求（{info}）。\nHK 出口场景要求隧道名以 vtun 开头，请检查数据头中的 Tunnel 字段。"

        # Unknown tuple kind
        return f"数据格式异常（{kind}），请检查输入数据是否完整。"

    s = str(err).strip()

    # Already Chinese or human-readable
    if any(s.startswith(p) for p in ["数据头缺少", "网络参数", "请输入", "隧道名称", "数据格式异常"]):
        return s

    # Technical errors → human-readable
    _MAP = {
        "No preview handler": "当前场景暂不支持模板预览。\n请确认：\n  1. 数据头是否完整填写\n  2. 模板是否包含必要的变量占位符",
        "Scenario not found": "未找到对应的配置场景，请刷新页面后重试。",
        "No scenario key": '请先在「我来定模板」下拉框中选择一个配置场景。',
        "Flink parser not found": "飞连解析器加载失败，请刷新页面后重试。",
        "New exit parser/builder not found": "新增出口解析器加载失败，请刷新页面后重试。",
        "Builder not found": "配置生成器加载失败，请刷新页面后重试。",
        "Domain split template not found": "域名分流模板加载失败，请刷新页面后重试。",
        "USG Flink builder not found": "USG 飞连生成器加载失败，请刷新页面后重试。",
        "MPLS parser not found": "MPLS 解析器加载失败，请刷新页面后重试。",
        "Generation failed": "配置生成失败，请检查输入数据后重试。",
        "No example for": "该场景暂无填写示例。",
        "cannot import name": "内部模块加载失败，请联系管理员检查代码。",
    }
    for key, msg in _MAP.items():
        if key.lower() in s.lower():
            return msg

    # Unknown variant
    if "Unknown variant" in s or "unknown variant" in s.lower():
        v = s.split(":")[-1].strip().strip("'").strip('"') if ":" in s else variant
        return f"不支持的配置类型（{v}），请重新选择变体后重试。"

    # Parser error — extract meaningful part
    if "Parser error:" in s:
        inner = s.split("Parser error:", 1)[-1].strip()
        return f"数据头解析失败：{inner}\n请检查数据头格式是否与填写示例一致。"

    # Generic fallback
    return s



@app.route("/")
def index():
    username = _get_request_username()
    uid = _get_request_user_id()
    template_editable = bool(uid)  # 登录用户可编辑自己的模板
    is_admin = (username == _TEMPLATE_ADMIN_USER)  # yucs 是管理员
    return render_template("index.html",
                           username=username,
                           template_editable=template_editable,
                           is_admin=is_admin)


@app.errorhandler(500)
def handle_500(e):
    import traceback
    app.logger.error("500 error: %s\n%s", e, traceback.format_exc())
    return jsonify({"ok": False, "error": _humanize_error(e)}), 500


@app.route("/api/tools")
def api_tools():
    return jsonify(
        {
            "tools": [
                {
                    "id": "epoch_fastip",
                    "name": "Epoch FastIP",
                    "variants": [
                        {"id": "hk", "name": "HK 香港出口"},
                        {"id": "us", "name": "非香港出口"},
                        {"id": "flink", "name": "ER 飞连"},
                        {"id": "new_exit", "name": "ER 新增出口"},
                        {"id": "domain_split", "name": "ER 域名分流"},
                    ],
                },
                {
                    "id": "usg_fastip",
                    "name": "USG FastIP",
                    "variants": [
                        {"id": "hk", "name": "HK 香港出口"},
                        {"id": "us", "name": "非香港出口"},
                        {"id": "flink", "name": "飞连"},
                        {"id": "new_exit", "name": "新增出口"},
                    ],
                },
                {
                    "id": "epoch_mpls",
                    "name": "Epoch MPLS",
                    "variants": [
                        {"id": "domestic", "name": "国内配置"},
                        {"id": "overseas", "name": "海外配置"},
                        {"id": "ipsec", "name": "IPSec"},
                    ],
                },
                {
                    "id": "ar_sdwan",
                    "name": "AR SD-WAN",
                    "variants": [
                        {"id": "single_ops", "name": "单机单WAN · OPS"},
                        {"id": "single_factory", "name": "单机单WAN · Factory"},
                        {"id": "dual_ops_pri", "name": "双机主 OPS"},
                        {"id": "dual_ops_bak", "name": "双机备 OPS"},
                    ],
                },
                {
                    "id": "ar_traditional",
                    "name": "AR 传统组网",
                    "variants": [
                        {"id": "dual", "name": "双线"},
                    ],
                },
            ]
        }
    )


# ── Generation API ──────────────────────────────────────────────────────


@app.route("/api/generate/epoch_fastip", methods=["POST"])
def generate_epoch_fastip():
    """Generate Epoch FastIP configuration using the full build_*_format_dict functions."""
    data = request.get_json(force=True)
    variant = data.get("variant", "hk")
    hdr_text = data.get("header_text", "")
    network = data.get("network", {})
    tool_id = "epoch_fastip"

    er = _get_er()
    _inject_network_to_module(er, network, is_hk=(variant == "hk"))

    try:
        if variant == "hk":
            build_fn = er.get("build_epoch_hk_format_dict")
            tpl = _get_effective_template(er, "TEMPLATE_EPOCH_HK")
        elif variant == "us":
            build_fn = er.get("build_epoch_us_format_dict")
            tpl = _get_effective_template(er, "TEMPLATE_EPOCH_US")
        elif variant == "flink":
            parse_fn = er.get("parse_er_flink_headers")
            fmt_fn = er.get("_build_er_flink_format_dict")
            build_fn = er.get("build_er_flink_config")
            tpl = _get_effective_template(er, "TEMPLATE_ER_FLINK_VISUAL")
            if not parse_fn:
                return jsonify({"ok": False, "error": _humanize_error("Flink parser not found", variant)}), 500
            routes, err = parse_fn(hdr_text)
            if err:
                return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            main_nh = network.get("ER_FL_MAIN_NH_DEFAULT", er.get("ER_FL_MAIN_NH_DEFAULT", "10.1.1.1"))
            backup_nh = network.get("ER_FL_BACKUP_NH_DEFAULT", er.get("ER_FL_BACKUP_NH_DEFAULT", "10.2.1.1"))
            output = ""
            if fmt_fn and tpl:
                d = fmt_fn(routes, str(main_nh), str(backup_nh))
                if d:
                    try:
                        output = tpl.format(**d)
                    except Exception:
                        pass
            if not output and build_fn:
                output = build_fn(routes, str(main_nh), str(backup_nh))
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        elif variant == "new_exit":
            parse_fn = er.get("parse_er_new_exit_blocks")
            build_fn = er.get("build_er_new_exit_config")
            fmt_fn = er.get("_build_er_new_exit_format_dict")
            tpl = _get_effective_template(er, "TEMPLATE_ER_NEW_EXIT_VISUAL")
            if not parse_fn or not build_fn:
                return jsonify({"ok": False, "error": _humanize_error("New exit parser/builder not found", variant)}), 500
            parsed, err = parse_fn(hdr_text)
            if err:
                return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            has_bk = "bk" in parsed and parsed.get("bk")
            main_nh = network.get("ER_NE_MAIN_PE_NH_DEFAULT") or er.get("ER_NE_MAIN_PE_NH_DEFAULT", "192.168.1.1")
            bk_nh = network.get("ER_NE_BK_PE_NH_DEFAULT") or er.get("ER_NE_BK_PE_NH_DEFAULT", "192.168.1.2")
            main_dum = network.get("ER_NE_MAIN_DUM_DEFAULT") or er.get("ER_NE_MAIN_DUM_DEFAULT", "300")
            bk_dum = network.get("ER_NE_BK_DUM_DEFAULT") or er.get("ER_NE_BK_DUM_DEFAULT", "400")
            main_nat = network.get("ER_NE_MAIN_NAT_RULE_DEFAULT") or er.get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300")
            bk_nat = network.get("ER_NE_BK_NAT_RULE_DEFAULT") or er.get("ER_NE_BK_NAT_RULE_DEFAULT", "400")
            nat_src = network.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT") or er.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "")
            # FNET whitelist 参数
            fnet_probe = network.get("ER_NE_FNET_PROBE_DEFAULT") or er.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")
            fnet_tunnel = network.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT") or er.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")
            fnet_nat_rule = network.get("ER_NE_FNET_NAT_RULE_DEFAULT") or er.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")
            # 三元组校验（仅双线时）
            f_filled = (bool(str(fnet_tunnel).strip()), bool(str(fnet_nat_rule).strip()))
            if has_bk and any(f_filled) and not all(f_filled):
                return jsonify({"ok": False, "error": _humanize_error("NAT rule 号、NAT 出口 tunnel 须同时填写或全部留空", variant)}), 400
            init_cfg = {
                "main_pe_next_hop": str(main_nh),
                "main_dum_start": int(main_dum) if str(main_dum).isdigit() else 300,
                "main_nat_rule": str(main_nat),
                "main_nat_rule_start": str(main_nat),
                "bk_pe_next_hop": str(bk_nh),
                "bk_dum_start": int(bk_dum) if str(bk_dum).isdigit() else 400,
                "bk_nat_rule": str(bk_nat),
                "bk_nat_rule_start": str(bk_nat),
                "main_nat_source_cidr": str(nat_src),
                "bk_nat_source_cidr": str(nat_src),
                "nat_source_cidr": str(nat_src),
                "fnet_probe": str(fnet_probe),
                "fnet_exit_tunnel": str(fnet_tunnel),
                "fnet_nat_rule": str(fnet_nat_rule),
            }
            output = ""
            if fmt_fn and tpl:
                d = fmt_fn(parsed, init_cfg)
                if isinstance(d, dict):
                    try:
                        output = tpl.format(**d)
                    except Exception:
                        pass
            if not output:
                output = build_fn(parsed, init_cfg)
                if isinstance(output, tuple):
                    output = output[0] if output[0] else str(output[1])
                output = str(output)
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        elif variant == "domain_split":
            extras_fn = er.get("er_ds_template_preview_extras")
            tpl = _get_effective_template(er, "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL")
            if not tpl:
                return jsonify({"ok": False, "error": _humanize_error("Domain split template not found", variant)}), 500
            d = {}
            _inject_variant_init(er, d, "domain_split", network)
            if extras_fn:
                try:
                    extras = extras_fn(d)
                    if isinstance(extras, dict):
                        d.update(extras)
                except Exception:
                    pass
            output = tpl.format(**d) if d and tpl else str(d)
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        else:
            return jsonify({"ok": False, "error": _humanize_error(f"Unknown variant: {variant}", variant)}), 400

        if not build_fn:
            return jsonify({"ok": False, "error": _humanize_error("Builder not found", variant)}), 500

        result = build_fn(hdr_text)
        if isinstance(result, tuple):
            d = result[0]
            err = result[1] if len(result) >= 2 else None
            if d is None:
                return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
        else:
            d = result

        _patch_format_dict(d, network, is_usg=False)
        hostname_override = str(network.get("hostname") or "").strip()
        if hostname_override and isinstance(d, dict):
            d["hostname"] = hostname_override
        output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
        return _log_and_return("epoch_fastip", variant, hdr_text, output, jsonify({"ok": True, "output": output}))
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": _humanize_error(e, variant)}), 500


@app.route("/api/generate/epoch_fastip5", methods=["POST"])
def generate_epoch_fastip5():
    """Generate Epoch FastIP 5.0 configuration (VyOS set syntax)."""
    data = request.get_json(force=True)
    variant = data.get("variant", "hk")
    hdr_text = data.get("header_text", "")
    network = data.get("network", {})
    tunnel_type = str(network.get("tunnel_type") or "openvpn").strip()
    tool_id = "epoch_fastip5"

    er5 = _get_er5()
    _inject_network_to_module(er5, network, is_hk=(variant == "hk"))

    try:
        hostname_override = str(network.get("hostname") or "").strip()
        if variant == "hk":
            if tunnel_type == "ipsec":
                tpl = _get_effective_template(er5, "TEMPLATE_EPOCH5_HK_IPSEC")
                if not tpl:
                    return jsonify({"ok": False, "error": "HK IPSec — 正在开发中，暂不支持。请使用 OpenVPN。"}), 400
                build_fn = er5.get("build_epoch5_hk_ipsec_format_dict")
                if build_fn:
                    result = build_fn(hdr_text)
                    d = result if not isinstance(result, tuple) else result[0]
                else:
                    d = {}
                if hostname_override and isinstance(d, dict):
                    d["hostname"] = hostname_override
                output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
                return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
            build_fn = er5.get("build_epoch5_hk_format_dict")
            tpl = _get_effective_template(er5, "TEMPLATE_EPOCH5_HK")
            if not build_fn:
                return jsonify({"ok": False, "error": "HK builder not found"}), 500
            result = build_fn(hdr_text)
            if isinstance(result, tuple):
                d, err = result
                if d is None:
                    return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            else:
                d = result
            if hostname_override and isinstance(d, dict):
                d["hostname"] = hostname_override
            output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        elif variant == "us":
            if tunnel_type == "ipsec":
                build_fn = er5.get("build_epoch5_us_ipsec_format_dict")
                tpl = _get_effective_template(er5, "TEMPLATE_EPOCH5_US_IPSEC")
                if not build_fn or not tpl:
                    return jsonify({"ok": False, "error": "非香港 IPSec builder 或模板未找到"}), 500
                result = build_fn(hdr_text)
                if isinstance(result, tuple):
                    if result[0] is None:
                        return jsonify({"ok": False, "error": _humanize_error(result[1], variant)}), 400
                    d, warning = result
                else:
                    d, warning = result, ""
                if not isinstance(d, dict):
                    return jsonify({"ok": False, "error": "IPSec builder 返回格式异常"}), 500
                if hostname_override and isinstance(d, dict):
                    d["hostname"] = hostname_override
                output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
                if warning:
                    output = "# " + warning + "\n" + output
                return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
            build_fn = er5.get("build_epoch5_us_format_dict")
            tpl = _get_effective_template(er5, "TEMPLATE_EPOCH5_US")
            if not build_fn:
                return jsonify({"ok": False, "error": "US builder not found"}), 500
            result = build_fn(hdr_text)
            if isinstance(result, tuple):
                d, err = result
                if d is None:
                    return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            else:
                d = result
            if hostname_override and isinstance(d, dict):
                d["hostname"] = hostname_override
            output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        elif variant == "flink":
            parse_fn = er5.get("parse_epoch5_flink_headers")
            fmt_fn = er5.get("_build_epoch5_flink_format_dict")
            build_fn = er5.get("build_epoch5_flink_config")
            tpl = _get_effective_template(er5, "TEMPLATE_EPOCH5_FLINK")
            if not parse_fn:
                return jsonify({"ok": False, "error": "Flink parser not found"}), 500
            routes, err = parse_fn(hdr_text)
            if err:
                return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            main_nh = network.get("ER5_FL_MAIN_NH_DEFAULT", er5.get("ER5_FL_MAIN_NH_DEFAULT", "10.1.1.1"))
            backup_nh = network.get("ER5_FL_BACKUP_NH_DEFAULT", er5.get("ER5_FL_BACKUP_NH_DEFAULT", "10.2.1.1"))
            output = ""
            if fmt_fn and tpl:
                d = fmt_fn(routes, str(main_nh), str(backup_nh))
                if d:
                    try:
                        output = tpl.format(**d)
                    except Exception:
                        pass
            if not output and build_fn:
                output = build_fn(routes, str(main_nh), str(backup_nh))
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        elif variant == "new_exit":
            parse_fn = er5.get("parse_epoch5_new_exit_blocks")
            build_fn = er5.get("build_epoch5_new_exit_format_dict")
            tpl = _get_effective_template(er5, "TEMPLATE_EPOCH5_NEW_EXIT")
            if not parse_fn or not build_fn:
                return jsonify({"ok": False, "error": "5.0 New exit parser/builder not found"}), 500
            parsed, err = parse_fn(hdr_text)
            if err:
                return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            has_bk = "bk" in parsed and parsed.get("bk")
            main_nh = network.get("ER5_NE_MAIN_PE_NH_DEFAULT") or er5.get("ER5_NE_MAIN_PE_NH_DEFAULT", "10.1.1.1")
            bk_nh = network.get("ER5_NE_BK_PE_NH_DEFAULT") or er5.get("ER5_NE_BK_PE_NH_DEFAULT", "10.2.1.1")
            main_dum = network.get("ER5_NE_MAIN_DUM_DEFAULT") or er5.get("ER5_NE_MAIN_DUM_DEFAULT", "300")
            bk_dum = network.get("ER5_NE_BK_DUM_DEFAULT") or er5.get("ER5_NE_BK_DUM_DEFAULT", "400")
            main_nat = network.get("ER5_NE_MAIN_NAT_RULE_DEFAULT") or er5.get("ER5_NE_MAIN_NAT_RULE_DEFAULT", "1001")
            bk_nat = network.get("ER5_NE_BK_NAT_RULE_DEFAULT") or er5.get("ER5_NE_BK_NAT_RULE_DEFAULT", "2001")
            nat_group = network.get("ER5_NE_NAT_GROUP_DEFAULT") or er5.get("ER5_NE_NAT_GROUP_DEFAULT", "LAN-NET1")
            nat_src = network.get("ER5_NE_NAT_SOURCE_CIDR_DEFAULT") or er5.get("ER5_NE_NAT_SOURCE_CIDR_DEFAULT", "192.168.0.0/24")
            fnet_probe = network.get("ER5_NE_FNET_PROBE_DEFAULT") or er5.get("ER5_NE_FNET_PROBE_DEFAULT", "")
            fnet_tunnel = network.get("ER5_NE_FNET_EXIT_TUNNEL_DEFAULT") or er5.get("ER5_NE_FNET_EXIT_TUNNEL_DEFAULT", "tun")
            fnet_nat_rule = network.get("ER5_NE_FNET_NAT_RULE_DEFAULT") or er5.get("ER5_NE_FNET_NAT_RULE_DEFAULT", "")
            init_cfg = {
                "main_pe_next_hop": str(main_nh),
                "main_dum_start": int(main_dum) if str(main_dum).isdigit() else 300,
                "main_nat_rule": str(main_nat),
                "bk_pe_next_hop": str(bk_nh),
                "bk_dum_start": int(bk_dum) if str(bk_dum).isdigit() else 400,
                "bk_nat_rule": str(bk_nat),
                "nat_group_name": str(nat_group),
                "nat_source_cidr": str(nat_src),
                "fnet_probe": str(fnet_probe),
                "fnet_exit_tunnel": str(fnet_tunnel),
                "fnet_nat_rule": str(fnet_nat_rule),
            }
            span_check = er5.get("epoch5_new_exit_nat_rule_span_error")
            span_err = span_check(parsed, init_cfg) if callable(span_check) else None
            if span_err:
                return jsonify({"ok": False, "error": _humanize_error(span_err, variant)}), 400
            d = build_fn(parsed, init_cfg) if build_fn and isinstance(parsed, dict) else {}
            _inject_variant_init(er5, d, "epoch5_new_exit", network)
            output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        elif variant == "domain_split":
            build_fn = er5.get("build_epoch5_domain_split_format_dict")
            if not build_fn:
                return jsonify({"ok": False, "error": "5.0 域名分流生成器未找到"}), 500
            # Inject ER5_DS_* from form into module globals for the builder
            for k in ("ER5_DS_ADDR_GROUP_DEFAULT","ER5_DS_RULE_NUM_DEFAULT","ER5_DS_TABLE_NUM_DEFAULT",
                      "ER5_DS_SOURCE_CIDR_DEFAULT","ER5_DS_ETH_DEFAULT",
                      "ER5_DS_DNS1_DEFAULT","ER5_DS_DNS2_DEFAULT",
                      "ER5_DS_TABLE_NH_PRIMARY_DEFAULT","ER5_DS_STATIC32_PRIMARY_NH_DEFAULT",
                      "ER5_DS_TRACK_NAME_DEFAULT","ER5_DS_STATIC32_BACKUP_NH_DEFAULT",
                      "ER5_DS_FNET_PROBE_DEFAULT","ER5_DS_FNET_NAT_RULE_DEFAULT",
                      "ER5_DS_EXIT_TUNNEL_DEFAULT","ER5_DS_EXIT_SNAT_IP_DEFAULT"):
                if k in network:
                    er5[k] = str(network.get(k, ""))
            # Domain list comes from form field ER5_DS_DOMAINS_DEFAULT
            domains_text = network.get("ER5_DS_DOMAINS_DEFAULT", network.get("header_text", ""))
            result = build_fn(domains_text)
            if isinstance(result, tuple):
                output, err = result
                if output is None:
                    return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            else:
                output = result
            output = str(output)
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        else:
            return jsonify({"ok": False, "error": f"Unknown variant: {variant}"}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": _humanize_error(e, variant)}), 500


@app.route("/api/generate/usg_fastip", methods=["POST"])
def generate_usg_fastip():
    data = request.get_json(force=True)
    variant = data.get("variant", "us")
    hdr_text = data.get("header_text", "")
    network = data.get("network", {})
    tool_id = "usg_fastip"

    usg = _get_usg()
    _inject_network_to_module(usg, network, is_usg=True, is_hk=(variant == "hk"))
    _apply_network_to_widgets(usg.get("__TAB_FRAME__", usg.get("__WEB_FRAME__")), usg)

    try:
        if variant == "hk":
            build_fn = usg.get("build_usg_hk_format_dict")
            tpl = _get_effective_template(usg, "TEMPLATE_USG_HK")
        elif variant == "us":
            build_fn = usg.get("build_usg_us_format_dict")
            tpl = _get_effective_template(usg, "TEMPLATE_USG_NONHK")
        elif variant == "flink":
            build_fn = usg.get("build_usg_flink_format_dict")
            tpl = _get_effective_template(usg, "TEMPLATE_USG_FLINK_VISUAL")
            if build_fn:
                main_tun = network.get("USG_FL_MAIN_TUN_DEFAULT") or usg.get("USG_FL_MAIN_TUN_DEFAULT", "3000")
                bk_tun = network.get("USG_FL_BK_TUN_DEFAULT") or usg.get("USG_FL_BK_TUN_DEFAULT", "4000")
                d, err = build_fn(hdr_text, main_tun=str(main_tun), bk_tun=str(bk_tun))
                if err:
                    return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
                output = tpl.format(**d) if d and tpl else str(d)
                return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
            return jsonify({"ok": False, "error": _humanize_error("USG Flink builder not found", variant)}), 500
        elif variant == "new_exit":
            result = usg.get("parse_usg_new_exit_blocks")(hdr_text) if usg.get("parse_usg_new_exit_blocks") else ({}, "")
            if isinstance(result, tuple):
                parsed, err = result
                if err:
                    return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
            else:
                parsed = result
            build_fn = usg.get("build_usg_new_exit_format_dict")
            tpl = _get_effective_template(usg, "TEMPLATE_USG_NEW_EXIT_VISUAL")
            init_cfg = {
                "main_tun": int(str(network.get("USG_NE_MAIN_TUN_DEFAULT") or usg.get("USG_NE_MAIN_TUN_DEFAULT", "1001"))),
                "bk_tun": int(str(network.get("USG_NE_BK_TUN_DEFAULT") or usg.get("USG_NE_BK_TUN_DEFAULT", "1002"))),
                "main_loop_start": int(str(network.get("USG_NE_MAIN_LOOP_START_DEFAULT") or usg.get("USG_NE_MAIN_LOOP_START_DEFAULT", "111"))),
                "bk_loop_start": int(str(network.get("USG_NE_BK_LOOP_START_DEFAULT") or usg.get("USG_NE_BK_LOOP_START_DEFAULT", "211"))),
                "main_nqa": str(network.get("USG_NE_MAIN_NQA_DEFAULT") or usg.get("USG_NE_MAIN_NQA_DEFAULT", "main2")),
                "bk_nqa": str(network.get("USG_NE_BK_NQA_DEFAULT") or usg.get("USG_NE_BK_NQA_DEFAULT", "backup2")),
            }
            d = build_fn(parsed, init_cfg) if build_fn and isinstance(parsed, dict) else parsed
            _inject_variant_init(usg, d, "usg_new_exit", network)
            output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
            return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
        else:
            return jsonify({"ok": False, "error": _humanize_error(f"Unknown variant: {variant}", variant)}), 400

        if not build_fn:
            return jsonify({"ok": False, "error": _humanize_error("Builder not found", variant)}), 500

        bgp_ver = network.get("DEFAULT_BGP_VERSION") if isinstance(network, dict) else None
        result = build_fn(hdr_text, bgp_version=bgp_ver) if bgp_ver else build_fn(hdr_text)
        if isinstance(result, tuple):
            d = result[0]
            err = result[1] if len(result) >= 2 else None
            if d is None:
                return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
        else:
            d = result

        _patch_format_dict(d, network, is_usg=True)
        output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
        return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
    except Exception as e:
        return jsonify({"ok": False, "error": _humanize_error(e, variant)}), 500


@app.route("/api/generate/epoch_mpls", methods=["POST"])
def generate_epoch_mpls():
    data = request.get_json(force=True)
    variant = data.get("variant", "domestic")
    hdr_text = data.get("header_text", "")
    network = data.get("network", {})
    tool_id = "epoch_mpls"

    mpls = _get_mpls()
    _inject_network_to_module(mpls, network)
    _apply_network_to_widgets(mpls.get("__TAB_FRAME__", mpls.get("__WEB_FRAME__")), mpls)

    try:
        if variant == "ipsec":
            parse_fn = mpls.get("parse_epoch_mpls_ipsec") or mpls.get("parse_epoch_mpls")
        else:
            parse_fn = mpls.get("parse_epoch_mpls")
        if not parse_fn:
            return jsonify({"ok": False, "error": _humanize_error("MPLS parser not found", variant)}), 500

        parsed = parse_fn(hdr_text)

        # Inject network fields that generate_mpls_config expects
        _inject_network_to_parsed(mpls, parsed)

        hostname_override = str(network.get("hostname") or "").strip()
        if variant == "ipsec":
            build_fn = mpls.get("build_mpls_ipsec_format_dict")
            gen_fn = mpls.get("generate_mpls_ipsec_config")
            wan_blocks_fn = mpls.get("build_wan_lan_blocks")
            if build_fn and gen_fn:
                d = build_fn(hdr_text, hostname=hostname_override, net=None)
                if wan_blocks_fn:
                    wan_dhcp = bool(network.get("wan_dhcp", False))
                    lan_dhcp = bool(network.get("lan_dhcp", True))
                    wan_cidr = str(mpls.get("DEFAULT_WAN_CIDR", "192.168.1.10/24"))
                    wan_gw = str(mpls.get("DEFAULT_WAN_GW", "192.168.1.1"))
                    lan_cidr = str(mpls.get("DEFAULT_LAN_CIDR", "192.168.5.1/24"))
                    bypass = bool(network.get("bypass", False))
                    weth = str(mpls.get("DEFAULT_WAN_ETH", "0"))
                    leth = str(mpls.get("DEFAULT_LAN_ETH", "1"))
                    blocks = wan_blocks_fn(f"eth{weth}", wan_dhcp, wan_cidr, wan_gw,
                                           f"eth{leth}", lan_dhcp, lan_cidr, bypass=bypass)
                    if isinstance(blocks, dict):
                        d.update(blocks)
                    # Recompute wan_addr_plain after blocks updated wan_addr
                    _cidr_plain = mpls.get("_cidr_plain")
                    if _cidr_plain:
                        d["wan_addr_plain"] = _cidr_plain(str(d.get("wan_addr", "")))
                    # Override inner_nets from form (builder reads stale tk defaults)
                    inner_raw_form = str(network.get("inner_nets", "")).strip()
                    if inner_raw_form:
                        import re as _re_in_ipsec
                        form_nets = []
                        for t in _re_in_ipsec.split(r'[\n,，\s]+', inner_raw_form):
                            t = t.strip()
                            if t and "/" in t:
                                parts = t.split("/")
                                if len(parts) == 2 and parts[0].count(".") == 3 and parts[1].isdigit():
                                    form_nets.append(t)
                        if form_nets:
                            d["inner_nets"] = form_nets
                    # Recompute return routes: WAN DHCP + bypass → dhcp-interface
                    if bypass and wan_dhcp and network.get("gen_return_route"):
                        inner_nets = d.get("inner_nets") or []
                        if inner_nets:
                            wan_if = f"eth{weth}" if weth else d.get("wan_if", "")
                            if wan_if:
                                rr_lines = [f"set protocols static route {n} dhcp-interface {wan_if}" for n in inner_nets]
                                d["return_routes_block"] = "\n".join(rr_lines)
                _inject_network_to_parsed(mpls, d)
                output = gen_fn(d)
            elif gen_fn:
                output = "# IPSec 配置生成暂不可用\n"
        else:
            import traceback as _tb
            try:
                build_fn = mpls.get("build_mpls_domestic_format_dict" if variant == "domestic" else "build_mpls_overseas_format_dict")
                tpl = _get_effective_template(mpls, "TEMPLATE_MPLS_DOMESTIC" if variant == "domestic" else "TEMPLATE_MPLS_OVERSEAS")
                wan_blocks_fn = mpls.get("build_wan_lan_blocks")
                output = ""
                if build_fn and tpl:
                    d, _ = build_fn(hdr_text)
                    if d:
                        if hostname_override:
                            d["hostname"] = hostname_override
                        # Build WAN/LAN blocks with correct DHCP/bypass flags from form
                        if wan_blocks_fn:
                            wan_dhcp = bool(network.get("wan_dhcp", False))
                            lan_dhcp = bool(network.get("lan_dhcp", True))
                            wan_cidr = str(mpls.get("DEFAULT_WAN_CIDR", "192.168.1.10/24"))
                            wan_gw = str(mpls.get("DEFAULT_WAN_GW", "192.168.1.1"))
                            lan_cidr = str(mpls.get("DEFAULT_LAN_CIDR", "192.168.5.1/24"))
                            bypass = bool(network.get("bypass", False))
                            weth = str(mpls.get("DEFAULT_WAN_ETH", "0"))
                            leth = str(mpls.get("DEFAULT_LAN_ETH", "1"))
                            blocks = wan_blocks_fn(
                                f"eth{weth}", wan_dhcp, wan_cidr, wan_gw,
                                f"eth{leth}", lan_dhcp, lan_cidr, bypass=bypass)
                            if isinstance(blocks, dict):
                                d.update(blocks)

                        # Handle bypass: clear LAN / DHCP server
                        if network.get("bypass"):
                            d["lan_if_block"] = ""
                            d["dhcp_server_block"] = ""

                        # Override inner_nets from form (builder reads stale tk defaults)
                        inner_raw_form = str(network.get("inner_nets", "")).strip()
                        if inner_raw_form:
                            import re as _re_in
                            form_nets = []
                            for t in _re_in.split(r'[\n,，\s]+', inner_raw_form):
                                t = t.strip()
                                if t and "/" in t:
                                    parts = t.split("/")
                                    if len(parts) == 2 and parts[0].count(".") == 3 and parts[1].isdigit():
                                        form_nets.append(t)
                            if form_nets:
                                d["inner_nets"] = form_nets
                                d["DEFAULT_INNER_NETS"] = inner_raw_form
                                # Regenerate prefix_list_block with new inner_nets
                                # (builder already built it with stale tk defaults)
                                pl_fn = mpls.get("_build_mpls_prefix_list_block")
                                if pl_fn:
                                    d["prefix_list_block"] = pl_fn(d)

                        # Return routes (closure BooleanVar not set in web mode)
                        d["return_routes_block"] = ""
                        if network.get("gen_return_route"):
                            inner_nets = d.get("inner_nets") or []
                            if not inner_nets:
                                inner_raw = str(mpls.get("DEFAULT_INNER_NETS", ""))
                                if inner_raw.strip():
                                    import re as _re
                                    nets = []
                                    for t in _re.split(r'[\n,，\s]+', inner_raw):
                                        t = t.strip()
                                        if t and "/" in t:
                                            parts = t.split("/")
                                            if len(parts) == 2 and parts[0].count(".") == 3 and parts[1].isdigit():
                                                nets.append(t)
                                    if nets:
                                        inner_nets = nets
                                        d["inner_nets"] = nets
                            if inner_nets:
                                if network.get("bypass"):
                                    ref_cidr = d.get("wan_cidr") or d.get("DEFAULT_WAN_CIDR", "")
                                    ref_gw = d.get("wan_gw") or d.get("DEFAULT_WAN_GW", "")
                                else:
                                    ref_cidr = d.get("lan_cidr") or d.get("DEFAULT_LAN_CIDR", "")
                                    ref_gw = d.get("lan_gw") or d.get("DEFAULT_LAN_GW", "")
                                if not ref_gw and ref_cidr and "/" in ref_cidr:
                                    ref_gw = ref_cidr.split("/")[0]
                                # WAN DHCP + bypass: return routes use dhcp-interface
                                if network.get("bypass") and wan_dhcp:
                                    wan_if = f"eth{weth}" if weth else d.get("wan_if", "")
                                    if wan_if:
                                        rr_lines = []
                                        for s in inner_nets:
                                            rr_lines.append(f"set protocols static route {s} dhcp-interface {wan_if}")
                                        if rr_lines:
                                            d["return_routes_block"] = "\n".join(rr_lines)
                                elif ref_cidr and ref_gw and ref_cidr != "dhcp" and ref_gw != "dhcp":
                                    ref_net = ref_cidr.split("/")[0].rsplit(".", 1)[0] + ".0/" + ref_cidr.split("/")[1] if "/" in ref_cidr else ""
                                    rr_lines = []
                                    for s in inner_nets:
                                        if s != ref_cidr and (not ref_net or s != ref_net):
                                            rr_lines.append(f"set protocols static route {s} next-hop {ref_gw}")
                                    if rr_lines:
                                        d["return_routes_block"] = "\n".join(rr_lines)

                        # Prefix-list block (same as desktop generate_mpls_config lines 1930-1933)
                        inner_list = d.get("inner_nets") or []
                        if not inner_list:
                            inner_raw = str(mpls.get("DEFAULT_INNER_NETS", ""))
                            if inner_raw.strip():
                                import re as _re2
                                inner_list = [t.strip() for t in _re2.split(r'[\n,，\s]+', inner_raw) if t.strip() and "/" in t]
                        if inner_list and d.get("ce_as"):
                            prefix_lines = []
                            for i, n in enumerate(inner_list):
                                rule_num = 10 * (i + 1)
                                prefix_lines.append(f"set policy prefix-list AS{d['ce_as']}-OUT rule {rule_num} action 'permit'")
                                prefix_lines.append(f"set policy prefix-list AS{d['ce_as']}-OUT rule {rule_num} prefix '{n}'")
                            d["prefix_list_block"] = "\n".join(prefix_lines)

                        # Template-based generation (unified with ER/USG pattern)
                        try:
                            output = tpl.format(**d)
                        except Exception as _fe:
                            import traceback as _tb3
                            _tb3.print_exc()
                            output = f"# Template format error: {_fe}\n"
                if not output:
                    output = "# MPLS 配置生成暂不可用\n"
            except Exception as e:
                output = f"# {type(e).__name__}: {e}\n# {_tb.format_exc().replace(chr(10), chr(10)+'# ')}"

        return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
    except Exception as e:
        return jsonify({"ok": False, "error": _humanize_error(e, variant)}), 500


@app.route("/api/generate/ar_sdwan", methods=["POST"])
def generate_ar_sdwan():
    data = request.get_json(force=True)
    variant = data.get("variant", "single_ops")
    hdr_text = data.get("header_text", "")
    tool_id = "ar_sdwan"

    ar = _get_ar()
    _inject_ar_params(ar, data.get("network", {}))

    # Template-driven variant map
    _AR_VARIANT_MAP = {
        "single_ops": ("TEMPLATE_AR_OPS_SINGLE_WAN1", "build_ar_ops_single_wan1_fd"),
        "single_factory": ("TEMPLATE_AR_FACTORY_SINGLE_WAN1", "build_ar_factory_single_wan1_fd"),
        "single_dualwan": ("TEMPLATE_AR_OPS_SINGLE_DUALWAN", "build_ar_ops_single_dualwan_fd"),
        "dual_ops_pri": ("TEMPLATE_AR_OPS_DUAL_PRIMARY", "build_ar_ops_dual_pri_fd"),
        "dual_ops_bak": ("TEMPLATE_AR_OPS_DUAL_BACKUP", "build_ar_ops_dual_bak_fd"),
        "dual_factory_pri": ("TEMPLATE_AR_FACTORY_DUAL_PRIMARY", "build_ar_factory_dual_pri_fd"),
        "dual_factory_bak": ("TEMPLATE_AR_FACTORY_DUAL_BACKUP", "build_ar_factory_dual_bak_fd"),
    }

    try:
        tpl_slot, builder_name = _AR_VARIANT_MAP.get(variant, (None, None))
        ops_output = ""
        factory_output = ""

        if tpl_slot and builder_name:
            tpl = ar.get(tpl_slot, "")
            build_fn = ar.get(builder_name)
            if build_fn and tpl:
                d, _ = build_fn(hdr_text)
                if d:
                    output = ""
                    try:
                        output = tpl.format(**d)
                    except Exception:
                        pass
                    if "ops" in variant or "single" in variant:
                        ops_output = output
                    if "factory" in variant:
                        factory_output = output

        # Fallback to legacy render functions (for 'single', 'dual' variants from frontend)
        if not ops_output and not factory_output:
            parse_fn = ar.get("parse_ar_sdwan_text")
            if parse_fn:
                parsed = parse_fn(hdr_text)
                ops_fn = ar.get("render_ops_script")
                is_dual = "dual" in variant
                role = "pri" if variant == "dual" or "pri" in variant else "bak"
                device_type = "dual" if is_dual else "single"
                if ops_fn:
                    try:
                        init_cfg = {"mode": "ops", "device_type": device_type, "device_role": role}
                        ops_output = ops_fn(parsed, init_cfg)
                    except Exception:
                        ops_output = "# OPS script generation failed"
                # Factory function names are device-type-specific (not generic)
                if is_dual:
                    factory_fn = ar.get(f"render_factory_dual_{'primary' if role == 'pri' else 'backup'}")
                else:
                    factory_fn = ar.get("render_factory_single")
                if factory_fn:
                    try:
                        init_cfg = {"mode": "factory", "device_type": device_type, "device_role": role}
                        factory_output = factory_fn(init_cfg, parsed.get("lines", [{}])[0] if isinstance(parsed, dict) else {})
                    except Exception:
                        factory_output = "# Factory config generation failed"
            if not ops_output and not factory_output:
                return jsonify({"ok": False, "error": _humanize_error("Generation failed", variant)}), 500

        return jsonify({"ok": True, "ops_output": ops_output, "factory_output": factory_output, "output": ops_output or factory_output})
    except Exception as e:
        return jsonify({"ok": False, "error": _humanize_error(e, variant)}), 500


@app.route("/api/generate/ar_traditional", methods=["POST"])
def generate_ar_traditional():
    data = request.get_json(force=True)
    variant = data.get("variant", "dual")
    hdr_text = data.get("header_text", "")
    network = data.get("network", {})
    tool_id = "ar_traditional"

    try:
        mod = _get_ar_traditional()
        parse_fn = mod.get("parse_ar_traditional_headers")
        builder_fn = mod.get("build_ar_traditional_format_dict")
        tpl = _get_effective_template(mod, "TEMPLATE_AR_TRADITIONAL")

        if not parse_fn or not builder_fn:
            return jsonify({"ok": False, "error": _humanize_error("Builder not found", variant)}), 500

        main_line, backup_line, err = parse_fn(hdr_text)
        if err:
            return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400

        d = builder_fn(main_line, backup_line, network)
        if isinstance(d, tuple):
            d = d[0]  # unpack (dict, error) tuple
        if not isinstance(d, dict):
            return jsonify({"ok": False, "error": "Builder returned invalid data type"}), 500
        output = tpl.format(**d) if d and tpl else str(d)

        return _log_and_return(tool_id, variant, hdr_text, output,
                              jsonify({"ok": True, "output": output}))
    except KeyError as e:
        return jsonify({"ok": False, "error": f"模板变量缺失: {e}"}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": _humanize_error(e, variant)}), 500


# ── Example Data API ────────────────────────────────────────────────────

_EXAMPLE_MAP = {
    ("epoch_fastip", "hk"): ("er_fastip_2in1_v8.py", "HK_EXAMPLE"),
    ("epoch_fastip", "us"): ("er_fastip_2in1_v8.py", "US_EXAMPLE"),
    ("epoch_fastip", "flink"): ("er_fastip_2in1_v8.py", "ER_FL_DEFAULT_HEADERS"),
    ("epoch_fastip", "new_exit"): ("er_fastip_2in1_v8.py", "ER_NEW_EXIT_EXAMPLE"),
    ("epoch_fastip", "domain_split"): ("er_fastip_2in1_v8.py", "ER_DOMAIN_SPLIT_EXAMPLE"),
    ("usg_fastip", "us"): ("usg_fastip_3in1_v5.py", "US_EXAMPLE"),
    ("usg_fastip", "hk"): ("usg_fastip_3in1_v5.py", "HK_EXAMPLE"),
    ("usg_fastip", "flink"): ("usg_fastip_3in1_v5.py", "USG_FL_EXAMPLE"),
    ("usg_fastip", "new_exit"): ("usg_fastip_3in1_v5.py", "USG_NEW_EXIT_EXAMPLE"),
    ("epoch_mpls", "domestic"): ("er_mpls_v1.py", "CN_EXAMPLE"),
    ("epoch_mpls", "overseas"): ("er_mpls_v1.py", "OV_EXAMPLE"),
    ("epoch_mpls", "ipsec"): ("er_mpls_v1.py", "MPLS_IPSEC_EXAMPLE"),
    ("ar_sdwan", "single_ops"): ("ar_sdwan_zihuan_v4.py", "ZH_EXAMPLE"),
    ("ar_sdwan", "single_factory"): ("ar_sdwan_zihuan_v4.py", "ZH_EXAMPLE"),
    ("ar_sdwan", "dual_ops_pri"): ("ar_sdwan_zihuan_v4.py", "ZH_EXAMPLE"),
    ("ar_sdwan", "dual_ops_bak"): ("ar_sdwan_zihuan_v4.py", "ZH_EXAMPLE"),
    ("epoch_fastip5", "hk"): ("er_fastip_5in1_v1.py", "HK5_EXAMPLE"),
    ("epoch_fastip5", "us"): ("er_fastip_5in1_v1.py", "US5_EXAMPLE"),
    ("epoch_fastip5", "us_ipsec"): ("er_fastip_5in1_v1.py", "US5_IPSEC_EXAMPLE"),
    ("epoch_fastip5", "flink"): ("er_fastip_5in1_v1.py", "ER5_FLINK_EXAMPLE"),
    ("epoch_fastip5", "new_exit"): ("er_fastip_5in1_v1.py", "ER5_NEW_EXIT_EXAMPLE"),
    ("epoch_fastip5", "domain_split"): ("er_fastip_5in1_v1.py", "HK5_EXAMPLE"),
    ("ar_traditional", "dual"): ("ar_traditional_v1.py", "AR_TRAD_EXAMPLE"),
}


@app.route("/api/examples/<tool>/<variant>")
def api_examples(tool, variant):
    key = (tool, variant)
    if key not in _EXAMPLE_MAP:
        return jsonify({"ok": False, "error": _humanize_error(f"No example for {tool}/{variant}")}), 404
    module_name, var_name = _EXAMPLE_MAP[key]
    try:
        ns = _load_module(module_name)
        # 显式校验：映射指向的常量必须在模块里真实存在且非空，
        # 否则等于示例数据丢失——禁止静默返回空字符串兜底（AGENTS.md 硬规则 1）。
        if var_name not in ns:
            return jsonify({"ok": False, "error": _humanize_error(
                f"示例常量 {var_name} 未在 {module_name} 中定义（数据丢失）")}), 500
        text = str(ns.get(var_name, ""))
        if not text.strip():
            return jsonify({"ok": False, "error": _humanize_error(
                f"示例常量 {var_name} 为空（数据丢失）")}), 500
        return jsonify({"ok": True, "example": text})
    except Exception as e:
        return jsonify({"ok": False, "error": _humanize_error(e)}), 500


# ── Notes API ────────────────────────────────────────────────────────────

_NOTES = {
    "epoch_fastip": {
        "hk": (
            "Epoch FastIP · HK 香港出口\n\n"
            "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
            "• lan的dhcp是你开给别人的。\n"
            "• BGP更新源：默认使用 CE LOIP。如果要建公网的，请自行调整。\n"
            "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
            "• 请自行修改nat/dns/mtu等部分。\n"
            "• nat只会打第一个出口ip的。其余ip请自行添加。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "us": (
            "Epoch FastIP · 非香港出口\n\n"
            "• 奇数尾号 = 主线，偶数尾号 = 备线\n"
            "• 块内 PE 顺序不限，通过 PE 名称自动识别角色\n"
            "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
            "• lan的dhcp是你开给别人的。\n"
            "• BGP更新源：默认使用假ip。如果要建内网的，请自行调整。\n"
            "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
            "• 请自行修改nat/dns/mtu等部分。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "domain_split": (
            "Epoch FastIP · ER 域名分流\n\n"
            "• 此场景仅需填写参数，无需粘贴数据头\n"
            "• Address Group 名称决定 domainlist 文件和 policy-route 命名\n"
            "• NAT rule / 出口 tunnel / 主线出口 IP 需三者同时填写或同时留空\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "flink": (
            "Epoch FastIP · ER 飞连\n\n"
            "• 飞连场景仅需填写主备回程下一跳参数，无需粘贴数据头\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "new_exit": (
            "Epoch FastIP · ER 新增出口\n\n"
            "• 新增出口场景需粘贴数据头，并配置 PE 对接 / dum / NAT rule 等参数\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "default": "• 请自行修改nat/dns/mtu等部分。\n• 配置仅供参考，使用仍需谨慎。",
    },
    "epoch_fastip5": {
        "hk": (
            "Epoch FastIP 5.0 · HK 香港出口\n\n"
            "• 5.0 使用 VyOS set 语法，与 4.0 Epoch 语法完全不同。\n"
            "• 数据头格式与 4.0 相同。\n"
            "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
            "• lan的dhcp是你开给别人的。\n"
            "• BGP更新源：默认使用 CE LOIP。\n"
            "• 请自行修改nat/dns/mtu等部分。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "us": (
            "Epoch FastIP 5.0 · 非香港出口\n\n"
            "• 5.0 使用 VyOS set 语法，与 4.0 Epoch 语法完全不同。\n"
            "• 数据头包含三层隧道：ACVPN GRE + ACVPN vtun + US tunnel。\n"
            "• 奇数尾号 LineID = 主线，偶数尾号 = 备线。\n"
            "• BGP更新源：默认使用海外出口 NAT IP (FakeIP)。\n"
            "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
            "• lan的dhcp是你开给别人的。\n"
            "• 请自行修改nat/dns/mtu等部分。\n"
            "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "flink": "5.0 ER 飞连\n\n• 使用 failover2 语法进行路由切换\n• 填写 PE/FPE/预留IP 格式数据头\n• failover source IP 从主回程下一跳所在 /30 的偶数位自动计算\n• 配置仅供参考，使用仍需谨慎。",
        "new_exit": "5.0 ER 新增出口\n\n• 使用 5.0 VyOS set 语法\n• 数据头格式与 4.0 相同（LineID/PE/WANIP/TUNNEL/Docking/海外出口ip）\n• GRE Tunnel + dummy LoopBack + NAT 规则\n• MTU & ip adjust-mss 可按需调整\n• 配置仅供参考，使用仍需谨慎。",
        "domain_split": "5.0 ER 域名分流\n\n• 使用 VyOS domain-list（带连字符）+ name-server 语法\n• 策略路由 interface 独立行\n• FNET/100.100 探测使用 failover2 语法\n• 初始化参数与 4.0 域名分流完全一致\n• 配置仅供参考，使用仍需谨慎。",
        "default": "• 5.0 版本使用 VyOS set 语法。\n• 配置仅供参考，使用仍需谨慎。",
    },
    "usg_fastip": {
        "us": (
            "USG FastIP · 非香港出口\n\n"
            "• 主备各有一个 IPSec PE + FastIP PE 子块\n"
            "• 奇数尾号LineID = 主线，偶数尾号 = 备线\n"
            "• WAN IP / LAN IP 请按 x.x.x.x/x 的 CIDR 格式填写\n"
            "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
            "• lan的dhcp是你开给别人的。\n"
            "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
            "• 请自行修改nat/dns/mtu等部分。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "hk": (
            "USG FastIP · HK 香港出口\n\n"
            "• HK 出口场景，默认 DNS 使用 10.255.108.5 / 10.255.108.6\n"
            "• WAN IP / LAN IP 请按 x.x.x.x/x 的 CIDR 格式填写\n"
            "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
            "• lan的dhcp是你开给别人的。\n"
            "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
            "• 请自行修改nat/dns/mtu等部分。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "flink": (
            "USG FastIP · 飞连\n\n"
            "• 飞连场景仅需填写主备 Tunnel 号参数，无需粘贴数据头\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "new_exit": (
            "USG FastIP · 新增出口\n\n"
            "• 新增出口场景需粘贴数据头，并配置主备 Tunnel / LoopBack / NQA 参数\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "default": (
            "USG FastIP\n\n"
            "• WAN IP / LAN IP 请按 x.x.x.x/x 的 CIDR 格式填写\n"
            "• wan的dhcp是别人开给你的。wan开了dhcp，就不会生成默认路由。\n"
            "• lan的dhcp是你开给别人的。\n"
            "• 多出口ip请自己验证，不一定能识别到所有的分割符。\n"
            "• 请自行修改nat/dns/mtu等部分。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
    },
    "epoch_mpls": {
        "domestic": (
            "Epoch MPLS · 国内配置\n\n"
            "• 奇数尾号LineID = 主线，偶数尾号 = 备线\n"
            "• 每条线需要 GRE PE + VPN PE 两个子块\n"
            "• 需要 PE AS号 和 CE AS号\n"
            "• 内网段同时作为 prefix-list 中宣告的路由\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "overseas": (
            "Epoch MPLS · 海外配置\n\n"
            "• 奇数尾号LineID = 主线，偶数尾号 = 备线\n"
            "• 主线仅需一个 vtun 直连骨干（无 GRE）\n"
            "• 备线为标准 VPN+GRE 双隧道接入骨干\n"
            "• 内网段同时作为 prefix-list 中宣告的路由\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
        "ipsec": (
            "Epoch MPLS · IPSec\n\n"
            "• IPSec 不再区分国内/海外，使用统一数据头与统一模板\n"
            "• 业务数据需包含 LineID / PE / Tunnel / wanip / PE对接 / CE对接 / AS号\n"
            "• 同时补充 拨号PE / 对接IP / LoopIP / 拨号IP / 密钥\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
    },
    "ar_sdwan": {
        "default": (
            "AR SD-WAN 自环组网\n\n"
            "• 自己确认 IKE IPsec 参数！！！\n"
            "• 只有OPS脚本会被导出为txt\n"
            "• 南向服务可选。\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
    },
    "ar_traditional": {
        "dual": (
            "AR 传统组网 · 双线\n\n"
            "• 粘贴包含主备两条 LineID 的完整数据头\n"
            "• WAN/LAN 接口不支持 DHCP（传统组网均为静态 IP）\n"
            "• 勾选「回程路由」为内网段生成回程静态路由（tag 8888）\n"
            "• 勾选「旁挂模式」不生成 LAN 接口配置\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
    },
}


@app.route("/api/notes/<tool>")
def api_notes(tool):
    variant = request.args.get("variant", "")
    notes_map = _NOTES.get(tool, {})
    text = notes_map.get(variant) or notes_map.get("default", "")
    return jsonify({"ok": True, "notes": text})


# ── Sponsor Board API ───────────────────────────────────────────────────

@app.route("/api/sponsor-board")
def api_sponsor_board():
    """Return sponsor board rankings."""
    json_path = _DATA_RO_DIR / "sponsor_board" / "rankings.json"
    try:
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8-sig"))
            return jsonify({"ok": True, "board": data})
    except Exception:
        pass
    return jsonify({"ok": True, "board": {}})


# ── Template Editor API ─────────────────────────────────────────────────

# Disk aliases: display name → disk directory name (matches original _VISUAL_SCENARIO_DISK_ALIASES)
_DISK_ALIASES = {
    "Epoch FastIP · HK 香港出口": "ER FastIP · HK 香港出口",
    "Epoch FastIP · 非香港出口": "ER FastIP · 非HK出口",
    "Epoch FastIP · ER 飞连": "Epoch FastIP · ER 飞连",
    "Epoch FastIP · ER 新增出口": "Epoch FastIP · ER 新增出口",
    "Epoch FastIP · ER 域名分流": "Epoch FastIP · ER 域名分流",
    "Epoch FastIP 5.0 · HK 香港出口": "ER_FastIP_5_0___HK_香港出口",
    "Epoch FastIP 5.0 · 非香港出口": "ER_FastIP_5_0___非HK出口",
    "Epoch FastIP 5.0 · ER 飞连": "ER_FastIP_5_0___ER_飞连",
    "Epoch FastIP 5.0 · ER 新增出口": "ER_FastIP_5_0___ER_新增出口",
    "Epoch FastIP 5.0 · ER 域名分流": "ER_FastIP_5_0___ER_域名分流",
    "USG FastIP · 非香港出口": "USG FastIP · 非HK出口",
    "Epoch MPLS · 国内配置": "ER MPLS · 国内配置",
    "Epoch MPLS · 海外配置": "ER MPLS · 海外配置",
    "Epoch MPLS · IPSec": "Epoch MPLS · IPSec",
    "AR 传统组网 · 双线": "AR_传统组网",
}

# Compact variable descriptions for auto-generated mapping
_VAR_DESC_SMALL = {
    "hostname": "设备主机名", "wan_if": "WAN接口名", "wan_addr": "WAN IP/CIDR",
    "wan_gw": "WAN网关", "lan_if": "LAN接口名", "lan_ip": "LAN IP", "dns_ip1": "DNS主", "dns_ip2": "DNS备",
    "main_pe": "主线PE", "main_tunnel": "主线Tunnel", "main_wanip": "主线WANIP",
    "main_docking": "主线对接IP", "main_bgp1": "主线BGP1", "main_bgp2": "主线BGP2",
    "bk_pe": "备线PE", "bk_tunnel": "备线Tunnel", "bk_wanip": "备线WANIP",
    "bk_docking": "备线对接IP", "bk_bgp1": "备线BGP1", "bk_bgp2": "备线BGP2",
    "ce_loip": "CE LoopBack IP", "hkip_nat": "HK出口NAT IP", "hkip_nat_all": "全部HK出口IP",
    "main_dial_pe": "主线拨号PE", "main_dial_ip": "主线拨号IP", "main_loopback": "主线LoopIP",
    "main_auth_id": "主线认证ID", "main_peer_ip": "主线PE对接IP",
    "main_export_natip": "主线出口NAT IP", "main_export_summary": "主线出口IP汇总",
    "backup_dial_pe": "备线拨号PE", "backup_dial_ip": "备线拨号IP",
    "backup_loopback": "备线LoopIP", "backup_auth_id": "备线认证ID",
    "wan_if_block": "WAN接口块", "lan_if_block": "LAN接口块", "fw_options_block": "防火墙选项块",
    "return_routes_block": "回程路由块", "dhcp_server_block": "DHCP服务块",
    "wan_eth": "WAN口", "lan_eth": "LAN口", "wan_mode_desc": "WAN接入模式",
    "main_lineid": "主线LineID", "main_ce_docking": "主线CE对接",
    "main_psk": "主线PSK", "bk_lineid": "备线LineID", "bk_ce_docking": "备线CE对接",
    "bk_psk": "备线PSK", "south_primary": "南向主IP", "south_backup": "南向备IP",
    "main_pe": "主线PE", "main_tunnel": "主线Tunnel",
    "main_wanip": "主线WAN IP", "main_wan_ip_plain": "主线WAN IP(纯IP)",
    "main_pe_docking": "主线PE对接", "main_pe_as": "主线PE AS", "main_ce_as": "主线CE AS",
    "main_zihuan": "主线自环网段", "main_dial_pe": "主线拨号PE",
    "main_dial_docking_ip": "主线拨号对接IP", "main_loop_ip": "主线LoopIP",
    "main_dial_ip": "主线拨号IP", "main_tunnel_local_ip": "主线Tunnel本地IP",
    "main_tunnel_remote_ip": "主线Tunnel远端IP",
    "backup_lineid": "备线LineID", "backup_pe": "备线PE", "backup_tunnel": "备线Tunnel",
    "backup_wanip": "备线WAN IP", "backup_wan_ip_plain": "备线WAN IP(纯IP)",
    "backup_pe_docking": "备线PE对接", "backup_ce_docking": "备线CE对接",
    "backup_pe_as": "备线PE AS", "backup_ce_as": "备线CE AS",
    "backup_zihuan": "备线自环网段", "backup_dial_pe": "备线拨号PE",
    "backup_dial_docking_ip": "备线拨号对接IP", "backup_loop_ip": "备线LoopIP",
    "backup_dial_ip": "备线拨号IP", "backup_psk": "备线PSK",
    "backup_tunnel_local_ip": "备线Tunnel本地IP", "backup_tunnel_remote_ip": "备线Tunnel远端IP",
    "lan_ip": "LAN IP", "lan_mask": "LAN掩码", "wan_ip": "WAN IP", "wan_mask": "WAN掩码",
    "wan_if_name": "WAN接口", "lan_if_name": "LAN接口",
    "ce_as": "CE AS号", "bgp_router_id": "BGP Router ID",
    "peer_main_ip": "BGP主Peer", "peer_main_as": "BGP主Peer AS",
    "peer_backup_ip": "BGP备Peer", "peer_backup_as": "BGP备Peer AS",
    "bgp_networks_block": "BGP宣告网段", "bgp_filter_prefix_block": "BGP Filter Prefix",
    "acl_inner_rules_block": "内网ACL规则", "static_routes_block": "静态路由",
    "wan_if_block": "WAN接口块",
    "loopback_main_block": "主线LoopBack块", "loopback_backup_block": "备线LoopBack块",
    "tunnel_main_block": "主线GRE Tunnel块", "tunnel_backup_block": "备线GRE Tunnel块",
    "ike_peer_main_block": "主线IKE Peer块", "ike_peer_backup_block": "备线IKE Peer块",
    "ipsec_acl_main_block": "主线IPSec ACL块", "ipsec_acl_backup_block": "备线IPSec ACL块",
    "ipsec_policy_block": "IPSec Policy块", "wan_if_num": "WAN接口号", "lan_if_num": "LAN接口号",
    "lan_ip_full": "LAN IP/掩码", "wan_ip_full": "WAN IP/掩码",
    "lineid_main": "主线LineID", "lineid_backup": "备线LineID",
}


_SCENARIO_LIST = [
    {"key": "Epoch FastIP · HK 香港出口", "source": "er_fastip_2in1_v8.py", "tpl_slot": "TEMPLATE_EPOCH_HK"},
    {"key": "Epoch FastIP · HK 香港出口 · IPSec", "source": "er_fastip_2in1_v8.py", "tpl_slot": "TEMPLATE_EPOCH_HK_IPSEC"},
    {"key": "Epoch FastIP · 非香港出口", "source": "er_fastip_2in1_v8.py", "tpl_slot": "TEMPLATE_EPOCH_US"},
    {"key": "Epoch FastIP · 非香港出口 · IPSec", "source": "er_fastip_2in1_v8.py", "tpl_slot": "TEMPLATE_EPOCH_US_IPSEC"},
    {"key": "Epoch FastIP · ER 飞连", "source": "er_fastip_2in1_v8.py", "tpl_slot": "TEMPLATE_ER_FLINK_VISUAL"},
    {"key": "Epoch FastIP · ER 新增出口", "source": "er_fastip_2in1_v8.py", "tpl_slot": "TEMPLATE_ER_NEW_EXIT_VISUAL"},
    {"key": "Epoch FastIP · ER 域名分流", "source": "er_fastip_2in1_v8.py", "tpl_slot": "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL"},
    {"key": "Epoch FastIP 5.0 · HK 香港出口", "source": "er_fastip_5in1_v1.py", "tpl_slot": "TEMPLATE_EPOCH5_HK"},
    {"key": "Epoch FastIP 5.0 · 非香港出口", "source": "er_fastip_5in1_v1.py", "tpl_slot": "TEMPLATE_EPOCH5_US"},
    {"key": "Epoch FastIP 5.0 · 非香港出口 · IPSec", "source": "er_fastip_5in1_v1.py", "tpl_slot": "TEMPLATE_EPOCH5_US_IPSEC"},
    {"key": "Epoch FastIP 5.0 · ER 飞连", "source": "er_fastip_5in1_v1.py", "tpl_slot": "TEMPLATE_EPOCH5_FLINK"},
    {"key": "Epoch FastIP 5.0 · ER 新增出口", "source": "er_fastip_5in1_v1.py", "tpl_slot": "TEMPLATE_EPOCH5_NEW_EXIT"},
    {"key": "Epoch FastIP 5.0 · ER 域名分流", "source": "er_fastip_5in1_v1.py", "tpl_slot": "TEMPLATE_EPOCH5_DOMAIN_SPLIT"},
    {"key": "USG FastIP · 非香港出口", "source": "usg_fastip_3in1_v5.py", "tpl_slot": "TEMPLATE_USG_NONHK"},
    {"key": "USG FastIP · HK 香港出口", "source": "usg_fastip_3in1_v5.py", "tpl_slot": "TEMPLATE_USG_HK"},
    {"key": "USG FastIP · 飞连", "source": "usg_fastip_3in1_v5.py", "tpl_slot": "TEMPLATE_USG_FLINK_VISUAL"},
    {"key": "USG FastIP · 新增出口", "source": "usg_fastip_3in1_v5.py", "tpl_slot": "TEMPLATE_USG_NEW_EXIT_VISUAL"},
    {"key": "Epoch MPLS · 国内配置", "source": "er_mpls_v1.py", "tpl_slot": "TEMPLATE_MPLS_DOMESTIC"},
    {"key": "Epoch MPLS · IPSec", "source": "er_mpls_v1.py", "tpl_slot": "TEMPLATE_MPLS_IPSEC"},
    {"key": "Epoch MPLS · 海外配置", "source": "er_mpls_v1.py", "tpl_slot": "TEMPLATE_MPLS_OVERSEAS"},
    {"key": "AR SD-WAN · 单机单WAN · OPS", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_OPS_SINGLE_WAN1"},
    {"key": "AR SD-WAN · 单机单WAN · Factory", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_FACTORY_SINGLE_WAN1"},
    {"key": "AR SD-WAN · 单机双WAN · OPS", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_OPS_SINGLE_DUALWAN"},
    {"key": "AR SD-WAN · 单机双WAN · Factory", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_FACTORY_SINGLE_DUALWAN"},
    {"key": "AR SD-WAN · 双机主 OPS", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_OPS_DUAL_PRIMARY"},
    {"key": "AR SD-WAN · 双机备 OPS", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_OPS_DUAL_BACKUP"},
    {"key": "AR SD-WAN · 双机主 Factory", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_FACTORY_DUAL_PRIMARY"},
    {"key": "AR SD-WAN · 双机备 Factory", "source": "ar_sdwan_zihuan_v4.py", "tpl_slot": "TEMPLATE_AR_FACTORY_DUAL_BACKUP"},
    {"key": "AR 传统组网 · 双线", "source": "ar_traditional_v1.py", "tpl_slot": "TEMPLATE_AR_TRADITIONAL"},
]


_SCENARIO_TREE = [
    {
        "label": "Epoch FastIP",
        "children": [
            {
                "label": "4.0",
                "children": [
                    {"label": "HK · OpenVPN",   "key": "Epoch FastIP · HK 香港出口"},
                    {"label": "HK · IPSec",     "key": "Epoch FastIP · HK 香港出口 · IPSec"},
                    {"label": "非香港 · OpenVPN", "key": "Epoch FastIP · 非香港出口"},
                    {"label": "非香港 · IPSec",   "key": "Epoch FastIP · 非香港出口 · IPSec"},
                ],
            },
            {
                "label": "5.0",
                "children": [
                    {"label": "HK · OpenVPN",   "key": "Epoch FastIP 5.0 · HK 香港出口"},
                    {"label": "非香港 · OpenVPN", "key": "Epoch FastIP 5.0 · 非香港出口"},
                    {"label": "非香港 · IPSec",   "key": "Epoch FastIP 5.0 · 非香港出口 · IPSec"},
                ],
            },
            {
                "label": "小应用",
                "children": [
                    {"label": "4.0 · ER 飞连",     "key": "Epoch FastIP · ER 飞连"},
                    {"label": "5.0 · ER 飞连",     "key": "Epoch FastIP 5.0 · ER 飞连"},
                    {"label": "4.0 · ER 新增出口", "key": "Epoch FastIP · ER 新增出口"},
                    {"label": "5.0 · ER 新增出口", "key": "Epoch FastIP 5.0 · ER 新增出口"},
                    {"label": "4.0 · ER 域名分流", "key": "Epoch FastIP · ER 域名分流"},
                    {"label": "5.0 · ER 域名分流", "key": "Epoch FastIP 5.0 · ER 域名分流"},
                ],
            },
        ],
    },
    {
        "label": "USG FastIP",
        "children": [
            {"label": "HK 香港出口", "key": "USG FastIP · HK 香港出口"},
            {"label": "非香港出口",  "key": "USG FastIP · 非香港出口"},
            {"label": "飞连",        "key": "USG FastIP · 飞连"},
            {"label": "新增出口",    "key": "USG FastIP · 新增出口"},
        ],
    },
    {
        "label": "Epoch MPLS",
        "children": [
            {"label": "国内配置", "key": "Epoch MPLS · 国内配置"},
            {"label": "海外配置", "key": "Epoch MPLS · 海外配置"},
            {"label": "IPSec",    "key": "Epoch MPLS · IPSec"},
        ],
    },
    {
        "label": "AR SD-WAN",
        "children": [
            {
                "label": "单机单 WAN",
                "children": [
                    {"label": "OPS",     "key": "AR SD-WAN · 单机单WAN · OPS"},
                    {"label": "Factory", "key": "AR SD-WAN · 单机单WAN · Factory"},
                ],
            },
            {
                "label": "单机双 WAN",
                "children": [
                    {"label": "OPS",     "key": "AR SD-WAN · 单机双WAN · OPS"},
                    {"label": "Factory", "key": "AR SD-WAN · 单机双WAN · Factory"},
                ],
            },
            {
                "label": "双机",
                "children": [
                    {"label": "主 OPS",     "key": "AR SD-WAN · 双机主 OPS"},
                    {"label": "备 OPS",     "key": "AR SD-WAN · 双机备 OPS"},
                    {"label": "主 Factory", "key": "AR SD-WAN · 双机主 Factory"},
                    {"label": "备 Factory", "key": "AR SD-WAN · 双机备 Factory"},
                ],
            },
        ],
    },
    {
        "label": "AR 传统组网",
        "children": [
            {"label": "双线", "key": "AR 传统组网 · 双线"},
        ],
    },
]


def _scenario_tree_leaf_keys(tree):
    """递归收集树中所有叶子的 scenario key。"""
    keys = []
    for node in tree:
        if "children" in node:
            keys.extend(_scenario_tree_leaf_keys(node["children"]))
        elif "key" in node:
            keys.append(node["key"])
    return keys


def _validate_scenario_tree():
    """启动期校验：树中每个 leaf key 必须能在 _SCENARIO_LIST 找到对应模板配置。"""
    flat_keys = {s["key"] for s in _SCENARIO_LIST}
    missing = [k for k in _scenario_tree_leaf_keys(_SCENARIO_TREE) if k not in flat_keys]
    if missing:
        raise RuntimeError(
            "_SCENARIO_TREE 中存在 _SCENARIO_LIST 未注册的场景 key："
            + ", ".join(missing)
        )


_validate_scenario_tree()


@app.route("/api/scenarios")
def api_scenarios():
    return jsonify({"ok": True, "scenarios": _SCENARIO_LIST, "tree": _SCENARIO_TREE})


@app.route("/api/template/load", methods=["POST"])
def api_template_load():
    data = request.get_json(force=True)
    scenario_key = data.get("key", "")
    info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
    if not info:
        return jsonify({"ok": False, "error": _humanize_error("Scenario not found")}), 404

    ns = _load_module(info["source"])
    slot = info["tpl_slot"]
    disk_key = _DISK_ALIASES.get(scenario_key, scenario_key)
    safe_key = re.sub(r"[^\w一-鿿]", "_", disk_key)
    ws_dir = _get_user_data_dir() / "editor_workspace" / safe_key
    def_dir = _DATA_RO_DIR / "editor_defaults" / safe_key

    def _read_file(name):
        for d in (ws_dir, def_dir):
            p = d / name
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8-sig")
                    if text.strip():
                        return text
                except Exception:
                    pass
        return ""

    hdr = _read_file("headers.txt")
    mp = _read_file("mapping.txt")
    tpl = _read_file(f"{slot}.tpl")

    # Fallback to module template variable
    if not tpl.strip():
        tpl = str(ns.get(slot, ""))
    # If template still empty, try alternate names
    if not tpl.strip():
        for alt in (slot.replace("TEMPLATE_", ""), slot):
            tpl = str(ns.get(alt, ""))
            if tpl.strip():
                break

    # Fallback header: try module example data first, then template variables
    if not hdr.strip():
        example_keys = {
            "TEMPLATE_EPOCH_HK": "HK_EXAMPLE",
            "TEMPLATE_EPOCH_US": "US_EXAMPLE",
            "TEMPLATE_EPOCH5_HK": "HK5_EXAMPLE",
            "TEMPLATE_EPOCH5_US": "US5_EXAMPLE",
            "TEMPLATE_EPOCH5_US_IPSEC": "US5_IPSEC_EXAMPLE",
            "TEMPLATE_EPOCH5_FLINK": "ER5_FLINK_EXAMPLE",
            "TEMPLATE_EPOCH5_NEW_EXIT": "ER5_NEW_EXIT_EXAMPLE",
            "TEMPLATE_EPOCH_HK_IPSEC": "HK_EXAMPLE_IPSEC",
            "TEMPLATE_EPOCH_US_IPSEC": "US_EXAMPLE_IPSEC",
            "TEMPLATE_ER_FLINK_VISUAL": "ER_FL_DEFAULT_HEADERS",
            "TEMPLATE_ER_NEW_EXIT_VISUAL": "ER_NEW_EXIT_EXAMPLE",
            "TEMPLATE_USG_HK": "HK_EXAMPLE",
            "TEMPLATE_USG_NONHK": "US_EXAMPLE",
            "TEMPLATE_USG_FLINK_VISUAL": "USG_FL_EXAMPLE",
            "TEMPLATE_USG_NEW_EXIT_VISUAL": "USG_NEW_EXIT_EXAMPLE",
            "TEMPLATE_MPLS_DOMESTIC": "CN_EXAMPLE",
            "TEMPLATE_MPLS_OVERSEAS": "OV_EXAMPLE",
            "TEMPLATE_MPLS_IPSEC": "MPLS_IPSEC_EXAMPLE",
            "TEMPLATE_AR_OPS_SINGLE_WAN1": "ZH_EXAMPLE",
            "TEMPLATE_AR_FACTORY_SINGLE_WAN1": "ZH_EXAMPLE",
            "TEMPLATE_AR_OPS_SINGLE_DUALWAN": "ZH_EXAMPLE",
            "TEMPLATE_AR_FACTORY_SINGLE_DUALWAN": "ZH_EXAMPLE",
            "TEMPLATE_AR_OPS_DUAL_PRIMARY": "ZH_EXAMPLE",
            "TEMPLATE_AR_OPS_DUAL_BACKUP": "ZH_EXAMPLE",
            "TEMPLATE_AR_FACTORY_DUAL_PRIMARY": "ZH_EXAMPLE",
            "TEMPLATE_AR_FACTORY_DUAL_BACKUP": "ZH_EXAMPLE",
            "TEMPLATE_AR_TRADITIONAL": "AR_TRAD_EXAMPLE",
        }
        example_var = example_keys.get(slot, "")
        if example_var:
            hdr = str(ns.get(example_var, ""))
        if not hdr.strip() and tpl:
            vars_found = list(dict.fromkeys(re.findall(r"\{(\w+)\}", tpl)))
            if vars_found:
                hdr = "\n".join(f"{v} = " for v in vars_found[:40])

    # Auto-generate mapping from template variables
    mp_lines = []
    if tpl and not mp.strip():
        vars_found = list(dict.fromkeys(re.findall(r"\{(\w+)\}", tpl)))
        for v in vars_found[:60]:
            desc = _VAR_DESC_SMALL.get(v, v)
            mp_lines.append(f"{v}  {desc}")
        mp = "\n".join(mp_lines)

    _touch_reload_stamp()
    return jsonify({"ok": True, "header": hdr, "mapping": mp, "template": tpl})


@app.route("/api/template/save", methods=["POST"])
def api_template_save():
    denied = _require_login()
    if denied:
        return denied
    data = request.get_json(force=True)
    scenario_key = data.get("key", "")
    hdr = data.get("header", "")
    mp = data.get("mapping", "")
    tpl = data.get("template", "")

    info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
    if not info:
        return jsonify({"ok": False, "error": _humanize_error("Scenario not found")}), 404

    disk_key = _DISK_ALIASES.get(scenario_key, scenario_key)
    safe_key = re.sub(r"[^\w一-鿿]", "_", disk_key)
    ws_dir = _get_user_data_dir() / "editor_workspace" / safe_key
    ws_dir.mkdir(parents=True, exist_ok=True)
    slot = info["tpl_slot"]

    try:
        # 原子写入：先写唯一临时文件再 rename，避免并发 save 临时文件冲突
        import tempfile, os
        from datetime import datetime
        # 在 .tpl 模板顶部加专属注释行：xxx专属yyy场景模板-yymmdd
        # 重复保存时先移除旧的注释行，避免累积
        username = _get_request_username() or "用户"
        yymmdd = datetime.now().strftime("%y%m%d")
        comment_line = f"# {username}专属{scenario_key}场景模板-{yymmdd}\n"
        tpl_lines = tpl.split("\n")
        tpl_lines = [l for l in tpl_lines if not re.match(r"^# .+专属.+场景模板-\d{6}$", l)]
        tpl_with_comment = comment_line + "\n".join(tpl_lines)
        for fname, content in [("headers.txt", hdr), ("mapping.txt", mp), (f"{slot}.tpl", tpl_with_comment)]:
            fp = ws_dir / fname
            tf = ws_dir / f".{fname}.{os.getpid()}.{id(content)}.tmp"
            tf.write_text(content, encoding="utf-8-sig")
            tf.replace(fp)
        # 不调 _apply_template_to_runtime：generate 从磁盘读模板（_get_effective_template），
        # ns 里的模板保持出厂值不变，避免 save 影响并发 generate。
        _touch_reload_stamp()
        return jsonify({"ok": True, "message": f"Saved to {ws_dir}"})
    except Exception as e:
        return jsonify({"ok": False, "error": _humanize_error(e)}), 500


@app.route("/api/template/reset", methods=["POST"])
def api_template_reset():
    denied = _require_login()
    if denied:
        return denied
    data = request.get_json(force=True)
    scenario_key = data.get("key", "")
    info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
    if not info:
        return jsonify({"ok": False, "error": _humanize_error("Scenario not found")}), 404

    ns = _load_module(info["source"])
    slot = info["tpl_slot"]
    # ALWAYS read from disk (editor_defaults) first for reset — NOT from in-memory ns
    disk_key = _DISK_ALIASES.get(scenario_key, scenario_key)
    safe_key = re.sub(r"[^\w一-鿿]", "_", disk_key)

    # Delete workspace files so next restart loads factory template
    ws_dir = _get_user_data_dir() / "editor_workspace" / safe_key
    if ws_dir.is_dir():
        for fname in ("headers.txt", "mapping.txt", f"{slot}.tpl"):
            fp = ws_dir / fname
            try:
                if fp.exists():
                    fp.unlink()
            except Exception:
                pass

    tpl = ""
    for d in (_DATA_RO_DIR / "editor_defaults" / safe_key,):
        p = d / f"{slot}.tpl"
        if p.exists():
            try:
                tpl = p.read_text(encoding="utf-8-sig")
                if tpl.strip():
                    break
            except Exception:
                pass
    # Fallback: read factory template from editor_defaults (no re-exec)
    if not tpl.strip():
        # Factory template not on disk → read from ns (already loaded at init)
        tpl = str(ns.get(slot, ""))
    # 不改 ns：generate 从磁盘读模板（_get_effective_template），
    # ns 保持出厂值，reset 只删磁盘文件。

    # Try example data first
    example_keys = {
        "TEMPLATE_EPOCH_HK": "HK_EXAMPLE", "TEMPLATE_EPOCH_US": "US_EXAMPLE",
        "TEMPLATE_ER_FLINK_VISUAL": "ER_FL_DEFAULT_HEADERS",
        "TEMPLATE_ER_NEW_EXIT_VISUAL": "ER_NEW_EXIT_EXAMPLE",
        "TEMPLATE_USG_HK": "HK_EXAMPLE", "TEMPLATE_USG_NONHK": "US_EXAMPLE",
        "TEMPLATE_USG_NEW_EXIT_VISUAL": "USG_NEW_EXIT_EXAMPLE",
        "TEMPLATE_MPLS_DOMESTIC": "CN_EXAMPLE", "TEMPLATE_MPLS_OVERSEAS": "OV_EXAMPLE",
        "TEMPLATE_MPLS_IPSEC": "MPLS_IPSEC_EXAMPLE",
        "TEMPLATE_AR_TRADITIONAL": "AR_TRAD_EXAMPLE",
    }
    example_var = example_keys.get(slot, "")
    hdr = str(ns.get(example_var, "")) if example_var else ""
    vars_found = list(dict.fromkeys(re.findall(r"\{(\w+)\}", tpl)))
    if not hdr.strip() and vars_found:
        hdr = "\n".join(f"{v} = " for v in vars_found[:40])

    # Restore factory template to runtime namespace
    if tpl.strip():
        ns[slot] = tpl

    mp_lines = []
    for v in vars_found[:60]:
        desc = _VAR_DESC_SMALL.get(v, v)
        mp_lines.append(f"{v}  {desc}")
    mp = "\n".join(mp_lines)

    _touch_reload_stamp()
    return jsonify({"ok": True, "header": hdr, "mapping": mp, "template": tpl})


# ── Preview API ──────────────────────────────────────────────────────────

@app.route("/api/template/preview", methods=["POST"])
def api_template_preview():
    denied = _require_login()
    if denied:
        return denied
    """Real preview using parser + builder, same as original VisualEditorTab.preview()."""
    data = request.get_json(force=True)
    scenario_key = data.get("key", "")
    hdr_text = data.get("header", "")
    tpl_text = data.get("template", "")

    info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
    if not info:
        return jsonify({"ok": False, "error": _humanize_error("Scenario not found")}), 404

    ns = _load_module(info["source"])
    slot = info["tpl_slot"]
    tpl = tpl_text.strip() or str(ns.get(slot, ""))

    try:
        # Determine which parser+builder to use per scenario
        rendered = ""
        parse_err = ""
        filled = 0
        total = 0

        if slot == "TEMPLATE_EPOCH_HK":
            fn = ns.get("build_epoch_hk_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_EPOCH_HK_IPSEC":
            fn = ns.get("build_epoch_hk_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_EPOCH_US":
            fn = ns.get("build_epoch_us_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_EPOCH_US_IPSEC":
            fn = ns.get("build_epoch_us_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_ER_FLINK_VISUAL":
            parse_fn = ns.get("parse_er_flink_headers")
            fmt_fn = ns.get("_build_er_flink_format_dict")
            build_fn = ns.get("build_er_flink_config")
            if parse_fn:
                routes, err = parse_fn(hdr_text)
                if not err:
                    main_nh = str(ns.get("ER_FL_MAIN_NH_DEFAULT", "10.1.1.1"))
                    backup_nh = str(ns.get("ER_FL_BACKUP_NH_DEFAULT", "10.2.1.1"))
                    if fmt_fn and tpl:
                        d = fmt_fn(routes, main_nh, backup_nh)
                        if d:
                            try:
                                rendered = tpl.format(**d)
                            except Exception:
                                rendered = ""
                    if not rendered and build_fn:
                        rendered = build_fn(routes, main_nh, backup_nh)
                else:
                    parse_err = str(err)
        elif slot == "TEMPLATE_ER_NEW_EXIT_VISUAL":
            parse_fn = ns.get("parse_er_new_exit_blocks")
            build_fn = ns.get("build_er_new_exit_config")
            fmt_fn = ns.get("_build_er_new_exit_format_dict")
            if parse_fn:
                result = parse_fn(hdr_text)
                parsed = result[0] if isinstance(result, tuple) else result
                if isinstance(parsed, dict):
                    init_cfg = {
                        "main_pe_next_hop": str(ns.get("ER_NE_MAIN_PE_NH_DEFAULT", "192.168.1.1")),
                        "main_dum_start": int(str(ns.get("ER_NE_MAIN_DUM_DEFAULT", "300"))),
                        "main_nat_rule_start": int(str(ns.get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300"))),
                        "main_nat_rule": str(ns.get("ER_NE_MAIN_NAT_RULE_DEFAULT", "300")),
                        "bk_pe_next_hop": str(ns.get("ER_NE_BK_PE_NH_DEFAULT", "192.168.1.2")),
                        "bk_dum_start": int(str(ns.get("ER_NE_BK_DUM_DEFAULT", "400"))),
                        "bk_nat_rule_start": int(str(ns.get("ER_NE_BK_NAT_RULE_DEFAULT", "400"))),
                        "bk_nat_rule": str(ns.get("ER_NE_BK_NAT_RULE_DEFAULT", "400")),
                        "main_nat_source_cidr": str(ns.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "")),
                        "bk_nat_source_cidr": str(ns.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "")),
                        "nat_source_cidr": str(ns.get("ER_NE_NAT_SOURCE_CIDR_DEFAULT", "")),
                        "fnet_probe": str(ns.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")),
                        "fnet_exit_tunnel": str(ns.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")),
                        "fnet_nat_rule": str(ns.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")),
                    }
                    if fmt_fn and tpl:
                        d = fmt_fn(parsed, init_cfg)
                        if isinstance(d, dict):
                            try:
                                rendered = tpl.format(**d)
                            except Exception:
                                pass
                    if not rendered and build_fn:
                        rendered = build_fn(parsed, init_cfg)
        elif slot == "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL":
            extras_fn = ns.get("er_ds_template_preview_extras")
            d = {}
            # Parse header text AND inject module defaults for all DS_ variables
            for line in (hdr_text or "").splitlines():
                m = re.match(r"(\S+)\s*[=:]\s*(.+)", line.strip())
                if m:
                    d[m.group(1)] = m.group(2).strip()
            for k in ("ER_DS_DOMAINS_DEFAULT", "ER_DS_ADDR_GROUP_DEFAULT",
                      "ER_DS_RULE_NUM_DEFAULT", "ER_DS_TABLE_NUM_DEFAULT",
                      "ER_DS_SOURCE_CIDR_DEFAULT", "ER_DS_ETH_DEFAULT",
                      "ER_DS_DNS1_DEFAULT", "ER_DS_DNS2_DEFAULT",
                      "ER_DS_TABLE_NH_PRIMARY_DEFAULT", "ER_DS_STATIC32_PRIMARY_NH_DEFAULT",
                      "ER_DS_TRACK_NAME_DEFAULT", "ER_DS_STATIC32_BACKUP_NH_DEFAULT",
                      "ER_DS_FNET_PROBE_DEFAULT", "ER_DS_FNET_NAT_RULE_DEFAULT",
                      "ER_DS_EXIT_TUNNEL_DEFAULT", "ER_DS_EXIT_SNAT_IP_DEFAULT"):
                if k not in d:
                    v = ns.get(k, "")
                    if v:
                        d[k] = str(v)
            if extras_fn:
                try:
                    extras = extras_fn(d)
                    if isinstance(extras, dict):
                        d.update(extras)
                except Exception:
                    pass
            if d:
                rendered = tpl.format(**d)
        elif slot in ("TEMPLATE_USG_HK", "TEMPLATE_USG_NONHK"):
            fn = ns.get("build_usg_hk_format_dict" if slot == "TEMPLATE_USG_HK" else "build_usg_us_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_USG_FLINK_VISUAL":
            build_fn = ns.get("build_usg_flink_format_dict")
            if build_fn:
                d, err = build_fn(
                    hdr_text,
                    main_tun=str(ns.get("USG_FL_MAIN_TUN_DEFAULT", "3000")),
                    bk_tun=str(ns.get("USG_FL_BK_TUN_DEFAULT", "4000")),
                )
                if err:
                    rendered = f"# {err}"
                elif d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_USG_NEW_EXIT_VISUAL":
            parse_fn = ns.get("parse_usg_new_exit_blocks")
            build_fn = ns.get("build_usg_new_exit_format_dict")
            if parse_fn:
                result = parse_fn(hdr_text)
                parsed = result[0] if isinstance(result, tuple) else result
                if build_fn and isinstance(parsed, dict):
                    init_cfg = {
                        "main_tun": int(str(ns.get("USG_NE_MAIN_TUN_DEFAULT", "1001"))),
                        "bk_tun": int(str(ns.get("USG_NE_BK_TUN_DEFAULT", "1002"))),
                        "main_loop_start": int(str(ns.get("USG_NE_MAIN_LOOP_START_DEFAULT", "111"))),
                        "bk_loop_start": int(str(ns.get("USG_NE_BK_LOOP_START_DEFAULT", "211"))),
                        "main_nqa": str(ns.get("USG_NE_MAIN_NQA_DEFAULT", "main2")),
                        "bk_nqa": str(ns.get("USG_NE_BK_NQA_DEFAULT", "backup2")),
                    }
                    d = build_fn(parsed, init_cfg)
                    rendered = tpl.format(**d) if tpl else str(d)
        elif slot == "TEMPLATE_EPOCH5_FLINK":
            parse_fn = ns.get("parse_epoch5_flink_headers")
            fmt_fn = ns.get("_build_epoch5_flink_format_dict")
            if parse_fn and hdr_text.strip():
                routes, err = parse_fn(hdr_text)
                if not err:
                    main_nh = str(ns.get("ER5_FL_MAIN_NH_DEFAULT", "10.1.1.1"))
                    backup_nh = str(ns.get("ER5_FL_BACKUP_NH_DEFAULT", "10.2.1.1"))
                    if fmt_fn:
                        d = fmt_fn(routes, main_nh, backup_nh)
                        if d:
                            try:
                                rendered = tpl.format(**d)
                            except Exception:
                                pass
        elif slot == "TEMPLATE_EPOCH5_NEW_EXIT":
            parse_fn = ns.get("parse_epoch5_new_exit_blocks")
            build_fn = ns.get("build_epoch5_new_exit_format_dict")
            if parse_fn and hdr_text.strip():
                result = parse_fn(hdr_text)
                parsed = result[0] if isinstance(result, tuple) else result
                err = result[1] if isinstance(result, tuple) else None
                if not err and isinstance(parsed, dict) and build_fn:
                    init_cfg = {
                        "main_pe_next_hop": str(ns.get("ER5_NE_MAIN_PE_NH_DEFAULT", "10.1.1.1")),
                        "main_dum_start": int(str(ns.get("ER5_NE_MAIN_DUM_DEFAULT", "300"))),
                        "main_nat_rule": str(ns.get("ER5_NE_MAIN_NAT_RULE_DEFAULT", "1001")),
                        "bk_pe_next_hop": str(ns.get("ER5_NE_BK_PE_NH_DEFAULT", "10.2.1.1")),
                        "bk_dum_start": int(str(ns.get("ER5_NE_BK_DUM_DEFAULT", "400"))),
                        "bk_nat_rule": str(ns.get("ER5_NE_BK_NAT_RULE_DEFAULT", "2001")),
                        "nat_group_name": str(ns.get("ER5_NE_NAT_GROUP_DEFAULT", "LAN-NET1")),
                        "nat_source_cidr": str(ns.get("ER5_NE_NAT_SOURCE_CIDR_DEFAULT", "192.168.0.0/24")),
                        "fnet_probe": str(ns.get("ER5_NE_FNET_PROBE_DEFAULT", "")),
                        "fnet_exit_tunnel": str(ns.get("ER5_NE_FNET_EXIT_TUNNEL_DEFAULT", "tun")),
                        "fnet_nat_rule": str(ns.get("ER5_NE_FNET_NAT_RULE_DEFAULT", "")),
                    }
                    d = build_fn(parsed, init_cfg)
                    if isinstance(d, dict):
                        try:
                            rendered = tpl.format(**d)
                        except Exception:
                            pass
        elif slot == "TEMPLATE_EPOCH5_HK":
            fn = ns.get("build_epoch5_hk_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_EPOCH5_US":
            fn = ns.get("build_epoch5_us_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_EPOCH5_US_IPSEC":
            fn = ns.get("build_epoch5_us_ipsec_format_dict")
            if fn:
                result = fn(hdr_text)
                d = result[0] if isinstance(result, tuple) else result
                if d:
                    rendered = tpl.format(**d)
        elif slot == "TEMPLATE_EPOCH5_DOMAIN_SPLIT":
            fn = ns.get("build_epoch5_domain_split_format_dict")
            if fn:
                result = fn(hdr_text)
                output_str, err = result if isinstance(result, tuple) else (result, None)
                if output_str:
                    rendered = output_str
        elif slot in ("TEMPLATE_MPLS_DOMESTIC", "TEMPLATE_MPLS_OVERSEAS"):
            build_fn = ns.get("build_mpls_domestic_format_dict" if "DOMESTIC" in slot else "build_mpls_overseas_format_dict")
            gen_fn = ns.get("generate_mpls_config")
            if build_fn and tpl:
                d, _ = build_fn(hdr_text)
                if d:
                    _inject_network_to_parsed(ns, d)
                    try:
                        rendered = tpl.format(**d)
                    except Exception:
                        pass
            if not rendered and gen_fn:
                parsed = ns.get("parse_epoch_mpls")(hdr_text) if ns.get("parse_epoch_mpls") else {}
                parsed["config_type"] = "国内" if "DOMESTIC" in slot else "海外"
                _inject_network_to_parsed(ns, parsed)
                rendered = gen_fn(parsed)
        elif slot == "TEMPLATE_MPLS_IPSEC":
            build_fn = ns.get("build_mpls_ipsec_format_dict")
            gen_fn = ns.get("generate_mpls_ipsec_config")
            wan_blocks_fn = ns.get("build_wan_lan_blocks")
            if build_fn and gen_fn:
                d = build_fn(hdr_text, hostname="", net=None)
                if wan_blocks_fn:
                    weth = str(ns.get("DEFAULT_WAN_ETH", "0"))
                    leth = str(ns.get("DEFAULT_LAN_ETH", "1"))
                    wan_cidr = str(ns.get("DEFAULT_WAN_CIDR", "192.168.1.10/24"))
                    wan_gw = str(ns.get("DEFAULT_WAN_GW", "192.168.1.1"))
                    lan_cidr = str(ns.get("DEFAULT_LAN_CIDR", "192.168.5.1/24"))
                    blocks = wan_blocks_fn(f"eth{weth}", False, wan_cidr, wan_gw, f"eth{leth}", True, lan_cidr, False)
                    if isinstance(blocks, dict):
                        d.update(blocks)
                _inject_network_to_parsed(ns, d)
                rendered = gen_fn(d)
        elif slot == "TEMPLATE_AR_TRADITIONAL":
            parse_fn = ns.get("parse_ar_traditional_headers")
            builder_fn = ns.get("build_ar_traditional_format_dict")
            if parse_fn and builder_fn and tpl:
                main_line, backup_line, err = parse_fn(hdr_text)
                if err:
                    parse_err = str(err)
                else:
                    d = builder_fn(main_line, backup_line)
                    if isinstance(d, tuple):
                        d = d[0]
                    if isinstance(d, dict):
                        try:
                            rendered = tpl.format(**d)
                        except Exception:
                            rendered = ""
        elif "TEMPLATE_AR_" in slot:
            # Map each AR SD-WAN slot to its builder function
            _AR_SLOT_BUILDERS = {
                "TEMPLATE_AR_OPS_SINGLE_WAN1": "build_ar_ops_single_wan1_fd",
                "TEMPLATE_AR_FACTORY_SINGLE_WAN1": "build_ar_factory_single_wan1_fd",
                "TEMPLATE_AR_OPS_SINGLE_DUALWAN": "build_ar_ops_single_dualwan_fd",
                "TEMPLATE_AR_FACTORY_SINGLE_DUALWAN": "build_ar_factory_single_dualwan_fd",
                "TEMPLATE_AR_OPS_DUAL_PRIMARY": "build_ar_ops_dual_pri_fd",
                "TEMPLATE_AR_OPS_DUAL_BACKUP": "build_ar_ops_dual_bak_fd",
                "TEMPLATE_AR_FACTORY_DUAL_PRIMARY": "build_ar_factory_dual_pri_fd",
                "TEMPLATE_AR_FACTORY_DUAL_BACKUP": "build_ar_factory_dual_bak_fd",
            }
            builder_name = _AR_SLOT_BUILDERS.get(slot, "")
            build_fn = ns.get(builder_name) if builder_name else None
            if build_fn and tpl:
                d, _ = build_fn(hdr_text)
                if d:
                    try:
                        rendered = tpl.format(**d)
                    except Exception:
                        pass
            # Fallback to legacy render
            if not rendered:
                ops_fn = ns.get("render_ops_script")
                parse_fn = ns.get("parse_ar_sdwan_text")
                if parse_fn and ops_fn:
                    parsed = parse_fn(hdr_text)
                    init_cfg = {"mode": "ops", "device_type": "single", "device_role": "pri"}
                    rendered = ops_fn(parsed, init_cfg)

        if not rendered:
            if parse_err:
                return jsonify({"ok": False, "error": _humanize_error(f"Parser error: {parse_err}")}), 400
            return jsonify({"ok": False, "error": _humanize_error(f"No preview handler: {slot}")}), 400

        return jsonify({
            "ok": True,
            "output": rendered,
            "filled": filled,
            "total": total,
            "parse_err": parse_err,
        })
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": _humanize_error(e), "trace": traceback.format_exc()}), 500


# ── VISUAL_PROG_OVERRIDE (for tpl_static scenarios) ─────────────────────

_VISUAL_PROG_OVERRIDE: dict[str, str] = {}


def _apply_template_to_runtime(key: str, info: dict, tpl: str) -> None:
    """Apply template to module namespace (tpl_var) or override dict (tpl_static)."""
    ns = _load_module(info["source"])
    slot = info["tpl_slot"]
    text = tpl.strip()
    # tpl_var: direct string template in module namespace
    tpl_var = slot  # For most scenarios, slot IS the variable name
    if tpl_var in ns and isinstance(ns[tpl_var], str):
        ns[tpl_var] = text
    # tpl_static: check if different from baseline, store override
    sk = slot.lower().replace("template_", "")
    # tpl_static: legacy overrides for scenarios without module template vars
    if sk in ():
        _VISUAL_PROG_OVERRIDE[sk] = text

def _get_effective_template(ns: dict, slot: str) -> str:
    """Get the effective template: workspace file on disk takes priority,
    otherwise fall back to the factory template in ns.

    Reads disk atomically (save uses tmp+rename). If disk file is empty
    or read fails, falls back to ns factory template to ensure generate
    never produces a truncated output.
    """
    ws = _get_user_data_dir() / "editor_workspace"
    if ws.is_dir():
        for sdir in ws.iterdir():
            if not sdir.is_dir():
                continue
            tpl_file = sdir / f"{slot}.tpl"
            if tpl_file.exists():
                try:
                    tpl = tpl_file.read_text(encoding="utf-8-sig")
                    if tpl.strip():
                        return tpl
                except Exception:
                    pass  # read failed (half-written?) → fall back to ns
    # Fall back to factory template in ns
    return str(ns.get(slot, ""))


def _load_workspace_templates():
    """Load all saved templates from editor_workspace into runtime."""
    import re as _re_lwt
    ws = _get_user_data_dir() / "editor_workspace"
    if not ws.is_dir():
        return
    count = 0
    for info in _SCENARIO_LIST:
        disk_key = _DISK_ALIASES.get(info["key"], info["key"])
        safe_key = _re_lwt.sub(r"[^\w一-鿿]", "_", disk_key)
        sdir = ws / safe_key
        tpl_file = sdir / f"{info['tpl_slot']}.tpl"
        if tpl_file.exists():
            try:
                tpl = tpl_file.read_text(encoding="utf-8-sig")
                if tpl.strip():
                    _apply_template_to_runtime(info["key"], info, tpl)
                    count += 1
            except Exception:
                pass
    if count:
        print(f"Loaded {count} workspace templates into runtime")


def _snapshot_factory_defaults():
    """Snapshot factory init defaults for all scenarios before any saved values are applied.
    These are used by api_init_defaults_reset to return true factory values.
    Idempotent: only runs once (first call populates, subsequent calls are no-ops).
    """
    if _FACTORY_INIT_DEFAULTS:
        return
    _BOOL_DEFAULTS = {"DEFAULT_WAN_DHCP": False, "DEFAULT_LAN_DHCP": True,
                      "DEFAULT_GEN_RETURN_ROUTE": False, "DEFAULT_BYPASS": False}
    for info in _SCENARIO_LIST:
        ns = _load_module(info["source"])
        slot = info["tpl_slot"]
        keys = _get_init_keys(slot)
        values = {}
        for k in keys:
            v = ns.get(k)
            if v is not None:
                values[k] = str(v) if not isinstance(v, bool) else v
            elif k in _BOOL_DEFAULTS:
                values[k] = _BOOL_DEFAULTS[k]
        _FACTORY_INIT_DEFAULTS[info["key"]] = values


def _load_init_defaults():
    """Load saved init defaults from user_init_placeholders.json into module globals."""
    json_path = _get_user_data_dir() / "user_init_placeholders.json"
    if not json_path.exists():
        return
    try:
        all_values = json.loads(json_path.read_text(encoding="utf-8-sig"))
        if not isinstance(all_values, dict):
            return
    except Exception:
        return
    _LAN_KEYS = {"DEFAULT_LAN_CIDR", "DEFAULT_LAN_GW", "DEFAULT_LAN_IP"}
    count = 0
    for scenario_key, values in all_values.items():
        info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
        if not info or not isinstance(values, dict):
            continue
        ns = _load_module(info["source"])
        for k, v in values.items():
            if v is not None:
                sv = str(v) if not isinstance(v, bool) else v
                if isinstance(sv, str) and sv.strip().lower() == 'dhcp' and k in _LAN_KEYS:
                    continue
                ns[k] = sv
        count += 1
    if count:
        print(f"Loaded {count} init defaults from user_init_placeholders.json")


# ── Init Defaults API ────────────────────────────────────────────────────

@app.route("/api/init-defaults")
def api_init_defaults():
    """Return init defaults for all scenarios.
    Uses _FACTORY_INIT_DEFAULTS to avoid request-polluted globals."""
    return jsonify({"ok": True, "defaults": _FACTORY_INIT_DEFAULTS})


# ── Init Defaults API ────────────────────────────────────────────────────

@app.route("/api/init-defaults/<path:scenario_key>")
def api_init_defaults_get(scenario_key):
    """Return init default values for a specific scenario.

    Uses _FACTORY_INIT_DEFAULTS (snapshot taken at startup) to avoid returning
    request-polluted values from the live module globals (which _inject_network_to_module
    modifies on every generate request).
    """
    info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
    if not info:
        return jsonify({"ok": False, "error": _humanize_error("Scenario not found")}), 404
    slot = info["tpl_slot"]
    keys = _get_init_keys(slot)
    # Start from factory defaults (snapshot before any requests polluted the globals)
    values = dict(_FACTORY_INIT_DEFAULTS.get(scenario_key, {}))
    # Overlay user-saved values from JSON
    json_path = _get_user_data_dir() / "user_init_placeholders.json"
    try:
        if json_path.exists():
            saved = json.loads(json_path.read_text(encoding="utf-8-sig"))
            if isinstance(saved, dict):
                user = saved.get(scenario_key, {})
                if isinstance(user, dict):
                    for k, v in user.items():
                        if k in keys and v is not None:
                            values[k] = str(v) if not isinstance(v, bool) else v
    except Exception:
        pass
    return jsonify({"ok": True, "values": values})


@app.route("/api/init-defaults/save", methods=["POST"])
def api_init_defaults_save():
    denied = _require_login()
    if denied:
        return denied
    """Save init default values for a scenario to user_init_placeholders.json."""
    data = request.get_json(force=True)
    scenario_key = data.get("key", "")
    values = data.get("values", {})
    if not scenario_key:
        return jsonify({"ok": False, "error": _humanize_error("No scenario key")}), 400

    # Filter: LAN fields must never be 'dhcp'
    _LAN_KEYS = {"DEFAULT_LAN_CIDR", "DEFAULT_LAN_GW", "DEFAULT_LAN_IP"}
    values = {k: v for k, v in values.items()
              if not (isinstance(v, str) and v.strip().lower() == 'dhcp' and k in _LAN_KEYS)}

    # Write to user_init_placeholders.json
    json_path = _get_user_data_dir() / "user_init_placeholders.json"
    try:
        all_values = {}
        if json_path.exists():
            all_values = json.loads(json_path.read_text(encoding="utf-8-sig"))
        if not isinstance(all_values, dict):
            all_values = {}
        all_values[scenario_key] = values
        json_path.write_text(json.dumps(all_values, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    except Exception as e:
        return jsonify({"ok": False, "error": _humanize_error(e)}), 500

    # Apply to module globals
    info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
    if info:
        ns = _load_module(info["source"])
        for k, v in values.items():
            if v is not None:
                sv = str(v) if not isinstance(v, bool) else v
                if isinstance(sv, str) and sv.strip().lower() == 'dhcp' and k in _LAN_KEYS:
                    continue
                ns[k] = sv

    _touch_reload_stamp()
    return jsonify({"ok": True, "message": "Saved"})


@app.route("/api/init-defaults/reset", methods=["POST"])
def api_init_defaults_reset():
    denied = _require_login()
    if denied:
        return denied
    """Reset init defaults to factory values for a scenario."""
    data = request.get_json(force=True)
    scenario_key = data.get("key", "")
    info = next((s for s in _SCENARIO_LIST if s["key"] == scenario_key), None)
    if not info:
        return jsonify({"ok": False, "error": _humanize_error("Scenario not found")}), 404

    # Remove from JSON first
    json_path = _get_user_data_dir() / "user_init_placeholders.json"
    try:
        if json_path.exists():
            all_values = json.loads(json_path.read_text(encoding="utf-8-sig"))
            if isinstance(all_values, dict) and scenario_key in all_values:
                del all_values[scenario_key]
                json_path.write_text(json.dumps(all_values, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    except Exception:
        pass

    # Reload module from source to get true factory globals
    source = info["source"]
    # Restore factory defaults from snapshot (no del _EMBEDDED_NS — that would
    # break concurrent generate requests using this ns)
    ns = _load_module(source)
    factory = _FACTORY_INIT_DEFAULTS.get(source, {})
    for k, v in factory.items():
        ns[k] = v

    # Re-apply saved init defaults for OTHER scenarios sharing this module
    try:
        if json_path.exists():
            remaining = json.loads(json_path.read_text(encoding="utf-8-sig"))
            if isinstance(remaining, dict):
                for sk, sv in remaining.items():
                    si = next((s for s in _SCENARIO_LIST if s["key"] == sk), None)
                    if si and si["source"] == source and sk != scenario_key:
                        for mk, mv in sv.items():
                            if mv is not None:
                                ns[mk] = str(mv) if not isinstance(mv, bool) else mv
    except Exception:
        pass

    # Also re-apply workspace templates for this module
    try:
        import re as _re_reset
        ws = _get_user_data_dir() / "editor_workspace"
        if ws.is_dir():
            for si in _SCENARIO_LIST:
                if si["source"] != source:
                    continue
                dk = _DISK_ALIASES.get(si["key"], si["key"])
                sk_dir = _re_reset.sub(r"[^\w一-鿿]", "_", dk)
                tp = ws / sk_dir / f"{si['tpl_slot']}.tpl"
                if tp.exists():
                    try:
                        txt = tp.read_text(encoding="utf-8-sig").strip()
                        if txt:
                            ns[si["tpl_slot"]] = txt
                    except Exception:
                        pass
    except Exception:
        pass

    slot = info["tpl_slot"]
    keys = _get_init_keys(slot)
    values = {}
    _BOOL_KEYS = {"DEFAULT_WAN_DHCP", "DEFAULT_LAN_DHCP", "DEFAULT_GEN_RETURN_ROUTE", "DEFAULT_BYPASS"}
    for k in keys:
        v = ns.get(k)
        if v is not None:
            values[k] = str(v) if not isinstance(v, bool) else v
        elif k in _BOOL_KEYS:
            values[k] = False
            ns[k] = False
        else:
            values[k] = ""
            ns[k] = ""

    return jsonify({"ok": True, "values": values})


def _get_init_keys(slot):
    """Return the list of init keys for a given scenario slot."""
    if slot in ("TEMPLATE_EPOCH_HK", "TEMPLATE_EPOCH_US",
                 "TEMPLATE_EPOCH_HK_IPSEC", "TEMPLATE_EPOCH_US_IPSEC",
                 "TEMPLATE_EPOCH5_HK", "TEMPLATE_EPOCH5_US",
                 "TEMPLATE_EPOCH5_US_IPSEC"):
        return ["DEFAULT_WAN_ETH","DEFAULT_WAN_CIDR","DEFAULT_WAN_GW","DEFAULT_WAN_DHCP",
                "DEFAULT_LAN_ETH","DEFAULT_LAN_CIDR","DEFAULT_LAN_GW","DEFAULT_LAN_DHCP",
                "DEFAULT_INNER_NETS","DEFAULT_GEN_RETURN_ROUTE"]
    if slot == "TEMPLATE_ER_FLINK_VISUAL":
        return ["ER_FL_MAIN_NH_DEFAULT","ER_FL_BACKUP_NH_DEFAULT"]
    if slot == "TEMPLATE_EPOCH5_FLINK":
        return ["ER5_FL_MAIN_NH_DEFAULT","ER5_FL_BACKUP_NH_DEFAULT"]
    if slot == "TEMPLATE_ER_NEW_EXIT_VISUAL":
        return ["ER_NE_MAIN_PE_NH_DEFAULT","ER_NE_BK_PE_NH_DEFAULT",
                "ER_NE_MAIN_DUM_DEFAULT","ER_NE_BK_DUM_DEFAULT",
                "ER_NE_MAIN_NAT_RULE_DEFAULT","ER_NE_BK_NAT_RULE_DEFAULT",
                "ER_NE_NAT_SOURCE_CIDR_DEFAULT",
                "ER_NE_FNET_PROBE_DEFAULT","ER_NE_FNET_EXIT_TUNNEL_DEFAULT",
                "ER_NE_FNET_NAT_RULE_DEFAULT"]
    if slot == "TEMPLATE_EPOCH5_NEW_EXIT":
        return ["ER5_NE_MAIN_PE_NH_DEFAULT","ER5_NE_BK_PE_NH_DEFAULT",
                "ER5_NE_MAIN_DUM_DEFAULT","ER5_NE_BK_DUM_DEFAULT",
                "ER5_NE_MAIN_NAT_RULE_DEFAULT","ER5_NE_BK_NAT_RULE_DEFAULT",
                "ER5_NE_NAT_GROUP_DEFAULT","ER5_NE_NAT_SOURCE_CIDR_DEFAULT",
                "ER5_NE_FNET_PROBE_DEFAULT","ER5_NE_FNET_EXIT_TUNNEL_DEFAULT",
                "ER5_NE_FNET_NAT_RULE_DEFAULT"]
    if slot == "TEMPLATE_ER_DOMAIN_SPLIT_VISUAL":
        return ["ER_DS_DOMAINS_DEFAULT","ER_DS_ADDR_GROUP_DEFAULT",
                "ER_DS_RULE_NUM_DEFAULT","ER_DS_TABLE_NUM_DEFAULT",
                "ER_DS_SOURCE_CIDR_DEFAULT","ER_DS_ETH_DEFAULT",
                "ER_DS_DNS1_DEFAULT","ER_DS_DNS2_DEFAULT",
                "ER_DS_TABLE_NH_PRIMARY_DEFAULT","ER_DS_STATIC32_PRIMARY_NH_DEFAULT",
                "ER_DS_TRACK_NAME_DEFAULT","ER_DS_STATIC32_BACKUP_NH_DEFAULT",
                "ER_DS_FNET_PROBE_DEFAULT","ER_DS_FNET_NAT_RULE_DEFAULT",
                "ER_DS_EXIT_TUNNEL_DEFAULT","ER_DS_EXIT_SNAT_IP_DEFAULT"]
    if slot == "TEMPLATE_EPOCH5_DOMAIN_SPLIT":
        return ["ER5_DS_DOMAINS_DEFAULT","ER5_DS_ADDR_GROUP_DEFAULT",
                "ER5_DS_RULE_NUM_DEFAULT","ER5_DS_TABLE_NUM_DEFAULT",
                "ER5_DS_SOURCE_CIDR_DEFAULT","ER5_DS_ETH_DEFAULT",
                "ER5_DS_DNS1_DEFAULT","ER5_DS_DNS2_DEFAULT",
                "ER5_DS_TABLE_NH_PRIMARY_DEFAULT","ER5_DS_STATIC32_PRIMARY_NH_DEFAULT",
                "ER5_DS_TRACK_NAME_DEFAULT","ER5_DS_STATIC32_BACKUP_NH_DEFAULT",
                "ER5_DS_FNET_PROBE_DEFAULT","ER5_DS_FNET_NAT_RULE_DEFAULT",
                "ER5_DS_EXIT_TUNNEL_DEFAULT","ER5_DS_EXIT_SNAT_IP_DEFAULT"]
    if slot == "TEMPLATE_USG_HK":
        return ["HK_DEFAULT_DNS1","HK_DEFAULT_DNS2","DEFAULT_WAN_ETH","DEFAULT_WAN_IP",
                "DEFAULT_WAN_GW","DEFAULT_WAN_DHCP","DEFAULT_LAN_ETH","DEFAULT_LAN_IP",
                "DEFAULT_LAN_GW","DEFAULT_LAN_DHCP","DEFAULT_INNER_NETS","DEFAULT_GEN_RETURN_ROUTE",
                "DEFAULT_BGP_VERSION"]
    if slot == "TEMPLATE_USG_NONHK":
        return ["DEFAULT_DNS1","DEFAULT_DNS2","DEFAULT_WAN_ETH","DEFAULT_WAN_IP",
                "DEFAULT_WAN_GW","DEFAULT_WAN_DHCP","DEFAULT_LAN_ETH","DEFAULT_LAN_IP",
                "DEFAULT_LAN_GW","DEFAULT_LAN_DHCP","DEFAULT_INNER_NETS","DEFAULT_GEN_RETURN_ROUTE",
                "DEFAULT_BGP_VERSION"]
    if slot == "TEMPLATE_USG_FLINK_VISUAL":
        return ["USG_FL_MAIN_TUN_DEFAULT","USG_FL_BK_TUN_DEFAULT"]
    if slot == "TEMPLATE_USG_NEW_EXIT_VISUAL":
        return ["USG_NE_MAIN_TUN_DEFAULT","USG_NE_BK_TUN_DEFAULT",
                "USG_NE_MAIN_LOOP_START_DEFAULT","USG_NE_BK_LOOP_START_DEFAULT",
                "USG_NE_MAIN_NQA_DEFAULT","USG_NE_BK_NQA_DEFAULT"]
    if slot in ("TEMPLATE_MPLS_DOMESTIC", "TEMPLATE_MPLS_OVERSEAS", "TEMPLATE_MPLS_IPSEC"):
        return ["DEFAULT_WAN_ETH","DEFAULT_WAN_CIDR","DEFAULT_WAN_GW",
                "DEFAULT_LAN_ETH","DEFAULT_LAN_CIDR","DEFAULT_LAN_GW",
                "DEFAULT_WAN_DHCP","DEFAULT_LAN_DHCP","DEFAULT_INNER_NETS","DEFAULT_GEN_RETURN_ROUTE"]
    if slot == "TEMPLATE_AR_TRADITIONAL":
        return ["DEFAULT_WAN_ETH","DEFAULT_WAN_IP","DEFAULT_WAN_GW",
                "DEFAULT_LAN_ETH","DEFAULT_LAN_IP","DEFAULT_LAN_GW",
                "DEFAULT_INNER_NETS","DEFAULT_GEN_RETURN_ROUTE","DEFAULT_BYPASS"]
    if "TEMPLATE_AR_" in slot:  # AR SD-WAN templates (OPS/Factory)
        return ["DEFAULT_WAN1_PORT","DEFAULT_WAN1_IP","DEFAULT_WAN1_GW",
                "DEFAULT_WAN2_PORT","DEFAULT_WAN2_IP","DEFAULT_WAN2_GW",
                "DEFAULT_ZIHUAN_PORT","DEFAULT_IPSEC_PORT",
                "DJ_WAN1_PORT","DJ_WAN1_IP","DJ_WAN1_GW",
                "DJ_WAN2_PORT","DJ_WAN2_IP","DJ_WAN2_GW",
                "DJ_ZIHUAN1_PORT","DJ_ZIHUAN2_PORT",
                "DJ_IPSEC1_PORT","DJ_IPSEC2_PORT"]
    return []


# ── Run ─────────────────────────────────────────────────────────────────

def _preload_all_modules():
    """Preload all embedded modules at startup so first request doesn't hang."""
    print("Preloading modules...")
    for fn in [_get_er, _get_er5, _get_usg, _get_mpls, _get_ar]:
        try:
            fn()
            print(f"  {fn.__name__} OK")
        except Exception as e:
            print(f"  {fn.__name__} FAIL: {e}")
    print("Preload done.")


# ── 多 worker 状态同步（mtime 轮询重载）──────────────────────────────────
# 多 worker 进程隔离下，worker A 保存模板/默认值后写磁盘，其他 worker 内存 ns
# 不会自动同步。用文件 mtime 轮询：每个 generate 请求开始前检查 mtime 是否变化，
# 变化则重载 init defaults + workspace templates 到当前 worker 的 _EMBEDDED_NS。
#
# sentinel 文件 data/.reload_stamp 在每次保存后被 touch，作为统一的变更信号。

_RELOAD_STAMP = _get_user_data_dir() / ".reload_stamp"
_runtime_mtime: float = 0.0


def _stamp_mtime() -> float:
    """Return current sentinel file mtime (0 if absent)."""
    try:
        return _RELOAD_STAMP.stat().st_mtime
    except OSError:
        return 0.0


def _touch_reload_stamp() -> None:
    """Touch sentinel file to signal other workers to reload. Called after saves.

    Does NOT update _runtime_mtime: the current worker already applied the
    change (save/reset updates ns directly). Other workers detect the mtime
    change via check_and_reload_runtime on their next request.
    """
    try:
        _RELOAD_STAMP.parent.mkdir(parents=True, exist_ok=True)
        _RELOAD_STAMP.touch()
    except Exception:
        pass


def check_and_reload_runtime() -> None:
    """Check if runtime state changed (other worker saved templates/defaults).

    Called at the start of each generate request. If the sentinel file's mtime
    advanced since we last saw it, reload workspace templates into this worker's
    _EMBEDDED_NS. Only reloads templates (not init defaults) to avoid overwriting
    form-injected network values. O(1) when nothing changed (one os.stat).
    """
    global _runtime_mtime
    cur = _stamp_mtime()
    if cur == _runtime_mtime:
        return
    # mtime changed -> reload templates only (NOT init defaults)
    try:
        _reload_workspace_templates_safe()
        _runtime_mtime = cur
    except Exception:
        pass


def init_worker() -> None:
    """Initialize a worker process: preload modules + snapshot factory defaults.
    Called by gunicorn post_fork (once per worker) and also safe to call in
    __main__ single-process mode (bare metal dev).

    Does NOT load per-user init defaults or workspace templates — those are
    user-specific and read on-demand via _get_effective_template /
    _get_user_data_dir. Module globals start as factory defaults.
    """
    _preload_all_modules()
    _snapshot_factory_defaults()
    # Record current sentinel mtime so we don't immediately re-reload.
    global _runtime_mtime
    _runtime_mtime = _stamp_mtime()


if __name__ == "__main__":
    import logging
    import threading
    import webbrowser

    logging.basicConfig(level=logging.INFO)

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5003
    print(f"all_in_one web · http://localhost:{port}")

    # 单进程裸机模式：自行初始化（gunicorn 模式下由 post_fork 调 init_worker）
    init_worker()

    # 1.2 秒后自动打开浏览器（仅本机）；TEST_MODE / NO_BROWSER / BROWSER=echo 下跳过。
    if (
        os.environ.get("TEST_MODE") != "1"
        and os.environ.get("NO_BROWSER") != "1"
        and os.environ.get("BROWSER") not in ("echo", "", "none")
    ):
        threading.Timer(
            1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")
        ).start()

    # host="0.0.0.0" 允许局域网内其他设备访问
    # threaded=True: tkinter 已被 stub 替代，无线程安全约束，可多线程并发。
    # （gunicorn 模式下不走 app.run）
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
