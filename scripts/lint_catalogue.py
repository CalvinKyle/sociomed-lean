#!/usr/bin/env python
"""Read the live catalogue sheet (read-only) and print price/link problems.

Usage:  python scripts/lint_catalogue.py [--limit N]
Exit code 1 when there are error-level findings. Nothing is written anywhere.
"""
import argparse
import sys

sys.path.insert(0, ".")

from app.core.catalogue_lint import lint_catalogue  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=15, help="max findings printed per code")
    args = parser.parse_args()

    from app.integrations.sheets import load_data  # imported late: opens the Google Sheet

    report = lint_catalogue(load_data())
    print(report.format(limit_per_code=args.limit))
    return 1 if report.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
