from quiet_chaos.fingerprints import browser_family, browser_headers


def test_browser_family_detects_common_agents() -> None:
    assert browser_family("Mozilla/5.0 Firefox/128.0") == "firefox"
    assert browser_family("Mozilla/5.0 Version/17.5 Safari/605.1.15") == "safari"
    assert browser_family("Mozilla/5.0 Chrome/126.0 Safari/537.36") == "chrome"


def test_browser_headers_match_user_agent_family() -> None:
    headers = browser_headers("Mozilla/5.0 Firefox/128.0", referrer="https://example.com/")

    assert headers["user-agent"] == "Mozilla/5.0 Firefox/128.0"
    assert headers["accept-language"] == "en-US,en;q=0.5"
    assert headers["referer"] == "https://example.com/"
