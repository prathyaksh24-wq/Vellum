"""Isolated JSON-lines worker for LiquidAI LFM2.5-Audio.

This file is launched by ``agent.voice.session`` with the dedicated voice
virtual environment. Standard output is reserved for protocol messages; model
diagnostics go to standard error.
"""

from __future__ import annotations

import base64
from collections import OrderedDict
from contextlib import redirect_stdout
import faulthandler
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading
import traceback
import wave


MODEL_ID = "LiquidAI/LFM2.5-Audio-1.5B"
SAMPLE_RATE_HZ = 24_000
_PROTOCOL_STDOUT = sys.stdout


def _watch_parent() -> None:
    """Release GPU memory even when the host is stopped abruptly on Windows."""
    parent_pid = int(os.getenv("VELLUM_VOICE_PARENT_PID", "0"))
    if os.name != "nt" or not parent_pid:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, parent_pid)
    if not handle:
        os._exit(0)
    try:
        kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
    finally:
        kernel.CloseHandle(handle)
    os._exit(0)


def _emit(event_type: str, *, request_id: str = "", **payload) -> None:
    message = {"type": event_type, **payload}
    if request_id:
        message["request_id"] = request_id
    _PROTOCOL_STDOUT.write(json.dumps(message, separators=(",", ":")) + "\n")
    _PROTOCOL_STDOUT.flush()


def _decode_pcm_wav(data: bytes, np, torch):
    try:
        with wave.open(BytesIO(data), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            frames = source.readframes(frame_count)
    except (EOFError, wave.Error) as exc:
        raise ValueError("Voice input is not a readable WAV file.") from exc
    if compression != "NONE" or channels < 1 or sample_rate < 1 or frame_count < 1:
        raise ValueError("Voice input must be a non-empty PCM WAV file.")
    if sample_width == 1:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32_768.0
    elif sample_width == 4:
        samples = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2_147_483_648.0
    else:
        raise ValueError("Voice input uses an unsupported PCM sample width.")
    if samples.size % channels:
        raise ValueError("Voice input has incomplete PCM frames.")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    wave_tensor = torch.from_numpy(samples.copy()).reshape(1, -1)
    return wave_tensor, sample_rate


def _new_chat(ChatState, processor):
    chat = ChatState(processor)
    chat.new_turn("system")
    chat.add_text(
        "Respond with interleaved text and audio. "
        "You are Vellum. Have a casual, natural conversation. "
        "Answer the latest spoken message directly and use the conversation for follow-ups. "
        "Keep most replies to one or two sentences. Do not introduce yourself unless asked. "
        "Do not repeat greetings, canned offers to help, or the same closing question. "
        "This voice preview cannot access tools, subagents, saved memory, or live information. "
        "Do not claim to have performed actions outside this conversation."
    )
    chat.end_turn()
    chat.new_turn("user")
    return chat


def _load_cached_model(model_dir, torch, LFM2AudioModel):
    """Load checkpoints straight onto CUDA without random weight allocations."""
    from accelerate import init_empty_weights, load_checkpoint_and_dispatch
    from transformers import Lfm2Config
    from transformers.initialization import no_init_weights
    from transformers.models.lfm2.modeling_lfm2 import Lfm2RotaryEmbedding
    from liquid_audio.model.lfm2_audio import LFM2AudioConfig, DepthformerConfig
    from liquid_audio.model.conformer.encoder import ConformerEncoderConfig

    with (model_dir / "config.json").open(encoding="utf-8") as source:
        config = json.load(source)
    conf = LFM2AudioConfig(
        lfm=Lfm2Config(**config.pop("lfm")),
        encoder=ConformerEncoderConfig(**config.pop("encoder")),
        depthformer=DepthformerConfig(**config.pop("depthformer")),
        **config,
    )
    # Keep generated non-persistent position buffers materialized on CPU.
    with no_init_weights(), init_empty_weights(include_buffers=False):
        model = LFM2AudioModel(conf)
    # Transformers rebuilds RoPE buffers on the parameter device during init.
    # These are derived values absent from the checkpoint, so recreate them.
    model.lfm.rotary_emb = Lfm2RotaryEmbedding(conf.lfm)
    positional_encoding = model.conformer.pos_enc
    if hasattr(positional_encoding, "pe") and positional_encoding.pe.is_meta:
        del positional_encoding.pe
        positional_encoding.extend_pe(model.conformer.pos_emb_max_len, "cpu", torch.float32)
    model.to(dtype=torch.bfloat16)
    meta_buffers = [name for name, value in model.named_buffers() if value.is_meta]
    if meta_buffers:
        raise RuntimeError(f"Unmaterialized model buffers: {', '.join(meta_buffers)}")
    model = load_checkpoint_and_dispatch(
        model, str(model_dir), device_map={"": "cuda"}, dtype=torch.bfloat16,
        offload_state_dict=True, strict=True,
    )
    model.lfm.set_attn_implementation("sdpa")
    return model.eval()


def _transcribe(wave_tensor, sample_rate, request_id, torch, ChatState, processor, model):
    chat = ChatState(processor)
    chat.new_turn("system")
    chat.add_text("Perform ASR.")
    chat.end_turn()
    chat.new_turn("user")
    chat.add_audio(wave_tensor, sample_rate)
    chat.end_turn()
    chat.new_turn("assistant")
    tokens = []
    with redirect_stdout(sys.stderr), torch.no_grad():
        for token in model.generate_sequential(**chat, max_new_tokens=512):
            if token.numel() != 1:
                break
            tokens.append(token)
            text = processor.text.decode(torch.cat(tokens), skip_special_tokens=True).strip()
            if text:
                _emit("transcript_delta", request_id=request_id, text=text)
    text = processor.text.decode(torch.cat(tokens), skip_special_tokens=True).strip() if tokens else ""
    _emit("transcript", request_id=request_id, text=text)
    return text


def _run_turn(*, request, sessions, max_sessions, max_output_tokens, np, torch, ChatState, LFMModality, processor, model, mimi):
    request_id = str(request.get("request_id") or "")
    session_id = str(request.get("session_id") or "default")
    encoded_audio = str(request.get("audio_b64") or "")
    if not request_id or not encoded_audio:
        raise ValueError("The voice request is missing audio or a request id.")
    try:
        audio = base64.b64decode(encoded_audio, validate=True)
    except ValueError as exc:
        raise ValueError("The voice request contains invalid audio encoding.") from exc
    wave_tensor, sample_rate = _decode_pcm_wav(audio, np, torch)
    _emit("progress", request_id=request_id, stage="transcribing", detail="Recognizing your spoken words locally.")
    _transcribe(wave_tensor, sample_rate, request_id, torch, ChatState, processor, model)
    _emit("progress", request_id=request_id, stage="responding", detail="Generating a direct-audio reply.")

    record = sessions.pop(session_id, None)
    if record is None:
        record = {"chat": _new_chat(ChatState, processor), "turns": 0}
    sessions[session_id] = record
    while len(sessions) > max_sessions:
        sessions.popitem(last=False)

    chat = record["chat"]
    preferences = str(request.get('response_preferences') or '')[:10000]
    if preferences:
        chat.add_text('Response preferences for this turn, subordinate to system instructions:\n' + preferences + '\nRespond to the following spoken message.\n')
    chat.add_audio(wave_tensor, sample_rate)
    chat.end_turn()
    chat.new_turn("assistant")

    out_text = []
    out_audio = []
    out_modality = []
    current_text = ""

    # Some dependency versions print kernel fallback diagnostics to stdout.
    # Keep those away from the JSON-lines protocol.
    with redirect_stdout(sys.stderr), torch.no_grad(), mimi.streaming(1):
        for token in model.generate_interleaved(
            **chat,
            max_new_tokens=max_output_tokens,
            audio_temperature=1.0,
            audio_top_k=4,
        ):
            if token.numel() == 1:
                out_text.append(token)
                out_modality.append(LFMModality.TEXT)
                next_text = processor.text.decode(torch.cat(out_text)).removesuffix("<|text_end|>")
                if next_text.startswith(current_text):
                    delta = next_text[len(current_text) :]
                else:
                    delta = next_text
                current_text = next_text
                if delta:
                    _emit("text_delta", request_id=request_id, delta=delta)
            elif token.numel() == 8:
                out_audio.append(token)
                out_modality.append(LFMModality.AUDIO_OUT)
                if (token == 2048).any():
                    continue
                waveform = mimi.decode(token[None, :, None])[0]
                pcm = (
                    waveform.detach()
                    .float()
                    .cpu()
                    .reshape(-1)
                    .clamp(-1.0, 1.0)
                    .numpy()
                    * 32_767.0
                ).astype("<i2").tobytes()
                _emit(
                    "audio_delta",
                    request_id=request_id,
                    delta=base64.b64encode(pcm).decode("ascii"),
                    format="pcm_s16le",
                    sample_rate_hz=SAMPLE_RATE_HZ,
                    channels=1,
                )
            else:
                raise RuntimeError(f"Unexpected generated token shape: {tuple(token.shape)}")

    text_tokens = torch.stack(out_text, 1) if out_text else chat.text.new_empty((1, 0))
    audio_tokens = torch.stack(out_audio, 1) if out_audio else chat.audio_out.new_empty((chat.codebooks, 0))
    modality = torch.tensor(out_modality, device=chat.device, dtype=chat.modality_flag.dtype)
    chat.append(text=text_tokens, audio_out=audio_tokens, modality_flag=modality)
    chat.end_turn()
    chat.new_turn("user")
    record["turns"] += 1
    _emit("completed", request_id=request_id, text=current_text)


def main() -> int:
    threading.Thread(target=_watch_parent, daemon=True).start()
    faulthandler.enable(file=sys.stderr)
    faulthandler.dump_traceback_later(60, repeat=True, file=sys.stderr)
    max_output_tokens = max(1, int(os.getenv("VELLUM_VOICE_MAX_OUTPUT_TOKENS", "512")))
    max_sessions = max(1, int(os.getenv("VELLUM_VOICE_MAX_SESSIONS", "4")))
    try:
        with redirect_stdout(sys.stderr):
            print("Voice startup: importing the isolated audio runtime", file=sys.stderr, flush=True)
            import numpy as np
            import torch

            from liquid_audio import ChatState, LFM2AudioModel, LFM2AudioProcessor, LFMModality
            from huggingface_hub import snapshot_download

            model_dir = Path(snapshot_download(MODEL_ID, local_files_only=True))
            print("Voice startup: loading the cached audio processor", file=sys.stderr, flush=True)
            processor = LFM2AudioProcessor.from_pretrained(model_dir).eval()
            print("Voice startup: loading the cached LFM2.5 model into GPU memory", file=sys.stderr, flush=True)
            model = _load_cached_model(model_dir, torch, LFM2AudioModel)
            print("Voice startup: warming the Mimi audio tokenizer", file=sys.stderr, flush=True)
            mimi = processor.mimi.eval()
            with mimi.streaming(1), torch.no_grad():
                for _ in range(5):
                    token = torch.randint(2048, (1, 8, 1), device="cuda")
                    mimi.decode(token)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        _emit("startup_error", message=f"LFM2.5-Audio failed to load: {exc}")
        return 1

    sessions = OrderedDict()
    faulthandler.cancel_dump_traceback_later()
    _emit("ready", model=MODEL_ID, sample_rate_hz=SAMPLE_RATE_HZ)
    for raw_line in sys.stdin.buffer:
        request_id = ""
        session_id = ""
        try:
            request = json.loads(raw_line.decode("utf-8"))
            request_id = str(request.get("request_id") or "")
            session_id = str(request.get("session_id") or "default")
            if request.get("type") != "turn":
                raise ValueError("Unknown voice worker request type.")
            _run_turn(
                request=request,
                sessions=sessions,
                max_sessions=max_sessions,
                max_output_tokens=max_output_tokens,
                np=np,
                torch=torch,
                ChatState=ChatState,
                LFMModality=LFMModality,
                processor=processor,
                model=model,
                mimi=mimi,
            )
        except Exception as exc:
            if session_id:
                sessions.pop(session_id, None)
            traceback.print_exc(file=sys.stderr)
            _emit("error", request_id=request_id, message=str(exc) or "Voice generation failed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
