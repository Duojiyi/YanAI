#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.storage_safety import (
    create_backup,
    format_backup_manifest,
    format_backup_verification,
    restore_backup,
    verify_backup,
)


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="备份、校验和恢复 YanAI 旧 JSON 存储数据",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DATA_DIR),
        help="JSON 数据目录，默认 ./data",
    )
    parser.add_argument(
        "--backup-dir",
        help="创建备份时写入的目录；默认 data/backups/storage-json-<timestamp>",
    )
    parser.add_argument(
        "--verify",
        metavar="BACKUP_DIR",
        help="只校验指定备份目录是否完整可恢复",
    )
    parser.add_argument(
        "--restore",
        metavar="BACKUP_DIR",
        help="从指定备份目录恢复 JSON 数据文件",
    )
    parser.add_argument(
        "--target-dir",
        help="恢复目标目录，默认 ./data",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="恢复时允许覆盖目标目录中的同名文件",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON",
    )
    args = parser.parse_args()

    if args.verify and args.restore:
        parser.error("--verify and --restore cannot be used together")

    if args.verify:
        report = verify_backup(Path(args.verify))
        _print(report, format_backup_verification(report), args.json)
        return 0 if report["status"] == "ok" else 1

    if args.restore:
        target_dir = Path(args.target_dir or args.data_dir)
        result = restore_backup(Path(args.restore), target_dir, overwrite=args.force)
        _print(result, f"Restored {len(result['copied_files'])} files to {result['target_dir']}", args.json)
        return 0

    manifest = create_backup(Path(args.data_dir), Path(args.backup_dir) if args.backup_dir else None)
    _print(manifest, format_backup_manifest(manifest), args.json)
    return 0


def _print(payload: dict, text: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(text)


if __name__ == "__main__":
    raise SystemExit(main())
