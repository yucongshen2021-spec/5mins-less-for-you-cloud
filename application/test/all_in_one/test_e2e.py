"""端到端测试 — 模拟用户完整操作流程"""
import sys, os
import _bootstrap  # noqa: F401
from app import app, _load_module

PASS = FAIL = 0

def t(name, ok):
    global PASS, FAIL
    if ok:
        PASS += 1; print(f"  [PASS] {name}")
    else:
        FAIL += 1; print(f"  [FAIL] {name}")

c = app.test_client()
hdr = "hostname:TEST\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\nwanip:10.22.98.40/30"

print("=" * 50)
print("1. DHCP 同步测试")
print("=" * 50)

# Step 1: Save DHCP=True via init panel
r = c.post('/api/init-defaults/save', json={
    'key': 'Epoch FastIP · HK 香港出口',
    'values': {'DEFAULT_WAN_DHCP': True, 'DEFAULT_LAN_DHCP': True}
}).get_json()
t("1a 保存DHCP=True", r.get('ok'))

# Step 2: Verify module globals updated
er = _load_module('er_fastip_2in1_v8.py')
t("1b 模块globals WAN_DHCP=True", er.get('DEFAULT_WAN_DHCP') == True)

# Step 3: Generate with DHCP=True (simulating form values from ldInitForm)
r = c.post('/api/generate/epoch_fastip', json={
    'variant':'hk','header_text':hdr,
    'network':{'wan_dhcp':True,'lan_dhcp':True}
}).get_json()
o_dhcp_on = r.get('output','')
t("1c DHCP=True 生成成功", r.get('ok'))

# Step 4: Generate with DHCP=False
r = c.post('/api/generate/epoch_fastip', json={
    'variant':'hk','header_text':hdr,
    'network':{'wan_dhcp':False,'lan_dhcp':False}
}).get_json()
o_dhcp_off = r.get('output','')
t("1d DHCP=False 生成成功", r.get('ok'))

# Step 5: Outputs MUST differ
t("1e DHCP ON≠OFF (输出不同)", o_dhcp_on != o_dhcp_off)
t("1f DHCP ON行数", len(o_dhcp_on.splitlines()) > 0)
t("1g DHCP OFF行数", len(o_dhcp_off.splitlines()) > 0)

print(f"\nDHCP ON lines: {len(o_dhcp_on.splitlines())}, OFF: {len(o_dhcp_off.splitlines())}")

print("\n" + "=" * 50)
print("2. 模板热更新测试")
print("=" * 50)

# Step 1: Get original template
r = c.post('/api/template/load', json={'key':'Epoch FastIP · HK 香港出口'}).get_json()
orig_tpl = r.get('template','')
t("2a 加载原始模板", len(orig_tpl) > 1000)

# Step 2: Save modified template
test_tpl = "# TEST MODIFIED TEMPLATE\nset system host-name TEST-HOTUPDATE\n"
r = c.post('/api/template/save', json={
    'key':'Epoch FastIP · HK 香港出口',
    'header':hdr, 'mapping':'', 'template':test_tpl
}).get_json()
t("2b 保存修改模板", r.get('ok'))

# Step 3: Generate — MUST use modified template
r = c.post('/api/generate/epoch_fastip', json={
    'variant':'hk','header_text':hdr,'network':{}
}).get_json()
gen_out = r.get('output','')
t("2c 生成使用新模板", 'HOTUPDATE' in gen_out)

# Step 4: Reset template
r = c.post('/api/template/reset', json={'key':'Epoch FastIP · HK 香港出口'}).get_json()
reset_tpl = r.get('template','')
t("2d 重置模板", r.get('ok') and len(reset_tpl) > 1000)

# Step 5: Generate after reset — must NOT have MODIFIED
r = c.post('/api/generate/epoch_fastip', json={
    'variant':'hk','header_text':hdr,'network':{}
}).get_json()
gen_after = r.get('output','')
t("2e 重置后生成不含HOTUPDATE", 'HOTUPDATE' not in gen_after)
t("2f 重置后生成含set epoch", 'set epoch' in gen_after)

# Clean up
c.post('/api/template/reset', json={'key':'Epoch FastIP · HK 香港出口'})

print("\n" + "=" * 50)
print("3. 初始化参数完整链路测试")
print("=" * 50)

# Step 1: Save WAN IP + DHCP + DNS
r = c.post('/api/init-defaults/save', json={
    'key': 'Epoch FastIP · HK 香港出口',
    'values': {'DEFAULT_WAN_CIDR': '10.99.99.1/24', 'DEFAULT_WAN_GW': '10.99.99.254',
               'DEFAULT_WAN_DHCP': False, 'DEFAULT_LAN_CIDR': '172.16.0.1/24'}
}).get_json()
t("3a 保存自定义网络参数", r.get('ok'))

# Step 2: Generate with these values
r = c.post('/api/generate/epoch_fastip', json={
    'variant':'hk','header_text':hdr,
    'network':{'wan_cidr':'10.99.99.1/24','wan_gw':'10.99.99.254',
               'lan_cidr':'172.16.0.1/24','wan_dhcp':False}
}).get_json()
gen = r.get('output','')
t("3b 生成成功", r.get('ok'))
t("3c WAN IP在输出中", '10.99.99' in gen)
t("3d LAN IP在输出中", '172.16.0' in gen)

# Clean up
c.post('/api/init-defaults/reset', json={'key':'Epoch FastIP · HK 香港出口'})

print("\n" + "=" * 50)
print(f"\n结果: {PASS}/{PASS+FAIL} 通过, {FAIL} 失败")
