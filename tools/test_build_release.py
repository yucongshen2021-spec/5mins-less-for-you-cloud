"""build_release.py 行为测试（main 分支）。"""
from __future__ import annotations

from pathlib import Path

import build_release


def test_collect_source_files_excludes_agents_md(tmp_path: Path) -> None:
    (tmp_path / "application").mkdir()
    (tmp_path / "application" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# agent guide\n", encoding="utf-8")

    files = build_release.collect_source_files(tmp_path)
    zip_paths = [dst for _, dst in files]

    assert f"{build_release.BUNDLE_NAME}/application/app.py" in zip_paths
    assert f"{build_release.BUNDLE_NAME}/AGENTS.md" not in zip_paths


def test_collect_source_files_excludes_mistake_txt(tmp_path: Path) -> None:
    (tmp_path / "application").mkdir()
    (tmp_path / "application" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "mistake.txt").write_text("# mistakes\n", encoding="utf-8")

    files = build_release.collect_source_files(tmp_path)
    zip_paths = [dst for _, dst in files]

    assert f"{build_release.BUNDLE_NAME}/application/app.py" in zip_paths
    assert all("mistake.txt" not in dst for dst in zip_paths)
