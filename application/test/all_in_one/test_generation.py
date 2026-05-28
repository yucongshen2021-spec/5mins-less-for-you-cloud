"""正式页面生成测试 — 16 个变体"""
from common import *
import common as cm

def test():
    global PASS, FAIL
    print("\n=== 正式页面生成测试 ===\n")
    with app.test_client() as c:
        # ── Epoch FastIP ──
        r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":ER_HK,"network":{}}).get_json()
        check_output(r, "ER_HK", 200, ["set epoch","set system host-name","set firewall","set protocols bgp"])
        t("ER HK 生成", lambda: None)

        r = c.post("/api/generate/epoch_fastip", json={"variant":"us","header_text":ER_US,"network":{}}).get_json()
        check_output(r, "ER_US", 250, ["set epoch","set system host-name","set firewall","set protocols bgp"])
        t("ER US 生成", lambda: None)

        r = c.post("/api/generate/epoch_fastip", json={"variant":"flink","header_text":ER_FLINK,"network":{}}).get_json()
        check_output(r, "ER_Flink", 3, ["set protocols static route"])
        t("ER Flink 生成", lambda: None)

        r = c.post("/api/generate/epoch_fastip", json={"variant":"new_exit","header_text":er_ne_data,"network":{}}).get_json()
        check_output(r, "ER_NewExit", 10, ["set interfaces tunnel"])
        t("ER New Exit 生成", lambda: None)

        r = c.post("/api/generate/epoch_fastip", json={"variant":"domain_split","header_text":"",
            "network":{"ER_DS_DOMAINS_DEFAULT":"google.com","ER_DS_ADDR_GROUP_DEFAULT":"to-US",
            "ER_DS_RULE_NUM_DEFAULT":"100","ER_DS_TABLE_NUM_DEFAULT":"139",
            "ER_DS_DNS1_DEFAULT":"209.244.0.3","ER_DS_ETH_DEFAULT":"eth0",
            "ER_DS_TABLE_NH_PRIMARY_DEFAULT":"2.2.2.2","ER_DS_STATIC32_PRIMARY_NH_DEFAULT":"10.22.15.185"}}).get_json()
        check_output(r, "ER_DomainSplit", 3, ["sudo tee","EOF"])
        t("ER Domain Split 生成", lambda: None)

        # ── USG FastIP ──
        r = c.post("/api/generate/usg_fastip", json={"variant":"us","header_text":USG_US,"network":{}}).get_json()
        check_output(r, "USG_US", 80, ["set firewall","ip address"])
        t("USG US 生成", lambda: None)

        r = c.post("/api/generate/usg_fastip", json={"variant":"hk","header_text":USG_HK,"network":{}}).get_json()
        check_output(r, "USG_HK", 80, ["set firewall","ip address"])
        t("USG HK 生成", lambda: None)

        r = c.post("/api/generate/usg_fastip", json={"variant":"flink","header_text":USG_FL,"network":{}}).get_json()
        check_output(r, "USG_Flink", 3, ["interface Tunnel"])
        t("USG Flink 生成", lambda: None)

        r = c.post("/api/generate/usg_fastip", json={"variant":"new_exit","header_text":usg_ne_data,"network":{}}).get_json()
        check_output(r, "USG_NewExit", 5, ["interface Tunnel"])
        check_output(r, "USG_NewExit", 5, ["interface Tunnel"])
        t("USG New Exit 生成", lambda: None)

        # ── Epoch MPLS ──
        r = c.post("/api/generate/epoch_mpls", json={"variant":"domestic","header_text":MPLS_CN,"network":{}}).get_json()
        check_output(r, "MPLS_CN", 60, ["set firewall","set protocols bgp","set interfaces"])
        t("MPLS CN 生成", lambda: None)

        r = c.post("/api/generate/epoch_mpls", json={"variant":"overseas","header_text":MPLS_OV,"network":{}}).get_json()
        check_output(r, "MPLS_OV", 50, ["set firewall","set protocols bgp","set interfaces"])
        t("MPLS OV 生成", lambda: None)

        r = c.post("/api/generate/epoch_mpls", json={"variant":"ipsec","header_text":mpls_ips_data,"network":{}}).get_json()
        check_output(r, "MPLS_IPSec", 40, ["set firewall","set interfaces","set vpn ipsec"])
        t("MPLS IPSec 生成", lambda: None)

        # ── AR SD-WAN ──
        r = c.post("/api/generate/ar_sdwan", json={"variant":"single_ops","header_text":AR_DATA,"network":{}}).get_json()
        ar_o = r.get("ops_output") or r.get("output", "")
        def _ar1(): assert ok(r) and len(ar_o.splitlines()) >= 2, f"AR OPS {len(ar_o.splitlines())} lines"
        save_sample("AR_Single_OPS", ar_o)
        t("AR Single OPS 生成", _ar1)

        r = c.post("/api/generate/ar_sdwan", json={"variant":"dual_pri_ops","header_text":AR_DATA,"network":{}}).get_json()
        ar_d = r.get("ops_output") or r.get("output", "")
        def _ar2(): assert ok(r) and len(ar_d.splitlines()) >= 2, f"AR Dual {len(ar_d.splitlines())} lines"
        save_sample("AR_Dual_Pri_OPS", ar_d)
        t("AR Dual Pri OPS 生成", _ar2)


if __name__ == "__main__":
    test()
    total = cm.PASS + cm.FAIL
    print(f"\n生成测试: {cm.PASS}/{total} 通过, {cm.FAIL} 失败")
    save_report("generation")
