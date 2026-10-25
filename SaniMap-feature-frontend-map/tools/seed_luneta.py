r"""Add the Luneta comfort rooms that the frontend demo lists but the registry seed lacks.

The registry seeds only restrooms 1 and 2 on first start. The mock-mode frontend also
shows Manila Ocean Park and Quirino Grandstand, so live mode looked incomplete.

This script adds the missing ones through the Gateway as an admin (it skips any
facility whose name already exists, so running it twice is safe).

Usage (venv active, Gateway running, env filled in):
    python tools\seed_luneta.py
    python tools\seed_luneta.py --gateway http://127.0.0.1:5100

Never commit tokens. The short-lived admin token is built in memory and not printed.
"""

import argparse
import os
import sys
import time
import jwt
import requests
from dotenv import load_dotenv

load_dotenv()

FACILITIES = [
    {
        "name": "Manila Ocean Park Comfort Room",
        "latitude": 14.5794,
        "longitude": 120.9732,
        "operatingHours": "06:00-21:00",
        "pwdAccessible": True,
        "genderType": "Male/Female",
        "amenities": ["Handwashing Station", "Soap"],
        "status": "open",
    },
    {
        "name": "Quirino Grandstand Comfort Room",
        "latitude": 14.5831,
        "longitude": 120.9761,
        "operatingHours": "06:00-18:00",
        "pwdAccessible": False,
        "genderType": "Unisex",
        "amenities": ["Handwashing Station", "Baby Changing"],
        "status": "closed",
    },
]


def admin_token():
    secret = os.environ.get("JWT_SECRET", "")
    issuer = os.environ.get("JWT_ISSUER", "")
    audience = os.environ.get("JWT_AUDIENCE", "")
    if len(secret) < 32 or not issuer or not audience:
        sys.exit(
            "Set JWT_SECRET (32+ characters), JWT_ISSUER and JWT_AUDIENCE in env first."
        )
    now = int(time.time())
    claims = {
        "sub": "seed-script",
        "role": "admin",
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + 300,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def main():
    parser = argparse.ArgumentParser(
        description="Seed the missing Luneta facilities."
    )
    parser.add_argument(
        "--gateway",
        default=os.environ.get("SEED_GATEWAY_URL", "http://127.0.0.1:5000"),
    )
    args = parser.parse_args()
    base = args.gateway.rstrip("/")

    headers = {"Authorization": f"Bearer {admin_token()}"}

    try:
        existing = requests.get(f"{base}/restrooms", timeout=5)
        existing.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"Could not read {base}/restrooms: {exc}")

    names = {item["name"] for item in existing.json()}

    for facility in FACILITIES:
        if facility["name"] in names:
            print(f"skip {facility['name']} (already exists)")
            continue
        response = requests.post(
            f"{base}/restrooms", json=facility, headers=headers, timeout=5
        )
        if response.status_code == 201:
            print(
                f"added {facility['name']} -> id {response.json()['restroomId']}"
            )
        else:
            print(
                f"FAILED {facility['name']}: HTTP {response.status_code} {response.text[:200]}"
            )


if __name__ == "__main__":
    main()