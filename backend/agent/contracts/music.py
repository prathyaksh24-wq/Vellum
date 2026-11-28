"""Provider-neutral, validated music intent used by the shared specialist runtime."""

import re
from typing import Callable, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator


def match_music_control(text: str) -> str | None:
    """Recognize whole control phrases before interpreting any song title."""
    next_track = r"(?:(?:play|go\s+to|skip\s+to)\s+)?(?:the\s+)?next(?:\s+(?:song|track))?|skip(?:\s+(?:this|(?:(?:the\s+)?current)|the))?(?:\s+(?:song|track))?"
    previous = r"(?:(?:play|go\s+(?:back\s+)?to|back\s+to)\s+)?(?:the\s+)?previous(?:\s+(?:song|track))?"
    if re.fullmatch(next_track, text, re.I):
        return "next"
    if re.fullmatch(previous, text, re.I):
        return "previous"
    control = re.fullmatch(r"(pause|resume|stop)(?:\s+(?:the\s+)?(?:song|track|music|spotify))?", text, re.I)
    if control:
        return "pause" if control[1].casefold() == "stop" else control[1].casefold()
    typo = re.fullmatch(r'([a-z]{4,7})(?:\s+(?:the\s+)?(?:song|track|music|spotify))?',text,re.I)
    if typo:
        word=typo[1].casefold()
        for command in ('pause','resume'):
            if len(word)==len(command):
                differences=[i for i,(a,b) in enumerate(zip(word,command)) if a!=b]
                if len(differences)==2 and differences[1]==differences[0]+1 and word[differences[0]]==command[differences[1]] and word[differences[1]]==command[differences[0]]:
                    return command
                if len(differences)==1 and word[:3]==command[:3]:
                    return command
            elif word[:3]==command[:3] and abs(len(word)-len(command))==1:
                longer,shorter=(word,command) if len(word)>len(command) else (command,word)
                if any(longer[:i]+longer[i+1:]==shorter for i in range(len(longer))):
                    return command
    return None


class PlayerCommand(BaseModel):
    """A whole-sentence player instruction or question about live playback.

    Provider-neutral: the App Action layer picks Local Music or Spotify from
    what is actually playing, so the same words work for either player.
    """
    model_config = ConfigDict(extra='forbid')
    op: Literal['pause', 'resume', 'next', 'previous', 'seek_by', 'restart', 'volume_set', 'volume_by',
                'mute', 'unmute', 'like', 'unlike', 'shuffle', 'repeat', 'info']
    seconds: int = Field(default=0, ge=-86400, le=86400)
    volume: int = Field(default=0, ge=-100, le=100)
    enabled: bool = False
    repeat: Literal['off', 'one', 'all'] = 'off'
    detail: Literal['song', 'artist', 'album', 'next', 'queue', 'playlist'] = 'song'
    provider: Literal['', 'spotify', 'local'] = ''


_PLAYER_POLITE = re.compile(r"^(?:(?:hey|ok|okay|so|um|uh)[, ]+)*(?:please\s+)?(?:(?:can|could|would|will)\s+(?:you|u)\s+)?(?:please\s+)?(?:(?:just|quickly)\s+)?")
_PROVIDER_ENDINGS = (('local', 'music', 'player'), ('local', 'music', 'library'), ('local', 'music'),
                     ('local', 'player'), ('local', 'library'), ('local',), ('spotify',))
_TRAILING_FILLERS = (('for', 'me'), ('please',), ('pls',), ('plz',), ('now',))


def split_player_provider(text: str) -> tuple[str, str]:
    """('play x', 'spotify') from 'play x on spotify'.

    Word comparisons, not a trailing regex search, so the time is linear.
    """
    words = text.split()
    for ending in _PROVIDER_ENDINGS:
        size = len(ending)
        if len(words) <= size or tuple(words[-size:]) != ending:
            continue
        rest = words[:-size]
        if rest and rest[-1] in {'my', 'the'}:
            rest = rest[:-1]
        if rest and rest[-1] in {'on', 'in', 'from', 'for', 'using'}:
            rest = rest[:-1]
        elif ending != ('spotify',):
            # "local" alone only names the player after on/in/from/for/using.
            continue
        if rest:
            return ' '.join(rest), 'spotify' if ending == ('spotify',) else 'local'
    return text, ''


def strip_trailing_filler(text: str) -> str:
    words = text.split()
    for filler in _TRAILING_FILLERS:
        size = len(filler)
        if len(words) > size and tuple(words[-size:]) == filler:
            return ' '.join(words[:-size])
    return text
_UNIT = r"(s|secs?|seconds?|sec|sens|m|mins?|minutes?)"
_IT = r"(?:(?:this|the|current|this\s+current|the\s+current|that)\s+)?(?:song|track|tune|music|one)"
_CURRENT = r"(?:it|this|that|" + _IT + r")"


def _player_seconds(amount: str, unit: str | None) -> int:
    return int(amount) * (60 if (unit or '').casefold().startswith('m') else 1)


# Words that make up player instructions. Typos of these are corrected
# before matching; titles and other words are never changed.
MUSIC_VOCABULARY = frozenset("""
what which who whats song songs track tracks tune playing play played playlist playlists album albums
artist artists singer sings name current currently next queue queued skip pause resume continue stop
volume increase decrease raise lower louder quieter mute unmute like unlike liked likes favorite
shuffle repeat loop seconds second secs minutes minute forward back rewind restart replay beginning
something anything music local player library spotify listening listen called title coming after
this from previous turn set please
""".split())
_SHORT_TYPOS = {'waht': 'what', 'wat': 'what', 'wht': 'what', 'whta': 'what', 'teh': 'the', 'sng': 'song',
                'skp': 'skip', 'nxt': 'next', 'vol': 'volume', 'plz': 'please', 'pls': 'please', 'thsi': 'this',
                'tis': 'this', 'ths': 'this', 'si': 'is', 'sogn': 'song', 'sonf': 'song', 'paly': 'play', 'lik': 'like', 'lke': 'like', 'lyk': 'like', 'sog': 'song', 'nme': 'name', 'whc': 'which'}


_KEEP_WORDS = frozenset('same some sang sung sing singing love loved down live life lame shop ship slip skin cause clay pray plan list link time take make lyric lyrics'.split())


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Damerau-Levenshtein (adjacent swaps count once), stopping above limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous2, previous = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            if previous2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                current[j] = min(current[j], previous2[j - 2] + 1)
        if min(current) > limit:
            return limit + 1
        previous2, previous = previous, current
    return previous[-1]


def fix_music_word(word: str) -> str:
    """The command word a misspelling was meant to be, or the word unchanged."""
    if word in MUSIC_VOCABULARY or word in _KEEP_WORDS or not word.isalpha():
        return word
    if word in _SHORT_TYPOS:
        return _SHORT_TYPOS[word]
    if len(word) < 4:
        return word
    limit = 1 if len(word) < 7 else 2
    best, best_distance = word, limit + 1
    for candidate in MUSIC_VOCABULARY:
        distance = _edit_distance(word, candidate, limit)
        if distance < best_distance:
            best, best_distance = candidate, distance
    return best if best_distance <= limit else word


def fix_music_spelling(text: str) -> str:
    words = [fix_music_word(word) for word in text.split(' ')]
    fixed = ' '.join(words)
    # Context-dependent slips: "name if the song", "the sing".
    fixed = re.sub(r"\bname\s+if\b", 'name of', fixed)
    return re.sub(r"\b(the|this|current|that)\s+sing\b", r'\1 song', fixed)


def match_player_request(text: str) -> PlayerCommand | None:
    """Match an entire short instruction; anything longer belongs to the model."""
    raw = ' '.join(str(text or '').split())
    if not raw or len(raw) > 120:
        return None
    t = raw.casefold().replace('’', "'").rstrip(' .!?>')
    t = fix_music_spelling(t)
    t = _PLAYER_POLITE.sub('', t).strip()
    t = strip_trailing_filler(t)
    t, provider = split_player_provider(t)
    if not t:
        return None
    command = _match_player_text(t)
    return command.model_copy(update={'provider': provider}) if command else None


def _match_player_text(t: str) -> PlayerCommand | None:
    control = match_music_control(t)
    if control:
        return PlayerCommand(op=control)
    if t in {'play', 'continue', 'unpause', 'keep playing', 'resume playing', 'resume playback', 'continue playing'}:
        return PlayerCommand(op='resume')
    if t in {'stop music', 'stop playing', 'stop playback', 'pause playback', 'pause it', 'pause this'}:
        return PlayerCommand(op='pause')

    # Seek by an interval, e.g. "skip 30 secs", "go back 10 seconds", "rewind 15".
    forward = re.fullmatch(r"(?:skip|fast\s*forward|forward|go\s+forward|move\s+forward|jump(?:\s+(?:ahead|forward))?|seek(?:\s+forward)?|skip\s+(?:ahead|forward)|go\s+ahead)\s+(?:by\s+)?(\d{1,4})\s*" + _UNIT + r"(?:\s+(?:ahead|forward))?", t)
    if forward:
        return PlayerCommand(op='seek_by', seconds=_player_seconds(forward[1], forward[2]))
    backward = re.fullmatch(r"(?:rewind|go\s+back(?:wards?)?|move\s+back|jump\s+back|skip\s+back(?:wards?)?|seek\s+back(?:wards?)?|back)\s+(?:by\s+)?(\d{1,4})\s*" + _UNIT + r"(?:\s+back)?", t)
    if backward:
        return PlayerCommand(op='seek_by', seconds=-_player_seconds(backward[1], backward[2]))
    if re.fullmatch(r"(?:restart|replay)(?:\s+" + _CURRENT + r")?|(?:start|play)\s+" + _CURRENT + r"\s+(?:over|again|from\s+the\s+(?:beginning|start))|(?:go\s+back\s+to|back\s+to|play\s+from)\s+the\s+(?:beginning|start)(?:\s+of\s+" + _CURRENT + r")?|start\s+over", t):
        return PlayerCommand(op='restart')

    # Volume.
    if re.fullmatch(r"(?:mute|silence)(?:\s+(?:it|the\s+(?:music|song|audio|volume|sound)|music|audio|sound|" + _IT + r"))?", t):
        return PlayerCommand(op='mute')
    if re.fullmatch(r"unmute(?:\s+(?:it|the\s+(?:music|song|audio|volume|sound)|music|audio|sound|" + _IT + r"))?", t):
        return PlayerCommand(op='unmute')
    vol = r"(?:the\s+)?(?:volume|sound)"
    absolute = re.fullmatch(r"(?:(?:set|change|put|make|turn)\s+(?:" + vol + r"|it)\s+(?:to|at)\s+|" + vol + r"\s+(?:to\s+)?|(?:increase|raise|turn\s+up|reduce|decrease|lower|turn\s+down)\s+" + vol + r"\s+to\s+)(\d{1,3})\s*(?:%|percent)?", t)
    if absolute and int(absolute[1]) <= 100:
        return PlayerCommand(op='volume_set', volume=int(absolute[1]))
    if re.fullmatch(r"(?:(?:set|put|turn)\s+" + vol + r"\s+(?:to\s+)?(?:max(?:imum)?|full)|max(?:imum)?\s+volume|full\s+volume|" + vol + r"\s+(?:to\s+)?max(?:imum)?|turn\s+it\s+all\s+the\s+way\s+up)", t):
        return PlayerCommand(op='volume_set', volume=100)
    step = re.fullmatch(r"(increase|raise|turn\s+up|up|boost|reduce|decrease|lower|turn\s+down|down|drop)\s+" + vol + r"(?:\s+by\s+(\d{1,3})\s*(?:%|percent)?)?|(?:(?:turn|put|bring)\s+)?" + vol + r"\s+(up|down)(?:\s+by\s+(\d{1,3})\s*(?:%|percent)?)?|(louder|quieter|softer|turn\s+it\s+up|turn\s+it\s+down|make\s+it\s+louder|make\s+it\s+quieter|a\s+(?:bit|little)\s+(?:louder|quieter))", t)
    if step:
        word = (step[1] or step[3] or step[5] or '').casefold()
        amount = int(step[2] or step[4] or 10)
        if amount > 100:
            return None
        down = any(key in word for key in ('reduce', 'decrease', 'lower', 'down', 'drop', 'quieter', 'softer'))
        return PlayerCommand(op='volume_by', volume=-amount if down else amount)

    # Likes.
    liked = r"(?:my\s+)?(?:liked\s+songs|likes|favou?rites)"
    if re.fullmatch(r"(?:like|love|heart|favou?rite)(?:\s+" + _CURRENT + r")?|save\s+" + _CURRENT + r"|(?:add|save)\s+" + _CURRENT + r"\s+to\s+" + liked, t):
        return PlayerCommand(op='like')
    if re.fullmatch(r"(?:unlike|un-like|unheart|unfavou?rite|unsave|dislike|remove\s+(?:the\s+)?like\s+(?:from|on)\s+" + _CURRENT + r")(?:\s+" + _CURRENT + r")?|remove\s+" + _CURRENT + r"\s+from\s+" + liked, t):
        return PlayerCommand(op='unlike')

    # Shuffle and repeat.
    shuffle = re.fullmatch(r"(?:turn\s+)?shuffle\s+(on|off)|(?:turn|switch)\s+(on|off)\s+shuffle|(enable|disable)\s+shuffle|(shuffle)(?:\s+(?:it|the\s+(?:queue|playlist|music)))?|(stop|don't)\s+shuffl(?:e|ing)", t)
    if shuffle:
        on = (shuffle[1] or shuffle[2] or shuffle[3] or shuffle[4] or '').casefold() in {'on', 'enable', 'shuffle'}
        return PlayerCommand(op='shuffle', enabled=on)
    if re.fullmatch(r"(?:repeat|loop)\s+" + _CURRENT + r"|(?:put|set)\s+" + _CURRENT + r"\s+on\s+(?:repeat|loop)|(?:turn\s+)?(?:repeat|loop)\s+(?:one|song|track)", t):
        return PlayerCommand(op='repeat', repeat='one')
    repeat = re.fullmatch(r"(?:turn\s+)?(?:repeat|loop)(?:\s+mode)?\s+(on|off|all)|(?:turn|switch)\s+(on|off)\s+(?:repeat|loop)|(?:repeat|loop)\s+(?:the\s+)?(?:playlist|queue|album)|(stop|don't)\s+(?:repeating|looping)", t)
    if repeat:
        state = (repeat[1] or repeat[2] or '').casefold()
        return PlayerCommand(op='repeat', repeat='off' if state == 'off' or repeat[3] else 'all')

    detail = _match_player_question(t) or _loose_player_question(t)
    return PlayerCommand(op='info', detail=detail) if detail else None


def _loose_player_question(t: str) -> str | None:
    """Short questions about the live song phrased in any order, e.g.
    "from which playlist is the song playing from"."""
    if len(t.split()) > 12:
        return None
    if not re.match(r"(?:what|which|who|whose|from\s+(?:which|what)|in\s+(?:which|what)|on\s+(?:which|what)|tell\s+me|name)\b", t):
        return None
    if not re.search(r"\b(?:this|current|currently|playing|now|it|that)\b", t):
        return None
    # Opinions, meaning, or changes are conversations, not player questions.
    if re.search(r"\b(?:about|mean|meaning|lyrics?|review|why|how|good|better|best|should|recommend|suggest|add|put|save|move|create|make|similar|like|love|do\s+i\s+have|all)\b", t):
        return None
    if re.search(r"\bplaylists?\b", t):
        return 'playlist'
    if re.search(r"\balbums?\b", t):
        return 'album'
    if re.search(r"\b(?:artist|singer|sings?|sang|singing|band|by)\b", t) or (t.startswith(('who', 'whose')) and re.search(r"(?:song|track|tune|music|playing)", t)):
        return 'artist'
    if re.search(r"\bqueue\b", t):
        return 'queue'
    if re.search(r"\b(?:next|after\s+(?:this|it|that))\b", t):
        return 'next'
    if re.search(r"\b(?:song|track|tune|music)\b", t) and re.search(r"\b(?:name|called|title|what|which|playing)\b", t):
        return 'song'
    return None


def _match_player_question(t: str) -> str | None:
    t = re.sub(r"^(?:whats|wats|wat\s+is|what's|whta\s+is|whta's)(?=\s|$)", 'what is', t)
    t = re.sub(r"^(?:tell|show)\s+me\s+", 'what is ', t)
    t = re.sub(r"^(?:do\s+you\s+know|can\s+you\s+tell\s+me)\s+", '', t)
    song = r"(?:song|track|music|tune|thing)"
    live = r"(?:\s+(?:that(?:\s+is|'s)?|which\s+is|is|currently|now|right\s+now|being|playing|on|in\s+the\s+background))*"
    if re.fullmatch(r"(?:who|which\s+artist)\s+(?:is\s+)?(?:sings|sang|is\s+singing|made|performs|sung|sing|singing|this\s+by|is\s+this\s+by|is\s+the\s+(?:artist|singer)|the\s+(?:artist|singer)\s+is)(?:\s+(?:of\s+)?" + _CURRENT + r")?(?:\s+by)?|(?:what|which)\s+is\s+(?:the\s+)?(?:artist|singer|band)(?:'s)?(?:\s+name)?(?:\s+(?:of|for|on)\s+" + _CURRENT + r")?|(?:artist|singer)\s+name|who\s+is\s+(?:playing|singing)(?:\s+" + _CURRENT + r")?", t):
        return 'artist'
    if re.fullmatch(r"(?:what|which)\s+(?:is\s+)?(?:the\s+)?album(?:\s+name)?(?:\s+(?:is\s+)?(?:" + _CURRENT + r"|it)\s+(?:from|on|in))?(?:\s+(?:of|for)\s+" + _CURRENT + r")?|(?:what|which)\s+album\s+(?:is\s+)?(?:" + _CURRENT + r"|it)(?:\s+(?:from|on|in))?|album\s+name|(?:what|which)\s+is\s+(?:the\s+)?name\s+of\s+(?:the|this)\s+album", t):
        return 'album'
    if re.fullmatch(r"(?:what|which)\s+(?:is\s+)?(?:the\s+)?playlist(?:\s+name)?(?:\s+(?:is\s+)?(?:" + _CURRENT + r"|it|playing|this|that)(?:\s+(?:from|on|in|playing))?)?|(?:what|which)\s+playlist\s+(?:am\s+i|are\s+we|is\s+(?:this|it|playing|on))(?:\s+(?:listening\s+to|playing|on|in|from))?|playlist\s+name|(?:what|which)\s+is\s+(?:the\s+)?name\s+of\s+(?:the|this)\s+playlist|(?:what|which)\s+(?:playlist|album)\s+is\s+(?:this|it)\s+(?:song\s+)?from", t):
        return 'playlist'
    if re.fullmatch(r"(?:what|which)\s+is\s+(?:the\s+)?(?:next|up\s+next|coming\s+(?:up\s+)?next|playing\s+next|next\s+" + song + r"|" + song + r"\s+(?:is\s+)?(?:up\s+)?next)(?:\s+(?:in\s+(?:the|my)\s+)?queue)?(?:\s+(?:after|after\s+" + _CURRENT + r"))?|(?:what|which)\s+(?:song|track)\s+(?:is\s+|comes\s+|plays\s+)?(?:up\s+)?next|(?:what|which)\s+(?:comes|plays)\s+next|next\s+(?:song|track)(?:\s+name)?|up\s+next", t):
        return 'next'
    if re.fullmatch(r"(?:what|which)\s+is\s+(?:in\s+)?(?:the\s+|my\s+)?(?:queue|queued|lined\s+up|coming\s+up)|(?:what|which)\s+(?:songs|tracks)\s+(?:are\s+)?(?:in\s+(?:the\s+|my\s+)?queue|queued|(?:coming\s+)?up(?:\s+next)?|next)|(?:show|list|read)\s+(?:me\s+)?(?:the\s+|my\s+)?queue|(?:the\s+|my\s+)?queue|what\s+is\s+(?:the\s+|my\s+)?queue(?:\s+like)?", t):
        return 'queue'
    if re.fullmatch(r"(?:what|which)\s+is\s+(?:the\s+)?(?:name\s+of\s+(?:the\s+|this\s+)?)?(?:current\s+)?" + song + r"(?:\s+name)?" + live + r"|(?:what|which)\s+is\s+(?:the\s+)?(?:current\s+)?" + song + r"(?:'s)?\s+name|(?:what|which)\s+is\s+(?:currently\s+|now\s+)?playing(?:\s+(?:now|right\s+now))?|(?:what|which)\s+is\s+(?:this|that|it)\s+(?:song|track|tune)(?:\s+called)?|(?:what|which)\s+" + song + r"\s+(?:is\s+)?(?:this|that|it|playing|on)(?:\s+(?:currently|now|right\s+now|playing))*|(?:what|which)\s+" + song + r"\s+is\s+(?:currently|now)\s+(?:playing|on)(?:\s+(?:now|right\s+now))?|(?:what|which)\s+(?:am\s+i|are\s+we)\s+(?:listening\s+to|playing|hearing)(?:\s+(?:now|right\s+now))?|(?:the\s+|current\s+)?" + song + r"\s+name|(?:i\s+need|give\s+me)\s+(?:the\s+)?(?:name\s+of\s+(?:the\s+|this\s+)?" + song + r"|" + song + r"\s+name)|now\s+playing|current\s+(?:song|track)|name\s+(?:of\s+)?(?:the\s+|this\s+)?" + song + r"", t):
        return 'song'
    return None


class MusicSongRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(default="", max_length=200)


class MusicPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["artist_stats", "find_artists", "artist_songs", "album_stats", "list_albums", "show_chart", "play_chart", "mute", "unmute", "restart", "list_playlists", "listening_history", "suggest_music", "play_song", "play_artist", "play_album", "play_playlist", "play_saved_playlist", "play_liked", "play_podcast", "play_episode", "create_playlist", "curate_playlist", "seek", "pause", "resume", "next", "previous", "set_shuffle", "set_volume", "adjust_volume", "set_repeat", "save_current", "remove_current", "check_current", "current", "clarify"]
    provider: str = Field(default="spotify", max_length=80, pattern=r"^[a-z][a-z0-9_\-]*$")
    query: str = Field(default="", max_length=500)
    artist: str = Field(default="", max_length=200)
    songs: list[MusicSongRequest] = Field(default_factory=list, max_length=50)
    version: Literal["unspecified", "original"] = "unspecified"
    description: str = Field(default="", max_length=300)
    shuffle: bool | None = None
    position: int | None = Field(default=None, ge=1, le=100000)
    source_uri: str = Field(default="", max_length=200)
    latest: bool = False
    chart_period: Literal['daily', 'weekly'] = 'daily'
    country: str = Field(default='global', max_length=80)
    limit: int = Field(default=10, ge=1, le=50)
    album_order: Literal['newest', 'oldest'] = 'newest'
    track_uri: str = Field(default='', max_length=200, pattern=r'^(?:spotify:track:[A-Za-z0-9]+)?$')
    volume_percent: int | None = Field(default=None, ge=0, le=100)
    seek_delta_ms: int | None = Field(default=None, ge=-86400000, le=86400000)
    volume_delta_percent: int | None = Field(default=None, ge=-100, le=100)
    repeat_state: Literal["track", "context", "off"] | None = None
    previous_repeat_state: Literal["track", "context", "off"] | None = None
    repeat_device_id: str = Field(default='',max_length=256)
    volume_device_id: str = Field(default='',max_length=256)
    collection: Literal['liked', 'playlist'] = 'liked'
    track_query: str = Field(default='', max_length=200)
    history_period: Literal['today', 'yesterday', 'recent', 'date'] = 'recent'
    history_date: str = Field(default='', max_length=10, pattern=r'^(?:\d{4}-\d{2}-\d{2})?$')

    @model_validator(mode="after")
    def required_arguments(self):
        if self.operation == 'play_artist' and not self.artist.strip():
            raise ValueError('An artist is required to choose a song from their catalog')
        if self.operation == 'play_album' and not (self.artist.strip() if self.latest else self.query.strip()):
            raise ValueError('An artist is required for the latest album, or supply an album title')
        if self.operation in {"play_song", "play_playlist", "play_podcast", "play_episode", "create_playlist"} and not self.query.strip():
            raise ValueError("A song or playlist name is required")
        if self.operation == "create_playlist" and not self.songs:
            raise ValueError("Supply the songs for the new playlist")
        if self.operation == "set_shuffle" and self.shuffle is None:
            raise ValueError("Choose whether shuffle is on or off")
        if self.operation == "set_volume" and self.volume_percent is None:
            raise ValueError("A volume from 0 to 100 is required")
        if self.operation == "seek" and self.seek_delta_ms is None:
            raise ValueError("A seek interval is required")
        if self.operation == "adjust_volume" and self.volume_delta_percent is None:
            raise ValueError("A volume change is required")
        if self.operation == "set_repeat" and self.repeat_state is None:
            raise ValueError("A repeat mode is required")
        return self


class MusicCompoundContinuation(BaseModel):
    """Unfinished, preflighted actions held only in the specialist thread context."""
    model_config = ConfigDict(extra='forbid')
    clauses: list[str] = Field(min_length=1, max_length=8)
    plans: list[MusicPlan | None] = Field(min_length=1, max_length=8)
    at: float

    @model_validator(mode='after')
    def aligned_actions(self):
        if len(self.clauses) != len(self.plans) or any(not c.strip() or len(c) > 2000 for c in self.clauses):
            raise ValueError('Invalid unfinished music actions')
        return self


class MusicPlaybackProposal(BaseModel):
    """Provider-resolved listening session retained by the pending-action owner."""
    model_config = ConfigDict(extra='forbid')
    provider: Literal['spotify'] = 'spotify'
    uri: str = Field(pattern=r'^spotify:(?:track|playlist):[A-Za-z0-9]+$')
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field(default='', max_length=400)
    continuation_uris: list[str] = Field(default_factory=list, max_length=49)

    @model_validator(mode='after')
    def valid_continuation(self):
        if any(not re.fullmatch(r'spotify:track:[A-Za-z0-9]+', uri) for uri in self.continuation_uris):
            raise ValueError('Invalid continuation track')
        if self.uri.startswith('spotify:playlist:') and self.continuation_uris:
            raise ValueError('Playlist sessions cannot carry a track queue')
        return self


class ResolvedMusicSong(MusicSongRequest):
    uri: str = Field(min_length=1, max_length=200)


class MusicPlaylistCreateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = Field(max_length=80, pattern=r"^[a-z][a-z0-9_\-]*$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)
    songs: list[ResolvedMusicSong] = Field(min_length=1, max_length=50)


class MusicCollectionChangeProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['save', 'remove']
    collection: Literal['liked', 'playlist']
    track_uri: str = Field(pattern=r'^spotify:track:[A-Za-z0-9]+$')
    track_title: str = Field(min_length=1, max_length=200)
    playlist_id: str = Field(default='', max_length=160, pattern=r'^[A-Za-z0-9]*$')
    playlist_name: str = Field(default='', max_length=200)

    @model_validator(mode='after')
    def playlist_target(self):
        if self.collection=='playlist' and (not self.playlist_id or not self.playlist_name):
            raise ValueError('An exact playlist is required')
        return self


class MusicIntegration(Protocol):
    skill_id: str

    def execute(self, plan: MusicPlan, invoke: Callable[[str, dict], dict]) -> str:
        """Execute normalized intent using only the permissioned capability invoker."""
        ...


class MusicChoiceRequired(ValueError):
    """A provider found multiple valid matches; no playback has happened."""

    def __init__(self, message: str, choices: list[dict]):
        super().__init__(message)
        self.choices = choices[:5]
        self.song_index: int | None = None
