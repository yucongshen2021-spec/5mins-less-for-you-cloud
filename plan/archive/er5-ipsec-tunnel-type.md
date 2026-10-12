# ER 5.0 FastIP IPSec 隧道类型 — 实现计划

> Demo 版（main 分支）。测试通过后再同步 release。
> 只做 5.0 非香港出口的 IPSec 完整实现。HK 和 4.0 留占位符。

**Goal:** ER FastIP 5.0 添加 OpenVPN/IPSec 隧道类型切换，IPSec 使用不同的模板、数据头解析和 IPSec 参数动态读取。

**Architecture:** UI 在 hostname 上方加 radio 二选一（默认 OpenVPN）。后端 `build_epoch5_us_format_dict()` 根据 tunnel_type 分支：OpenVPN 走现有逻辑，IPSec 走新的 IPSec 模板和解析器。IPSec 参数从粘贴的数据头动态提取（IKE/IPsec proposal），提取不到时提示用户。

---

## Task 1: 前端 UI — 5.0 隧道类型切换

**Files:**
- Modify: `application/all_in_one - cc/web/templates/index.html`

在 5.0 hostname 上方加 radio 按钮组：

```html
<!-- 隧道类型（仅 5.0 可见） -->
<div class="fg er5-only" id="epoch-fastip5-tunnel-type-row" style="display:none">
  <label class="fl">隧道类型</label>
  <div class="tunnel-type-group">
    <label class="tunnel-radio active" id="tunnel-openvpn-label">
      <input type="radio" name="epoch-fastip5-tunnel-type" value="openvpn" checked onchange="onTunnelTypeChange()"> OpenVPN
    </label>
    <label class="tunnel-radio" id="tunnel-ipsec-label">
      <input type="radio" name="epoch-fastip5-tunnel-type" value="ipsec" onchange="onTunnelTypeChange()"> IPSec
    </label>
  </div>
</div>
```

JS: `onTunnelTypeChange()` 切换时更新当前 variant 的提示和参数面板可见性。
`switchERVersion('5')` 中显示该行，`switchERVersion('4')` 中隐藏。

---

## Task 2: 后端 — IPSec 模板

**Files:**
- Modify: `application/all_in_one - cc/src/er_fastip_5in1_v1.py`

新增 `TEMPLATE_EPOCH5_US_IPSEC` 模板，隧道部分用 `vpn ipsec` + GRE 替代 `interfaces openvpn`：

```python
TEMPLATE_EPOCH5_US_IPSEC = """\
# Epoch 5.0 非香港出口配置 (IPSec)  Hostname: {hostname}
# ═══════════════════════════════════════════════════
...
"""
```

模板内容基于用户提供的 VyOS 配置文件（`er 5.0 非香港 ipsec.txt`），包含：
- IKE group 定义
- ESP group 定义  
- IPSec site-to-site peer (main/backup)
- GRE tunnel interfaces（保持 GRE，与 IPSec 独立）
- 其余配置（BGP、NAT、firewall 等）与 OpenVPN 版相同

---

## Task 3: 后端 — IPSec 数据头解析器

**Files:**
- Modify: `application/all_in_one - cc/src/er_fastip_5in1_v1.py`

新增 `build_epoch5_us_ipsec_format_dict(hdr_text)`：

从数据头中提取：
- 基本字段（LineID, PE, Tunnel, wanip, docking 等）— 与 OpenVPN 相同
- IPSec 特有字段：
  - `dial_pe`, `dial_ip`, `loop_ip`, `secret`
  - IKE 参数：`key_exchange`, `dh_group`, `encryption`, `hash`, `prf`, `dead_peer_detection`
  - IPsec proposal 参数：`encryption`, `hash`

```python
def _parse_ipsec_params(hdr_text):
    """从数据头提取 IKE/IPSec proposal 参数。提取不到返回空 dict 并设置警告。"""
    params = {}
    # 解析 --- IKE (ike-peer IPSEC) --- 块
    # 解析 --- IPsec proposal (IPSEC) --- 块
    if not params:
        params['_ipsec_warning'] = '未检测到IKE/IPSec参数，将使用默认值生成，请自行检查。'
    return params
```

---

## Task 4: 后端 — 隧道类型路由

**Files:**
- Modify: `application/all_in_one - cc/src/er_fastip_5in1_v1.py`

修改 `build_epoch5_us_format_dict()` 接受 `tunnel_type` 参数：

```python
def build_epoch5_us_format_dict(hdr_text, tunnel_type='openvpn'):
    if tunnel_type == 'ipsec':
        return build_epoch5_us_ipsec_format_dict(hdr_text)
    # 原有 OpenVPN 逻辑
    ...
```

---

## Task 5: Web API — 传递 tunnel_type

**Files:**
- Modify: `application/all_in_one - cc/web/app.py`

在 `/api/generate/er_fastip_5in1` 端点接收 `tunnel_type` 参数并传递给 `build_epoch5_us_format_dict()`。

---

## Task 6: IPSec 占位符

为以下场景留占位符（模板 + mapping + 数据头都标记"正在开发中"）：
1. ER 5.0 HK IPSec
2. ER 4.0 HK IPSec  
3. ER 4.0 非HK IPSec

创建 editor_defaults 目录和 placeholder 文件。

---

## Task 7: 测试

**Files:**
- Create: `application/test/all_in_one/test_er5_ipsec.py`

测试：
1. OpenVPN 模式生成与现有行为一致
2. IPSec 模式生成包含 vpn ipsec 配置块
3. 无 IPSec 参数时返回警告
4. 有 IPSec 参数时正确提取并填入模板

---

## Task 8: 全量回归测试

```bash
cd application/test
py -3 -m pytest --deselect all_in_one/test_e2e_playwright.py -q
```
预期：所有现有 50 个测试通过 + 新增 IPSec 测试通过
