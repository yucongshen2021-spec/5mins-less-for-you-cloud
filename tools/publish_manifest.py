"""publish_manifest.py — 为最新一份发布 zip 生成一个 manifest.json，给客户端做更新提醒用。

工作流程：
    1. 在项目根跑一次 `py -3 tools/build_release.py --version v1.2.3`
    2. 跑这个脚本：
           py -3 tools/publish_manifest.py \
               --download-url https://你的存储/5mins/帮你节省5分钟-1.2.3.zip \
               --release-url  https://你的存储/5mins/release-notes.html
    3. 它会读取 dist/ 里最新的 zip 内嵌 RELEASE_INFO.json，拿到 version / built_at
    4. 在 dist/manifest.json 写入合法 JSON
    5. 你把 dist/manifest.json 上传到你已配置在 portal/update_config.json 中的 mirror_url

设计原则：
- 严格按 zip 内 RELEASE_INFO.json 的 version 写入；不允许人工指定（避免人写错）
- download_url / release_url 必须由用户显式提供（默认不猜）
- 生成的 manifest 完全对应 update_check.fetch_mirror_manifest 期望的字段
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"


def find_latest_zip() -> Path:
    if not DIST_DIR.is_dir():
        raise SystemExit(f"未找到 {DIST_DIR}；请先在项目根运行 build_release.py")
    zips = sorted(DIST_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise SystemExit(f"{DIST_DIR} 内没有 zip；请先 build_release.py")
    return zips[0]


def read_release_info(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith("/RELEASE_INFO.json") or name == "RELEASE_INFO.json":
                with zf.open(name) as f:
                    return json.loads(f.read().decode("utf-8"))
    raise SystemExit(f"{zip_path.name} 内无 RELEASE_INFO.json，不是合法发布包")


def main():
    p = argparse.ArgumentParser(description="为最新发布 zip 生成 manifest.json")
    p.add_argument("--download-url", required=True,
                   help="manifest 中 download_url 字段：客户从哪里下载 zip。例：https://your-host/5mins/.../*.zip")
    p.add_argument("--release-url", required=True,
                   help="manifest 中 release_url 字段：客户点'查看并下载'跳转到的页面。可以与 download_url 相同")
    p.add_argument("--output", default=None,
                   help="输出文件路径；缺省 dist/manifest.json")
    p.add_argument("--zip", default=None,
                   help="指定从哪份 zip 读取 version；缺省取 dist/ 里 mtime 最新的")
    args = p.parse_args()

    zip_path = Path(args.zip).resolve() if args.zip else find_latest_zip()
    print(f"[manifest] reading version from: {zip_path.name}")
    info = read_release_info(zip_path)
    version = info.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit(f"{zip_path.name} 内 RELEASE_INFO.json 缺少 version 字段")

    manifest = {
        "version": version.strip(),
        "release_url": args.release_url,
        "download_url": args.download_url,
        "built_at": info.get("built_at"),
        "size_bytes": zip_path.stat().st_size,
    }

    out_path = Path(args.output).resolve() if args.output else (DIST_DIR / "manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[manifest] written -> {out_path}")
    print(f"[manifest] version    = {manifest['version']}")
    print(f"[manifest] release    = {manifest['release_url']}")
    print(f"[manifest] download   = {manifest['download_url']}")
    print(f"[manifest] size_bytes = {manifest['size_bytes']}")
    print()
    print("下一步：把这个 manifest.json 上传到你在 application/portal/update_config.json 中配置的")
    print("       mirror_url 指向的位置（覆盖原有的同名文件即可）。")


if __name__ == "__main__":
    sys.exit(main() or 0)
