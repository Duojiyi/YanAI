from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    filename: str
    primary_key: str
    description: str
    list_key: str | None = None
    unique_keys: tuple[str, ...] = ()


DATASET_SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec("accounts", "accounts.json", "access_token", "账号池", unique_keys=("user_id",)),
    DatasetSpec("auth_keys", "auth_keys.json", "id", "API 鉴权密钥", list_key="items"),
    DatasetSpec("users", "users.json", "id", "用户"),
    DatasetSpec("sessions", "sessions.json", "id", "登录会话", unique_keys=("token_hash",)),
    DatasetSpec("redeem_codes", "redeem_codes.json", "id", "兑换码", unique_keys=("code",)),
    DatasetSpec("channels", "channels.json", "id", "外部图片渠道"),
    DatasetSpec("prompt_library", "prompt_library.json", "id", "提示词库"),
    DatasetSpec("image_records", "image_records.json", "id", "图片记录"),
)


MANIFEST_NAME = "manifest.json"


def audit_data_dir(data_dir: Path) -> dict[str, Any]:
    data_dir = Path(data_dir)
    datasets = [_audit_dataset(data_dir, spec) for spec in DATASET_SPECS]
    summary = {
        "dataset_count": len(DATASET_SPECS),
        "files_present": sum(1 for item in datasets if item["exists"]),
        "files_missing": sum(1 for item in datasets if not item["exists"]),
        "total_items": sum(int(item["count"]) for item in datasets),
        "invalid_json_files": sum(1 for item in datasets if item["json_error"]),
        "shape_error_files": sum(1 for item in datasets if item["shape_error"]),
        "non_object_items": sum(int(item["non_object_count"]) for item in datasets),
        "missing_primary_key_items": sum(int(item["missing_primary_key_count"]) for item in datasets),
        "duplicate_primary_key_groups": sum(int(item["duplicate_primary_key_group_count"]) for item in datasets),
        "duplicate_unique_key_groups": sum(
            sum(int(stat["duplicate_group_count"]) for stat in item["unique_key_stats"].values())
            for item in datasets
        ),
    }
    summary["problem_count"] = (
        summary["invalid_json_files"]
        + summary["shape_error_files"]
        + summary["non_object_items"]
        + summary["missing_primary_key_items"]
        + summary["duplicate_primary_key_groups"]
        + summary["duplicate_unique_key_groups"]
    )
    return {
        "generated_at": _now_iso(),
        "data_dir": str(data_dir),
        "inventory": [_spec_to_dict(spec) for spec in DATASET_SPECS],
        "datasets": datasets,
        "summary": summary,
    }


def create_backup(data_dir: Path, backup_dir: Path | None = None) -> dict[str, Any]:
    data_dir = Path(data_dir)
    if backup_dir is None:
        backup_dir = data_dir / "backups" / f"storage-json-{_timestamp()}"
    else:
        backup_dir = Path(backup_dir)

    if (backup_dir / MANIFEST_NAME).exists():
        raise FileExistsError(f"backup manifest already exists: {backup_dir / MANIFEST_NAME}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    audit_report = audit_data_dir(data_dir)
    datasets = []
    for spec in DATASET_SPECS:
        source = data_dir / spec.filename
        target = backup_dir / spec.filename
        dataset_audit = next(item for item in audit_report["datasets"] if item["name"] == spec.name)
        record: dict[str, Any] = {
            "name": spec.name,
            "filename": spec.filename,
            "primary_key": spec.primary_key,
            "exists": source.exists(),
            "count": dataset_audit["count"],
            "sha256": None,
            "bytes": 0,
        }
        if source.exists():
            shutil.copy2(source, target)
            record["sha256"] = sha256_file(target)
            record["bytes"] = target.stat().st_size
        datasets.append(record)

    manifest = {
        "version": 1,
        "created_at": _now_iso(),
        "source_data_dir": str(data_dir),
        "backup_dir": str(backup_dir),
        "manifest_file": str(backup_dir / MANIFEST_NAME),
        "inventory": [_spec_to_dict(spec) for spec in DATASET_SPECS],
        "datasets": datasets,
        "audit_summary": audit_report["summary"],
    }
    (backup_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    backup_dir = Path(backup_dir)
    manifest_path = backup_dir / MANIFEST_NAME
    problems: list[str] = []
    if not manifest_path.exists():
        return {
            "checked_at": _now_iso(),
            "backup_dir": str(backup_dir),
            "status": "failed",
            "problems": [f"missing {MANIFEST_NAME}"],
        }

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "checked_at": _now_iso(),
            "backup_dir": str(backup_dir),
            "status": "failed",
            "problems": [f"invalid manifest JSON: {exc}"],
        }

    records = {
        str(item.get("name") or ""): item
        for item in manifest.get("datasets", [])
        if isinstance(item, dict)
    }
    expected_names = {spec.name for spec in DATASET_SPECS}
    missing_records = sorted(expected_names - set(records))
    extra_records = sorted(set(records) - expected_names)
    if missing_records:
        problems.append(f"manifest missing dataset records: {', '.join(missing_records)}")
    if extra_records:
        problems.append(f"manifest has unknown dataset records: {', '.join(extra_records)}")

    for spec in DATASET_SPECS:
        record = records.get(spec.name) or {}
        target = backup_dir / spec.filename
        expected_exists = bool(record.get("exists"))
        if expected_exists and not target.exists():
            problems.append(f"{spec.filename}: file missing")
            continue
        if not expected_exists:
            continue
        expected_sha = str(record.get("sha256") or "")
        actual_sha = sha256_file(target)
        if expected_sha and actual_sha != expected_sha:
            problems.append(f"{spec.filename}: checksum mismatch")

    audit_report = audit_data_dir(backup_dir)
    for item in audit_report["datasets"]:
        record = records.get(item["name"]) or {}
        if not bool(record.get("exists")):
            continue
        if item["json_error"]:
            problems.append(f"{item['filename']}: invalid JSON in backup")
        if item["shape_error"]:
            problems.append(f"{item['filename']}: {item['shape_error']}")
        if int(record.get("count") or 0) != int(item["count"]):
            problems.append(
                f"{item['filename']}: count mismatch, manifest={record.get('count')} actual={item['count']}"
            )

    return {
        "checked_at": _now_iso(),
        "backup_dir": str(backup_dir),
        "status": "ok" if not problems else "failed",
        "problems": problems,
        "manifest": manifest,
        "audit_summary": audit_report["summary"],
    }


def restore_backup(backup_dir: Path, target_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    backup_dir = Path(backup_dir)
    target_dir = Path(target_dir)
    verification = verify_backup(backup_dir)
    if verification["status"] != "ok":
        raise ValueError("backup verification failed: " + "; ".join(verification["problems"]))

    manifest = verification["manifest"]
    copied = []
    target_dir.mkdir(parents=True, exist_ok=True)
    for record in manifest.get("datasets", []):
        if not isinstance(record, dict) or not record.get("exists"):
            continue
        filename = str(record.get("filename") or "")
        source = backup_dir / filename
        target = target_dir / filename
        if target.exists() and not overwrite:
            raise FileExistsError(f"target file already exists: {target}")
        shutil.copy2(source, target)
        copied.append(filename)

    return {
        "restored_at": _now_iso(),
        "backup_dir": str(backup_dir),
        "target_dir": str(target_dir),
        "copied_files": copied,
    }


def format_audit_report(report: dict[str, Any]) -> str:
    lines = [
        "Storage JSON audit",
        f"Data dir: {report['data_dir']}",
        "",
        "Inventory:",
    ]
    for spec in report["inventory"]:
        lines.append(
            f"  - {spec['filename']}: {spec['description']} (primary key: {spec['primary_key']})"
        )

    lines.extend(["", "Datasets:"])
    lines.append(
        "  {name:<16} {status:<12} {count:>7} {missing:>10} {dupes:>10} {extra}".format(
            name="name",
            status="status",
            count="count",
            missing="missing_pk",
            dupes="dup_pk",
            extra="notes",
        )
    )
    for item in report["datasets"]:
        status = "missing"
        notes: list[str] = []
        if item["exists"]:
            status = "ok"
        if item["json_error"]:
            status = "invalid-json"
            notes.append(str(item["json_error"]))
        elif item["shape_error"]:
            status = "bad-shape"
            notes.append(str(item["shape_error"]))
        if item["non_object_count"]:
            notes.append(f"non_object={item['non_object_count']}")
        unique_dup_count = sum(
            int(stat["duplicate_group_count"]) for stat in item["unique_key_stats"].values()
        )
        if unique_dup_count:
            notes.append(f"unique_dup_groups={unique_dup_count}")
        lines.append(
            "  {name:<16} {status:<12} {count:>7} {missing:>10} {dupes:>10} {extra}".format(
                name=item["name"],
                status=status,
                count=item["count"],
                missing=item["missing_primary_key_count"],
                dupes=item["duplicate_primary_key_group_count"],
                extra="; ".join(notes),
            )
        )

    summary = report["summary"]
    lines.extend(
        [
            "",
            "Summary:",
            f"  files present/missing: {summary['files_present']}/{summary['files_missing']}",
            f"  total items: {summary['total_items']}",
            f"  invalid JSON files: {summary['invalid_json_files']}",
            f"  missing primary key items: {summary['missing_primary_key_items']}",
            f"  duplicate primary key groups: {summary['duplicate_primary_key_groups']}",
            f"  duplicate unique key groups: {summary['duplicate_unique_key_groups']}",
            f"  problem count: {summary['problem_count']}",
        ]
    )
    return "\n".join(lines)


def format_backup_manifest(manifest: dict[str, Any]) -> str:
    lines = [
        "Storage JSON backup created",
        f"Backup dir: {manifest['backup_dir']}",
        "",
        "Files:",
    ]
    for item in manifest["datasets"]:
        status = "copied" if item["exists"] else "missing in source"
        lines.append(
            f"  - {item['filename']}: {status}, count={item['count']}, bytes={item['bytes']}"
        )
    return "\n".join(lines)


def format_backup_verification(report: dict[str, Any]) -> str:
    lines = [
        "Storage JSON backup verification",
        f"Backup dir: {report['backup_dir']}",
        f"Status: {report['status']}",
    ]
    if report["problems"]:
        lines.append("Problems:")
        lines.extend(f"  - {problem}" for problem in report["problems"])
    return "\n".join(lines)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_dataset(data_dir: Path, spec: DatasetSpec) -> dict[str, Any]:
    path = data_dir / spec.filename
    result: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "filename": spec.filename,
        "path": str(path),
        "exists": path.exists(),
        "bytes": path.stat().st_size if path.exists() else 0,
        "primary_key": spec.primary_key,
        "count": 0,
        "json_error": None,
        "shape_error": None,
        "non_object_count": 0,
        "non_object_indices": [],
        "missing_primary_key_count": 0,
        "missing_primary_key_indices": [],
        "duplicate_primary_key_group_count": 0,
        "duplicate_primary_keys": [],
        "unique_key_stats": {},
    }
    if not path.exists():
        return result

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["json_error"] = f"{exc.msg} at line {exc.lineno} column {exc.colno}"
        return result

    items = _extract_items(raw, spec)
    if items is None:
        if spec.list_key:
            result["shape_error"] = f"expected array or object with array field {spec.list_key!r}"
        else:
            result["shape_error"] = "expected JSON array"
        return result

    result["count"] = len(items)
    result.update(_key_stats(items, spec.primary_key, primary=True))
    result["unique_key_stats"] = {
        key: _key_stats(items, key, primary=False)
        for key in spec.unique_keys
    }
    return result


def _extract_items(raw: Any, spec: DatasetSpec) -> list[Any] | None:
    if isinstance(raw, list):
        return raw
    if spec.list_key and isinstance(raw, dict):
        value = raw.get(spec.list_key)
        if isinstance(value, list):
            return value
    return None


def _key_stats(items: list[Any], key: str, *, primary: bool) -> dict[str, Any]:
    values: dict[str, list[int]] = defaultdict(list)
    missing_indices = []
    non_object_indices = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            non_object_indices.append(index)
            if primary:
                missing_indices.append(index)
            continue
        value = _clean_value(item.get(key))
        if not value:
            missing_indices.append(index)
            continue
        values[value].append(index)

    duplicate_groups = [
        {
            "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
            "count": len(indices),
            "indices": indices[:20],
        }
        for value, indices in sorted(values.items(), key=lambda pair: pair[0])
        if len(indices) > 1
    ]
    stats: dict[str, Any] = {
        "key": key,
        "missing_count": len(missing_indices),
        "missing_indices": missing_indices[:50],
        "duplicate_group_count": len(duplicate_groups),
        "duplicates": duplicate_groups,
    }
    if primary:
        stats = {
            "non_object_count": len(non_object_indices),
            "non_object_indices": non_object_indices[:50],
            "missing_primary_key_count": len(missing_indices),
            "missing_primary_key_indices": missing_indices[:50],
            "duplicate_primary_key_group_count": len(duplicate_groups),
            "duplicate_primary_keys": duplicate_groups,
        }
    return stats


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _spec_to_dict(spec: DatasetSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "filename": spec.filename,
        "primary_key": spec.primary_key,
        "description": spec.description,
        "list_key": spec.list_key,
        "unique_keys": list(spec.unique_keys),
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
