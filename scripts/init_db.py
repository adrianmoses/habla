"""Bring the database up to head.

Idempotent. Assumes the database and role exist (docker-compose creates them
via POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD).
"""

from __future__ import annotations

import asyncio
import logging
import sys

from hable_ya.db import upgrade_to_head


async def amain() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        await upgrade_to_head()
    except Exception as exc:
        logging.error("init_db failed: %s", exc)
        return 1
    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
