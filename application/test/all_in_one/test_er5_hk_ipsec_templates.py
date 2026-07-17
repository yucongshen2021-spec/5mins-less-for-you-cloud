"""ER 5.0 香港出口 IPSec - 模板编辑器生命周期测试"""
import _bootstrap  # noqa: F401
from app import app, init_worker

init_worker()

client = app.test_client()
client.environ_base["HTTP_X_USER_ID"] = "test-user-1"
client.environ_base["HTTP_X_USERNAME"] = "tester"
SCENARIO_KEY = "Epoch FastIP 5.0 · HK 香港出口 · IPSec"


def test_template_load():
    r = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    data = r.get_json()
    assert data["ok"], f"Load failed: {data.get('error', '')}"
    assert len(data["template"]) > 500
    assert len(data["header"]) > 50
    assert len(data["mapping"]) > 100


def test_template_preview():
    r_load = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    load_data = r_load.get_json()
    assert load_data["ok"]
    r = client.post("/api/template/preview", json={
        "key": SCENARIO_KEY,
        "header": load_data["header"],
        "template": load_data["template"]
    })
    data = r.get_json()
    assert data["ok"], f"Preview failed: {data.get('error', '')}"
    output = data.get("output", "")
    assert len(output) > 500
    assert "{hostname}" not in output
    assert "{hkip}" not in output


def test_template_save_and_reset():
    r_orig = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    orig = r_orig.get_json()
    modified_header = orig["header"] + "\n# test comment"
    r_save = client.post("/api/template/save", json={
        "key": SCENARIO_KEY,
        "header": modified_header,
        "mapping": orig["mapping"],
        "template": orig["template"]
    })
    assert r_save.get_json()["ok"]
    r_mod = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    mod = r_mod.get_json()
    assert "# test comment" in mod["header"]
    r_reset = client.post("/api/template/reset", json={"key": SCENARIO_KEY})
    assert r_reset.get_json()["ok"]
    r_after = client.post("/api/template/load", json={"key": SCENARIO_KEY})
    after = r_after.get_json()
    assert "# test comment" not in after["header"]


def test_scenario_in_list():
    r = client.get("/api/scenarios")
    data = r.get_json()
    assert data["ok"]
    keys = [s["key"] for s in data["scenarios"]]
    assert SCENARIO_KEY in keys


def test_scenario_in_tree():
    r = client.get("/api/scenarios")
    data = r.get_json()
    assert data["ok"]
    def find_key(nodes):
        for n in nodes:
            if n.get("key") == SCENARIO_KEY:
                return True
            if "children" in n:
                if find_key(n["children"]):
                    return True
        return False
    assert find_key(data["tree"]), f"{SCENARIO_KEY} not found in tree"
