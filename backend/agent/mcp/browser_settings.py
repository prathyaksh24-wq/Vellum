"""Profile and activity operations executed only by the existing browser worker.

No browser process is started by reads, preference changes or profile creation.
The default profile retains its original path and existing sign-ins.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import time
from urllib.parse import urlsplit
from uuid import uuid4

from agent.contracts.browser import (
    BrowserActivity, BrowserDownload, BrowserPreferences, BrowserProfile,
    BrowserSettingsCommand, BrowserSettingsView,
)


def profile_relative_root(identity: str) -> Path:
    # Only typed/generated IDs reach this function; check again at the path seam.
    if identity == "default":
        return Path("data/browser-session")
    if len(identity) != 32 or any(ch not in "0123456789abcdef" for ch in identity):
        raise ValueError("Unknown browser profile.")
    return Path("data/browser-session/profiles") / identity


def site_origin(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError()
        hostname = parsed.hostname.encode("idna").decode("ascii").lower()
        host = "[" + hostname + "]" if ":" in hostname else hostname
        port = parsed.port
        suffix = ":" + str(port) if port and port != {"http":80, "https":443}[parsed.scheme] else ""
        return parsed.scheme + "://" + host + suffix
    except (ValueError, UnicodeError):
        raise ValueError("Enter an exact http or https site, without a path, credentials or wildcards.") from None


def download_directory(value: str, fallback: Path) -> Path:
    if not value.strip():
        return fallback
    path = Path(value.strip())
    # Network shares and device paths can transmit Windows credentials.
    if not path.is_absolute() or value.startswith(("\\\\", "//")) or (os.name == "nt" and path.drive.startswith("\\")):
        raise ValueError("Enter an absolute local folder path.")
    if path.exists() and not path.is_dir():
        raise ValueError("Choose a folder, not a file.")
    return path


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        # Windows file scanners can briefly hold the destination after a read.
        # Retry only sharing/permission failures, with a bounded 75 ms delay.
        for attempt in range(3):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(.025 * (attempt + 1))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


class BrowserSettingsMixin:
    def _profile(self, identity: str = "") -> BrowserProfile:
        preferences = self._browser_preferences()
        identity = identity or preferences.active_profile_id
        for profile in preferences.profiles:
            if profile.id == identity:
                return profile
        raise ValueError("This browser profile no longer exists. Refresh Settings.")

    def _profile_root(self, identity: str = "") -> Path:
        return self._storage_path(profile_relative_root(self._profile(identity).id))

    def _activity_path(self) -> Path:
        return self._profile_root() / "activity.json"

    def _load_activity(self) -> dict:
        try:
            data = json.loads(self._activity_path().read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            return data
        except (OSError, ValueError):
            return {}

    def _restore_downloads(self) -> None:
        self._downloads.clear()
        self._paths.clear()
        for entry in self._load_activity().get("downloads", [])[-500:]:
            try:
                item = BrowserDownload.model_validate(entry["item"])
                # Pending transfers do not survive worker shutdown.
                if item.state in {"downloading", "awaiting_approval"}:
                    item.state = "failed"
                self._downloads[item.id] = item
                if item.state == "saved" and entry.get("path"):
                    self._paths[item.id] = Path(entry["path"])
            except (ValueError, KeyError, TypeError):
                continue

    def _persist_downloads(self) -> None:
        data = self._load_activity()
        data["downloads"] = [{"item":item.model_dump(), "path":str(self._paths.get(item.id, ""))}
                             for item in list(self._downloads.values())[-500:]]
        atomic_json(self._activity_path(), data)

    def _record_activity(self, event: str, url: str = "", title: str = "") -> None:
        data = self._load_activity()
        entries = data.get("activity", [])
        entries.append(BrowserActivity(id=uuid4().hex, at=datetime.now(timezone.utc).isoformat(),
            event=event, url=url[:4096], title=title[:512]).model_dump())
        data["activity"] = entries[-500:]
        try:
            atomic_json(self._activity_path(), data)
        except OSError:
            # Activity is evidence, not a reason to prevent navigation.
            pass

    def _store_preferences(self, preferences: BrowserPreferences) -> None:
        preferences = self._validated_preferences(preferences)
        try:
            atomic_json(self._storage_path(Path("data/browser-session/preferences.json")), preferences.model_dump())
        except OSError:
            raise ValueError("Browser preferences could not be saved. Try again.") from None
        self._preferences = preferences

    def agent_policy(self, url: str, kind: str = "browsing") -> str:
        preferences = self._browser_preferences()
        if not preferences.agent_enabled:
            return "block"
        try:
            parsed = urlsplit(url)
            origin = site_origin(parsed.scheme + "://" + parsed.netloc)
        except ValueError:
            return "allow" if url == "about:blank" else "block"
        rule = next((rule for rule in self._profile().site_rules if rule.origin == origin), None)
        return getattr(rule, kind) if rule else getattr(preferences, "agent_" + kind)

    def _write_native_preferences(self) -> None:
        """Apply Chromium content settings before launching our closed profile.

        Keep all unrelated Brave preferences; never write into a running profile.
        """
        profile = self._profile()
        path = self._profile_root() / "profile/Default/Preferences"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            raise ValueError("Brave's profile preferences could not be read. Repair the profile before opening it.") from None
        settings = data.setdefault("profile", {})
        values = {"allow":1, "block":2, "ask":3}
        keys = {"location":"geolocation", "camera":"media_stream_camera", "microphone":"media_stream_mic",
                "notifications":"notifications", "javascript":"javascript", "images":"images", "popups":"popups"}
        settings.setdefault("default_content_setting_values", {}).update({native:values[getattr(profile.site_defaults, key)] for key, native in keys.items()})
        blocked = profile.site_defaults.third_party_cookies == "block"
        settings["block_third_party_cookies"] = blocked
        settings["cookie_controls_mode"] = 1 if blocked else 0
        exceptions = settings.setdefault("content_settings", {}).setdefault("exceptions", {})
        # This dedicated profile's rules are managed by Vellum. Replace only the
        # categories exposed here, leaving unrelated Brave settings intact.
        for key, native in keys.items():
            exceptions[native] = {rule.origin + ",*":{"setting":values[getattr(rule.permissions, key)]}
                                  for rule in profile.site_rules if rule.permissions is not None}
        atomic_json(path, data)

    def _expire_site_permissions(self) -> None:
        preferences = self._browser_preferences().model_copy(deep=True)
        if not preferences.expire_site_permissions:
            return
        threshold = datetime.now(timezone.utc) - timedelta(days=90)
        visits = {}
        for item in self._load_activity().get("activity", []):
            try:
                parsed = urlsplit(item.get("url", ""))
                origin = site_origin(parsed.scheme + "://" + parsed.netloc)
                date = datetime.fromisoformat(item["at"])
                if date.tzinfo is not None:
                    visits[origin] = max(visits.get(origin, date), date)
            except (ValueError, KeyError, TypeError):
                continue
        changed = False
        profile = next(item for item in preferences.profiles if item.id == preferences.active_profile_id)
        for rule in profile.site_rules:
            if rule.permissions is None:
                continue
            try:
                updated = datetime.fromisoformat(rule.updated_at)
                if updated.tzinfo is None:
                    continue
            except ValueError:
                continue
            if max(updated, visits.get(rule.origin, updated)) < threshold:
                for name in ("location", "camera", "microphone", "notifications"):
                    if getattr(rule.permissions, name) == "allow":
                        setattr(rule.permissions, name, "ask")
                        changed = True
        if changed:
            self._store_preferences(preferences)

    async def settings_view(self) -> BrowserSettingsView:
        # Full bounded history is distinct from the eight address suggestions.
        if self.context is None:
            history = self._read_address_history()
            if history is not None:
                self._address_history = history
        activity = []
        for item in self._load_activity().get("activity", [])[-500:]:
            try:
                activity.append(BrowserActivity.model_validate(item))
            except (ValueError, TypeError):
                continue
        return BrowserSettingsView(preferences=self._browser_preferences(), running=self.context is not None,
            history=self._address_history[:500], downloads=list(self._downloads.values())[-500:],
            activity=list(reversed(activity)), download_directory=str(download_directory(
                self._browser_preferences().download_directory, self._storage_path(Path("data/browser-downloads")))))

    def _remove_owned_path(self, target: Path) -> None:
        base = self._storage_path(Path("data/browser-session")).resolve()
        resolved = target.resolve()
        if resolved == base or base not in resolved.parents:
            raise ValueError("The browser data path is outside Vellum's profiles.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)

    async def manage_settings(self, request: BrowserSettingsCommand) -> BrowserSettingsView:
        preferences = self._browser_preferences().model_copy(deep=True)
        operation = request.operation
        if operation == "preferences":
            if request.patch is None:
                raise ValueError("Choose a browser preference to change.")
            preferences = BrowserPreferences.model_validate({**preferences.model_dump(), **request.patch.model_dump(exclude_none=True)})
            download_directory(preferences.download_directory, self._storage_path(Path("data/browser-downloads")))
            self._store_preferences(preferences)
            if not preferences.agent_enabled and self.control == "agent":
                self.control = "paused"
        elif operation == "create_profile":
            name = request.name.strip()
            if not name or len(preferences.profiles) >= 12:
                raise ValueError("Give the profile a name. You can keep up to 12 profiles.")
            preferences.profiles.append(BrowserProfile(id=uuid4().hex, name=name))
            self._store_preferences(preferences)
        elif operation in {"rename_profile", "site_defaults", "site_rule", "remove_site_rule"}:
            profile = next((item for item in preferences.profiles if item.id == self._profile(request.profile_id).id), None)
            if operation == "rename_profile":
                if not request.name.strip():
                    raise ValueError("Give the profile a name.")
                profile.name = request.name.strip()
            elif operation == "site_defaults":
                if request.defaults is None:
                    raise ValueError("Choose site permissions.")
                profile.site_defaults = request.defaults
            else:
                origin = site_origin(request.rule.origin if request.rule else request.origin)
                profile.site_rules = [rule for rule in profile.site_rules if rule.origin != origin]
                if operation == "site_rule":
                    if request.rule is None:
                        raise ValueError("Choose a site rule.")
                    profile.site_rules.append(request.rule.model_copy(update={"origin":origin,"updated_at":datetime.now(timezone.utc).isoformat()}))
            # Content changes close the profile before native preferences change.
            # The UI explains this; reopening is an explicit action.
            if profile.id == preferences.active_profile_id and (operation == "site_defaults" or request.rule and request.rule.permissions is not None or operation == "remove_site_rule"):
                await self.close()
            self._store_preferences(preferences)
        elif operation == "close_profile":
            if self._profile(request.profile_id).id != preferences.active_profile_id:
                raise ValueError("This browser profile is already closed.")
            await self.close()
        elif operation in {"select_profile", "open_profile"}:
            identity = self._profile(request.profile_id).id
            if identity != preferences.active_profile_id:
                await self.close()
                preferences.active_profile_id = identity
                self._store_preferences(preferences)
                self._address_history = self._read_address_history() or []
                self._restore_downloads()
            if operation == "open_profile":
                from agent.contracts.browser import BrowserControl
                await self.ui_control(BrowserControl(operation="open"))
                self.control = "user"
        elif operation == "delete_profile":
            profile = self._profile(request.profile_id)
            if profile.id == "default":
                raise ValueError("Keep the Personal profile. Use Clear browsing data to reset it.")
            root = self._profile_root(profile.id)
            was_active = profile.id == preferences.active_profile_id
            if was_active:
                await self.close()
            self._remove_owned_path(root)
            preferences.profiles = [item for item in preferences.profiles if item.id != profile.id]
            if preferences.active_profile_id == profile.id:
                preferences.active_profile_id = "default"
            self._store_preferences(preferences)
            if was_active:
                self._address_history = self._read_address_history() or []
                self._restore_downloads()
        elif operation == "clear_data":
            if not request.data_types:
                raise ValueError("Choose the browsing data to clear.")
            profile = self._profile(request.profile_id)
            root = self._profile_root(profile.id)
            if profile.id == preferences.active_profile_id:
                await self.close()
            paths = {"history":["Default/History", "Default/History-journal", "Default/History-wal", "Default/History-shm"],
                     "cookies":["Default/Network/Cookies", "Default/Network/Cookies-journal", "Default/Network/Cookies-wal", "Default/Network/Cookies-shm", "Default/Cookies", "Default/Cookies-journal", "Default/Local Storage", "Default/Session Storage", "Default/IndexedDB", "Default/Service Worker"],
                     "cache":["Default/Cache", "Default/Code Cache", "Default/GPUCache", "ShaderCache", "GrShaderCache"]}
            from agent.mcp.electron_browser import ElectronBridge
            native = getattr(self,'_native',None) or ElectronBridge.discover(self._storage_path(Path('.desktop-runtime/browser-bridge.json')))
            if native is not None:
                await native.call('clear', profile_id=profile.id, data_types=request.data_types)
            else:
                for category in request.data_types:
                    for relative in paths.get(category, []):
                        self._remove_owned_path(root / "profile" / relative)
            try:
                data = json.loads((root / "activity.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if "history" in request.data_types:
                data["activity"] = []
                if profile.id == preferences.active_profile_id:
                    self._address_history = []
            if "downloads" in request.data_types:
                data["downloads"] = []  # Keep the downloaded files.
                if profile.id == preferences.active_profile_id:
                    self._downloads.clear()
                    self._paths.clear()
            atomic_json(root / "activity.json", data)
        elif operation == "remove_download":
            if self._profile(request.profile_id).id != preferences.active_profile_id:
                raise ValueError("The active profile changed. Refresh Downloads before continuing.")
            item = self._downloads.get(request.download_id)
            if item is None:
                raise ValueError("This download no longer exists.")
            pending = self._pending_downloads.pop(item.id, None)
            if pending is not None:
                await pending.cancel()
            self._downloads.pop(item.id, None)
            self._paths.pop(item.id, None)
            self._persist_downloads()
        elif operation == "save_download":
            if self._profile(request.profile_id).id != preferences.active_profile_id:
                raise ValueError("The active profile changed. Refresh Downloads before continuing.")
            pending = self._pending_downloads.get(request.download_id)
            item = self._downloads.get(request.download_id)
            if pending is None or item is None or item.state != "awaiting_approval":
                raise ValueError("This pending download expired. Start it again from the page.")
            directory = download_directory(request.directory, download_directory(preferences.download_directory, self._storage_path(Path("data/browser-downloads"))))
            await self._save_download(item.id, item.name, pending, directory=directory)
            self._pending_downloads.pop(item.id, None)
            if self._downloads[item.id].state != "saved":
                raise ValueError("The download could not be saved. Check the folder and start the download again from the page.")
        return await self.settings_view()
