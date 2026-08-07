from agent.tools.providers import registry
from agent.tools.providers.base import WebSearchProvider

ALL_NAMES = ("serpapi", "exa", "brave", "tavily", "ddgs", "firecrawl")


class FakeProvider(WebSearchProvider):
    def __init__(self, name, *, search=True, extract=False, available=True):
        self._name = name
        self._search = search
        self._extract = extract
        self._available = available

    @property
    def name(self):
        return self._name

    @property
    def display_name(self):
        return self._name.title()

    def is_available(self):
        return self._available

    def supports_search(self):
        return self._search

    def supports_extract(self):
        return self._extract


def install_registry(monkeypatch, **providers):
    for name in ALL_NAMES:
        monkeypatch.setitem(
            registry._PROVIDERS,
            name,
            providers.get(name) or FakeProvider(name, available=False),
        )
    return providers


def fake_settings(**attrs):
    defaults = {"web_backend": "", "web_search_backend": "", "web_extract_backend": ""}
    defaults.update(attrs)
    return type("Settings", (), defaults)()


def test_search_walk_uses_first_available(monkeypatch):
    serpapi = FakeProvider("serpapi", available=False)
    exa = FakeProvider("exa", available=True)
    install_registry(monkeypatch, serpapi=serpapi, exa=exa)

    assert registry.get_active_search_provider(fake_settings()).name == "exa"


def test_search_explicit_backend_wins(monkeypatch):
    serpapi = FakeProvider("serpapi", available=True)
    brave = FakeProvider("brave", available=True)
    install_registry(monkeypatch, serpapi=serpapi, brave=brave)

    settings = fake_settings(web_search_backend="brave")
    assert registry.get_active_search_provider(settings).name == "brave"


def test_shared_web_backend_wins_over_walk(monkeypatch):
    serpapi = FakeProvider("serpapi", available=True)
    exa = FakeProvider("exa", available=True)
    install_registry(monkeypatch, serpapi=serpapi, exa=exa)

    settings = fake_settings(web_backend="exa")
    assert registry.get_active_search_provider(settings).name == "exa"


def test_per_capability_overrides_shared(monkeypatch):
    serpapi = FakeProvider("serpapi", available=True)
    install_registry(monkeypatch, serpapi=serpapi)

    settings = fake_settings(web_backend="serpapi", web_search_backend="exa")
    # exa unavailable in registry -> falls back to walk -> serpapi
    assert registry.get_active_search_provider(settings).name == "serpapi"


def test_unknown_backend_falls_back_to_walk(monkeypatch):
    serpapi = FakeProvider("serpapi", available=True)
    install_registry(monkeypatch, serpapi=serpapi)

    settings = fake_settings(web_search_backend="bogus")
    assert registry.get_active_search_provider(settings).name == "serpapi"


def test_extract_walk_skips_search_only_providers(monkeypatch):
    serpapi = FakeProvider("serpapi", search=True, extract=False, available=True)
    firecrawl = FakeProvider("firecrawl", search=False, extract=True, available=True)
    install_registry(monkeypatch, serpapi=serpapi, firecrawl=firecrawl)

    assert registry.get_active_search_provider(fake_settings()).name == "serpapi"
    assert registry.get_active_extract_provider(fake_settings()).name == "firecrawl"


def test_extract_explicit_backend_must_support_extract(monkeypatch):
    serpapi = FakeProvider("serpapi", search=True, extract=False, available=True)
    firecrawl = FakeProvider("firecrawl", search=False, extract=True, available=True)
    install_registry(monkeypatch, serpapi=serpapi, firecrawl=firecrawl)

    settings = fake_settings(web_extract_backend="serpapi")
    # serpapi cannot extract -> falls back to walk -> firecrawl
    assert registry.get_active_extract_provider(settings).name == "firecrawl"


def test_no_available_provider_returns_none(monkeypatch):
    install_registry(monkeypatch)

    assert registry.get_active_search_provider(fake_settings()) is None
    assert registry.get_active_extract_provider(fake_settings()) is None


def test_provider_chain_starts_at_active_provider(monkeypatch):
    serpapi = FakeProvider("serpapi", available=True)
    exa = FakeProvider("exa", available=True)
    brave = FakeProvider("brave", available=True)
    install_registry(monkeypatch, serpapi=serpapi, exa=exa, brave=brave)

    settings = fake_settings(web_search_backend="brave")
    chain = registry.provider_chain("search", settings)

    assert [p.name for p in chain] == ["brave", "serpapi", "exa"]


def test_register_provider_is_last_writer_wins(monkeypatch):
    install_registry(monkeypatch, serpapi=FakeProvider("serpapi", available=True))
    replacement = FakeProvider("serpapi", available=True)
    registry.register_provider(replacement)

    assert registry.get_provider("serpapi") is replacement
