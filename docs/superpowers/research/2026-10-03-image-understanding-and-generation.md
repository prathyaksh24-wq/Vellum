# Vellum image understanding and generation research

Research date: 2026-10-03. Scope: model/provider selection and a proposed integration sequence; no product implementation or model installation.

## Recommendation

Keep the installed **Gemma 4 12B** as Vellum's initial image-understanding model. Establish that actual image pixels survive the complete attachment-to-model path before adding another large model. Use local OCR/document parsing when exact text or page structure matters. Add **image generation and editing as separate capabilities**, with a local generator as the privacy-first option and explicit, purpose-specific consent for any cloud alternative.

Gemma 4 12B accepts text, images and audio and produces text. Its ability to describe a picture does not mean it can create a new picture. Google identifies it as a local multimodal model, and the official checkpoint is Apache-2.0. [Google model overview](https://ai.google.dev/gemma/docs/core) · [official checkpoint](https://huggingface.co/google/gemma-4-12B-it)

## The three jobs need different treatment

| User request | Required capability | Recommended initial route |
| --- | --- | --- |
| “Explain this screenshot/chart/photo.” | Visual understanding and reasoning | Existing Gemma 4 12B, receiving image pixels |
| “Extract the invoice fields/table/text exactly.” | OCR, layout parsing, document extraction | Native document text where available; local OCR/page parsing for scans, then Gemma for interpretation |
| “Generate a picture” or “edit this photo.” | Image generation/editing | A separate generator tool; Gemma plans the request and discusses the result |

This separation is a proposed Vellum design decision. One conversational experience can route requests through different tools without replacing the conversational model.

## What the current model and runtime support

Ollama's official library currently lists `gemma4:12b` as a Text/Image model with a roughly 7.7–8.0 GB download range. Gemma 4 supports variable image resolutions; the library recommends greater visual detail for small text and document parsing. File size is not total runtime memory, and maximum context support is not a recommendation to allocate that context on this laptop. [Ollama Gemma 4 library](https://ollama.com/library/gemma4)

For the native REST `/api/chat` endpoint, the image belongs in the user message's `images` array as base64 image bytes. Passing a filename in ordinary text does not deliver pixels. The Ollama SDK may resolve local files, whereas raw REST requires encoded image data. [Ollama vision guide](https://docs.ollama.com/capabilities/vision)

```json
{
  "model": "gemma4:12b",
  "messages": [{
    "role": "user",
    "content": "Read the text and explain the chart.",
    "images": ["<base64 image bytes>"]
  }],
  "stream": false
}
```

Ollama also documents vision through its OpenAI-compatible `/v1/chat/completions` endpoint, using `image_url` content blocks containing a data URI. This is a distinct wire format; adapters should translate the canonical attachment representation to the endpoint they actually use. [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)

Vellum's repository inspection found a native `langchain_ollama.ChatOllama` subclass in `OllamaAdapter`. Its `vellum_attachment_image` conversion produces an `image_url` block which the underlying Ollama message converter then turns into an images array. This is a plausible supported route, but a converter test containing base64-encoded “hello” cannot establish actual image recognition. The local probe results below determine what is known about that path.

## Repository evidence

The inspected checkout was `37f99e6c9d7dedc6f1cb642aff71c3d9820766c6`. Relevant canonical owners and current gaps are:

- `design/Velllum/uploads/components/attachment-runtime.js` prepares uploads, retaining the normalized attachment data URI. The production HTML's `streamBackendReply` submits the attachment array to the existing chat API.
- `backend/agent/app_actions/attachments.py` owns `ConversationAttachment` and local preparation. It accepts PNG/JPEG/WebP/GIF, supported text files and DOCX text extraction. Generic PDF attachment parsing is currently absent; embedded DOCX illustrations are not extracted by its text-only parser.
- `backend/agent/api.py::_agent_content_with_attachments` creates local image/text envelopes; `backend/agent/llm/routing/adapters.py::OllamaAdapter` translates them at the local transport boundary.
- `backend/agent/llm/providers.py` already discovers installed models and capabilities through Ollama `/api/tags` and `/api/show`. Use this owner to require vision support for image-bearing turns and expose clear unsupported-model responses.
- `backend/agent/tools/capabilities/x_service.py` calls `scripts/openai_image_client.py` for X media generation. It is a reuse candidate, not evidence of general conversational image generation.

These paths are code-inspection evidence, not proof that every running UI branch, selected specialist or restored conversation preserves images. Extend these owners, the shared ToolRegistry and the existing DisclosureBroker rather than adding another provider router, store or API.

## Current laptop constraints

The live inspection in this research session found:

- Installed `gemma4:12b`: 11.9B parameters, Q4_K_M; `ollama show` advertises vision, audio, tools and thinking.
- NVIDIA RTX 5070 Ti Laptop GPU: 12,227 MiB total VRAM, with 8,606 MiB in use at the inspection snapshot.
- System RAM: approximately 16.3 GB decimal.

These are local observations, not published model requirements. Current VRAM use changes with application activity. A second vision or image-generation model should be scheduled sequentially and unloaded when idle; reliable coexistence is not established. CPU offload may reduce GPU pressure but can increase latency and RAM pressure.

## Candidate choices

### Image understanding: Gemma first; benchmark alternatives only if needed

The installed Gemma model eliminates another model download and runtime owner. If valid attachments reach it but representative screenshots or small text remain poor, benchmark a specialist before deciding to switch or delegate.

**Qwen3-VL 8B Instruct** is a concrete local comparison candidate: its official card describes GUI understanding, multilingual OCR, and document-structure parsing, and lists Apache-2.0. These are vendor capability claims rather than measured Vellum outcomes. [Qwen official model card](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)

Ollama's `qwen3-vl:8b` listing provides a roughly 6.1 GB Q4_K_M artifact. That is a weight download figure, not a promise of total VRAM use. If used, evaluate the exact instruct tag/quantization through the existing provider and capability profile; avoid installing another independent router. [Ollama Qwen3-VL 8B](https://ollama.com/library/qwen3-vl:8b)

**Local OCR/document parsing:** PaddleOCR is an Apache-2.0 toolkit with local Windows deployment support. Its current PaddleOCR-VL-1.6 model is 0.9B and produces document structure in Markdown/JSON, including tables and formulas. This makes it worth evaluating for dense scanned pages; simpler OCR components may suffice for screenshots. [PaddleOCR official repository](https://github.com/PaddlePaddle/PaddleOCR)

Native text extraction should precede OCR for digitally authored documents. Render relevant scanned PDF pages locally rather than assuming an image-only endpoint understands arbitrary PDF/DOCX bytes. Preserve page numbers and evidence links; distinguish exact extraction from a model's interpretation.

### Local generation/editing: FLUX.2 [klein] 4B is a candidate, not a confirmed fit

FLUX.2 [klein] 4B supports both text-to-image and reference-image editing and is Apache-2.0. The publisher's current model page gives 8.4 GB VRAM for this variant; the official Hugging Face card says approximately 13 GB. Different backend, precision and offload assumptions can explain different figures, but those assumptions have not been reconciled here. A 12 GB laptop deployment requires an actual measured trial, likely with Gemma unloaded and quantization/offload considered. No concurrent fit or latency guarantee is justified. [BFL model page](https://bfl.ai/models/flux-2-klein) · [official model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)

Prefer the **4B** variant for the first commercial product evaluation: BFL lists the 9B variants under a non-commercial license, unlike 4B's Apache-2.0. Preserve license/notice obligations when packaging weights and dependencies. [BFL local deployment and licensing guidance](https://help.bfl.ai/articles/7108141705-can-i-run-or-fine-tune-flux-2-klein-locally)

Use an existing local generation service/tool integration if one is suitable; ComfyUI or Diffusers are supported runtimes named by the model card. Vellum should store the resulting image locally, display it in chat, and preserve references needed for “change the background” follow-ups.

### Optional cloud generation/editing

The current OpenAI image guide recommends **GPT Image 2.5 Flare** (`gpt-image-2.5-flare`) for everyday generation and **Sunburst** (`gpt-image-2.5-sunburst`) for edit precision. Both have direct Images API support; the Responses API can provide tool orchestration and conversational edits. A Vellum local brain can call the direct Images API without replacing itself with a cloud conversational model. [OpenAI image generation guide](https://developers.openai.com/api/docs/guides/image-generation)

This is an optional paid/cloud route. Make provider/model selection configurable and verify availability before implementation. Keep originals and generated artifacts local; disclose exactly which prompt and reference images will leave the device, request approval, and send only the selected material. Text-only PII scrubbing cannot establish that an attached image is safe to disclose.

The repository has `scripts/openai_image_client.py` with a `gpt-image-1` default for an X media workflow. That does not demonstrate general chat generation, inline rendering, editing continuity, or an approved disclosure route. Reuse compatible provider code only after checking those boundaries.

## Proposed delivery sequence

1. **Prove and repair image understanding.** Trace paste/upload through storage, canonical attachment state, privacy handling, message conversion and final local request. Compare native Ollama, the Vellum adapter and the complete chat path with the same synthetic fixture. Report transport/runtime failures separately from model-quality errors.
2. **Strengthen document extraction.** Use native text where possible, local page rendering/OCR where necessary, and source-linked structured extraction. Crop or tile dense screenshots while retaining an overview when global layout matters.
3. **Add generation/editing tools.** Evaluate a local FLUX 4B deployment with memory/latency measurements, wire cancellation and progress, and display local results inline. Implement optional cloud disclosure through the existing approval owner.
4. **Benchmark before expanding the model set.** Compare exact text/number extraction, chart interpretation, UI understanding, page order, latency, peak VRAM/RAM, and failure clarity on representative inputs. Add Qwen or a document VLM only if it provides a measured benefit.

The acceptance set should include a small-text screenshot, a chart, a multi-page scanned document, two images in one message, a follow-up referencing an earlier image, restart/history reload, and an unsupported-format failure. Generation acceptance includes create, edit, cancel, save/reopen, and a cloud request that sends nothing before approval.

## Local probe findings

A locally generated 760 x 240 image contained the text “Invoice total: 472.83” and a blue square. The prompt requested the invoice total and square color without revealing either expected value.

- Native Ollama `/api/chat` returned HTTP 200 and: “The invoice total is 472.83 and the square is blue.”
- The existing Vellum `OllamaAdapter` returned the same exact answer; its converted request contained one image.

These observations establish that the installed model and isolated adapter can read a real synthetic image. They do not establish the complete paste/upload, API, routing, session-history and frontend flow. The reported original failure was not reproduced here, so its root cause remains unknown. Next trace the upload payload, selected model, specialist routing and attachment persistence; evaluate small-text resolution/crops if pixels reach the correct model but extraction quality is poor.

## Research limitations

Existing focused suites `backend/tests/test_routing_adapters.py` and `backend/tests/test_app_action_attachments.py` passed: **29 passed in 5.29 seconds**. The first attempt had four setup errors because Windows denied pytest's default temporary directory; rerunning with a fresh writable `--basetemp` and cache disabled resolved them. No tests or product code were added. Full backend/frontend suites and browser upload acceptance were not run for this documentation-only change.

Primary sources were checked for this report. Public model claims and benchmark scores do not establish accuracy on the user's own documents. No new weights were downloaded, no generator was installed, and no user image was sent to a cloud model. Agent Reach's configured Exa command was attempted but `mcporter` was absent, so official pages were gathered using the available web-search/read fallback.
