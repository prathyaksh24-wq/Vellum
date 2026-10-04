"""Music adapter over the existing portable Spotify plugin; owns no credentials or player."""

import json
import random
import re
import time
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher

from agent.contracts.music import MusicChoiceRequired, MusicPlan, MusicPlaylistCreateProposal, MusicCollectionChangeProposal
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


def song_key(value: str) -> str:
    """Comparison only: never change the provider's title or stable URI."""
    value = title_key(value)
    value = re.sub(r'\bu\b', 'you', value)
    return ' '.join(re.sub(r'[^\w\s]', ' ', value).split())


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
        matching = [t for t in tracks if title_key(t.get("name", "")) == title_key(plan.query)]
        if not matching:
            # The exact track filter often returns no results for a typo. One
            # bounded broad catalog query supplies candidates; ranking below
            # remains deterministic and never selects an unrelated popular hit.
            broad = invoke('spotify_search', {'query':title + (' ' + plan.artist if plan.artist else ''), 'types':['track'], 'limit':10})
            additional = [t for t in broad.get('tracks', {}).get('items', []) if t and t.get('uri') and t.get('is_playable') is not False]
            tracks = list({t['uri']:t for t in tracks + additional}.values())
            matching = [t for t in tracks if title_key(t.get('name', '')) == title_key(plan.query)]
            if not matching:
                scores = {song_key(t.get('name','')):SequenceMatcher(None, song_key(plan.query), song_key(t.get('name',''))).ratio() for t in tracks}
                ranked = sorted(scores.items(), key=lambda pair:(-pair[1], pair[0]))
                if plan.artist and ranked and ranked[0][1] >= .9 and (len(ranked)==1 or ranked[0][1]-ranked[1][1] >= .08):
                    matching = [t for t in tracks if song_key(t.get('name','')) == ranked[0][0]]
        if not tracks:
            raise MusicChoiceRequired("No playable song matched " + plan.query + " on Spotify.", [])
        # A catalog search can return unrelated popular tracks. Ask about near
        # matches instead of silently starting the first search result.
        if not matching:
            choices = [{"title":t.get("name", ""), "artist":", ".join(a.get("name", "") for a in t.get("artists", []))}
                       for t in tracks if SequenceMatcher(None, title_key(plan.query), title_key(t.get("name", ""))).ratio() >= .65]
            choices = list({(title_key(c["title"]), normalized_name(c["artist"])):c for c in choices}.values())
            raise MusicChoiceRequired("No exact song title matched " + plan.query + "." +
                                      (" Did you mean " + "; ".join(c["title"] + " by " + c["artist"] for c in choices[:5]) + ("? Reply yes to play it." if len(choices)==1 else "? Reply with the artist.") if choices else " Try its title and artist."), choices)
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

    def resolve_playlist(self, plan: MusicPlan, invoke, *, saved_only=False) -> dict:
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
            if saved_only:
                raise MusicChoiceRequired('No saved playlist matched ' + plan.query + '. Give its exact name or Spotify link.', [])
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

    def resolve_album(self, plan: MusicPlan, invoke) -> dict:
        if not plan.latest:
            found = invoke('spotify_search', {'query':'album:"' + plan.query.replace('"', ' ') + '" ' + plan.artist, 'types':['album'], 'limit':10})
            albums = [a for a in found.get('albums', {}).get('items', []) if a and a.get('uri') and
                      normalized_name(a.get('name', '')) == normalized_name(plan.query) and
                      (not plan.artist or any(normalized_name(x.get('name','')) == normalized_name(plan.artist) for x in a.get('artists', [])))]
            identities = {(normalized_name(a['name']), tuple(x.get('id') or x.get('name') for x in a.get('artists', []))) for a in albums}
            if len(identities) != 1:
                raise MusicChoiceRequired('Give the album title and artist so I can select the right album.', [])
            return sorted(albums, key=lambda a:a['uri'])[0]
        found = invoke('spotify_search', {'query':plan.artist, 'types':['artist'], 'limit':10})
        artists = {a['id']:a for a in found.get('artists', {}).get('items', []) if a and a.get('id') and
                   normalized_name(a.get('name', '')) == normalized_name(plan.artist)}
        if len(artists) != 1:
            raise MusicChoiceRequired('Spotify did not identify one artist named ' + plan.artist + '. Give the artist’s exact name.', [])
        artist = next(iter(artists.values()))
        albums = []
        deadline = time.monotonic() + 12
        for offset in range(0, 1000, 10):
            if time.monotonic() >= deadline:
                raise ValueError('Album lookup reached its time limit; I have not started an older release.')
            page = invoke('spotify_albums', {'action':'artist_albums', 'artist_id':artist['id'], 'include_groups':'album', 'limit':10, 'offset':offset})
            if not isinstance(page.get('items'), list):
                raise ValueError('Spotify did not expose the artist’s album catalog.')
            albums.extend(a for a in page['items'] if a and a.get('album_type') == 'album' and a.get('uri') and
                          any(x.get('id') == artist['id'] for x in a.get('artists', [])))
            if not page.get('next'):
                break
        else:
            raise ValueError('The artist’s catalog exceeded the lookup limit; I cannot verify the latest album.')
        today = datetime.now(UTC).date().isoformat()
        dated = [a for a in albums if re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', str(a.get('release_date') or '')) and a['release_date'] <= today]
        if not dated:
            raise MusicChoiceRequired('Spotify returned no released album for ' + artist['name'] + '.', [])
        newest = max(a['release_date'] for a in dated)
        candidates = [a for a in dated if a['release_date'] == newest]
        if len({normalized_name(a['name']) for a in candidates}) > 1:
            raise MusicChoiceRequired('Multiple albums share the latest release date: ' + '; '.join(sorted({a['name'] for a in candidates})) + '. Give the album title.', [])
        return sorted(candidates, key=lambda a:a['uri'])[0]

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

    def curate_playlist(self, plan: MusicPlan, invoke) -> MusicPlaylistCreateProposal:
        year = re.search(r"\b20\d{2}\b", plan.query)
        query = "viral hits" + (" " + year[0] if year else "")
        found = invoke("spotify_search", {"query":query, "types":["playlist"], "limit":10})
        lists = [p for p in found.get("playlists", {}).get("items", []) if p and p.get("id")
                 and (not year or year[0] in str(p.get("name") or ""))]
        if not lists:
            raise ValueError("Spotify did not return a matching current playlist. Give me song titles or a source playlist link; I have not created anything.")
        requested = re.search(r"\b(\d{1,2})\s+(?:(?:trendy|trending|viral|popular|current)\s+)?songs\b", plan.query, re.I)
        count = min(50, int(requested[1])) if requested else 20
        if count<1:
            raise ValueError('Choose at least one song for the playlist.')
        fallback = False
        try:
            items = invoke("spotify_playlists", {"action":"tracks", "playlist_id":lists[0]["id"], "limit":50})
        except ValueError as exc:
            if '403' not in str(exc) and 'forbidden' not in str(exc).casefold():
                raise
            fallback = True
            items = {'items':[]}
            for offset in range(0, count, 10):
                found = invoke('spotify_search', {'query':'year:'+year[0] if year else 'viral', 'types':['track'], 'limit':10, 'offset':offset})
                tracks = found.get('tracks',{}).get('items') or []
                items['items'].extend({'track':track} for track in tracks if track)
                if not tracks:
                    break
        songs, seen = [], set()
        for entry in items.get("items", []):
            track = entry.get("track") or entry.get("item") or {}
            uri = str(track.get("uri") or "")
            if re.fullmatch(r"spotify:track:[A-Za-z0-9]+", uri) and uri not in seen and track.get("is_playable") is not False:
                seen.add(uri)
                songs.append({"title":track.get("name") or "Untitled track", "artist":", ".join(a.get("name", "") for a in track.get("artists", [])), "uri":uri})
            if len(songs) == count:
                break
        if not songs:
            raise ValueError("Spotify did not expose playable songs for that source playlist. No playlist was created.")
        description = ('Spotify blocked the public playlist contents; selected from catalog search, not verified trends.' if fallback else
            "Selected from " + str(lists[0].get("name") or "a Spotify playlist")[:200] + "; playlist labels are not verified chart rankings.")
        named = re.search(r'\b(?:named|called)\s+(.+?)(?:\s+with\b|$)',plan.query,re.I)
        name = named[1].strip(' \"') if named else ("Current Picks" if fallback else "Viral Picks") + (" " + year[0] if year else "")
        return MusicPlaylistCreateProposal(provider="spotify", name=name,
            description=description, songs=songs)

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
        try:
            saved = invoke("spotify_playlists", {"action":"get", "playlist_id":playlist_id})
            entries = invoke("spotify_playlists", {"action":"tracks", "playlist_id":playlist_id, "limit":50})
            actual = [str((entry.get("track") or entry.get("item") or {}).get("uri") or "") for entry in entries.get("items", [])]
            wanted = [song.uri for song in proposal.songs]
            if saved.get("id") != playlist_id or saved.get("name") != proposal.name or actual[:len(wanted)] != wanted:
                raise ValueError("Playlist read-back did not match the requested name and songs")
        except Exception as exc:
            raise ValueError(f"Spotify has not verified the playlist name and songs. Check https://open.spotify.com/playlist/{playlist_id} before retrying; I will not create a duplicate automatically.") from exc
        count = len(proposal.songs)
        return f"Created private playlist {proposal.name} with {count} {'song' if count == 1 else 'songs'}. https://open.spotify.com/playlist/{playlist_id}"

    def execute(self, plan: MusicPlan, invoke) -> str:
        if plan.operation=='check_current':
            return self.check_collection(plan,invoke)
        if plan.operation == 'play_album':
            album = self.resolve_album(plan, invoke)
            invoke('spotify_playback', {'action':'play', 'context_uri':album['uri']})
            self._verify_control(invoke, lambda state:state.get('is_playing') and
                (state.get('context') or {}).get('uri') == album['uri'], 'album playback', state_action='get_currently_playing')
            return 'Playing ' + album['name'] + (' by ' + plan.artist if plan.artist else '') + '.'
        if plan.operation == "seek":
            state = invoke("spotify_playback", {"action":"get_state"})
            if not (state.get("track") or state.get("item")):
                return "Nothing is playing on Spotify to seek within."
            before = int(state.get("progress_ms") or 0)
            position = max(0, before + plan.seek_delta_ms)
            duration = int(state.get("duration_ms") or (state.get("item") or {}).get("duration_ms") or 0)
            if duration:
                position = min(position, max(0, duration - 1000))
            if position == before:
                return "Already at the requested playback boundary."
            started = time.monotonic()
            invoke("spotify_playback", {"action":"seek", "position_ms":position, **self._device_args(state)})
            track = state.get('track') or state.get('item') or {}
            def changed(after):
                current = after.get('track') or after.get('item') or {}
                same_track = bool(current) and (not track.get('uri') or current.get('uri') == track['uri'])
                elapsed = int((time.monotonic()-started)*1000) if after.get('is_playing') else 0
                observed = int(after.get('progress_ms') or 0)
                # Spotify can report the new position before it advances by
                # the complete request round-trip. Accept that bounded range,
                # while excluding the trajectory of an unchanged player.
                reached = position-250 <= observed <= position+elapsed+250
                changed_position = abs(observed-before-elapsed) > min(750,abs(position-before)/2)
                return same_track and self._same_device(state, after) and reached and changed_position
            self._verify_control(invoke, changed, "seek")
            return f"Moved {'forward' if position >= before else 'back'} {abs(position-before)/1000:g} seconds within the current audio."
        if plan.operation in {"set_volume", "adjust_volume", "set_repeat", "set_shuffle"}:
            state = invoke("spotify_playback", {"action":"get_state"})
            device = state.get('device') or {}
            if not (state.get('track') or state.get('item') or device):
                return "No active Spotify playback device is available. Open Spotify or enable Vellum's player."
            args = self._device_args(state)
            if plan.operation in {"set_volume", "adjust_volume"}:
                before = device.get('volume_percent')
                if device.get('supports_volume') is False or not isinstance(before, int):
                    return "This Spotify device does not expose volume control. Adjust its volume directly."
                target = plan.volume_percent if plan.operation == 'set_volume' else max(0, min(100, before + plan.volume_delta_percent))
                if target == before:
                    return f"Volume is already {target}%."
                invoke('spotify_playback', {'action':'set_volume', 'volume_percent':target, **args})
                self._verify_control(invoke, lambda after:self._same_device(state,after) and (after.get('device') or {}).get('volume_percent')==target, 'volume change')
                return f"Volume changed from {before}% to {target}%."
            if plan.operation == 'set_repeat':
                target = plan.repeat_state
                invoke('spotify_playback', {'action':'set_repeat', 'state':target, **args})
                self._verify_control(invoke, lambda after:self._same_device(state,after) and after.get('repeat')==target, 'repeat change')
                return {'track':'This song is now on repeat.', 'context':'The current collection is now on repeat.', 'off':'Repeat is off.'}[target]
            invoke('spotify_playback', {'action':'set_shuffle', 'shuffle':plan.shuffle, **args})
            self._verify_control(invoke, lambda after:self._same_device(state,after) and after.get('shuffle')==plan.shuffle, 'shuffle change')
            return 'Shuffle is on.' if plan.shuffle else 'Shuffle is off.'
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
            names = track.get("artists") or state.get("artists") or []
            artists = ", ".join(a.get("name", "") if isinstance(a, dict) else str(a) for a in names)
            label = "Currently playing " if state.get("is_playing", True) else "Paused on "
            return label + track.get("name", "an unknown track") + (" by " + artists if artists else "") + "." if track else "Nothing is playing on Spotify."
        action = {"resume":"play"}.get(plan.operation, plan.operation)
        args = {"action":action}
        if plan.operation == "set_shuffle":
            args["shuffle"] = plan.shuffle
        if plan.operation == "set_volume":
            args["volume_percent"] = plan.volume_percent
        invoke("spotify_playback", args)
        return {"pause":"Spotify paused.", "resume":"Spotify resumed.", "next":"Skipped to the next track.",
                "previous":"Previous track requested."}.get(plan.operation, "Spotify playback setting applied.")

    @staticmethod
    def _device_args(state):
        device_id = (state.get('device') or {}).get('id')
        return {'device_id':device_id} if device_id else {}

    @staticmethod
    def _same_device(before, after):
        expected = (before.get('device') or {}).get('id')
        return not expected or (after.get('device') or {}).get('id') == expected

    @staticmethod
    def _verify_control(invoke, matches, label, *, state_action='get_state'):
        deadline = time.monotonic()+4
        try:
            for attempt in range(5):
                if attempt:
                    time.sleep(.2)
                if time.monotonic()>=deadline:
                    break
                if matches(invoke('spotify_playback', {'action':state_action})):
                    return
        except Exception as exc:
            raise ValueError(f"Spotify accepted the {label}, but I could not verify it. I have not repeated the command.") from exc
        raise ValueError(f"Spotify accepted the {label}, but playback did not confirm the change. I have not repeated the command.")

    def _collection_track(self,plan,invoke):
        if plan.track_uri:
            return {'uri':plan.track_uri, 'name':plan.track_query}
        if plan.track_query:
            parts = re.split(r'\s+by\s+', plan.track_query, maxsplit=1, flags=re.I)
            track=self.resolve_song(MusicPlan(operation='play_song',query=parts[0],artist=parts[1] if len(parts)>1 else ''),invoke)
        else:
            state=invoke('spotify_playback',{'action':'get_state'})
            track=state.get('track') or state.get('item') or {}
        if not re.fullmatch(r'spotify:track:[A-Za-z0-9]+',str(track.get('uri') or '')):
            raise ValueError('No current Spotify song is available. Play a song or give its title.')
        return track

    @staticmethod
    def _liked_contains(uri,invoke):
        data=invoke('spotify_library',{'action':'contains','kind':'tracks','uris':[uri]})
        values=data.get('items')
        if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],bool):
            raise ValueError('Spotify did not return a verified Liked Songs membership result.')
        return values[0]

    @staticmethod
    def _playlist_contains(playlist_id,uri,invoke,*,deadline=None):
        for offset in range(0,10000,50):
            if deadline is not None and time.monotonic()>=deadline:
                raise ValueError('Playlist lookup reached its time limit.')
            data=invoke('spotify_playlists',{'action':'tracks','playlist_id':playlist_id,'limit':50,'offset':offset})
            entries=data.get('items')
            if not isinstance(entries,list):
                raise ValueError('Spotify did not expose this playlist’s contents.')
            if any((entry.get('item') or entry.get('track') or {}).get('uri')==uri for entry in entries if isinstance(entry,dict)):
                return True
            if not data.get('next') or not entries:
                return False
        raise ValueError('This playlist is too large to verify completely in one request.')

    def prepare_collection_change(self,plan,invoke):
        action='save' if plan.operation=='save_current' else 'remove'
        playlist=self.resolve_playlist(plan,invoke,saved_only=True) if plan.collection=='playlist' else {}
        track=(self._resolve_collection_song(plan, playlist, invoke) if action=='remove' and plan.track_query and not plan.track_uri
               else self._collection_track(plan,invoke))
        exists=(self._playlist_contains(playlist['id'],track['uri'],invoke,deadline=time.monotonic()+12) if playlist else self._liked_contains(track['uri'],invoke))
        name=playlist.get('name') or 'Liked Songs'
        if exists==(action=='save'):
            return f"{track.get('name') or 'This song'} is {'already in' if exists else 'not in'} {name}."
        return MusicCollectionChangeProposal(action=action,collection=plan.collection,track_uri=track['uri'],
            track_title=track.get('name') or 'This song',playlist_id=playlist.get('id',''),playlist_name=playlist.get('name',''))

    def _resolve_collection_song(self, plan, playlist, invoke):
        """Remove from the requested collection, including typos, without web search."""
        tracks = {}
        deadline = time.monotonic() + 12
        for offset in range(0, 10000, 50):
            if time.monotonic() >= deadline:
                raise ValueError('Song lookup reached its time limit. Give the song’s exact title and artist; nothing was removed.')
            name = 'spotify_playlists' if playlist else 'spotify_library'
            args = {'action':'tracks', 'playlist_id':playlist['id']} if playlist else {'action':'list', 'kind':'tracks'}
            page = invoke(name, {**args, 'limit':50, 'offset':offset})
            if not isinstance(page.get('items'), list):
                raise ValueError('Spotify did not expose this collection’s songs; nothing was removed.')
            for entry in page['items']:
                track = (entry.get('item') or entry.get('track') or {}) if isinstance(entry, dict) else {}
                if re.fullmatch(r'spotify:track:[A-Za-z0-9]+', str(track.get('uri') or '')) and track.get('name'):
                    tracks[track['uri']] = track
            if not page.get('next'):
                break
        else:
            raise ValueError('The collection exceeded the lookup limit; nothing was removed.')
        parts = re.split(r'\s+by\s+', plan.track_query, maxsplit=1, flags=re.I)
        title, artist = parts[0], parts[1] if len(parts)>1 else ''
        wanted = song_key(title)
        candidates = list(tracks.values())
        if artist:
            candidates = [t for t in candidates if any(normalized_name(artist) == normalized_name(a.get('name','')) for a in t.get('artists', []))]
        exact = [t for t in candidates if song_key(t['name']) == wanted]
        if exact:
            matches = exact
        else:
            def score(track):
                # Versions still retain their own URIs. Multiple editions with
                # the same base title need a selection, never an arbitrary write.
                base = re.split(r'\s*[\(\[]|\s+-\s+', track['name'], maxsplit=1)[0]
                return SequenceMatcher(None, wanted, song_key(base)).ratio()
            ranked = sorted(((score(t), t) for t in candidates), key=lambda pair:(-pair[0], pair[1]['uri']))
            matches = [t for similarity, t in ranked if similarity >= .84 and ranked[0][0]-similarity < .08]
        if len(matches) == 1:
            return matches[0]
        choices = [{'title':t['name'], 'artist':', '.join(a.get('name','') for a in t.get('artists', [])), 'uri':t['uri'], 'kind':'track'} for t in matches[:5]]
        if choices:
            raise MusicChoiceRequired('Which saved version? ' + '; '.join(f"{i}. {c['title']} by {c['artist']}" for i,c in enumerate(choices,1)) + '. Reply with its number or artist.', choices)
        raise MusicChoiceRequired('No saved song matched ' + plan.track_query + ' in ' + (playlist.get('name') or 'Liked Songs') + '. Give its title and artist; nothing was removed.', [])

    def change_collection(self,proposal,invoke):
        # The proposal's captured URI survives a song change before confirmation.
        expected=proposal.action=='save'
        if proposal.collection=='liked':
            contains=lambda:self._liked_contains(proposal.track_uri,invoke)
            args={'action':proposal.action,'kind':'tracks','uris':[proposal.track_uri],'confirm':True}
            name='Liked Songs'; tool='spotify_library'
        else:
            contains=lambda:self._playlist_contains(proposal.playlist_id,proposal.track_uri,invoke,deadline=time.monotonic()+12)
            args={'action':'add_items' if expected else 'remove_items','playlist_id':proposal.playlist_id,'uris':[proposal.track_uri],'confirm':True}
            name=proposal.playlist_name; tool='spotify_playlists'
        if contains()==expected:
            return f"{proposal.track_title} is {'already in' if expected else 'not in'} {name}."
        invoke(tool,args)
        try:
            if contains()!=expected:
                raise ValueError('Membership did not change')
        except Exception as exc:
            raise ValueError('Spotify accepted the change, but I could not verify it. Check the collection before retrying; I have not repeated the write.') from exc
        return f"{'Added' if expected else 'Removed'} {proposal.track_title} {'to' if expected else 'from'} {name}."

    def check_collection(self,plan,invoke):
        track=self._collection_track(plan,invoke)
        title=track.get('name') or 'This song'
        if plan.collection=='liked':
            return f"{title} is {'in' if self._liked_contains(track['uri'],invoke) else 'not in'} your Liked Songs."
        if plan.query:
            playlist=self.resolve_playlist(plan,invoke)
            exists=self._playlist_contains(playlist['id'],track['uri'],invoke,deadline=time.monotonic()+12)
            return f"{title} is {'in' if exists else 'not in'} {playlist.get('name') or 'that playlist'}."
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        page=invoke('spotify_playlists',{'action':'list','limit':50,'offset':0})
        playlists=[p for p in page.get('items',[]) if p and p.get('id')]
        deadline=time.monotonic()+12
        def lookup(playlist):
            try:
                return playlist.get('name') or 'Untitled playlist',self._playlist_contains(playlist['id'],track['uri'],invoke,deadline=deadline)
            except ValueError:
                return playlist.get('name') or 'Untitled playlist',None
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures=[pool.submit(copy_context().run,lookup,p) for p in playlists[:20]]
            results=[future.result() for future in futures]
        names=[name for name,found in results if found]
        incomplete=bool(page.get('next') or len(playlists)>20 or any(found is None for _,found in results))
        answer=f"{title} is in: " + ', '.join(names) + '.' if names else f"{title} was not found in the {sum(found is not None for _,found in results)} playlists I could check."
        if incomplete:
            answer+=' Some playlists could not be checked; name one for a complete lookup.'
        return answer
