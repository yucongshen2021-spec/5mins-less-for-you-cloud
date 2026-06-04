#!/usr/bin/env python3
"""One-click release script. Run from project root.

Usage:
    py tools/release.py 1.1.7              # full release
    py tools/release.py 1.1.7 --no-push    # local test only

This module lives in tools/ and does not depend on application code.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_SCRIPT = PROJECT_ROOT / "tools" / "build_release.py"
VERIFY_SCRIPT = PROJECT_ROOT / "tools" / "_verify_zip.py"
RELEASE_INFO = PROJECT_ROOT / "RELEASE_INFO.json"

MIRROR_PRIMARY = "http://192.168.72.219:8000/api/update/manifest"
MIRROR_BACKUP = "http://192.168.5.10:8000/api/update/manifest"

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def run(cmd: list[str], check: bool = True, cwd: Path = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd or PROJECT_ROOT),
                          capture_output=True, text=True, check=check)


def step(n: int, msg: str) -> None:
    print(f"{YELLOW}[{n}/5] {msg}...{RESET}")


def fail(msg: str) -> None:
    print(f"{RED}  FAILED: {msg}{RESET}")
    sys.exit(1)


def ok(msg: str = "") -> None:
    print(f"{GREEN}  {msg}{RESET}" if msg else "")


def git(*args: str) -> None:
    cmd = ["git"] + list(args)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT),
                            capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"git {' '.join(args)}: {result.stderr.strip()}")


def main():
    if len(sys.argv) < 2:
        print("Usage: py tools/release.py <version> [--no-push]")
        sys.exit(1)

    version = sys.argv[1]
    no_push = "--no-push" in sys.argv

    # Read bundle name from build script
    build_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    for line in build_text.splitlines():
        if 'BUNDLE_NAME' in line and '=' in line and '"' in line:
            bundle_name = line.split('"')[1]
            break
    else:
        bundle_name = "5mins-tools"

    print(f"{CYAN}{'=' * 60}{RESET}")
    print(f"{CYAN}  Release v{version}  (bundle: {bundle_name}){RESET}")
    print(f"{CYAN}{'=' * 60}{RESET}")
    print()

    # 1. Switch to release branch
    step(1, "Switch to release branch")
    git("checkout", "release")
    ok("release")

    # 2. Sync main -> release (only if behind)
    step(2, "Sync main -> release")
    git("fetch", "origin", "main")
    result = subprocess.run(
        ["git", "rev-list", "--count", "release..origin/main"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    behind = int(result.stdout.strip() or 0)
    if behind > 0:
        print(f"  main ahead by {behind} commits, merging...")
        git("merge", "origin/main",
            "-m", f"merge: sync main into release for v{version}")
        ok("merged")
    else:
        ok("already synced")

    # 3. Build
    step(3, f"Build v{version}")
    ri = {
        "version": version,
        "name": bundle_name,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    RELEASE_INFO.write_text(json.dumps(ri, ensure_ascii=False), encoding="utf-8")

    # Delete old zip of same version
    old_zips = list(DIST_DIR.glob(f"*{version}.zip"))
    for z in old_zips:
        z.unlink()

    result = subprocess.run(
        [sys.executable, str(BUILD_SCRIPT),
         "--version", version, "--mirror-url", MIRROR_PRIMARY],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        fail(f"build error:\n{result.stderr}")

    # Find built zip
    zips = sorted(DIST_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        fail("no zip found after build")
    zip_path = zips[0]
    zip_name = zip_path.name

    # Inject backup mirror URL into zip
    tmp_zip = zip_path.with_suffix(".tmp")
    shutil.copy2(zip_path, tmp_zip)
    try:
        with zipfile.ZipFile(zip_path, "a") as zf:
            for name in zf.namelist():
                if name.endswith("application/portal/update_config.json"):
                    cfg = json.loads(zf.read(name))
                    cfg["mirror_urls"] = [MIRROR_PRIMARY, MIRROR_BACKUP]
                    cfg["mirror_url"] = MIRROR_PRIMARY
                    # Can't write directly to existing entry, so we
                    # handle it via read-modify-write on the whole zip
                    break
            else:
                fail("update_config.json not found in zip")

        # Read all entries, modify the config one, write to new zip
        with zipfile.ZipFile(tmp_zip, "r") as z_in:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z_out:
                for item in z_in.infolist():
                    data = z_in.read(item.filename)
                    if item.filename.endswith("application/portal/update_config.json"):
                        cfg = json.loads(data.decode("utf-8"))
                        cfg["mirror_urls"] = [MIRROR_PRIMARY, MIRROR_BACKUP]
                        cfg["mirror_url"] = MIRROR_PRIMARY
                        data = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
                    z_out.writestr(item, data)
        tmp_zip.unlink()
    except Exception:
        if tmp_zip.exists():
            tmp_zip.unlink()
        raise

    size_mb = round(zip_path.stat().st_size / 1024 / 1024, 2)
    ok(f"{zip_name} ({size_mb} MB)")

    # 4. Commit + push
    step(4, "Commit + push")
    git("add", "RELEASE_INFO.json")
    git("commit", "-m", f"chore: release v{version}")
    if not no_push:
        git("push", "origin", "release")
        ok("pushed release")
        git("checkout", "main")
        git("merge", "release", "-m", f"merge: sync release v{version} back to main")
        git("push", "origin", "main")
        ok("synced main")
    else:
        ok("skipped (--no-push)")

    # 5. Verify
    step(5, "Verify")
    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(zip_path), version],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        fail("verification failed")

    print()
    print(f"{CYAN}{'=' * 60}{RESET}")
    print(f"{CYAN}  DONE: dist/{zip_name}{RESET}")
    print(f"{CYAN}{'=' * 60}{RESET}")


if __name__ == "__main__":
    main()
