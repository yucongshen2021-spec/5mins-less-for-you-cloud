"""共享测试工具 — sample data, check helpers, app loader"""
import json, sys, os
from pathlib import Path
from datetime import datetime

import _bootstrap  # noqa: F401 — sets sys.path & TEST_MODE
from app import app, _SCENARIO_LIST, _load_module

# Re-export for test files
__all__ = ["app","_SCENARIO_LIST","_load_module","t","ok","out","lines","check_output","save_sample","save_report",
           "ER_HK","ER_US","ER_FLINK","USG_US","USG_HK","USG_FL","MPLS_CN","MPLS_OV","AR_DATA",
           "er_ne_data","usg_ne_data","mpls_ips_data","PASS","FAIL","RESULTS","LOG_DIR","logged_client"]

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

RESULTS = []; PASS = FAIL = 0

def t(name, fn):
    global PASS, FAIL
    try:
        fn(); PASS += 1
        RESULTS.append({"name": name, "status": "PASS"})
        print(f"  [PASS] {name}")
    except AssertionError as e:
        FAIL += 1; RESULTS.append({"name": name, "status": "FAIL", "error": str(e)})
        print(f"  [FAIL] {name}: {e}")
    except Exception as e:
        FAIL += 1; RESULTS.append({"name": name, "status": "ERROR", "error": f"{type(e).__name__}: {e}"})
        print(f"  [ERR]  {name}: {type(e).__name__}: {e}")
    return PASS, FAIL

def ok(r): return r.get("ok", False)
def out(r): return r.get("output", "")
def lines(r): return len(out(r).splitlines())

# 已登录测试 client：注入 X-User-Id（模拟 portal proxy 转发的已登录用户）。
# template/load、init-defaults 等接口对访客(user_id 为空)返回 403，测试需登录态。
_TEST_UID = "test-user-1"
def logged_client():
    c = app.test_client()
    c.environ_base["HTTP_X_USER_ID"] = _TEST_UID
    c.environ_base["HTTP_X_USERNAME"] = "tester"
    return c

def save_sample(name, output):
    fname = name.replace(" ", "_").replace("/", "-").replace("·", "-") + ".txt"
    (LOG_DIR / fname).write_text(output, encoding="utf-8")

def check_output(r, name, min_lines=10, must_have=None):
    assert ok(r), f"API returned ok=False: {r.get('error','')}"
    o = out(r)
    assert o.strip(), f"empty output"
    lc = len(o.splitlines())
    assert lc >= min_lines, f"only {lc} lines (expected >= {min_lines})"
    if must_have:
        for kw in must_have:
            assert kw in o, f"missing required keyword '{kw}'"
    save_sample(name, o)

def save_report(prefix="test"):
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    rdir = Path(__file__).resolve().parent / "results"
    rdir.mkdir(exist_ok=True)
    report = {"timestamp": ts, "pass": PASS, "fail": FAIL, "total": PASS + FAIL, "results": RESULTS}
    p = rdir / f"{prefix}_{ts}.json"
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告: {p}")
    return p

# ═══════════════════════════════════════════════════════════════
# Sample data
# ═══════════════════════════════════════════════════════════════
ER_HK = ("hostname:TEST-CE\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\n"
         "wanip:10.22.98.40/30\n对接IP:10.255.110.6\n"
         "LineID:609157A2\nPE:szd-ape3\ntunnel:vtun1214\nwanip:10.22.98.44/30\n对接IP:10.255.110.10")

ER_US = ("LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\n"
         "PE 对接:192.168.247.17\nCE 对接:10.23.0.122\n"
         "PE:gzd-acvpnpe2\nTunnel:vtun17953\nwanip:10.23.0.120/30\nPE 对接:183.63.68.171\n\n"
         "LineID:609169A2\nPE:dgb-upebk2\nTunnel:Tunnel0/0/1998\nwanip:10.40.209.220/30\n"
         "PE 对接:192.168.251.100\nCE 对接:10.30.167.202\n"
         "PE:dgb-acvpnpe2\nTunnel:vtun50057\nwanip:10.30.167.200/30\nPE 对接:121.12.128.254\n\n"
         "LineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\n"
         "PE Docking:192.168.239.12\nCE Docking:10.22.241.232\nBGPSERVER IP:103.252.19.25,43.229.117.226\n"
         "海外出口ip:\n10.60.44.28-218.32.88.83\n\n"
         "LineID:609169A6\nPE:twb-natpe1\nWANIP:10.21.31.120/30\nTUNNEL:tun2366\n"
         "PE Docking:192.168.239.14\nCE Docking:10.22.241.232\nBGPSERVER IP:103.252.19.99,43.229.119.251\n"
         "海外出口ip:\n10.60.18.22-150.116.112.236")

ER_FLINK = "预留IP:100.94.5.32/28\n预留IP:100.93.5.32/28\n预留IP:100.92.5.32/28"

USG_US = ("main IPSEC_PE: szd-ape2\nmain dial_ip: 121.14.82.235\nmain loopback: 10.18.12.57\n"
          "main auth_id: 609157A1\nmain psk: both-win\n\n"
          "LineID:609157A1\nPE:lax1-fgpe1\nWANIP:10.22.98.40/30\nTUNNEL:tun1213\n"
          "PE对接:10.255.110.6\nCE对接:10.18.12.57\n出口ip:64.81.158.21\n\n"
          "backup IPSEC_PE: szc-apebk2\nbackup dial_ip: 120.133.138.20\n"
          "backup loopback: 10.18.14.21\nbackup auth_id: 609157A2\nbackup psk: both-win\n\n"
          "LineID:609157A2\nPE:sjc1-fgpe1\nWANIP:10.22.32.60/30\nTUNNEL:tun2305\nPE对接:10.255.111.128\n出口ip:172.16.14.118")

USG_HK = ("main IPSEC_PE: bja-ape1\nmain dial_ip: 118.193.100.10\nmain loopback: 10.18.5.13\n"
          "main auth_id: 608810A10\nmain psk: both-win\n\n"
          "LineID:608810A10\nPE:hkg1-fgpe3\nWANIP:10.22.98.40/30\nTUNNEL:tun1040\n"
          "PE对接:10.255.110.48\nCE对接:10.18.5.13\n出口ip:103.91.158.227")

USG_FL = ("LineID:609526A3\nPE:szd-upe3\nTunnel:Tunnel0/0/2017\nwanip:10.40.99.44/30\n"
          "PE 对接:10.255.110.13\nCE 对接:10.18.16.58\n\n"
          "LineID:609526A4\nPE:szc-upe2\nTunnel:Tunnel0/0/1601\nwanip:10.40.194.24/30\n"
          "PE 对接:10.255.111.139\nCE 对接:10.18.14.165\n\n"
          "PE：szd-vupe6  FPE：F-ShenZhen4  预留IP：100.94.11.144/29\n"
          "PE：bja-vupe6  FPE：F-BeiJing4  预留IP：100.93.11.144/29\n"
          "PE：sha-vupe6  FPE：F-ShangHai4  预留IP：100.92.11.144/29")

MPLS_CN = ("LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\n"
           "PE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\n"
           "PE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\n"
           "LineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\n"
           "PE 对接:192.168.253.80\nCE 对接:10.120.52.30\nPE AS号:65531\n"
           "PE:szd-acvpnpe2\nTunnel:vtun10209\nwanip:10.120.52.28/30\nPE 对接:202.46.225.106")

MPLS_OV = ("LineID:609291B1\nPE:han2-vupe1\nTunnel:vtun1104\nwanip:10.40.252.148/30\n"
           "PE 对接:42.115.85.51\nPE AS号:65179\n\n"
           "LineID:609291B2\nPE:hkj-upe2\nTunnel:Tunnel0/0/1618\nwanip:10.33.62.160/30\n"
           "PE 对接:192.168.236.21\nCE 对接:10.55.18.78\nPE AS号:65532\n"
           "PE:hkj-ipsecgw2\nTunnel:vtun1176\nwanip:10.55.18.76/30\nPE 对接:103.48.141.29")

AR_DATA = ("LineID:604604Hw1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1147\nwanip:10.40.232.248/30\n"
           "PE 对接:10.200.200.76\nCE 对接:10.50.131.16\nPE AS号:65176\n"
           "拨号PE:gzd-upe5\n对接IP:10.200.200.76\nLoopIP:10.50.131.16\n"
           "拨号ip:183.63.68.174\n秘钥:both-win\n\n"
           "LineID:604604Hw2\nPE:szd-upebk1\nTunnel:Tunnel0/0/1605\nwanip:10.30.115.252/30\n"
           "PE 对接:10.200.200.22\nCE 对接:10.120.47.20\nPE AS号:65144\n"
           "拨号PE:szd-upebk1\n对接IP:10.200.200.22\nLoopIP:10.120.47.20\n"
           "拨号ip:183.56.163.24\n秘钥:both-win")

# 从模块加载的示例数据（New Exit / IPSec 需要原始格式）
er_ne_data = str(_load_module("er_fastip_2in1_v8.py").get("ER_NEW_EXIT_EXAMPLE", ""))
usg_ne_data = str(_load_module("usg_fastip_3in1_v5.py").get("USG_NEW_EXIT_EXAMPLE", ""))
mpls_ips_data = str(_load_module("er_mpls_v1.py").get("MPLS_IPSEC_EXAMPLE", ""))
