# Voice Model Landscape for Vellum

**Research snapshot:** 2026-09-29
**Decision target:** natural two-way voice for Vellum, including interruptions, pauses, backchannels, long-running tools, and subagent work
**Target machine:** Windows laptop, RTX 5070 Ti Laptop GPU with 12,227 MiB VRAM (about 11.94 GiB), reportedly about 16 GB system RAM, and an installed Gemma model/download around 7.5 GB. The GPU total was verified live; system RAM and Gemma's resident footprint were not. The download size is not itself measured VRAM usage—resident memory depends on quantization, offload, context, and runtime overhead.

## Executive answer

1. **GPT-Live-1 is a paid API product.** OpenAI charges **$0.05 per active session minute**, billed per second. Silence, user speech, assistant speech, and time spent waiting for a delegated backend all count; the backend model and tools are billed separately. ChatGPT plan allowances do not provide an embeddable Vellum API entitlement. [OpenAI pricing](https://platform.openai.com/pricing) · [cost guide](https://developers.openai.com/api/docs/guides/voice-latency-cost) · [GPT-Live-1 announcement](https://openai.com/index/introducing-gpt-live-1-in-the-api/)

2. **No downloadable model is presently on par with GPT-Live-1 as a complete Vellum solution on this laptop.** Several open models genuinely listen and speak simultaneously, but the credible ones need roughly 10–24+ GB VRAM, are mostly English or English/Chinese, and generally lack GPT-Live-1's clean foreground-voice/background-agent delegation model. If the installed Gemma quantization occupies roughly 7.5 GB when loaded, only about 4.4 GB of nominal VRAM remains before display, CUDA, KV-cache, codec, and application overhead. None of the serious full-duplex models can coexist with it in that case.

3. **The only plausible local full-duplex experiment is MiniCPM-o 4.5 GGUF, with Gemma unloaded.** OpenBMB lists about **10 GB GPU memory** for GGUF and 11 GB for AWQ, and provides a Windows llama.cpp path. That is a laboratory fit, not a safe production fit: the official lossless service needs over 28 GB, the quantized runtime leaves little headroom, speech is English/Chinese, and the installed Gemma cannot stay GPU-resident alongside it. [MiniCPM model zoo](https://github.com/OpenBMB/MiniCPM-V) · [official deployment requirements](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/main/docs/en/deployment.md) · [GGUF model card](https://huggingface.co/openbmb/MiniCPM-o-4_5-gguf)

4. **The strongest cloud alternatives are real competitors, but they solve different problems.** Grok Voice Think Fast 2.0 is the clearest direct full-duplex rival; Gemini Live, Qwen3.8 Omni Realtime, and Nova 2 Sonic are excellent native speech services with barge-in and tools, but their public documentation describes turn/semantic-VAD interruption rather than GPT-Live-style continuous cooperative overlap. ElevenAgents, Deepgram Voice Agent, and Sarvam Voice Agents are managed cascades: they can feel polished, but they are not one full-duplex speech model.

5. **For Vellum, the decisive architectural question is who remains the brain.** If Vellum's runtime, tools, permissions, memory, and subagents must remain authoritative, prefer a replaceable voice-front-end adapter. GPT-Live-1 was explicitly designed for that split. Among alternatives, ElevenAgents custom LLM and Deepgram BYO LLM are the cleanest managed shells; Sarvam's raw STT/TTS APIs are the strongest Indic speech components. If a cloud voice model is allowed to own the foreground conversation and call Vellum as a tool, Gemini Live, Qwen3.8 Omni Realtime, Grok Voice, and Nova 2 Sonic become stronger candidates.

## What “full duplex” means here

The market uses *realtime*, *bidirectional*, *speech-to-speech*, and *full duplex* loosely. They are not interchangeable.

| Class | What actually happens | Typical behavior |
|---|---|---|
| **Continuous full duplex** | The model keeps processing incoming audio while generating outgoing audio. Concurrent user speech can change whether it continues, pauses, backchannels, or stops. | Natural “mm-hmm,” overlap, mid-sentence redirection, and fewer hard turn boundaries. GPT-Live-1, PersonaPlex/Moshi, MiniCPM-o 4.5 duplex, Realtime-Venus, Raon, and Grok's documented Voice API belong here. |
| **Native/end-to-end realtime with barge-in** | One service understands audio and produces audio, while a turn detector or semantic VAD decides when to respond. User speech during playback normally cancels the current response. | Fast and natural, but “mic remains open” is not proof that the model reasons over both sides continuously. Gemini Live, Qwen Omni Realtime, and Nova Sonic fit here based on public documentation. |
| **Speech-native input plus synthesized output** | The conversational model consumes audio directly, but output passes through a speech renderer. | Retains tone better than ASR-first systems, but not necessarily full-duplex. Ultravox is the clearest example. |
| **Cascaded voice-agent platform** | Streaming STT → text LLM/agent → streaming TTS, coordinated by an orchestration layer. | Can implement VAD, barge-in, fillers, and tool calls, but pauses, hums, prosody, and overlap may be reduced to control signals or text. ElevenAgents, Deepgram Voice Agent, Hume EVI 4-mini, and Sarvam Voice Agents are in this category. |
| **Component only** | STT-only, TTS-only, VAD-only, or a turn detector. | Useful in a custom Vellum pipeline, but not a standalone answer to “talk naturally with Vellum.” |

**Barge-in is not full duplex.** A cascade can keep the microphone open, detect speech, clear its playback buffer, and cancel TTS. That is good interruption handling, but it does not mean the speaking model understood a quiet “yeah,” a hesitation, laughter, or a correction while it was talking.

## The laptop constraint is decisive

The GPU has about 11.94 GiB total VRAM. If Gemma occupies about 7.5 GB, nominal free capacity is only about **4.4 GB**, and usable capacity is lower once Windows' display allocation, CUDA context, KV cache, audio codecs, buffers, and the desktop app are included.

Consequences:

- **PersonaPlex/Moshi cannot fit.** Kyutai's official PyTorch runtime requires **24 GB**, has no quantization support there, and does not officially support Windows. [Moshi repository](https://github.com/kyutai-labs/moshi)
- **MiniCPM-o 4.5 cannot coexist with Gemma.** OpenBMB lists 10 GB for GGUF and 11 GB for AWQ. The official PyTorch service uses about 21.5 GB after initialization and requires a GPU with more than 28 GB VRAM. [OpenBMB model zoo](https://github.com/OpenBMB/MiniCPM-V) · [deployment guide](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/main/docs/en/deployment.md)
- **Even an apparent 5 GB Q4 model file is not a 5 GB application.** The official GGUF repository has a 5.03 GB Q4_K_M language-model file, but the complete omni runtime also loads audio/vision/TTS/token-to-wave components and working memory; OpenBMB's stated runtime budget is 10 GB. [GGUF files](https://huggingface.co/openbmb/MiniCPM-o-4_5-gguf/tree/main)
- **System-RAM offload is not a comfortable escape hatch.** Windows plus Vellum plus a 7.5 GB local model already puts pressure on 16 GB RAM. Moving a second model's weights/KV cache across CPU and GPU would trade an out-of-memory failure for latency and paging, exactly where a voice loop is least tolerant.
- **A local voice front end and local Gemma can coexist only if the voice layer is much smaller and cascaded.** That means lightweight STT/VAD/TTS components, not one of today's best full-duplex models. It can be private and useful, but it will not match GPT-Live-1's conversational dynamics.

## Local and open-weight landscape

### 1. MiniCPM-o 4.5 — the only credible experiment on this machine

MiniCPM-o 4.5 is a 9B end-to-end omni model with explicit audio and audio-video full-duplex modes. Its official protocol continuously accepts one-second chunks while returning listen/text/audio events; the model itself decides when to listen or speak rather than relying on a separate VAD. It supports simultaneous input/output, interruption, and proactive interaction. [official repository](https://github.com/OpenBMB/MiniCPM-V) · [duplex protocol](https://github.com/OpenBMB/MiniCPM-o-Demo/blob/main/docs/en/api/duplex.md)

- **Speech languages:** English and Chinese. This is not an Indic solution.
- **License:** Apache-2.0. [model card](https://huggingface.co/openbmb/MiniCPM-o-4_5)
- **Windows:** official GGUF/llama.cpp instructions include WinGet and the demo links Windows desktop installers. The official high-fidelity PyTorch deployment remains Linux/CUDA. [GGUF card](https://huggingface.co/openbmb/MiniCPM-o-4_5-gguf) · [demo](https://github.com/OpenBMB/MiniCPM-o-Demo)
- **Memory:** 19 GB BF16, 11 GB AWQ, and 10 GB GGUF in OpenBMB's model zoo; the maintained PyTorch server requires over 28 GB and reports about 21.5 GB resident per worker.
- **Tools:** no documented native function-call or asynchronous Vellum-delegation channel in duplex mode. It can be wrapped by an external controller, but that controller must infer a delegation request from speech/text and safely reconcile interruption and cancellation.
- **Verdict:** worth a one-off GGUF test only after unloading Gemma. It is too tight to promise stable Windows laptop operation and cannot simultaneously serve as Vellum's voice layer while Gemma remains the local reasoning brain.

### 2. NVIDIA PersonaPlex 7B / Kyutai Moshi — excellent dynamics, wrong hardware

PersonaPlex is a Moshi-family dual-stream model that explicitly listens and speaks concurrently. NVIDIA describes interruption, overlap, rapid-turn, backchannel, and pause behavior, and publishes FullDuplexBench results. It is English-in/English-out. [PersonaPlex model card](https://huggingface.co/nvidia/personaplex-7b-v1)

- **License:** NVIDIA Open Model License, with additional CC-BY-4.0 information; NVIDIA marks the model ready for commercial use.
- **Official platform:** Linux on A100/H100; the model was tested on A100 80 GB.
- **Practical runtime:** the upstream Moshi PyTorch path needs 24 GB VRAM, does not support quantization there, and says Windows may work but is not officially supported. [Moshi repository](https://github.com/kyutai-labs/moshi)
- **Tools:** Kyutai itself says Moshi does not yet match text models on function calling, stronger reasoning, or in-context learning. [Kyutai Unmute prompt/source](https://github.com/kyutai-labs/unmute/blob/main/unmute/llm/system_prompt.py)
- **MoshiRAG:** adds asynchronous retrieval through an OpenAI-compatible backend, but still needs 24 GB for the voice front end, a reference encoder, and another GPU if the retrieval LLM is local; delays over three seconds hurt the experience. It is not a general Vellum tool runtime. [MoshiRAG](https://github.com/kyutai-labs/moshi-rag)
- **Verdict:** a strong research reference for conversational timing, not a viable RTX 5070 Ti Laptop deployment.

### 3. Realtime-Venus — the best open architectural reference for Vellum

Realtime-Venus, released in September 2026, combines 9B full-duplex audio/omni checkpoints with an asynchronous Harness. It continuously listens while speaking, distinguishes acknowledgments/background speech from real interruptions, can emit delegated work, lets the task continue in the background, and returns the result to the originating conversation for spoken delivery. The public demo includes a Codex task backend. [official repository](https://github.com/inclusionAI/Realtime-Venus) · [project page](https://realtime-venus.github.io/) · [model card](https://huggingface.co/inclusionAI/Realtime-Venus)

- **Why it matters:** its dual-loop split—foreground conversation plus background execution—is the closest open design analogue to what Vellum needs.
- **Languages:** English and Chinese tags/checkpoints; no broad Indic claim.
- **License:** Apache-2.0 for the repository/checkpoint, subject to listed upstream terms.
- **Hardware/platform:** BF16 9B; the online duplex demo requires at least an A100 and the installer targets Linux/CUDA.
- **Maturity:** a research/demo release only about two weeks old at this snapshot. Its own published delegation score measures routing decisions, not end-to-end task success.
- **Verdict:** borrow the protocol and lifecycle ideas; do not plan to run these weights on the laptop.

### 4. Raon-SpeechChat-9B — true duplex, English-only, noncommercial

KRAFTON's Raon-SpeechChat-9B supports simultaneous listening and speaking, backchannels, pause handling, and barge-in. [model card](https://huggingface.co/KRAFTON/Raon-SpeechChat-9B) · [repository](https://github.com/krafton-ai/Raon-Speech)

- **Language:** English.
- **Weights license:** CC-BY-NC-4.0, so it is not suitable for a commercial Vellum distribution without separate permission.
- **Hardware:** the project recommends at least 16 GB VRAM and a CUDA/Docker deployment; the checkpoint is about 19.5 GB on Hugging Face.
- **Tools:** no first-class Vellum-style delegation interface.
- **Verdict:** does not fit the GPU, Windows path, language goals, or commercial requirements.

### 5. Other credible research systems

| Model | What is credible | Why it is not the answer for this laptop |
|---|---|---|
| **Lychee-FD** | Apache-2.0 end-to-end full duplex with explicit listen/respond/stop control and early-exit interruption. [official repository](https://github.com/HITsz-TMG/Lychee-FD) | Custom patched vLLM/CUDA stack; reference deployment can split token-to-wave and model across GPUs. No supported Windows laptop configuration or native tool channel. |
| **ELLSA** | 18B full-duplex multimodal model spanning vision, speech, text, and embodied action. [SALMONN repository](https://github.com/bytedance/SALMONN) · [model card](https://huggingface.co/tsinghua-ee/ELLSA) | Roughly 37 GB of checkpoint files, research-stage release, and its “action” modality is not arbitrary Vellum function calling. |
| **DuplexSLA** | Promising native full-duplex research with a structured action stream for planning/tool calls. [official repository](https://github.com/hyzhang24/DuplexSLA) | Inference code/checkpoints were still marked forthcoming at this snapshot, so it is not installable or evaluable. |
| **LFM2.5-Audio-1.5B** | A small end-to-end audio foundation model with audio input and speech output, plus official GGUF/CPU support. [model card](https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B) | It is English and turn-based/interleaved rather than continuously full duplex, so it is the easiest laptop-sized direct-audio experiment but does not meet Vellum's interruption/overlap requirement. Its LFM Open License is also only freely commercial below the stated $10M annual-revenue threshold. [license](https://huggingface.co/LiquidAI/LFM2.5-Audio-1.5B/blob/main/LICENSE) |
| **NVIDIA NemotronLabs VoiceChat 11B** | End-to-end full-duplex speech with native tool calling and roughly 450 ms reported latency, making it unusually aligned with Vellum's agent/tool use case. [model card](https://huggingface.co/nvidia/NVIDIA-NemotronLabs-VoiceChat-11B) | The supported path is Linux on A100/H100/H200/B100/B200/RTX 6000-class hardware and the published test platform is H100, not a 12 GB Windows laptop. |
| **Qwen3-Omni-30B-A3B** | Apache-2.0 native end-to-end omni model with streaming speech; 119 text languages, 19 speech-input languages, and 10 speech-output languages. [official repository](https://github.com/QwenLM/Qwen3-Omni) | It is turn-oriented streaming, not documented continuous full duplex. Official BF16 minimum is 78.85 GB for the instruct/talker configuration with a 15-second video input. Urdu is the only Indian speech-input language in the published 19-language list; output has no Indian language. [memory table](https://github.com/QwenLM/Qwen3-Omni#usage-tips-recommended-reading) |
| **Qwen2.5-Omni 3B/7B** | Smaller end-to-end audio/vision-to-speech models with streaming output. [official repository](https://github.com/QwenLM/Qwen2.5-Omni) | “Realtime streaming output” is not the same as simultaneous listen/speak. The 3B model's published BF16 footprint is already above this machine's practical budget, and it is not a modern full-duplex replacement. [3B model card](https://huggingface.co/Qwen/Qwen2.5-Omni-3B) |
| **Freeze-Omni / Fun-Audio-Chat** | Useful low-latency speech-language research; Fun-Audio-Chat demonstrates speech function calling. [Freeze-Omni](https://github.com/VITA-MLLM/Freeze-Omni) · [Fun-Audio-Chat](https://github.com/FunAudioLLM/Fun-Audio-Chat) | Neither has a supported, validated 12 GB Windows full-duplex deployment. Function calling in a demo does not supply Vellum's permissions, cancellation, subagent state, or long-running task delivery. |

### Local conclusion

There are now multiple **real** open full-duplex models; this is no longer a category with only Moshi. But “open weights exist” and “works as Vellum on this laptop” remain far apart. The laptop can test quantized MiniCPM-o 4.5 only by evicting Gemma. PersonaPlex, Realtime-Venus, Raon, Lychee-FD, ELLSA, and full Qwen Omni configurations are hardware or platform mismatches. None combines broad Indic speech, stable Windows support, low enough memory, commercial terms, and a production-grade Vellum delegation seam.

## Cloud landscape

### Baseline: OpenAI GPT-Live-1

GPT-Live-1 is a foreground voice model designed to listen and speak at the same time. It can continue the live conversation while delegating deeper reasoning and tool work to an OpenAI or third-party backend. OpenAI specifically documents backchannels, pauses, silence/background-noise handling, mid-conversation redirection, and client delegation. [GPT-Live overview](https://openai.com/index/introducing-gpt-live/) · [API launch](https://openai.com/index/introducing-gpt-live-1-in-the-api/) · [getting started](https://developers.openai.com/api/docs/guides/live)

- **Price:** $0.05 per active minute for the voice layer, plus backend/tool usage.
- **Vellum fit:** strongest conceptual fit because the voice model can remain the conversation specialist while Vellum remains the authoritative worker/runtime.
- **Tradeoff:** microphone audio and delegated context go to OpenAI; a local-first product must show an explicit cloud indicator/approval and minimize what it sends.

### Native/direct cloud speech models

| Provider/model | Architecture and conversational behavior | Tools and Vellum integration | Languages | Current public price | Assessment |
|---|---|---|---|---|---|
| **xAI Grok Voice Think Fast 2.0** | xAI explicitly markets full-duplex speech-to-speech, sub-second latency, natural turn-taking, and barge-in. Its announcement reports 95.1% on Conversational Dynamics Full Duplex Bench versus 95.7% for GPT-Realtime-2.1; that is a vendor-published comparison, not proof against GPT-Live-1. [Voice API](https://x.ai/api/voice) · [Think Fast 2.0](https://x.ai/news/grok-voice-think-fast-2) | Native tool calling; Agent Builder supports APIs, MCP-style integrations, SIP, and multi-tool workflows. Grok still owns the foreground intelligence; Vellum would be exposed as tools rather than being the direct response generator. | 25+ claimed; official examples include Hindi and Bengali, but far less Indic breadth than Gemini/Qwen/Sarvam. | **$0.08/min** for Think Fast 2.0. The $0.05 landing-page figure refers to the deprecated 1.0 floor; current model/pricing docs and the 2.0 announcement say $0.08. [pricing](https://docs.x.ai/developers/pricing) | **Closest direct competitor on paper.** It deserves a same-microphone A/B trial, but is not yet demonstrated to equal GPT-Live-1's delegated-background-work design. |
| **Google Gemini 3.8 Live** | Native low-latency audio-to-audio over a persistent WebSocket; automatic/configurable VAD, barge-in, affective dialogue, proactive audio, and tone-sensitive speech. Public docs establish excellent native speech and interruption behavior, not continuous cooperative overlap/backchannel generation equivalent to GPT-Live. [Live API](https://ai.google.dev/gemini-api/docs/live-api) · [capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities) | Particularly strong asynchronous function calling. Non-blocking tool results can be scheduled `SILENT`, `WHEN_IDLE`, or `INTERRUPTED`, which maps well to background Vellum work. An interruption can cancel pending model function calls, so Vellum must separately decide whether the underlying task is canceled. | 99 documented languages, including Assamese, Bengali, Gujarati, Hindi, Kannada, Malayalam, Marathi, Odia, Punjabi, Sindhi, Tamil, Telugu, Urdu, and Nepali. | Audio input **$3/M tokens** (about $0.005/min) and output **$12/M** (about $0.018/min), plus text/context. A one-input-minute plus one-output-minute floor is about $0.023, but history is reprocessed and can compound. [pricing](https://ai.google.dev/gemini-api/docs/pricing) | **Best broad-language native alternative** and strong tool scheduler. Use an A/B test before calling it full-duplex-equivalent. |
| **Alibaba Qwen3.8 Omni Flash Realtime** | End-to-end streaming audio/video input with text/audio output, semantic VAD, interruption, 120-minute sessions, and a large context. The service is a native realtime turn model; public docs do not claim GPT-Live-style simultaneous cooperative speaking/listening. [model page](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen3-8-omni-flash-realtime) · [realtime guide](https://www.alibabacloud.com/help/en/model-studio/realtime) | Custom function calling and remote MCP are native. The new Apache-2.0 **Qwen Live Harness** can delegate background work to Qwen Code, Codex, Claude Code, Gemini CLI, or ACP backends while conversation continues—an unusually close match to Vellum's desired control plane. The released desktop Host is currently macOS; the daemon would need a Vellum/Windows host adapter. [Qwen Live Harness](https://github.com/QwenLM/Qwen-Live-Harness) | Recognition: 113 languages/dialects, including major Indian languages. Speech output: 36 languages/dialects; published voices include Hindi and Urdu, but not the full Indic set. [voice list](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/omni-voice-list) | Singapore: audio input **$0.93/M**, audio output **$1.87/M**, text/video input $0.23/M, text output $0.70/M. At the documented 7 input audio tokens/s and 12.5 output tokens/s, one full minute in plus one full minute out is roughly **$0.0018 in audio tokens**, before text and repeatedly billed history. [pricing/model card](https://docs.modelstudio.console.alibabacloud.com/en/model-studio/qwen3-8-omni-flash-realtime) | **Most interesting new value/architecture candidate.** Very new, region/cloud-dependent, and not yet a turnkey Windows Vellum integration. |
| **Amazon Nova 2 Sonic** | Unified speech-to-speech foundation model through Bedrock bidirectional streaming, with intelligent turn-taking, prosody, barge-in, context preservation, and automatic language switching. It is native speech-to-speech but public docs describe interruption-based turns rather than continuous overlap. [overview](https://docs.aws.amazon.com/nova/latest/nova2-userguide/using-conversational-speech.html) · [getting started](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-getting-started.html) | Function calling, RAG, and asynchronous/parallel tools can continue while the service listens and responds. AWS's production controls are strong, but the bidirectional Bedrock API and credential setup are heavier than a browser-direct WebRTC provider. [async tools](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-async-tools.html) | English variants including India, French, Italian, German, Spanish, Portuguese, and Hindi. [language support](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-language-support.html) | Official examples list $0.003/1K speech-input tokens and $0.012/1K speech-output tokens; an AWS post estimates about **$0.27/hour of input audio**, with output depending on speaking time. Always confirm the live Bedrock regional table. [AWS cost example](https://aws.amazon.com/blogs/machine-learning/live-meeting-assistant-with-amazon-transcribe-amazon-bedrock-and-strands-agents/) | **Strong production/Hindi option**, especially for an AWS deployment; less Indic breadth and more infrastructure than Gemini/Qwen. |

### Managed voice-agent shells and cascades

| Provider | What it really is | Pauses, interruption, and fillers | Vellum integration | Languages | Price | Assessment |
|---|---|---|---|---|---|---|
| **ElevenLabs ElevenAgents** | Managed cascade: Scribe realtime STT → chosen/custom LLM → conversational ElevenLabs TTS. It is not a single full-duplex speech model. [overview](https://elevenlabs.io/docs/eleven-agents/overview) | Prosody-aware turn detection; Eager/Normal/Patient modes; silence timeout; soft fillers such as “hmm”; configurable interruption and ignored acknowledgment terms. [conversation flow](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow) | Excellent seam for keeping Vellum as the brain: point it at an OpenAI-compatible `/v1/chat/completions` or `/v1/responses` SSE server; also supports client tools, webhooks, MCP, and agent transfers. The custom server generally must be reachable from ElevenLabs cloud. [custom LLM](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm) | 31 standard agent languages; expressive modes and underlying speech products advertise broader coverage. Hindi/Hinglish is explicit, but validate each target language and code-switch pattern. | Free 15 min; paid allocations work out near **$0.08/min** overage, with LLM and telephony separate. [pricing](https://elevenlabs.io/pricing/agents) | **Best polished managed voice shell if Vellum must generate the words.** It can feel excellent, but a cascade cannot fully preserve every hum/overlap/prosodic cue. |
| **Deepgram Voice Agent** | Single-WebSocket managed cascade: Flux/Nova STT + LLM orchestration + Aura/Flux TTS. Deepgram explicitly describes the components, so it should not be mislabeled end-to-end. [product](https://deepgram.com/product/voice-agent-api) | Semantic turn detection, barge-in, speculative turn confirmation/cancellation, and precise “text actually heard” reconciliation. Injected messages can wait, queue, or interrupt during long tools. [barge-in](https://developers.deepgram.com/voice-agent/optimize/audio-preprocessing-barge-in) · [function-call lifecycle](https://developers.deepgram.com/docs/voice-agent-function-call-request) | Strong BYO LLM/custom OpenAI-compatible endpoint, client/server functions, multiple agents, and progress injection. This is the cleanest controllable shell after ElevenAgents. | STT supports English plus nine languages including Hindi. Native TTS is English-centric (or seven Aura-2 languages) and has no Hindi output, so Hindi needs third-party TTS. [STT languages](https://developers.deepgram.com/docs/models-languages-overview) · [TTS languages](https://developers.deepgram.com/docs/tts-models-languages-overview) | Standard **$0.075/min** ($4.50/hr); BYO configurations can reach **$0.05/min**, with plan/model differences. [pricing/product](https://deepgram.com/product/voice-agent-api) | **Best orchestration/observability shell**, weaker than Sarvam or Gemini for Indian speech output. |
| **Hume EVI 3 / EVI 4-mini** | EVI 3 uses Hume's native speech-language model; EVI 4-mini requires a supplemental LLM and speech layer. Neither public interface is documented as continuous full duplex. [version guide](https://dev.hume.ai/docs/speech-to-speech-evi/configuration/evi-version) | Strongest specialist in emotion, tone, timing, and vocal nuance. Interruption minimum is configurable 50–2000 ms and end-of-turn silence 500–3000 ms; the client must also clear queued audio on interruption events. [interruption](https://dev.hume.ai/docs/speech-to-speech-evi/configuration/interruption) · [audio guide](https://dev.hume.ai/docs/speech-to-speech-evi/guides/audio) | Supplemental/custom OpenAI-compatible LLM, RAG, webhooks, and tools. Tools rely on the supplemental LLM and parallel function calls are not supported. [tools](https://dev.hume.ai/docs/speech-to-speech-evi/configuration/tools) · [custom LLM](https://dev.hume.ai/docs/speech-to-speech-evi/guides/custom-language-model) | EVI 3: English/Spanish. EVI 4-mini: English, Japanese, Korean, Spanish, French, Portuguese, Italian, German, Russian, Hindi, Arabic. | Roughly **$0.04–$0.075/min** by tier for EVI 3; external managed LLM usage can add cost. [pricing](https://www.hume.ai/pricing) | **Best for emotional sensitivity**, but only Hindi among Indian languages and a weaker parallel-tool story. |
| **Sarvam Voice Agents** | Explicit cascade: Saaras STT → LLM → Bulbul TTS with VAD/orchestration. Sarvam's own runtime documentation shows these stages. [runtime](https://docs.sarvam.ai/conversations/build/run-time) | Barge-in, holds, long-silence nudges, voicemail behavior, pronunciation, and language switching. Its raw streaming TTS has no in-band cancel; the client stops playback, closes the socket, and reconnects. [streaming TTS/barge-in](https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket) | Hosted Voice Agents support HTTP tools, but an arbitrary Vellum custom reasoning endpoint is not documented as a first-class replacement. For Vellum ownership, use raw Saaras streaming STT and Bulbul streaming TTS around Vellum instead of adopting the whole hosted agent. | Hosted agents cover English plus 11 Indian languages; raw Saaras v4 covers 22 Indian languages plus English, while Bulbul v3 outputs English plus 10 major Indian languages. [Saaras](https://docs.sarvam.ai/api/getting-started/models/saaras) · [Bulbul](https://docs.sarvam.ai/api/getting-started/models/bulbul) | Hosted Voice Agents **₹3.50/min**. Raw STT **₹30/hour**, Bulbul v3 **₹30/10K characters**, LLM separate; ₹100 signup credit. [launch/pricing](https://www.sarvam.ai/epoch/summary) · [API pricing](https://docs.sarvam.ai/api/getting-started/pricing) | **Best Indian-language specialist.** Use raw speech APIs if Vellum must remain the agent; use hosted Voice Agents for telephony/business flows where Sarvam may own orchestration. |
| **Ultravox Realtime** | Speech-native input model: it processes audio directly without an ASR transcript, while the hosted platform supplies output voice and agent runtime. It is not advertised as continuous listen-and-speak full duplex. [architecture](https://docs.ultravox.ai/gettingstarted/how-ultravox-works) | Multi-layer VAD distinguishes thoughtful pauses from end-of-turn; default endpoint delay 384 ms and minimum interruption 90 ms. [VAD](https://docs.ultravox.ai/noise/understanding-vad) | HTTP/client/WebSocket tools, RAG, call stages, and speculative read-only “precomputable” tools. Longer normal tools freeze the conversational response; Threads are the async escape hatch. [async tools](https://docs.ultravox.ai/tools/async-tools) | 26 languages including Hindi and Tamil. [overview](https://docs.ultravox.ai/overview) | First 30 min free, then **$0.05/min**, TTS included. [pricing](https://www.ultravox.ai/pricing) | **Strong lesser-known native-input platform**, but hosted Ultravox remains the conversational brain rather than a transparent Vellum voice codec. |

## STT-only and TTS-only products are not GPT-Live alternatives

Several excellent products are useful building blocks but should not be compared as if they were complete duplex models:

- **Sarvam Saaras v4** is STT-only: 22 Indian languages plus English, streaming, code-mixing modes, and Indian telephony support. **Bulbul v3** is TTS-only: English plus 10 major Indian languages, with streaming first audio and strong Indic pronunciation. Combining them with Vellum creates a cascade, not a native speech model. [Saaras](https://docs.sarvam.ai/api/getting-started/models/saaras) · [Bulbul](https://docs.sarvam.ai/api/getting-started/models/bulbul)
- **Deepgram Flux/Nova** are STT/turn models and **Aura/Flux TTS** are output renderers. Deepgram Voice Agent is the orchestrated product that connects them. [STT overview](https://developers.deepgram.com/docs/models-languages-overview) · [TTS overview](https://developers.deepgram.com/docs/tts-models-languages-overview)
- **ElevenLabs Scribe and Eleven v3 conversational TTS** are components under ElevenAgents; the surrounding runtime supplies turn-taking, tools, and interruption behavior.
- **Kyutai Unmute** is deliberately a cascade that wraps any text LLM with streaming STT/TTS. Kyutai presents this as the way to regain text-model reasoning/function capability that Moshi lacks. Its official self-hosting stack is multi-service and GPU-heavy, not a small Windows laptop package. [Unmute](https://github.com/kyutai-labs/unmute)
- A home-grown local pipeline using a small STT model, semantic turn detector, Vellum/Gemma, and lightweight TTS can fit by moving some components to CPU. It can support cancel-on-speech and intentional silence. It will still lose some paralinguistic information and cannot honestly promise GPT-Live-level overlap/backchannel behavior.

## Comparative verdict

| Question | Answer |
|---|---|
| Is any **local** model genuinely on par with GPT-Live-1 for Vellum on this laptop? | **No.** MiniCPM-o 4.5 is the closest installable experiment, but only with Gemma unloaded, little memory headroom, English/Chinese speech, and no native Vellum delegation contract. |
| Is any **cloud** model plausibly on par in raw conversation? | **Grok Voice Think Fast 2.0 is the only current service that explicitly claims the same full-duplex class.** Its public results are promising, but not a controlled GPT-Live-1 comparison. Gemini/Qwen/Nova may match or win on some latency, price, language, or intelligence axes, but their documented interaction model is barge-in/semantic-turn based. |
| Which alternative has the best Indian-language coverage? | **Sarvam** for Indian speech specialization; **Gemini Live** for broad native conversational coverage; **Qwen3.8 Omni Realtime** for very broad recognition plus Hindi/Urdu output. |
| Which best preserves Vellum as the brain? | **GPT-Live-1 client delegation** first; **ElevenAgents custom LLM** or **Deepgram custom think endpoint** among managed alternatives; **Sarvam raw STT/TTS** for an Indic cascade. |
| Which is cheapest on published usage rates? | **Qwen3.8 Omni Realtime** has an exceptionally low token rate, but repeated-history billing, region availability, very new tooling, and integration work matter. Sarvam raw APIs are also inexpensive for Indic cascades. Cheapest does not mean best conversational match. |
| Which open project should guide Vellum's design? | **Realtime-Venus** for the dual-loop delegation lifecycle, even though its weights cannot run here. |

## Recommended Vellum direction

### Recommended product architecture

Keep one provider-neutral `VoiceSession` boundary around the existing Vellum runtime:

```text
microphone / echo control
        │
        ▼
replaceable live-voice adapter
        │  speech events, partial meaning, interruption, playback position
        ▼
Vellum conversation coordinator
        ├── canonical local memory/context
        ├── permission and disclosure broker
        ├── local Gemma or chosen reasoning provider
        ├── tools/subagents/background jobs
        └── result scheduler: silent / when-idle / interrupt
        │
        ▼
voice adapter output / captions / UI state
```

The adapter must not become a second agent runtime, tool registry, memory store, or authority. It should expose capabilities such as `continuous_duplex`, `barge_in`, `semantic_pause`, `backchannel`, `async_result_delivery`, `languages`, and `cloud_audio` so provider differences remain explicit.

### Suggested evaluation order

1. **GPT-Live-1 reference lane.** It is the feature target and cleanest delegation fit. The known voice-layer price is $0.05/min; cap sessions and close idle sessions because silence/backend wait is billable.
2. **Qwen3.8 Omni Realtime challenger lane.** Prototype its Realtime API plus a minimal Vellum backend adapter. It is extremely inexpensive, broad-language, tool/MCP-capable, and its open Qwen Live Harness provides useful delegation patterns. Treat it as new and unproven on Windows.
3. **Gemini Live challenger lane.** Use when broad Indic languages and mature asynchronous result scheduling matter more than proven continuous duplex overlap.
4. **ElevenAgents custom-LLM lane.** Use when Vellum must author every response and voice polish/turn controls matter more than native audio reasoning.
5. **Sarvam lane for Indian-language mode.** Start with raw Saaras v4 + Bulbul v3 around Vellum; consider hosted Voice Agents only if telephony and Sarvam-owned orchestration become requirements.
6. **MiniCPM-o 4.5 local lab lane.** Run Q4/GGUF only as a hardware experiment with Gemma explicitly stopped. Do not make it the default or promise full Vellum tool parity.

### Do not select a provider from demos alone

Run the same recorded and live test suite against every candidate:

- 500 ms and 1.5 s mid-sentence interruptions;
- “wait—actually…” direction changes;
- short acknowledgments (“mm-hmm,” “yeah,” “right”) that should **not** stop the agent;
- 1–5 second thinking pauses, fillers, and false starts;
- laughter, coughs, keyboard noise, another person speaking, speaker echo, and music;
- a 20–60 second Vellum tool/subagent task while the user keeps talking;
- task cancellation versus merely interrupting spoken output;
- Hindi, Hinglish, and at least two additional target Indian languages;
- one-hour context continuity and provider reconnect;
- exact data disclosure, retention, transcript, and audio-deletion behavior;
- laptop thermals, real-time factor, VRAM peak, RAM peak, and battery mode for the local lane.

Record four different metrics: **time to first meaningful audio**, **time to stop after a true interruption**, **false interruption rate on backchannels/noise**, and **task result correctness after interruption**. A single latency number hides the failures Vellum cares about.

## Final recommendation

Do not replace Vellum's text/runtime core with a local omni model. The current laptop cannot comfortably keep a high-quality full-duplex model GPU-resident beside the installed 7.5 GB Gemma quantization, and the local candidates are weaker in tools, languages, and Windows support.

For a first serious implementation, compare **GPT-Live-1**, **Qwen3.8 Omni Realtime**, and **Gemini Live** behind one adapter, with Vellum retaining tool/subagent authority. Add **ElevenAgents custom LLM** as the “Vellum writes every word” control and **Sarvam raw speech APIs** as the Indic control. Keep **MiniCPM-o 4.5 GGUF** as an offline research mode, not the production default.

Today, the honest answer is:

- **Cloud:** several options are competitive, and Grok is plausibly in the same full-duplex class, but none is confirmed to match GPT-Live-1 for Vellum without an A/B test of overlap plus long-running delegation.
- **Local/open on this laptop:** **not on par**. MiniCPM-o 4.5 is the only meaningful experiment; Realtime-Venus is the most useful architecture to learn from; PersonaPlex/Moshi is the best-known conversational reference but officially needs 24 GB and lacks Windows support.

## Source policy

This report uses vendor documentation, vendor pricing pages, official upstream repositories, official Hugging Face model cards, and the projects' own papers/model reports. Marketing benchmark claims are labeled as provider claims. No third-party comparison blog or reseller page is used as evidence for a selection.
