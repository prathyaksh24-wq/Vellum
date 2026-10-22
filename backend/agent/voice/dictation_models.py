"""Pinned public dictation checkpoints shared by setup and the local worker owner."""

import json
from pathlib import Path

DEFAULT_MODEL = "large-v3-turbo"
LANGUAGE_CODES = tuple("af am ar as az ba be bg bn bo br bs ca cs cy da de el en es et eu fa fi fo fr gl gu ha haw he hi hr ht hu hy id is it ja jw ka kk km kn ko la lb ln lo lt lv mg mi mk ml mn mr ms mt my ne nl nn no oc pa pl ps pt ro ru sa sd si sk sl sn so sq sr su sv sw ta te tg th tk tl tr tt uk ur uz vi yi yo zh yue".split())


def validate_language(value: str) -> str:
    if value != "auto" and value not in LANGUAGE_CODES:
        raise ValueError("Choose Auto or a supported dictation language.")
    return value


MODELS = {
    "small": {"repo_id": "Systran/faster-whisper-small", "revision": "536b0662742c02347bc0e980a01041f333bce120", "model_id": "openai/whisper-small", "label": "Whisper Small"},
    "large-v3-turbo": {"repo_id": "dropbox-dash/faster-whisper-large-v3-turbo", "revision": "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf", "model_id": "openai/whisper-large-v3-turbo", "label": "Whisper Large v3 Turbo"},
}


def model_identity(directory: Path) -> tuple[str, str]:
    source = directory / "source.json"
    if source.is_file():
        try:
            if source.stat().st_size <= 4096:
                repo = json.loads(source.read_text(encoding="utf-8")).get("repo_id")
                for model in MODELS.values():
                    if model["repo_id"] == repo:
                        return model["model_id"], model["label"]
        except (OSError, ValueError, AttributeError):
            pass
        return "local/whisper", "Local Whisper"
    model = MODELS.get(directory.name.removeprefix("whisper-"))
    return (model["model_id"], model["label"]) if model else ("local/whisper", "Local Whisper")
