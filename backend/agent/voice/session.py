"""Canonical Vellum voice session backed by an isolated LFM2.5 worker."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import subprocess
from typing import Any, AsyncIterator
from uuid import uuid4

import anyio

from agent.config import REPO_ROOT, Settings, get_settings
from agent.contracts.voice import DictationStatus, DictationTranscript, VoiceCapabilities, VoiceStatus
from agent.voice.dictation_models import model_identity


_LOGGER = logging.getLogger(__name__)
_PROTOCOL_LIMIT = 32 * 1024 * 1024


class VoiceSessionError(RuntimeError):
    """A safe, user-presentable local voice session failure."""


@dataclass(frozen=True, slots=True)
class VoiceEvent:
    type: str
    data: dict[str, Any]


class LfmVoiceSession:
    """Own one persistent model worker and serialize direct-audio turns.

    The worker is deliberately a model process, not another Vellum runtime: it
    owns no tools, stores, schedulers, or HTTP routes. Vellum retains the public
    session contract and the conversation UI.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._warmup_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._ready = False
        self._worker_metadata: dict[str, Any] = {}
        self._state = "cold"
        self._detail = "Installed; the local model loads on the first voice turn."

    @property
    def worker_script(self) -> Path:
        return Path(__file__).with_name("lfm_worker.py")

    @property
    def worker_environment(self) -> dict[str, str]:
        return {}

    @property
    def diagnostic_filename(self) -> str:
        return "voice-worker.log"

    @property
    def model_label(self) -> str:
        return "LFM2.5-Audio"

    @property
    def python_executable(self) -> Path:
        if os.name == "nt":
            return self.settings.voice_model_dir / ".venv" / "Scripts" / "python.exe"
        return self.settings.voice_model_dir / ".venv" / "bin" / "python"

    @property
    def installed(self) -> bool:
        return self.python_executable.is_file() and self.worker_script.is_file()

    @property
    def capabilities(self) -> VoiceCapabilities:
        return VoiceCapabilities(
            available=bool(self.settings.voice_enabled and self.installed),
            notes=[
                "Hands-free half-duplex preview: the browser detects speech followed by a pause and listens again after playback. Barge-in and semantic turn detection are not enabled.",
                "This direct-audio provider cannot call Vellum tools or write Vellum memory.",
            ],
        )

    def status(self) -> VoiceStatus:
        enabled = bool(self.settings.voice_enabled)
        process_alive = self._process is not None and self._process.returncode is None
        ready = bool(enabled and self.installed and process_alive and self._ready)
        if not enabled:
            state = "disabled"
            detail = "Voice is disabled by VOICE_ENABLED."
        elif not self.installed:
            state = "unavailable"
            detail = f"The isolated LFM2.5-Audio environment is missing at {self.python_executable}."
        elif ready:
            state = self._state if self._state in {"ready", "busy"} else "ready"
            detail = self._detail or "The local direct-audio worker is ready."
        elif self._state in {"starting", "error"}:
            state = self._state
            detail = self._detail
        else:
            state = "cold"
            detail = "Installed; the local model loads on the first voice turn."
        return VoiceStatus(
            enabled=enabled,
            ready=ready,
            state=state,
            detail=detail,
            capabilities=self.capabilities,
        )

    def prepare(self) -> VoiceStatus:
        """Warm the single worker independently of a browser request's lifetime."""
        if not self.settings.voice_enabled:
            raise VoiceSessionError("Voice is disabled.")
        if not self.installed:
            raise VoiceSessionError("The isolated LFM2.5-Audio worker is not installed.")
        if not self._ready and (self._warmup_task is None or self._warmup_task.done()):
            self._state = "starting"
            self._detail = "Loading the local voice model."
            self._warmup_task = asyncio.create_task(self._warm_worker())
        return self.status()

    async def _warm_worker(self) -> None:
        async with self._lock:
            try:
                await self._ensure_worker()
            except asyncio.CancelledError:
                await self._stop_worker()
                raise
            except Exception as exc:
                await self._stop_worker()
                self._state = "error"
                self._detail = str(exc) if isinstance(exc, VoiceSessionError) else "The local voice model could not load."
                _LOGGER.exception("Could not prepare the local voice worker")

    async def stream_turn(self, audio: bytes, *, session_id: str, response_preferences: str = '', language: str | None = None, dictionary: list[str] | None = None) -> AsyncIterator[VoiceEvent]:
        self.prepare()
        # A cancelled recording/upload must not cancel imports and checkpoint
        # loading. Only active generation needs a process reset in this preview.
        if self._warmup_task is not None:
            await asyncio.shield(self._warmup_task)
        if self._state == "error":
            raise VoiceSessionError(self._detail)

        request_id = f"voice_{uuid4().hex}"
        async with self._lock:
            try:
                await self._ensure_worker()
                process = self._process
                if process is None or process.stdin is None or process.stdout is None:
                    raise VoiceSessionError("The local audio worker did not start.")

                self._state = "busy"
                self._detail = "Generating a local direct-audio reply."
                request = {
                    "type": "turn",
                    "request_id": request_id,
                    "session_id": session_id,
                    "audio_b64": base64.b64encode(audio).decode("ascii"),
                    "response_preferences": response_preferences[:10000],
                }
                if language is not None:
                    request['language']=language
                if dictionary:
                    request['dictionary']=dictionary
                process.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8"))
                await process.stdin.drain()
                deadline = asyncio.get_running_loop().time() + self.settings.voice_turn_timeout_seconds
                while True:
                    try:
                        line = await asyncio.wait_for(
                            process.stdout.readline(),
                            timeout=max(0.01, deadline - asyncio.get_running_loop().time()),
                        )
                    except TimeoutError as exc:
                        raise VoiceSessionError("The local audio model timed out.") from exc
                    if not line:
                        raise VoiceSessionError("The local audio model stopped unexpectedly.")
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise VoiceSessionError("The local audio worker returned an invalid response.") from exc
                    if message.get("request_id") != request_id:
                        _LOGGER.warning("Ignoring stale voice worker message for %s", message.get("request_id"))
                        continue
                    event_type = str(message.get("type") or "")
                    if event_type == "error":
                        raise VoiceSessionError(str(message.get("message") or "The local audio model failed."))
                    if event_type not in {"progress", "transcript_delta", "transcript", "text_delta", "audio_delta", "completed"}:
                        raise VoiceSessionError("The local audio worker returned an unknown event.")
                    data = {key: value for key, value in message.items() if key not in {"type", "request_id"}}
                    yield VoiceEvent(event_type, data)
                    if event_type == "completed":
                        self._state = "ready"
                        self._detail = "The local direct-audio worker is ready."
                        return
            except asyncio.CancelledError:
                # The v1 worker generates synchronously. Killing it is the only
                # reliable way to avoid leaving unread tokens in the protocol.
                try:
                    await self._stop_worker()
                finally:
                    self._state = "cold"
                    self._detail = "Voice generation was stopped; the model will reload on the next turn."
                raise
            except VoiceSessionError:
                await self._stop_worker()
                self._state = "error"
                self._detail = "The local voice worker needs to be restarted."
                raise
            except Exception as exc:
                await self._stop_worker()
                self._state = "error"
                self._detail = "The local voice worker needs to be restarted."
                _LOGGER.exception("Unexpected LFM2.5 voice worker failure")
                raise VoiceSessionError("The local audio model failed unexpectedly.") from exc

    async def _ensure_worker(self) -> None:
        if self._stop_task is not None:
            await self._stop_worker()
        if self._process is not None and self._process.returncode is None and self._ready:
            return
        await self._stop_worker()
        self._state = "starting"
        self._detail = f"Loading {self.model_label}. The first turn can take a while."

        env = os.environ.copy()
        cache_root = REPO_ROOT / "data" / "cache"
        hf_home = cache_root / "huggingface"
        lfm_cache = cache_root / "lfm-audio"
        temp_dir = lfm_cache / "temp"
        for path in (hf_home, lfm_cache / "triton", lfm_cache / "inductor", temp_dir):
            path.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "HF_HOME": str(hf_home),
                "HF_HUB_CACHE": str(hf_home / "hub"),
                "TRANSFORMERS_CACHE": str(hf_home / "transformers"),
                "HF_XET_HIGH_PERFORMANCE": "1",
                "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "PYTHONUTF8": "1",
                "TRITON_CACHE_DIR": str(lfm_cache / "triton"),
                "TORCHINDUCTOR_CACHE_DIR": str(lfm_cache / "inductor"),
                "TEMP": str(temp_dir),
                "TMP": str(temp_dir),
                "VELLUM_VOICE_MAX_OUTPUT_TOKENS": str(self.settings.voice_max_output_tokens),
                "VELLUM_VOICE_MAX_SESSIONS": str(self.settings.voice_max_sessions),
                "VELLUM_VOICE_PARENT_PID": str(os.getpid()),
            }
        )
        env.update(self.worker_environment)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self._process = await asyncio.create_subprocess_exec(
                str(self.python_executable),
                "-u",
                str(self.worker_script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(REPO_ROOT),
                env=env,
                limit=_PROTOCOL_LIMIT,
                creationflags=creationflags,
            )
            self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))
            if self._process.stdout is None:
                raise VoiceSessionError("The local audio worker has no output stream.")
            line = await asyncio.wait_for(
                self._process.stdout.readline(),
                timeout=self.settings.voice_startup_timeout_seconds,
            )
            if not line:
                raise VoiceSessionError("The local audio worker exited during startup.")
            message = json.loads(line.decode("utf-8"))
            if message.get("type") != "ready":
                detail = str(message.get("message") or "The local audio worker did not become ready.")
                raise VoiceSessionError(detail)
            self._worker_metadata = message
        except TimeoutError as exc:
            await self._stop_worker()
            raise VoiceSessionError(f"{self.model_label} took too long to load.") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            await self._stop_worker()
            raise VoiceSessionError("The local audio worker could not be started.") from exc

        self._ready = True
        self._state = "ready"
        self._detail = "The local direct-audio worker is ready."

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        log_dir = REPO_ROOT / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (log_dir / self.diagnostic_filename).open("w", encoding="utf-8") as log:
                size = 0
                while line := await process.stderr.readline():
                    detail = line.decode("utf-8", errors="replace").rstrip()
                    if detail.startswith("Voice startup:"):
                        self._detail = detail.removeprefix("Voice startup:").strip()
                    if size < 1024 * 1024:
                        log.write(detail + "\n")
                        log.flush()
                        size += len(line)
                    _LOGGER.info("LFM2.5 worker: %s", detail)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Could not read LFM2.5 worker diagnostics")

    async def _stop_worker(self) -> None:
        # StreamingResponse uses an AnyIO cancel scope: every await in cleanup
        # is cancelled again unless shielded. Keep ownership until the entire
        # Windows launcher/interpreter tree exits, before allowing a replacement.
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_worker_tree())
        task = self._stop_task
        cancelled = False
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
            try:
                task.result()
            finally:
                if self._stop_task is task:
                    self._stop_task = None
        if cancelled:
            raise asyncio.CancelledError

    async def _stop_worker_tree(self) -> None:
        process = self._process
        self._ready = False
        stderr_task = self._stderr_task
        if process is not None and process.returncode is None:
            if os.name == "nt":
                # Windows venv python.exe is a launcher with a child interpreter.
                # Terminating only the launcher leaves CUDA work orphaned.
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=10,
                        check=False,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    _LOGGER.exception("Could not stop the Windows voice worker tree")
                    if process.returncode is None:
                        process.terminate()
            else:
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
        if stderr_task is not None:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass
        if self._process is process:
            self._process = None
        if self._stderr_task is stderr_task:
            self._stderr_task = None

    async def close(self) -> None:
        if self._warmup_task is not None and not self._warmup_task.done():
            self._warmup_task.cancel()
            with anyio.CancelScope(shield=True):
                try:
                    await self._warmup_task
                except asyncio.CancelledError:
                    pass
        async with self._lock:
            await self._stop_worker()
            self._state = "cold"
            self._detail = "Installed; the local model loads on the first voice turn."


_voice_session: LfmVoiceSession | None = None
_dictation_session: WhisperDictationSession | None = None


class WhisperDictationSession(LfmVoiceSession):
    """Transcription mode using the same bounded local-worker lifecycle as voice.

    There is no agent turn or conversation store here. Only explicit text-chat
    submission gives the resulting draft to Vellum's agent.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self.device = settings.dictation_device
        super().__init__(settings.model_copy(update={
            "voice_enabled": settings.voice_enabled and settings.dictation_enabled,
            "voice_model_dir": settings.dictation_model_dir,
        }))

    @property
    def worker_script(self) -> Path:
        return Path(__file__).with_name("whisper_worker.py")

    @property
    def installed(self) -> bool:
        root = self.settings.voice_model_dir
        return super().installed and all((root / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json"))

    @property
    def worker_environment(self) -> dict[str, str]:
        return {"VELLUM_DICTATION_MODEL_DIR": str(self.settings.voice_model_dir), "VELLUM_DICTATION_DEVICE": self.device,
                "VELLUM_DICTATION_MODEL_ID": self.model_id}

    @property
    def model_id(self) -> str:
        return model_identity(self.settings.voice_model_dir)[0]

    @property
    def diagnostic_filename(self) -> str:
        return "dictation-worker.log"

    @property
    def model_label(self) -> str:
        return model_identity(self.settings.voice_model_dir)[1]

    def status(self) -> DictationStatus:
        enabled = self.settings.voice_enabled
        available = enabled and self.installed
        ready = available and self._ready and self._process is not None and self._process.returncode is None
        state = "disabled" if not enabled else "unavailable" if not available else self._state if self._state in {"starting", "error"} else "busy" if ready and self._state == "busy" else "ready" if ready else "cold"
        detail = f"Local {self.model_label} is ready." if ready else f"{self.model_label} loads when dictation starts."
        if not enabled:
            detail = "Local dictation is disabled."
        elif not available:
            detail = "Local dictation is not installed. Run scripts/setup-dictation.ps1, then try again."
        elif state == "starting":
            detail = f"Loading local {self.model_label}."
        elif state == "error":
            detail = "Local dictation could not start. Try again or check data/logs/dictation-worker.log."
        return DictationStatus(enabled=enabled, available=available, ready=ready, state=state, detail=detail,
                               model=self.model_id,
                               device=str(self._worker_metadata.get("device", self.device)))

    def prepare(self) -> DictationStatus:
        if not self.settings.voice_enabled or not self.installed:
            raise VoiceSessionError(self.status().detail)
        if not self._ready and (self._warmup_task is None or self._warmup_task.done()):
            self._state = "starting"
            self._warmup_task = asyncio.create_task(self._warm_worker())
        return self.status()

    async def transcribe(self, audio: bytes, *, duration_seconds: float, language: str | None = None, dictionary: list[str] | None = None) -> DictationTranscript:
        from agent.voice.dictation_models import validate_language
        requested=validate_language(language or 'auto')
        transcript = None
        async for event in self.stream_turn(audio, session_id="dictation", language=None if requested=='auto' else requested,dictionary=dictionary):
            if event.type == "transcript":
                transcript = event.data
        if transcript is None:
            raise VoiceSessionError("Local dictation returned no transcript. Try again.")
        return DictationTranscript(text=str(transcript.get("text", "")).strip(),
                                   requested_language=requested,
                                   model=self.model_id,
                                   language=transcript.get("language"), duration_seconds=duration_seconds,
                                   device=str(self._worker_metadata.get("device", self.device)))


def get_dictation_session() -> WhisperDictationSession:
    global _dictation_session
    if _dictation_session is None:
        _dictation_session = WhisperDictationSession()
    return _dictation_session


def get_voice_session() -> LfmVoiceSession:
    global _voice_session
    if _voice_session is None:
        _voice_session = LfmVoiceSession()
    return _voice_session


async def close_voice_session() -> None:
    global _voice_session, _dictation_session
    session = _voice_session
    _voice_session = None
    if session is not None:
        await session.close()
    dictation = _dictation_session
    _dictation_session = None
    if dictation is not None:
        await dictation.close()
