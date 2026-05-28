"""示例数据 & 备注说明 API 测试"""
from common import *
import common as cm

def test():
    print("\n=== API 端点测试 ===\n")
    with app.test_client() as c:
        for tool, var in [("epoch_fastip","hk"),("epoch_fastip","us"),("epoch_fastip","flink"),
                          ("epoch_fastip","new_exit"),("usg_fastip","us"),("usg_fastip","hk"),
                          ("usg_fastip","flink"),("usg_fastip","new_exit"),
                          ("epoch_mpls","domestic"),("epoch_mpls","overseas"),("epoch_mpls","ipsec"),
                          ("ar_sdwan","single_ops"),("ar_sdwan","dual_ops_pri")]:
            r = c.get(f"/api/examples/{tool}/{var}").get_json()
            def _ex():
                assert ok(r), f"Failed: {r.get('error','')}"
                assert len(r.get("example","")) > 20, f"Too short"
            t(f"Example {tool}/{var}", _ex)

        for tool, var in [("epoch_fastip","hk"),("usg_fastip","us"),
                           ("epoch_mpls","domestic"),("ar_sdwan","default")]:
            r = c.get(f"/api/notes/{tool}?variant={var}").get_json()
            def _nt():
                assert ok(r), "Failed"
                assert len(r.get("notes","")) > 30, "Too short"
            t(f"Notes {tool}/{var}", _nt)


if __name__ == "__main__":
    test()
    total = cm.PASS + cm.FAIL
    print(f"\nAPI 测试: {cm.PASS}/{total} 通过, {cm.FAIL} 失败")
    save_report("apis")
