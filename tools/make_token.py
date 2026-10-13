r"""Create a short-lived demo JWT for local testing.

Usage (from the SaniMap folder, venv active):
    python tools\make_token.py admin
    python tools\make_token.py park_manager --minutes 30

Reads JWT_SECRET, JWT_ISSUER and JWT_AUDIENCE from the git-ignored .env file.
Never commit tokens, and never share them in chat.
"""
import argparse
import os
import sys
import time

import jwt
from dotenv import load_dotenv

load_dotenv()

VALID_ROLES = ("admin", "park_manager")
MIN_SECRET_LENGTH = 32
MAX_MINUTES = 24 * 60


def main():
    parser = argparse.ArgumentParser(description="Create a demo SaniMap JWT.")
    parser.add_argument("role", choices=VALID_ROLES)
    parser.add_argument("--minutes", type=int, default=60,
                        help="Token lifetime in minutes (1-1440, default 60).")
    parser.add_argument("--subject", default=None,
                        help="Optional label for who the token is for.")
    args = parser.parse_args()

    if not 1 <= args.minutes <= MAX_MINUTES:
        sys.exit(f"--minutes must be between 1 and {MAX_MINUTES}.")

    secret = os.environ.get("JWT_SECRET", "")
    issuer = os.environ.get("JWT_ISSUER", "")
    audience = os.environ.get("JWT_AUDIENCE", "")
    if len(secret) < MIN_SECRET_LENGTH or not issuer or not audience:
        sys.exit("Set JWT_SECRET (32+ characters), JWT_ISSUER and JWT_AUDIENCE in .env first.")

    now = int(time.time())
    claims = {
        "sub": args.subject or f"demo-{args.role}",
        "role": args.role,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + args.minutes * 60,
    }
    print(jwt.encode(claims, secret, algorithm="HS256"))
    print(f"(role={args.role}, expires in {args.minutes} minutes)", file=sys.stderr)


if __name__ == "__main__":
    main()