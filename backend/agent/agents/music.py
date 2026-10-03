"""Provider-neutral music specialist using Vellum's canonical delegation and tools."""

import json
import re
import time
from difflib import SequenceMatcher
from typing import Mapping

from agent.agents.base import SpecialistResponse
from agent.contracts.music import MusicChoiceRequired, MusicIntegration, MusicPlan, MusicPlaylistCreateProposal, match_music_control
from agent.profiles.policy import get_active_profile_policy
from agent.tools.registry import ToolRegistry


PROVIDER_NAMES = {"spotify":"spotify", "apple music":"apple_music", "youtube music":"youtube_music"}


class LocalMusicPlanner:
    def __init__(self, *, model_factory=None, model_resolver=None):
        self.model_factory = model_factory
        self.model_resolver = model_resolver

    @staticmethod
    def _local_model_id() -> str:
        from agent.llm.providers import get_provider_registry

        registry = get_provider_registry()
        registry.refresh_local_models()
        return registry.current_model().id

    def __call__(self, query: str, skill: str) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage
        from agent.llm.routing.models import provider_for_model
        from agent.llm.routing.runtime import get_routed_chat_model

        model_id = (self.model_resolver or self._local_model_id)()
        if provider_for_model(model_id) != "ollama":
            raise ValueError("Select a local model to interpret this music request.")
        model = (self.model_factory or get_routed_chat_model)(model_id)
        output = model.invoke([
            SystemMessage(content=("Translate the user's typed music request into one JSON object matching this schema. "
                "Return JSON only. Interpret the request; do not execute tools or invent a song/playlist name. "
                "Use clarify when the requested music or operation is unclear. Default provider is spotify. "
                "Liked Songs means play_liked, not a playlist name. For create_playlist, query is the new playlist name "
                "Treat liked playlist and liked song playlist as Liked Songs. Podcasts use play_podcast for a show "
                "or play_episode for an episode title, never play_song. Position is a one-based requested track number. "
                "and songs contains the requested titles and artists. Ask for missing details; never invent its songs. "
                "Never infer a mood from listening history or claim playback happened.\n"
                + json.dumps(MusicPlan.model_json_schema()) + "\nSpotify procedure when applicable:\n" + skill[:12000])),
            HumanMessage(content=query[:4000]),
        ], response_format={"type":"json_object"}, request_timeout=40.0, max_tokens=1000)
        content = getattr(output, "content", output)
        if isinstance(content, list):
            content = "".join(str(block.get("text") or "") for block in content if isinstance(block, dict))
        content = str(content or "").strip()
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I)
        return json.loads(content)


class MusicAgent:
    name = "MusicAgent"

    def __init__(self, *, tool_registry: ToolRegistry, integrations: Mapping[str, MusicIntegration] | None = None,
                 planner=None, skill_loader=None):
        if integrations is None:
            from agent.tools.capabilities.spotify_service import SpotifyCapabilityService
            integrations = {"spotify":SpotifyCapabilityService()}
        self.tool_registry = tool_registry
        self.integrations = dict(integrations)
        self.planner = planner or LocalMusicPlanner()
        self.skill_loader = skill_loader or self._load_skill

    @staticmethod
    def _clean(query: str) -> str:
        text = re.sub(r"^\[Vellum UI context:[^\n]*\]\s*", "", str(query or ""))
        return text.split("\n\n[", 1)[0].strip().rstrip(".!?")

    def can_handle(self, query: str) -> bool:
        text = re.sub(r"^(?:please\s+)?(?:(?:can|could|would)\s+(?:you|u)\s+)?(?:please\s+)?", "", self._clean(query), flags=re.I).casefold()
        if re.search(r"\b(?:chess|games?|videos?|youtube(?!\s+music))\b", text):
            return False
        if match_music_control(text):
            return True
        if self._original_version_request(text):
            return True
        if re.fullmatch(r"by\s+a\s+song\s+(?:inside|from)\s+my\s+liked\s+songs\s+playlist", text):
            return True
        if re.match(r"(?:create?|make)\b", text) and re.search(r"\bplaylist\b", text):
            return True
        if re.match(r"(?:please\s+)?(?:play|put on|pause|resume|stop|skip|next|previous|shuffle)\b", text):
            return True
        if re.match(r"from\s+(?:my\s+)?[^?]+playlist\b", text) and re.search(r"\b(?:play|shuffle)\b", text):
            return True
        if re.fullmatch(r"(?:something|soemthing|a\s+(?:random\s+)?song)\s+from\s+(?:my\s+)?(?:liked\s+songs|.+?\s+playlist)", text):
            return True
        if re.search(r"\b(?:what|which)\b.*\b(?:playing|listening)\b", text) or re.match(r"set\s+(?:the\s+)?volume\b", text):
            return True
        return bool(re.search(r"\b(?:on|using|in|through)\s+(?:spotify|apple music|youtube music)$", text)
                    and not re.match(r"(?:what|why|how|explain|search|find posts|research)\b", text))

    @staticmethod
    def _fresh_context(context: dict) -> dict:
        try:
            age = time.time() - float(context.get("at", 0))
        except (ValueError, TypeError):
            return {}
        return context if -5 <= age <= 1800 else {}

    @staticmethod
    def _artist_correction(query: str) -> str | None:
        if re.search(r"\b(?:songs?|tracks?|playlists?|liked)\b", query, re.I):
            return None
        match = re.fullmatch(r"(?:(?:no[, ]+|i meant\s+))?(?:from|by)\s+(.+)", query, re.I)
        return match[1].strip() if match else None

    def can_handle_with_context(self, query: str, context: dict) -> bool:
        context = self._fresh_context(context)
        clean = self._clean(query)
        operation = (context.get("last_plan") or {}).get("operation")
        if context.get("choices") and re.fullmatch(r"(?:yes|yeah|yep|okay|ok)(?:\s+please)?", clean, re.I):
            return True
        if context.get("playlist_request") and re.search(r"\b(?:songs|name|trendy|viral|hits|playlist)\b", clean, re.I):
            return True
        if self._original_version_request(clean) and (operation == "play_song" or context.get("last_song_plan")):
            return True
        if operation == "play_playlist" and re.fullmatch(r"(?:https://open\.spotify\.com/playlist/|spotify:playlist:)[A-Za-z0-9]+(?:\?\S*)?", clean):
            return True
        if operation in {"play_playlist", "play_podcast"} and context.get("choices"):
            return self._source_choice(clean, context) is not None
        return bool((self._artist_correction(clean) or self._artist_choice(clean, context))
                    and (operation == "play_song" or operation == "create_playlist" and context.get("choices")))

    @staticmethod
    def _original_version_request(query: str) -> bool:
        text = re.sub(r"^(?:nah|no|nope)[, ]+", "", query, flags=re.I)
        return bool(re.fullmatch(r"(?:please\s+)?(?:play\s+)?(?:that\s+(?:song|track)\s+(?:by|nby)\s+)?(?:the\s+)?original(?:\s+(?:song|track|version|artist))?", text, re.I))

    @staticmethod
    def _source_choice(text: str, context: dict) -> dict | None:
        choices = context.get("choices") or []
        if len(choices) == 1 and re.fullmatch(r"(?:yes|yeah|yep|okay|ok)(?:\s+please)?", text, re.I):
            return choices[0]
        ordinal = re.fullmatch(r"(?:the\s+)?(\d+)(?:st|nd|rd|th)?(?:\s+one)?", text, re.I)
        if ordinal and 0 < int(ordinal[1]) <= len(choices):
            return choices[int(ordinal[1])-1]
        text = re.sub(r"^(?:from|by)\s+", "", text, flags=re.I).casefold()
        ranked = sorted(((max(SequenceMatcher(None, text, c.get("title", "").casefold()).ratio(),
                              1.0 if text and text in c.get("title", "").casefold() else 0), c)
                         for c in choices), key=lambda pair:pair[0], reverse=True)
        if ranked and ranked[0][0] >= .65 and (len(ranked)==1 or ranked[0][0]-ranked[1][0] >= .15):
            return ranked[0][1]
        return None

    @staticmethod
    def _artist_choice(artist: str, context: dict) -> dict | None:
        choices = context.get("choices") or []
        ordinal = re.fullmatch(r"(?:the\s+)?(\d+)(?:st|nd|rd|th)?(?:\s+one)?", artist, re.I)
        if ordinal and 0 < int(ordinal[1]) <= len(choices):
            return choices[int(ordinal[1])-1]
        if len(choices) == 1 and re.fullmatch(r"(?:yes|yeah|yep|okay|ok)(?:\s+please)?", artist, re.I):
            return choices[0]
        def score(choice):
            names = choice.get("artists") or choice.get("artist", "").split(",")
            names = [choice.get("artist", ""), *names]
            return max((SequenceMatcher(None, artist.casefold(), name.strip().casefold()).ratio() for name in names), default=0)
        ranked = sorted(((score(c), c)
                         for c in context.get("choices", [])), key=lambda pair:pair[0], reverse=True)
        if ranked and ranked[0][0] >= .55 and (len(ranked)==1 or ranked[0][0]-ranked[1][0] >= .15):
            return ranked[0][1]
        return None

    @staticmethod
    def thread_context(response: SpecialistResponse, previous: dict) -> dict:
        previous = MusicAgent._fresh_context(previous)
        plan = response.structured_payload.get("music_plan")
        if plan is None:
            return MusicAgent._fresh_context(previous)
        links = list(MusicAgent._fresh_context(previous).get("playlist_links") or [])
        if plan.get("operation") == "play_playlist" and plan.get("source_uri") and not re.match(r"(?:spotify:|https://)", plan.get("query", "")):
            links = [link for link in links if (link.get("provider"),link.get("query")) != (plan["provider"],plan["query"])]
            links.append({"provider":plan["provider"], "query":plan["query"], "source_uri":plan["source_uri"]})
        last_song = previous.get("last_song_plan") or (previous.get("last_plan") if (previous.get("last_plan") or {}).get("operation") == "play_song" else None)
        if plan.get("operation") == "play_song" and response.status == "answered":
            last_song = plan
        return {"last_plan":plan, "last_song_plan":last_song, "playlist_request":response.structured_payload.get("playlist_request", False), "playlist_links":links[-5:], "choices":response.structured_payload.get("choices", [])[:5],
                "song_index":response.structured_payload.get("song_index"), "at":time.time()}

    @staticmethod
    def _load_skill(name: str) -> str:
        from agent.skills.runtime import get_skill_registry
        policy = get_active_profile_policy()
        if policy is not None and name not in policy.allowed_skills:
            raise ValueError("This music skill is not allowed by the active profile.")
        return get_skill_registry().view(name).body

    @staticmethod
    def _fast_plan(query: str) -> MusicPlan | None:
        text = re.sub(r"^(?:please\s+)?(?:(?:can|could|would)\s+(?:you|u)\s+)?(?:please\s+)?", "", query, flags=re.I)
        provider = "spotify"
        suffix = re.search(r"\s+(?:on|using|in|through)\s+(spotify|apple music|youtube music)$", text, re.I)
        explicit_provider = suffix is not None
        if suffix:
            provider = PROVIDER_NAMES[suffix[1].casefold()]
            text = text[:suffix.start()].strip()
        seek = re.fullmatch(r"(?:skip(?:\s+(?:ahead|forward))?|forward|go\s+forward|rewind|go\s+back|back)\s+(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m)", text, re.I)
        if seek:
            delta = int(seek[1]) * (60000 if seek[2].casefold().startswith('m') else 1000)
            if re.match(r"(?:rewind|go\s+back|back)\b", text, re.I):
                delta = -delta
            return MusicPlan(operation="seek", provider=provider, seek_delta_ms=delta)
        if re.search(r"\b(?:what|which)\b.*\b(?:playing|listening)\b", text, re.I):
            return MusicPlan(operation="current", provider=provider)
        if re.match(r"(?:create?|make|come\s+up)\b", text, re.I) and re.search(r"\b(?:trendy|trending|viral|reel)\b", text, re.I):
            return MusicPlan(operation="curate_playlist", provider=provider, query=text)
        create = re.fullmatch(r"(?:create|make)(?:\s+me)?\s+(?:a\s+)?(?:new\s+)?playlist\s+(?:called|named)\s+(.+?)\s+(?:with|containing)\s+(.+)", text, re.I)
        if create:
            songs = []
            for item in re.split(r"\s*,\s*|\s+and\s+", create[2]):
                parts = re.split(r"\s+by\s+", item, maxsplit=1, flags=re.I)
                songs.append({"title":parts[0].strip(' \"\u201c\u201d'), "artist":parts[1].strip() if len(parts)>1 else ""})
            return MusicPlan(operation="create_playlist", provider=provider, query=create[1].strip(' \"\u201c\u201d'), songs=songs)
        if re.fullmatch(r"(?:create?|make)(?:\s+me)?\s+(?:a\s+)?(?:new\s+)?playlist", text, re.I):
            return MusicPlan(operation="clarify", provider=provider)
        if text.casefold() == "play":
            return MusicPlan(operation="resume", provider=provider)
        if re.fullmatch(r"what(?:'s| is|\s+(?:song|track)\s+is)\s+(?:currently\s+)?playing", text, re.I):
            return MusicPlan(operation="current", provider=provider)
        volume = re.fullmatch(r"set\s+(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*(?:%|percent)?", text, re.I)
        if volume:
            return MusicPlan(operation="set_volume", provider=provider, volume_percent=int(volume[1]))
        control = match_music_control(text)
        if control:
            return MusicPlan(operation=control, provider=provider)
        # Classify media and collections before the generic 'play TITLE' path.
        podcast = re.fullmatch(r"(?:play|put on)\s+(?:a\s+|an\s+|the\s+)?(?:latest\s+)?(podcasts?|podacts?|podcats?|episodes?)(?:\s+(from|by|of|on))?\s+(.+)", text, re.I)
        if podcast:
            operation = "play_episode" if podcast[1].casefold().startswith("episode") and not podcast[2] else "play_podcast"
            return MusicPlan(operation=operation, provider=provider, query=podcast[3].strip(' \"\u201c\u201d'))
        if re.search(r"\b(?:podcasts?|podacts?|podcats?|episodes?)\b", text, re.I):
            return None
        link = re.fullmatch(r"(?:play\s+)?((?:https://open\.spotify\.com/playlist/|spotify:playlist:)[A-Za-z0-9]+(?:\?\S*)?)", text, re.I)
        if link:
            return MusicPlan(operation="play_playlist", provider=provider, query=link[1])
        position_match = re.search(r"\b(?:the\s+)?(first|second|third|\d+(?:st|nd|rd|th)?)\s+(?:song|track)\b", text, re.I)
        position = None
        if position_match:
            label = position_match[1].casefold()
            position = {"first":1,"second":2,"third":3}.get(label)
            if position is None:
                position = int(re.match(r"\d+", label)[0])
        shuffle = True if re.search(r"\b(?:shuffle|something|soemthing|random)\b", text, re.I) else False if position else None
        liked = re.search(r"\b(?:liked\s+songs?(?:\s+playlist)?|liked\s+playlist)(?:\s+(?:on\s+shuffle|in\s+shuffle\s+order))?\s*$", text, re.I)
        if liked:
            return MusicPlan(operation="play_liked", provider=provider, shuffle=shuffle if shuffle is not None else True, position=position)
        if re.fullmatch(r"(?:(?:play|shuffle|put on)\s+)?(?:(?:something|soemthing|a\s+(?:random\s+)?song)\s+from\s+)?(?:my\s+)?liked\s+songs", text, re.I):
            return MusicPlan(operation="play_liked", provider=provider, shuffle=True)
        if "playlist" in text.casefold():
            # Prefer the source phrase so 'play something from my Kannada' is
            # not mistaken for the playlist's name.
            playlist = re.search(r"\bfrom\s+(?:my\s+|the\s+)?(.+?)\s+playlist\b", text, re.I)
            if playlist is None:
                playlist = re.fullmatch(r"(?:play|shuffle)\s+(?:my\s+|the\s+)?(.+?)\s+playlist(?:\s+(?:on\s+shuffle|in\s+shuffle\s+order))?", text, re.I)
            if playlist:
                name = re.sub(r"^(?:saved\s+)", "", playlist[1], flags=re.I).strip(' \"\u201c\u201d')
                return MusicPlan(operation="play_playlist", provider=provider, query=name, shuffle=shuffle, position=position)
            return None
        mix = re.fullmatch(r"(?:play|shuffle)\s+(?:something\s+from\s+)?(?:my\s+|the\s+)?(.+?\s+mix(?:\s+\d+)?)", text, re.I)
        if mix:
            return MusicPlan(operation="play_playlist", provider=provider, query=mix[1], shuffle=shuffle)
        song = re.fullmatch(r"(?:play|put on)\s+(?:the\s+song\s+)?(.+)", text, re.I)
        if song or (explicit_provider and " by " in text.casefold()):
            title = song[1] if song else text
            emoji_name = re.sub(r"^my\s+", "", title, flags=re.I).strip(' \"\u201c\u201d')
            if emoji_name and not any(c.isalnum() for c in emoji_name):
                return MusicPlan(operation="play_playlist", provider=provider, query=emoji_name)
            artist = ""
            parts = re.split(r"\s+by\s+", title, maxsplit=1, flags=re.I)
            if len(parts) == 2:
                title, artist = parts
            return MusicPlan(operation="play_song", provider=provider, query=title.strip(' \"\u201c\u201d'), artist=artist.strip())
        return None

    def answer(self, query: str) -> SpecialistResponse:
        return self.answer_with_context(query, {})

    def answer_with_context(self, query: str, context: dict) -> SpecialistResponse:
        clean = self._clean(query)
        events = []
        plan = None
        def invoke(name: str, payload: dict) -> dict:
            result = self.tool_registry.invoke(name, payload, agent_name=self.name)
            if result.get("ok") is not True:
                error = result.get("error") or {}
                raise ValueError(str(error.get("message") or "The music service could not complete this request."))
            events.append({"name":name, "status":"completed"})
            return result.get("data") or {}
        try:
            context = self._fresh_context(context)
            if len(context.get("choices") or []) > 1 and re.fullmatch(r"(?:yes|yeah|yep|okay|ok)(?:\s+please)?", clean, re.I):
                return SpecialistResponse(agent=self.name, status="needs_fetch",
                    summary="Choose one: " + "; ".join(f"{i}. {c.get('title', '')} by {c.get('artist', '')}" for i,c in enumerate(context['choices'],1)) + ". Reply with its number or artist.",
                    structured_payload={"music_plan":context.get("last_plan"), "choices":context["choices"]})
            artist = self._artist_correction(clean) or (clean if self._artist_choice(clean, context) else None)
            last_plan = context.get("last_plan") or {}
            source_choice = self._source_choice(clean, context) if last_plan.get("operation") in {"play_playlist", "play_podcast"} else None
            fresh_plan = self._fast_plan(clean)
            original = self._original_version_request(clean)
            if fresh_plan is not None and fresh_plan.operation == "play_liked":
                plan = fresh_plan
            elif original and (last_plan.get("operation") == "play_song" or context.get("last_song_plan")):
                song = context.get("last_song_plan") or last_plan
                plan = MusicPlan.model_validate({**song, "artist":"", "version":"original"})
            elif original:
                return SpecialistResponse(agent=self.name, status="needs_fetch", summary="Which song do you mean? Send its title or artist so I can find the original version.")
            elif source_choice:
                plan = MusicPlan.model_validate({**last_plan, "query":source_choice["title"], "source_uri":source_choice["uri"]})
            elif last_plan.get("operation") == "play_playlist" and re.fullmatch(r"(?:https://open\.spotify\.com/playlist/|spotify:playlist:)[A-Za-z0-9]+(?:\?\S*)?", clean):
                playlist_id = re.search(r"(?:playlist/|playlist:)([A-Za-z0-9]+)", clean)[1]
                plan = MusicPlan.model_validate({**last_plan, "source_uri":"spotify:playlist:" + playlist_id})
            elif artist and last_plan.get("operation") in {"play_song", "create_playlist"}:
                # Resolve a spelling correction against this turn's explicit
                # choices, never against global listening history.
                candidate = self._artist_choice(artist, context)
                if last_plan["operation"] == "create_playlist":
                    songs = [dict(song) for song in last_plan["songs"]]
                    index = context.get("song_index")
                    if not isinstance(index, int) or not 0 <= index < len(songs):
                        raise ValueError("Repeat the playlist request with song titles and artists.")
                    songs[index]["artist"] = candidate["artist"] if candidate else artist
                    if candidate:
                        songs[index]["title"] = candidate["title"]
                    plan = MusicPlan.model_validate({**last_plan, "songs":songs})
                else:
                    plan = MusicPlan.model_validate({**last_plan, "query":candidate["title"] if candidate else last_plan["query"],
                                                    "artist":candidate["artist"] if candidate else artist})
            else:
                plan = self._fast_plan(clean)
            if plan is None:
                # No credentials, listening history, or unrelated chat enters the model.
                plan = MusicPlan.model_validate(self.planner(clean, self.skill_loader("spotify")))
            if plan.operation == "play_playlist" and not plan.source_uri:
                key = " ".join(plan.query.casefold().split())
                linked = next((link for link in context.get("playlist_links", []) if link.get("provider") == plan.provider and
                               " ".join(link.get("query", "").casefold().split()) == key), None)
                if linked:
                    plan = plan.model_copy(update={"source_uri":linked["source_uri"]})
            if re.search(r"\b(?:podcasts?|podacts?|podcats?|episodes?)\b", clean, re.I) and plan.operation not in {"play_podcast", "play_episode", "clarify"}:
                return SpecialistResponse(agent=self.name, status="needs_fetch", summary="Which podcast show or episode would you like me to play?")
            if plan.operation == "clarify":
                creating = bool(context.get("playlist_request") or re.search(r"\b(?:create?|make)\b.*\bplaylist\b", clean, re.I))
                message = "What songs or style should the playlist contain? I can suggest a name." if creating else "Which song or playlist would you like me to play?"
                return SpecialistResponse(agent=self.name, status="needs_fetch", summary=message,
                    structured_payload={"music_plan":plan.model_dump(), "playlist_request":creating})
            integration = self.integrations.get(plan.provider)
            if integration is None:
                return SpecialistResponse(agent=self.name, status="needs_fetch", summary=f"{plan.provider.replace('_', ' ').title()} is not connected to Vellum yet.")
            self.skill_loader(integration.skill_id)
            if plan.operation in {"create_playlist", "curate_playlist"}:
                prepare = getattr(integration, "curate_playlist" if plan.operation == "curate_playlist" else "prepare_playlist", None)
                if not callable(prepare):
                    return SpecialistResponse(agent=self.name, status="needs_fetch", summary="This music integration does not support playlist creation yet.")
                proposal = prepare(plan, invoke)
                preview = "Create private playlist " + proposal.name + " with these songs:\n" + "\n".join(
                    "- " + song.title + (" by " + song.artist if song.artist else "") for song in proposal.songs)
                return SpecialistResponse(agent=self.name, status="needs_fetch", summary=preview + "\nConfirm to create it.",
                    action_request={"action":"music.create_playlist", "payload":proposal.model_dump(), "preview":preview},
                    activity_events=events, structured_payload={"music_plan":plan.model_dump()})
            summary = integration.execute(plan, invoke)
            return SpecialistResponse(agent=self.name, status="answered", summary=summary, activity_events=events,
                                      structured_payload={"music_plan":plan.model_dump()},
                                      analysis="Used " + ", ".join(event["name"] for event in events), confidence=1.0)
        except MusicChoiceRequired as exc:
            return SpecialistResponse(agent=self.name, status="needs_fetch", summary=str(exc), activity_events=events,
                                      structured_payload={"music_plan":plan.model_dump(), "choices":exc.choices, "song_index":exc.song_index})
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "MusicAgent could not complete that request."
            if "no available spotify device" in message.casefold():
                message = "Spotify has no active playback device. Open Spotify or activate Vellum's player, then try again."
            return SpecialistResponse(agent=self.name, status="error", summary=message[:300], activity_events=events)

    def execute_action_request(self, action_request: dict) -> SpecialistResponse:
        if action_request.get("action") != "music.create_playlist":
            return SpecialistResponse(agent=self.name, status="blocked", summary="MusicAgent cannot execute that pending action.")
        events = []
        def invoke(name, payload):
            result = self.tool_registry.invoke(name, payload, agent_name=self.name)
            if result.get("ok") is not True:
                raise ValueError(str((result.get("error") or {}).get("message") or "Spotify did not confirm the change."))
            events.append({"name":name, "status":"completed"})
            return result.get("data") or {}
        try:
            proposal = MusicPlaylistCreateProposal.model_validate(action_request.get("payload") or {})
            integration = self.integrations.get(proposal.provider)
            if integration is None or not callable(getattr(integration, "create_playlist", None)):
                raise ValueError("This music integration cannot create playlists.")
            self.skill_loader(integration.skill_id)
            message = integration.create_playlist(proposal, invoke)
            return SpecialistResponse(agent=self.name, status="answered", summary=message, activity_events=events)
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else "MusicAgent could not confirm playlist creation. Check Spotify before retrying."
            return SpecialistResponse(agent=self.name, status="error", summary=message[:500], activity_events=events)
