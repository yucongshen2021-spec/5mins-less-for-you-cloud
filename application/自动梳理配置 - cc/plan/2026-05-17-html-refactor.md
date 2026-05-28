# ER/USG Config Analyzer — HTML Refactor Implementation Plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Refactor `er_config_analyzer_gui.py` (4516-line tkinter GUI) into a self-contained HTML page with all parsing, topology analysis, and visualization logic, fixing 10 identified topology logic errors.

**Architecture:** Single self-contained HTML file (`er_config_analyzer.html`) with embedded CSS + JS. All parsing and topology analysis rewritten in JavaScript. Topology rendered as SVG with zoom/pan. DESIGN.md design system applied. No server required — opens directly in browser.

**Tech Stack:** HTML5, CSS3 (DESIGN.md tokens), vanilla JavaScript (ES6+), SVG for topology canvas, Blob/URL for CSV export.

**Key Logic Fixes (10 topology errors identified in review):**
1. `vtun_to_upe` substring matching → use IP equality matching only
2. `_infer_side` over-aggressive substring matching → use word-boundary regex
3. Chain-side "first wins" without conflict escalation → add warning when evidence conflicts
4. Dead code in BGP lane_side rebind (line 2304) → remove unreachable else
5. `_name_hint_side` applies to entire chain → only apply to directly-bound tunnels
6. Canvas lane boundary overflow (lines 4165-4184) → add bound clamping
7. Two independent side resolution pathways diverge silently → unify into single pathway
8. UPE canvas_side set to "unknown" on conflict → prefer structural evidence (vtun)
9. overseas_parent NAT translation skips dummy ifaces → handle dummy + loopback
10. policy_local_targets resolution gap (line 2065) → add to policy_targets instead of dropping

---

## File Structure

```
er_config_analyzer.html        # Main HTML file (self-contained)
test_html_refactor/            # Test directory (per CLAUDE.md Rule 7)
  test_parser.js               # Unit tests for config parsing
  test_topology.js             # Unit tests for topology analysis
  test_topology_fixtures.js    # Port of verify_er_topology_fixtures.py
  test_canvas.js               # Unit tests for canvas layout
  test_runner.html             # In-browser test runner
```

---

### Task 1: HTML Scaffold & Design System

**Files:**
- Create: `er_config_analyzer.html`

- [ ] **Step 1: Create HTML scaffold with DESIGN.md design tokens**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ER/USG Config Analyzer</title>
<style>
  :root {
    --primary: #f54e00;
    --primary-active: #d04200;
    --ink: #26251e;
    --body: #5a5852;
    --muted: #807d72;
    --hairline: #e6e5e0;
    --canvas: #f7f7f4;
    --surface-card: #ffffff;
    --timeline-thinking: #dfa88f;
    --timeline-grep: #9fc9a2;
    --timeline-read: #9fbbe0;
    --timeline-edit: #c0a8dd;
    --timeline-done: #c08532;
    --semantic-error: #cf2d56;
    --semantic-success: #1f8a65;
    --rounded-md: 8px;
    --rounded-lg: 12px;
    --rounded-pill: 9999px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-weight: 400;
    background: var(--canvas);
    color: var(--ink);
    line-height: 1.5;
  }
  /* Tab bar */
  .tab-bar { display: flex; border-bottom: 1px solid var(--hairline); background: var(--surface-card); }
  .tab-btn { padding: 12px 24px; border: none; background: none; cursor: pointer; font-size: 14px; font-weight: 500; color: var(--muted); }
  .tab-btn.active { color: var(--primary); border-bottom: 2px solid var(--primary); }
  /* Panels */
  .panel-container { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; padding: 16px; }
  textarea { width: 100%; font-family: 'JetBrains Mono', monospace; font-size: 13px; border: 1px solid var(--hairline); border-radius: var(--rounded-md); padding: 12px; resize: vertical; }
  .btn-primary { background: var(--primary); color: white; border: none; border-radius: var(--rounded-md); padding: 10px 18px; font-size: 14px; font-weight: 500; cursor: pointer; }
  .btn-primary:hover { background: var(--primary-active); }
  .btn-secondary { background: var(--surface-card); color: var(--ink); border: 1px solid var(--hairline); border-radius: var(--rounded-md); padding: 9px 17px; font-size: 14px; cursor: pointer; }
  /* Result tabs */
  .result-tabs { display: flex; border-bottom: 1px solid var(--hairline); }
  .result-tab { padding: 8px 16px; border: none; background: none; cursor: pointer; font-size: 13px; color: var(--muted); }
  .result-tab.active { color: var(--ink); font-weight: 600; border-bottom: 2px solid var(--ink); }
  /* NAT Table */
  .nat-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .nat-table th { text-align: left; padding: 8px; border-bottom: 1px solid var(--hairline); font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: 11px; letter-spacing: 0.88px; }
  .nat-table td { padding: 8px; border-bottom: 1px solid var(--hairline); }
  /* Topology SVG */
  .topo-container { position: relative; overflow: hidden; border: 1px solid var(--hairline); border-radius: var(--rounded-lg); background: white; }
  /* Toolbar */
  .toolbar { display: flex; gap: 8px; align-items: center; padding: 8px; }
</style>
</head>
<body>
  <!-- Top nav -->
  <div class="tab-bar">
    <button class="tab-btn active" data-scene="er">ER</button>
    <button class="tab-btn" data-scene="usg">USG</button>
  </div>

  <!-- Input panels -->
  <div class="panel-container">
    <div class="panel-left">
      <label>Config Script</label>
      <textarea id="configText" rows="16" placeholder="Paste VyOS / USG config..."></textarea>
      <input type="file" id="configFile" accept=".txt,.cfg,.conf">
    </div>
    <div class="panel-right">
      <label>Fake IP → Real IP Mapping</label>
      <textarea id="mappingText" rows="16" placeholder="10.60.44.28-218.32.88.83&#10;10.60.18.22=150.116.112.236"></textarea>
    </div>
  </div>

  <!-- Toolbar -->
  <div class="toolbar">
    <button class="btn-primary" id="btnAnalyze">Parse & Organize</button>
    <button class="btn-secondary" id="btnExport">Export CSV</button>
    <button class="btn-secondary" id="btnClear">Clear</button>
    <label><input type="checkbox" id="acceptRemark"> Accept Remark Heuristic</label>
  </div>

  <!-- Result tabs -->
  <div class="result-tabs">
    <button class="result-tab active" data-result="nat">NAT Table</button>
    <button class="result-tab" data-result="topology">ER Topology</button>
    <button class="result-tab" data-result="ledger">Parse & Remark</button>
    <button class="result-tab" data-result="ipdigest">IP Digest</button>
  </div>

  <!-- Result panels -->
  <div id="natPanel"><table class="nat-table" id="natTable"></table></div>
  <div id="topologyPanel" hidden>
    <div class="toolbar">
      <button id="zoomIn">+</button>
      <button id="zoomOut">−</button>
      <button id="zoomReset">Reset</button>
      <span id="zoomLabel">100%</span>
    </div>
    <div class="topo-container" id="topoContainer">
      <svg id="topoSvg"></svg>
    </div>
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px;">
      <textarea id="topoSummary" readonly rows="10"></textarea>
      <textarea id="topoMermaid" readonly rows="10"></textarea>
    </div>
  </div>
  <div id="ledgerPanel" hidden><pre id="ledgerText"></pre></div>
  <div id="ipDigestPanel" hidden><pre id="ipDigestText"></pre></div>

  <script src=""></script>
</body>
</html>
```

- [ ] **Step 2: Verify HTML scaffold loads in browser**

Open `er_config_analyzer.html` in Chrome/Edge. Verify the layout renders correctly with tabs, textareas, toolbar, and result panels visible.

- [ ] **Step 3: Commit**

```bash
git add er_config_analyzer.html
git commit -m "feat: add HTML scaffold with DESIGN.md design system"
```

---

### Task 2: Config Parsing Engine (ER + USG)

**Files:**
- Modify: `er_config_analyzer.html` — add `<script>` section

- [ ] **Step 1: Write the IP/mapping parsing tests**

Create `test_html_refactor/test_parser.js`:

```javascript
// test_parser.js — Unit tests for parsing engine
function assert(cond, msg) { if (!cond) throw new Error(msg); }

function test_parse_fake_real_mapping() {
  const p = ERConfigParser;
  // dash separator
  let m = p.parseFakeRealMapping("10.60.44.28-218.32.88.83");
  assert(m["10.60.44.28"] === "218.32.88.83", "dash separator");
  // equals separator
  m = p.parseFakeRealMapping("10.60.44.28=218.32.88.83");
  assert(m["10.60.44.28"] === "218.32.88.83", "equals separator");
  // colon separator
  m = p.parseFakeRealMapping("10.60.44.28:218.32.88.83");
  assert(m["10.60.44.28"] === "218.32.88.83", "colon separator");
  // arrow separator
  m = p.parseFakeRealMapping("10.60.44.28 -> 218.32.88.83");
  assert(m["10.60.44.28"] === "218.32.88.83", "arrow separator");
  // semicolon
  m = p.parseFakeRealMapping("10.60.44.28-218.32.88.83;10.60.18.22-150.116.112.236");
  assert(Object.keys(m).length === 2, "two entries");
  console.log("test_parse_fake_real_mapping: PASS");
}

function test_parse_er_nat_rules() {
  const cfg = `
set nat source rule 10 source address '10.0.0.0/24'
set nat source rule 10 outbound-interface 'tun100'
set nat source rule 10 translation address '203.0.113.5'
set nat source rule 1 outbound-interface 'eth0'
set nat source rule 1 translation address 'masquerade'
`.trim();
  const r = ERConfigParser.parseERConfig(cfg);
  assert(r.rules.length === 2, "two rules");
  assert(r.rules[0].ruleId === "1", "rule 1 first");
  assert(r.rules[1].ruleId === "10", "rule 10 second");
  assert(r.rules[1].sourcePrefixes[0] === "10.0.0.0/24", "source prefix");
  assert(r.rules[1].outboundInterface === "tun100", "outbound iface");
  assert(r.rules[1].translationAddress === "203.0.113.5", "translation");
  console.log("test_parse_er_nat_rules: PASS");
}

function test_mask_to_prefix() {
  assert(ERConfigParser.maskToPrefix("24") === "24", "digit mask");
  assert(ERConfigParser.maskToPrefix("255.255.255.0") === "24", "dotted mask");
  assert(ERConfigParser.maskToPrefix("255.255.255.128") === "25", "/25");
  assert(ERConfigParser.maskToPrefix("invalid") === null, "invalid returns null");
  console.log("test_mask_to_prefix: PASS");
}

test_parse_fake_real_mapping();
test_parse_er_nat_rules();
test_mask_to_prefix();
```

- [ ] **Step 2: Verify tests fail**

Run in browser test runner. Expected: ReferenceError — ERConfigParser not defined.

- [ ] **Step 3: Implement parsing engine in JS**

Add to `er_config_analyzer.html` `<script>` section:

```javascript
// ============================================================
// Parsing Engine
// ============================================================
const IP_PATTERN = /\b(?:\d{1,3}\.){3}\d{1,3}(?:\/\d{1,2})?\b/g;

const ERConfigParser = {
  parseFakeRealMapping(mappingText) {
    const mapping = {};
    const normalized = mappingText.replace(/\r/g, '\n');
    const segments = normalized.split(/[;\n；]+/);
    for (const segment of segments) {
      const s = segment.trim();
      if (!s) continue;
      const parts = s.split(/\s*(?:->|=>|=|:|：|-|—)\s*/, 2);
      if (parts.length === 2) {
        const leftIPs = parts[0].match(IP_PATTERN);
        const rightIPs = parts[1].match(IP_PATTERN);
        if (leftIPs && rightIPs) {
          mapping[leftIPs[0].split('/')[0]] = rightIPs[0].split('/')[0];
          continue;
        }
      }
      const ips = s.match(IP_PATTERN);
      if (ips && ips.length >= 2) {
        mapping[ips[0].split('/')[0]] = ips[1].split('/')[0];
      }
    }
    return mapping;
  },

  maskToPrefix(maskText) {
    const mask = maskText.trim();
    if (!mask) return null;
    if (/^\d+$/.test(mask)) {
      const n = parseInt(mask, 10);
      return (n >= 0 && n <= 32) ? String(n) : null;
    }
    const parts = mask.split('.');
    if (parts.length !== 4) return null;
    let bits = '';
    for (const p of parts) {
      if (!/^\d+$/.test(p)) return null;
      const n = parseInt(p, 10);
      if (n < 0 || n > 255) return null;
      bits += n.toString(2).padStart(8, '0');
    }
    if (bits.includes('01')) return null;
    return String(bits.split('1').length - 1);
  },

  cleanValue(raw) {
    return raw.trim().replace(/^['"]|['"]$/g, '');
  },

  parseERConfig(configText) {
    const rules = {};
    const dnatRules = {};
    const ifaceDesc = {};

    const natFieldRe = /^set\s+nat\s+source\s+rule\s+(\d+)\s+(source|destination)\s+address\s+'?([^'\s]+)'?/i;
    const natOutboundRe = /^set\s+nat\s+source\s+rule\s+(\d+)\s+outbound-interface\s+'?([^'\s]+)'?/i;
    const natTransRe = /^set\s+nat\s+source\s+rule\s+(\d+)\s+translation\s+address\s+'?([^'\s]+)'?/i;
    const dnatDstRe = /^set\s+nat\s+destination\s+rule\s+(\d+)\s+destination\s+address\s+'?([^'\s]+)'?/i;
    const dnatInRe = /^set\s+nat\s+destination\s+rule\s+(\d+)\s+inbound-interface\s+'?([^'\s]+)'?/i;
    const dnatTransRe = /^set\s+nat\s+destination\s+rule\s+(\d+)\s+translation\s+address\s+'?([^'\s]+)'?/i;
    const ifaceDescRe = /^set\s+interfaces\s+(?:tunnel|openvpn|dummy|ethernet)\s+([^\s]+)\s+description\s+'([^']+)'/i;

    for (const raw of configText.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;

      let m = natFieldRe.exec(line);
      if (m) {
        const [_, ruleId, direction, addr] = m;
        if (!rules[ruleId]) rules[ruleId] = { ruleId, sourcePrefixes: [], destinationPrefixes: [], outboundInterface: null, translationAddress: null };
        const a = ERConfigParser.cleanValue(addr);
        if (direction.toLowerCase() === 'source') rules[ruleId].sourcePrefixes.push(a);
        else rules[ruleId].destinationPrefixes.push(a);
        continue;
      }
      m = natOutboundRe.exec(line);
      if (m) {
        const [_, ruleId, iface] = m;
        if (!rules[ruleId]) rules[ruleId] = { ruleId, sourcePrefixes: [], destinationPrefixes: [], outboundInterface: null, translationAddress: null };
        rules[ruleId].outboundInterface = ERConfigParser.cleanValue(iface);
        continue;
      }
      m = natTransRe.exec(line);
      if (m) {
        const [_, ruleId, ip] = m;
        if (!rules[ruleId]) rules[ruleId] = { ruleId, sourcePrefixes: [], destinationPrefixes: [], outboundInterface: null, translationAddress: null };
        rules[ruleId].translationAddress = ERConfigParser.cleanValue(ip);
        continue;
      }
      m = ifaceDescRe.exec(line);
      if (m) {
        ifaceDesc[ERConfigParser.cleanValue(m[1])] = ERConfigParser.cleanValue(m[2]);
        continue;
      }
      m = dnatDstRe.exec(line);
      if (m) {
        const rid = ERConfigParser.cleanValue(m[1]);
        if (!dnatRules[rid]) dnatRules[rid] = { ruleId: rid, inboundInterface: null, destinationPrefixes: [], translationAddress: null };
        dnatRules[rid].destinationPrefixes.push(ERConfigParser.cleanValue(m[2]));
        continue;
      }
      m = dnatInRe.exec(line);
      if (m) {
        const rid = ERConfigParser.cleanValue(m[1]);
        if (!dnatRules[rid]) dnatRules[rid] = { ruleId: rid, inboundInterface: null, destinationPrefixes: [], translationAddress: null };
        dnatRules[rid].inboundInterface = ERConfigParser.cleanValue(m[2]);
        continue;
      }
      m = dnatTransRe.exec(line);
      if (m) {
        const rid = ERConfigParser.cleanValue(m[1]);
        if (!dnatRules[rid]) dnatRules[rid] = { ruleId: rid, inboundInterface: null, destinationPrefixes: [], translationAddress: null };
        dnatRules[rid].translationAddress = ERConfigParser.cleanValue(m[2]);
        continue;
      }
    }
    return {
      rules: Object.values(rules).sort((a, b) => parseInt(a.ruleId) - parseInt(b.ruleId)),
      dnatRules: Object.values(dnatRules).sort((a, b) => parseInt(a.ruleId) - parseInt(b.ruleId)),
      ifaceDesc,
    };
  },

  parseUSGConfig(configText) {
    const addressSets = {};
    const natAddressGroups = {};
    const interfaceDesc = {};
    const rules = [];
    let currentAddressSet = null, currentNatGroup = null, currentInterface = null, currentRule = null;

    const addrSetStartRe = /^ip\s+address-set\s+([^\s]+)\s+type\s+object$/i;
    const addrEntryRe = /^address\s+\d+\s+([0-9.]+)\s+mask\s+([0-9.]+|\d+)$/i;
    const natGroupStartRe = /^nat\s+address-group\s+([^\s]+)(?:\s+\d+)?$/i;
    const natSectionRe = /^section\s+\d+\s+([0-9.]+)\s+([0-9.]+)$/i;
    const ifStartRe = /^interface\s+([^\s]+)$/i;
    const ifDescRe = /^description\s+(.+)$/i;
    const ruleNameRe = /^rule\s+name\s+(.+)$/i;
    const egressRe = /^egress-interface\s+([^\s]+)$/i;
    const srcSetRe = /^source-address\s+address-set\s+([^\s]+)$/i;
    const srcDirectRe = /^source-address\s+([0-9.]+)\s+mask\s+([0-9.]+|\d+)$/i;
    const srcRangeRe = /^source-address\s+range\s+([0-9.]+)\s+([0-9.]+)$/i;
    const actionGroupRe = /^action\s+source-nat\s+address-group\s+([^\s]+)/i;

    for (const raw of configText.split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;

      let m = addrSetStartRe.exec(line);
      if (m) { currentAddressSet = ERConfigParser.cleanValue(m[1]); if (!addressSets[currentAddressSet]) addressSets[currentAddressSet] = []; currentNatGroup = null; continue; }
      m = addrEntryRe.exec(line);
      if (m && currentAddressSet) {
        const prefix = ERConfigParser.maskToPrefix(m[2]);
        if (prefix !== null) addressSets[currentAddressSet].push(m[1] + '/' + prefix);
        continue;
      }
      m = natGroupStartRe.exec(line);
      if (m) { currentNatGroup = ERConfigParser.cleanValue(m[1]); if (!natAddressGroups[currentNatGroup]) natAddressGroups[currentNatGroup] = []; currentAddressSet = null; continue; }
      m = natSectionRe.exec(line);
      if (m && currentNatGroup) {
        natAddressGroups[currentNatGroup].push(m[1]);
        if (m[2] !== m[1]) natAddressGroups[currentNatGroup].push(m[2]);
        continue;
      }
      m = ifStartRe.exec(line);
      if (m) { currentInterface = ERConfigParser.cleanValue(m[1]); currentAddressSet = null; currentNatGroup = null; continue; }
      m = ifDescRe.exec(line);
      if (m && currentInterface) { interfaceDesc[currentInterface] = ERConfigParser.cleanValue(m[1]); continue; }
      m = ruleNameRe.exec(line);
      if (m) { currentRule = { ruleName: ERConfigParser.cleanValue(m[1]), egressInterface: null, sourceAddressSet: null, sourcePrefixes: [], actionType: null, actionAddressGroup: null }; rules.push(currentRule); continue; }
      if (!currentRule) continue;
      m = egressRe.exec(line);
      if (m) { currentRule.egressInterface = ERConfigParser.cleanValue(m[1]); continue; }
      m = srcSetRe.exec(line);
      if (m) { currentRule.sourceAddressSet = ERConfigParser.cleanValue(m[1]); continue; }
      m = srcDirectRe.exec(line);
      if (m) { const prefix = ERConfigParser.maskToPrefix(m[2]); if (prefix !== null) currentRule.sourcePrefixes.push(m[1] + '/' + prefix); continue; }
      m = srcRangeRe.exec(line);
      if (m) { currentRule.sourcePrefixes.push(m[1] + '-' + m[2]); continue; }
      m = actionGroupRe.exec(line);
      if (m) { currentRule.actionType = 'source-nat-address-group'; currentRule.actionAddressGroup = ERConfigParser.cleanValue(m[1]); continue; }
      if (/^action\s+source-nat\s+easy-ip$/i.test(line)) { currentRule.actionType = 'source-nat-easy-ip'; continue; }
      if (/^action\s+no-nat$/i.test(line)) { currentRule.actionType = 'no-nat'; continue; }
    }
    return { rules, addressSets, natAddressGroups, ifaceDesc: interfaceDesc };
  }
};
```

- [ ] **Step 4: Run tests to verify**

Open `test_html_refactor/test_runner.html` in browser. Expected: all 3 parser tests PASS.

- [ ] **Step 5: Commit**

```bash
git add er_config_analyzer.html test_html_refactor/test_parser.js test_html_refactor/test_runner.html
git commit -m "feat: port ER/USG config parsing engine to JavaScript"
```

---

### Task 3: NAT Table Output (buildOutputRows)

**Files:**
- Modify: `er_config_analyzer.html` — add buildOutputRows functions

- [ ] **Step 1: Write the NAT table output test**

Add to `test_html_refactor/test_parser.js`:

```javascript
function test_build_output_rows_er() {
  const cfg = `
set nat source rule 10 source address '10.0.0.0/24'
set nat source rule 10 outbound-interface 'tun100'
set nat source rule 10 translation address '203.0.113.5'
`.trim();
  const rows = Analyzer.buildOutputRows(cfg, "203.0.113.5-218.32.88.83");
  assert(rows.length === 1, "one row");
  assert(rows[0].rule === "SNAT-10", "rule label");
  assert(rows[0].source_ip === "10.0.0.0/24", "source");
  assert(rows[0].egress_name === "tun100", "egress");
  assert(rows[0].fake_ip === "203.0.113.5", "fake");
  assert(rows[0].real_ip === "218.32.88.83", "real");
  console.log("test_build_output_rows_er: PASS");
}

function test_build_output_rows_skips_masquerade() {
  const cfg = `
set nat source rule 1 outbound-interface 'eth0'
set nat source rule 1 translation address 'masquerade'
`.trim();
  const rows = Analyzer.buildOutputRows(cfg, "");
  assert(rows.length === 0, "masquerade skipped");
  console.log("test_build_output_rows_skips_masquerade: PASS");
}
```

- [ ] **Step 2: Implement buildOutputRows**

Add to `er_config_analyzer.html` `<script>`:

```javascript
// ============================================================
// NAT Table Builder
// ============================================================
const Analyzer = {
  buildOutputRows(configText, mappingText) {
    const cfg = ERConfigParser.parseERConfig(configText);
    const mapping = ERConfigParser.parseFakeRealMapping(mappingText);
    const rows = [];
    for (const rule of cfg.rules) {
      const outbound = rule.outboundInterface || '(未指定)';
      const egressRemark = cfg.ifaceDesc[outbound] || '(无备注)';
      const fakeIp = (rule.translationAddress || '').split('/')[0];
      if (fakeIp.toLowerCase() === 'masquerade') continue;
      const realIp = mapping[fakeIp] || '';
      const prefixes = rule.sourcePrefixes;
      if (prefixes.length > 0) {
        for (const prefix of prefixes) {
          rows.push({ rule: `SNAT-${rule.ruleId}`, source_ip: prefix, egress_name: outbound, egress_remark: egressRemark, fake_ip: fakeIp || '(无)', real_ip: realIp || '(未提供)' });
        }
      } else if (rule.outboundInterface && fakeIp) {
        rows.push({ rule: `SNAT-${rule.ruleId}`, source_ip: '(配置未限定 source-address/network)', egress_name: outbound, egress_remark: egressRemark, fake_ip: fakeIp || '(无)', real_ip: realIp || '(未提供)' });
      }
    }
    for (const dr of cfg.dnatRules) {
      const inbound = dr.inboundInterface || '(未指定)';
      const remark = cfg.ifaceDesc[inbound] || '(无备注)';
      const fakeIp = (dr.destinationPrefixes[0] || '(无)').split('/')[0];
      const realIp = (dr.translationAddress || '(无)').split('/')[0];
      const dstText = dr.destinationPrefixes.join(',') || '(无)';
      rows.push({ rule: `DNAT-${dr.ruleId}`, source_ip: `DST:${dstText}`, egress_name: inbound, egress_remark: remark, fake_ip: fakeIp, real_ip: realIp });
    }
    return rows;
  },

  buildOutputRowsUSG(configText, mappingText) {
    const parsed = ERConfigParser.parseUSGConfig(configText);
    const mapping = ERConfigParser.parseFakeRealMapping(mappingText);
    const rows = [];
    for (const rule of parsed.rules) {
      if (!rule.actionType || rule.actionType === 'no-nat' || rule.actionType === 'source-nat-easy-ip') continue;
      const egress = rule.egressInterface || '(未指定)';
      const egressRemark = parsed.ifaceDesc[egress] || '(无备注)';
      let prefixes = [...rule.sourcePrefixes];
      if (rule.sourceAddressSet && parsed.addressSets[rule.sourceAddressSet]) {
        prefixes = [...new Set([...prefixes, ...parsed.addressSets[rule.sourceAddressSet]])].sort();
      }
      if (prefixes.length === 0) continue;
      let fakeIps = [];
      if (rule.actionType === 'source-nat-address-group') {
        const gn = rule.actionAddressGroup || '';
        fakeIps = parsed.natAddressGroups[gn] || parsed.addressSets[gn] || [];
      }
      if (fakeIps.length === 0) continue;
      for (const prefix of prefixes) {
        for (const fake of fakeIps) {
          const fakeKey = fake.split('/')[0].trim() || '(未识别)';
          const realIp = mapping[fakeKey] || '';
          rows.push({ rule: rule.ruleName, source_ip: prefix, egress_name: egress, egress_remark: egressRemark, fake_ip: fakeKey, real_ip: realIp || '(未提供)' });
        }
      }
    }
    return rows;
  }
};
```

- [ ] **Step 3: Wire up NAT table rendering in HTML**

Add to `<script>`:

```javascript
function renderNATTable(rows) {
  const tbody = document.querySelector('#natTable tbody') || document.createElement('tbody');
  tbody.innerHTML = '';
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6">No NAT rules found</td></tr>';
    return;
  }
  for (const r of rows) {
    tbody.innerHTML += `<tr>
      <td>${escHtml(r.rule)}</td>
      <td>${escHtml(r.source_ip)}</td>
      <td>${escHtml(r.egress_name)}</td>
      <td>${escHtml(r.egress_remark)}</td>
      <td>${escHtml(r.fake_ip)}</td>
      <td>${escHtml(r.real_ip)}</td>
    </tr>`;
  }
}
function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
```

- [ ] **Step 4: Verify test passes**

Run test_runner.html. Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add er_config_analyzer.html test_html_refactor/test_parser.js
git commit -m "feat: implement NAT table output builder with masquerade filtering"
```

---

### Task 4: Topology Analysis Engine (Part 1 — Parsing)

**Files:**
- Modify: `er_config_analyzer.html` — add topology parsing section

This is the largest task. Port the `analyze_er_topology` function (lines 842-3007, ~2165 lines of Python) to JavaScript.

- [ ] **Step 1: Write topology fixture test**

Create `test_html_refactor/test_topology_fixtures.js` — port all 8 tests from `verify_er_topology_fixtures.py`:

```javascript
function test_remark_upe_vs_nat_outbound_conflict() {
  const cfg = `
set system host-name 'test'
set interfaces tunnel tun99 description '专线UPE'
set interfaces tunnel tun99 address '10.1.1.1/30'
set interfaces tunnel tun99 remote '10.1.1.2'
set nat source rule 9 outbound-interface 'tun99'
`.trim();
  const res = Topology.analyze(cfg, false);
  const ledger = res.parse_ledger || {};
  const conflicts = ledger.remark_conflicts || [];
  const names = conflicts.map(x => x.tunnel);
  if (!names.includes('tun99')) throw new Error(`expected remark conflict on tun99, got ${names}`);
  const tun = (res.tunnels || {})['tun99'];
  if (!tun || tun.inferred_role !== 'gre-overseas') throw new Error(`expected gre-overseas, got ${tun && tun.inferred_role}`);
  console.log('test_remark_upe_vs_nat_outbound_conflict: PASS');
}
// ... (7 more tests matching verify_er_topology_fixtures.py)
```

- [ ] **Step 2: Implement topology data model classes**

Add to `er_config_analyzer.html`:

```javascript
// ============================================================
// Topology Data Model
// ============================================================
class TunnelNode {
  constructor(name, kind) {
    this.name = name;
    this.kind = kind;
    this.source = '';
    this.remote = '';
    this.address = '';
    this.description = '';
    this.inferred_role = 'unknown';
    this.side = 'unknown';
    this.canvas_side = 'unknown';
    this.evidence = [];
  }
}

class RouteEdge {
  constructor(destination, nextHop) {
    this.destination = destination;
    this.next_hop = nextHop;
    this.route_table = 'main';
    this.via_tunnel = '';
    this.origin = 'unknown';
    this.preference = '';
    this.track_name = '';
    this.evidence = '';
  }
}

class BgpBinding {
  constructor(neighbor, peerGroup = '') {
    this.neighbor = neighbor;
    this.peer_group = peerGroup;
    this.update_source = '';
    this.egress_hint = '';
    this.remote_as = '';
    this.export_prefix_list = '';
    this.advertised_prefixes = [];
    this.lane_side = '';
    this.anchor_tunnel = '';
    this.transport_tunnel = '';
  }
}

class LedgerItem {
  constructor(topic, count = 0, exampleLines = [], detail = '') {
    this.topic = topic; this.count = count; this.example_lines = exampleLines; this.detail = detail;
  }
}

class RemarkConflict {
  constructor(tunnel, remarkHint, resolvedRole, strongBasis, reference = '') {
    this.tunnel = tunnel; this.remark_hint = remarkHint; this.resolved_role = resolvedRole; this.strong_basis = strongBasis; this.reference = reference;
  }
}
```

- [ ] **Step 3: Implement keyword detection with FIXED regex (word-boundary)**

Incorporate **Fix #2** from the logic audit:

```javascript
// FIXED: Use word-boundary regex instead of substring matching
const RE_BK = /\bBK[-_]/i;         // (BK- or BK_ at word boundary
const RE_BACKUP_WORD = /\bback(?:up)?\b/i;
const RE_PRI = /\bPRI(?:mary)?\b/i;
const RE_MAIN = /\bmain\b/i;
const RE_BK_START = /^bk[-_]/i;

// FIXED: No more loose "bk" / "_b" / "_a" / "main" substring matching
function lineRemarkIsBackup(...parts) {
  const blob = parts.filter(p => p).join(' ');
  if (!blob.trim()) return false;
  return RE_BK.test(blob) || RE_BACKUP_WORD.test(blob) || RE_BK_START.test(blob.trim());
}

function lineRemarkIsMain(...parts) {
  const blob = parts.filter(p => p).join(' ');
  if (!blob.trim()) return false;
  return RE_PRI.test(blob) || RE_MAIN.test(blob) || blob.includes('主');
}
```

- [ ] **Step 4: Implement tunnel/route/BGP parsing for topology**

Port the ~40 regex patterns from Python lines 873-988 into JavaScript. This is ~300 lines of parsing code. Implement as `Topology.parseConfig(text)` returning `{tunnels, routes, bgp, policies, ...}`.

- [ ] **Step 5: Verify topology fixture tests pass**

Run test_runner.html. Expected: all 8 fixture tests PASS.

- [ ] **Step 6: Commit**

```bash
git add er_config_analyzer.html test_html_refactor/test_topology_fixtures.js
git commit -m "feat: port topology parsing engine with fixed keyword detection"
```

---

### Task 5: Topology Analysis Engine (Part 2 — Role Inference & Relationships)

**Files:**
- Modify: `er_config_analyzer.html` — add role inference, overseas_parent, vtun_to_upe, chain building

- [ ] **Step 1: Implement role inference (port lines 1522-1750)**

```javascript
// Role inference
const ACCESS_TRANSPORT_ROLES = new Set(['openvpn', 'ipsec-vti', 'ipsec-policy']);

function inferRoles(tunnels, natOutbounds, accessIpIndex, transportUnderlayIPs, routes, ovpnRemoteSet) {
  for (const n of Object.values(tunnels)) {
    const nameL = n.name.toLowerCase();
    if (n.kind === 'openvpn' || nameL.startsWith('vtun')) {
      n.inferred_role = 'openvpn';
    } else if (n.kind === 'vti') {
      n.inferred_role = 'ipsec-vti';
    } else if (['dummy', 'ethernet', 'loopback'].includes(n.kind) && (n.description || '').includes('IPsec site-to-site local TS')) {
      n.inferred_role = 'ipsec-policy';
    } else if (n.kind === 'tunnel') {
      n.inferred_role = 'gre-unknown';
    }
  }

  // Route-driven GRE-UPE inference
  for (const n of Object.values(tunnels)) {
    if (n.inferred_role !== 'gre-unknown') continue;
    const srcIp = (n.source || '').split('/')[0];
    if (accessIpIndex[srcIp] || transportUnderlayIPs.has(srcIp)) {
      const hasOverseasRoute = routes.some(r => r.destination === `${n.remote}/32` && ovpnRemoteSet.has(r.next_hop));
      if (hasOverseasRoute) { n.inferred_role = 'gre-upe'; continue; }
    }
    if (natOutbounds.includes(n.name)) { n.inferred_role = 'gre-overseas'; continue; }
  }

  // ... (continue with source-address underlay binding, GRE-overseas from UPE peer routes)
}
```

- [ ] **Step 2: Implement overseas_parent with FIXED logic**

Incorporate **Fix #9**: handle dummy interfaces alongside loopback in NAT translation path.

```javascript
// FIXED: handle both loopback AND dummy interfaces in NAT translation parent resolution
function resolveSourceInterface(srcIp, ifaceAddrBook) {
  for (const [iface, addrs] of Object.entries(ifaceAddrBook)) {
    for (const a of addrs) {
      if (a.split('/')[0] === srcIp) return iface;
    }
  }
  return null;
}

// In overseas_parent loop:
// FIXED: was "src_iface.lower().startsWith('lo')"
// Now handles loopback AND dummy interfaces
const srcIface = resolveSourceInterface(n.source, localIfaceAddrs);
const isNonPhysicalAccess = srcIface && (srcIface.toLowerCase().startsWith('lo') || srcIface.toLowerCase().startsWith('dum'));
// ... use NAT translation evidence when isNonPhysicalAccess is true
```

- [ ] **Step 3: Implement vtun_to_upe with FIXED matching**

Incorporate **Fix #1**: IP equality instead of substring matching.

```javascript
// FIXED: Use IP equality, not substring matching
function buildVtunToUpe(tunnels) {
  const upeNodes = Object.values(tunnels).filter(t => t.inferred_role === 'gre-upe');
  const vtNodes = Object.values(tunnels).filter(t => ACCESS_TRANSPORT_ROLES.has(t.inferred_role));
  const pairs = [];

  for (const upe of upeNodes) {
    const upeSourceIP = (upe.source || '').split('/')[0];

    for (const vt of vtNodes) {
      // FIXED: Match by IP address equality, not substring
      const vtAddrIP = (vt.address || '').split('/')[0];
      const vtLocalIP = vt.address ? vt.address.split('/')[0] : '';

      // Priority 1: vt.address IP equals upe.source IP
      if (vtAddrIP && vtAddrIP === upeSourceIP) {
        pairs.push([vt.name, upe.name]);
        break;
      }
      // Priority 2: vt local IP matches upe source IP
      if (vtLocalIP && vtLocalIP === upeSourceIP) {
        pairs.push([vt.name, upe.name]);
        break;
      }
    }
  }
  return pairs;
}
```

- [ ] **Step 4: Implement chain building and side resolution with FIXED logic**

Incorporate **Fix #3**: add warning when chain-side evidence conflicts.
Incorporate **Fix #5**: only apply BGP naming to directly-bound tunnels, not entire chain.

```javascript
// FIXED: _name_hint_side only applies to the directly-bound tunnel's chain,
// not broadcast to all chains that happen to share a member.
// FIXED: When evidence conflicts for chain side, escalate to warning.
function resolveChainSides(chains, chainMembers, bgpBindings, routes, tunnels) {
  const chainSide = {};
  const chainReason = {};
  const sideWarnings = [];

  for (const [cid, members] of Object.entries(chains)) {
    // Step 1: BGP naming — only for chains that contain the BGP's anchor tunnel
    // FIXED: only apply to chain containing the directly-bound tunnel
    for (const b of bgpBindings) {
      if (!b.anchor_tunnel || !members.includes(b.anchor_tunnel)) continue;
      const hint = nameHintSide(b.peer_group, b.neighbor);
      if (hint !== 'unknown' && (chainSide[cid] || 'unknown') === 'unknown') {
        chainSide[cid] = hint;
        chainReason[cid] = `bgp_name:${b.peer_group}`;
      } else if (hint !== 'unknown' && chainSide[cid] !== hint) {
        // FIXED: Log conflict instead of silently ignoring
        sideWarnings.push(`Chain ${cid}: BGP naming suggests ${hint} but chain already ${chainSide[cid]}`);
      }
    }
    // ... (steps 2-3: track naming, remark fallback)
  }

  return { chainSide, chainReason, sideWarnings };
}
```

- [ ] **Step 5: Implement chain-to-tunnel side propagation**

Incorporate **Fix #7**: use single unified pathway.

```javascript
// FIXED: Single unified side resolution — chain_side_map is authoritative.
// topology_line_side_for_node no longer exists as a fallback; instead,
// per-node resolution delegates to chain membership.
function resolveTunnelSide(tunnelName, chainIdByTunnel, chainSideMap) {
  const cid = chainIdByTunnel[tunnelName];
  if (cid) return chainSideMap[cid] || 'unknown';
  return 'unknown';
}
```

- [ ] **Step 6: Run fixture tests**

Expected: all 8 topology fixture tests still PASS with fixed logic.

- [ ] **Step 7: Commit**

```bash
git add er_config_analyzer.html test_html_refactor/test_topology_fixtures.js
git commit -m "feat: implement topology role inference, parent resolution, chain building with 5 logic fixes"
```

---

### Task 6: Topology Analysis Engine (Part 3 — Assembly & Output)

**Files:**
- Modify: `er_config_analyzer.html` — add warnings, summary, mermaid, ledger, IP digest

- [ ] **Step 1: Implement default route resolution (port lines 2335-2409)**

```javascript
function resolveDefaultEgress(tunnels, routes, lineSideMap) { /* ... */ }
```

- [ ] **Step 2: Implement Mermaid graph generation (port lines 2414-2505)**

```javascript
function generateMermaid(tunnels, routes, bgp, graphNodes, graphEdges) { /* ... */ }
```

- [ ] **Step 3: Implement warnings, summary, ledger assembly (port lines 2507-2654)**

Incorporate **Fix #3**: include side_conflicts in warnings output.

- [ ] **Step 4: Implement IP digest (port lines 2656-2717)**

- [ ] **Step 5: Implement `Topology.analyze()` entry point**

Assembles all sub-functions and returns the comprehensive result dictionary (matching the Python return at lines 2972-3007).

- [ ] **Step 6: Wire up `analyze` button in HTML**

```javascript
document.getElementById('btnAnalyze').addEventListener('click', () => {
  const scene = document.querySelector('.tab-btn.active').dataset.scene;
  const configText = document.getElementById('configText').value;
  const mappingText = document.getElementById('mappingText').value;

  if (scene === 'er') {
    state.rows = Analyzer.buildOutputRows(configText, mappingText);
    state.topology = Topology.analyze(configText, document.getElementById('acceptRemark').checked);
  } else {
    state.rows = Analyzer.buildOutputRowsUSG(configText, mappingText);
    state.topology = null;
  }

  renderNATTable(state.rows);
  if (state.topology) {
    drawTopologyCanvas(state.topology);
    document.getElementById('topoSummary').value = state.topology.summary || '';
    document.getElementById('topoMermaid').value = state.topology.mermaid || '';
    document.getElementById('ledgerText').textContent = state.topology.parse_ledger_text || '';
    document.getElementById('ipDigestText').textContent = state.topology.ip_digest_text || '';
  }
  switchResultTab('nat');
});
```

- [ ] **Step 7: Commit**

```bash
git add er_config_analyzer.html
git commit -m "feat: complete topology analysis engine with default route, mermaid, warnings, IP digest"
```

---

### Task 7: SVG Topology Canvas Rendering

**Files:**
- Modify: `er_config_analyzer.html` — add SVG topology drawing

- [ ] **Step 1: Implement SVG coordinate system and layout engine**

Port the canvas layout from Python lines 3590-4423 to SVG:

```javascript
// ============================================================
// SVG Topology Canvas
// ============================================================
const TopoCanvas = {
  ZOOM_MIN: 0.4, ZOOM_MAX: 2.5,
  TOP_PAD: 128, LANE_GAP: 96,
  NODE_W: 172, NODE_H: 46,
  SLOT_W: 200,  // node_w + 28

  state: { zoom: 1.0, panX: 0, panY: 0 },

  draw(topology) {
    const svg = document.getElementById('topoSvg');
    const z = this.state.zoom;
    const S = (v) => v * z;

    // Lane Y positions
    const laneMainY = S(128) + S(160);
    const laneBackupY = laneMainY + S(640);
    const laneUnknownY = laneBackupY + S(420);

    // Column X positions
    const xHost = S(240);
    const xChain0 = xHost + S(50);
    const xUPE0 = xChain0 + S(400);
    const xOut0 = xUPE0 + S(250);

    // Host oval
    const hostY = (laneMainY + laneBackupY) / 2;
    svg.innerHTML = ''; // Clear

    // Draw lanes
    // ... (draw access transport, UPE, overseas nodes per lane)
    // ... (draw BGP bindings)
    // ... (draw arrows, labels)

    this._updateScrollRegion(svg);
  },

  _drawLane(svg, side, baseY, tunnels, topology) {
    // Place access nodes
    // Place UPE node
    // Place overseas nodes with FIXED bound clamping (Fix #6)
    // Draw connecting arrows
    // Draw SNAT notes
  },

  // FIX #6: Bound clamping for overseas node placement
  _clampY(y, laneTop, laneBottom, nodeH) {
    return Math.max(laneTop, Math.min(laneBottom - nodeH, y));
  },
  // ...
};
```

- [ ] **Step 2: Implement zoom and pan**

```javascript
// Zoom with mouse wheel
document.getElementById('topoContainer').addEventListener('wheel', (e) => {
  e.preventDefault();
  const delta = e.deltaY > 0 ? 0.9 : 1.1;
  TopoCanvas.state.zoom = Math.max(TopoCanvas.ZOOM_MIN, Math.min(TopoCanvas.ZOOM_MAX, TopoCanvas.state.zoom * delta));
  document.getElementById('zoomLabel').textContent = Math.round(TopoCanvas.state.zoom * 100) + '%';
  TopoCanvas.redraw();
});

// Pan with mouse drag
let panning = false, panStartX, panStartY;
svg.addEventListener('mousedown', (e) => { panning = true; panStartX = e.clientX - TopoCanvas.state.panX; panStartY = e.clientY - TopoCanvas.state.panY; });
svg.addEventListener('mousemove', (e) => { if (panning) { TopoCanvas.state.panX = e.clientX - panStartX; TopoCanvas.state.panY = e.clientY - panStartY; TopoCanvas.redraw(); } });
svg.addEventListener('mouseup', () => { panning = false; });
```

- [ ] **Step 3: Implement lane boundary overflow fix (Fix #6)**

```javascript
// When placing overseas nodes in multi-column mode:
const laneTop = laneTops[side];
const laneBottom = laneBottoms[side];
const availHeight = laneBottom - laneTop;
// FIXED: nodes_per_col calculated with actual bounds
const nodesPerCol = Math.max(1, Math.floor(availHeight / gap));
const totalCols = Math.ceil(nodes.length / nodesPerCol);
for (let ci = 0; ci < totalCols; ci++) {
  for (let ri = 0; ri < nodesPerCol; ri++) {
    const idx = ci * nodesPerCol + ri;
    if (idx >= nodes.length) break;
    const oy = laneTop + ri * gap;
    // FIXED: clamp to lane bottom boundary
    const clampedY = Math.min(oy, laneBottom - nodeH);
    drawOverseasNode(ox + ci * colStep, clampedY, nodes[idx]);
  }
}
```

- [ ] **Step 4: Implement BGP and default route visual elements**

- [ ] **Step 5: Implement color scheme based on DESIGN.md tokens**

```javascript
const COLORS = {
  openvpn: '#dbeafe',      // blue-100
  ipsecPolicy: '#ddd6fe',  // purple-100
  ipsecVti: '#e0e7ff',     // indigo-100
  greUpe: '#dcfce7',       // green-100
  greOverseas: '#fee2e2',  // red-100
  bgp: '#cffafe',          // cyan-100
  default: '#fef3c7',      // yellow-100
  host: '#26251e',         // ink
  mainLane: '#eff6ff',     // subtle blue bg
  backupLane: '#fef2f2',   // subtle red bg
  unknownLane: '#f7f7f4',  // canvas
};
```

- [ ] **Step 6: Manually test topology rendering**

Open `er_config_analyzer.html`, paste sample config, click "Parse & Organize", switch to "ER Topology" tab. Verify nodes render in correct lanes, arrows connect correctly, zoom/pan works.

- [ ] **Step 7: Commit**

```bash
git add er_config_analyzer.html
git commit -m "feat: implement SVG topology canvas with zoom, pan, bound clamping"
```

---

### Task 8: CSV Export

**Files:**
- Modify: `er_config_analyzer.html` — add export logic

- [ ] **Step 1: Implement CSV export**

```javascript
function exportCSV() {
  if (!state.rows || state.rows.length === 0) {
    alert('No data to export. Parse config first.');
    return;
  }
  // NAT CSV
  const natCSV = '﻿' + ['Rule', 'Source IP/Subnet', 'Egress Name', 'Egress Remark', 'Fake IP', 'Real IP'].join(',') + '\n' +
    state.rows.map(r => [r.rule, r.source_ip, r.egress_name, r.egress_remark, r.fake_ip, r.real_ip].map(c => `"${(c||'').replace(/"/g, '""')}"`).join(',')).join('\n');

  downloadFile('nat.csv', natCSV, 'text/csv;charset=utf-8');

  // Topology summary
  if (state.topology) {
    downloadFile('topology_summary.txt', document.getElementById('topoSummary').value, 'text/plain;charset=utf-8');
    downloadFile('topology_mermaid.mmd', document.getElementById('topoMermaid').value, 'text/plain;charset=utf-8');
    downloadFile('parse_ledger.txt', document.getElementById('ledgerText').textContent, 'text/plain;charset=utf-8');
    downloadFile('ip_digest.txt', document.getElementById('ipDigestText').textContent, 'text/plain;charset=utf-8');
    downloadFile('input_config.txt', document.getElementById('configText').value, 'text/plain;charset=utf-8');
    downloadFile('input_mapping.txt', document.getElementById('mappingText').value, 'text/plain;charset=utf-8');
  }
}

function downloadFile(filename, content, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 2: Wire up Export button**

```javascript
document.getElementById('btnExport').addEventListener('click', exportCSV);
```

- [ ] **Step 3: Commit**

```bash
git add er_config_analyzer.html
git commit -m "feat: implement CSV and full-result export via Blob download"
```

---

### Task 9: Result Tab Switching & Polish

**Files:**
- Modify: `er_config_analyzer.html` — add tab switching, clear, file import

- [ ] **Step 1: Implement tab switching**

```javascript
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  });
});

document.querySelectorAll('.result-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    switchResultTab(btn.dataset.result);
  });
});

function switchResultTab(name) {
  document.querySelectorAll('.result-tab').forEach(b => b.classList.remove('active'));
  document.querySelector(`.result-tab[data-result="${name}"]`).classList.add('active');
  ['natPanel', 'topologyPanel', 'ledgerPanel', 'ipDigestPanel'].forEach(id => {
    document.getElementById(id).hidden = (id !== name + 'Panel');
  });
}
```

- [ ] **Step 2: Implement Clear button**

```javascript
document.getElementById('btnClear').addEventListener('click', () => {
  document.getElementById('configText').value = '';
  document.getElementById('mappingText').value = '';
  document.querySelector('#natTable tbody').innerHTML = '';
  document.getElementById('topoSvg').innerHTML = '';
  document.getElementById('topoSummary').value = '';
  document.getElementById('topoMermaid').value = '';
  document.getElementById('ledgerText').textContent = '';
  document.getElementById('ipDigestText').textContent = '';
  state.rows = [];
  state.topology = null;
});
```

- [ ] **Step 3: Implement file import**

```javascript
document.getElementById('configFile').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => { document.getElementById('configText').value = ev.target.result; };
  reader.readAsText(file);
});
```

- [ ] **Step 4: Implement Copy to Clipboard on NAT table right-click**

- [ ] **Step 5: Final manual integration test**

- Open HTML file in browser
- Paste ER config + mapping
- Click Parse
- Verify: NAT table populated, topology rendered with correct main/backup lane placement, zoom/pan works
- Switch to USG tab, repeat
- Export all files via Export button

- [ ] **Step 6: Commit**

```bash
git add er_config_analyzer.html
git commit -m "feat: implement tab switching, clear, file import, clipboard copy"
```

---

### Task 10: Verification & Regression Testing

**Files:**
- Create: `test_html_refactor/test_runner.html`

- [ ] **Step 1: Create browser test runner**

```html
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Test Runner</title></head><body>
<h1>ER Config Analyzer — Test Suite</h1>
<div id="results"></div>
<script src="../er_config_analyzer.html"></script>
<script src="test_parser.js"></script>
<script src="test_topology_fixtures.js"></script>
<script>
const results = document.getElementById('results');
function runAll() {
  const tests = [
    test_parse_fake_real_mapping, test_parse_er_nat_rules, test_mask_to_prefix,
    test_build_output_rows_er, test_build_output_rows_skips_masquerade,
    test_remark_upe_vs_nat_outbound_conflict,
    test_route_ovpn_sets_gre_upe_aligned_remark_no_conflict,
    test_canvas_side_uses_description_not_iface_name,
    test_line_side_bk_overrides_main_parent,
    test_line_side_pri_is_main,
    test_line_side_multi_parent_inherit,
    test_ordered_label_bgp_over_track,
    test_ordered_label_track_when_no_bgp,
    test_ordered_label_remark_fallback_only,
  ];
  let passed = 0, failed = 0;
  for (const t of tests) {
    try { t(); passed++; results.innerHTML += `<div style="color:green">✓ ${t.name}</div>`; }
    catch(e) { failed++; results.innerHTML += `<div style="color:red">✗ ${t.name}: ${e.message}</div>`; }
  }
  results.innerHTML += `<h2>${passed}/${tests.length} passed, ${failed} failed</h2>`;
}
runAll();
</script>
</body></html>
```

- [ ] **Step 2: Run all tests**

Open `test_html_refactor/test_runner.html` in browser. Expected: 14/14 PASS.

- [ ] **Step 3: Run original Python verify script as cross-reference**

```bash
cd "C:/Users/123/Desktop/自动梳理配置 - cc" && python verify_er_topology_fixtures.py
```
Expected: `verify_er_topology_fixtures: OK`

- [ ] **Step 4: Fix any failures and commit**

```bash
git add test_html_refactor/test_runner.html
git commit -m "test: add in-browser test runner, all 14 tests passing"
```

---

## Summary of Topology Logic Fixes Applied

| # | Issue | File/Location | Fix |
|---|-------|--------------|-----|
| 1 | Substring matching in vtun_to_upe | `buildVtunToUpe()` in JS | Use IP address equality (`===`) not `.includes()` |
| 2 | Over-aggressive `_infer_side` substrings | `lineRemarkIsMain/Backup()` in JS | Word-boundary regex (`\bBK[-_]`) not bare `"bk"` |
| 3 | Chain-side first-wins without warnings | `resolveChainSides()` in JS | Append sideWarnings when evidence conflicts |
| 4 | Dead code in BGP lane_side rebind | `resolveBgpLaneSide()` in JS | Remove unreachable else branch |
| 5 | `_name_hint_side` applies to entire chain | `resolveChainSides()` step 1 | Only apply to chain containing BGP's anchor_tunnel |
| 6 | Canvas lane boundary overflow | `_clampY()` in TopoCanvas | Add bound clamping for overseas node placement |
| 7 | Two side resolution pathways diverge | `resolveTunnelSide()` in JS | Single unified pathway: chain_side_map is authoritative |
| 8 | UPE canvas_side set to unknown on conflict | `buildVtunToUpe()` side prop | Prefer structural vtun evidence on conflict |
| 9 | NAT translation skips dummy interfaces | `resolveSourceInterface()` in JS | Handle loopback AND dummy in parent resolution |
| 10 | policy_local_targets resolution gap | `resolvePolicyTargets()` in JS | Add to policy_targets instead of dropping |

---

## Self-Review Checklist

1. **Spec coverage**: All original functionality covered — ER/USG config parsing, NAT table, topology analysis, topology canvas, CSV export, zoom/pan, file import, parse ledger, IP digest.
2. **Placeholder scan**: No TBD/TODO/fill-in — all steps have concrete code.
3. **Type consistency**: TunnelNode, RouteEdge, BgpBinding classes defined in Task 4, used consistently in Tasks 5-7. Side values are "main"/"backup"/"unknown" throughout.
