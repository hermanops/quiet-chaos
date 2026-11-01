from quiet_chaos.defaults import DEFAULT_USER_AGENTS
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


def test_default_agents_cover_browser_families_with_matching_headers() -> None:
    assert {browser_family(agent) for agent in DEFAULT_USER_AGENTS} == {
        "chrome",
        "safari",
        "firefox",
    }
    for agent in DEFAULT_USER_AGENTS:
        headers = browser_headers(agent)
        assert headers["user-agent"] == agent
        assert ("sec-fetch-mode" in headers) == (browser_family(agent) == "chrome")


def test_default_agents_include_mobile_and_desktop_browser_families() -> None:
    for mobile in (True, False):
        agents = [agent for agent in DEFAULT_USER_AGENTS if ("Mobile" in agent) == mobile]
        assert len(agents) == 3
        assert {browser_family(agent) for agent in agents} == {"chrome", "safari", "firefox"}
