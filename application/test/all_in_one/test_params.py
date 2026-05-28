"""网络参数注入验证"""
from common import *
import common as cm

def test():
    print("\n=== 网络参数注入验证 ===\n")
    with app.test_client() as c:
        r = c.post("/api/generate/epoch_fastip", json={"variant":"hk","header_text":ER_HK,
            "network":{"wan_cidr":"10.99.99.1/24","lan_cidr":"172.16.0.1/24","inner_nets":"10.0.0.0/8"}}).get_json()
        o = out(r)
        def _w(): assert "10.99.99" in o or "eth" in o, "WAN not in output"
        def _l(): assert "172.16.0" in o or "eth" in o, "LAN not in output"
        def _i(): assert "10.0.0.0/8" in o, "Inner nets not in output"
        t("WAN IP 注入", _w)
        t("LAN IP 注入", _l)
        t("内网段注入", _i)

        r = c.post("/api/generate/usg_fastip", json={"variant":"us","header_text":USG_US,"network":{"dns1":"1.1.1.1"}}).get_json()
        def _dns(): assert ok(r), f"USG DNS failed: {r.get('error','')}"
        t("USG DNS 注入", _dns)

        r = c.post("/api/generate/epoch_fastip", json={"variant":"flink","header_text":ER_FLINK,
            "network":{"ER_FL_MAIN_NH_DEFAULT":"99.99.99.99"}}).get_json()
        def _fl(): assert ok(r), f"Flink NH failed: {r.get('error','')}"
        t("Flink NH 注入", _fl)

        r = c.post("/api/generate/epoch_fastip", json={"variant":"domain_split","header_text":"",
            "network":{"ER_DS_ADDR_GROUP_DEFAULT":"TEST-GROUP","ER_DS_DNS1_DEFAULT":"9.9.9.9",
            "ER_DS_ETH_DEFAULT":"eth5","ER_DS_TABLE_NH_PRIMARY_DEFAULT":"5.5.5.5"}}).get_json()
        o = out(r)
        def _g(): assert "TEST-GROUP" in o, "Group missing"
        def _d(): assert "9.9.9.9" in o, "DNS missing"
        def _e(): assert "eth5" in o, "Interface missing"
        t("DS Group", _g)
        t("DS DNS", _d)
        t("DS Interface", _e)


if __name__ == "__main__":
    test()
    total = cm.PASS + cm.FAIL
    print(f"\n参数测试: {cm.PASS}/{total} 通过, {cm.FAIL} 失败")
    save_report("params")
