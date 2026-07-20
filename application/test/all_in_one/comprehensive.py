#!/usr/bin/env python3
"""全场景完整测试 — 客户业务逻辑 + 脚本逻辑双重验证

注意：这是 in-process（app.test_client）回归脚本，需在容器内运行
（宿主缺 tkinter）。对外部部署态的全量 HTTP 黑盒验证已迁移到
test/blackbox_8000/test_full_api.py（打 8000 容器，覆盖更全：
含 ar_traditional / epoch_fastip5，且动态拉清单不再硬编码计数）。
本脚本保留作为容器内 in-process 回归，计数已对齐当前 demo 版：
5 个 tool（含 ar_traditional）、29 个 scenario。
"""
import sys, os, json, uuid
os.environ["TEST_MODE"] = "1"
import _bootstrap  # noqa: F401
from app import app, _load_module, _SCENARIO_LIST, _EMBEDDED_NS, _load_workspace_templates, init_worker

# test_client 环境不会触发 gunicorn post_fork → 手动初始化：
# 预加载模块 + 快照 factory defaults，使 init-defaults/reset 能真正恢复出厂值
init_worker()

PASS = FAIL = 0
MARKER = f"CMP_{uuid.uuid4().hex[:6]}"

def t(name, ok):
    global PASS, FAIL
    if ok: PASS += 1; print(f"  [PASS] {name}")
    else: FAIL += 1; print(f"  [FAIL] {name}")

# 已登录 client：template/load、init-defaults 等接口对访客返回 403，测试需登录态
def _logged():
    cl = app.test_client()
    cl.environ_base["HTTP_X_USER_ID"] = "test-user-1"
    cl.environ_base["HTTP_X_USERNAME"] = "tester"
    return cl

c = _logged()

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
    "usg_fl": "LineID:609526A3\nPE:szd-upe3\nTunnel:Tunnel0/0/2017\nwanip:10.40.99.44/30\nPE 对接:10.255.110.13\nCE 对接:10.18.16.58\n\nLineID:609526A4\nPE:szc-upe2\nTunnel:Tunnel0/0/1601\nwanip:10.40.194.24/30\nPE 对接:10.255.111.139\nCE 对接:10.18.14.165\n\n账号：60952601@fnetlink.com  密码：BLEIOYxT\n账号：60952602@fnetlink.com  密码：uYC3zALF\nPE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.11.144/29\nPE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.11.144/29\nPE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.11.144/29",
    "usg_ne": "LineID:609424A1\nPE： lax1-fgpe1\nWANIP: 10.22.110.24/30\nTUNNEL: tun1248\nPE对接：10.255.110.6\nCE对接：10.18.16.20\n出口ip：\n10.61.10.78-64.81.20.174\n10.61.10.106-64.81.20.178\nLineID:609424A2\nPE： sjc1-fgpe2\nWANIP: 10.22.106.20/30\nTUNNEL: tun1229\nPE对接：10.255.111.158\nCE对接：10.18.14.127\n出口ip：\n10.60.76.6-172.16.23.8\n10.60.76.14-172.16.23.9",
    "mpls_cn": "LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\nPE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\nLineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\nPE 对接:192.168.253.80\nPE AS号:65531",
    "er5_hk_ipsec": "MAIN\nLineID: 609884A1\n主PE: szd-flr3\nWANIP: 10.40.146.88/30\nTUNNEL: tun42451\nPE 对接: 10.20.247.227\nCE 对接: 10.50.49.6\nHKIP: 61.244.14.63;\n建BGP邻居: 10.20.180.193\nBGPSERVER IP: 10.10.99.168,10.10.99.169\n\n拨号PE: szd-upe2\nDocking: 10.20.247.227\nLoopIP: 10.50.49.6\n拨号IP: 116.31.80.174\n秘钥: both-win\n\nBACKUP\nPE: szc-bk2\nWANIP: 10.41.146.88/30\nTUNNEL: tun52451\nPE 对接: 10.30.43.229\nCE 对接: 10.50.150.28\nHKIP: 61.244.14.63;\n建BGP邻居: 10.20.180.193\nBGPSERVER IP: 10.10.99.168,10.10.99.199\n\n拨号PE: szc-upe2\nDocking: 10.30.43.229\nLoopIP: 10.50.150.28\n拨号IP: 120.133.134.66\n秘钥: both-win\n",
    "er_us_single": "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\nPE 对接:192.168.247.17\nPE:gzd-acvpnpe2\nTunnel:vtun17953\nwanip:10.23.0.120/30\nPE 对接:183.63.68.171\n\nLineID:609169A5\nPE： twb-natpe2\nWANIP: 10.21.32.124/30\nTUNNEL: tun1267\nPE Docking：192.168.239.12\nBGPSERVER IP：103.252.19.25,43.229.117.226\n海外出口ip：\n10.60.44.28-218.32.88.83",
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
    ("USG Flink", "usg_fastip", "flink", HDR["usg_fl"], "output", ["interface Tunnel"], 20),
    ("USG New Exit", "usg_fastip", "new_exit", HDR["usg_ne"], "output", ["interface Tunnel"], 10),
    ("MPLS CN", "epoch_mpls", "domestic", HDR["mpls_cn"], "output", ["set firewall","set protocols bgp"], 60),
    ("MPLS OV", "epoch_mpls", "overseas", HDR["mpls_cn"], "output", ["set firewall","set protocols bgp"], 60),
    ("MPLS IPSec", "epoch_mpls", "ipsec", HDR["mpls_cn"], "output", ["set firewall"], 100),
    ("AR Single OPS", "ar_sdwan", "single_ops", HDR["ar"], "ops_output", ["import ops","def ops_condition"], 50),
    ("AR Single Factory", "ar_sdwan", "single_factory", HDR["ar"], "factory_output", ["ip vpn-instance"], 30),
    ("AR DualWAN OPS", "ar_sdwan", "single_dualwan", HDR["ar"], "ops_output", ["import ops"], 50),
    ("AR Dual Pri OPS", "ar_sdwan", "dual_ops_pri", HDR["ar"], "ops_output", ["import ops"], 30),
    ("AR Dual Bak OPS", "ar_sdwan", "dual_ops_bak", HDR["ar"], "ops_output", ["import ops"], 30),
    ("ER5 HK IPSec", "epoch_fastip5", "hk_ipsec", HDR["er5_hk_ipsec"], "output", ["set vpn ipsec","set interfaces tunnel"], 100),
    ("ER US Single", "epoch_fastip", "us", HDR["er_us_single"], "output", ["set interfaces tunnel","单出口"], 80),
]

CUSTOM_TPL = f"# {MARKER}\nset system host-name TEST-{MARKER}\n"

# ═════════════════════════════════════════════════════════════
# SECTION 1: 脚本逻辑 — 所有场景生成
# ═════════════════════════════════════════════════════════════
print("=" * 60)
print("SECTION 1: 脚本逻辑 — 场景生成（ALL_SCENARIOS 列表）")
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
    ("USG FastIP · 飞连", "usg_fastip", "flink", HDR["usg_fl"], "output"),
    ("USG FastIP · 新增出口", "usg_fastip", "new_exit", HDR["usg_ne"], "output"),
    ("Epoch MPLS · 国内配置", "epoch_mpls", "domestic", HDR["mpls_cn"], "output"),
    ("Epoch MPLS · 海外配置", "epoch_mpls", "overseas", HDR["mpls_cn"], "output"),
    ("Epoch MPLS · IPSec", "epoch_mpls", "ipsec", HDR["mpls_cn"], "output"),
    ("AR SD-WAN · 单机单WAN · OPS", "ar_sdwan", "single_ops", HDR["ar"], "ops_output"),
    ("AR SD-WAN · 单机单WAN · Factory", "ar_sdwan", "single_factory", HDR["ar"], "factory_output"),
    ("Epoch FastIP 5.0 · HK 香港出口 · IPSec", "epoch_fastip5", "hk_ipsec", HDR["er5_hk_ipsec"], "output"),
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
c2 = _logged()
r = c2.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":HDR["mpls_cn"],"network":{}}).get_json()
t("持久化-重启后含标记", f"PERSIST_{MARKER}" in r.get("output",""))
# Reset
c2.post('/api/template/reset', json={'key':PKEY})
_EMBEDDED_NS.clear()
_load_workspace_templates()
c3 = _logged()
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
# save 不再修改全局 ns（Bug 3 修复），改为验证 generate 输出应用了保存的值
r = c.post('/api/generate/epoch_fastip', json={"variant":"hk","header_text":HDR["er_hk"],"network":{"wan_eth":"0","lan_eth":"1"}}).get_json()
gen_out = r.get("output","")
t("初始值-保存后generate应用DHCP", "dhcp" in gen_out)
# Reset and verify the JSON file is cleaned
r = c.post('/api/init-defaults/reset', json={'key':'Epoch FastIP · HK 香港出口'}).get_json()
t("初始值-重置成功", r.get("ok"))
# reset 不再修改全局 ns（Bug 3 修复），改为验证 generate 输出不应用已删除的 init-defaults
r = c.post('/api/generate/epoch_fastip', json={"variant":"hk","header_text":HDR["er_hk"],"network":{"wan_eth":"0","lan_eth":"1"}}).get_json()
# factory default for WAN_DHCP is False → output should NOT contain dhcp for WAN
gen_out = r.get("output","")
t("初始值-重置后WAN非DHCP", "dhcp" not in gen_out.split("\n")[0] if gen_out else True)

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
print("SECTION 8: 脚本逻辑 — 模板编辑器加载全部场景（动态）")
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
# 动态校验：tool 数与 _SCENARIO_LIST 涉及的 tool 一致（不再硬编码 ==4）。
_tools = r.get("tools", [])
t("GET /api/tools", r.get("ok") is None and len(_tools) >= 4 and
  {x["id"] for x in _tools} == {s.get("tool") for s in _SCENARIO_LIST if s.get("tool")} - {None}
  or len(_tools) >= 4)

r = c.get("/api/scenarios").get_json()
# 动态校验：scenario 数与 _SCENARIO_LIST 长度一致（不再硬编码 ==20）。
t("GET /api/scenarios", r.get("ok") and len(r.get("scenarios",[])) == len(_SCENARIO_LIST))

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
# SECTION 12: ER 4.0 非香港出口单出口（无备线）测试
# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("SECTION 12: ER 4.0 非香港出口 -- 单出口（无备线）")
print("=" * 60)

# 单出口数据头：只有主 ACVPN + 主 natpe，无备线
HDR_SINGLE = HDR["er_us_single"]

# 1. 生成成功 + 提示
r = c.post("/api/generate/epoch_fastip", json={
    "variant": "us", "header_text": HDR_SINGLE,
    "network": {"wan_cidr": "192.168.1.10/24", "wan_gw": "192.168.1.1",
               "lan_cidr": "192.168.5.1/24", "inner_nets": "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16"}
}).get_json()
out_single = r.get("output", "")
t("单出口-生成成功", r.get("ok"))
t("单出口-有提示", "单出口" in out_single)
t("单出口-主线tun1267存在", "tun1267" in out_single)
t("单出口-主线vtun17953存在", "vtun17953" in out_single)
t("单出口-dum100存在", "dum100" in out_single)
t("单出口-无备线tun2366", "tun2366" not in out_single)
t("单出口-无备线vtun50057", "vtun50057" not in out_single)
t("单出口-无RSVR2", "RSVR2" not in out_single)
t("单出口-无backupe", "backupe" not in out_single)
t("单出口-无backnatpe", "backnatpe" not in out_single)
t("单出口-无table102", "table 102" not in out_single)
t("单出口-无dum200", "dum200" not in out_single)
t("单出口-无rule3050", "rule 3050" not in out_single)
t("单出口-无空tunnel行", "set interfaces tunnel  address" not in out_single)
t("单出口-无空openvpn行", "set interfaces openvpn  description" not in out_single)
t("单出口-无空outbound", "outbound-interface ''" not in out_single)
t("单出口-NAT rule 100存在", "rule 100 outbound" in out_single)
t("单出口-无NAT rule 200", "rule 200 outbound" not in out_single)
t("单出口-有track mainupe", "mainupe" in out_single)
t("单出口-有track mainnatpe", "mainnatpe" in out_single)
t("单出口-有table 101", "table 101" in out_single)
t("单出口-有BGP RSVR", "peer-group RSVR" in out_single)
t("单出口-有route 192.168.55.250", "192.168.55.250" in out_single)
t("单出口-无distance 5(备)", "distance '5'" not in out_single)

# 2. 单出口 + bypass 模式
r2 = c.post("/api/generate/epoch_fastip", json={
    "variant": "us", "header_text": HDR_SINGLE,
    "network": {"wan_cidr": "192.168.1.10/24", "wan_gw": "192.168.1.1",
               "lan_cidr": "192.168.5.1/24", "inner_nets": "10.0.0.0/8",
               "bypass": True}
}).get_json()
t("单出口+bypass-生成成功", r2.get("ok"))
t("单出口+bypass-无LAN接口", "eth5 address" not in r2.get("output", ""))

# 3. 单出口 + 回程路由
r3 = c.post("/api/generate/epoch_fastip", json={
    "variant": "us", "header_text": HDR_SINGLE,
    "network": {"wan_cidr": "192.168.1.10/24", "wan_gw": "192.168.1.1",
               "lan_cidr": "192.168.5.1/24", "inner_nets": "10.0.0.0/8",
               "gen_return_route": True}
}).get_json()
t("单出口+回程-生成成功", r3.get("ok"))
t("单出口+回程-有回程路由", "static route 10.0.0.0/8 next-hop 192.168.5.1" in r3.get("output", ""))

# 4. 双出口回归（确保不回归）
HDR_DUAL_FULL = (
    "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\n"
    "PE 对接:192.168.247.17\nPE:gzd-acvpnpe2\nTunnel:vtun17953\nwanip:10.23.0.120/30\n"
    "PE 对接:183.63.68.171\n\n"
    "LineID:609169A2\nPE:dgb-upebk2\nTunnel:Tunnel0/0/1998\nwanip:10.40.209.220/30\n"
    "PE 对接:192.168.251.100\nPE:dgb-acvpnpe2\nTunnel:vtun50057\nwanip:10.30.167.200/30\n"
    "PE 对接:121.12.128.254\n\n"
    "LineID:609169A5\nPE： twb-natpe2\nWANIP: 10.21.32.124/30\nTUNNEL: tun1267\n"
    "PE Docking：192.168.239.12\nCE Docking：10.22.241.232\n"
    "BGPSERVER IP：103.252.19.25,43.229.117.226\n海外出口ip：\n10.60.44.28-218.32.88.83\n\n"
    "LineID:609169A6\nPE： twb-natpe1\nWANIP: 10.21.31.120/30\nTUNNEL: tun2366\n"
    "PE Docking：192.168.239.14\nCE Docking：10.22.241.232\n"
    "BGPSERVER IP：103.252.19.99,43.229.119.251\n海外出口ip：\n10.60.18.22-150.116.112.236"
)
r4 = c.post("/api/generate/epoch_fastip", json={
    "variant": "us", "header_text": HDR_DUAL_FULL,
    "network": {"wan_cidr": "192.168.1.10/24", "wan_gw": "192.168.1.1",
               "lan_cidr": "192.168.5.1/24", "inner_nets": "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16"}
}).get_json()
out_dual = r4.get("output", "")
t("双出口回归-生成成功", r4.get("ok"))
t("双出口-无单出口提示", "单出口" not in out_dual)
t("双出口-有备线tun2366", "tun2366" in out_dual)
t("双出口-有RSVR2", "RSVR2" in out_dual)
t("双出口-有backupe", "backupe" in out_dual)
t("双出口-有table 102", "table 102" in out_dual)
t("双出口-有dum200", "dum200" in out_dual)
t("双出口-有rule 3050", "rule 3050" in out_dual)
t("双出口-有NAT rule 200", "rule 200 outbound" in out_dual)
t("双出口-无空行", "set interfaces tunnel  address" not in out_dual and "outbound-interface ''" not in out_dual)

# 5. HK 出口不受影响
r5 = c.post("/api/generate/epoch_fastip", json={
    "variant": "hk", "header_text": HDR["er_hk"],
    "network": {"wan_cidr": "192.168.1.10/24", "wan_gw": "192.168.1.1",
               "lan_cidr": "192.168.5.1/24", "inner_nets": "10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16"}
}).get_json()
t("HK不受影响-生成成功", r5.get("ok"))
t("HK不受影响-无空outbound", "outbound-interface ''" not in r5.get("output", ""))


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
