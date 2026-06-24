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
