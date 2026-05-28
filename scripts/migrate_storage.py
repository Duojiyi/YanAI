#!/usr/bin/env python3
"""
存储后端数据迁移脚本

用法：
  python scripts/migrate_storage.py --from json --to postgres
  python scripts/migrate_storage.py --from json --to postgres --dry-run
  python scripts/migrate_storage.py --from json --to postgres --backup-dir data/backups/pre-postgres
  python scripts/migrate_storage.py --from json --to postgres --verify-only
  python scripts/migrate_storage.py --from sqlite --to postgres
  python scripts/migrate_storage.py --export data/backups/postgres-full.json
  python scripts/migrate_storage.py --import data/backups/postgres-full.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

from services.repositories.base import RepositoryValidationError
from services.storage.factory import create_storage_backend
from scripts.storage_safety import (
    DATASET_SPECS,
    audit_data_dir,
    create_backup,
    format_audit_report,
    format_backup_manifest,
    format_backup_verification,
    verify_backup,
)


DATASET_ACCESSORS = {
    "accounts": ("load_accounts", "save_accounts"),
    "auth_keys": ("load_auth_keys", "save_auth_keys"),
    "users": ("load_users", "save_users"),
    "sessions": ("load_sessions", "save_sessions"),
    "redeem_codes": ("load_redeem_codes", "save_redeem_codes"),
    "channels": ("load_channels", "save_channels"),
    "prompt_library": ("load_prompt_library", "save_prompt_library"),
    "image_records": ("load_image_records", "save_image_records"),
}


def export_to_json(output_file: str, *, dry_run: bool = False):
    """导出当前存储后端的完整数据到 JSON 文件"""
    print(f"[migrate] Exporting data to {output_file}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage = create_storage_backend(DATA_DIR)
    try:
        data = _load_all_datasets(storage)
    finally:
        _close_storage(storage)
    _print_dataset_counts("Loaded for export", data)

    if dry_run:
        print(f"[migrate] Dry run: would export full dataset backup to {output_file}")
        return

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "datasets": data,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[migrate] Exported full dataset backup to {output_file}")


def import_from_json(
    input_file: str,
    *,
    dry_run: bool = False,
    backup_dir: str | None = None,
    verify_only: bool = False,
):
    """从 JSON 文件导入数据到当前存储后端"""
    print(f"[migrate] Importing data from {input_file}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    input_path = Path(input_file)
    if not input_path.exists():
        print(f"[migrate] Error: File not found: {input_file}")
        sys.exit(1)
    
    try:
        data = _parse_import_payload(json.loads(input_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        print(f"[migrate] Error: Invalid JSON: {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"[migrate] Error: {e}")
        sys.exit(1)

    _print_dataset_counts("Loaded from import file", data)
    if not _validate_dataset_report(data):
        sys.exit(1)

    if verify_only:
        print(f"[migrate] Verify only: {input_file} is a valid full dataset backup")
        return

    if dry_run:
        print(f"[migrate] Dry run: would import full dataset backup from {input_file}")
        return

    if backup_dir:
        _create_and_verify_backup(backup_dir)

    storage = create_storage_backend(DATA_DIR)
    try:
        try:
            _save_all_datasets(storage, data)
        except RepositoryValidationError as exc:
            print(f"[migrate] Error: {exc}")
            sys.exit(1)
        target_data = _load_all_datasets(storage)
        if not _verify_dataset_data(data, target_data):
            print("[migrate] Error: import verification failed")
            sys.exit(1)
    finally:
        _close_storage(storage)

    print("[migrate] Imported full dataset backup")


def migrate_data(
    from_backend: str,
    to_backend: str,
    *,
    dry_run: bool = False,
    backup_dir: str | None = None,
    verify_only: bool = False,
):
    """从一个存储后端迁移到另一个"""
    print(f"[migrate] Migrating from {from_backend} to {to_backend}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # 保存原始环境变量
    original_backend = os.environ.get("STORAGE_BACKEND")
    from_storage = None
    to_storage = None

    try:
        # 从源后端读取数据
        os.environ["STORAGE_BACKEND"] = from_backend
        from_storage = create_storage_backend(DATA_DIR)
        source_data = _load_all_datasets(from_storage)
        _print_dataset_counts(f"Loaded from {from_backend}", source_data)
        if not _validate_dataset_report(source_data):
            sys.exit(1)

        if verify_only:
            os.environ["STORAGE_BACKEND"] = to_backend
            to_storage = create_storage_backend(DATA_DIR)
            target_data = _load_all_datasets(to_storage)
            _print_dataset_counts(f"Loaded from {to_backend}", target_data)
            if not _verify_dataset_data(source_data, target_data):
                sys.exit(1)
            print("[migrate] Verification completed successfully!")
            return

        if dry_run:
            _print_dataset_counts(f"Dry run: would save to {to_backend}", source_data)
            print("[migrate] Dry run completed without writing data.")
            return

        if backup_dir:
            _create_and_verify_backup(backup_dir)
        
        # 写入目标后端
        os.environ["STORAGE_BACKEND"] = to_backend
        to_storage = create_storage_backend(DATA_DIR)
        try:
            _save_all_datasets(to_storage, source_data)
        except RepositoryValidationError as exc:
            print(f"[migrate] Error: {exc}")
            sys.exit(1)
        _print_dataset_counts(f"Saved to {to_backend}", source_data)

        target_data = _load_all_datasets(to_storage)
        if not _verify_dataset_data(source_data, target_data):
            print("[migrate] Error: post-migration verification failed")
            sys.exit(1)
        
        print(f"[migrate] Migration completed successfully!")
        
    finally:
        _close_storage(to_storage)
        _close_storage(from_storage)
        # 恢复原始环境变量
        if original_backend:
            os.environ["STORAGE_BACKEND"] = original_backend
        elif "STORAGE_BACKEND" in os.environ:
            del os.environ["STORAGE_BACKEND"]


def verify_backup_dir(backup_dir: str) -> None:
    report = verify_backup(Path(backup_dir))
    print(format_backup_verification(report))
    if report["status"] != "ok":
        sys.exit(1)


def audit_json_data(*, fail_on_issues: bool = False) -> None:
    report = audit_data_dir(DATA_DIR)
    print(format_audit_report(report))
    if fail_on_issues and int(report["summary"]["problem_count"]) > 0:
        sys.exit(1)


def _load_all_datasets(storage) -> dict[str, list[dict]]:
    data = {}
    for spec in DATASET_SPECS:
        loader_name, _ = DATASET_ACCESSORS[spec.name]
        data[spec.name] = list(getattr(storage, loader_name)())
    return data


def _save_all_datasets(storage, data: dict[str, list[dict]]) -> None:
    for spec in DATASET_SPECS:
        _, saver_name = DATASET_ACCESSORS[spec.name]
        getattr(storage, saver_name)(data.get(spec.name, []))


def _parse_import_payload(payload: object) -> dict[str, list[dict]]:
    if isinstance(payload, list):
        return {
            spec.name: payload if spec.name == "accounts" else []
            for spec in DATASET_SPECS
        }
    if not isinstance(payload, dict):
        raise ValueError("Invalid JSON format, expected full export object or legacy accounts array")

    raw_datasets = payload.get("datasets")
    if raw_datasets is None:
        raw_datasets = payload
    if not isinstance(raw_datasets, dict):
        raise ValueError("Invalid JSON format, field 'datasets' must be an object")

    data: dict[str, list[dict]] = {}
    for spec in DATASET_SPECS:
        items = raw_datasets.get(spec.name, [])
        if spec.list_key and isinstance(items, dict):
            items = items.get(spec.list_key, [])
        if not isinstance(items, list):
            raise ValueError(f"Invalid JSON format, dataset {spec.name!r} must be an array")
        data[spec.name] = items
    return data


def _validate_dataset_report(data: dict[str, list[dict]]) -> bool:
    ok = True
    for spec in DATASET_SPECS:
        items = data.get(spec.name, [])
        problems = _dataset_problems(items, spec.primary_key, spec.unique_keys)
        if problems:
            ok = False
            print(f"[migrate] Validation failed for {spec.name}:")
            for problem in problems[:20]:
                print(f"[migrate]   - {problem}")
            if len(problems) > 20:
                print(f"[migrate]   - ... {len(problems) - 20} more")
    return ok


def _dataset_problems(items: list[dict], primary_key: str, unique_keys: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    primary_seen: dict[str, int] = {}
    unique_seen: dict[str, dict[str, int]] = {key: {} for key in unique_keys}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"index {index}: item is not an object")
            continue
        primary_value = _clean_value(item.get(primary_key))
        if not primary_value:
            problems.append(f"index {index}: missing primary key {primary_key!r}")
        elif primary_value in primary_seen:
            problems.append(
                f"index {index}: duplicate primary key {primary_key!r} "
                f"(first index {primary_seen[primary_value]}, value_sha256={_sha_preview(primary_value)})"
            )
        else:
            primary_seen[primary_value] = index
        for unique_key in unique_keys:
            value = _clean_value(item.get(unique_key))
            if not value:
                continue
            seen = unique_seen[unique_key]
            if value in seen:
                problems.append(
                    f"index {index}: duplicate unique key {unique_key!r} "
                    f"(first index {seen[value]}, value_sha256={_sha_preview(value)})"
                )
            else:
                seen[value] = index
    return problems


def _verify_dataset_data(source: dict[str, list[dict]], target: dict[str, list[dict]]) -> bool:
    ok = True
    for spec in DATASET_SPECS:
        source_items = source.get(spec.name, [])
        target_items = target.get(spec.name, [])
        if len(source_items) != len(target_items):
            print(
                f"[migrate] Verify failed for {spec.name}: "
                f"source count={len(source_items)}, target count={len(target_items)}"
            )
            ok = False
            continue
        source_keys = _key_set(source_items, spec.primary_key)
        target_keys = _key_set(target_items, spec.primary_key)
        if source_keys != target_keys:
            print(f"[migrate] Verify failed for {spec.name}: primary key set mismatch")
            ok = False
    return ok


def _key_set(items: list[dict], key: str) -> set[str]:
    return {
        str(item.get(key) or "").strip()
        for item in items
        if isinstance(item, dict) and str(item.get(key) or "").strip()
    }


def _clean_value(value: object) -> str:
    return str(value or "").strip()


def _sha_preview(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _print_dataset_counts(label: str, data: dict[str, list[dict]]) -> None:
    counts = ", ".join(f"{spec.name}={len(data.get(spec.name, []))}" for spec in DATASET_SPECS)
    print(f"[migrate] {label}: {counts}")


def _create_and_verify_backup(backup_dir: str) -> None:
    manifest = create_backup(DATA_DIR, Path(backup_dir))
    print(format_backup_manifest(manifest))
    report = verify_backup(Path(backup_dir))
    print(format_backup_verification(report))
    if report["status"] != "ok":
        print("[migrate] Error: backup verification failed; migration aborted")
        sys.exit(1)


def _close_storage(storage) -> None:
    if storage is None:
        return
    close = getattr(storage, "close", None)
    if callable(close):
        close()


def main():
    parser = argparse.ArgumentParser(
        description="ChatGPT2API 存储后端数据迁移工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 从 JSON 迁移到 PostgreSQL
  python scripts/migrate_storage.py --from json --to postgres

  # 迁移前只预演，不写入目标后端
  python scripts/migrate_storage.py --from json --to postgres --dry-run

  # 迁移前生成并校验完整 JSON 备份
  python scripts/migrate_storage.py --from json --to postgres --backup-dir data/backups/pre-postgres
  
  # 只校验两个后端的数据数量和主键集合
  python scripts/migrate_storage.py --from json --to postgres --verify-only
  
  # 导出当前后端完整数据到 JSON 文件
  python scripts/migrate_storage.py --export backup.json
  
  # 从完整 JSON 备份导入数据
  python scripts/migrate_storage.py --import backup.json

环境变量:
  STORAGE_BACKEND  - 存储后端类型 (json, sqlite, postgres, git)
  DATABASE_URL     - 数据库连接字符串
  GIT_REPO_URL     - Git 仓库地址
  GIT_TOKEN        - Git 访问令牌
        """
    )
    
    parser.add_argument(
        "--from",
        dest="from_backend",
        choices=["json", "sqlite", "postgres", "git"],
        help="源存储后端",
    )
    parser.add_argument(
        "--to",
        dest="to_backend",
        choices=["json", "sqlite", "postgres", "git"],
        help="目标存储后端",
    )
    parser.add_argument(
        "--export",
        dest="export_file",
        metavar="FILE",
        help="导出数据到 JSON 文件",
    )
    parser.add_argument(
        "--import",
        dest="import_file",
        metavar="FILE",
        help="从 JSON 文件导入数据",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预演迁移/导入/导出，不写入任何数据",
    )
    parser.add_argument(
        "--backup-dir",
        help="写入前先生成并校验完整 JSON 备份目录；与 --verify-only 单独使用时校验该备份目录",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="只执行校验，不迁移、不导入、不导出",
    )
    
    args = parser.parse_args()
    
    # 检查参数
    if args.from_backend and args.to_backend:
        migrate_data(
            args.from_backend,
            args.to_backend,
            dry_run=args.dry_run,
            backup_dir=args.backup_dir,
            verify_only=args.verify_only,
        )
    elif args.export_file:
        if args.verify_only:
            print("[migrate] Error: --verify-only cannot be used with --export")
            sys.exit(1)
        export_to_json(args.export_file, dry_run=args.dry_run)
    elif args.import_file:
        import_from_json(
            args.import_file,
            dry_run=args.dry_run,
            backup_dir=args.backup_dir,
            verify_only=args.verify_only,
        )
    elif args.verify_only and args.backup_dir:
        verify_backup_dir(args.backup_dir)
    elif args.verify_only:
        audit_json_data(fail_on_issues=True)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
