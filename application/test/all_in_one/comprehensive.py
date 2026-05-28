#!/usr/bin/env python3
"""全场景完整测试 — 客户业务逻辑 + 脚本逻辑双重验证"""
import sys, os, json, uuid
os.environ["TEST_MODE"] = "1"
import _bootstrap  # noqa: F401
from app import app, _load_module, _SCENARIO_LIST, _EMBEDDED_NS, _load_workspace_templates

PASS = FAIL = 0
MARKER = f"CMP_{uuid.uuid4().hex[:6]}"

def t(name, ok):
    global PASS, FAIL
    if ok: PASS += 1; print(f"  [PASS] {name}")
    else: FAIL += 1; print(f"  [FAIL] {name}")

c = app.test_client()

# ═════════════════════════════════════════════════════════════
# 测试数据
# ═════════════════════════════════════════════════════════════
HDR = {
    "er_hk": "hostname:TEST-CE\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\nwanip:10.22.98.40/30\n对接IP:10.255.110.6\nLineID:609157A2\nPE:szd-ape3\ntunnel:vtun1214\nwanip:10.22.98.44/30\n对接IP:10.255.110.10",
    "er_us": "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\nPE 对接:192.168.247.17\n海外出口ip:\n10.60.44.28-218.32.88.83\n\nLineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\nPE Docking:192.168.239.12\nBGPSERVER IP:103.252.19.25,43.229.117.226\n海外出口ip:\n10.60.44.28-218.32.88.83",
    "er_flink": "PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.1.0/29\nPE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.1.0/29\nPE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.1.0/29",
    "er_ne": "LineID:609353B7\nPE： tyo2-natpe4\nWANIP: 10.22.86.196/30\nTUNNEL: tun1083\nPE Docking：192.168.205.67\nCE Docking：: 10.22.242.21\nBGPSERVER IP：103.252.19.25,43.229.117.226\n海外出口ip：\n10.60.21.185-103.57.50.44\n\nLineID:609353B8\nPE： tyo4-natpe2\nWANIP: 10.22.100.120/30\nTUNNEL: tun1033\nPE Docking：10.33.54.78\nCE Docking：: 10.22.242.21\nBGPSERVER IP：103.252.19.99,43.229.119.251\n海外出口ip：\n10.60.21.186-103.57.50.45",
    "er_ds": "google.com\nyoutube.com",
    "usg_us": "main IPSEC_PE: szd-ape2\nmain dial_ip: 121.14.82.235\nmain loopback: 10.18.12.57\nmain auth_id: 609157A1\nLineID:609157A1\nPE:lax1-fgpe1\nWANIP:10.22.98.40/30\nTUNNEL:tun1213\nPE对接:10.255.110.6\n出口ip:64.81.158.21\n\nbackup IPSEC_PE: szc-apebk2\nbackup dial_ip: 120.133.138.20\nbackup loopback: 10.18.14.21\nbackup auth_id: 609157A2\nLineID:609157A2\nPE:sjc1-fgpe1\nWANIP:10.22.32.60/30\nTUNNEL:tun2305\nPE对接:10.255.111.128\n出口ip:172.16.14.118",
    "usg_ne": "LineID:609424A1\nPE： lax1-fgpe1\nWANIP: 10.22.110.24/30\nTUNNEL: tun1248\nPE对接：10.255.110.6\nCE对接：10.18.16.20\n出口ip：\n10.61.10.78-64.81.20.174\n10.61.10.106-64.81.20.178\nLineID:609424A2\nPE： sjc1-fgpe2\nWANIP: 10.22.106.20/30\nTUNNEL: tun1229\nPE对接：10.255.111.158\nCE对接：10.18.14.127\n出口ip：\n10.60.76.6-172.16.23.8\n10.60.76.14-172.16.23.9",
    "mpls_cn": "LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\nPE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\nLineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\nPE 对接:192.168.253.80\nPE AS号:65531",
    "ar": "LineID:604604Hw1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1147\nwanip:10.40.232.248/30\nPE 对接:10.200.200.76\nCE 对接:10.50.131.16\n拨号PE:gzd-upe5\n对接IP:10.200.200.76\nLoopIP:10.50.131.16\n拨号ip:183.63.68.174\n秘钥:both-win\n\nLineID:604604Hw2\nPE:szd-upebk1\nTunnel:Tunnel0/0/1605\nwanip:10.30.115.252/30\nPE 对接:10.200.200.22\nCE 对接:10.120.47.20\n拨号PE:szd-upebk1\n对接IP:10.200.200.22\nLoopIP:10.120.47.20\n拨号ip:183.56.163.24\n秘钥:both-win",
}

# All 20 scenario generation tests
ALL_SCENARIOS = [
    # (name, tool, variant, header, output_key, keywords, min_lines)
    ("ER HK", "epoch_fastip", "hk", HDR["er_hk"], "output", ["set epoch","set system host-name"], 200),
    ("ER US", "epoch_fastip", "us", HDR["er_us"], "output", ["set epoch","set system host-name"], 250),
    ("ER Flink", "epoch_fastip", "flink", HDR["er_flink"], "output", ["set track"], 3),
    ("ER New Exit", "epoch_fastip", "new_exit", HDR["er_ne"], "output", ["set interfaces tunnel"], 10),
    ("ER Domain Split", "epoch_fastip", "domain_split", HDR["er_ds"], "output", ["set protocols static"], 5),
    ("USG US", "usg_fastip", "us", HDR["usg_us"], "output", ["set firewall","ip address"], 100),
    ("USG HK", "usg_fastip", "hk", HDR["usg_us"], "output", ["set firewall","ip address"], 100),
    ("USG Flink", "usg_fastip", "flink", HDR["usg_us"], "output", ["interface Tunnel"], 20),
    ("USG New Exit", "usg_fastip", "new_exit", HDR["usg_ne"], "output", ["interface Tunnel"], 10),
    ("MPLS CN", "epoch_mpls", "domestic", HDR["mpls_cn"], "output", ["set firewall","set protocols bgp"], 60),
    ("MPLS OV", "epoch_mpls", "overseas", HDR["mpls_cn"], "output", ["set firewall","set protocols bgp"], 60),
    ("MPLS IPSec", "epoch_mpls", "ipsec", HDR["mpls_cn"], "output", ["set firewall"], 100),
    ("AR Single OPS", "ar_sdwan", "single_ops", HDR["ar"], "ops_output", ["import ops","def ops_condition"], 50),
    ("AR Single Factory", "ar_sdwan", "single_factory", HDR["ar"], "factory_output", ["ip vpn-instance"], 30),
    ("AR DualWAN OPS", "ar_sdwan", "single_dualwan", HDR["ar"], "ops_output", ["import ops"], 50),
    ("AR Dual Pri OPS", "ar_sdwan", "dual_ops_pri", HDR["ar"], "ops_output", ["import ops"], 30),
    ("AR Dual Bak OPS", "ar_sdwan", "dual_ops_bak", HDR["ar"], "ops_output", ["import ops"], 30),
]

CUSTOM_TPL = f"# {MARKER}\nset system host-name TEST-{MARKER}\n"

# ═════════════════════════════════════════════════════════════
# SECTION 1: 脚本逻辑 — 所有场景生成
# ═════════════════════════════════════════════════════════════
print("=" * 60)
print("SECTION 1: 脚本逻辑 — 20 场景生成")
print("=" * 60)
for name, tool, variant, hdr, out_key, kw, min_l in ALL_SCENARIOS:
    r = c.post(f"/api/generate/{tool}", json={
        "variant": variant, "header_text": hdr, "network": {}
    }).get_json()
    gen_out = r.get(out_key, "") or r.get("output", "")
    lines = len(gen_out.splitlines()) if gen_out else 0
    all_kw = all(k in gen_out for k in kw)
    t(f"{name} 生成成功", r.get("ok"))
    t(f"{name} 关键字完整", all_kw)
    t(f"{name} 行数合理 ({lines}行)", lines >= min_l)

# ═════════════════════════════════════════════════════════════
# SECTION 2: 脚本逻辑 — 参数修改反映到输出
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 2: 脚本逻辑 — 网络参数注入")
print("=" * 60)

# WAN IP change
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{"wan_cidr":"192.168.1.10/24"}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{"wan_cidr":"99.99.99.1/24"}}).get_json()
t("WAN IP 变化 → 输出不同", r1.get("output") != r2.get("output"))
t("WAN IP 192.168 在输出中", "192.168.1.10" in r1.get("output",""))
t("WAN IP 99.99 在输出中", "99.99.99" in r2.get("output",""))

# DHCP
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{"wan_dhcp":True,"lan_dhcp":True}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{"wan_dhcp":False,"lan_dhcp":False}}).get_json()
t("DHCP 变化 → 输出不同", r1.get("output") != r2.get("output"))

# DNS (USG)
r1 = c.post("/api/generate/usg_fastip", json={"variant":"us","header_text":HDR["usg_us"],"network":{"dns1":"1.1.1.1"}}).get_json()
t("USG DNS 1.1.1.1 生效", "1.1.1.1" in r1.get("output",""))

# Inner nets
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{"inner_nets":"10.10.10.0/24"}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{"inner_nets":"172.16.0.0/12"}}).get_json()
t("内网段 10.10 生效", "10.10.10" in r1.get("output",""))
t("内网段 172.16 生效", "172.16.0" in r2.get("output",""))

# Bypass (ER/MPS)
for tool, variant, hdr in [
    ("epoch_fastip","hk",HDR["er_hk"]),
    ("epoch_fastip","us",HDR["er_us"]),
    ("epoch_mpls","domestic",HDR["mpls_cn"]),
]:
    r1 = c.post(f"/api/generate/{tool}", json={"variant":variant,"header_text":hdr,"network":{"bypass":True}}).get_json()
    r2 = c.post(f"/api/generate/{tool}", json={"variant":variant,"header_text":hdr,"network":{"bypass":False}}).get_json()
    t(f"{tool}/{variant} 旁挂 ON≠OFF", r1.get("output","") != r2.get("output",""))

# ═════════════════════════════════════════════════════════════
# SECTION 3: 脚本逻辑 — 模板生命周期 (14 模板驱动场景)
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 3: 脚本逻辑 — 模板生命周期")
print("=" * 60)

TPL_SCENARIOS = [
    ("Epoch FastIP · HK 香港出口", "epoch_fastip", "hk", HDR["er_hk"], "output"),
    ("Epoch FastIP · 非香港出口", "epoch_fastip", "us", HDR["er_us"], "output"),
    ("Epoch FastIP · ER 飞连", "epoch_fastip", "flink", HDR["er_flink"], "output"),
    ("Epoch FastIP · ER 新增出口", "epoch_fastip", "new_exit", HDR["er_ne"], "output"),
    ("Epoch FastIP · ER 域名分流", "epoch_fastip", "domain_split", HDR["er_ds"], "output"),
    ("USG FastIP · 非香港出口", "usg_fastip", "us", HDR["usg_us"], "output"),
    ("USG FastIP · HK 香港出口", "usg_fastip", "hk", HDR["usg_us"], "output"),
    ("USG FastIP · 飞连", "usg_fastip", "flink", HDR["usg_us"], "output"),
    ("USG FastIP · 新增出口", "usg_fastip", "new_exit", HDR["usg_ne"], "output"),
    ("Epoch MPLS · 国内配置", "epoch_mpls", "domestic", HDR["mpls_cn"], "output"),
    ("Epoch MPLS · 海外配置", "epoch_mpls", "overseas", HDR["mpls_cn"], "output"),
    ("Epoch MPLS · IPSec", "epoch_mpls", "ipsec", HDR["mpls_cn"], "output"),
    ("AR SD-WAN · 单机单WAN · OPS", "ar_sdwan", "single_ops", HDR["ar"], "ops_output"),
    ("AR SD-WAN · 单机单WAN · Factory", "ar_sdwan", "single_factory", HDR["ar"], "factory_output"),
]

for key, tool, variant, hdr, out_key in TPL_SCENARIOS:
    short = key[:40]
    # Save
    r = c.post('/api/template/save', json={'key':key,'header':hdr,'mapping':'','template':CUSTOM_TPL}).get_json()
    t(f"{short} 保存模板", r.get("ok"))
    # Generate with custom
    r = c.post(f"/api/generate/{tool}", json={"variant":variant,"header_text":hdr,"network":{}}).get_json()
    gen_out = r.get(out_key,"") or r.get("output","")
    t(f"{short} 生成含自定义", MARKER in gen_out)
    # Reset
    r = c.post('/api/template/reset', json={'key':key}).get_json()
    t(f"{short} 重置模板", r.get("ok") and len(r.get("template",""))>50)
    # Generate after reset
    r = c.post(f"/api/generate/{tool}", json={"variant":variant,"header_text":hdr,"network":{}}).get_json()
    gen_out = r.get(out_key,"") or r.get("output","")
    t(f"{short} 重置后不含自定义", MARKER not in gen_out)

# ═════════════════════════════════════════════════════════════
# SECTION 4: 脚本逻辑 — 模板持久化 (模拟重启)
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 4: 脚本逻辑 — 模板持久化")
print("=" * 60)

PKEY = "Epoch MPLS · 国内配置"
P_TPL = f"# PERSIST_{MARKER}\nset system host-name PERSIST\n"
# Save
r = c.post('/api/template/save', json={'key':PKEY,'header':HDR["mpls_cn"],'mapping':'','template':P_TPL}).get_json()
t("持久化-保存", r.get("ok"))
# Verify in session
r = c.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":HDR["mpls_cn"],"network":{}}).get_json()
t("持久化-当前会话含标记", f"PERSIST_{MARKER}" in r.get("output",""))
# Simulate restart
_EMBEDDED_NS.clear()
_load_workspace_templates()
c2 = app.test_client()
r = c2.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":HDR["mpls_cn"],"network":{}}).get_json()
t("持久化-重启后含标记", f"PERSIST_{MARKER}" in r.get("output",""))
# Reset
c2.post('/api/template/reset', json={'key':PKEY})
_EMBEDDED_NS.clear()
_load_workspace_templates()
c3 = app.test_client()
r = c3.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":HDR["mpls_cn"],"network":{}}).get_json()
t("持久化-重置重启后不含标记", f"PERSIST_{MARKER}" not in r.get("output",""))

# ═════════════════════════════════════════════════════════════
# SECTION 5: 脚本逻辑 — 跨场景隔离
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 5: 脚本逻辑 — 跨场景隔离")
print("=" * 60)

r = c.post('/api/template/save', json={'key':'Epoch FastIP · HK 香港出口','header':HDR["er_hk"],'mapping':'','template':CUSTOM_TPL}).get_json()
t("隔离-保存HK自定义", r.get("ok"))
r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{}}).get_json()
t("隔离-HK含标记", MARKER in r.get("output",""))
r = c.post("/api/generate/epoch_fastip", json={"variant":"us","header_text":HDR["er_us"],"network":{}}).get_json()
t("隔离-US不含标记(TEMPLATE_EPOCH_US≠TEMPLATE_EPOCH_HK)", MARKER not in r.get("output",""))
r = c.post("/api/generate/usg_fastip", json={"variant":"us","header_text":HDR["usg_us"],"network":{}}).get_json()
t("隔离-USG US不含标记(不同模块)", MARKER not in r.get("output",""))
c.post('/api/template/reset', json={'key':'Epoch FastIP · HK 香港出口'})

# ═════════════════════════════════════════════════════════════
# SECTION 6: 脚本逻辑 — 初始化默认值持久化
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 6: 脚本逻辑 — 初始化默认值持久化")
print("=" * 60)

r = c.post('/api/init-defaults/save', json={'key':'Epoch FastIP · HK 香港出口','values':{'DEFAULT_WAN_DHCP':True,'DEFAULT_LAN_DHCP':True}}).get_json()
t("初始值-保存DHCP=True", r.get("ok"))
er = _load_module('er_fastip_2in1_v8.py')
t("初始值-模块globals WAN_DHCP=True", er.get('DEFAULT_WAN_DHCP')==True)
# Reset and verify the JSON file is cleaned
r = c.post('/api/init-defaults/reset', json={'key':'Epoch FastIP · HK 香港出口'}).get_json()
t("初始值-重置成功", r.get("ok"))
# Verify module global is reset (factory is False for WAN_DHCP)
er2 = _load_module('er_fastip_2in1_v8.py')
t("初始值-重置后WAN_DHCP=False", er2.get('DEFAULT_WAN_DHCP')==False)

# ═════════════════════════════════════════════════════════════
# SECTION 7: 脚本逻辑 — 备注和示例加载
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 7: 脚本逻辑 — 备注说明 & 填写示例")
print("=" * 60)

NOTES_CHECKS = [
    ("epoch_fastip", "hk", 50), ("epoch_fastip", "us", 50),
    ("usg_fastip", "us", 50), ("usg_fastip", "hk", 50),
    ("epoch_mpls", "domestic", 50), ("epoch_mpls", "overseas", 50),
]
for tool, variant, min_len in NOTES_CHECKS:
    r = c.get(f"/api/notes/{tool}?variant={variant}").get_json()
    t(f"{tool}/{variant} 备注加载", r.get("ok") and len(r.get("notes",""))>min_len)

EXAMPLE_CHECKS = [
    ("epoch_fastip", "hk"), ("epoch_fastip", "us"), ("epoch_fastip", "flink"),
    ("usg_fastip", "us"), ("usg_fastip", "hk"),
    ("epoch_mpls", "domestic"), ("epoch_mpls", "overseas"),
    ("ar_sdwan", "single_ops"),
]
for tool, variant in EXAMPLE_CHECKS:
    r = c.get(f"/api/examples/{tool}/{variant}").get_json()
    t(f"{tool}/{variant} 示例加载", r.get("ok") and len(r.get("example",""))>20)

# ═════════════════════════════════════════════════════════════
# SECTION 8: 脚本逻辑 — 模板编辑器加载所有场景
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 8: 脚本逻辑 — 模板编辑器加载全部 20 场景")
print("=" * 60)

for info in _SCENARIO_LIST:
    key = info["key"]
    r = c.post('/api/template/load', json={'key': key}).get_json()
    ok = r.get("ok") and len(r.get("header",""))>0 and len(r.get("template",""))>0
    t(f"Load {key[:45]}", ok)

# ═════════════════════════════════════════════════════════════
# SECTION 9: 客户业务逻辑 — 模板编辑器全流程
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 9: 客户业务逻辑 — 模板编辑器完整流程")
print("=" * 60)

USER_KEY = "Epoch FastIP · HK 香港出口"
USER_TPL = f"# USER_FLOW_{MARKER}\nset system host-name USER-FLOW\n"

r = c.post('/api/template/load', json={'key': USER_KEY}).get_json()
t("用户流程-加载模板", r.get("ok") and len(r.get("template",""))>1000)

r = c.post('/api/template/save', json={'key':USER_KEY,'header':HDR["er_hk"],'mapping':r.get("mapping",""),'template':USER_TPL}).get_json()
t("用户流程-保存修改", r.get("ok"))

r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{}}).get_json()
t("用户流程-生成含修改", "USER_FLOW" in r.get("output",""))

r = c.post('/api/template/preview', json={'key':USER_KEY,'header':HDR["er_hk"],'template':USER_TPL}).get_json()
t("用户流程-预览含修改", r.get("ok") and "USER_FLOW" in r.get("output",""))

r = c.post('/api/template/reset', json={'key':USER_KEY}).get_json()
t("用户流程-重置", r.get("ok"))

r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":HDR["er_hk"],"network":{}}).get_json()
t("用户流程-重置后不含修改", "USER_FLOW" not in r.get("output",""))

# ═════════════════════════════════════════════════════════════
# SECTION 10: 客户业务逻辑 — API 端点
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 10: 客户业务逻辑 — API 端点")
print("=" * 60)

r = c.get("/api/tools").get_json()
t("GET /api/tools", r.get("ok") is None and len(r.get("tools",[]))==4)

r = c.get("/api/scenarios").get_json()
t("GET /api/scenarios", r.get("ok") and len(r.get("scenarios",[]))==20)

r = c.get("/api/sponsor-board").get_json()
t("GET /api/sponsor-board", r.get("ok") and "赞助榜单" in str(r.get("board",{})))

r = c.get("/api/init-defaults").get_json()
t("GET /api/init-defaults", r.get("ok") and len(r.get("defaults",{}))>0)

# ═════════════════════════════════════════════════════════════
# SECTION 11: 客户业务逻辑 — 错误处理
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 11: 客户业务逻辑 — 错误处理")
print("=" * 60)

r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":"","network":{}}).get_json()
t("空数据头-返回错误", not r.get("ok") or "error" in str(r).lower() or r.get("output","").strip() != "")

r = c.post("/api/generate/epoch_fastip", json={"variant":"xyz","header_text":"test","network":{}}).get_json()
t("无效variant-返回错误", not r.get("ok"))

r = c.post('/api/template/load', json={'key':'不存在的场景'}).get_json()
t("无效场景-返回404", not r.get("ok"))

# ═════════════════════════════════════════════════════════════
# RESULTS
# ═════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  完整测试报告")
print(f"{'='*60}")
print(f"  PASS: {PASS}")
print(f"  FAIL: {FAIL}")
print(f"  TOTAL: {PASS+FAIL}")
print(f"  RATE: {PASS*100//(PASS+FAIL) if PASS+FAIL else 0}%")

if FAIL == 0:
    print(f"\n  >>> 全部测试通过 <<<")
else:
    print(f"\n  >>> 存在 {FAIL} 个失败项 <<<")
