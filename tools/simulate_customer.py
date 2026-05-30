"""模拟"客户机器 + 开发机 mirror"的真实使用场景，覆盖 6 个版本通知场景。

执行步骤（脚本自动完成）：
  1. 起一份"开发机 portal"（仅 Web 层，监听 0.0.0.0:5000，不拉 4 个子应用）
  2. 用 importlib 隔离加载"客户包"内的 update_check 模块（指向 customer_v030 目录）
  3. 客户视角真实通过 192.168.5.10:5000/api/update/manifest 拉 manifest
  4. 验证每个场景的 JSON 结果是否符合预期

使用：
  py -3 tools/simulate_customer.py
  py -3 tools/simulate_customer.py --bind 0.0.0.0 --customer-bundle <path>

注意：
  - 此脚本是"开发机和客户机在同一台机器"的模拟。客户包内 update_config.json
    指向 http://192.168.5.10:5000，这台机器自己也能访问该 IP，因此模拟真实。
  - 不启动 4 个子应用，仅启 portal Flask 进程，避免占用 5739/5740/5741/5742 干扰。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import socket
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"
CUSTOMER_DIR_DEFAULT = DIST_DIR / "customer_v030" / "帮你节省5分钟"
DEV_HOST = "192.168.5.10"
DEV_PORT = 5000


# ── 终端着色（仅 PASS/FAIL，不带表情） ─────────────────────────────────
def _color(s: str, code: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m"


def green(s): return _color(s, "32")
def red(s): return _color(s, "31")
def cyan(s): return _color(s, "36")


# ── 开发机 portal（仅 Web 层） ─────────────────────────────────────────
def start_dev_portal_web_only(bind_host: str, port: int):
    sys.path.insert(0, str(PROJECT_ROOT / "application" / "portal"))
    import app as portal_app  # noqa
    from werkzeug.serving import make_server

    server = make_server(bind_host, port, portal_app.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    # wait until socket accepts
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection((bind_host if bind_host != "0.0.0.0" else "127.0.0.1", port), timeout=1):
                return server
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    raise RuntimeError(f"dev portal 没起来：{bind_host}:{port}")


# ── 客户视角：隔离加载客户包内的 update_check.py ──────────────────────
def load_customer_update_check(customer_bundle: Path):
    """以独立 module 名加载客户包里的 update_check，使其 _HERE / _LOCAL_RELEASE_INFO
    都指向客户目录，等同于客户 portal 实际跑这段代码。
    """
    uc_path = customer_bundle / "application" / "portal" / "update_check.py"
    if not uc_path.is_file():
        raise SystemExit(f"未找到客户 update_check.py：{uc_path}")
    spec = importlib.util.spec_from_file_location("client_update_check", str(uc_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["client_update_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def _zip_release_version(zip_path: Path) -> str | None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith("/RELEASE_INFO.json") or name == "RELEASE_INFO.json":
                    with zf.open(name) as f:
                        data = json.loads(f.read().decode("utf-8"))
                    v = data.get("version")
                    return v if isinstance(v, str) else None
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
        return None
    return None


class HiddenServerZips:
    """Temporarily hide server zips whose RELEASE_INFO.version is not keep_version."""

    def __init__(self, keep_version: str):
        self.keep_version = keep_version
        self.hidden_dir = DIST_DIR / ".simulate_customer_hidden"
        self.hidden: list[tuple[Path, Path]] = []

    def __enter__(self):
        self.hidden_dir.mkdir(parents=True, exist_ok=True)
        for z in sorted(DIST_DIR.glob("*.zip")):
            if _zip_release_version(z) == self.keep_version:
                continue
            dst = self.hidden_dir / z.name
            if dst.exists():
                dst.unlink()
            z.rename(dst)
            self.hidden.append((dst, z))
        return self

    def __exit__(self, *exc):
        for src, dst in reversed(self.hidden):
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
        try:
            self.hidden_dir.rmdir()
        except OSError:
            pass


def ensure_server_zip(version: str) -> None:
    for z in DIST_DIR.glob("*.zip"):
        if _zip_release_version(z) == version:
            return
    raise SystemExit(f"dist/ 内未找到服务端版本 {version} 的合法 zip，请先运行 build_release.py")


# ── 工具：临时改写客户文件，跑完恢复 ─────────────────────────────────
class TempPatch:
    def __init__(self, path: Path):
        self.path = path
        self._backup = None

    def __enter__(self):
        self._backup = self.path.read_text(encoding="utf-8") if self.path.is_file() else None
        return self

    def write(self, content: str):
        self.path.write_text(content, encoding="utf-8")

    def write_json(self, obj):
        self.path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

    def __exit__(self, *exc):
        if self._backup is None:
            self.path.unlink(missing_ok=True)
        else:
            self.path.write_text(self._backup, encoding="utf-8")


# ── 测试结果聚合 ──────────────────────────────────────────────────────
class Tally:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def record(self, name: str, ok: bool, detail: str = ""):
        tag = green("PASS") if ok else red("FAIL")
        line = f"  [{tag}] {name}"
        if detail:
            line += f"  — {detail}"
        print(line)
        if ok:
            self.passed += 1
        else:
            self.failed += 1
            self.failures.append(f"{name}: {detail}")

    def summary(self):
        total = self.passed + self.failed
        bar = "─" * 60
        print()
        print(bar)
        if self.failed == 0:
            print(green(f"全部 {total} 项断言通过"))
        else:
            print(red(f"{self.failed} 项失败 / 共 {total} 项："))
            for f in self.failures:
                print(red(f"  - {f}"))
        return self.failed == 0


# ── 场景 ──────────────────────────────────────────────────────────────
def scenario_a_same_version(client_uc, t: Tally):
    """客户 0.3.0 = 服务端 0.3.0 → 不出横幅"""
    print(cyan("\n[场景 A] 客户 = 服务端，不出横幅"))
    client_uc.reset_cache_for_tests()
    r = client_uc.check(force=True)
    t.record("status == ok", r["status"] == "ok", f"got {r['status']}")
    t.record("local_version == 0.3.0", r["local_version"] == "0.3.0", f"got {r['local_version']}")
    t.record("remote_version == 0.3.0", r["remote_version"] == "0.3.0", f"got {r['remote_version']}")
    t.record("comparison == same", r["comparison"] == "same", f"got {r['comparison']}")
    t.record("has_update == False", r["has_update"] is False, f"got {r['has_update']}")
    t.record("source == mirror", r["source"] == "mirror", f"got {r['source']}")


def scenario_b_update_available(client_uc, t: Tally):
    """[核心] 客户 0.3.0 < 服务端 0.3.1 → 必须出横幅 + 下载 URL 可达"""
    print(cyan("\n[场景 B] 服务端有新版 0.3.1（核心场景）"))
    client_uc.reset_cache_for_tests()
    r = client_uc.check(force=True)
    print("    -> remote =", r.get("remote_version"))
    t.record("status == ok", r["status"] == "ok", str(r["status"]))
    t.record("local_version == 0.3.0", r["local_version"] == "0.3.0", f"got {r['local_version']}")
    t.record("remote_version == 0.3.1", r["remote_version"] == "0.3.1", f"got {r['remote_version']}")
    t.record("comparison == older", r["comparison"] == "older", f"got {r['comparison']}")
    t.record("has_update == True", r["has_update"] is True, f"got {r['has_update']}")
    t.record("download_url is not None", bool(r["download_url"]),
             f"got {r['download_url']}")

    # 真去拉一下 download_url 看是否能拿到 zip
    if r.get("download_url"):
        try:
            req = urllib.request.Request(r["download_url"], method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                clen = int(resp.headers.get("Content-Length", "0"))
                ctype = resp.headers.get("Content-Type", "")
                ok = resp.status == 200 and clen > 1_000_000 and "zip" in ctype.lower()
                t.record(
                    "download_url 真可下载（HEAD 200 + zip + size>1MB）",
                    ok,
                    f"status={resp.status} size={clen} ctype={ctype}",
                )
        except Exception as e:
            t.record("download_url 真可下载", False, f"error: {e}")


def scenario_c_server_down(client_uc, t: Tally, dev_server):
    """服务端宕机 → status=network_error，绝不假装"已是最新"。"""
    print(cyan("\n[场景 C] 服务端宕机，不假装最新"))
    print("    -> shutting down dev portal ...")
    dev_server.shutdown()
    time.sleep(0.5)

    client_uc.reset_cache_for_tests()
    r = client_uc.check(force=True)
    t.record("status == network_error", r["status"] == "network_error", f"got {r['status']}")
    t.record("has_update == False", r["has_update"] is False, f"got {r['has_update']}")
    t.record("remote_version is None", r["remote_version"] is None,
             f"got {r['remote_version']}")
    t.record("errors 非空（明确告知）", len(r.get("errors", [])) >= 1,
             f"errors count = {len(r.get('errors', []))}")


def scenario_e_client_newer(client_uc, customer_release_info: Path, t: Tally):
    """客户 9.9.9 > 服务端 0.3.1 → comparison=newer，不出横幅。"""
    print(cyan("\n[场景 E] 客户版本比服务端还高（开发机自测/降级场景）"))
    with TempPatch(customer_release_info) as patch:
        info = json.loads(customer_release_info.read_text(encoding="utf-8"))
        info["version"] = "9.9.9"
        patch.write_json(info)

        client_uc.reset_cache_for_tests()
        r = client_uc.check(force=True)
        t.record("status == ok", r["status"] == "ok", f"got {r['status']}")
        t.record("local_version == 9.9.9", r["local_version"] == "9.9.9",
                 f"got {r['local_version']}")
        t.record("comparison == newer", r["comparison"] == "newer",
                 f"got {r['comparison']}")
        t.record("has_update == False", r["has_update"] is False,
                 f"got {r['has_update']}")


def scenario_f_cache(client_uc, t: Tally, customer_config: Path):
    """缓存生效：相同 TTL 内连续检查应命中缓存，不重打 mirror。"""
    print(cyan("\n[场景 F] 缓存生效（TTL 内不重复打 mirror）"))
    # 把客户 cache_ttl_seconds 改为 3600，确保会命中缓存
    with TempPatch(customer_config) as patch:
        cfg = json.loads(customer_config.read_text(encoding="utf-8"))
        cfg["cache_ttl_seconds"] = 3600
        patch.write_json(cfg)

        client_uc.reset_cache_for_tests()
        r1 = client_uc.check(force=False)
        r2 = client_uc.check(force=False)
        t.record("第一次 from_cache=False", r1.get("from_cache") is False,
                 f"got {r1.get('from_cache')}")
        t.record("第二次 from_cache=True", r2.get("from_cache") is True,
                 f"got {r2.get('from_cache')}")
        t.record("两次 remote_version 一致", r1["remote_version"] == r2["remote_version"],
                 f"r1={r1['remote_version']} r2={r2['remote_version']}")


# ── main ──────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bind", default="0.0.0.0", help="dev portal 监听地址（默认 0.0.0.0 让 LAN 可达）")
    p.add_argument("--port", type=int, default=DEV_PORT)
    p.add_argument("--customer-bundle", default=str(CUSTOMER_DIR_DEFAULT),
                   help="客户包解压后的根目录（含 RELEASE_INFO.json）")
    p.add_argument("--no-build-031", action="store_true",
                   help="跳过自动打 v0.3.1（仅当你已经手动打过时使用）")
    args = p.parse_args()

    customer_bundle = Path(args.customer_bundle).resolve()
    if not (customer_bundle / "RELEASE_INFO.json").is_file():
        raise SystemExit(f"客户 bundle 不存在或缺 RELEASE_INFO.json：{customer_bundle}")
    customer_release_info = customer_bundle / "RELEASE_INFO.json"
    customer_config = customer_bundle / "application" / "portal" / "update_config.json"

    print(cyan(f"客户 bundle：{customer_bundle}"))
    print(cyan(f"客户 update_config.json 内 mirror_url：" +
               json.loads(customer_config.read_text(encoding='utf-8'))["mirror_url"]))

    # 启动开发机 portal
    print(cyan(f"\n启动开发机 portal: http://{args.bind}:{args.port}"))
    dev_server = start_dev_portal_web_only(args.bind, args.port)
    print(cyan("dev portal up."))

    # 加载客户视角的 update_check
    client_uc = load_customer_update_check(customer_bundle)
    print(cyan(f"loaded client update_check from {customer_bundle.name}/.../update_check.py"))

    tally = Tally()

    # 场景 A：临时隐藏其它版本，让服务端 latest 精确等于客户版本 0.3.0。
    # 这样脚本可重复运行；即使 dist/ 里已有 0.3.1，也不会污染 same-version 判断。
    ensure_server_zip("0.3.0")
    with HiddenServerZips("0.3.0"):
        scenario_a_same_version(client_uc, tally)

    # 打 v0.3.1 让 dist 里出现"未来版本"
    if not args.no_build_031:
        print(cyan("\n打 v0.3.1（让开发机 dist 里出现新版本）..."))
        import subprocess
        subprocess.check_call(
            [sys.executable, str(PROJECT_ROOT / "tools" / "build_release.py"),
             "--version", "v0.3.1"],
            cwd=str(PROJECT_ROOT),
        )
    else:
        ensure_server_zip("0.3.1")

    # 场景 B [核心]
    scenario_b_update_available(client_uc, tally)

    # 场景 E
    scenario_e_client_newer(client_uc, customer_release_info, tally)

    # 场景 F（必须在 C 之前，因为 C 关掉了 dev portal）
    scenario_f_cache(client_uc, tally, customer_config)

    # 场景 C 必须最后跑（关 dev portal）
    scenario_c_server_down(client_uc, tally, dev_server)

    ok = tally.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
