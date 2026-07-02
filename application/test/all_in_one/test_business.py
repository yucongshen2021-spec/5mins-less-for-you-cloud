#!/usr/bin/env python3
"""业务级全场景测试 — 模拟用户完整操作流程"""
import sys, os, json
os.environ["TEST_MODE"] = "1"
import _bootstrap  # noqa: F401
from app import app, _load_module, _SCENARIO_LIST, init_worker

# test_client 环境手动初始化：预加载模块 + 快照 factory defaults
init_worker()

PASS = FAIL = 0
def t(name, ok):
    global PASS, FAIL
    if ok: PASS += 1; print(f"  [PASS] {name}")
    else: FAIL += 1; print(f"  [FAIL] {name}")

c = app.test_client()
# template/load、init-defaults 等接口对访客返回 403，测试需模拟已登录用户
c.environ_base["HTTP_X_USER_ID"] = "test-user-1"
c.environ_base["HTTP_X_USERNAME"] = "tester"
er_hk_hdr = "hostname:TEST-CE\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\nwanip:10.22.98.40/30\n对接IP:10.255.110.6\nLineID:609157A2\nPE:szd-ape3\ntunnel:vtun1214\nwanip:10.22.98.44/30\n对接IP:10.255.110.10"

# ═══ 1. 脚本生成 — 所有变体 ═══
print("=" * 50)
print("1. 脚本生成测试")
print("=" * 50)

TESTS = [
    ("ER HK", "/api/generate/epoch_fastip", {"variant":"hk","header_text":er_hk_hdr,"network":{}}, ["set epoch","set system host-name","set firewall"], 200, 230),
    ("ER US", "/api/generate/epoch_fastip", {"variant":"us","header_text":"LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\nPE 对接:192.168.247.17\n海外出口ip:\n10.60.44.28-218.32.88.83\n\nLineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\nPE Docking:192.168.239.12\nBGPSERVER IP:103.252.19.25,43.229.117.226\n海外出口ip:\n10.60.44.28-218.32.88.83","network":{}}, ["set epoch","set system host-name"], 250, 310),
    ("ER Flink", "/api/generate/epoch_fastip", {"variant":"flink","header_text":"预留IP:100.94.5.32/28\n预留IP:100.93.5.32/28","network":{}}, ["set track name flink"], 3, 30),
    ("USG US", "/api/generate/usg_fastip", {"variant":"us","header_text":"main IPSEC_PE: szd-ape2\nmain dial_ip: 121.14.82.235\nmain loopback: 10.18.12.57\nmain auth_id: 609157A1\nLineID:609157A1\nPE:lax1-fgpe1\nWANIP:10.22.98.40/30\nTUNNEL:tun1213\nPE对接:10.255.110.6\n出口ip:64.81.158.21\n\nbackup IPSEC_PE: szc-apebk2\nbackup dial_ip: 120.133.138.20\nbackup loopback: 10.18.14.21\nbackup auth_id: 609157A2\nLineID:609157A2\nPE:sjc1-fgpe1\nWANIP:10.22.32.60/30\nTUNNEL:tun2305\nPE对接:10.255.111.128\n出口ip:172.16.14.118","network":{}}, ["set firewall","ip address"], 100, 850),
    ("MPLS CN", "/api/generate/epoch_mpls", {"variant":"domestic","header_text":"LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\nPE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\nLineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\nPE 对接:192.168.253.80\nPE AS号:65531","network":{}}, ["set firewall","set protocols bgp","set interfaces"], 60, 160),
    ("AR OPS", "/api/generate/ar_sdwan", {"variant":"single_ops","header_text":"LineID:604604Hw1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1147\nwanip:10.40.232.248/30\nPE 对接:10.200.200.76\nCE 对接:10.50.131.16\n拨号PE:gzd-upe5\n对接IP:10.200.200.76\nLoopIP:10.50.131.16\n拨号ip:183.63.68.174\n秘钥:both-win\n\nLineID:604604Hw2\nPE:szd-upebk1\nTunnel:Tunnel0/0/1605\nwanip:10.30.115.252/30\nPE 对接:10.200.200.22\nCE 对接:10.120.47.20\n拨号PE:szd-upebk1\n对接IP:10.200.200.22\nLoopIP:10.120.47.20\n拨号ip:183.56.163.24\n秘钥:both-win","network":{}}, ["import ops","def ops_condition"], 50, 300),
]

for name, url, data, keywords, min_l, max_l in TESTS:
    r = c.post(url, json=data).get_json()
    o = r.get("output","") or r.get("ops_output","")
    lc = len(o.splitlines())
    kw_ok = all(k in o for k in keywords)
    range_ok = min_l <= lc <= max_l
    t(f"{name} 生成成功", r.get("ok"))
    t(f"{name} 关键字完整", kw_ok)
    t(f"{name} 行数合理({lc})", range_ok)

# ═══ 2. 参数修改反映到输出 ═══
print("\n" + "=" * 50)
print("2. 参数修改测试")
print("=" * 50)

# WAN IP change
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"wan_cidr":"192.168.1.10/24"}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"wan_cidr":"99.99.99.1/24"}}).get_json()
t("WAN IP改变输出不同", r1.get("output") != r2.get("output"))

# DHCP change
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"wan_dhcp":True,"lan_dhcp":True}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"wan_dhcp":False,"lan_dhcp":False}}).get_json()
t("DHCP改变输出不同", r1.get("output") != r2.get("output"))

# DNS change (USG)
r1 = c.post("/api/generate/usg_fastip", json={"variant":"us","header_text":"main IPSEC_PE: szd-ape2\nmain dial_ip: 121.14.82.235\nmain loopback: 10.18.12.57\nmain auth_id: 609157A1\nLineID:609157A1\nPE:lax1-fgpe1\nWANIP:10.22.98.40/30\nTUNNEL:tun1213\nPE对接:10.255.110.6\n出口ip:64.81.158.21","network":{"dns1":"1.1.1.1"}}).get_json()
t("USG DNS改变生效", "1.1.1.1" in r1.get("output",""))

# Inner nets change
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"inner_nets":"10.10.10.0/24"}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"inner_nets":"172.16.0.0/12"}}).get_json()
t("内网段改变输出不同", r1.get("output") != r2.get("output"))

# Bypass change (ER HK)
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"bypass":True}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"bypass":False}}).get_json()
t("ER HK 旁挂ON≠OFF", r1.get("output") != r2.get("output"))

# Bypass change (ER US)
us_hdr = "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\nPE 对接:192.168.247.17\n海外出口ip:\n10.60.44.28-218.32.88.83\n\nLineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\nPE Docking:192.168.239.12\nBGPSERVER IP:103.252.19.25,43.229.117.226\n海外出口ip:\n10.60.44.28-218.32.88.83"
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"us","header_text":us_hdr,"network":{"bypass":True}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"us","header_text":us_hdr,"network":{"bypass":False}}).get_json()
t("ER US 旁挂ON≠OFF", r1.get("output") != r2.get("output"))

# Bypass change (MPLS)
mpls_hdr = "LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\nPE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\nLineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\nPE 对接:192.168.253.80\nPE AS号:65531"
r1 = c.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":mpls_hdr,"network":{"bypass":True}}).get_json()
r2 = c.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":mpls_hdr,"network":{"bypass":False}}).get_json()
t("MPLS 旁挂ON≠OFF", r1.get("output") != r2.get("output"))

# ═══ 3. 自定义模板热更新 ═══
print("\n" + "=" * 50)
print("3. 模板热更新测试")
print("=" * 50)

# Save modified template
r = c.post('/api/template/save', json={'key':'Epoch FastIP · HK 香港出口','header':er_hk_hdr,'mapping':'','template':'# CUSTOM_TEMPLATE_V2\nset system host-name CUSTOM-TEST\n'}).get_json()
t("保存自定义模板", r.get("ok"))

# Generate must use new template
r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{}}).get_json()
t("生成使用自定义模板", "CUSTOM_TEMPLATE_V2" in r.get("output",""))

# Reset
r = c.post('/api/template/reset', json={'key':'Epoch FastIP · HK 香港出口'}).get_json()
t("重置模板", r.get("ok") and len(r.get("template","")) > 1000)

# Generate after reset — must not have CUSTOM
r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{}}).get_json()
t("重置后不含自定义", "CUSTOM_TEMPLATE_V2" not in r.get("output",""))

# ═══ 4. 初始化参数持久化 ═══
print("\n" + "=" * 50)
print("4. 初始化参数持久化测试")
print("=" * 50)

# Save DHCP=True
r = c.post('/api/init-defaults/save', json={'key':'Epoch FastIP · HK 香港出口','values':{'DEFAULT_WAN_DHCP':True,'DEFAULT_LAN_DHCP':True}}).get_json()
t("保存DHCP=True", r.get("ok"))

# Verify globals
er = _load_module('er_fastip_2in1_v8.py')
t("模块DEFAULT_WAN_DHCP=True", er.get('DEFAULT_WAN_DHCP') == True)

# Generate with DHCP=True → verify output differs
r1 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"wan_dhcp":True,"lan_dhcp":True}}).get_json()
r2 = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":er_hk_hdr,"network":{"wan_dhcp":False,"lan_dhcp":False}}).get_json()
t("DHCP初始化生效(ON≠OFF)", r1.get("output") != r2.get("output"))

# Reset init
r = c.post('/api/init-defaults/reset', json={'key':'Epoch FastIP · HK 香港出口'}).get_json()
t("重置初始化", r.get("ok") and r.get("values",{}).get('DEFAULT_WAN_DHCP') == False)

# ═══ 5. 模板编辑器全场景加载/预览 ═══
print("\n" + "=" * 50)
print("5. 模板编辑器全场景测试")
print("=" * 50)

for info in _SCENARIO_LIST:
    key = info["key"]; short = key[:45]
    r = c.post('/api/template/load', json={'key': key}).get_json()
    ok = r.get("ok") and len(r.get("header","")) > 0 and len(r.get("template","")) > 0 and len(r.get("mapping","")) > 0
    t(f"Load {short}", ok)

# ═══ 6. MPLS & AR 模板热更新 ═══
print("\n" + "=" * 50)
print("6. MPLS & AR 模板热更新测试")
print("=" * 50)

mpls_hdr = "LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\nPE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\nLineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\nPE 对接:192.168.253.80\nPE AS号:65531"

# MPLS domestic
r = c.post('/api/template/save', json={'key':'Epoch MPLS · 国内配置','header':mpls_hdr,'mapping':'','template':'# MPLS_DOMESTIC_CUSTOM\nset system host-name CUSTOM-MPLS-DOMESTIC\n'}).get_json()
t("MPLS国内 保存自定义模板", r.get("ok"))
r = c.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":mpls_hdr,"network":{}}).get_json()
t("MPLS国内 生成使用自定义模板", "MPLS_DOMESTIC_CUSTOM" in r.get("output",""))
r = c.post('/api/template/reset', json={'key':'Epoch MPLS · 国内配置'}).get_json()
t("MPLS国内 重置模板", r.get("ok") and len(r.get("template","")) > 100)
r = c.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":mpls_hdr,"network":{}}).get_json()
t("MPLS国内 重置后不含自定义", "MPLS_DOMESTIC_CUSTOM" not in r.get("output",""))

# MPLS overseas
r = c.post('/api/template/save', json={'key':'Epoch MPLS · 海外配置','header':mpls_hdr,'mapping':'','template':'# MPLS_OVERSEAS_CUSTOM\nset system host-name CUSTOM-MPLS-OVERSEAS\n'}).get_json()
t("MPLS海外 保存自定义模板", r.get("ok"))
r = c.post("/api/generate/epoch_mpls", json={"variant":"overseas","header_text":mpls_hdr,"network":{}}).get_json()
t("MPLS海外 生成使用自定义模板", "MPLS_OVERSEAS_CUSTOM" in r.get("output",""))
r = c.post('/api/template/reset', json={'key':'Epoch MPLS · 海外配置'}).get_json()
t("MPLS海外 重置模板", r.get("ok") and len(r.get("template","")) > 100)
r = c.post("/api/generate/epoch_mpls", json={"variant":"overseas","header_text":mpls_hdr,"network":{}}).get_json()
t("MPLS海外 重置后不含自定义", "MPLS_OVERSEAS_CUSTOM" not in r.get("output",""))

# AR single OPS
ar_hdr = "LineID:604604Hw1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1147\nwanip:10.40.232.248/30\nPE 对接:10.200.200.76\nCE 对接:10.50.131.16\n拨号PE:gzd-upe5\n对接IP:10.200.200.76\nLoopIP:10.50.131.16\n拨号ip:183.63.68.174\n秘钥:both-win\n\nLineID:604604Hw2\nPE:szd-upebk1\nTunnel:Tunnel0/0/1605\nwanip:10.30.115.252/30\nPE 对接:10.200.200.22\nCE 对接:10.120.47.20\n拨号PE:szd-upebk1\n对接IP:10.200.200.22\nLoopIP:10.120.47.20\n拨号ip:183.56.163.24\n秘钥:both-win"
r = c.post('/api/template/save', json={'key':'AR SD-WAN · 单机单WAN · OPS','header':ar_hdr,'mapping':'','template':'# AR_OPS_CUSTOM\n# custom ops template\n'}).get_json()
t("AR OPS 保存自定义模板", r.get("ok"))
r = c.post("/api/generate/ar_sdwan", json={"variant":"single_ops","header_text":ar_hdr,"network":{}}).get_json()
t("AR OPS 生成使用自定义模板", "AR_OPS_CUSTOM" in r.get("ops_output",""))
r = c.post('/api/template/reset', json={'key':'AR SD-WAN · 单机单WAN · OPS'}).get_json()
t("AR OPS 重置模板", r.get("ok") and len(r.get("template","")) > 100)
r = c.post("/api/generate/ar_sdwan", json={"variant":"single_ops","header_text":ar_hdr,"network":{}}).get_json()
t("AR OPS 重置后不含自定义", "AR_OPS_CUSTOM" not in r.get("ops_output",""))

# AR single Factory
r = c.post('/api/template/save', json={'key':'AR SD-WAN · 单机单WAN · Factory','header':ar_hdr,'mapping':'','template':'# AR_FACTORY_CUSTOM\n# custom factory config\n'}).get_json()
t("AR Factory 保存自定义模板", r.get("ok"))
r = c.post("/api/generate/ar_sdwan", json={"variant":"single_factory","header_text":ar_hdr,"network":{}}).get_json()
t("AR Factory 生成使用自定义模板", "AR_FACTORY_CUSTOM" in r.get("factory_output",""))
r = c.post('/api/template/reset', json={'key':'AR SD-WAN · 单机单WAN · Factory'}).get_json()
t("AR Factory 重置模板", r.get("ok") and len(r.get("template","")) > 100)

# ═══ 结果 ═══
print(f"\n{'='*50}")
print(f"结果: {PASS}/{PASS+FAIL} 通过, {FAIL} 失败")
