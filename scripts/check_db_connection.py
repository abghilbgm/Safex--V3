"""
check_db_connection.py
------------------------
Standalone diagnostic tool - run this FIRST whenever the app fails to start
with a database-related error. It tests the exact same connection settings
the main app uses, but in isolation, with a fast timeout and a clear
pass/fail report - so you know in 5 seconds whether the problem is
Postgres itself, credentials, or networking, before digging into the full
app's logs.

Usage:
    python scripts/check_db_connection.py
    (reads the same POSTGRES_* environment variables / .env as the main app)
"""
import sys
import os
import asyncio

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
    print(f"  Host:     {config.PG_HOST}")
    print(f"  Port:     {config.PG_PORT}")
    print(f"  Database: {config.PG_DB}")
    print(f"  User:     {config.PG_USER}")
    print(f"  Password: {'*' * len(config.PG_PASSWORD) if config.PG_PASSWORD else '(empty!)'}")
    print("=" * 70)

    print("\n[1/3] Attempting to connect...")
    try:
        conn = await asyncpg.connect(
            host=config.PG_HOST, port=config.PG_PORT, database=config.PG_DB,
            user=config.PG_USER, password=config.PG_PASSWORD, timeout=8,
        )
        print("      ✓ Connected successfully!")
    except asyncpg.InvalidPasswordError:
        print("      ✗ FAILED: Invalid password.")
        print("        -> Check POSTGRES_PASSWORD in your .env matches what")
        print("           Postgres was actually initialized with.")
        print("        -> If using Docker and you changed the password AFTER")
        print("           the postgres data volume was created, that change")
        print("           has NO EFFECT. Run: docker compose down -v")
        print("           (WARNING: this deletes existing data) then start again.")
        sys.exit(1)
    except asyncpg.InvalidCatalogNameError:
        print(f"      ✗ FAILED: Database '{config.PG_DB}' does not exist.")
        print("        -> If running locally (no Docker), create it with:")
        print(f'           psql -U postgres -c "CREATE DATABASE {config.PG_DB};"')
        print("        -> If using Docker, this should be created automatically -")
        print("           check: docker compose logs postgres")
        sys.exit(1)
    except (ConnectionRefusedError, OSError) as e:
        print(f"      ✗ FAILED: Connection refused - {e}")
        print("        -> Postgres isn't running or isn't reachable at this host:port.")
        print("        -> If using Docker: run 'docker compose ps' - is 'postgres' Up and healthy?")
        print("           run 'docker compose logs postgres' to see its own errors.")
        print(f"        -> If running locally: is POSTGRES_HOST set to 'localhost' (not 'postgres')?")
        print(f"           Currently set to: '{config.PG_HOST}'")
        sys.exit(1)
    except Exception as e:
        print(f"      ✗ FAILED: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\n[2/3] Checking database version...")
    version = await conn.fetchval("SELECT version();")
    print(f"      ✓ {version.split(',')[0]}")

    print("\n[3/3] Checking if tables exist yet (normal to be empty on first run)...")
    tables = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;"
    )
    if tables:
        print(f"      ✓ Found {len(tables)} table(s): {', '.join(t['table_name'] for t in tables)}")
    else:
        print("      ✓ No tables yet - this is normal before the app's first successful startup.")
        print("        Tables + your 16 seed cameras will be created automatically")
        print("        the next time you run: python -m app.main")

    await conn.close()
    print("\n" + "=" * 70)
    print("ALL CHECKS PASSED - your database connection is working correctly.")
    print("You can now run: python -m app.main")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
