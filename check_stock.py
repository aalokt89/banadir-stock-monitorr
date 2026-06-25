#!/usr/bin/env python3
"""
Checks a Shopify product page for stock availability using a real headless
browser (Playwright), because this store's stock status ("Sold out" vs
"Add to cart") is set by client-side JavaScript AFTER the initial page
load, not baked into the server-rendered HTML.

WHY THIS APPROACH:
A plain HTTP fetch (urllib/requests) only ever sees the pre-JS HTML, which
defaults to "Sold out" regardless of true stock - confirmed by comparing
view-source output against the rendered page. Playwright launches a real
(headless) Chromium browser, lets the page's JS run, waits for the stock
button/text to settle, and THEN reads the result. This is slower per-check
than a raw HTTP fetch but is the only reliable way to see what an actual
visitor sees.

Sends an email via Resend ONLY if the product is in stock (not sold out).
"""

import os
import sys
import resend
from playwright.sync_api import sync_playwright

PRODUCT_URL = "https://banadirfragrance.com/products/banadirfragrance-89-extrait-de-parfum-10-ml-sample-inspired-sedley"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "onboarding@resend.dev")

# How long to wait (ms) after page load for client-side JS to update the
# stock state before we read it. Generous because we'd rather be slow and
# correct than fast and wrong.
JS_SETTLE_TIMEOUT_MS = 8000


def check_stock_with_browser(url: str):
    """
    Returns (in_stock: bool, debug_text: str).

    debug_text is the visible text near the add-to-cart area at the time
    we checked, so logs show exactly what was read - useful for catching
    future false positives/negatives without guessing.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent="Mozilla/5.0 (stock-checker)")
            page.goto(url, wait_until="networkidle", timeout=30000)

            # Give client-side JS extra time to settle the button/price
            # state, even after network goes idle (some apps poll or use
            # setTimeout rather than firing immediately on load).
            page.wait_for_timeout(JS_SETTLE_TIMEOUT_MS)

            # Pull the visible text of the whole product form area rather
            # than the whole page, to reduce the chance of matching
            # "Sold out" text from an unrelated section (e.g. a related
            # products carousel). Falls back to full body text if this
            # specific region isn't found, so we still get a signal.
            try:
                product_text = page.locator("main").inner_text(timeout=5000)
            except Exception:
                product_text = page.locator("body").inner_text(timeout=5000)

            in_stock = "sold out" not in product_text.lower()
            return in_stock, product_text[:2000]  # cap debug text length
        finally:
            browser.close()


def send_email(subject: str, body: str) -> None:
    """
    Uses Resend's official Python SDK rather than a raw urllib POST.

    WHY THE SWITCH: a bare urllib request was getting blocked with
    "Cloudflare error code: 1010" - a bot-fingerprint block triggered by
    requests that don't look like they come from a normal HTTP client
    library (missing standard headers, unusual TLS/request signature).
    The official SDK sends requests the way Resend's infrastructure
    expects, which avoids this entirely. This is the correct long-term
    fix rather than trying to hand-craft headers to imitate a "normal"
    client via trial and error.
    """
    if not RESEND_API_KEY or not EMAIL_TO:
        print("Missing RESEND_API_KEY or EMAIL_TO env vars; skipping email send.", file=sys.stderr)
        sys.exit(1)

    resend.api_key = RESEND_API_KEY

    try:
        result = resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [EMAIL_TO],
            "subject": subject,
            "html": body,
        })
        print(f"Resend response: {result}")
    except Exception as e:
        # Print whatever Resend's SDK surfaces about the failure, so a
        # future failure is diagnosable from the log directly.
        print(f"Resend API error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    try:
        in_stock, debug_text = check_stock_with_browser(PRODUCT_URL)
    except Exception as e:
        print(
            f"Error checking product page with browser: {e}", file=sys.stderr)
        # Don't email on a fetch/browser error - that's a script issue,
        # not a real stock event.
        sys.exit(1)

    print(f"Checked: {PRODUCT_URL}")
    print(f"In stock: {in_stock}")
    print("---- Visible text snapshot (for debugging false positives/negatives) ----")
    print(debug_text)
    print("--------------------------------------------------------------------------")

    if in_stock:
        subject = "IN STOCK: Banadirfragrance 89 (10ml sample)"
        body = (
            "<p>The product is now available (not sold out).</p>"
            f'<p><a href="{PRODUCT_URL}">{PRODUCT_URL}</a></p>'
        )
        send_email(subject, body)
        print("Email sent.")
    else:
        print("Still sold out. No email sent.")


if __name__ == "__main__":
    main()
