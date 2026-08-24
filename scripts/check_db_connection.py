"""
check_db_connection.py — standalone DB connection diagnostic.
Usage: python scripts/check_db_connection.py
       docker compose exec ppe-app python scripts/check_db_connection.py
"""
import sys, os, asyncio

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import asyncpg
from app import config


async def main():
    print("=" * 70)
    print("PostgreSQL Connection Diagnostic")
    print("=" * 70)
    print(f"  Host: {config.PG_HOST}  Port: {config.PG_PORT}  DB: {config.PG_DB}  User: {config.PG_USER}")
    print(f"  Pool size configured: {config.PG_POOL_MIN}-{config.PG_POOL_MAX}")
    print("=" * 70)

    print("\n[1/3] Attempting to connect...")
    try:
        conn = await asyncpg.connect(
            host=config.PG_HOST, port=config.PG_PORT, database=config.PG_DB,
            user=config.PG_USER, password=config.PG_PASSWORD, timeout=8,
        )
        print("      Connected successfully!")
    except asyncpg.InvalidPasswordError:
        print("      FAILED: Invalid password. Check POSTGRES_PASSWORD in .env.")
        sys.exit(1)
    except asyncpg.InvalidCatalogNameError:
        print(f"      FAILED: Database '{config.PG_DB}' does not exist.")
        sys.exit(1)
    except (ConnectionRefusedError, OSError) as e:
        print(f"      FAILED: Connection refused - {e}")
        print("        -> docker compose ps / docker compose logs postgres")
        sys.exit(1)
    except Exception as e:
        print(f"      FAILED: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\n[2/3] Checking database version...")
    version = await conn.fetchval("SELECT version();")
    print(f"      {version.split(',')[0]}")

    print("\n[3/3] Checking current connection usage (helps diagnose pool exhaustion)...")
    active = await conn.fetchval(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = $1;", config.PG_DB
    )
    max_conn = await conn.fetchval("SHOW max_connections;")
    print(f"      Active connections to '{config.PG_DB}': {active} (Postgres max_connections={max_conn})")
    if active and int(active) > 50:
        print("      NOTE: high connection count - if cameras/API are failing intermittently,")
        print("      consider increasing Postgres max_connections or lowering camera count per instance.")

    await conn.close()
    print("\n" + "=" * 70)
    print("ALL CHECKS PASSED.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
