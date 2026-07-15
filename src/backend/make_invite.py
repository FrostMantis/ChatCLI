"""
Interactive generator for ChatCLI registration invite codes.

Run it with no arguments and answer the prompts:

    python make_invite.py

Connects to the same database as the app, using the DB_* variables from .env.
"""
import os
import sys
import secrets
from datetime import datetime, timedelta, timezone

import mariadb
from dotenv import load_dotenv

load_dotenv()

# Unambiguous alphabet (no 0/O, 1/I) for codes people may type by hand.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def gen_code(groups: int = 3, size: int = 4) -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(groups * size))
    return "-".join(raw[i:i + size] for i in range(0, len(raw), size))


def get_conn():
    return mariadb.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "chatcli"),
        port=int(os.getenv("DB_PORT", 3306)),
        autocommit=True,
    )


def ask_int(prompt: str, default: int, minimum: int = 1) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("  Please enter a whole number.")
            continue
        if value < minimum:
            print(f"  Must be at least {minimum}.")
            continue
        return value


def ask_optional_int(prompt: str, minimum: int = 1) -> int | None:
    while True:
        raw = input(f"{prompt} (blank = never): ").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            print("  Please enter a whole number, or leave blank.")
            continue
        if value < minimum:
            print(f"  Must be at least {minimum}.")
            continue
        return value


def main() -> int:
    print("=== ChatCLI invite code generator ===")

    max_uses = ask_int("How many registrations per code?", default=1)
    count = ask_int("How many codes to generate?", default=1)
    expires_days = ask_optional_int("Days until the code expires?")

    custom = None
    if count == 1:
        custom = input("Custom code (blank = random): ").strip() or None

    expires_at = None
    if expires_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    try:
        conn = get_conn()
    except mariadb.Error as e:
        print(f"DB connection failed: {e}", file=sys.stderr)
        return 1

    cur = conn.cursor()
    made = []
    for _ in range(count):
        for _attempt in range(5):
            code = custom or gen_code()
            try:
                cur.execute(
                    "INSERT INTO invite_codes (code, max_uses, expires_at) VALUES (%s, %s, %s)",
                    (code, max_uses, expires_at),
                )
                made.append(code)
                break
            except mariadb.IntegrityError:
                if custom:
                    print(f"Code {code!r} already exists.", file=sys.stderr)
                    return 1
                continue
        else:
            print("Could not generate a unique code after several tries.", file=sys.stderr)
            return 1

    exp_txt = "never" if expires_at is None else expires_at.isoformat()
    print(f"\nCreated {len(made)} code(s) — max_uses={max_uses}, expires={exp_txt}:")
    for c in made:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
