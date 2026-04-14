#!/usr/bin/env python3
"""Monitor SG-image stock for a specific Shopify variant."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


PRODUCT_JSON_URL = os.environ.get(
    "SG_PRODUCT_JSON_URL",
    "https://www.sg-image.com/products/"
    "sg-image-af35mm-f2-2-full-frame-lens-for-e-mount-z-mount-l-mount.js",
)
VARIANT_ID = int(os.environ.get("SG_VARIANT_ID", "48131425272033"))
PRODUCT_PAGE_URL = os.environ.get(
    "SG_PRODUCT_PAGE_URL",
    "https://www.sg-image.com/products/"
    "sg-image-af35mm-f2-2-full-frame-lens-for-e-mount-z-mount-l-mount"
    "?variant=48131425272033",
)
ISSUE_TITLE = os.environ.get(
    "SG_ALERT_ISSUE_TITLE",
    "SG-image AF35mm f/2.2 L-mount is in stock",
)
ISSUE_LABEL = os.environ.get("SG_ALERT_LABEL", "stock-alert")
RECIPIENT = os.environ.get("SG_ALERT_RECIPIENT", os.environ.get("GITHUB_REPOSITORY_OWNER", ""))


@dataclass
class VariantStatus:
    product_title: str
    variant_id: int
    variant_title: str
    json_available: bool
    page_available: bool
    available: bool
    price: str
    page_reason: str


def http_json(url: str, token: str | None = None, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    headers = {
        "Accept": "application/json",
        "User-Agent": "stock-notification-bot/1.0",
    }
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset("utf-8")
        return json.loads(response.read().decode(charset))


def http_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "stock-notification-bot/1.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset("utf-8")
        return response.read().decode(charset, errors="replace")


def storefront_availability(page_html: str) -> tuple[bool, str]:
    sold_out_badge = bool(
        re.search(r'price__badge-sold-out[^>]*>\s*Sold out\s*<', page_html, flags=re.IGNORECASE)
    )

    checked_unavailable = bool(
        re.search(
            r"<input[^>]*checked[^>]*>\s*<label[^>]*>.*?label-unavailable",
            page_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )

    add_to_cart_enabled = bool(
        re.search(
            r'<button[^>]*product-form__submit[^>]*>\s*<span>\s*Add to cart\s*</span>',
            page_html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )

    if sold_out_badge:
        return False, "page shows a Sold out badge"
    if checked_unavailable:
        return False, "selected page options are marked sold out or unavailable"
    if not add_to_cart_enabled:
        return False, "page does not show an enabled Add to cart button"
    return True, "page shows the selected variant as purchasable"


def fetch_variant_status() -> VariantStatus:
    product = http_json(PRODUCT_JSON_URL)
    page_html = http_text(PRODUCT_PAGE_URL)
    variants = product.get("variants", [])
    page_available, page_reason = storefront_availability(page_html)

    for variant in variants:
        if int(variant["id"]) == VARIANT_ID:
            cents = int(variant["price"])
            price = f"${cents / 100:.2f}"
            json_available = bool(variant["available"])
            return VariantStatus(
                product_title=product["title"],
                variant_id=VARIANT_ID,
                variant_title=variant["title"],
                json_available=json_available,
                page_available=page_available,
                available=json_available and page_available,
                price=price,
                page_reason=page_reason,
            )

    raise RuntimeError(f"Variant {VARIANT_ID} was not found at {PRODUCT_JSON_URL}")


def github_api_url(path: str) -> str:
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    return f"{api_url.rstrip('/')}{path}"


def repo_issues_url(query: str = "") -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY is required for issue notifications")
    suffix = f"?{query}" if query else ""
    return github_api_url(f"/repos/{repo}/issues{suffix}")


def list_matching_issues(token: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "state": "all",
            "labels": ISSUE_LABEL,
            "per_page": "100",
        }
    )
    issues = http_json(repo_issues_url(params), token=token)
    return [issue for issue in issues if issue.get("title") == ISSUE_TITLE and "pull_request" not in issue]


def post_issue_comment(token: str, issue_number: int, body: str) -> None:
    http_json(
        github_api_url(f"/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{issue_number}/comments"),
        token=token,
        method="POST",
        payload={"body": body},
    )


def create_issue(token: str, status: VariantStatus) -> None:
    mention = f"@{RECIPIENT} " if RECIPIENT else ""
    body = (
        f"{mention}The tracked variant is in stock.\n\n"
        f"- Product: {status.product_title}\n"
        f"- Variant: {status.variant_title}\n"
        f"- Price: {status.price}\n"
        f"- Variant ID: `{status.variant_id}`\n"
        f"- Link: {PRODUCT_PAGE_URL}\n"
        f"- Shopify JSON available: `{str(status.json_available).lower()}`\n"
        f"- Storefront page available: `{str(status.page_available).lower()}` ({status.page_reason})\n"
    )
    payload: dict[str, Any] = {
        "title": ISSUE_TITLE,
        "body": body,
        "labels": [ISSUE_LABEL],
    }
    if RECIPIENT:
        payload["assignees"] = [RECIPIENT]
    http_json(repo_issues_url(), token=token, method="POST", payload=payload)


def update_issue_state(token: str, issue_number: int, state: str) -> None:
    http_json(
        github_api_url(f"/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{issue_number}"),
        token=token,
        method="PATCH",
        payload={"state": state},
    )


def update_notifications(status: VariantStatus) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    if not token or not os.environ.get("GITHUB_REPOSITORY"):
        print("GitHub issue notifications skipped because GITHUB_TOKEN or GITHUB_REPOSITORY is missing.")
        return

    issues = list_matching_issues(token)
    open_issue = next((issue for issue in issues if issue.get("state") == "open"), None)
    closed_issue = next((issue for issue in issues if issue.get("state") == "closed"), None)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if status.available:
        if open_issue:
            print(f"Issue #{open_issue['number']} is already open; leaving it in place.")
            return

        if closed_issue:
            update_issue_state(token, closed_issue["number"], "open")
            post_issue_comment(
                token,
                closed_issue["number"],
                (
                    f"Back in stock as of {timestamp}.\n\n"
                    f"- Variant: {status.variant_title}\n"
                    f"- Price: {status.price}\n"
                    f"- Link: {PRODUCT_PAGE_URL}\n"
                    f"- Shopify JSON available: `{str(status.json_available).lower()}`\n"
                    f"- Storefront page available: `{str(status.page_available).lower()}` ({status.page_reason})"
                ),
            )
            print(f"Reopened issue #{closed_issue['number']}.")
            return

        create_issue(token, status)
        print("Created a new GitHub issue notification.")
        return

    if open_issue:
        post_issue_comment(
            token,
            open_issue["number"],
            f"Out of stock again as of {timestamp}. Closing this alert until it returns.",
        )
        update_issue_state(token, open_issue["number"], "closed")
        print(f"Closed issue #{open_issue['number']} because the variant is out of stock.")
        return

    print("Variant is out of stock and there is no open alert issue.")


def write_summary(status: VariantStatus) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = [
        "## SG-image stock check",
        "",
        f"- Product: {status.product_title}",
        f"- Variant: {status.variant_title}",
        f"- Variant ID: `{status.variant_id}`",
        f"- Price: {status.price}",
        f"- Shopify JSON available: `{'yes' if status.json_available else 'no'}`",
        f"- Storefront page available: `{'yes' if status.page_available else 'no'}`",
        f"- Page signal: {status.page_reason}",
        f"- Alert eligible: `{'yes' if status.available else 'no'}`",
        f"- Link: {PRODUCT_PAGE_URL}",
        "",
    ]
    content = "\n".join(lines)
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(content)
    else:
        print(content)


def main() -> int:
    try:
        status = fetch_variant_status()
        print(
            f"Checked variant {status.variant_id} ({status.variant_title}): "
            f"{'in stock' if status.available else 'out of stock'} at {status.price} "
            f"(json={status.json_available}, page={status.page_available})"
        )
        write_summary(status)
        update_notifications(status)
        return 0
    except urllib.error.HTTPError as exc:
        print(f"HTTP error while checking stock: {exc}", file=sys.stderr)
    except urllib.error.URLError as exc:
        print(f"Network error while checking stock: {exc}", file=sys.stderr)
    except Exception as exc:  # pragma: no cover - safety net for Actions logs
        print(f"Stock check failed: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
