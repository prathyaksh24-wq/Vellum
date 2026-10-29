from agent.plugins.credential_binding import credential_digest


def test_review_binding_matches_only_the_same_provider_and_credential() -> None:
    original = credential_digest("fixture-token", provider="linear")

    assert original == credential_digest("fixture-token", provider="linear")
    assert original != credential_digest("rotated-token", provider="linear")
    assert original != credential_digest("fixture-token", provider="google")


def test_structured_credential_binding_ignores_mapping_order() -> None:
    assert credential_digest({"token": "fixture", "account": "one"}, provider="google") == credential_digest(
        {"account": "one", "token": "fixture"}, provider="google"
    )
