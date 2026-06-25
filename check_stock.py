#!/usr/bin/env python3
"""
Checks a Shopify product page for stock availability by inspecting the
rendered HTML for the "Sold out" vs "Add to cart" button state.

NOTE ON APPROACH: Shopify's <product>.json endpoint is normally the cleaner
way to check stock (via variants[].available), but this store's JSON does
NOT expose an `available` field on variants (confirmed by direct inspection
of the JSON response - it only has inventory_management, no
inventory_quantity or available key in the public payload). So instead we
check the actual rendered product page text, which is what's reliably
present for this store regardless of JSON quirks.
"""

import os
import sys
import re
import urllib.request
import json

PRODUCT_URL = "https://banadirfragrance.com/products/banadirfragrance-89-extrait-de-parfum-10-ml-sample-inspired-sedley"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
TO_EMAIL = os.environ.get("TO_EMAIL")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (stock-checker)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Unexpected HTTP status: {resp.status}")
        return resp.read().decode("utf-8", errors="replace")


def is_in_stock(html: str) -> bool:
    """
    Checks the rendered page for stock status text.

    This theme renders "Sold out" near the price when the variant is
    unavailable, and the add-to-cart button text changes from "Add to cart"
    to "Sold out" as well. We treat the product as sold out if "Sold out"
    appears; otherwise we treat it as in stock.

    CAVEAT: this is text-matching against the live theme's markup, which is
    less robust than structured data. If the store changes its theme, this
    may need updating. It correctly mirrors what a human visiting the page
    would see, which is the most honest signal available here given the
    JSON doesn't expose it.
    """
    # Normalize whitespace to make matching reliable regardless of how the
    # HTML wraps/indents this text.
    normalized = re.sub(r"\s+", " ", html)
    return "Sold out" not in normalized


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
        html = fetch_html(PRODUCT_URL)
    except Exception as e:
        print(f"Error fetching product page: {e}", file=sys.stderr)
        # Don't email on a fetch error - that's a script/network issue, not a stock event.
        sys.exit(1)

    in_stock = is_in_stock(html)

    print(f"Checked: {PRODUCT_URL}")
    print(f"In stock: {in_stock}")

    if in_stock:
        subject = "IN STOCK: Banadirfragrance 89 (10ml sample)"
        body = (
            "The product is now available (not sold out).\n\n"
            f"Link: {PRODUCT_URL}\n"
        )
        send_email(subject, body)
        print("Email sent.")
    else:
        print("Still sold out. No email sent.")


if __name__ == "__main__":
    main()
