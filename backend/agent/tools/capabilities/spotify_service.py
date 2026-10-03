"""Music adapter over the existing portable Spotify plugin; owns no credentials or player."""

import json
import random
import re
import unicodedata
from difflib import SequenceMatcher

from agent.contracts.music import MusicChoiceRequired, MusicPlan, MusicPlaylistCreateProposal
from agent.plugins.registry import get_plugin_registry
from agent.plugins.spotify_runtime import registered_spotify_context, spotify_catalog_query_gate
from agent.tools.registry import CapabilityAccess, CapabilityRecord, ToolPermissionError, ToolRegistry


def normalized_name(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)).split())


def title_key(value: str) -> str:
    title = normalized_name(value)
    # Featured-artist credits are catalog metadata, not a different song title.
    # Preserve remix, live, cover and other version qualifiers.
    title = re.sub(r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+[^\)\]]+[\)\]]\s*$", "", title)
    return re.sub(r"^(?:the|a)\s+", "", title)


def playlist_key(value: str) -> str:
    # Preserve emoji symbols and joiners; presentation selectors do not change identity.
    return " ".join("".join(" " if unicodedata.category(c).startswith("P") else c
                            for c in normalized_name(value) if c not in "\ufe0e\ufe0f").split())


class SpotifyCapabilityService:
    skill_id = "spotify"

    def __init__(self, *, context=None, rng=None):
        self.context = context or registered_spotify_context()
        self.rng = rng or random.SystemRandom()

    def build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        for name, record in self.context.tools.items():
            registry.register(CapabilityRecord(name=name, namespace="spotify",
                access=CapabilityAccess.READ if name in {"spotify_search", "spotify_albums", "spotify_podcasts"} else CapabilityAccess.WRITE,
                allowed_agents=frozenset({"MusicAgent"}), stream_label=name.replace("_", " "),
                adapter=lambda payload, registered=record: self._invoke(registered, payload)))
        return registry

    @staticmethod
    def _invoke(record, payload):
        if not get_plugin_registry().is_enabled("spotify"):
            raise ToolPermissionError("The Spotify integration is disabled")
        action = payload.get("action")
        writes = ((record.name == "spotify_library" and action in {"save", "remove", "save_current", "remove_current"})
                  or (record.name == "spotify_playlists" and action not in {"list", "get", "tracks", "get_tracks"}))
        if writes and payload.get("confirm") is not True:
            raise ToolPermissionError("Confirm changing your Spotify library or playlist")
        return json.loads(record.handler(payload, privacy_gate=spotify_catalog_query_gate))

    def resolve_song(self, plan: MusicPlan, invoke) -> dict:
        title = plan.query.replace('"', ' ').replace('\\', ' ').strip()
        query = 'track:"' + title + '"' + (" " + plan.artist if plan.artist else "")
        found = invoke("spotify_search", {"query":query, "types":["track"], "limit":10})
        tracks = [track for track in found.get("tracks", {}).get("items", []) if track.get("uri") and track.get("is_playable") is not False]
        if not tracks:
            raise MusicChoiceRequired("No playable song matched " + plan.query + " on Spotify.", [])
        matching = [t for t in tracks if title_key(t.get("name", "")) == title_key(plan.query)]
        # A catalog search can return unrelated popular tracks. Ask about near
        # matches instead of silently starting the first search result.
        if not matching:
            choices = [{"title":t.get("name", ""), "artist":", ".join(a.get("name", "") for a in t.get("artists", []))}
                       for t in tracks if SequenceMatcher(None, title_key(plan.query), title_key(t.get("name", ""))).ratio() >= .65]
            raise MusicChoiceRequired("No exact song title matched " + plan.query + "." +
                                      (" Did you mean " + "; ".join(c["title"] + " by " + c["artist"] for c in choices[:5]) + "? Reply with the artist." if choices else " Try its title and artist."), choices)
        candidates = matching
        if plan.artist:
            def artist_matches(track):
                requested = normalized_name(plan.artist)
                collaboration = normalized_name(", ".join(a.get("name", "") for a in track.get("artists", [])))
                return requested == collaboration or any(requested in normalized_name(a.get("name", "")) or
                           SequenceMatcher(None, requested, normalized_name(a.get("name", ""))).ratio() >= .65
                           for a in track.get("artists", []))
            candidates = [t for t in candidates if artist_matches(t)]
            if not candidates:
                raise MusicChoiceRequired("I could not find that song by " + plan.artist + ". Try the song title and artist together.", [])
        artists = {}
        for candidate in candidates:
            label = ", ".join(a.get("name", "") for a in candidate.get("artists", []))
            artists.setdefault(normalized_name(label), {"title":candidate.get("name", ""), "artist":label,
                "artists":[a.get("name", "") for a in candidate.get("artists", [])]})
        if not plan.artist and matching and (len(artists) > 1 or plan.version == "original"):
            choices = list(artists.values())[:5]
            raise MusicChoiceRequired("Which version did you mean? " + "; ".join(c["title"] + " by " + c["artist"] for c in choices) + ". Reply with the artist.", choices)
        return candidates[0]

    @staticmethod
    def _spotify_id(value: str, kind: str) -> str | None:
        match = re.fullmatch(r"(?:spotify:" + kind + r":|https://open\.spotify\.com/" + kind + r"/)([A-Za-z0-9]+)(?:\?\S*)?", value)
        return match[1] if match else None

    def resolve_playlist(self, plan: MusicPlan, invoke) -> dict:
        direct = self._spotify_id(plan.source_uri or plan.query, "playlist")
        if direct:
            # Personalized mixes may play successfully while metadata returns
            # 404. An explicit, validated link needs no catalog preflight.
            return {"id":direct, "uri":"spotify:playlist:"+direct,
                    "name":plan.query if plan.source_uri else "your linked Spotify playlist", "linked":True}
        exact, partial, seen = [], [], set()
        wanted = playlist_key(plan.query)
        for offset in range(0, 100001, 50):
            page = invoke("spotify_playlists", {"action":"list", "limit":50, "offset":offset})
            entries = page.get("items") or []
            new_entries = [p for p in entries if p and p.get("id") not in seen]
            if not new_entries:
                break
            for playlist in new_entries:
                seen.add(playlist.get("id"))
                label = playlist_key(playlist.get("name", ""))
                if label == wanted:
                    exact.append(playlist)
                elif wanted and re.search(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)", label):
                    partial.append(playlist)
            if not page.get("next"):
                break
        matches = exact or partial
        if len(matches) == 1:
            return matches[0]
        if not matches and re.search(r"\bdaily\s+mix\b", plan.query, re.I):
            raise MusicChoiceRequired("Spotify did not expose your " + plan.query + " in the saved-playlist list. Paste that playlist's Spotify link so I can try it directly.", [])
        if not matches:
            public = invoke("spotify_search", {"query":plan.query, "types":["playlist"], "limit":10})
            matches = [p for p in public.get("playlists", {}).get("items", []) if p and p.get("uri") and
                       wanted and re.search(r"(?<!\w)" + re.escape(wanted) + r"(?!\w)", playlist_key(p.get("name", "")))]
            message = "That name is missing from your saved playlists. Spotify search found "
        else:
            message = "I found multiple saved playlists: "
        choices = [{"title":p.get("name", ""), "uri":p.get("uri") or "spotify:playlist:" + p["id"]} for p in matches[:5]]
        if choices:
            raise MusicChoiceRequired(message + "; ".join(str(i+1) + ". " + c["title"] for i,c in enumerate(choices)) + ". Reply with its number or Spotify link.", choices)
        raise MusicChoiceRequired("Spotify did not return a playlist named " + plan.query + ". Paste its Spotify link to try it directly.", [])

    def resolve_podcast(self, plan: MusicPlan, invoke) -> tuple[dict, dict]:
        show_id = self._spotify_id(plan.source_uri or plan.query, "show")
        if show_id:
            show = invoke("spotify_podcasts", {"action":"show", "show_id":show_id})
        else:
            found = invoke("spotify_search", {"query":plan.query, "types":["show"], "limit":10})
            shows = [s for s in found.get("shows", {}).get("items", []) if s and s.get("id") and s.get("uri")]
            wanted = normalized_name(plan.query)
            exact = [s for s in shows if normalized_name(s.get("name", "")) == wanted]
            # A host name may be misspelled. Match its words against a bounded
            # window in the actual show title; never substitute a music track.
            def score(show):
                words = normalized_name(show.get("name", "")).split()
                length = len(wanted.split())
                return max((SequenceMatcher(None, wanted, " ".join(words[i:i+length])).ratio()
                            for i in range(len(words))), default=0)
            candidates = exact or [s for s in shows if score(s) >= .75]
            if len(candidates) != 1:
                choices = [{"title":s.get("name", ""), "uri":s["uri"]} for s in (candidates or shows)[:5]]
                raise MusicChoiceRequired("Which podcast did you mean? " + "; ".join(str(i+1) + ". " + c["title"] for i,c in enumerate(choices)) + ". Reply with the show name or number." if choices else "No podcast show matched " + plan.query + ". Try the show name or host.", choices)
            show = candidates[0]
            show_id = show["id"]
        episodes = invoke("spotify_podcasts", {"action":"episodes", "show_id":show_id, "limit":50})
        playable = [e for e in episodes.get("items", []) if e and str(e.get("uri", "")).startswith("spotify:episode:") and e.get("is_playable") is not False]
        if not playable:
            raise MusicChoiceRequired("Spotify returned no playable episodes for " + show.get("name", plan.query) + ".", [])
        return show, playable[0]

    def prepare_playlist(self, plan: MusicPlan, invoke) -> MusicPlaylistCreateProposal:
        resolved, seen = [], set()
        for index, song in enumerate(plan.songs):
            try:
                track = self.resolve_song(MusicPlan(operation="play_song", query=song.title, artist=song.artist), invoke)
            except MusicChoiceRequired as exc:
                exc.song_index = index
                raise
            if track["uri"] not in seen:
                seen.add(track["uri"])
                resolved.append({"title":track.get("name") or song.title,
                                 "artist":", ".join(a.get("name", "") for a in track.get("artists", [])), "uri":track["uri"]})
        return MusicPlaylistCreateProposal(provider="spotify", name=plan.query, description=plan.description, songs=resolved)

    def create_playlist(self, proposal: MusicPlaylistCreateProposal, invoke) -> str:
        if proposal.provider != "spotify" or any(not re.fullmatch(r"spotify:track:[A-Za-z0-9]+", song.uri) for song in proposal.songs):
            raise ValueError("The pending Spotify playlist contains an invalid song.")
        try:
            created = invoke("spotify_playlists", {"action":"create", "name":proposal.name,
                                                   "description":proposal.description, "public":False, "confirm":True})
        except Exception as exc:
            raise ValueError("Spotify did not confirm playlist creation. Check your library before retrying.") from exc
        playlist_id = created.get("id")
        if not playlist_id:
            raise ValueError("Spotify did not return a playlist ID. Check your library before retrying creation.")
        try:
            invoke("spotify_playlists", {"action":"add_items", "playlist_id":playlist_id,
                                         "uris":[song.uri for song in proposal.songs], "confirm":True})
        except Exception as exc:
            raise ValueError(f"Created {proposal.name}, but Spotify did not confirm adding its songs. Check https://open.spotify.com/playlist/{playlist_id} before retrying.") from exc
        count = len(proposal.songs)
        return f"Created private playlist {proposal.name} with {count} {'song' if count == 1 else 'songs'}. https://open.spotify.com/playlist/{playlist_id}"

    def execute(self, plan: MusicPlan, invoke) -> str:
        if plan.operation == "play_podcast":
            show, episode = self.resolve_podcast(plan, invoke)
            invoke("spotify_playback", {"action":"play", "uris":[episode["uri"]]})
            return "Playing " + episode.get("name", "an episode") + " from " + show.get("name", plan.query) + "."
        if plan.operation == "play_episode":
            found = invoke("spotify_search", {"query":plan.query, "types":["episode"], "limit":10})
            episodes = [e for e in found.get("episodes", {}).get("items", []) if e and e.get("is_playable") is not False and
                        str(e.get("uri", "")).startswith("spotify:episode:") and normalized_name(e.get("name", "")) == normalized_name(plan.query)]
            if len(episodes) != 1:
                raise MusicChoiceRequired("Give me the episode's full title and show name so I can select it correctly.", [])
            invoke("spotify_playback", {"action":"play", "uris":[episodes[0]["uri"]]})
            return "Playing podcast episode " + episodes[0]["name"] + "."
        if plan.operation == "play_song":
            track = self.resolve_song(plan, invoke)
            invoke("spotify_playback", {"action":"play", "uris":[track["uri"]]})
            artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
            return "Playing " + track.get("name", plan.query) + (" by " + artists if artists else "") + "."
        if plan.operation == "play_playlist":
            playlist = self.resolve_playlist(plan, invoke)
            uri = playlist.get("uri") or "spotify:playlist:" + playlist["id"]
            body = {"action":"play", "context_uri":uri}
            if plan.position:
                body["offset"] = {"position":plan.position-1}
                invoke("spotify_playback", {"action":"set_shuffle", "shuffle":False})
            if plan.shuffle and playlist.get("linked") and not plan.position:
                invoke("spotify_playback", {"action":"set_shuffle", "shuffle":True})
            elif plan.shuffle and not plan.position:
                details = invoke("spotify_playlists", {"action":"get", "playlist_id":playlist["id"]})
                items = details.get("items") or details.get("tracks") or {}
                total = items.get("total", 0) if isinstance(items, dict) else 0
                if total:
                    body["offset"] = {"position":self.rng.randrange(total)}
            # Activating this context first allows shuffle to target the same Vellum device.
            invoke("spotify_playback", body)
            if plan.shuffle is not None and not (plan.position and plan.shuffle is False) and not (playlist.get("linked") and plan.shuffle and not plan.position):
                invoke("spotify_playback", {"action":"set_shuffle", "shuffle":plan.shuffle})
            return "Playing " + playlist.get("name", plan.query) + (" with shuffle on." if plan.shuffle else ".")
        if plan.operation == "play_liked":
            # Liked Songs is a saved-track library, not an ordinary playlist URI.
            saved = invoke("spotify_library", {"action":"list", "kind":"tracks", "limit":50, "offset":(plan.position or 1)-1})
            total = int(saved.get("total") or 0)
            if plan.shuffle and total > 50:
                saved = invoke("spotify_library", {"action":"list", "kind":"tracks", "limit":50,
                                                   "offset":self.rng.randrange(total)})
            tracks = [entry.get("track") or {} for entry in saved.get("items", [])]
            uris = list(dict.fromkeys(t["uri"] for t in tracks if t.get("uri") and t.get("is_playable") is not False))
            if not uris:
                return "There are no playable tracks in your Liked Songs."
            if plan.shuffle:
                self.rng.shuffle(uris)
            else:
                invoke("spotify_playback", {"action":"set_shuffle", "shuffle":False})
            invoke("spotify_playback", {"action":"play", "uris":uris[:50]})
            if plan.shuffle:
                invoke("spotify_playback", {"action":"set_shuffle", "shuffle":True})
            return "Playing from your Liked Songs" + (" with shuffle on." if plan.shuffle else ".")
        if plan.operation == "current":
            state = invoke("spotify_playback", {"action":"get_state"})
            track = state.get("item") or state.get("track") or {}
            artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
            return "Currently playing " + track.get("name", "an unknown track") + (" by " + artists if artists else "") + "." if track else "Nothing is playing on Spotify."
        action = {"resume":"play"}.get(plan.operation, plan.operation)
        args = {"action":action}
        if plan.operation == "set_shuffle":
            args["shuffle"] = plan.shuffle
        if plan.operation == "set_volume":
            args["volume_percent"] = plan.volume_percent
        invoke("spotify_playback", args)
        return {"pause":"Spotify paused.", "resume":"Spotify resumed.", "next":"Skipped to the next track.",
                "previous":"Previous track requested."}.get(plan.operation, "Spotify playback setting applied.")
