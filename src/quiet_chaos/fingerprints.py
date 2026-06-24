from __future__ import annotations


def browser_family(user_agent: str) -> str:
    normalized = user_agent.lower()
    if "firefox" in normalized:
        return "firefox"
    if "safari" in normalized and "chrome" not in normalized and "chromium" not in normalized:
        return "safari"
    return "chrome"


def browser_headers(user_agent: str, referrer: str | None = None) -> dict[str, str]:
    family = browser_family(user_agent)
    headers = {
        "user-agent": user_agent,
        "accept-encoding": "gzip, deflate",
        "cache-control": "max-age=0",
        "upgrade-insecure-requests": "1",
    }
    if referrer:
        headers["referer"] = referrer

    if family == "firefox":
        headers.update(
            {
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,*/*;q=0.8"
                ),
                "accept-language": "en-US,en;q=0.5",
            }
        )
    elif family == "safari":
        headers.update(
            {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9",
            }
        )
    else:
        headers.update(
            {
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/avif,image/webp,image/apng,*/*;q=0.8"
                ),
                "accept-language": "en-US,en;q=0.9",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "none" if referrer is None else "same-origin",
                "sec-fetch-user": "?1",
            }
        )
    return headers
