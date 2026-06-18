from agent.tools.web import public_web_search_query


def test_public_web_search_preserves_public_sports_entities_and_dates():
    query = "Cristiano Ronaldo performance vs Germany yesterday"

    assert public_web_search_query(query) == query


def test_public_web_search_still_scrubs_private_contact_identifiers():
    query = "Find John Smith at john.smith@example.com"

    clean = public_web_search_query(query)

    assert "john.smith@example.com" not in clean
    assert "John Smith" not in clean
    assert "[EMAIL_1]" in clean
