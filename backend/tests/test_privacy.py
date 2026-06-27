from agent.privacy.classifier import DataClass, classify
from agent.privacy.scrubber import PrivacyScrubber


def test_scrubber_removes_common_pii_and_identifiers():
    text = (
        "Contact John Smith at john.smith@example.com or +1 415 555 0101. "
        "He works at Acme Corp near 221B Baker Street. "
        "SSN 123-45-6789 and api_key=secret-value must not leave local."
    )

    clean, replacements = PrivacyScrubber().scrub(text)

    leaked_values = [
        "John Smith",
        "john.smith@example.com",
        "+1 415 555 0101",
        "Acme Corp",
        "221B Baker Street",
        "123-45-6789",
        "secret-value",
    ]
    for value in leaked_values:
        assert value not in clean

    labels = {item.label for item in replacements}
    assert {"PERSON", "EMAIL", "PHONE", "ORGANIZATION", "ADDRESS", "GOVERNMENT_ID", "SECRET"} <= labels


def test_classifier_blocks_red_sensitive_material():
    data_class, reason = classify("password=super-secret and SSN 123-45-6789")

    assert data_class == DataClass.RED
    assert "secret" in reason.casefold() or "government" in reason.casefold()


def test_classifier_marks_names_addresses_and_orgs_yellow():
    data_class, reason = classify("Email Jane Doe at Example Labs, 10 Downing Street.")

    assert data_class == DataClass.YELLOW
    assert "pii detected" in reason.casefold()


def test_classifier_allows_public_queries():
    data_class, reason = classify("latest NBA standings and playoff schedule")

    assert data_class == DataClass.GREEN
    assert "no sensitive" in reason.casefold()
