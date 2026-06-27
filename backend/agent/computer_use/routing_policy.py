"""Deterministic routing hints for computer-use requests."""

from __future__ import annotations

from urllib.parse import quote_plus

KNOWN_WEBSITES = {
    "amazon": "https://www.amazon.com",
    "google": "https://www.google.com",
    "swiggy": "https://www.swiggy.com",
    "youtube": "https://www.youtube.com",
}

KNOWN_APPS = {
    "brave",
    "calculator",
    "chrome",
    "edge",
    "excel",
    "explorer",
    "notepad",
    "paint",
    "powershell",
    "terminal",
    "word",
}

WEB_TERMS = {
    "browser",
    "google",
    "site",
    "url",
    "web",
    "website",
    "youtube",
}

TERMINAL_TERMS = {
    "command",
    "powershell",
    "pytest",
    "terminal",
    "shell",
}

COMING_SOON_TERMS = {
    "cloud vm",
    "cua",
    "cua driver",
    "simultaneously",
    "same laptop",
    "virtual machine",
    "vm",
}


def classify_computer_use_request(instruction: str) -> dict[str, object]:
    """Return a serializable routing recommendation without executing actions."""

    text = " ".join(str(instruction or "").casefold().split())
    if _contains_any(text, COMING_SOON_TERMS):
        return {
            "mode": "coming_soon",
            "intent": "cloud_vm_or_cua",
            "status": "coming_soon",
            "reason": "CUA driver, cloud VM, and simultaneous local laptop sharing are not active driver modes yet.",
            "recommended_actions": [],
        }

    if _is_terminal_request(text):
        return {
            "mode": "workspace",
            "intent": "terminal",
            "status": "available",
            "reason": "Terminal commands should run in Vellum's workspace instead of typed into the host desktop.",
            "recommended_actions": [
                {"tool": "computer_use", "mode": "workspace", "action": "terminal.run"},
            ],
            "fallback_mode": "desktop",
        }

    website = _mentioned_website(text)
    if website or _is_web_request(text):
        return _browser_route(text, website)

    app = _mentioned_app(text)
    if app:
        return {
            "mode": "desktop",
            "intent": "installed_app",
            "status": "available",
            "reason": "Installed host applications require native Windows desktop app launch.",
            "required_permission": "open_apps",
            "recommended_actions": [
                {"tool": "computer_use", "mode": "desktop", "action": "open_app", "app": app},
            ],
            "fallback_mode": "workspace",
        }

    return {
        "mode": "workspace",
        "intent": "workspace_task",
        "status": "available",
        "reason": "No explicit host-app or website target was found, so use Vellum's workspace first.",
        "recommended_actions": [
            {"tool": "computer_use", "mode": "workspace", "action": "screen.screenshot"},
        ],
        "fallback_mode": "desktop",
    }


def _browser_route(text: str, website: str | None) -> dict[str, object]:
    if "youtube" in text:
        query = _extract_search_query(text)
        url = "https://www.youtube.com"
        if query:
            url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        return {
            "mode": "browser",
            "intent": "web_task",
            "status": "available",
            "reason": "YouTube and website tasks should use Playwright/browser automation directly.",
            "recommended_actions": [{"tool": "browser_navigate", "url": url}],
            "fallback_mode": "desktop",
        }

    url = KNOWN_WEBSITES.get(website or "", "")
    if not url:
        url = "https://www.google.com"
    return {
        "mode": "browser",
        "intent": "web_task",
        "status": "available",
        "reason": "Website tasks should use Playwright/browser automation before native desktop control.",
        "recommended_actions": [{"tool": "browser_navigate", "url": url}],
        "fallback_mode": "desktop",
    }


def _extract_search_query(text: str) -> str:
    for marker in ("search for ", "search ", "look up ", "find "):
        if marker not in text:
            continue
        query = text.split(marker, 1)[1]
        for stop in (",", " and click", " then click", " and open", " then open"):
            query = query.split(stop, 1)[0]
        query = query.strip()
        if query:
            return query
    return ""


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _is_terminal_request(text: str) -> bool:
    return _contains_any(text, TERMINAL_TERMS) and not _contains_any(text, WEB_TERMS)


def _is_web_request(text: str) -> bool:
    return _contains_any(text, WEB_TERMS) or "http://" in text or "https://" in text or ".com" in text


def _mentioned_website(text: str) -> str | None:
    for website in KNOWN_WEBSITES:
        if website in text:
            return website
    return None


def _mentioned_app(text: str) -> str | None:
    for app in KNOWN_APPS:
        if app in text:
            return app
    return None
