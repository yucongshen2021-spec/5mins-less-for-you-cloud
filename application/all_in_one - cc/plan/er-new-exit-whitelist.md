# ER FastIP 新增出口 — 添加 FNET Whitelist + 支持单线输入

## Context

当前 ER FastIP「新增出口」有两个问题：
1. 缺少 whitelist（FNET）探活机制（域名分流已有）
2. **必须同时输入主/备两条线**，只输入一条主线会报错

本次修改同时解决这两个问题：
- 模仿域名分流的 FNET whitelist（firewall network-group + NAT rule + static route + track）
- **允许用户只输入一条主线数据**（单 LineID block），此时不生成备线配置、不生成 whitelist

## 设计要点

### A. 单线 vs 双线输入

| 输入 | 行为 |
|---|---|
| **单线**（1 个奇数 LineID block） | 只生成主线 tunnel + static route + dum，**不生成备线、不生成 FNET whitelist** |
| **双线**（1 奇数 + 1 偶数 LineID block） | 完整生成主/备 tunnel + static route + dum + NAT + FNET whitelist（三元组填写时） |

单线输入的预期输出示例：
```
set interfaces tunnel tun1083 address '10.22.86.198/30'
set interfaces tunnel tun1083 description 'main-tyo2-natpe4'
set interfaces tunnel tun1083 encapsulation 'gre'
set interfaces tunnel tun1083 firewall local name 'WAN2LOCAL'
set interfaces tunnel tun1083 mtu '1400'
set interfaces tunnel tun1083 multicast 'disable'
set interfaces tunnel tun1083 parameters ip ttl '255'
set interfaces tunnel tun1083 remote '192.168.205.67'
set interfaces tunnel tun1083 source-address '10.22.242.21'

set protocols static route 192.168.205.67/32 next-hop 192.168.1.1
set interface dummy dum300 address   10.60.21.185/32
set interface dummy dum300 description main-outip-10.60.21.185-103.57.50.44
set interface dummy dum301 address   10.60.21.186/32
set interface dummy dum301 description main-outip-10.60.21.186-103.57.50.45
```

### B. FNET Whitelist（仅双线时生效）

#### 新增初始化参数（3 个）

| 参数名 | 默认值 | 说明 |
|---|---|---|
| `ER_NE_FNET_PROBE_DEFAULT` | `"100.100.100.1"` | 100.100 探测 IP |
| `ER_NE_FNET_EXIT_TUNNEL_DEFAULT` | `""` | NAT 出口 tunnel（openvpn 名） |
| `ER_NE_FNET_NAT_RULE_DEFAULT` | `""` | NAT rule 号 |

Track 名称固定为 `tooutbound1`，不可配置。

#### 三元组约束（模仿域名分流）

probe IP、NAT tunnel、NAT rule **三项必须同填或同空**，否则报错。
**仅双线时生效**，单线时忽略 whitelist 参数。

#### 自动推导（从数据头解析）

- **NAT translation address**（主线 IP）→ 主线第一条海外出口左 IP
- **静态路由 next-hop** → `ER_NE_MAIN_PE_NH_DEFAULT`

#### 生成的配置块（`{ER_NE_FNET_BLOCK}`）

```
set firewall group network-group GROUP-FNET-Whitelist network 100.100.100.0/24

set nat source rule {nat_rule} destination address {probe_ip}/32
set nat source rule {nat_rule} outbound-interface '{exit_tunnel}'
set nat source rule {nat_rule} translation address '{first_overseas_left_ip}'

set protocols static route {probe_ip}/32 next-hop {main_pe_nh}

set track name tooutbound1 failure-count '5'
set track name tooutbound1 success-count '5'
set track name tooutbound1 test 10 resp-time '5'
set track name tooutbound1 test 10 target '{probe_ip}'
set track name tooutbound1 test 10 ttl-limit '1'
set track name tooutbound1 test 10 type 'ping'
```

### C. 模板重构 — 备线块化

将 `TEMPLATE_ER_NEW_EXIT_VISUAL` 的备线部分抽取为 `{ER_NE_BK_BLOCK}`，单线时为空字符串。

**旧模板：**
```
{main tunnel section}
{main dum block}

{backup tunnel section}    ← 直接内联，单线时 {backup_tun} 等占位符无值
{backup dum block}
{NAT blocks}
```

**新模板：**
```
{main tunnel section}
{ER_NE_MAIN_DUM_BLOCK}

{ER_NE_BK_BLOCK}           ← 整个备线块（双线时 = 备线 tunnel + static route + dum；单线时 = ""）
{ER_NE_NAT_HEADER_BLOCK}{ER_NE_NAT_BLOCK}{ER_NE_FNET_BLOCK}
```

---

## 修改清单

### 1. `src/er_fastip_2in1_v8.py` — 核心逻辑

#### 1.1 新增常量（在 `ER_NEW_EXIT_EXAMPLE` 之后，约 line 2201）

```python
# ── ER 新增出口 FNET Whitelist（track 100.100 / NAT 探测段；三项须同填或同空；仅双线时生效）──
ER_NE_FNET_PROBE_DEFAULT = "100.100.100.1"
ER_NE_FNET_EXIT_TUNNEL_DEFAULT = ""
ER_NE_FNET_NAT_RULE_DEFAULT = ""
```

复用 `_ER_DS_FNET_NETGROUP = "GROUP-FNET-Whitelist"` 和 `_ER_DS_FNET_NET = "100.100.100.0/24"`。

#### 1.2 修改 `parse_er_new_exit_blocks` — 允许单线

当前逻辑要求 `"main" in parsed and "bk" in parsed`，修改为：
- 如果只有 1 个 block（奇数 LineID）→ `parsed["main"]` 有值，`parsed["bk"]` 不存在
- 如果有 2 个 block → 现有行为不变
- 如果只有 1 个 block（偶数 LineID）→ 作为 bk，但仍然需要 main（报错）
- 返回值改为 `(parsed, err)` — err 仅在完全无法解析时报错，单线不报错

#### 1.3 重构 `TEMPLATE_ER_NEW_EXIT_VISUAL`

```python
TEMPLATE_ER_NEW_EXIT_VISUAL = """\
set interfaces tunnel {main_tun} address '{main_tun_addr}'
set interfaces tunnel {main_tun} description 'main-{main_pe}'
set interfaces tunnel {main_tun} encapsulation 'gre'
set interfaces tunnel {main_tun} firewall local name 'WAN2LOCAL'
set interfaces tunnel {main_tun} mtu '1400'
set interfaces tunnel {main_tun} multicast 'disable'
set interfaces tunnel {main_tun} parameters ip ttl '255'
set interfaces tunnel {main_tun} remote '{main_pe_docking}'
set interfaces tunnel {main_tun} source-address '{main_ce_docking}'

set protocols static route {main_pe_docking}/32 next-hop {ER_NE_MAIN_PE_NH_DEFAULT}
{ER_NE_MAIN_DUM_BLOCK}
{ER_NE_BK_BLOCK}{ER_NE_NAT_HEADER_BLOCK}{ER_NE_NAT_BLOCK}{ER_NE_FNET_BLOCK}"""
```

#### 1.4 新增 `_build_er_ne_fnet_block` 函数（在 `build_er_new_exit_nat_block` 之后）

```python
def _build_er_ne_fnet_block(parsed: dict, init_cfg: dict) -> str:
    """生成 FNET whitelist 块。仅双线 + 三元组齐全时生成。"""
    # 仅双线
    if "bk" not in parsed or not parsed.get("bk"):
        return ""
    probe = str(init_cfg.get("fnet_probe", "")).strip()
    tunnel = str(init_cfg.get("fnet_exit_tunnel", "")).strip()
    nat_rule = str(init_cfg.get("fnet_nat_rule", "")).strip()
    f_filled = (bool(probe), bool(tunnel), bool(nat_rule))
    if not any(f_filled):
        return ""
    if not all(f_filled):
        return ""  # 调用方应提前校验报错
    m = parsed.get("main") or {}
    pairs = list(m.get("oversea_pairs") or [])
    if not pairs:
        return ""
    trans_ip = (pairs[0][0] or "").strip()
    if not trans_ip:
        return ""
    main_nh = str(init_cfg.get("main_pe_next_hop", "")).strip()
    track_name = "tooutbound1"
    lines = [
        "",
        f"set firewall group network-group {_ER_DS_FNET_NETGROUP} network {_ER_DS_FNET_NET}",
        "",
        f"set nat source rule {nat_rule} destination address {probe}/32",
        f"set nat source rule {nat_rule} outbound-interface '{tunnel}'",
        f"set nat source rule {nat_rule} translation address '{trans_ip}'",
        "",
        f"set protocols static route {probe}/32 next-hop {main_nh}",
        "",
        f"set track name {track_name} failure-count '5'",
        f"set track name {track_name} success-count '5'",
        f"set track name {track_name} test 10 resp-time '5'",
        f"set track name {track_name} test 10 target '{probe}'",
        f"set track name {track_name} test 10 ttl-limit '1'",
        f"set track name {track_name} test 10 type 'ping'",
        "",
    ]
    return "\n".join(lines)
```

#### 1.5 修改 `_build_er_new_exit_format_dict`

```python
def _build_er_new_exit_format_dict(parsed, init_cfg) -> dict:
    def _dum_block(key: str, prefix: str, start_key: str) -> str:
        item = parsed.get(key)
        if not item:
            return ""
        dum_id = int(init_cfg[start_key])
        out = []
        for left_ip, right_ip in item.get("oversea_pairs", []):
            out.append(f"set interface dummy dum{dum_id} address   {left_ip}/32")
            out.append(f"set interface dummy dum{dum_id} description {prefix}-outip-{left_ip}-{right_ip}")
            dum_id += 1
        return "\n".join(out)

    m = parsed.get("main") or {}
    b = parsed.get("bk")  # None for single line

    # 备线块：双线时生成完整备线配置，单线时为空
    bk_block = ""
    if b:
        bk_lines = [
            f"set interfaces tunnel {b['tun']} address '{b['tun_addr']}'",
            f"set interfaces tunnel {b['tun']} description 'backup-{b['pe']}'",
            f"set interfaces tunnel {b['tun']} encapsulation 'gre'",
            f"set interfaces tunnel {b['tun']} firewall local name 'WAN2LOCAL'",
            f"set interfaces tunnel {b['tun']} mtu '1400'",
            f"set interfaces tunnel {b['tun']} multicast 'disable'",
            f"set interfaces tunnel {b['tun']} parameters ip ttl '255'",
            f"set interfaces tunnel {b['tun']} remote '{b['pe_docking']}'",
            f"set interfaces tunnel {b['tun']} source-address '{b['ce_docking']}'",
            "",
            f"set protocols static route {b['pe_docking']}/32 next-hop {init_cfg.get('bk_pe_next_hop', '')}",
            _dum_block("bk", "backup", "bk_dum_start"),
        ]
        bk_block = "\n".join(bk_lines)

    # NAT blocks — 仅双线时生成（单线时 nat_source_cidr 为空，现有函数返回空）
    nat_hdr = build_er_new_exit_nat_header_block(parsed, init_cfg) if b else ""
    nat_blk = build_er_new_exit_nat_block(parsed, init_cfg) if b else ""

    d = {
        "main_tun": m.get("tun", ""),
        "main_tun_addr": m.get("tun_addr", ""),
        "main_pe": m.get("pe", ""),
        "main_pe_docking": m.get("pe_docking", ""),
        "main_ce_docking": m.get("ce_docking", ""),
        "ER_NE_MAIN_PE_NH_DEFAULT": init_cfg.get("main_pe_next_hop", ""),
        "ER_NE_MAIN_DUM_BLOCK": _dum_block("main", "main", "main_dum_start"),
        "ER_NE_BK_BLOCK": bk_block,
        "ER_NE_NAT_HEADER_BLOCK": nat_hdr,
        "ER_NE_NAT_BLOCK": nat_blk,
        "ER_NE_FNET_BLOCK": _build_er_ne_fnet_block(parsed, init_cfg),
        "ER_NE_MAIN_NAT_RULE_DEFAULT": str(init_cfg.get("main_nat_rule", "")).strip(),
        "ER_NE_BK_NAT_RULE_DEFAULT": str(init_cfg.get("bk_nat_rule", "")).strip(),
        "ER_NE_NAT_SOURCE_CIDR_DEFAULT": str(init_cfg.get("nat_source_cidr", "")).strip(),
        # 透传新 whitelist 参数
        "ER_NE_FNET_PROBE_DEFAULT": str(init_cfg.get("fnet_probe", "")).strip(),
        "ER_NE_FNET_EXIT_TUNNEL_DEFAULT": str(init_cfg.get("fnet_exit_tunnel", "")).strip(),
        "ER_NE_FNET_NAT_RULE_DEFAULT": str(init_cfg.get("fnet_nat_rule", "")).strip(),
    }
    return d
```

#### 1.6 修改 `build_er_new_exit_config`（fallback builder）

单线时只遍历 `("main", "main")`，跳过后面的 `("bk", "backup")`：

```python
def build_er_new_exit_config(parsed, init_cfg):
    lines = []
    has_bk = "bk" in parsed and parsed.get("bk")
    items = [("main", "main", "main_pe_next_hop", "main_dum_start")]
    if has_bk:
        items.append(("bk", "backup", "bk_pe_next_hop", "bk_dum_start"))
    for key, prefix, next_hop_key, dum_start_key in items:
        item = parsed[key]
        lines.extend([...])  # 现有逻辑不变
        ...
    # NAT blocks（仅双线）
    if has_bk:
        nat_hdr = build_er_new_exit_nat_header_block(parsed, init_cfg)
        nat_blk = build_er_new_exit_nat_block(parsed, init_cfg)
        ...
    # FNET block（仅双线）
    fnet_blk = _build_er_ne_fnet_block(parsed, init_cfg)
    if fnet_blk.strip():
        lines.append(fnet_blk.rstrip())
    return "\n".join(lines).strip() + "\n"
```

#### 1.7 桌面 UI：新增 3 个 Entry widget

在 `er_fl_new_exit_body` frame 中添加：
- `er_fl_ne_fnet_probe` — 100.100 探测 IP
- `er_fl_ne_fnet_tunnel` — NAT 出口 tunnel
- `er_fl_ne_fnet_nat_rule` — NAT rule 号

更新 `er_fl_generate_new_exit`：读取 widget 值 + 三元组校验（仅双线时触发校验）。
更新 `_visual_merge_er_init` 的 `"new_exit"` 分支。

#### 1.8 单线时 `er_new_exit_nat_rule_span_error` 跳过

NAT rule 区间校验仅在双线时进行。

---

### 2. `src/all_in_one_v2.py` — 编排层

#### 2.1 `_INIT_MAP_ER_NEW_EXIT` 追加 3 行

```
ER_NE_FNET_PROBE_DEFAULT  新增出口初始化默认：100.100 探测 IP
ER_NE_FNET_EXIT_TUNNEL_DEFAULT  新增出口初始化默认：NAT 出口 tunnel（可空）
ER_NE_FNET_NAT_RULE_DEFAULT  新增出口初始化默认：NAT rule 号（可空）
```

#### 2.2 `_INIT_PLACEHOLDER_FIELDS[ER_INIT_MOD_NEW_EXIT]` 追加

```python
("ER_NE_FNET_PROBE_DEFAULT", "100.100 探测 IP"),
("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "NAT 出口 tunnel(可空)"),
("ER_NE_FNET_NAT_RULE_DEFAULT", "NAT rule 号(可空)"),
```

#### 2.3 表单行布局追加

```python
["ER_NE_FNET_PROBE_DEFAULT", "ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "ER_NE_FNET_NAT_RULE_DEFAULT"],
```

#### 2.4 `_seed` 追加

```python
"ER_NE_FNET_PROBE_DEFAULT": "100.100.100.1",
"ER_NE_FNET_EXIT_TUNNEL_DEFAULT": "",
"ER_NE_FNET_NAT_RULE_DEFAULT": "",
```

#### 2.5 `_INIT_ENTRY_ALLOW_EMPTY` 新增 `ER_INIT_MOD_NEW_EXIT` 条目

```python
ER_INIT_MOD_NEW_EXIT: frozenset({
    "ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "ER_NE_FNET_NAT_RULE_DEFAULT",
}),
```

#### 2.6 `_ER_NEW_EXIT_MAP` 追加

```
ER_NE_BK_BLOCK  备线完整块（双线时 = 备线 tunnel + static route + dum；单线时为空）
ER_NE_FNET_BLOCK  FNET whitelist 块（防火墙 network-group + NAT rule + 静态路由 + track；仅双线+三元组齐全时生成）
ER_NE_FNET_PROBE_DEFAULT  新增出口初始化默认：100.100 探测 IP
ER_NE_FNET_EXIT_TUNNEL_DEFAULT  新增出口初始化默认：NAT 出口 tunnel
ER_NE_FNET_NAT_RULE_DEFAULT  新增出口初始化默认：NAT rule 号
```

#### 2.7 预览逻辑 — 处理单线情况

在 `parser_name == "parse_er_new_exit_blocks"` 分支中：
- `err` 仅在完全无法解析时报错，单线不报错
- 备线相关字段仅在 `"bk" in parsed` 时填充，否则为空字符串
- FNET block 调用 `_build_er_ne_fnet_block`（内部判断单线返回空）

#### 2.8 正式生成 — 更新 `init_cfg`

```python
init_cfg = {
    ...
    "fnet_probe": str(ns.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")),
    "fnet_exit_tunnel": str(ns.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")),
    "fnet_nat_rule": str(ns.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")),
}
```

---

### 3. `web/app.py` — Web 后端

#### 3.1 new_exit handler — 单线不报错

当前逻辑：
```python
parsed, err = parse_fn(hdr_text)
if err:
    return jsonify({"ok": False, "error": ...}), 400
```

修改为：单线时 `err` 为 None（或仅在完全无有效 block 时报错）。

#### 3.2 new_exit handler — init_cfg 添加 whitelist 参数

```python
fnet_probe = network.get("ER_NE_FNET_PROBE_DEFAULT") or er.get("ER_NE_FNET_PROBE_DEFAULT", "100.100.100.1")
fnet_tunnel = network.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT") or er.get("ER_NE_FNET_EXIT_TUNNEL_DEFAULT", "")
fnet_nat_rule = network.get("ER_NE_FNET_NAT_RULE_DEFAULT") or er.get("ER_NE_FNET_NAT_RULE_DEFAULT", "")

init_cfg = {
    ...
    "fnet_probe": str(fnet_probe),
    "fnet_exit_tunnel": str(fnet_tunnel),
    "fnet_nat_rule": str(fnet_nat_rule),
}
```

三元组校验：仅在双线时（`"bk" in parsed`）校验，单线时跳过。

#### 3.3 `_inject_variant_init` — new_exit 分支追加

```python
for k in ("ER_NE_FNET_PROBE_DEFAULT", "ER_NE_FNET_EXIT_TUNNEL_DEFAULT",
          "ER_NE_FNET_NAT_RULE_DEFAULT"):
    v = network.get(k, ns.get(k, ""))
    if v:
        d[k] = str(v)
```

---

### 4. `web/templates/index.html` — 前端

#### 4.1 表单 HTML（`#er-panel-new_exit`）

NAT 源网段 CIDR 行之后追加：

```html
<div class="fr2"><div class="fg"><label class="fl">100.100 探测 IP</label><input class="fi" id="epoch-fastip-ne-fnet-probe" value="100.100.100.1"></div><div class="fg"><label class="fl">NAT 出口 Tunnel（可空）</label><input class="fi" id="epoch-fastip-ne-fnet-tunnel" placeholder="可空"></div></div>
<div class="fg"><label class="fl">NAT Rule 号（可空）</label><input class="fi" id="epoch-fastip-ne-fnet-nat-rule" placeholder="可空"></div>
```

#### 4.2 `gn()` 函数

```javascript
ER_NE_FNET_PROBE_DEFAULT: g('ne-fnet-probe')?.value||'',
ER_NE_FNET_EXIT_TUNNEL_DEFAULT: g('ne-fnet-tunnel')?.value||'',
ER_NE_FNET_NAT_RULE_DEFAULT: g('ne-fnet-nat-rule')?.value||'',
```

---

### 5. 跨场景一致性检查（Rule 1）

- [ ] USG FastIP 新增出口是否需要同步支持单线输入？
- [ ] USG FastIP 新增出口是否需要 FNET whitelist？
  - 当前需求仅针对 ER FastIP，修改完成后确认 USG 侧是否需要对齐。

---

## 验证方案

### 单线输入（新功能）
1. 选择「Epoch FastIP · ER 新增出口」
2. 粘贴**单条** LineID block（奇数尾号）
3. 点击生成 → 验证只输出主线 tunnel + static route + dum，**无备线、无 whitelist**
4. 验证不报错

### 双线 + whitelist（新功能）
5. 粘贴两条 LineID block
6. 填写 whitelist 三元组（probe IP、tunnel、NAT rule）
7. 点击生成 → 验证输出含完整 FNET block（firewall group + NAT + static route + track `tooutbound1`）
8. 三元组部分填写 → 验证错误提示
9. 三元组全空 → 验证不生成 FNET block（但正常生成主/备配置）

### 回归
10. 双线 + 不填 whitelist → 输出应与修改前一致
11. 运行 `python test/run_all.py`
12. 验证 HK/US/flink/domain_split 不受影响

### 运维
13. 修改 .py 后重启 Flask（`debug=False` 无热重载）
