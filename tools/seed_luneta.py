r"""Add canonical Luneta comfort rooms through the Gateway when needed.

The Registry seeds these facilities automatically. This optional admin script
can add them to an already-running registry and skips names that already exist.

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
        "name": "Manila Ocean Park Restroom",
        "latitude": 14.5791,
        "longitude": 120.9723,
        "operatingHours": "10:00 - 20:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": [
            "Air-conditioned",
            "Handwashing Station",
            "Soap",
            "Toilet Paper",
            "Bidet",
            "Flush Toilet",
        ],
        "status": "open",
    },
    {
        "name": "Quirino Grandstand Comfort Room",
        "latitude": 14.5800,
        "longitude": 120.9739,
        "operatingHours": "06:00 - 22:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": [
            "Handwashing Station",
            "Soap",
            "Toilet Paper",
            "Flush Toilet",
            "Wheelchair Ramp",
        ],
        "status": "open",
    },
    {
        "name": "Relief Map Comfort Room",
        "latitude": 14.5835,
        "longitude": 120.9798,
        "operatingHours": "06:00 - 20:00",
        "pwdAccessible": True,
        "genderType": "Unisex",
        "amenities": ["Handwashing Station", "Soap", "Flush Toilet"],
        "status": "open",
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