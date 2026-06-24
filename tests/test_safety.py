from quiet_chaos.safety import SafetyPolicy


def test_safety_policy_allows_http_and_https() -> None:
    policy = SafetyPolicy(["localhost"])

    assert policy.is_allowed_url("https://example.com/path")
    assert policy.is_allowed_url("http://example.com/path")


def test_safety_policy_rejects_unsafe_urls() -> None:
    policy = SafetyPolicy(["localhost", "example.internal"])

    assert not policy.is_allowed_url("file:///etc/passwd")
    assert not policy.is_allowed_url("javascript:alert(1)")
    assert not policy.is_allowed_url("https://localhost/admin")
    assert not policy.is_allowed_url("https://api.example.internal/status")
