#!/usr/bin/env python3
"""
Checks a Shopify product's JSON endpoint for stock availability.
Sends an email via Resend ONLY if the product is in stock (not sold out).
"""

import os
import sys
import json
import urllib.request

PRODUCT_URL = "https://banadirfragrance.com/products/banadirfragrance-89-extrait-de-parfum-10-ml-sample-inspired-sedley"
JSON_URL = PRODUCT_URL + ".json"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
TO_EMAIL = os.environ.get("TO_EMAIL")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")


def fetch_product_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (stock-checker)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Unexpected HTTP status: {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def is_in_stock(product_json: dict) -> bool:
    """
    A Shopify product can have multiple variants (e.g. different scent
    options). We treat the product as 'available' if ANY variant is
    available. Adjust this logic if you only care about a specific variant.
    """
    variants = product_json.get("product", {}).get("variants", [])
    if not variants:
        return False
    return any(v.get("available") is True for v in variants)


def send_email(subject: str, body: str) -> None:
    if not RESEND_API_KEY or not TO_EMAIL:
        print("Missing RESEND_API_KEY or TO_EMAIL env vars; skipping email send.", file=sys.stderr)
        sys.exit(1)

    payload = json.dumps({
        "from": FROM_EMAIL,
        "to": [TO_EMAIL],
        "subject": subject,
        "text": body,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp_body = resp.read().decode("utf-8")
        print(f"Resend response ({resp.status}): {resp_body}")


def main():
    try:
        data = fetch_product_json(JSON_URL)
    except Exception as e:
        print(f"Error fetching product JSON: {e}", file=sys.stderr)
        # Don't email on a fetch error - that's a script/network issue, not a stock event.
        sys.exit(1)

    in_stock = is_in_stock(data)
    title = data.get("product", {}).get("title", "Product")

    print(f"Checked: {title}")
    print(f"In stock: {in_stock}")

    if in_stock:
        subject = f"IN STOCK: {title}"
        body = (
            f"{title} is now available (not sold out).\n\n"
            f"Link: {PRODUCT_URL}\n"
        )
        send_email(subject, body)
        print("Email sent.")
    else:
        print("Still sold out. No email sent.")


if __name__ == "__main__":
    main()
