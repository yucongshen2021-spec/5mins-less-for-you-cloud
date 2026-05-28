#!/usr/bin/env python3
"""模板系统全面审计 — 模拟真实用户操作流程

检测项：
1. 保存自定义模板 → 生成使用自定义模板
2. 重启服务 → 自定义模板持久化
3. 重置模板 → 恢复出厂模板
4. 跨场景隔离（修改 A 不影响 B）
5. 所有 20 个场景的模板加载
"""
import sys, os, json, time, subprocess, uuid
os.environ["TEST_MODE"] = "1"
import _bootstrap  # noqa: F401
from app import app, _load_module, _SCENARIO_LIST

PASS = FAIL = 0
MARKER = f"AUDIT_{uuid.uuid4().hex[:8]}"

def t(name, ok):
    global PASS, FAIL
    if ok:
        PASS += 1; print(f"  [PASS] {name}")
    else:
        FAIL += 1; print(f"  [FAIL] {name}")

c = app.test_client()

# ══════════════════════════════════════════════════════
# 测试数据
# ══════════════════════════════════════════════════════
ER_HK_HDR = "hostname:TEST-CE\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\nwanip:10.22.98.40/30\n对接IP:10.255.110.6\nLineID:609157A2\nPE:szd-ape3\ntunnel:vtun1214\nwanip:10.22.98.44/30\n对接IP:10.255.110.10"
ER_US_HDR = "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\nPE 对接:192.168.247.17\n海外出口ip:\n10.60.44.28-218.32.88.83\n\nLineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\nPE Docking:192.168.239.12\nBGPSERVER IP:103.252.19.25,43.229.117.226\n海外出口ip:\n10.60.44.28-218.32.88.83"
USG_US_HDR = "main IPSEC_PE: szd-ape2\nmain dial_ip: 121.14.82.235\nmain loopback: 10.18.12.57\nmain auth_id: 609157A1\nLineID:609157A1\nPE:lax1-fgpe1\nWANIP:10.22.98.40/30\nTUNNEL:tun1213\nPE对接:10.255.110.6\n出口ip:64.81.158.21"
MPLS_HDR = "LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\nPE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\nLineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\nPE 对接:192.168.253.80\nPE AS号:65531"
AR_HDR = "LineID:604604Hw1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1147\nwanip:10.40.232.248/30\nPE 对接:10.200.200.76\nCE 对接:10.50.131.16\n拨号PE:gzd-upe5\n对接IP:10.200.200.76\nLoopIP:10.50.131.16\n拨号ip:183.63.68.174\n秘钥:both-win\n\nLineID:604604Hw2\nPE:szd-upebk1\nTunnel:Tunnel0/0/1605\nwanip:10.30.115.252/30\nPE 对接:10.200.200.22\nCE 对接:10.120.47.20\n拨号PE:szd-upebk1\n对接IP:10.200.200.22\nLoopIP:10.120.47.20\n拨号ip:183.56.163.24\n秘钥:both-win"

# scenarios that support template-driven generation
TEMPLATE_SCENARIOS = [
    # (scenario_key, variant, tool, header, check_in_output_key)
    ("Epoch FastIP · HK 香港出口", "hk", "epoch_fastip", ER_HK_HDR, "output"),
    ("Epoch FastIP · 非香港出口", "us", "epoch_fastip", ER_US_HDR, "output"),
    ("Epoch FastIP · ER 飞连", "flink", "epoch_fastip", "PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.1.0/29", "output"),
    ("Epoch FastIP · ER 新增出口", "new_exit", "epoch_fastip", "LineID:609353B7\nPE： tyo2-natpe4\nWANIP: 10.22.86.196/30\nTUNNEL: tun1083\nPE Docking：192.168.205.67\nCE Docking：: 10.22.242.21\nBGPSERVER IP：103.252.19.25,43.229.117.226\n海外出口ip：\n10.60.21.185-103.57.50.44\n\nLineID:609353B8\nPE： tyo4-natpe2\nWANIP: 10.22.100.120/30\nTUNNEL: tun1033\nPE Docking：10.33.54.78\nCE Docking：: 10.22.242.21\nBGPSERVER IP：103.252.19.99,43.229.119.251\n海外出口ip：\n10.60.21.186-103.57.50.45", "output"),
    ("Epoch FastIP · ER 域名分流", "domain_split", "epoch_fastip", "google.com\nyoutube.com", "output"),
    ("USG FastIP · 新增出口", "new_exit", "usg_fastip", "LineID:609424A1\nPE： lax1-fgpe1\nWANIP: 10.22.110.24/30\nTUNNEL: tun1248\nPE对接：10.255.110.6\nCE对接：10.18.16.20\n出口ip：\n10.61.10.78-64.81.20.174\n10.61.10.106-64.81.20.178\nLineID:609424A2\nPE： sjc1-fgpe2\nWANIP: 10.22.106.20/30\nTUNNEL: tun1229\nPE对接：10.255.111.158\nCE对接：10.18.14.127\n出口ip：\n10.60.76.6-172.16.23.8\n10.60.76.14-172.16.23.9", "output"),
    ("USG FastIP · 非香港出口", "us", "usg_fastip", USG_US_HDR, "output"),
    ("USG FastIP · HK 香港出口", "hk", "usg_fastip", USG_US_HDR, "output"),
    ("USG FastIP · 飞连", "flink", "usg_fastip", USG_US_HDR, "output"),
    ("Epoch MPLS · 国内配置", "domestic", "epoch_mpls", MPLS_HDR, "output"),
    ("Epoch MPLS · 海外配置", "overseas", "epoch_mpls", MPLS_HDR, "output"),
    ("Epoch MPLS · IPSec", "ipsec", "epoch_mpls", MPLS_HDR, "output"),
    ("AR SD-WAN · 单机单WAN · OPS", "single_ops", "ar_sdwan", AR_HDR, "ops_output"),
    ("AR SD-WAN · 单机单WAN · Factory", "single_factory", "ar_sdwan", AR_HDR, "factory_output"),
]

CUSTOM_TPL = f"# {MARKER}\n# 自定义模板 - 审计测试\nset system host-name AUDIT-{MARKER}\n"

print("=" * 60)
print("模板系统全面审计")
print(f"标记: {MARKER}")
print("=" * 60)

# ═══ Phase 1: 每个场景的 save → generate → reset → generate 循环 ═══
print("\n" + "=" * 60)
print("Phase 1: 单场景模板生命周期 (save → gen → reset → gen)")
print("=" * 60)

for key, variant, tool, hdr, output_key in TEMPLATE_SCENARIOS:
    short = key[:40]

    # 1. Save custom template
    r = c.post('/api/template/save', json={
        'key': key, 'header': hdr, 'mapping': '', 'template': CUSTOM_TPL
    }).get_json()
    t(f"{short} 保存", r.get("ok"))

    # 2. Generate — must contain custom marker
    r = c.post(f"/api/generate/{tool}", json={
        "variant": variant, "header_text": hdr, "network": {}
    }).get_json()
    gen_output = r.get(output_key, "") or r.get("output", "")
    t(f"{short} 生成含标记", MARKER in gen_output)

    # 3. Reset template
    r = c.post('/api/template/reset', json={'key': key}).get_json()
    t(f"{short} 重置", r.get("ok") and len(r.get("template", "")) > 50)

    # 4. Generate after reset — must NOT contain custom marker
    r = c.post(f"/api/generate/{tool}", json={
        "variant": variant, "header_text": hdr, "network": {}
    }).get_json()
    gen_after = r.get(output_key, "") or r.get("output", "")
    t(f"{short} 重置后不含标记", MARKER not in gen_after)

# ═══ Phase 2: 跨场景隔离 ═══
print("\n" + "=" * 60)
print("Phase 2: 跨场景隔离（修改 A 不影响 B）")
print("=" * 60)

# Save custom template for HK only
r = c.post('/api/template/save', json={
    'key': 'Epoch FastIP · HK 香港出口', 'header': ER_HK_HDR,
    'mapping': '', 'template': CUSTOM_TPL
}).get_json()
t("隔离-保存HK自定义", r.get("ok"))

# HK should have custom marker
r = c.post("/api/generate/epoch_fastip", json={
    "variant": "hk", "header_text": ER_HK_HDR, "network": {}
}).get_json()
t("隔离-HK含标记", MARKER in r.get("output", ""))

# US should NOT have custom marker (different template slot)
r = c.post("/api/generate/epoch_fastip", json={
    "variant": "us", "header_text": ER_US_HDR, "network": {}
}).get_json()
t("隔离-US不含标记", MARKER not in r.get("output", ""))

# Reset HK
c.post('/api/template/reset', json={'key': 'Epoch FastIP · HK 香港出口'})

# ═══ Phase 3: 持久化测试 ═══
print("\n" + "=" * 60)
print("Phase 3: 持久化（save → verify in new test_client → reset）")
print("=" * 60)

PERSIST_KEY = "Epoch MPLS · 国内配置"
PERSIST_MARKER = f"PERSIST_{MARKER}"
PERSIST_TPL = f"# {PERSIST_MARKER}\nset system host-name PERSIST-TEST\n"

# Save via test_client
r = c.post('/api/template/save', json={
    'key': PERSIST_KEY, 'header': MPLS_HDR, 'mapping': '',
    'template': PERSIST_TPL
}).get_json()
t("持久化-保存", r.get("ok"))

# Verify in same session
r = c.post("/api/generate/epoch_mpls", json={
    "variant": "domestic", "header_text": MPLS_HDR, "network": {}
}).get_json()
t("持久化-当前会话含标记", PERSIST_MARKER in r.get("output", ""))

# Create a NEW test_client (simulating new request after restart)
# Clear module cache and reload workspace templates
from app import _EMBEDDED_NS, _load_workspace_templates
_EMBEDDED_NS.clear()  # Simulate restart by clearing module cache
_load_workspace_templates()  # Re-apply workspace overrides

c2 = app.test_client()
# Verify workspace file exists and namespace is updated
from app import _load_module
ns = _load_module("er_mpls_v1.py")
tpl_val = ns.get("TEMPLATE_MPLS_DOMESTIC", "")
t("持久化-命名空间含模板", PERSIST_MARKER in str(tpl_val))
r = c2.post("/api/generate/epoch_mpls", json={
    "variant": "domestic", "header_text": MPLS_HDR, "network": {}
}).get_json()
t("持久化-新会话含标记(重启模拟)", PERSIST_MARKER in r.get("output", ""))

# Reset
r = c2.post('/api/template/reset', json={'key': PERSIST_KEY}).get_json()
t("持久化-重置", r.get("ok") and len(r.get("template", "")) > 50)

# Verify reset in new session
_EMBEDDED_NS.clear()
_load_workspace_templates()
c3 = app.test_client()
r = c3.post("/api/generate/epoch_mpls", json={
    "variant": "domestic", "header_text": MPLS_HDR, "network": {}
}).get_json()
t("持久化-重置后不含标记", PERSIST_MARKER not in r.get("output", ""))

# ═══ Phase 4: 用户实际操作模拟 ═══
print("\n" + "=" * 60)
print("Phase 4: 用户实际操作流程模拟")
print("=" * 60)

# 模拟用户流程：打开 ER → 选 HK → 切换到模板编辑器 → 修改模板 → 保存 → 切回正式页面 → 生成
USER_TPL = f"# USER_FLOW_{MARKER}\nset system host-name USER-FLOW-TEST\n"

# Step 1: 用户在模板编辑器中加载 ER HK
r = c.post('/api/template/load', json={'key': 'Epoch FastIP · HK 香港出口'}).get_json()
t("用户流程-加载模板", r.get("ok") and len(r.get("template", "")) > 1000)

# Step 2: 用户修改模板并保存
r = c.post('/api/template/save', json={
    'key': 'Epoch FastIP · HK 香港出口',
    'header': ER_HK_HDR, 'mapping': r.get("mapping", ""),
    'template': USER_TPL
}).get_json()
t("用户流程-保存修改", r.get("ok"))

# Step 3: 用户切到正式页面，选择 ER HK，粘贴数据头，生成
r = c.post("/api/generate/epoch_fastip", json={
    "variant": "hk", "header_text": ER_HK_HDR, "network": {}
}).get_json()
t("用户流程-生成含修改", "USER_FLOW" in r.get("output", ""))

# Step 4: 用户发现模板有问题，回去重置
r = c.post('/api/template/reset', json={'key': 'Epoch FastIP · HK 香港出口'}).get_json()
t("用户流程-重置模板", r.get("ok"))

# Step 5: 用户重新生成，恢复出厂
r = c.post("/api/generate/epoch_fastip", json={
    "variant": "hk", "header_text": ER_HK_HDR, "network": {}
}).get_json()
t("用户流程-重置后生成正常", MARKER not in r.get("output", "") and "USER_FLOW" not in r.get("output", ""))

# ═══ Phase 5: 参数修改不影响模板 ═══
print("\n" + "=" * 60)
print("Phase 5: 参数修改不影响模板内容")
print("=" * 60)

# 确保是出厂模板
c.post('/api/template/reset', json={'key': 'Epoch FastIP · HK 香港出口'})

# 用不同的网络参数生成两次
r1 = c.post("/api/generate/epoch_fastip", json={
    "variant": "hk", "header_text": ER_HK_HDR,
    "network": {"wan_cidr": "10.10.10.1/24", "lan_cidr": "192.168.99.1/24"}
}).get_json()
t("参数隔离-生成1成功", r1.get("ok"))

r2 = c.post("/api/generate/epoch_fastip", json={
    "variant": "hk", "header_text": ER_HK_HDR,
    "network": {"wan_cidr": "99.99.99.1/24", "lan_cidr": "172.16.99.1/24"}
}).get_json()
t("参数隔离-生成2成功", r2.get("ok"))

t("参数隔离-不同参数输出不同", r1.get("output") != r2.get("output"))
t("参数隔离-生成1含WAN IP", "10.10.10" in r1.get("output", ""))
t("参数隔离-生成2含WAN IP", "99.99.99" in r2.get("output", ""))

# ═══ 结果 ═══
print(f"\n{'='*60}")
print(f"审计结果: {PASS}/{PASS+FAIL} 通过, {FAIL} 失败")
if FAIL == 0:
    print("✓ 所有模板系统检查通过")
else:
    print("✗ 存在失败项，需要修复")
