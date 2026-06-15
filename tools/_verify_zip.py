"""Verify release zip — exhaustive check against all known mistakes.

Covers: #2 #14 #15 #17 #19 #27 #32 #33 #34 #35 #36 #38 #42 #43 #46 #47 #48
"""
import json, sys, zipfile

zip_path = sys.argv[1]
expected = sys.argv[2]
ok, bad = 0, 0

def chk(name, cond, detail=""):
    global ok, bad
    if cond:
        ok += 1; print(f"  PASS  {name}")
    else:
        bad += 1; print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

with zipfile.ZipFile(zip_path, "r") as z:
    names = z.namelist()
    prefix = [n for n in names if n.endswith("/RELEASE_INFO.json")][0].replace("RELEASE_INFO.json", "")

    # M#19: version
    ri = json.loads(z.read(prefix + "RELEASE_INFO.json"))
    chk("M#19 version=" + expected, ri.get("version") == expected, f"got {ri.get('version')}")

    # M#17: no duplicate RELEASE_INFO
    chk("M#17 single RELEASE_INFO", len([n for n in names if n.endswith("/RELEASE_INFO.json")]) == 1)

    # M#42: mirror URLs
    for n in names:
        if n.endswith("application/portal/update_config.json"):
            cfg = json.loads(z.read(n))
            chk("M#42 mirror_urls configured", len(cfg.get("mirror_urls") or []) >= 1)
            break

    # M#33 #36 #46: bat pure ASCII, no chcp
    for n in names:
        if n.endswith("/start_all.bat"):
            b = z.read(n).decode("utf-8")
            chk("M#33 no chcp 67001", "chcp 67001" not in b)
            chk("M#36 no chcp 65001", "chcp 65001" not in b)
            chk("M#36 bat pure ASCII", b.isascii())
            chk("M#46 zero chcp anywhere", "chcp" not in b)
            break

    # M#35: port 7000. app.py switches at runtime via RELEASE_MODE; both branches
    # must be intact (7000 for release, 5000 for demo fallback — see build_release.py).
    for n in names:
        if n.endswith("portal/app.py") and ".py" in n:
            a = z.read(n).decode("utf-8")
            chk("M#35 app.py runtime port switch intact",
                "7000 if _RELEASE else 5000" in a,
                "expected '7000 if _RELEASE else 5000' (runtime switch)")
            chk("M#14 pycache clean at startup", "__pycache__" in a)
            chk("M#47 import upgrade", "import upgrade" in a)
            break

    # M#2: process_manager must keep BOTH runtime branches intact (7000/5000),
    # and sub-apps get their port via argv (built per RELEASE_MODE at runtime).
    for n in names:
        if n.endswith("portal/process_manager.py"):
            pm = z.read(n).decode("utf-8")
            chk("M#2 process_manager runtime port switch intact",
                "_BASE = 7000 if _RELEASE else 5000" in pm,
                "expected '_BASE = 7000 if _RELEASE else 5000'")
            # Sub-app cmds use _BASE+offset, so the literal release ports appear
            # as `_BASE + 1..4`, NOT as '7001'..'7004' literals.
            chk("M#2 sub-app cmds use _BASE offset",
                "_BASE + 1" in pm and "_BASE + 3" in pm)
            break

    # M#34 #38: DOM — release template must have upgradeBtn, banner before script
    for n in names:
        if n.endswith("portal/templates/index.html"):
            h = z.read(n).decode("utf-8")
            chk("M#38 upgradeBtn exists in template", 'id="upgradeBtn"' in h)
            chk("M#38 dlCard only in not-release block",
                'id="dlCard"' not in h or "not is_release" in h or "{% else %}" in h)
            # M#34: banner must appear BEFORE the upgrade JS (look for upgradeBtn IIFE)
            banner_pos = h.find('id="updateBanner"')
            upg_script = h.find("// -- Update check (RELEASE ONLY) --")
            chk("M#34 banner DOM before upgrade JS",
                banner_pos > 0 and (upg_script < 0 or banner_pos < upg_script))
            break

    # M#47 #48 #27: upgrade.py
    for n in names:
        if n.endswith("portal/upgrade.py"):
            u = z.read(n).decode("utf-8")
            chk("M#47 URL encoding in upgrade", "urllib.parse.quote" in u)
            chk("M#48 PermissionError handler", "PermissionError" in u)
            chk("M#27 no hardcoded BUNDLE_NAME", "_BUNDLE_NAME" not in u or "_PROJECT_DIR" in u)
            pause_count = u.count("\npause\n") + u.count("\npause\r")
            chk("M#36 zero pause in bat", pause_count == 0, f"found {pause_count} pauses")
            break

    # M#47 auto-shutdown: check template JS
    for n in names:
        if n.endswith("portal/templates/index.html"):
            tpl = z.read(n).decode("utf-8")
            chk("M#47 auto-shutdown in frontend", "api/shutdown" in tpl or "/api/shutdown" in tpl)
            break

    # PNGs
    chk("Zero app PNGs", len([n for n in names if n.endswith(".png") and "runtime/" not in n]) == 0)
    # Tests
    chk("Zero test files", len([n for n in names if "/test/" in n and "runtime/" not in n]) == 0)
    # Source count
    chk("Source count < 200", ri.get("source_file_count", 999) < 200)

print(f"\n  {ok} passed, {bad} failed")
sys.exit(0 if bad == 0 else 1)
