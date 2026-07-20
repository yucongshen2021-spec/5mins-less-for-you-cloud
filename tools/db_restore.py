#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库恢复脚本 -- 从备份恢复 SQLite 数据库到容器。

用法：
  python3 /opt/fivemins/tools/db_restore.py --list          # 列出可用备份
  python3 /opt/fivemins/tools/db_restore.py --latest         # 恢复最新备份
  python3 /opt/fivemins/tools/db_restore.py --file auth_20260720_0900.sqlite  # 恢复指定备份
  python3 /opt/fivemins/tools/db_restore.py --db auth --latest  # 只恢复 auth 的最新备份

恢复方式：
  停容器 -> docker cp 覆盖 DB 文件 -> 启容器
  （SQLite 单文件，停容器后覆盖最安全）
"""

import sys
import os
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

CONTAINER = "fivemins-portal"
DB_DIR_IN_CONTAINER = "/app/application/portal/logs"
DB_FILES = ["auth.sqlite", "stats.sqlite"]
BACKUP_DIR = Path("/opt/fivemins/db_backup")
WEEKLY_DIR = BACKUP_DIR / "weekly"
LOG_FILE = BACKUP_DIR / "restore.log"


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def find_backups(db_prefix: str = None):
    """查找所有备份，按时间倒序。db_prefix: 'auth' 或 'stats'，None=全部。"""
    all_files = []
    for d in [BACKUP_DIR, WEEKLY_DIR]:
        for f in d.glob("*.sqlite"):
            if db_prefix and not f.name.startswith(db_prefix):
                continue
            all_files.append(f)
    all_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return all_files


def list_backups():
    """列出所有可用备份。"""
    for prefix in ["auth", "stats"]:
        files = find_backups(prefix)
        log(f"\n=== {prefix} 备份 ({len(files)} 个) ===")
        for f in files[:10]:  # 只显示最近10个
            size = f.stat().st_size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            tag = " [周备份]" if f.parent == WEEKLY_DIR else ""
            log(f"  {f.name}  {size:>10,} bytes  {mtime}{tag}")


def stop_container():
    log(f"停止容器 {CONTAINER}...")
    subprocess.run(["sudo", "docker", "stop", CONTAINER], check=True, timeout=30)
    log("容器已停止")


def start_container():
    log(f"启动容器 {CONTAINER}...")
    subprocess.run(["sudo", "docker", "start", CONTAINER], check=True, timeout=30)
    log("容器已启动")


def restore_file(backup_path: Path, db_file: str):
    """恢复单个数据库文件。"""
    container_path = f"{DB_DIR_IN_CONTAINER}/{db_file}"
    log(f"恢复: {backup_path.name} -> {container_path}")

    # docker cp 覆盖
    result = subprocess.run(
        ["sudo", "docker", "cp", str(backup_path), f"{CONTAINER}:{container_path}"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        log(f"FAIL: docker cp 失败 - {result.stderr.strip()}")
        return False
    log(f"OK: {db_file} 已恢复")
    return True


def verify_restored():
    """启动后验证 DB 完整性。"""
    log("验证恢复的数据库...")
    for db_file in DB_FILES:
        container_path = f"{DB_DIR_IN_CONTAINER}/{db_file}"
        result = subprocess.run(
            ["sudo", "docker", "exec", CONTAINER, "python3", "-c",
             f'import sqlite3; c=sqlite3.connect("{container_path}"); '
             f'print(c.execute("PRAGMA integrity_check").fetchone()[0]); c.close()'],
            capture_output=True, text=True, timeout=15
        )
        status = result.stdout.strip()
        if status == "ok":
            log(f"  {db_file}: OK")
        else:
            log(f"  {db_file}: FAIL - {status}")


def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(description="数据库恢复工具")
    parser.add_argument("--list", action="store_true", help="列出可用备份")
    parser.add_argument("--latest", action="store_true", help="恢复最新备份")
    parser.add_argument("--file", type=str, help="恢复指定备份文件")
    parser.add_argument("--db", type=str, choices=["auth", "stats"],
                        help="只恢复指定数据库")
    args = parser.parse_args()

    if args.list:
        list_backups()
        return

    if not args.latest and not args.file:
        parser.print_help()
        return

    # 确定要恢复哪些 DB
    prefixes = [args.db] if args.db else ["auth", "stats"]
    db_map = {"auth": "auth.sqlite", "stats": "stats.sqlite"}

    log("===== 开始恢复 =====")

    # 找备份文件
    to_restore = []  # [(backup_path, db_file)]
    for prefix in prefixes:
        db_file = db_map[prefix]
        if args.file:
            # 指定文件名
            bp = BACKUP_DIR / args.file
            if not bp.exists():
                bp = WEEKLY_DIR / args.file
            if not bp.exists():
                log(f"ERROR: 备份文件不存在: {args.file}")
                sys.exit(1)
            to_restore.append((bp, db_file))
        else:
            # 最新备份
            files = find_backups(prefix)
            if not files:
                log(f"ERROR: 无 {prefix} 的备份")
                sys.exit(1)
            to_restore.append((files[0], db_file))
            log(f"选用最新备份: {files[0].name}")

    # 停容器
    stop_container()

    # 恢复
    all_ok = True
    for bp, db_file in to_restore:
        if not restore_file(bp, db_file):
            all_ok = False

    # 启容器
    start_container()

    # 等待启动
    import time
    time.sleep(5)

    # 验证
    verify_restored()

    if all_ok:
        log("===== 恢复完成 =====")
    else:
        log("===== 恢复结束（有失败项）=====")
        sys.exit(1)


if __name__ == "__main__":
    main()
