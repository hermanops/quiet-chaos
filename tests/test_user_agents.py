import json

import pytest

from quiet_chaos.user_agents import UserAgentStore


def test_parse_useragents_me_extracts_unique_agents() -> None:
    text = """
    <script>
    [{"ua": "Agent One"}, {"ua": "Agent Two"}, {"ua": "Agent One"}]
    </script>
    """

    agents = UserAgentStore._parse_useragents_me(text, limit=10)

    assert agents == ["Agent One", "Agent Two"]


def test_parse_useragents_me_respects_limit() -> None:
    text = '[{"ua": "Agent One"}, {"ua": "Agent Two"}]'

    agents = UserAgentStore._parse_useragents_me(text, limit=1)

    assert agents == ["Agent One"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('<script>[{"ua": "one"}]</script>[{"ua": "two"}]', ["one", "two"]),
        ('[invalid] [{"ua": "good"}]', ["good"]),
        ('[} [{"ua": "good"}]', ["good"]),
        ('[{"ua": "unterminated"}', []),
        ('[1, null, {}, {"ua": "one"}, {"ua": "one"}]', ["one"]),
        (
            json.dumps([{"ua": 'Agent [brackets] {braces} "quotes" \\escape'}]),
            ['Agent [brackets] {braces} "quotes" \\escape'],
        ),
        ('[{"ua": "one", "nested": {"list": [1, 2]}}]', ["one"]),
    ],
)
def test_parse_useragents_me_handles_structured_candidates(text: str, expected: list[str]) -> None:
    assert UserAgentStore._parse_useragents_me(text, limit=10) == expected


def test_parse_useragents_me_limits_nesting_and_malformed_candidates() -> None:
    text = "[{" * 100_000
    assert UserAgentStore._parse_useragents_me(text, limit=10) == []


def test_parse_useragents_me_stops_scanning_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    original = json.loads

    def decode(block):
        calls.append(block)
        return original(block)

    monkeypatch.setattr("quiet_chaos.user_agents.json.loads", decode)
    text = '[{"ua": "one"}]' + '[{"ua": "unneeded"}]' * 10_000
    assert UserAgentStore._parse_useragents_me(text, limit=1) == ["one"]
    assert calls == ['[{"ua": "one"}]']


def test_parse_useragents_me_nonpositive_limit() -> None:
    assert UserAgentStore._parse_useragents_me('[{"ua": "one"}]', limit=0) == []
