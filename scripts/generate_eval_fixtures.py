"""Single CLI entry point for the fixture generation pipeline.

Subcommands mirror the four stages from ``habla_fixture_spec.md``:

    generate    Submit Message Batches to Opus, write _pending/*.json
    validate    Run universal + category checks over _pending/
    review      Rich TUI over _pending/ → _approved/ or _rejected/
    consolidate Assemble _approved/<cat>/*.json into eval/fixtures/<cat>.json
    all         generate → validate → review → consolidate
"""

from __future__ import annotations

import argparse
import sys

from scripts.fixtures import (
    consolidate_fixtures,
    generate_fixtures,
    review_fixtures,
    validate_fixtures,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "generate", help="submit batches and write pending fixtures"
    ).set_defaults(forward=generate_fixtures.main)
    sub.add_parser("validate", help="validate pending fixtures").set_defaults(
        forward=validate_fixtures.main
    )
    sub.add_parser("review", help="human review TUI").set_defaults(
        forward=review_fixtures.main
    )
    sub.add_parser("consolidate", help="assemble final category files").set_defaults(
        forward=consolidate_fixtures.main
    )
    sub.add_parser(
        "all", help="generate → validate → review → consolidate"
    ).set_defaults(forward=None)
    sub.add_parser(
        "auto",
        help="generate → auto-approve (no TUI) → consolidate",
    ).set_defaults(forward=None)

    args, rest = parser.parse_known_args()
    sys.argv = [sys.argv[0], *rest]

    if args.cmd == "all":
        # generate runs inline validation; skip standalone validate step
        for step in (
            generate_fixtures.main,
            review_fixtures.main,
            consolidate_fixtures.main,
        ):
            rc = step()
            if rc:
                return rc
        return 0

    if args.cmd == "auto":
        # generate first — consumes the user's --categories / --bands / etc.
        if (rc := generate_fixtures.main()) != 0:
            return rc
        # auto-approve takes only its own flag
        sys.argv = [sys.argv[0], "--auto-approve"]
        if (rc := review_fixtures.main()) != 0:
            return rc
        # consolidate takes no args
        sys.argv = [sys.argv[0]]
        return consolidate_fixtures.main()

    return args.forward()


if __name__ == "__main__":
    raise SystemExit(main())
