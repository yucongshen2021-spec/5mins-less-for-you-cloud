"""模板编辑器加载/重置/预览 — 20 场景"""
from common import *
import common as cm

def test():
    print("\n=== 模板编辑器测试 ===\n")
    smap = {"TEMPLATE_EPOCH_HK":ER_HK,"TEMPLATE_EPOCH_US":ER_US,
            "TEMPLATE_ER_FLINK_VISUAL":ER_FLINK,"TEMPLATE_ER_NEW_EXIT_VISUAL":er_ne_data,
            "TEMPLATE_USG_HK":USG_HK,"TEMPLATE_USG_NONHK":USG_US,
            "TEMPLATE_USG_FLINK_VISUAL":USG_FL,"TEMPLATE_USG_NEW_EXIT_VISUAL":usg_ne_data,
            "TEMPLATE_MPLS_DOMESTIC":MPLS_CN,"TEMPLATE_MPLS_OVERSEAS":MPLS_OV,
            "TEMPLATE_MPLS_IPSEC":mpls_ips_data}
    with logged_client() as c:
        for info in _SCENARIO_LIST:
            key = info["key"]; short = key[:48]; slot = info["tpl_slot"]

            r = c.post("/api/template/load", json={"key": key}).get_json()
            def _ld():
                assert ok(r), f"Load failed: {r.get('error','')}"
                assert r.get("header","").strip(), "Header empty"
                assert r.get("template","").strip(), "Template empty"
                assert r.get("mapping","").strip(), "Mapping empty"
            t(f"Load {short}", _ld)

            r = c.post("/api/template/reset", json={"key": key}).get_json()
            def _rs():
                assert ok(r), f"Reset failed: {r.get('error','')}"
                assert r.get("template","").strip(), "Reset empty"
            t(f"Reset {short}", _rs)

            sample = smap.get(slot, AR_DATA if "TEMPLATE_AR_" in slot else "test=value")
            r = c.post("/api/template/preview", json={"key":key,"header":sample,"template":""}).get_json()
            def _pv():
                assert ok(r), f"Preview failed: {r.get('error','')}"
                assert r.get("output","").strip(), "Preview empty"
            t(f"Preview {short}", _pv)


if __name__ == "__main__":
    test()
    total = cm.PASS + cm.FAIL
    print(f"\n模板测试: {cm.PASS}/{total} 通过, {cm.FAIL} 失败")
    save_report("templates")
