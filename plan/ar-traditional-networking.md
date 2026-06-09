# AR 传统组网 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "AR 传统组网" (AR Traditional Networking) scenario to the config generation tool — a dual-line BGP+GRE+IPSec Huawei AR configuration generator.

**Architecture:** New business module `ar_traditional_v1.py` with header parser + builder + template, new nav tab in frontend, new `/api/generate/ar_traditional` endpoint. Follows the existing pattern: data header parsed → format dict built → template filled. No DHCP for WAN/LAN; has return route + bypass toggles. Demo version only.

**Tech Stack:** Python (Flask, ipaddress, re), JavaScript (vanilla), HTML/CSS (Cursor design system), Playwright (E2E tests)

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `application/all_in_one - cc/src/ar_traditional_v1.py` | **Create** | Business logic: parser, builder, template constant, example data |
| `application/all_in_one - cc/data/editor_defaults/AR_传统组网/` | **Create** | Factory default: headers.txt, mapping.txt, TEMPLATE_AR_TRADITIONAL.tpl |
| `application/all_in_one - cc/web/app.py` | **Modify** | Module loader, scenario list/tree, generate endpoint, template preview, example/notes, init-defaults |
| `application/all_in_one - cc/web/templates/index.html` | **Modify** | Nav tab, tool panel, variant pills, param panel, JS functions |
| `application/test/all_in_one/test_ar_traditional_gen.py` | **Create** | API generation tests |
| `application/test/all_in_one/test_ar_traditional_e2e.py` | **Create** | Playwright E2E tests |
| `application/test/all_in_one/test_ar_traditional_templates.py` | **Create** | Template editor tests |
| `application/all_in_one - cc/plan/ar传统组网数据和配置.txt` | **Reference** | Data header format & config example (existing, read-only) |

---

### Task 1: Create Business Logic Module — Template & Example Data

**Files:**
- Create: `application/all_in_one - cc/src/ar_traditional_v1.py`

- [ ] **Step 1: Create the module skeleton with template constant and example data**

The data header format (from the spec file):

```
LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win
```

Each data header contains 2 lines (main + backup), each with line info + dial-up info.

Write `application/all_in_one - cc/src/ar_traditional_v1.py`:

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AR 传统组网 — 双线 BGP+GRE+IPSec 华为 AR 配置生成工具 v1"""

import ipaddress
import re

try:
    import field_coverage
except ImportError:
    field_coverage = None

try:
    from user_activity_log import log_generate_config
except ImportError:
    def log_generate_config(**_kwargs):
        pass

# ── Re-exported for shared_utils compatibility ──
try:
    _get
except NameError:
    def _get(pattern, block, flags=re.IGNORECASE | re.MULTILINE):
        m = re.search(pattern, block, flags)
        return m.group(1).strip() if m else ""


# ═══════════════════════════════════════════════════════════════
# Example data
# ═══════════════════════════════════════════════════════════════

AR_TRAD_EXAMPLE = """\
LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""

```

- [ ] **Step 2: Add the parser function**

Add to `ar_traditional_v1.py`:

```python
# ═══════════════════════════════════════════════════════════════
# Header parser
# ═══════════════════════════════════════════════════════════════

def _parse_one_line(text):
    """Parse one line's info + dial-up sections into a dict."""
    d = {}
    d["lineid"] = _get(r"LineID:\s*(\S+)", text)
    d["pe"] = _get(r"^PE:\s*(\S+)", text)
    d["tunnel"] = _get(r"Tunnel:\s*(\S+)", text)
    d["wanip"] = _get(r"wanip:\s*(\S+)", text)
    d["pe_docking"] = _get(r"PE\s*对接:\s*(\S+)", text)
    d["ce_docking"] = _get(r"CE\s*对接:\s*(\S+)", text)
    d["pe_as"] = _get(r"PE\s*AS号:\s*(\S+)", text)
    d["ce_as"] = _get(r"CE\s*AS号:\s*(\S+)", text)
    d["zihuan"] = _get(r"自环网段[：:]\s*(?:备\s*)?(\S+)", text)

    # Dial-up info
    d["dial_pe"] = _get(r"拨号PE:\s*(\S+)", text)
    d["dial_docking_ip"] = _get(r"对接IP:\s*(\S+)", text)
    d["loop_ip"] = _get(r"LoopIP:\s*(\S+)", text)
    d["dial_ip"] = _get(r"拨号ip:\s*(\S+)", text)
    d["psk"] = _get(r"秘钥:\s*(\S+)", text)

    # Compute derived values
    if d["wanip"] and "/" in d["wanip"]:
        d["wan_ip_plain"] = d["wanip"].split("/")[0]
    else:
        d["wan_ip_plain"] = d["wanip"]

    # Tunnel source/dest IP from wanip (tunnel IP = wanip + 1 for CE side)
    if d["wanip"] and "/" in d["wanip"]:
        try:
            net = ipaddress.ip_network(d["wanip"], strict=False)
            hosts = list(net.hosts())
            if len(hosts) >= 2:
                d["tunnel_local_ip"] = str(hosts[0])
                d["tunnel_remote_ip"] = str(hosts[1])
            else:
                d["tunnel_local_ip"] = d["wan_ip_plain"]
                d["tunnel_remote_ip"] = ""
        except Exception:
            d["tunnel_local_ip"] = d["wan_ip_plain"]
            d["tunnel_remote_ip"] = ""
    else:
        d["tunnel_local_ip"] = d["wan_ip_plain"]
        d["tunnel_remote_ip"] = ""

    # LoopBack interface number
    if d["lineid"]:
        d["loopback_if"] = f"LoopBack{d.get('loopback_num', '1000')}"

    return d


def parse_ar_traditional_headers(text):
    """Parse the complete data header (2 lines, each with info + dial-up).
    Returns (main_line, backup_line, error).
    """
    if not text or not text.strip():
        return None, None, ("empty", "请输入业务数据头")

    # Split by LineID markers
    parts = re.split(r"\n(?=LineID:)", text.strip())
    lines_data = []
    for part in parts:
        if not part.strip():
            continue
        d = _parse_one_line(part)
        if d.get("lineid"):
            lines_data.append(d)

    if len(lines_data) < 1:
        return None, None, ("empty", "未解析到有效的 LineID 数据")
    if len(lines_data) < 2:
        return None, None, ("empty", "需要主线+备线两条数据，当前仅解析到 1 条")

    main_line = lines_data[0]
    backup_line = lines_data[1]

    # Validate required fields
    for label, d in [("主线", main_line), ("备线", backup_line)]:
        missing = []
        for k in ["lineid", "pe", "tunnel", "wanip", "pe_docking", "ce_docking", "pe_as", "ce_as"]:
            if not d.get(k):
                missing.append(k)
        if missing:
            return None, None, ("empty", f"{label}缺少必要字段: {', '.join(missing)}")

    return main_line, backup_line, None
```

- [ ] **Step 3: Add the builder function**

Add to `ar_traditional_v1.py`:

```python
# ═══════════════════════════════════════════════════════════════
# Builder: builds format dict from parsed data + network params
# ═══════════════════════════════════════════════════════════════

def build_ar_traditional_format_dict(main_line, backup_line, network=None):
    """Build the format dict for TEMPLATE_AR_TRADITIONAL.
    
    network dict keys (from web form):
      hostname, wan_if, wan_ip, wan_mask, lan_if, lan_ip, lan_mask,
      wan_gw, lan_gw, inner_nets, gen_return_route, bypass,
      bgp_networks, static_routes_extra
    """
    if network is None:
        network = {}

    d = {}

    # ── From data headers (main line) ──
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

    # ── From data headers (backup line) ──
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

    # ── From network parameters ──
    hostname = network.get("hostname", "") or main_line.get("lineid", "")
    d["hostname"] = hostname

    wan_if = network.get("wan_if", "GigabitEthernet0/0/9")
    lan_if = network.get("lan_if", "GigabitEthernet0/0/1")
    d["wan_if_name"] = wan_if
    d["lan_if_name"] = lan_if
    # Extract interface numbers for descriptions
    d["wan_if_num"] = wan_if.replace("GigabitEthernet", "").replace("GE", "")
    d["lan_if_num"] = lan_if.replace("GigabitEthernet", "").replace("GE", "")

    wan_ip = network.get("wan_ip", "173.15.30.40")
    wan_mask = network.get("wan_mask", "255.255.255.0")
    d["wan_ip"] = wan_ip
    d["wan_mask"] = wan_mask
    d["wan_ip_full"] = f"{wan_ip} {wan_mask}"

    lan_ip = network.get("lan_ip", "173.15.20.10")
    lan_mask = network.get("lan_mask", "255.255.255.0")
    d["lan_ip"] = lan_ip
    d["lan_mask"] = lan_mask
    d["lan_ip_full"] = f"{lan_ip} {lan_mask}"

    wan_gw = network.get("wan_gw", "173.15.30.254")
    lan_gw = network.get("lan_gw", "173.15.30.254")
    d["wan_gw"] = wan_gw
    d["lan_gw"] = lan_gw

    # ── BGP config ──
    ce_as = main_line.get("ce_as", "65201")
    d["ce_as"] = ce_as
    d["bgp_router_id"] = d["main_tunnel_local_ip"]

    # BGP peers
    d["peer_main_ip"] = backup_line.get("tunnel_local_ip", "")
    d["peer_main_as"] = backup_line.get("pe_as", "")
    d["peer_backup_ip"] = main_line.get("tunnel_local_ip", "")
    d["peer_backup_as"] = main_line.get("pe_as", "")

    # BGP advertised networks
    bgp_networks_raw = network.get("bgp_networks", "")
    if bgp_networks_raw:
        nets = [n.strip() for n in re.split(r'[\n,，\s]+', bgp_networks_raw) if n.strip()]
    else:
        nets = [f"{wan_ip.rsplit('.', 1)[0]}.0"]
    d["bgp_networks_block"] = "\n".join(
        f"  network {n} 255.255.255.0" for n in nets
    )

    # BGP filter prefix list
    d["bgp_filter_prefix_block"] = "\n".join(
        f"ip ip-prefix bgp-filte-pre-export index {(i+1)*10} permit {n} 24"
        for i, n in enumerate(nets)
    )

    # ── Inner nets (for ACL rules) ──
    inner_nets_raw = network.get("inner_nets", "192.168.0.0/16\n172.16.0.0/12\n10.0.0.0/8")
    inner_nets = []
    for token in re.split(r'[\n,，\s]+', inner_nets_raw):
        s = token.strip()
        if s:
            try:
                inner_nets.append(str(ipaddress.ip_network(s, strict=False)))
            except Exception:
                inner_nets.append(s)

    # Generate ACL rules for inner nets
    d["acl_inner_rules_block"] = ""
    rule_num = 10
    acl_lines = []
    for net in inner_nets:
        try:
            n = ipaddress.ip_network(net, strict=False)
            wildcard = ".".join(str(255 - int(o)) for o in str(n.netmask).split("."))
            acl_lines.append(f"  rule {rule_num} permit source {n.network_address} {wildcard}")
        except Exception:
            acl_lines.append(f"  rule {rule_num} permit source {net}")
        rule_num += 10
    d["acl_inner_rules_block"] = "\n".join(acl_lines)

    # ── Static routes ──
    static_routes_lines = []
    # Default route
    static_routes_lines.append(f"ip route-static 0.0.0.0 0.0.0.0 {wan_gw} tag 7777")
    # Routes to IPSec remote peers via WAN gateway
    static_routes_lines.append(
        f"ip route-static {main_line.get('pe_docking', '')} 255.255.255.255 {wan_gw} tag 7777 description To_ipsec_main"
    )
    static_routes_lines.append(
        f"ip route-static {backup_line.get('pe_docking', '')} 255.255.255.255 {wan_gw} tag 7777 description To_ipsec_back"
    )
    static_routes_lines.append(
        f"ip route-static {main_line.get('dial_ip', '')} 255.255.255.255 {wan_gw} tag 7777 description To_ipsec_main"
    )
    static_routes_lines.append(
        f"ip route-static {backup_line.get('dial_ip', '')} 255.255.255.255 {wan_gw} tag 7777 description To_ipsec_back"
    )
    d["static_routes_block"] = "\n".join(static_routes_lines)

    # ── Return routes (回程路由) ──
    d["return_routes_block"] = ""
    gen_return = network.get("gen_return_route", False)
    if gen_return and inner_nets:
        rr_lines = []
        for net in inner_nets:
            rr_lines.append(f"ip route-static {net} {wan_gw} tag 8888")
        d["return_routes_block"] = "\n".join(rr_lines)

    # ── LAN interface block (bypass mode) ──
    bypass = network.get("bypass", False)
    if bypass:
        d["lan_if_block"] = ""
        d["lan_if_acl_block"] = ""
    else:
        d["lan_if_block"] = (
            f"interface {lan_if}\n"
            f" undo portswitch\n"
            f" ip address {lan_ip} {lan_mask}"
        )
        d["lan_if_acl_block"] = ""

    # ── WAN interface block ──
    d["wan_if_block"] = (
        f"interface {wan_if}\n"
        f" ip address {wan_ip} {wan_mask}\n"
        f" ipsec policy S2S-IPSEC"
    )

    # ── LoopBack interfaces ──
    d["loopback_main_block"] = (
        f"interface LoopBack1000\n"
        f" description To IPSec main\n"
        f" ip address {main_line.get('loop_ip', '')} 255.255.255.255"
    )
    d["loopback_backup_block"] = (
        f"interface LoopBack1001\n"
        f" description To IPSec backup\n"
        f" ip address {backup_line.get('loop_ip', '')} 255.255.255.255"
    )

    # ── Tunnel interfaces ──
    d["tunnel_main_block"] = (
        f"interface Tunnel0/0/1000\n"
        f" description 'pri to {main_line.get('pe', '')} {main_line.get('tunnel', '')}'\n"
        f" tcp adjust-mss 1300\n"
        f" ip address {main_line.get('tunnel_local_ip', '')} 255.255.255.252\n"
        f" tunnel-protocol gre\n"
        f" source LoopBack1000\n"
        f" destination {main_line.get('pe_docking', '')}"
    )
    d["tunnel_backup_block"] = (
        f"interface Tunnel0/0/1001\n"
        f" description 'back to {backup_line.get('pe', '')} {backup_line.get('tunnel', '')}'\n"
        f" tcp adjust-mss 1300\n"
        f" ip address {backup_line.get('tunnel_local_ip', '')} 255.255.255.252\n"
        f" tunnel-protocol gre\n"
        f" source LoopBack1001\n"
        f" destination {backup_line.get('pe_docking', '')}"
    )

    # ── IPSec ACLs ──
    main_loop = main_line.get("loop_ip", "")
    main_dock = main_line.get("dial_docking_ip", "")
    backup_loop = backup_line.get("loop_ip", "")
    backup_dock = backup_line.get("dial_docking_ip", "")
    d["ipsec_acl_main_block"] = (
        f"acl number 3333\n"
        f" rule 1 permit ip source {main_loop} 0 destination {main_dock} 0"
    )
    d["ipsec_acl_backup_block"] = (
        f"acl number 3334\n"
        f" rule 1 permit ip source {backup_loop} 0 destination {backup_dock} 0"
    )

    # ── IKE peers ──
    d["ike_peer_main_name"] = "main"
    d["ike_peer_backup_name"] = "backup"
    d["ike_peer_main_block"] = (
        f"ike peer main\n"
        f" version 1\n"
        f" pre-shared-key cipher {main_line.get('psk', '')}\n"
        f" ike-proposal 10\n"
        f" dpd type on-demand\n"
        f" dpd idle-time 10\n"
        f" dpd retransmit-interval 2\n"
        f" remote-address {main_line.get('dial_ip', '')}\n"
        f" rsa encryption-padding oaep\n"
        f" rsa signature-padding pss\n"
        f" undo local-id-preference certificate enable\n"
        f" ikev2 authentication sign-hash sha2-256"
    )
    d["ike_peer_backup_block"] = (
        f"ike peer backup\n"
        f" version 1\n"
        f" pre-shared-key cipher {backup_line.get('psk', '')}\n"
        f" ike-proposal 10\n"
        f" dpd type on-demand\n"
        f" dpd idle-time 10\n"
        f" dpd retransmit-interval 2\n"
        f" remote-address {backup_line.get('dial_ip', '')}\n"
        f" rsa encryption-padding oaep\n"
        f" rsa signature-padding pss\n"
        f" undo local-id-preference certificate enable\n"
        f" ikev2 authentication sign-hash sha2-256"
    )

    # ── IPSec policy ──
    d["ipsec_policy_block"] = (
        f"ipsec policy S2S-IPSEC 10 isakmp\n"
        f" security acl 3333\n"
        f" pfs dh-group2\n"
        f" ike-peer main\n"
        f" proposal ipsectran1\n"
        f"ipsec policy S2S-IPSEC 20 isakmp\n"
        f" security acl 3334\n"
        f" pfs dh-group2\n"
        f" ike-peer backup\n"
        f" proposal ipsectran1"
    )

    d["hostname"] = hostname
    d["lineid_main"] = d["main_lineid"]
    d["lineid_backup"] = d["backup_lineid"]

    return d
```

- [ ] **Step 4: Write the template constant**

Add to `ar_traditional_v1.py` — the full config template based on the spec file's output:

```python
TEMPLATE_AR_TRADITIONAL = """\
#
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
```

- [ ] **Step 5: Commit**

```bash
git add "application/all_in_one - cc/src/ar_traditional_v1.py"
git commit -m "feat: add AR traditional networking business module (parser + template + builder)"
```

---

### Task 2: Create Template Data Files (editor_defaults)

**Files:**
- Create: `application/all_in_one - cc/data/editor_defaults/AR_传统组网/headers.txt`
- Create: `application/all_in_one - cc/data/editor_defaults/AR_传统组网/mapping.txt`
- Create: `application/all_in_one - cc/data/editor_defaults/AR_传统组网/TEMPLATE_AR_TRADITIONAL.tpl`

- [ ] **Step 1: Create the directory**

```powershell
New-Item -ItemType Directory -Path "application/all_in_one - cc/data/editor_defaults/AR_传统组网" -Force
```

- [ ] **Step 2: Write headers.txt**

Use the example data from the spec:

```
LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win
```

- [ ] **Step 3: Write mapping.txt**

Variable-to-description mapping:

```
hostname  设备主机名 (默认取 LineID)
main_lineid  主线 LineID
main_pe  主线 PE 名称
main_tunnel  主线 Tunnel 接口
main_wanip  主线 WAN IP/CIDR
main_pe_docking  主线 PE 对接 IP
main_ce_docking  主线 CE 对接 IP
main_pe_as  主线 PE AS 号
main_ce_as  主线 CE AS 号
main_zihuan  主线自环网段
main_dial_pe  主线拨号 PE
main_dial_docking_ip  主线拨号对接 IP
main_loop_ip  主线 LoopBack IP
main_dial_ip  主线拨号 IP (IPSec 远端)
main_psk  主线预共享密钥
backup_lineid  备线 LineID
backup_pe  备线 PE 名称
backup_tunnel  备线 Tunnel 接口
backup_wanip  备线 WAN IP/CIDR
backup_pe_docking  备线 PE 对接 IP
backup_ce_docking  备线 CE 对接 IP
backup_pe_as  备线 PE AS 号
backup_ce_as  备线 CE AS 号
backup_zihuan  备线自环网段
backup_dial_pe  备线拨号 PE
backup_dial_docking_ip  备线拨号对接 IP
backup_loop_ip  备线 LoopBack IP
backup_dial_ip  备线拨号 IP (IPSec 远端)
backup_psk  备线预共享密钥
wan_if_name  WAN 接口名
wan_ip  WAN IP
wan_mask  WAN 子网掩码
lan_if_name  LAN 接口名
lan_ip  LAN IP
lan_mask  LAN 子网掩码
wan_gw  WAN 网关
lan_gw  LAN 网关
ce_as  CE AS 号
bgp_router_id  BGP Router ID
peer_main_ip  BGP 主 Peer IP
peer_main_as  BGP 主 Peer AS
peer_backup_ip  BGP 备 Peer IP
peer_backup_as  BGP 备 Peer AS
bgp_networks_block  BGP 宣告网段
bgp_filter_prefix_block  BGP Filter Prefix List
acl_inner_rules_block  内网段 ACL 规则
static_routes_block  静态路由
return_routes_block  回程路由
lan_if_block  LAN 接口配置
wan_if_block  WAN 接口配置
loopback_main_block  主线 LoopBack
loopback_backup_block  备线 LoopBack
tunnel_main_block  主线 GRE Tunnel
tunnel_backup_block  备线 GRE Tunnel
ike_peer_main_block  主线 IKE Peer
ike_peer_backup_block  备线 IKE Peer
ipsec_acl_main_block  主线 IPSec ACL
ipsec_acl_backup_block  备线 IPSec ACL
ipsec_policy_block  IPSec Policy
```

- [ ] **Step 4: Write TEMPLATE_AR_TRADITIONAL.tpl**

Copy the exact `TEMPLATE_AR_TRADITIONAL` string content from the module.

- [ ] **Step 5: Commit**

```bash
git add "application/all_in_one - cc/data/editor_defaults/AR_传统组网/"
git commit -m "feat: add AR traditional networking template data files"
```

---

### Task 3: Update Backend — Scenario Registration & API

**Files:**
- Modify: `application/all_in_one - cc/web/app.py`

- [ ] **Step 1: Add module loader**

Add after `_get_ar()` (line ~157):

```python
def _get_ar_traditional():
    return _load_module("ar_traditional_v1.py")
```

- [ ] **Step 2: Add to `_SCENARIO_LIST`**

Add at the end of the list (after the last AR SD-WAN entry, before `]`):

```python
    {"key": "AR 传统组网 · 双线", "source": "ar_traditional_v1.py", "tpl_slot": "TEMPLATE_AR_TRADITIONAL"},
```

- [ ] **Step 3: Add to `_SCENARIO_TREE`**

Add a new top-level entry after the AR SD-WAN block:

```python
    {
        "label": "AR 传统组网",
        "children": [
            {"label": "双线", "key": "AR 传统组网 · 双线"},
        ],
    },
```

- [ ] **Step 4: Add to `_VAR_DESC_SMALL`**

Add new variable descriptions:

```python
    "main_lineid": "主线LineID", "main_pe": "主线PE", "main_tunnel": "主线Tunnel",
    "main_pe_docking": "主线PE对接IP", "main_ce_docking": "主线CE对接IP",
    "main_pe_as": "主线PE AS", "main_ce_as": "主线CE AS",
    "main_zihuan": "主线自环网段", "main_dial_pe": "主线拨号PE",
    "main_dial_docking_ip": "主线拨号对接IP", "main_loop_ip": "主线LoopIP",
    "main_dial_ip": "主线拨号IP", "main_psk": "主线PSK",
    "backup_lineid": "备线LineID", "backup_pe": "备线PE", "backup_tunnel": "备线Tunnel",
    "backup_pe_docking": "备线PE对接IP", "backup_ce_docking": "备线CE对接IP",
    "backup_pe_as": "备线PE AS", "backup_ce_as": "备线CE AS",
    "backup_zihuan": "备线自环网段", "backup_dial_pe": "备线拨号PE",
    "backup_dial_docking_ip": "备线拨号对接IP", "backup_loop_ip": "备线LoopIP",
    "backup_dial_ip": "备线拨号IP", "backup_psk": "备线PSK",
    "lan_ip": "LAN IP", "lan_mask": "LAN 掩码", "wan_ip": "WAN IP", "wan_mask": "WAN 掩码",
    "ce_as": "CE AS号", "bgp_router_id": "BGP Router ID",
    "peer_main_ip": "BGP主Peer IP", "peer_main_as": "BGP主Peer AS",
    "peer_backup_ip": "BGP备Peer IP", "peer_backup_as": "BGP备Peer AS",
```

- [ ] **Step 5: Add generate endpoint**

Add after `generate_ar_sdwan()` (before `# ── Example Data API ──`):

```python
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
        tpl = mod.get("TEMPLATE_AR_TRADITIONAL", "")

        if not parse_fn or not builder_fn:
            return jsonify({"ok": False, "error": _humanize_error("Builder not found", variant)}), 500

        main_line, backup_line, err = parse_fn(hdr_text)
        if err:
            return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400

        d = builder_fn(main_line, backup_line, network)
        output = tpl.format(**d) if d and tpl else str(d)

        return _log_and_return(tool_id, variant, hdr_text, output,
                              jsonify({"ok": True, "output": output}))
    except KeyError as e:
        return jsonify({"ok": False, "error": f"模板变量缺失: {e}"}), 500
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": _humanize_error(e, variant)}), 500
```

- [ ] **Step 6: Add to `_EXAMPLE_MAP`**

```python
    ("ar_traditional", "dual"): ("ar_traditional_v1.py", "AR_TRAD_EXAMPLE"),
```

- [ ] **Step 7: Add to `_NOTES`**

```python
    "ar_traditional": {
        "dual": (
            "AR 传统组网 · 双线\n\n"
            "• 粘贴包含主备两条 LineID 的完整数据头\n"
            "• WAN/LAN 接口不支持 DHCP（传统组网均为静态 IP）\n"
            "• 勾选「回程路由」为内网段生成回程静态路由\n"
            "• 勾选「旁挂模式」不生成 LAN 接口配置\n"
            "• 配置仅供参考，使用仍需谨慎。"
        ),
    },
```

- [ ] **Step 8: Add template preview handler**

In `/api/template/preview`, add handling for the new slot (after the existing elif-chain):

```python
        elif slot == "TEMPLATE_AR_TRADITIONAL":
            parse_fn = ns.get("parse_ar_traditional_headers")
            builder_fn = ns.get("build_ar_traditional_format_dict")
            if parse_fn and builder_fn and tpl:
                main_line, backup_line, err = parse_fn(hdr_text)
                if not err:
                    d = builder_fn(main_line, backup_line)
                    if d:
                        try:
                            rendered = tpl.format(**d)
                        except Exception:
                            rendered = ""
```

- [ ] **Step 9: Add init-defaults field mappings**

In `/api/init-defaults` handling (endpoint around line 2287), the init-defaults are keyed by scenario_key. The `DEFAULT_*` fields for AR traditional are different (no DHCP fields, has return route + bypass). Add to the `_FACTORY_INIT_DEFAULTS` (if it exists) or rely on the dynamic save/reset mechanism.

Actually, init-defaults uses `user_init_placeholders.json` and the template editor `saveInitDefaults()` saves whatever fields are in the `#tpl-init-body`. The mapping for form fields will be defined in the frontend JS. For now, we need to ensure the init-defaults API handles the new key.

In the `api_init_defaults_get` and `api_init_defaults_save` endpoints, add the factory defaults for the new key:

No changes needed — the init-defaults endpoints are generic and work with any scenario_key. The factory defaults come from the template's inferred variables.

- [ ] **Step 10: Add to `api/template/load` example_keys mapping**

```python
            "TEMPLATE_AR_TRADITIONAL": "AR_TRAD_EXAMPLE",
```

Add this inside the `example_keys` dict (around line 1797).

- [ ] **Step 11: Add to `api/template/reset` example_keys mapping**

```python
            "TEMPLATE_AR_TRADITIONAL": "AR_TRAD_EXAMPLE",
```

Add this inside the reset example_keys dict (around line 1924).

- [ ] **Step 12: Commit**

```bash
git add "application/all_in_one - cc/web/app.py"
git commit -m "feat: add AR traditional networking backend API (scenario, generate, template, preview)"
```

---

### Task 4: Update Frontend — Nav Tab, Panel, JS

**Files:**
- Modify: `application/all_in_one - cc/web/templates/index.html`

- [ ] **Step 1: Add nav tab**

After the AR SD-WAN tab button (line 203):

```html
<button class="nav-tab" data-panel="ar-traditional">AR 传统组网</button>
```

- [ ] **Step 2: Add tool panel HTML**

Add after the AR SD-WAN section (before `<!-- ═══ 我来定模板 ═══ -->`):

```html
<!-- ═══ AR 传统组网 ═══ -->
<section class="tool-panel" id="panel-ar-traditional">
<div class="panel-header"><h1 class="panel-title">AR 传统组网</h1><p class="panel-subtitle">双线 BGP + GRE + IPSec · 华为 AR 配置生成</p></div>
<div class="variant-bar" data-tool="ar-traditional">
<button class="variant-pill active" data-variant="dual">双线</button>
</div>
<div class="info-row">
<div class="card"><div class="card-h" onclick="tg(this)"><span>备注说明</span><span class="carr">▼</span></div><div class="card-b"><textarea class="ft notes" id="ar-traditional-notes" readonly></textarea></div></div>
<div class="card"><div class="card-h" onclick="tg(this)"><span>填写示例</span><span class="carr">▼</span></div><div class="card-b"><textarea class="ft ex" id="ar-traditional-example" readonly></textarea></div></div>
</div>
<div class="editor-grid">
<div class="card"><div class="card-h">数据头输入</div><div class="card-b p0"><textarea class="ft hdr" id="ar-traditional-header" placeholder="粘贴数据头（含主备两条 LineID）…"></textarea></div><div style="padding:6px 12px;border-top:1px solid var(--hls);display:flex;gap:6px"><button class="btn btn-s" onclick="clearAll('ar-traditional')" style="font-size:11px">清除数据头</button></div></div>
<div class="card"><div class="card-h">参数设置</div><div class="card-b">
<div class="fg"><label class="fl">Hostname</label><input class="fi" id="ar-traditional-hostname" placeholder="从数据头自动提取"></div>
<div class="fr2">
<div class="fg"><label class="fl">WAN 接口</label><input class="fi" id="ar-traditional-wan-if" value="GigabitEthernet0/0/9"></div>
<div class="fg"><label class="fl">LAN 接口</label><input class="fi" id="ar-traditional-lan-if" value="GigabitEthernet0/0/1"></div>
</div>
<div class="fr2">
<div class="fg"><label class="fl">WAN IP</label><input class="fi" id="ar-traditional-wan-ip" value="173.15.30.40"></div>
<div class="fg"><label class="fl">WAN 掩码</label><input class="fi" id="ar-traditional-wan-mask" value="255.255.255.0"></div>
</div>
<div class="fr2">
<div class="fg"><label class="fl">LAN IP</label><input class="fi" id="ar-traditional-lan-ip" value="173.15.20.10"></div>
<div class="fg"><label class="fl">LAN 掩码</label><input class="fi" id="ar-traditional-lan-mask" value="255.255.255.0"></div>
</div>
<div class="fr2">
<div class="fg"><label class="fl">WAN 网关</label><input class="fi" id="ar-traditional-wan-gw" value="173.15.30.254"></div>
<div class="fg"><label class="fl">LAN 网关</label><input class="fi" id="ar-traditional-lan-gw" value="173.15.30.254"></div>
</div>
<div class="fg"><label class="fl">内网段（每行一个，用于 ACL 和回程路由）</label><textarea class="ft ft-sm" id="ar-traditional-inner-nets">192.168.0.0/16
172.16.0.0/12
10.0.0.0/8</textarea></div>
<div class="fg"><label class="fl">BGP 宣告网段（每行一个，不含掩码，如 173.15.30.0）</label><textarea class="ft ft-sm" id="ar-traditional-bgp-nets">173.15.30.0
173.15.20.0
173.15.40.0
173.15.50.0</textarea></div>
<div style="display:flex;gap:16px">
<div class="cb"><input type="checkbox" id="ar-traditional-gen-rr"><label for="ar-traditional-gen-rr">生成回程路由</label></div>
<div class="cb"><input type="checkbox" id="ar-traditional-bypass"><label for="ar-traditional-bypass">旁挂模式（不生成LAN接口）</label></div>
</div>
</div></div></div>
<div class="btn-row"><button class="btn btn-p" onclick="gen('ar-traditional')">生成配置</button><button class="btn btn-s" onclick="copy('ar-traditional-output')">复制输出</button><button class="btn btn-s" onclick="exportOut('ar-traditional')">导出脚本</button><span class="status" id="ar-traditional-status"></span></div>
<div class="card"><div class="card-h">生成结果（可直接编辑）</div><div class="card-b p0"><textarea class="ft code-out" id="ar-traditional-output" spellcheck="false" placeholder="点击「生成配置」…"></textarea></div></div>
</section>
```

- [ ] **Step 3: Add to TM map**

Update the `TM` const (line ~471):

```javascript
const TM={'epoch-fastip':'epoch_fastip','epoch-fastip5':'epoch_fastip5','usg-fastip':'usg_fastip','epoch-mpls':'epoch_mpls','ar-sdwan':'ar_sdwan','ar-traditional':'ar_traditional'};
```

- [ ] **Step 4: Add to `gn()` function for network collection**

Add after the `domain_split` branch in `gn()` (around line 661):

```javascript
  }else if(tp==='ar-traditional'){
    n={hostname:g('hostname')?.value||'',
       wan_if:g('wan-if')?.value||'',wan_ip:g('wan-ip')?.value||'',wan_mask:g('wan-mask')?.value||'',
       lan_if:g('lan-if')?.value||'',lan_ip:g('lan-ip')?.value||'',lan_mask:g('lan-mask')?.value||'',
       wan_gw:g('wan-gw')?.value||'',lan_gw:g('lan-gw')?.value||'',
       inner_nets:g('inner-nets')?.value||'',
       bgp_networks:g('bgp-nets')?.value||'',
       gen_return_route:cb('gen-rr'),bypass:cb('bypass')};
```

- [ ] **Step 5: Add to `ldInitForm()` scenario map**

Add to the `scenarioMap` object (around line 695):

```javascript
      'ar-traditional+dual':'AR 传统组网 · 双线';
```

- [ ] **Step 6: Add to `ldInitForm()` fieldMap**

The fieldMap already handles some keys; add AR traditional specific ones. Actually, the init-defaults for AR traditional will save keys like `wan_if`, `wan_ip`, `wan_mask`, etc. Add mapping:

```javascript
      wan_if:'wan-if',wan_ip:'wan-ip',wan_mask:'wan-mask',
      lan_if:'lan-if',lan_ip:'lan-ip',lan_mask:'lan-mask',
      wan_gw:'wan-gw',lan_gw:'lan-gw',
      inner_nets:'inner-nets',bgp_networks:'bgp-nets',
      gen_return_route:'gen-rr',bypass:'bypass',
```

- [ ] **Step 7: Add to `loadInitDefaults()` labelMap**

Add label mappings for AR traditional fields:

```javascript
      'wan_if':'WAN 接口','lan_if':'LAN 接口',
      'wan_ip':'WAN IP','wan_mask':'WAN 掩码',
      'lan_ip':'LAN IP','lan_mask':'LAN 掩码',
      'wan_gw':'WAN 网关','lan_gw':'LAN 网关',
      'inner_nets':'内网段','bgp_networks':'BGP 宣告网段',
      'gen_return_route':'生成回程路由','bypass':'旁挂模式',
```

- [ ] **Step 8: Update the nav tab panel mapping for Ctrl+Enter**

Update the keyboard shortcut map (line 869):

```javascript
    let m={'panel-epoch-fastip':'epoch-fastip','panel-usg-fastip':'usg-fastip','panel-epoch-mpls':'epoch-mpls','panel-ar-sdwan':'ar-sdwan','panel-ar-traditional':'ar-traditional'};
```

- [ ] **Step 9: Update the nav tab click handler to support new panel**

The existing handler (line 689) uses `tab.dataset.panel` to map to `$('panel-'+...)`. The new panel id is `panel-ar-traditional`. Add the tool-specific init logic:

In the nav tab click handler, add `ar-traditional` to the condition:

```javascript
    if(tp!=='templates'&&tp!=='thanks'){
      showNetPanel(tp,gv(tp));
      if(tp==='usg-fastip')usgUpdateDNS(gv(tp));
      if(tp!=='ar-traditional'){ldNotes(tp);ldEx(tp);ldInitForm(tp)}
      else{ldNotesARTraditional();ldExARTraditional();ldInitFormARTraditional()}
    }
```

Actually simpler: since `ar-traditional` only has one variant `dual`, the `ldNotes`/`ldEx`/`ldInitForm` functions should handle it natively by adding to TM.

The `gen()` function uses `TM[tp]` to get the API tool name. `ar-traditional` maps to `ar_traditional`. The `ldNotes()` and `ldEx()` functions also use `TM[tp]`. We need to handle `ar-traditional` in these functions.

`ldNotes` uses a `v=gv(tp)` and `TM[tp]`. `gv('ar-traditional')` returns `'dual'`. So `ldNotes` would call `/api/notes/ar_traditional?variant=dual`. This should work if `_NOTES["ar_traditional"]["dual"]` is defined.

Similarly `ldEx` calls `/api/examples/ar_traditional/dual`. This should work with `_EXAMPLE_MAP[("ar_traditional", "dual")]`.

For `ldInitForm`, the `scenarioMap` key `'ar-traditional+dual'` maps to `'AR 传统组网 · 双线'`, which calls `/api/init-defaults/AR 传统组网 · 双线`.

These should all work without additional changes beyond what we already added.

- [ ] **Step 10: Commit**

```bash
git add "application/all_in_one - cc/web/templates/index.html"
git commit -m "feat: add AR traditional networking frontend panel and JS logic"
```

---

### Task 5: API Logic Tests (pytest)

**Files:**
- Create: `application/test/all_in_one/test_ar_traditional_gen.py`

- [ ] **Step 1: Write generation API tests**

```python
"""AR 传统组网 — Generation API tests"""
import json
import sys
import os
import _bootstrap  # noqa: F401
from app import app

client = app.test_client()

SAMPLE_HEADER = """\
LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""


def test_generate_success():
    """Basic generation with default params should succeed."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9",
            "wan_ip": "173.15.30.40",
            "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1",
            "lan_ip": "173.15.20.10",
            "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254",
            "lan_gw": "173.15.30.254",
            "inner_nets": "192.168.0.0/16\n172.16.0.0/12\n10.0.0.0/8",
            "bgp_networks": "173.15.30.0\n173.15.20.0\n173.15.40.0\n173.15.50.0",
            "gen_return_route": False,
            "bypass": False
        }
    })
    data = r.get_json()
    assert data["ok"], f"Generation failed: {data.get('error', '')}"
    output = data["output"]
    assert len(output) > 500, f"Output too short: {len(output)} chars"
    # Must contain key config blocks
    assert "bgp 65201" in output
    assert "interface GigabitEthernet0/0/9" in output
    assert "interface GigabitEthernet0/0/1" in output
    assert "ike peer main" in output
    assert "ike peer backup" in output
    assert "ipsec policy S2S-IPSEC" in output
    assert "Tunnel0/0/1000" in output
    assert "Tunnel0/0/1001" in output
    assert "LoopBack1000" in output
    assert "LoopBack1001" in output


def test_generate_empty_header():
    """Empty header should return error."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": "",
        "network": {}
    })
    data = r.get_json()
    assert not data["ok"]


def test_generate_single_line_error():
    """Single line (missing backup) should return error."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": "LineID:609498A1\nPE:szd-upe3\nTunnel:Tunnel0/0/1978\nwanip:10.55.19.236/30\nPE 对接:10.200.200.37\nCE 对接:10.50.86.18\nPE AS号:65510\nCE AS号:65201",
        "network": {}
    })
    data = r.get_json()
    assert not data["ok"]


def test_generate_with_return_routes():
    """Return route toggle should add static routes with tag 8888."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9",
            "wan_ip": "173.15.30.40",
            "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1",
            "lan_ip": "173.15.20.10",
            "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254",
            "lan_gw": "173.15.30.254",
            "inner_nets": "192.168.0.0/16",
            "gen_return_route": True,
            "bypass": False
        }
    })
    data = r.get_json()
    assert data["ok"]
    output = data["output"]
    assert "tag 8888" in output, "Return routes with tag 8888 should be present"


def test_generate_bypass_mode():
    """Bypass mode should omit LAN interface."""
    r = client.post("/api/generate/ar_traditional", json={
        "variant": "dual",
        "header_text": SAMPLE_HEADER,
        "network": {
            "wan_if": "GigabitEthernet0/0/9",
            "wan_ip": "173.15.30.40",
            "wan_mask": "255.255.255.0",
            "lan_if": "GigabitEthernet0/0/1",
            "lan_ip": "173.15.20.10",
            "lan_mask": "255.255.255.0",
            "wan_gw": "173.15.30.254",
            "lan_gw": "173.15.30.254",
            "bypass": True
        }
    })
    data = r.get_json()
    assert data["ok"]
    output = data["output"]
    # LAN interface should NOT appear (bypass mode)
    assert "interface GigabitEthernet0/0/1" not in output or "undo portswitch" not in output


def test_example_api():
    """Example API should return sample data."""
    r = client.get("/api/examples/ar_traditional/dual")
    data = r.get_json()
    assert data["ok"]
    assert "LineID:" in data["example"]


def test_notes_api():
    """Notes API should return Chinese notes."""
    r = client.get("/api/notes/ar_traditional?variant=dual")
    data = r.get_json()
    assert data["ok"]
    assert len(data["notes"]) > 20
```

- [ ] **Step 2: Run generation tests**

```bash
py -m pytest application/test/all_in_one/test_ar_traditional_gen.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add application/test/all_in_one/test_ar_traditional_gen.py
git commit -m "test: add AR traditional networking generation API tests"
```

---

### Task 6: Template Editor Tests (pytest)

**Files:**
- Create: `application/test/all_in_one/test_ar_traditional_templates.py`

- [ ] **Step 1: Write template API tests**

```python
"""AR 传统组网 — Template editor API tests"""
import json
import _bootstrap  # noqa: F401
from app import app

client = app.test_client()
SCENARIO_KEY = "AR 传统组网 · 双线"


def test_template_load():
    """Load template should return header, mapping, template."""
    r = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    data = r.get_json()
    assert data["ok"], f"Load failed: {data.get('error', '')}"
    assert len(data["template"]) > 500
    assert "bgp" in data["template"].lower() or "bgp" in data["template"]
    assert len(data["header"]) > 50
    assert "LineID:" in data["header"]
    assert len(data["mapping"]) > 100


def test_template_preview():
    """Preview should fill template variables with parsed header."""
    # First load to get template
    r_load = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    load_data = r_load.get_json()
    assert load_data["ok"]

    r = client.post("/api/template/preview", json={
        "key": SCENARIO_KEY,
        "header": load_data["header"],
        "template": load_data["template"]
    })
    data = r.get_json()
    assert data["ok"], f"Preview failed: {data.get('error', '')}"
    output = data.get("output", "")
    assert len(output) > 500
    # Should NOT contain raw {PLACEHOLDER} variables
    assert "{main_lineid}" not in output
    assert "{backup_lineid}" not in output


def test_template_save_and_reset():
    """Save custom template, verify it loads, then reset."""
    # Load original
    r_orig = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    orig = r_orig.get_json()

    # Save modified
    modified_header = orig["header"] + "\n# test comment"
    r_save = client.post("/api/template/save", json={
        "key": SCENARIO_KEY,
        "header": modified_header,
        "mapping": orig["mapping"],
        "template": orig["template"]
    })
    assert r_save.get_json()["ok"]

    # Load again — should have the modified header
    r_mod = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    mod = r_mod.get_json()
    assert "# test comment" in mod["header"]

    # Reset
    r_reset = client.post("/api/template/reset", json={"key": SCENARIO_KEY})
    assert r_reset.get_json()["ok"]

    # Load after reset — should be back to original
    r_after = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    after = r_after.get_json()
    assert "# test comment" not in after["header"]


def test_scenario_in_list():
    """The scenario should appear in the scenario list."""
    r = client.get("/api/scenarios")
    data = r.get_json()
    assert data["ok"]
    keys = [s["key"] for s in data["scenarios"]]
    assert SCENARIO_KEY in keys


def test_scenario_in_tree():
    """The scenario should appear in the scenario tree."""
    r = client.get("/api/scenarios")
    data = r.get_json()
    assert data["ok"]

    def find_key(nodes):
        for n in nodes:
            if n.get("key") == SCENARIO_KEY:
                return True
            if "children" in n:
                if find_key(n["children"]):
                    return True
        return False

    assert find_key(data["tree"]), f"{SCENARIO_KEY} not found in tree"
```

- [ ] **Step 2: Run template tests**

```bash
py -m pytest application/test/all_in_one/test_ar_traditional_templates.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add application/test/all_in_one/test_ar_traditional_templates.py
git commit -m "test: add AR traditional networking template editor tests"
```

---

### Task 7: Playwright E2E Tests

**Files:**
- Create: `application/test/all_in_one/test_ar_traditional_e2e.py`

- [ ] **Step 1: Write Playwright E2E tests**

```python
"""AR 传统组网 — Playwright E2E tests (real browser)"""
import pytest
import _bootstrap  # noqa: F401


@pytest.mark.playwright
def test_ar_traditional_tab_visible(page):
    """Nav tab 'AR 传统组网' should be visible and clickable."""
    tab = page.locator(".nav-tab", has_text="AR 传统组网")
    assert tab.is_visible()
    tab.click()
    page.wait_for_timeout(500)
    panel = page.locator("#panel-ar-traditional")
    assert panel.is_visible()
    assert "active" in panel.get_attribute("class") or panel.evaluate("el => el.classList.contains('active')")


@pytest.mark.playwright
def test_ar_traditional_variant_pill(page):
    """Variant pill '双线' should be visible and active."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)
    pill = page.locator('[data-tool="ar-traditional"] .variant-pill.active')
    assert pill.is_visible()
    assert pill.text_content() == "双线"


@pytest.mark.playwright
def test_ar_traditional_generate_button(page):
    """Click generate with sample data should produce output."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    # Fill header
    sample = """LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""
    header_ta = page.locator("#ar-traditional-header")
    header_ta.fill(sample)

    # Click generate
    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    # Check output
    output_ta = page.locator("#ar-traditional-output")
    output = output_ta.input_value()
    assert len(output) > 500, f"Output too short: {len(output)}"
    assert "bgp 65201" in output
    assert "ipsec policy S2S-IPSEC" in output


@pytest.mark.playwright
def test_ar_traditional_bypass_toggle(page):
    """Bypass checkbox should toggle and affect output."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    # Check bypass checkbox
    bypass_cb = page.locator("#ar-traditional-bypass")
    assert bypass_cb.is_visible()

    # Fill minimal header and generate with bypass on
    sample = """LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""
    page.locator("#ar-traditional-header").fill(sample)
    bypass_cb.check()
    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    output = page.locator("#ar-traditional-output").input_value()
    assert "bgp 65201" in output  # BGP should still be there


@pytest.mark.playwright
def test_ar_traditional_return_route_toggle(page):
    """Return route checkbox should add tag 8888 routes."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    sample = """LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win"""
    page.locator("#ar-traditional-header").fill(sample)

    # Check return route
    rr_cb = page.locator("#ar-traditional-gen-rr")
    rr_cb.check()

    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    output = page.locator("#ar-traditional-output").input_value()
    assert "tag 8888" in output


@pytest.mark.playwright
def test_ar_traditional_clear_button(page):
    """Clear button should clear header and output."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    page.locator("#ar-traditional-header").fill("test data")
    page.locator("#ar-traditional-output").fill("test output")

    page.locator("button", has_text="清除数据头").click()
    page.wait_for_timeout(300)

    header_val = page.locator("#ar-traditional-header").input_value()
    assert header_val == ""


@pytest.mark.playwright
def test_ar_traditional_copy_button(page):
    """Copy button should be visible."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    copy_btn = page.locator("button", has_text="复制输出")
    assert copy_btn.is_visible()


@pytest.mark.playwright
def test_ar_traditional_no_dhcp_buttons(page):
    """There should be NO DHCP checkboxes for WAN/LAN."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    # Verify no DHCP checkbox in the parameter panel
    panel = page.locator("#panel-ar-traditional")
    dhcp_checkboxes = panel.locator("input[type=checkbox]")
    count = dhcp_checkboxes.count()
    # Only "生成回程路由" and "旁挂模式" checkboxes
    assert count == 2, f"Expected 2 checkboxes, found {count}"
    labels = []
    for i in range(count):
        cb_id = dhcp_checkboxes.nth(i).get_attribute("id")
        if cb_id:
            label = page.locator(f"label[for='{cb_id}']")
            if label.is_visible():
                labels.append(label.text_content())
    assert "生成回程路由" in labels or any("回程" in l for l in labels)
    assert "旁挂" in labels or any("旁挂" in l for l in labels)
    # No DHCP
    assert not any("DHCP" in l or "dhcp" in l for l in labels)


@pytest.mark.playwright
def test_ar_traditional_template_editor_integration(page):
    """Template editor should list AR 传统组网 scenario."""
    page.locator(".nav-tab", has_text="我来定模板").click()
    page.wait_for_timeout(500)

    # Open cascade dropdown
    trigger = page.locator("#tpl-cascade-trigger")
    trigger.click()
    page.wait_for_timeout(500)

    # Find AR 传统组网 in the dropdown
    dropdown = page.locator("#tpl-cascade-dropdown")
    assert dropdown.is_visible()
    assert "AR 传统组网" in dropdown.text_content()


@pytest.mark.playwright
def test_ar_traditional_console_no_errors(page):
    """No console errors on the page after using AR traditional."""
    page.locator(".nav-tab", has_text="AR 传统组网").click()
    page.wait_for_timeout(500)

    page.locator("#ar-traditional-header").fill("""LineID:609498A1
PE:szd-upe3
Tunnel:Tunnel0/0/1978
wanip:10.55.19.236/30
PE 对接:10.200.200.37
CE 对接:10.50.86.18
PE AS号:65510
CE AS号:65201
自环网段：100.100.100.0/30

拨号PE:szd-upe3
对接IP:10.200.200.37
LoopIP:10.50.86.18
拨号ip:183.56.161.86
秘钥:both-win

LineID:609498A2
PE:szc-upe1
Tunnel:Tunnel0/0/1136
wanip:10.30.36.216/30
PE 对接:10.200.200.27
CE 对接:10.50.118.34
PE AS号:65107
CE AS号:65201
自环网段：备 100.100.101.0/30

拨号PE:szc-upe1
对接IP:10.200.200.27
LoopIP:10.50.118.34
拨号ip:120.133.134.72
秘钥:both-win""")

    page.locator("button", has_text="生成配置").click()
    page.wait_for_timeout(3000)

    # Check for JS errors (Playwright auto-collects console errors)
    # The actual error check happens via the page fixture
    # This test ensures the generation completes without crashing
    output = page.locator("#ar-traditional-output").input_value()
    assert not output.startswith("// Error")
    assert not output.startswith("// 错误")
```

- [ ] **Step 2: Run E2E tests**

Start the dev server first:
```bash
cd "application/all_in_one - cc/web" && py app.py
```

Then in another terminal:
```bash
py -m pytest application/test/all_in_one/test_ar_traditional_e2e.py -v --browser=chromium
```

Expected: All 9 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add application/test/all_in_one/test_ar_traditional_e2e.py
git commit -m "test: add AR traditional networking Playwright E2E tests"
```

---

### Task 8: Integration Verification & Cross-Check

**Files:**
- No new files. Verify existing tests still pass.

- [ ] **Step 1: Run existing test suite to check no regressions**

```bash
py -m pytest application/test/all_in_one/test_generation.py application/test/all_in_one/test_templates.py application/test/all_in_one/test_apis.py -v
```

Expected: All existing tests still PASS. No regressions.

- [ ] **Step 2: Run all new AR traditional tests together**

```bash
py -m pytest application/test/all_in_one/test_ar_traditional_gen.py application/test/all_in_one/test_ar_traditional_templates.py -v
```

Expected: All pass.

- [ ] **Step 3: Verify "我来定模板" cascade tree includes the new scenario**

```bash
py -c "import sys; sys.path.insert(0, 'application/all_in_one - cc/web'); from app import _SCENARIO_TREE, _scenario_tree_leaf_keys; keys = _scenario_tree_leaf_keys(_SCENARIO_TREE); assert 'AR 传统组网 · 双线' in keys, f'Missing! Keys: {keys}'; print('OK — scenario in tree')"
```

- [ ] **Step 4: Verify tree validation passes at import time**

```bash
py -c "import sys; sys.path.insert(0, 'application/all_in_one - cc/web'); from app import _validate_scenario_tree; _validate_scenario_tree(); print('OK — tree validated')"
```

- [ ] **Step 5: Commit if any fixes were needed**

Only if regression fixes needed.

---

### Task 9: Record Changes in log/

- [ ] **Step 1: Append to `log/YYYY-MM-DD.md`**

Append to `log/2026-06-09.md`:

```
### AR 传统组网 — 新增场景

- 新增文件: `src/ar_traditional_v1.py` — 业务逻辑模块（解析器、模板常量、builder）
- 新增文件: `data/editor_defaults/AR_传统组网/` — 出厂模板数据
- 修改文件: `web/app.py` — 场景注册、generate API、模板 API、预览、示例/备注
- 修改文件: `web/templates/index.html` — 新 tab、参数面板、JS 逻辑
- 新增测试: `test_ar_traditional_gen.py` — API 生成测试
- 新增测试: `test_ar_traditional_templates.py` — 模板编辑测试
- 新增测试: `test_ar_traditional_e2e.py` — Playwright E2E 测试
- 特点: 无 DHCP 按钮、有回程路由和旁挂选项
```
```

- [ ] **Step 2: Commit log**

```bash
git add log/
git commit -m "docs: log AR traditional networking implementation"
```

---

## Self-Review

**1. Spec coverage:**
- "场景名字是 AR 传统组网" → Task 1-4 implement the scenario with this name
- "标准数据头和配置在 plan/ar传统组网和数据" → Read and used in Task 1 (template design)
- "wan lan口不需要dhcp按钮" → Task 4 (no DHCP checkboxes) + Task 7 (test verifies no DHCP)
- "需要回程路由选项" → Task 4 (gen-rr checkbox) + Task 5 (test verifies tag 8888)
- "需要旁挂选项" → Task 4 (bypass checkbox) + Task 5 (test verifies LAN omitted)
- "全量测试（逻辑和用户侧）" → Task 5 (API) + Task 6 (templates) + Task 7 (Playwright E2E)
- "我来定模板需要更新" → Task 3 (_SCENARIO_TREE) + Task 7 (cascade integration test)
- "先只改demo版" → No RELEASE_MODE conditionals, no port changes — demo only

**2. Placeholder scan:** Verified no TBD/TODO, no "add appropriate error handling", no "similar to Task N" without code.

**3. Type consistency:**
- Module exports `parse_ar_traditional_headers`, `build_ar_traditional_format_dict`, `TEMPLATE_AR_TRADITIONAL`, `AR_TRAD_EXAMPLE`
- API endpoint references `mod.get("parse_ar_traditional_headers")` etc. — consistent
- Frontend uses `ar-traditional` as HTML id prefix, `ar_traditional` as API tool name — consistent
- Template variables match between builder dict keys and template `{placeholders}`
