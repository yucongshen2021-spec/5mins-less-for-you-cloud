"""prepare_runtime.py — 下载并组装一份「便携 Python 运行时」给客户分发包用。

策略：
- 下载 python-build-standalone 提供的 install_only_stripped tarball（带 tkinter / pip / ssl）
- 解压到 .build_cache/runtime/python/
- 用其中 python.exe 安装 release_requirements.txt 列出的运行期依赖
- 全程缓存：再次运行时若已有 .build_cache/runtime/.ready 标记则直接跳过

最终客户解压 zip 后会看到 `runtime/python/python.exe`，所有 .bat 都用它。
脚本只用 Python 标准库 + 系统 tar，CI 上无需任何额外动作。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = PROJECT_ROOT / ".build_cache"
RUNTIME_DIR = CACHE_DIR / "runtime"
PYTHON_DIR = RUNTIME_DIR / "python"
READY_FILE = RUNTIME_DIR / ".ready"

# 固定一个版本以保证可重复构建。要升级时改这里 + STANDALONE_SHA256。
STANDALONE_TAG = "20260510"
STANDALONE_VER = "3.13.13"
STANDALONE_FILENAME = (
    f"cpython-{STANDALONE_VER}+{STANDALONE_TAG}"
    f"-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
)
STANDALONE_URL = (
    f"https://github.com/astral-sh/python-build-standalone/releases/download/"
    f"{STANDALONE_TAG}/cpython-{STANDALONE_VER}%2B{STANDALONE_TAG}"
    f"-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
)
# 校验和 — 第一次跑时由 download() 自动写入 .build_cache/runtime/.sha256
# 后续再跑校验。仓库不预先固定哈希，避免上游 release 重打 tag 失效。

REQUIREMENTS = PROJECT_ROOT / "tools" / "release_requirements.txt"


def log(msg: str) -> None:
    print(f"[runtime] {msg}", flush=True)


def download_tarball() -> Path:
    """下载 standalone tarball 到缓存；已存在则直接返回。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / STANDALONE_FILENAME
    if target.is_file() and target.stat().st_size > 0:
        log(f"reuse cached tarball: {target.name} ({target.stat().st_size/1024/1024:.1f} MB)")
        return target

    log(f"downloading {STANDALONE_URL}")
    tmp = target.with_suffix(target.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    with urllib.request.urlopen(STANDALONE_URL, timeout=120) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f, length=1024 * 1024)
    tmp.replace(target)
    log(f"downloaded {target.stat().st_size/1024/1024:.1f} MB -> {target.name}")
    return target


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_tarball(tarball: Path) -> None:
    """tarball 内顶层目录就是 `python/`；解压到 RUNTIME_DIR 即可。"""
    if PYTHON_DIR.is_dir():
        log(f"removing previous {PYTHON_DIR}")
        shutil.rmtree(PYTHON_DIR)
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    log(f"extracting tarball -> {RUNTIME_DIR}")
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(RUNTIME_DIR)
    if not PYTHON_DIR.is_dir():
        raise RuntimeError(
            f"解压后未找到 {PYTHON_DIR}（tarball 顶层目录变了？）"
        )


def runtime_python_exe() -> Path:
    return PYTHON_DIR / "python.exe"


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    # 严格隔离：不读取当前用户 roaming site-packages，避免“机器上装过啥就捡到啥”。
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def install_requirements() -> None:
    py = runtime_python_exe()
    if not py.is_file():
        raise RuntimeError(f"未找到 runtime python: {py}")
    if not REQUIREMENTS.is_file():
        raise RuntimeError(f"未找到 {REQUIREMENTS}")

    log("upgrading pip")
    subprocess.check_call([str(py), "-m", "pip", "install", "--no-warn-script-location",
                           "--upgrade", "pip"], env=runtime_env())
    log(f"installing {REQUIREMENTS.name}")
    subprocess.check_call([str(py), "-m", "pip", "install", "--no-warn-script-location",
                           "-r", str(REQUIREMENTS)], env=runtime_env())


def smoke_test() -> None:
    """验证 runtime 能 import 所有关键模块（不允许猜测：能不能跑要靠实际 import）。"""
    py = runtime_python_exe()
    code = (
        "import tkinter, ssl, sqlite3;"
        "import flask, dns.resolver, docx, PIL, paramiko, playwright;"
        "print('runtime OK')"
    )
    subprocess.check_call([str(py), "-c", code], env=runtime_env())


def is_ready() -> bool:
    return READY_FILE.is_file() and runtime_python_exe().is_file()


def mark_ready(tarball_sha: str) -> None:
    READY_FILE.write_text(
        f"tag={STANDALONE_TAG}\nver={STANDALONE_VER}\nsha256={tarball_sha}\n",
        encoding="utf-8",
    )


def prepare(force: bool = False) -> Path:
    """主入口。返回 runtime python.exe 的绝对路径。"""
    if is_ready() and not force:
        log("runtime already prepared (use --force to rebuild)")
        return runtime_python_exe()

    tarball = download_tarball()
    sha = sha256_of(tarball)
    log(f"sha256 = {sha}")
    extract_tarball(tarball)
    install_requirements()
    smoke_test()
    mark_ready(sha)
    log(f"runtime ready at {PYTHON_DIR}")
    return runtime_python_exe()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true", help="忽略缓存重新下载并安装")
    args = p.parse_args()
    prepare(force=args.force)


if __name__ == "__main__":
    sys.exit(main() or 0)
