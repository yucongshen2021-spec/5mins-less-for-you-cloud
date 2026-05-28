# ER FastIP 5.0 非香港出口 (US) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** Implement Epoch FastIP 5.0 US (non-HK) variant — full VyOS template, parser, builder, backend endpoint, and tests.

**Architecture:** Reuse 4.0's `parse_epoch_us` for data header parsing (same format). Create new 5.0 US template and builder. US variant has 3 tunnel layers (ACVPN vtun → GRE → US tunnel) vs HK's single tunnel. No UI changes needed — US already uses `er5-panel-hk-us` form panel.

**Tech Stack:** Python 3, Flask, existing VyOS `set` syntax patterns

---

## 4.0 HK→US Difference Summary

| Aspect | HK | US |
|--------|----|----|
| Tunnels per line | 1 (OpenVPN vtun) | 3 (ACVPN vtun + GRE + US tunnel) |
| BGP update source | CE LOIP (dum0) | NAT IP / FakeIP |
| Dummy interfaces | dum0=CE LOIP, dum1=HKIP | dum0=CE Docking, dum100=main NAT IP, dum200=bk NAT IP |
| BGP peers | RSVR + RSVR2 (4 neighbors) | RSVR + RSVR2 (4 neighbors) |
| Route-map rules | 80-83 (4 rules) | 100-400 (4 rules with different next-hops) |
| NAT source rules | 50(wan), 1000/2000(tunnel), 5000/6000(DNS) | Same pattern + overseas NAT for each inner net |
| Extra | HKIP, HK-specific community | overseas_nat_block, extra_dum for multiple NAT IPs |
| Data header | MAIN/BACKUP blocks | LineID blocks (奇数=主, 偶数=备) with PE sub-blocks |

---

## Files Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/er_fastip_5in1_v1.py` | Add US template, parser (reuse 4.0 parse_epoch_us), builder |
| Modify | `web/app.py` | Wire US variant in generate endpoint |
| Create | `test/test_er5/test_us_generation.py` | US integration tests |
| Modify | `log/2026-05-20.md` | Change log |

---

### Task 1: Add 5.0 US Template & Builder to Module

**Files:** Modify `src/er_fastip_5in1_v1.py`

#### Step 1: Add US template

After `TEMPLATE_EPOCH5_HK`, add `TEMPLATE_EPOCH5_US` using VyOS `set` syntax. Key differences from HK template:
- 2 OpenVPN tunnels per line: ACVPN vtun (main/bk) + Tunnel GRE + US tunnel
- `set interfaces tunnel` for GRE tunnels
- CE Docking as source-address for US tunnels
- Multiple dummy interfaces (dum0=CE Docking, dum100=MAIN_OUTIP, dum200=BK_OUTIP)
- Extra NAT IPs with dum101-dum108 / dum201-dum209
- `{overseas_nat_block}` instead of single NAT rules
- BGP update source = main NAT IP (not CE LOIP)
- Route-map rules numbered 100-400 instead of 80-83

The template follows the same 5.0 patterns: hardcoded 5.0 system values (SSH 2707, SNMP both-win, NTP, timezone, DNS) with template variables for dynamic content.

#### Step 2: Import parse_epoch_us from 4.0 module

Since the data header format is identical, import the parser:
```python
# In the builder, load the 4.0 module to reuse parse_epoch_us
_er4_ns = None
def _get_er4_parser():
    global _er4_ns
    if _er4_ns is None:
        import importlib
        # Load 4.0 module namespace (already cached by web app)
        try:
            import sys
            # Try to get from cached modules
            _er4_ns = sys.modules.get('_web_er_fastip_2in1_v8')
        except:
            pass
    return _er4_ns
```

Actually, simpler approach: copy the `parse_epoch_us` function from 4.0 module into 5.0 module. It's ~100 lines and self-contained. This avoids cross-module dependency issues.

#### Step 3: Write `build_epoch5_us_format_dict(hdr_text)`

Returns `(dict, None)` on success or `(None, error_tuple)` on failure.

Flow:
1. Call `parse_epoch_us(hdr_text)` — same parser as 4.0
2. Read 4.0-compatible params from globals() (same as HK builder): wan_eth/lan_eth/wan_cidr/lan_cidr/wan_gw/wan_dhcp/lan_dhcp/bypass/inner_nets
3. Validate required fields (main_acvpn_gre_pe, main_us_pe, main_us_nat_ips, bk_us_nat_ips)
4. Build format dict with all template variables
5. Generate fwnet_block (hardcoded IPs + inner_nets + BGP IPs)
6. Generate fw_options_block (adjust-mss for tunnels)
7. Generate extra_dum_main_block / extra_dum_bk_block (extra NAT IPs)
8. Generate overseas_nat_block (NAT per inner net, main+bk)
9. Generate bgp_routes (blackhole + static routes)
10. All 5.0-specific values hardcoded inline (same as HK)
11. Return `(d, None)` or `(None, ("parse"/"natmiss"/"network", msg))`

#### Step 4: Fix placeholder

Replace `TEMPLATE_EPOCH5_US = "# [5.0 非香港出口 — 开发中]\n# 模板待实现\n"` with the real template. Replace `build_epoch5_us_format_dict` placeholder with the real builder.

---

### Task 2: Wire US in Backend

**Files:** Modify `web/app.py`

In `generate_epoch_fastip5()`, change the US branch from placeholder error to real implementation:

```python
elif variant == "us":
    build_fn = er5.get("build_epoch5_us_format_dict")
    tpl = er5.get("TEMPLATE_EPOCH5_US", "")
    if not build_fn:
        return jsonify({"ok": False, "error": "US builder not found"}), 500
    result = build_fn(hdr_text)
    if isinstance(result, tuple):
        d, err = result
        if d is None:
            return jsonify({"ok": False, "error": _humanize_error(err, variant)}), 400
    else:
        d = result
    output = tpl.format(**d) if isinstance(d, dict) and tpl else str(d)
    return _log_and_return(tool_id, variant, hdr_text, output, jsonify({"ok": True, "output": output}))
```

Also add US example to `_EXAMPLE_MAP`:
```python
("epoch_fastip5", "us"): ("er_fastip_5in1_v1.py", "US5_EXAMPLE"),
```

Add `US5_EXAMPLE` to the 5.0 module.

---

### Task 3: Integration Tests

**Files:** Create `test/test_er5/test_us_generation.py`

Test cases:
1. Empty header → returns error
2. Valid US header (LineID blocks) → 200 with `set system host-name` and `set interfaces tunnel` in output
3. NAT IP extraction → main_us_nat_ip and bk_us_nat_ip in output
4. Extra NAT IPs → dum101/dum102 generated
5. Missing NAT IPs → natmiss error
6. Custom network params reflected
7. US notes load correctly

---

### Task 4: Log & Verification

- Update `log/2026-05-20.md`
- Cross-check: HK still works, US now works
- Playwright E2E: select 5.0 → 非香港出口 → fill header → generate → verify
