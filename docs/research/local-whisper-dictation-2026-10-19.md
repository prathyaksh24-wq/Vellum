# Local Whisper dictation research

Researched 2026-10-19. Research only: no packages installed, weights downloaded, microphone recording, inference, latency measurement, or UI implementation performed.

## Recommendation

Start the lower-resource dictation trial with multilingual **Whisper small through faster-whisper**, then compare **large-v3-turbo** before choosing a default. Use GPU `float16` only after the runtime smoke test; CPU `int8` is the fallback. These are proposals, not measured winners on this machine. The live hardware inspection in this research session found an RTX 5070 Ti Laptop GPU, 12,227 MiB total / 11,681 MiB free, driver 591.97. That capacity does not restrict the choice to small: OpenAI lists approximate original-runtime VRAM of 2 GB for small, 5 GB for medium, 6 GB for turbo, and 10 GB for large. These are estimates, not faster-whisper allocations or guarantees alongside other running models. [OpenAI model table](https://github.com/openai/whisper#available-models-and-languages)

## Models and downloads

| Model | OpenAI HF checkpoint | faster-whisper-compatible HF download | Published converted repository size |
|---|---|---|---|
| small, multilingual | [openai/whisper-small](https://huggingface.co/openai/whisper-small) | [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small/tree/main) | 486 MB |
| small.en, English only | [openai/whisper-small.en](https://huggingface.co/openai/whisper-small.en) | [Systran/faster-whisper-small.en](https://huggingface.co/Systran/faster-whisper-small.en/tree/main) | 486 MB |
| medium, multilingual | [openai/whisper-medium](https://huggingface.co/openai/whisper-medium) | [Systran/faster-whisper-medium](https://huggingface.co/Systran/faster-whisper-medium/tree/main) | 1.53 GB |
| large-v3-turbo, multilingual | [openai/whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo) | [dropbox-dash/faster-whisper-large-v3-turbo](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/tree/main) | 1.62 GB |

Sizes above are HF file-tree totals in decimal units, excluding Python, runtime libraries, download/cache overhead and recordings. They are disk/download sizes, not runtime RAM/VRAM. OpenAI HF checkpoints use the Transformers format; faster-whisper needs a CTranslate2 conversion. Its `turbo` alias currently maps to the older `mobiuslabsgmbh/faster-whisper-large-v3-turbo` ID, which redirected to `dropbox-dash` during this research. Pin the chosen repository revision for a reproducible installation. [Runtime model mapping and download implementation](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/utils.py)

English and Hindi are listed in Whisper's tokenizer. Use a multilingual checkpoint for both; `.en` is English-only. Mixed Hindi/English speech, accents, technical names and preferred output script need evaluation on the user's recordings; no Hinglish accuracy claim is supported by this research. Use `task="transcribe"` to retain the spoken language rather than request English translation. Turbo is optimized for transcription and is not trained for translation. [Supported languages](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py), [turbo model card](https://huggingface.co/openai/whisper-large-v3-turbo)

## Runtime choice and Windows constraints

**faster-whisper** fits a Python backend: it uses CTranslate2, supports CPU/GPU inference and quantization, and decodes audio through PyAV without a separate system FFmpeg installation. Its README requests CUDA 12 cuBLAS and cuDNN 9 for current GPU builds. Installing a display driver alone does not demonstrate that those runtime DLLs are present. Its published benchmark is on other hardware and must not be presented as this laptop's latency. [Maintainer README](https://github.com/SYSTRAN/faster-whisper)

**Blackwell needs a smoke test.** NVIDIA lists RTX 5070 Ti under compute capability 12.0; compatible kernels/PTX and libraries matter as well as driver support. CTranslate2 previously merged a change disabling INT8 for sm120 after cuBLAS failures, while current master source no longer shows that exclusion. Therefore GPU `float16` is the conservative starting proposal; probe the installed package's supported compute types and transcribe real clips before considering `int8_float16`. CPU `int8` avoids this GPU dependency. No particular wheel/CUDA/cuDNN combination was validated here. [NVIDIA GPU table](https://developer.nvidia.com/cuda/gpus), [Blackwell compatibility guide](https://docs.nvidia.com/cuda/blackwell-compatibility-guide/index.html), [CTranslate2 sm120 fix](https://github.com/OpenNMT/CTranslate2/pull/1937), [current capability implementation](https://github.com/OpenNMT/CTranslate2/blob/master/src/cuda/utils.cc)

**whisper.cpp** is the alternative when native desktop packaging and smaller quantized artifacts matter: C/C++, Windows support, CPU, CUDA and Vulkan paths. It requires its own GGML model format, not CTranslate2 weights. The maintainer's HF repository offers `ggml-small-q5_1.bin` at 190 MB and `ggml-large-v3-turbo-q5_0.bin` at 574 MB. Quantization can change accuracy; compare before selecting it. GPU support and packaging still need testing. [Runtime documentation](https://github.com/ggml-org/whisper.cpp), [maintainer HF files](https://huggingface.co/ggerganov/whisper.cpp/tree/main)

## Minimal file-transcription example — untested

This is an example for a separate environment, not commands executed during the research. It intentionally demonstrates CPU inference first; GPU use additionally needs compatible NVIDIA runtime libraries. Download once online, then load only that local directory. The example does not record microphone audio or insert text into a composer. [faster-whisper API examples](https://github.com/SYSTRAN/faster-whisper#usage), [HF snapshot downloads](https://huggingface.co/docs/huggingface_hub/guides/download)

```powershell
py -3.11 -m venv .venv-dictation
.\.venv-dictation\Scripts\python.exe -m pip install faster-whisper huggingface_hub
```

Save the following as `transcribe_local.py`, and supply a local recording such as `dictation.wav`:

```python
import sys
from pathlib import Path
from huggingface_hub import snapshot_download
from faster_whisper import WhisperModel

model_dir = Path("models/whisper-small").resolve()
if "--download" in sys.argv:
    snapshot_download(
        repo_id="Systran/faster-whisper-small",
        local_dir=str(model_dir),
        allow_patterns=["config.json", "model.bin", "tokenizer.json",
                        "vocabulary.*", "preprocessor_config.json"],
    )
    raise SystemExit("Model downloaded; run again with an audio file.")

model = WhisperModel(str(model_dir), device="cpu", compute_type="int8",
                     local_files_only=True)
segments, info = model.transcribe(sys.argv[1], task="transcribe",
                                  language=None, vad_filter=True,
                                  beam_size=5)
print(" ".join(segment.text.strip() for segment in segments).strip())
```

```powershell
.\.venv-dictation\Scripts\python.exe transcribe_local.py --download
$env:HF_HUB_OFFLINE = "1"
.\.venv-dictation\Scripts\python.exe transcribe_local.py .\dictation.wav
```

For a later GPU trial, replace CPU/INT8 with `device="cuda", compute_type="float16"` after installing compatible libraries. Turbo needs its own downloaded directory and repository ID from the table. Keep the model loaded between dictations to avoid repeated cold-start cost. Compare warm and cold latency, memory, silence, 10-second and multi-minute speech, English, Hindi and mixed speech before selecting a default.

## Interaction implications

Whisper supplies speech-to-text inference. The moving sound bars, recording, pause/resume, cancel, processing state and insertion into an editable prompt are application features. The waveform can come directly from microphone amplitude while recording; it does not require live transcription. Recording then transcribing after the user finishes is a suitable first design for this request. Whisper's standard transcription processes windows; continuously revised live text requires additional buffering and streaming policy. [OpenAI transcription implementation overview](https://github.com/openai/whisper#python-usage), [turbo limitations](https://huggingface.co/openai/whisper-large-v3-turbo#broader-implications)

This note does not establish which server-side model/version Codex currently uses. Public Whisper checkpoints should not be described as the identical downloadable Codex dictation model without direct evidence.

## Current Vellum seam and proposed behavior

Observed in the current working tree on branch `codex/browser-local-preview`:

- `design/Velllum/uploads/Vellum Default Re-designed.html:3934`, `:3991` and `:4200`: the composer microphone button and Ctrl+Shift+D only toggle local `mic` presentation state. `frontend/ui/action-parity.inventory.json:125` explicitly documents that limitation. There is no working Whisper dictation behind that button.
- `design/Velllum/uploads/api/voice.js`: the existing microphone adapter captures PCM WAV at 24 kHz, uses energy-based pause detection for conversational turns, and exposes stop/cancel. It currently retains a short pre-roll before speech and bounds turns. A dictation implementation must deliberately adapt those policies for manual pause/resume and longer recordings rather than inherit automatic submission.
- `backend/agent/contracts/voice.py`, `backend/agent/contracts/capabilities.py`, `backend/agent/voice/session.py`, and `docs/voice.md`: the existing voice contract is a local LFM2.5 direct-audio conversation with spoken replies. It is not a transcript-to-composer transport. Extend the existing voice ownership, typed capability discovery and frontend adapter when adding a dictation mode; keep transcript submission in the canonical text-chat flow.
- The main `.venv` has `torch 2.14.0+cpu`, no CUDA build, and no `faster_whisper` or `ctranslate2` installed. `huggingface_hub` and `sounddevice` are present. Faster-whisper uses CTranslate2, so replacing the app's PyTorch is not itself the GPU-enablement step. Prefer an isolated model environment consistent with the current local voice worker pattern.

Proposed interaction, not implemented:

1. Click Dictate or Ctrl+Shift+D. Request microphone permission and show a timer plus actual microphone level bars.
2. Pause freezes recording while retaining the captured audio; Resume continues it. Pause does not send a chat message. Done ends capture and starts local transcription. Cancel discards the recording and leaves the existing draft intact.
3. Show a processing state, then insert the transcript into the same editable composer without overwriting text the user typed while transcription ran. Keep the selected text model unchanged.
4. Only the normal Send action submits the prompt and starts the Vellum agent. Whisper does not invoke tools or act on the transcript.
5. Retain raw audio only for the bounded capture/transcription lifetime by default. A fully local ASR path does not imply the later selected chat model is local; that step follows the existing model/disclosure settings.

Use the microphone signal for visualization independently of ASR. Web Audio's `AnalyserNode` supplies waveform/level data; application state owns pause, cancel and completion. The standard `MediaRecorder.pause()` is an option if recording uses MediaRecorder; Vellum's current PCM capture requires equivalent explicit state handling. [AnalyserNode](https://developer.mozilla.org/en-US/docs/Web/API/AnalyserNode), [MediaRecorder pause](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/pause)

## Codex model correction and evidence limits

The earlier installed-client investigation found dedicated dictation transport and optional transcript cleanup, but no definitive backend speech model identifier. That is historical static evidence, not a fresh inspection of this installed build. Current official OpenAI documentation confirms editable dictation in the composer and distinguishes it from live Voice, but the pages reviewed do not disclose the private deployed dictation checkpoint. The earlier assertion that this was definitively Whisper was too strong. [Official prompting documentation](https://learn.chatgpt.com/docs/prompting#use-voice-dictation), [Voice versus dictation](https://learn.chatgpt.com/docs/features/voice#chatgpt-voice-and-voice-dictation)

Verification here consisted of primary-source research, current source inspection, `nvidia-smi`, and Python package availability/version inspection. No model download, microphone capture, inference, GPU runtime validation, UI flow or accuracy/latency benchmark ran. Unrelated working-tree changes were preserved. Agent Reach's CLI was unavailable on PATH and its documented Jina fetch returned no content in this sandbox; browser-backed web retrieval provided the cited primary sources instead.
