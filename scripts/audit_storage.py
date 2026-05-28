#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.storage_safety import audit_data_dir, format_audit_report


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="只读审计 YanAI 旧 JSON 存储数据",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DATA_DIR),
        help="JSON 数据目录，默认 ./data",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出机器可读 JSON 报告",
    )
    parser.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="发现异常 JSON、缺失主键或重复主键时返回非零退出码",
    )
    args = parser.parse_args()

    report = audit_data_dir(Path(args.data_dir))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_audit_report(report))

    if args.fail_on_issues and int(report["summary"]["problem_count"]) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
