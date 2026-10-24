"""Refresh credential-free API metadata from Google's official Discovery service."""
import json
from pathlib import Path
import re
import sys
import httpx

SOURCES = {
    "gmail": "https://gmail.googleapis.com/$discovery/rest?version=v1",
    "drive": "https://www.googleapis.com/discovery/v1/apis/drive/v3/rest",
    "calendar": "https://www.googleapis.com/discovery/v1/apis/calendar/v3/rest",
    "contacts": "https://people.googleapis.com/$discovery/rest?version=v1",
}


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / "backend/agent/plugins/google_discovery"
    destination.mkdir(exist_ok=True)
    for name, url in SOURCES.items():
        response = httpx.get(url, timeout=30, follow_redirects=False)
        response.raise_for_status()
        document = response.json()
        # Keep the published schemas intact; never fetch metadata during chat.
        document = {key: document[key] for key in (
            "id", "name", "version", "revision", "rootUrl", "servicePath", "baseUrl",
            "parameters", "resources", "schemas", "methods",
        ) if key in document}
        document["discovery_source"] = url
        (destination / (name + ".json")).write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(name, document["revision"])
    update_manifests(root)


def update_manifests(root):
    # Keep manifest ownership aligned with the same method/name generator.
    sys.path.insert(0, str(root / "backend"))
    from agent.plugins.google_api_catalog import methods, tool_name
    for service, folder in {"gmail":"gmail", "drive":"google_drive", "calendar":"google_calendar", "contacts":"google_contacts"}.items():
        path = root / "plugins/connectors" / folder / "plugin.yaml"
        text = path.read_text(encoding="utf-8")
        listing = "provides_tools:\n" + "".join(f"  - {tool_name(service, identifier)}\n" for identifier in methods(service))
        text, count = re.subn(r"(?m)^provides_tools:\n(?:[ \t]+[^\n]*\n)*", lambda match: listing, text)
        if count != 1:
            raise ValueError(f"Expected one provides_tools list in {path}")
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
