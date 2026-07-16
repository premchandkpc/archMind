"""Dangerous: drop all tables and re-migrate."""

import asyncio
import sys


async def main() -> None:
    import asyncpg

    confirm = input("DROP SCHEMA public CASCADE? Type 'yes' to confirm: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        sys.exit(0)

    c = await asyncpg.connect(
        "postgresql://civilmind:civilmind@localhost:5432/civilmind"
    )
    await c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    await c.close()
    print("Schema dropped.")


if __name__ == "__main__":
    asyncio.run(main())
