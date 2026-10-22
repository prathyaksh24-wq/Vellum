# Local dictation model upgrade

Researched 2026-10-19. This note compares published models and records public repository metadata. It does not demonstrate an accuracy improvement on the user's speech or measure a candidate model's latency. No model weights or dependencies were installed by this research task.

## Recommendation

Trial **multilingual large-v3-turbo through the existing faster-whisper runtime, using CUDA FP16**. It is a practical next step from Small when the user values both recognition quality and short transcription waits. This is an engineering recommendation, subject to a real Hindi/English comparison, rather than a measured winner on this laptop.

OpenAI describes Turbo as an optimized large-v3 with a small accuracy tradeoff. Its published comparison places Turbo at 809 million parameters, Medium at 769 million, and Small at 244 million. Turbo's decoder has four layers instead of large-v3's 32. [OpenAI model table](https://github.com/openai/whisper#available-models-and-languages), [OpenAI Turbo model card](https://huggingface.co/openai/whisper-large-v3-turbo)

| Candidate | Published approximate original-runtime VRAM | Published relative speed | Decision |
|---|---:|---:|---|
| Small, existing | 2 GB | 4x | Retain as rollback option |
| Medium, multilingual | 5 GB | 2x | Plausible upgrade, but a less attractive first speed/quality trial |
| large-v3-turbo, multilingual | 6 GB | 8x | Recommended first trial |
| large-v3, multilingual | 10 GB | 1x | Compare later if Turbo's remaining errors justify more latency |

These figures come from OpenAI's English/A100 comparison, relative to Large. They are **not** faster-whisper memory measurements, Hindi results, or promised laptop timings. [OpenAI comparison and caveat](https://github.com/openai/whisper#available-models-and-languages)

Live hardware inspection during this task reported `NVIDIA GeForce RTX 5070 Ti Laptop GPU`, 12,227 MiB total and 11,105 MiB free. This supports trying Turbo without restricting the choice to Medium. Free memory changes with other applications, and a real model startup/transcription remains the acceptance check.

Keep `task="transcribe"` with automatic language identification for the existing multilingual workflow. Turbo is designed for transcription; OpenAI says it is not trained for translation. A larger model can still misrecognize names, unfamiliar words, accents and mixed-language speech. The user's preferred Hindi/English output and spelling need testing on their own phrases. [OpenAI task guidance](https://github.com/openai/whisper#command-line-usage), [model limitations](https://huggingface.co/openai/whisper-large-v3-turbo#performance-and-limitations)

## Compatible downloads and immutable revisions

Public Hugging Face model API metadata was read with `blobs=true` on 2026-10-19. The following are exact revisions and decimal byte counts, excluding `.gitattributes` and `README.md` from runtime totals. They exclude Python, CUDA libraries, caches and download overhead. Disk size does not equal VRAM use.

| CTranslate2 repository | Immutable revision | `model.bin` bytes | Runtime file total bytes |
|---|---|---:|---:|
| `dropbox-dash/faster-whisper-large-v3-turbo` | `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf` | 1,617,884,929 | 1,621,665,983 |
| `Systran/faster-whisper-medium` | `08e178d48790749d25932bbc082711ddcfdfbc4f` | 1,527,906,378 | 1,530,571,735 |
| `Systran/faster-whisper-large-v3` | `edaa852ec7e145841d8ffdb056a99866b5f0a478` | 3,087,284,237 | 3,090,835,702 |

Sources: [Turbo metadata API](https://huggingface.co/api/models/dropbox-dash/faster-whisper-large-v3-turbo?blobs=true), [Medium metadata API](https://huggingface.co/api/models/Systran/faster-whisper-medium?blobs=true), [large-v3 metadata API](https://huggingface.co/api/models/Systran/faster-whisper-large-v3?blobs=true). To reproduce later, resolve the immutable revision rather than trusting a subsequently changed `main` branch.

The recommended pinned Turbo runtime files are:

| File | Bytes |
|---|---:|
| `config.json` | 2,263 |
| `model.bin` | 1,617,884,929 |
| `preprocessor_config.json` | 340 |
| `tokenizer.json` | 2,710,337 |
| `vocabulary.json` | 1,068,114 |

The converter owner states these are FP16 CTranslate2 weights converted from `openai/whisper-large-v3-turbo`. Use this format with faster-whisper rather than downloading the original Transformers weights. [Pinned converter model card](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/blob/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf/README.md), [pinned file tree](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/tree/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf)

## Existing runtime compatibility and integration checks

The installed dependency file pins faster-whisper 1.2.1, CTranslate2 4.8.3, huggingface-hub 2.2.0 and PyAV 16.1.0. Faster-whisper 1.2.1 already recognizes `large-v3-turbo` and `turbo`; those aliases point at `mobiuslabsgmbh/faster-whisper-large-v3-turbo`, which redirected to the canonical `dropbox-dash` repository during this research. Prefer the explicit canonical repository plus immutable revision. A runtime package upgrade is not indicated by the model selection alone. [Versioned model mapping and download allowlist](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/utils.py)

Two current Vellum worker details require attention before selecting Turbo:

1. `backend/agent/voice/whisper_worker.py` warms the encoder with an `80 x 3000` feature array. Turbo's pinned preprocessor specifies **128** mel features. Build the warm-up shape from the actual extractor, for example its `mel_filters.shape[0]`, rather than retaining Small's hardcoded width. The installed faster-whisper `FeatureExtractor` does not expose a `feature_size` attribute. [Pinned Turbo preprocessor](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/resolve/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf/preprocessor_config.json), [versioned feature extractor](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/feature_extractor.py)
2. The worker's ready event currently reports `openai/whisper-small`. Update the reported model identity with the selected local artifact so status remains truthful. The download helper also currently pins only Small; preserve explicit provenance and offline `local_files_only=True` when adding Turbo. These are current local-code observations, not upstream model requirements.

Use the existing worker, capture flow, cancellation and composer insertion path. Start with CUDA `float16`, already used for Small, and retain CPU `int8` fallback without promising equivalent responsiveness. Faster-whisper documents both modes. [Maintainer usage examples](https://github.com/SYSTRAN/faster-whisper#faster-whisper)

## Acceptance evidence still needed

Measure cold startup and repeated warm transcription separately. Compare the same short English, Hindi and mixed Hindi/English clips between Small and Turbo, including music commands, proper names, and the specific troublesome words the user noticed. Confirm the returned transcript is the text actually submitted by the composer. Music routing must be checked separately: increasing ASR size cannot establish that an identical transcript will use the correct music capability.

This research did not record the microphone, run candidate inference, change live application configuration, or prove improved spelling. Retain Small until the larger model passes the worker smoke test and the user evaluates recognition on their speech.
