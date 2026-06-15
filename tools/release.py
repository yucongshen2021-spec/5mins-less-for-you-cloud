#!/usr/bin/env python3
"""One-click release. Run from project root.

Usage: py tools/release.py 1.1.7 [--no-push]
"""
import json, subprocess, sys, zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M1 = "http://192.168.72.219:8000/api/update/manifest"
M2 = "http://192.168.5.10:8000/api/update/manifest"


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        print(f"  git error: {r.stderr.strip()}")
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: py tools/release.py <version> [--no-push]")
        sys.exit(1)

    ver = sys.argv[1]
    no_push = "--no-push" in sys.argv

    # Read bundle name from build script
    bundle = "5mins-tools"
    for line in (ROOT / "tools" / "build_release.py").read_text("utf-8").splitlines():
        if "BUNDLE_NAME" in line and '"' in line:
            bundle = line.split('"')[1]
            break

    print(f"Release v{ver}  bundle={bundle}")
    print()

    # 1. Branch check
    print("[1/4] Branch check")
    r = subprocess.run(["git", "branch", "--show-current"], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8")
    branch = r.stdout.strip()
    print(f"  building from: {branch}")
    if branch != "release":
        print("  WARNING: not on release branch!")
        print("  Production releases should run from release branch.")
    print()

    # 2. Build
    print(f"[2/4] Build v{ver}")
    ri = {"version": ver, "name": bundle,
          "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    (ROOT / "RELEASE_INFO.json").write_text(
        json.dumps(ri, ensure_ascii=False), encoding="utf-8")

    for old in (ROOT / "dist").glob(f"*{ver}.zip"):
        old.unlink()

    r = subprocess.run(
        [sys.executable, "tools/build_release.py", "--version", ver, "--mirror-url", M1],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    print(r.stdout.strip())
    if r.returncode != 0:
        print(f"  FAILED: {r.stderr}")
        sys.exit(1)

    dist = ROOT / "dist"
    zips = sorted(dist.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    zip_path = zips[0]
    zip_name = zip_path.name

    # Inject backup mirror URL into zip
    tmp = str(zip_path) + ".tmp"
    with zipfile.ZipFile(zip_path, "r") as zi:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
            for n in zi.namelist():
                data = zi.read(n)
                if n.endswith("application/portal/update_config.json"):
                    cfg = json.loads(data.decode("utf-8"))
                    cfg["mirror_urls"] = [M1, M2]
                    cfg["mirror_url"] = M1
                    data = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
                zo.writestr(n, data)
    Path(tmp).replace(zip_path)

    mb = round(zip_path.stat().st_size / 1024 / 1024, 2)
    print(f"  {zip_name} ({mb} MB)")
    print()

    # 3. Commit + push
    print("[3/4] Commit + push")
    git("add", "RELEASE_INFO.json")
    git("commit", "-m", f"chore: release v{ver}")
    if not no_push:
        git("push", "origin", branch)
        print(f"  pushed {branch}")
    else:
        print("  skipped (--no-push)")
    print()

    # 4. Verify
    print("[4/4] Verify")
    r = subprocess.run(
        [sys.executable, "tools/_verify_zip.py", str(zip_path), ver],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    print(r.stdout.strip())
    if r.returncode != 0:
        print("  FAILED")
        sys.exit(1)

    # 5. Pre-release leftover-version sweep (M#58)
    # RELEASE_INFO.json is the single source of truth for the version header
    # (app.py::_local_version reads it on BOTH branches; demo portal on main
    # shows it at templates/index.html:344). release.py only commits it on the
    # release branch, so the other branch silently keeps the OLD version and the
    # demo portal shows a stale number. This check refuses to finish release
    # until the checked-out tree has no other RELEASE_INFO.json version drift.
    print()
    print("[5/5] Leftover version sweep (M#58)")
    stale = []
    ri_path = ROOT / "RELEASE_INFO.json"
    if ri_path.exists():
        try:
            cur = json.loads(ri_path.read_text(encoding="utf-8")).get("version")
            if cur != ver:
                stale.append(f"RELEASE_INFO.json version={cur} (expected {ver})")
        except (json.JSONDecodeError, OSError) as e:
            stale.append(f"RELEASE_INFO.json unreadable: {e}")
    if stale:
        print("  STALE VERSION FOUND:")
        for s in stale:
            print(f"    - {s}")
        print("  Fix before completing the release (M#58).")
        sys.exit(1)
    print(f"  RELEASE_INFO.json version matches {ver}")

    print()
    print(f"DONE: dist/{zip_name}")


if __name__ == "__main__":
    main()
