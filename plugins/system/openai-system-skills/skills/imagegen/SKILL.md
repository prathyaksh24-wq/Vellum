---
name: imagegen
description: Generate or edit raster images, illustrations, photos, textures or mockups
  with Vellum image tools.
author: OpenAI; Vellum runtime adaptation
license: Apache-2.0
metadata:
  hermes:
    category: system
  vellum:
    trigger_only: true
    trigger:
    - generate an image
    - generate image
    - create an image
    - create image
    - make an image
    - draw a picture
    - edit an image
    - edit this image
    - imagegen
    - image generation
  provenance:
    source: openai-system-adapted
    repository_url: https://github.com/openai/skills
    source_ref: 49f948faa9258a0c61caceaf225e179651397431
    source_path: skills/.system/imagegen
---

# Image Generation for Vellum

Use raster generation for photos, illustrations, textures, sprites, product mockups and image variants. Use existing SVG/code tools for deterministic diagrams or edits to an existing vector system.

## Procedure
1. Identify generation versus editing, the intended use, exact text, output format/aspect ratio, and what must be preserved. Keep specific prompts faithful; add composition detail only when it helps the stated request.
2. Load `references/prompting.md` or `references/sample-prompts.md` through `skill_view(name="imagegen", path=...)` when needed. These are shared OpenAI prompting references; their Codex tool names do not grant tools to Vellum.
3. Discover `image_generate` through `tool_search` and inspect its schema. Use `action="status"` to check actual readiness. Vellum uses its configured OpenAI key for this optional cloud feature; it is not Codex's subscription-backed image_gen tool. Never collect or expose a key in chat.
4. Structure the prompt as subject, setting, style, composition, lighting, exact text and constraints. For edits identify the actual target and invariants explicitly. The tool supports new images and editing an explicitly selected image in an allowed local folder; pass its `image_path` only for an edit. A reference image is not automatically an edit target.
5. Explain that the prompt (and selected image for edits) will be sent to OpenAI. Call `image_generate` with the requested operation, prompt and size/background to prepare the exact-input App Action review. The user approves that review before the cloud request runs; never confirm it yourself. Local-only privacy mode blocks this cloud feature. A readiness/status check makes no image API request.
6. Use only paths returned by the tool. Each result is saved non-destructively with a unique name. Report failure or missing setup honestly; never substitute an unrelated image, post to X or overwrite a project asset to claim success.
7. Inspect the saved output with available visual tools before claiming visual verification. Check subject, style, exact text and invariants; iterate with one targeted change. Return the actual saved path. If visual inspection is unavailable, say so.

## Completion
A successful tool receipt with an existing saved file proves generation, not visual quality. Prompt preparation or skill activation alone does not prove an image was generated. Do not run the bundled Codex CLI automatically; Vellum's typed tool keeps credential and file-access checks in the runtime.
