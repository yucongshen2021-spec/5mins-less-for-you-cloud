# ER FastIP 5.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Epoch FastIP 5.0 (VyOS `set` syntax) alongside 4.0 (Epoch syntax) with version toggle. HK variant first, others placeholder.

**Architecture:** New module `er_fastip_5in1_v1.py` + new endpoint `/api/generate/epoch_fastip5`. Version pills in UI. **No new user params — 5.0 uses exact same 4.0 params.** All 5.0-specific values (SSH/SNMP/NTP/PKI/DNS forwarding/DHCP/failover2/probe IPs/jumpbox) are hardcoded in the template/builder.

**Tech Stack:** Python 3, Flask, Vanilla JS/CSS

---

## Files Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/er_fastip_5in1_v1.py` | 5.0 module: parser, builder, templates (all hardcoded 5.0-specific values) |
| Modify | `web/templates/index.html` | Version pills + 5.0 form (same params as 4.0, no extra fields) + JS wiring |
| Modify | `web/app.py` | `/api/generate/epoch_fastip5` endpoint, scenarios, disk aliases, notes, examples, init defaults (4.0-compatible only) |

---

### Task 1: Create 5.0 Module (HK full + placeholders)

**Files:** Create `src/er_fastip_5in1_v1.py`

The module has 5 key parts:

1. **Shared utilities** — `_get`, `wanip_hosts`, `_parse_inner_nets`, `_nets_needing_return_by_network`, validation functions (identical to 4.0 module)
2. **HK template** `TEMPLATE_EPOCH5_HK` — full VyOS `set` syntax, ALL 5.0-specific values hardcoded (SSH port 2707, SNMP both-win, NTP 192.168.55.250/202.104.174.178, timezone Asia/Hong_Kong, DNS CN 223.5.5.5, DNS HK 8.8.4.4/8.8.8.8, DNS global 8.8.4.4/8.8.8.8, cache 10000, probe IPs 114.113.245.99/100, jumpbox 192.168.55.250). Only 4.0-compatible params (`{wan_if}`, `{wan_cidr}`, `{wan_gw}`, `{lan_if}`, `{lan_cidr}`, `{lan_gw}`, `{hostname}`, `{main_*}`, `{bk_*}`, `{ce_loip}`, `{hkip}`, `{fwnet_block}`, `{lan_net_block}`, `{default_route_block}`, `{dhcp_block}`, `{pki_block}`, `{track_block}`, `{dns_ip1}`, `{dns_ip2}`) are template variables.
3. **Placeholder templates** — `TEMPLATE_EPOCH5_US`, `TEMPLATE_EPOCH5_FLINK`, `TEMPLATE_EPOCH5_NEW_EXIT`, `TEMPLATE_EPOCH5_DOMAIN_SPLIT` (all `"# 开发中"`)
4. **Parser** `parse_epoch5_hk_headers(raw_text)` — identical logic to 4.0 HK parser (MAIN/BACKUP blocks, PE, WANIP, TUNNEL, Docking, CE LOIP, HKIP, BGPSERVER IP, derived wanip_hosts, tunnel port)
5. **Builder** `build_epoch5_hk_format_dict(hdr_text)` — reads `DEFAULT_*` from globals() like 4.0, ALL 5.0-specific values hardcoded inline, returns `(dict, None)` or `(None, error)`
6. **Placeholder builders** — for us/flink/new_exit/domain_split: `return None, ("tpl", "5.0 XX模板尚未实现")`
7. **Example** `HK5_EXAMPLE` — from `5.0版本er香港.txt` reference
8. **Merge function** `_visual_merge_er5_init(variant, updates)` — same pattern as 4.0

**Key hardcoded values in builder:**
```python
ssh_port = "2707"
snmp_community = "both-win"
ntp_server1 = "192.168.55.250"
ntp_server2 = "202.104.174.178"
timezone = "Asia/Hong_Kong"
dns_cn_server = "223.5.5.5"
dns_hk_server1 = "8.8.4.4"
dns_hk_server2 = "8.8.8.8"
dns_global1 = "8.8.4.4"
dns_global2 = "8.8.8.8"
dns_cache_size = "10000"
probe_ip1 = "114.113.245.99"
probe_ip2 = "114.113.245.100"
jumpbox_ip = "192.168.55.250"
pki_secret_key = ""  # empty → comment block
```

**PKI block** — when `pki_secret_key` is empty, generate `# PKI secret key 未填写，请手动添加` comment. When filled, generate the `set pki openvpn shared-secret` + `run import` commands.

**DHCP block** — when `DEFAULT_LAN_DHCP` is True, generate DHCP server config from `lan_cidr`/`lan_gw`. DHCP DNS uses hardcoded `dns_cn_server`/`dns_hk_server2`. When DHCP is off, output comment.

**Track/failover2 block** — generated from `main_wanip_local`/`main_wanip_remote` + hardcoded `jumpbox_ip`.

**Default route block** — when `DEFAULT_WAN_DHCP` is False, `set protocols static route 0.0.0.0/0 next-hop {wan_gw} distance '220'`.

**BGP — static route for backup docking:** `set protocols static route {bk_docking}/32 next-hop {wan_gw}` (fallback to comment if bk_docking missing).

**Reference file:** `C:\Users\123\Desktop\all_in_one - cc\5.0版本er香港.txt`

---

### Task 2: Web Backend

**Files:** Modify `web/app.py`

1. Add `_get_er5()` loader → `return _load_module("er_fastip_5in1_v1.py")`
2. Register 5 scenarios in `_SCENARIO_LIST` (key format: `"Epoch FastIP 5.0 · HK 香港出口"`, source: `"er_fastip_5in1_v1.py"`, tpl_slot: `"TEMPLATE_EPOCH5_HK"` etc.)
3. Register disk aliases in `_DISK_ALIASES` (key → `"ER_FastIP_5.0___HK_香港出口"` etc.)
4. Add notes in `_NOTES["epoch_fastip5"]` (hk note, placeholder notes for others)
5. Add `"TEMPLATE_EPOCH5_HK": "HK5_EXAMPLE"` to example_keys dict
6. Add `/api/generate/epoch_fastip5` route — only hk variant works, others return 400 "尚未实现"
7. In `_snapshot_factory_defaults`, seed `"er_fastip_5in1_v1.py::HK"` with ONLY 4.0-compatible params:
   ```python
   _seed("er_fastip_5in1_v1.py::HK", {
       "DEFAULT_WAN_ETH": "eth0", "DEFAULT_LAN_ETH": "eth2",
       "DEFAULT_WAN_CIDR": "192.168.1.106/24", "DEFAULT_WAN_GW": "192.168.1.1",
       "DEFAULT_LAN_CIDR": "192.168.8.1/24", "DEFAULT_LAN_GW": "192.168.8.1",
       "DEFAULT_WAN_DHCP": False, "DEFAULT_LAN_DHCP": True,
       "DEFAULT_INNER_NETS": "192.168.0.0/16", "DEFAULT_GEN_RETURN_ROUTE": False,
       "DEFAULT_DNS1": "8.8.8.8", "DEFAULT_DNS2": "8.8.4.4",
   })
   ```
8. The endpoint uses `_inject_network_to_module(er5, network, is_hk=True)` — same mechanism as 4.0. The same `network` dict with 4.0-compatible keys is passed. The builder reads `globals()` for `DEFAULT_*` values.

**No all_in_one_v2.py changes needed** — the 5.0 module doesn't need init mod constants since the desktop tkinter version is out of scope for this plan. The web app handles everything via `_inject_network_to_module` + `globals()`.

---

### Task 3: Web Frontend

**Files:** Modify `web/templates/index.html`

1. **Version pills** — after variant-bar for epoch-fastip, add:
   ```html
   <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
     <span style="font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;color:var(--mu)">Version</span>
     <button class="variant-pill active" id="er-ver-4" onclick="switchERVersion('4')">4.0 (Epoch)</button>
     <button class="variant-pill" id="er-ver-5" onclick="switchERVersion('5')">5.0 (VyOS)</button>
   </div>
   ```

2. **5.0 form** — `er5-panel-hk-us` with SAME params as 4.0, using IDs prefixed `epoch-fastip5-`:
   - Hostname, WAN eth+DHCP, LAN eth+DHCP, WAN CIDR, WAN GW, LAN CIDR, LAN GW, DNS1, DNS2, inner nets (textarea!), gen-rr checkbox
   - **NO 5.0专属参数 section**

3. **Placeholder panels** for flink/new_exit/domain_split (all hidden, text "开发中")

4. **JS** — `switchERVersion(ver)` toggles pills + re-runs showNetPanel. `showNetPanel` modified to check `erVersion` global. `gen()` routes `epoch-fastip` → `/api/generate/epoch_fastip5` when `erVersion==='5'`. `gn5(tp)` reads same fields as `gn()` but from `epoch-fastip5-*` IDs. 5.0 notes/examples loaded from `epoch_fastip5` API prefix.

5. **Ctrl+Enter** keyboard shortcut also respects version.

---

### Task 4: Integration Test

**Files:** Create `test/test_er5/test_hk_generation.py`

Test cases:
- Basic HK with empty header (returns error for missing PE)
- HK with valid header → `set system host-name` in output, `set protocols bgp` in output
- Unimplemented variants return 400
- Custom network params (WAN CIDR, inner nets, DNS) reflected in output

---

### Task 5: Log & Verification

- Append to `log/2026-05-20.md`
- Cross-scenario check: 4.0 ER, USG, MPLS, AR all still work
- Manual smoke test in browser
