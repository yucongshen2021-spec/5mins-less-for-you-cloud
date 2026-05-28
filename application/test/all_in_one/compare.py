#!/usr/bin/env python3
"""全场景输出对比 — Web vs 桌面版（直接调用模块，无网络注入）"""
import json, sys, os, difflib
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401
from app import app, _SCENARIO_LIST, _load_module

TODAY = datetime.now().strftime("%Y-%m-%d")
LOG_DIR = Path(__file__).resolve().parent / "logs"
WEB_DIR = LOG_DIR / f"{TODAY}_web"
DSK_DIR = LOG_DIR / f"{TODAY}_desktop"
WEB_DIR.mkdir(parents=True, exist_ok=True)
DSK_DIR.mkdir(parents=True, exist_ok=True)

# Sample data for each variant
SAMPLES = {
    "epoch_fastip+hk": "hostname:TEST-CE\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\nwanip:10.22.98.40/30\n对接IP:10.255.110.6\nLineID:609157A2\nPE:szd-ape3\ntunnel:vtun1214\nwanip:10.22.98.44/30\n对接IP:10.255.110.10",
    "epoch_fastip+us": "LineID:609169A1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1165\nwanip:10.55.14.64/30\nPE 对接:192.168.247.17\nCE 对接:10.23.0.122\nPE:gzd-acvpnpe2\nTunnel:vtun17953\nwanip:10.23.0.120/30\nPE 对接:183.63.68.171\n\nLineID:609169A5\nPE:twb-natpe2\nWANIP:10.21.32.124/30\nTUNNEL:tun1267\nPE Docking:192.168.239.12\nBGPSERVER IP:103.252.19.25,43.229.117.226\n海外出口ip:\n10.60.44.28-218.32.88.83\n\nLineID:609169A6\nPE:twb-natpe1\nWANIP:10.21.31.120/30\nTUNNEL:tun2366\nPE Docking:192.168.239.14\nCE Docking:10.22.241.232\nBGPSERVER IP:103.252.19.99,43.229.119.251\n海外出口ip:\n10.60.18.22-150.116.112.236",
    "epoch_fastip+flink": "预留IP:100.94.5.32/28\n预留IP:100.93.5.32/28\n预留IP:100.92.5.32/28",
    "usg_fastip+us": "main IPSEC_PE: szd-ape2\nmain dial_ip: 121.14.82.235\nmain loopback: 10.18.12.57\nmain auth_id: 609157A1\nmain psk: both-win\n\nLineID:609157A1\nPE:lax1-fgpe1\nWANIP:10.22.98.40/30\nTUNNEL:tun1213\nPE对接:10.255.110.6\nCE对接:10.18.12.57\n出口ip:64.81.158.21\n\nbackup IPSEC_PE: szc-apebk2\nbackup dial_ip: 120.133.138.20\nbackup loopback: 10.18.14.21\nbackup auth_id: 609157A2\nbackup psk: both-win\n\nLineID:609157A2\nPE:sjc1-fgpe1\nWANIP:10.22.32.60/30\nTUNNEL:tun2305\nPE对接:10.255.111.128\n出口ip:172.16.14.118",
    "usg_fastip+hk": "main IPSEC_PE: bja-ape1\nmain dial_ip: 118.193.100.10\nmain loopback: 10.18.5.13\nmain auth_id: 608810A10\nmain psk: both-win\n\nLineID:608810A10\nPE:hkg1-fgpe3\nWANIP:10.22.98.40/30\nTUNNEL:tun1040\nPE对接:10.255.110.48\nCE对接:10.18.5.13\n出口ip:103.91.158.227",
    "usg_fastip+flink": "LineID:609204A4\nPE:hza-upe1\nTunnel:Tunnel0/0/1505\nwanip:10.40.147.236/30\nPE 对接:10.255.110.35\nCE 对接:10.18.2.89\nPE AS号:65120\n\nLineID:609204A5\nPE:wha-upebk3\nTunnel:Tunnel0/0/1228\nwanip:10.40.223.4/30\nPE 对接:10.255.111.152\nCE 对接:10.18.14.65\nPE AS号:65185",
    "epoch_mpls+domestic": "LineID:609291A1\nPE:nna-upe1\nTunnel:Tunnel0/0/1030\nwanip:10.40.79.92/30\nPE 对接:192.168.204.1\nCE 对接:10.40.91.42\nPE AS号:65512\nPE:nna-ipsecgw1\nTunnel:vtun10013\nwanip:10.40.91.40/30\nPE 对接:180.142.110.241\n\nLineID:609291A2\nPE:szd-upebk2\nTunnel:Tunnel10447\nwanip:10.40.195.188/30\nPE 对接:192.168.253.80\nCE 对接:10.120.52.30\nPE AS号:65531\nPE:szd-acvpnpe2\nTunnel:vtun10209\nwanip:10.120.52.28/30\nPE 对接:202.46.225.106",
    "epoch_mpls+overseas": "LineID:609291B1\nPE:han2-vupe1\nTunnel:vtun1104\nwanip:10.40.252.148/30\nPE 对接:42.115.85.51\nPE AS号:65179\n\nLineID:609291B2\nPE:hkj-upe2\nTunnel:Tunnel0/0/1618\nwanip:10.33.62.160/30\nPE 对接:192.168.236.21\nCE 对接:10.55.18.78\nPE AS号:65532\nPE:hkj-ipsecgw2\nTunnel:vtun1176\nwanip:10.55.18.76/30\nPE 对接:103.48.141.29",
    "ar_sdwan+single_ops": "LineID:604604Hw1\nPE:gzd-upe5\nTunnel:Tunnel0/0/1147\nwanip:10.40.232.248/30\nPE 对接:10.200.200.76\nCE 对接:10.50.131.16\nPE AS号:65176\n拨号PE:gzd-upe5\n对接IP:10.200.200.76\nLoopIP:10.50.131.16\n拨号ip:183.63.68.174\n秘钥:both-win\n\nLineID:604604Hw2\nPE:szd-upebk1\nTunnel:Tunnel0/0/1605\nwanip:10.30.115.252/30\nPE 对接:10.200.200.22\nCE 对接:10.120.47.20\nPE AS号:65144\n拨号PE:szd-upebk1\n对接IP:10.200.200.22\nLoopIP:10.120.47.20\n拨号ip:183.56.163.24\n秘钥:both-win",
}

# Load module example data for New Exit / IPSec
er_ne = str(_load_module("er_fastip_2in1_v8.py").get("ER_NEW_EXIT_EXAMPLE", ""))
usg_ne = str(_load_module("usg_fastip_3in1_v5.py").get("USG_NEW_EXIT_EXAMPLE", ""))
mpls_ips = str(_load_module("er_mpls_v1.py").get("MPLS_IPSEC_EXAMPLE", ""))
SAMPLES["epoch_fastip+new_exit"] = er_ne
SAMPLES["usg_fastip+new_exit"] = usg_ne
SAMPLES["epoch_mpls+ipsec"] = mpls_ips

# Domain split uses no header, only network params
DS_NET = {"ER_DS_DOMAINS_DEFAULT":"google.com","ER_DS_ADDR_GROUP_DEFAULT":"to-US",
          "ER_DS_RULE_NUM_DEFAULT":"100","ER_DS_TABLE_NUM_DEFAULT":"139",
          "ER_DS_DNS1_DEFAULT":"209.244.0.3","ER_DS_ETH_DEFAULT":"eth0",
          "ER_DS_TABLE_NH_PRIMARY_DEFAULT":"2.2.2.2","ER_DS_STATIC32_PRIMARY_NH_DEFAULT":"10.22.15.185"}


def safe_name(name):
    return name.replace(" ", "_").replace("/", "-").replace("·", "-")

def gen_web(tool, variant, hdr, network=None):
    """Generate via web API"""
    with app.test_client() as c:
        r = c.post(f"/api/generate/{tool}", json={"variant":variant,"header_text":hdr,"network":network or {}}).get_json()
        if r.get("ok"):
            return r.get("output","")
        return f"# ERROR: {r.get('error','')}"

def gen_desktop(tool, variant, hdr):
    """Generate via direct module calls (simulating desktop with factory defaults)"""
    from app import _load_module

    if tool == "epoch_fastip":
        ns = _load_module("er_fastip_2in1_v8.py")
        if variant == "hk":
            r = ns["build_epoch_hk_format_dict"](hdr)
            d = r[0] if isinstance(r, tuple) else r
            return ns["TEMPLATE_EPOCH_HK"].format(**d) if d else f"# FAIL: {r[1]}"
        elif variant == "us":
            r = ns["build_epoch_us_format_dict"](hdr)
            d = r[0] if isinstance(r, tuple) else r
            return ns["TEMPLATE_EPOCH_US"].format(**d) if d else f"# FAIL: {r[1]}"
        elif variant == "flink":
            routes, err = ns["parse_er_flink_headers"](hdr)
            if err: return f"# FAIL: {err}"
            return ns["build_er_flink_config"](routes, "192.168.1.1", "192.168.1.2")
        elif variant == "new_exit":
            r = ns["parse_er_new_exit_blocks"](hdr)
            p = r[0] if isinstance(r, tuple) else r
            if not isinstance(p, dict): return "# FAIL: parse error"
            init_cfg = {"main_pe_next_hop":"192.168.1.1","main_dum_start":300,"main_nat_rule_start":300,
                        "bk_pe_next_hop":"192.168.1.2","bk_dum_start":400,"bk_nat_rule_start":400,
                        "main_nat_source_cidr":"","bk_nat_source_cidr":""}
            return ns["build_er_new_exit_config"](p, init_cfg)
        elif variant == "domain_split":
            d = DS_NET.copy()
            fn = ns.get("er_ds_template_preview_extras")
            if fn:
                try: d.update(fn(d))
                except: pass
            return ns.get("TEMPLATE_ER_DOMAIN_SPLIT_VISUAL","").format(**d) if d else ""

    elif tool == "usg_fastip":
        ns = _load_module("usg_fastip_3in1_v5.py")
        if variant == "us":
            r = ns["build_usg_us_format_dict"](hdr)
            d = r[0] if isinstance(r, tuple) else r
            return ns["TEMPLATE_USG_NONHK"].format(**d) if d else f"# FAIL: {r[1]}"
        elif variant == "hk":
            r = ns["build_usg_hk_format_dict"](hdr)
            d = r[0] if isinstance(r, tuple) else r
            return ns["TEMPLATE_USG_HK"].format(**d) if d else f"# FAIL: {r[1]}"
        elif variant == "flink":
            p = ns["parse_feilink_data"](hdr)
            d = {}
            if isinstance(p, dict):
                for sec in ("main","backup"):
                    sub = p.get(sec,{})
                    if isinstance(sub, dict):
                        for k,v in sub.items(): d[f"{sec}_{k}"] = v
                for i,r in enumerate(p.get("reserved_ips",[])[:3]):
                    if isinstance(r, dict):
                        cidr = str(r.get("cidr",""))
                        d[f"reserved{i+1}_net"] = cidr.split("/")[0] if "/" in cidr else cidr
                        d[f"reserved{i+1}_mask"] = cidr.split("/")[1] if "/" in cidr else ""
            for i in (1,2,3): d.setdefault(f"reserved{i}_net",""); d.setdefault(f"reserved{i}_mask","")
            d.setdefault("USG_FL_MAIN_TUN_DEFAULT","3000"); d.setdefault("USG_FL_BK_TUN_DEFAULT","4000")
            return ns["TEMPLATE_USG_FLINK_VISUAL"].format(**d) if d else ""
        elif variant == "new_exit":
            r = ns["parse_usg_new_exit_blocks"](hdr)
            p = r[0] if isinstance(r, tuple) else r
            if not isinstance(p, dict): return "# FAIL: parse error"
            init_cfg = {"main_tun":1001,"bk_tun":1002,"main_loop_start":111,"bk_loop_start":211,
                        "main_nqa":"main2","bk_nqa":"backup2"}
            d = ns["build_usg_new_exit_format_dict"](p, init_cfg)
            return ns["TEMPLATE_USG_NEW_EXIT_VISUAL"].format(**d) if d else ""

    elif tool == "epoch_mpls":
        ns = _load_module("er_mpls_v1.py")
        from app import _inject_network_to_parsed as _inj_mpls
        if variant in ("domestic", "overseas"):
            p = ns["parse_epoch_mpls"](hdr)
            p["config_type"] = "国内" if variant == "domestic" else "海外"
            _inj_mpls(ns, p)  # inject wan_if etc.
            return ns["generate_mpls_config"](p)
        elif variant == "ipsec":
            d = ns["build_mpls_ipsec_format_dict"](hdr, hostname="", net=None)
            wan_cidr = str(ns.get("DEFAULT_WAN_CIDR","192.168.1.10/24"))
            wan_gw = str(ns.get("DEFAULT_WAN_GW","192.168.1.1"))
            lan_cidr = str(ns.get("DEFAULT_LAN_CIDR","192.168.5.1/24"))
            weth = str(ns.get("DEFAULT_WAN_ETH","0"))
            leth = str(ns.get("DEFAULT_LAN_ETH","1"))
            blocks = ns["build_wan_lan_blocks"](f"eth{weth}",False,wan_cidr,wan_gw,f"eth{leth}",True,lan_cidr,False)
            if isinstance(blocks, dict): d.update(blocks)
            _inj_mpls(ns, d)
            return ns["generate_mpls_ipsec_config"](d)

    elif tool == "ar_sdwan":
        ns = _load_module("ar_sdwan_zihuan_v4.py")
        p = ns["parse_ar_sdwan_text"](hdr)
        init = {"mode":"ops","device_type":"single","device_role":"pri"}
        return ns["render_ops_script"](p, init)

    return "# UNSUPPORTED"


# ── Run ──
results = []
variants = [
    ("epoch_fastip","hk"), ("epoch_fastip","us"), ("epoch_fastip","flink"),
    ("epoch_fastip","new_exit"), ("epoch_fastip","domain_split"),
    ("usg_fastip","us"), ("usg_fastip","hk"), ("usg_fastip","flink"),
    ("usg_fastip","new_exit"),
    ("epoch_mpls","domestic"), ("epoch_mpls","overseas"), ("epoch_mpls","ipsec"),
    ("ar_sdwan","single_ops"),
]

print("=" * 60)
print(f"全场景输出对比 — {TODAY}")
print(f"Web: {WEB_DIR}")
print(f"Desktop: {DSK_DIR}")
print("=" * 60)

for tool, variant in variants:
    key = f"{tool}+{variant}"
    hdr = SAMPLES.get(key, "")
    net = DS_NET if variant == "domain_split" else {}
    name = safe_name(f"{tool}_{variant}")

    print(f"\n{name}:")
    # Web
    try:
        w_out = gen_web(tool, variant, hdr, net)
        (WEB_DIR / f"{name}.txt").write_text(w_out, encoding="utf-8")
        w_lines = len(w_out.splitlines())
        print(f"  Web:     {w_lines} lines")
    except Exception as e:
        w_out = f"# EXCEPTION: {e}"
        w_lines = 0
        (WEB_DIR / f"{name}.txt").write_text(w_out, encoding="utf-8")
        print(f"  Web:     ERROR {e}")

    # Desktop
    try:
        d_out = gen_desktop(tool, variant, hdr)
        (DSK_DIR / f"{name}.txt").write_text(d_out, encoding="utf-8")
        d_lines = len(d_out.splitlines())
        print(f"  Desktop: {d_lines} lines")
    except Exception as e:
        d_out = f"# EXCEPTION: {e}"
        d_lines = 0
        (DSK_DIR / f"{name}.txt").write_text(d_out, encoding="utf-8")
        print(f"  Desktop: ERROR {e}")

    # Compare
    diff = abs(w_lines - d_lines)
    if w_lines == d_lines:
        # Deeper comparison: check if content is identical
        if w_out == d_out:
            status = "IDENTICAL"
        else:
            ratio = difflib.SequenceMatcher(None, w_out, d_out).ratio()
            status = f"DIFF {ratio:.1%}"
    else:
        status = f"DIFF lines ({w_lines} vs {d_lines})"

    print(f"  -> {status}")
    results.append({"name": name, "web_lines": w_lines, "desktop_lines": d_lines, "status": status})

# Summary
print(f"\n{'='*60}")
identical = sum(1 for r in results if r["status"] == "IDENTICAL")
close = sum(1 for r in results if "DIFF" in r["status"] and "%" in r["status"])
diff = len(results) - identical - close
print(f"IDENTICAL: {identical}  DIFFER: {diff}")

report = {"date": TODAY, "results": results}
(LOG_DIR / f"compare_{TODAY}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
