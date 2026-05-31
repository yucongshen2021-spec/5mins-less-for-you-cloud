"""build_release.py — 把"帮你节省5分钟"打包成可分发 zip。

用法：
    python tools/build_release.py
    python tools/build_release.py --version v1.2.3
    python tools/build_release.py --version v1.2.3 --output dist/
    python tools/build_release.py --list-only        # 只列出会被打包的文件，不实际写 zip
    python tools/build_release.py --no-runtime       # 不打入便携 Python（仅用于本地小测）

输出：
    dist/帮你节省5分钟-<version>.zip

zip 内根目录是 `帮你节省5分钟/`，客户解压一次就拿到一个干净文件夹。
默认会把便携 Python（含运行期依赖）打到 zip 内 `runtime/python/`，
所有 `start_*.bat` 优先用它，零安装。

脚本只用 Python 标准库，本地和 GitHub Actions 上都能跑。
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR_DEFAULT = PROJECT_ROOT / "dist"
BUNDLE_NAME = "帮你节省5分钟"

# 让本目录可被 import（prepare_runtime 在同目录）
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_runtime  # noqa: E402

# ---- 排除规则（仅作用于「项目源码」walk） ----
# 任意深度命中目录名 → 整个子树跳过
EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".git", ".github", ".gitlab",
    ".vscode", ".idea", ".cursor", ".claude",
    ".playwright-mcp", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox",
    ".build_cache",  # 仅作为构建中转目录，不进项目 walk；runtime 走独立逻辑
    "node_modules",
    "chromium",
    "build", "dist",
    "log", "logs",
    "test", "tests", "test_html_refactor",
    "测试用例",
    "agent-transcripts", "plan",
    "editor_workspace",  # 用户工作区 → 客户应拿到工厂态
}

# 文件名 glob（与文件名比对，不含路径）
EXCLUDE_FILE_GLOBS = [
    "*.pyc", "*.pyo", "*.pyd",
    "*.log",
    "*.exe", "*.dll", "*.bin",
    "*.spec.bak",
    "*.swp", "*.swo",
    "*.tmp", "*.bak", "*.orig", "*~",
    ".DS_Store", "Thumbs.db", "desktop.ini",
    ".gitignore", ".gitattributes",
    ".env", ".env.*", "*.local.json",
    "secrets.json", "credentials.json",
    "mistake.txt",
    "经历.md",
    "DESIGN.md",
    "AGENTS.md",  # 给 AI agent 看的工作守则，客户包不需要
    "user_init_placeholders.json",
    # 单元测试不发客户（开发期跑用，已通过严格命名约定区分）
    "test_*.py",
    # 运行期产生的本地缓存（更新检查、数据缓存等）
    ".update_cache.json",
]

# 整段路径前缀（项目根的 POSIX 相对路径），命中即跳过
EXCLUDE_PATH_PREFIXES = [
    "application/test",
    "tools",  # 打包脚本本身不进客户包
]


def matches_file_glob(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_FILE_GLOBS)


def should_skip_dir(dir_path: Path, root: Path) -> bool:
    if dir_path.name in EXCLUDE_DIR_NAMES:
        return True
    rel = dir_path.relative_to(root).as_posix()
    if any(rel == p or rel.startswith(p + "/") for p in EXCLUDE_PATH_PREFIXES):
        return True
    return False


def detect_version(cli_version: str | None) -> str:
    """优先级：CLI > GITHUB_REF_NAME / RELEASE_VERSION > git describe > 'dev'。"""
    if cli_version:
        return cli_version.lstrip("v")

    for env_key in ("GITHUB_REF_NAME", "RELEASE_VERSION"):
        env_ref = os.environ.get(env_key)
        if env_ref:
            return env_ref.lstrip("v")

    try:
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            return out.lstrip("v")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return "dev"


def collect_source_files(root: Path) -> list[tuple[Path, str]]:
    """走查项目源码，返回 [(绝对路径, zip 内相对路径)]。

    zip 路径以 BUNDLE_NAME/ 开头。
    本函数仅处理「项目源码」，runtime 由 collect_runtime_files 单独负责。
    """
    out: list[tuple[Path, str]] = []
    for cur, dirs, files in os.walk(root):
        cur_path = Path(cur)
        dirs[:] = sorted(
            d for d in dirs
            if not should_skip_dir(cur_path / d, root)
        )

        for f in sorted(files):
            if matches_file_glob(f):
                continue
            abs_path = cur_path / f
            rel_in_proj = abs_path.relative_to(root).as_posix()
            zip_path = f"{BUNDLE_NAME}/{rel_in_proj}"
            out.append((abs_path, zip_path))
    return out


def collect_runtime_files(runtime_python_dir: Path) -> list[tuple[Path, str]]:
    """收集便携 Python 整个目录。

    runtime 里 .pyc / .pyd / .exe / .dll 都是必需文件，所以**不**应用项目级过滤规则。
    只跳过 __pycache__/ 之外纯日志文件。standalone tarball 不带 __pycache__，
    但已安装的依赖可能产生，安全起见这里仍裁掉。
    """
    out: list[tuple[Path, str]] = []
    if not runtime_python_dir.is_dir():
        raise RuntimeError(f"runtime 目录不存在：{runtime_python_dir}；请先跑 prepare_runtime.py")

    for cur, dirs, files in os.walk(runtime_python_dir):
        cur_path = Path(cur)
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for f in sorted(files):
            abs_path = cur_path / f
            rel = abs_path.relative_to(runtime_python_dir).as_posix()
            zip_path = f"{BUNDLE_NAME}/runtime/python/{rel}"
            out.append((abs_path, zip_path))
    return out


def build(version: str, output_dir: Path, include_runtime: bool, mirror_url: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{BUNDLE_NAME}-{version}.zip"
    if zip_path.exists():
        zip_path.unlink()

    src_files = collect_source_files(PROJECT_ROOT)
    if not src_files:
        raise RuntimeError("没有任何源码文件可打包，请检查排除规则。")

    runtime_files: list[tuple[Path, str]] = []
    runtime_info: dict | None = None
    if include_runtime:
        prepare_runtime.prepare()
        runtime_files = collect_runtime_files(prepare_runtime.PYTHON_DIR)
        runtime_info = {
            "python_version": prepare_runtime.STANDALONE_VER,
            "standalone_tag": prepare_runtime.STANDALONE_TAG,
            "file_count": len(runtime_files),
            "total_bytes": sum(p.stat().st_size for p, _ in runtime_files),
        }

    all_files = src_files + runtime_files
    total_bytes = sum(p.stat().st_size for p, _ in all_files)

    manifest = {
        "name": BUNDLE_NAME,
        "version": version,
        "built_at": datetime.datetime.now(datetime.timezone.utc)
                            .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "file_count": len(all_files),
        "total_bytes": total_bytes,
        "source_file_count": len(src_files),
        "bundled_runtime": runtime_info,  # None 表示这次打包不带 runtime
    }

    print(f"[build] source files: {len(src_files)}", flush=True)
    if include_runtime:
        print(f"[build] runtime files: {len(runtime_files)} "
              f"({runtime_info['total_bytes']/1024/1024:.1f} MB raw)", flush=True)
    print(f"[build] writing {zip_path.name} ...", flush=True)

    update_config_dst = f"{BUNDLE_NAME}/application/portal/update_config.json"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for src, dst in all_files:
            if mirror_url and dst == update_config_dst:
                cfg = json.loads(src.read_text(encoding="utf-8"))
                cfg["mirror_url"] = mirror_url
                print(f"[build] mirror_url = {mirror_url}", flush=True)
                zf.writestr(dst, json.dumps(cfg, ensure_ascii=False, indent=2))
            else:
                zf.write(src, dst)
        zf.writestr(
            f"{BUNDLE_NAME}/RELEASE_INFO.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    return zip_path


def main():
    parser = argparse.ArgumentParser(description="打包帮你节省5分钟为可分发 zip")
    parser.add_argument("--version", help="版本号，如 v1.0.0；缺省时尝试从 git tag / 环境变量推导")
    parser.add_argument("--output", default=str(DIST_DIR_DEFAULT), help="输出目录（默认 dist/）")
    parser.add_argument("--list-only", action="store_true",
                        help="只列出会被打包的文件，不实际写 zip（仅源码部分，便于排查规则）")
    parser.add_argument("--no-runtime", action="store_true",
                        help="跳过便携 Python（zip 会非常小，仅本地小测用，客户拿到无法运行）")
    parser.add_argument("--mirror-url",
                        help="镜像更新地址，写入客户包 update_config.json。"
                             "例：http://192.168.72.219:5000/api/update/manifest")
    args = parser.parse_args()

    version = detect_version(args.version)
    output_dir = Path(args.output).resolve()

    if args.list_only:
        files = collect_source_files(PROJECT_ROOT)
        print(f"version: {version}")
        print(f"source_file_count: {len(files)}")
        for _, dst in files:
            print(dst)
        return

    if not args.mirror_url:
        print("[build] WARNING: 未指定 --mirror-url，客户包内 mirror_url 保持源码默认值", flush=True)
        print("[build]         外部客户可能无法收到更新提醒，建议指定外部可达的 mirror 地址", flush=True)

    print(f"[build] version = {version}")
    print(f"[build] output  = {output_dir}")
    print(f"[build] runtime = {'no' if args.no_runtime else 'yes'}")
    zip_path = build(version, output_dir, include_runtime=not args.no_runtime,
                     mirror_url=args.mirror_url or None)
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"[build] OK -> {zip_path} ({size_mb:.2f} MB)")


if __name__ == "__main__":
    sys.exit(main() or 0)
