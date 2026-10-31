# Provider icons

These provider marks are copied from the OpenCodex provider icon catalog at
https://github.com/lidge-jun/opencodex/tree/main/gui/public/provider-icons.

They identify runtimes and model vendors in the coding workspace, chat model
picker, and Configuration settings. OpenCodex is MIT licensed; see
`LICENSE.opencodex` in this directory.
Individual SVG source comments are preserved where the upstream asset included
additional attribution.

Google DeepMind, MiniMax, Z.ai, Meta, Cohere, and ByteDance SVGs come from the LobeHub icon
catalog at https://github.com/lobehub/lobe-icons/tree/master/packages/static-svg/icons.
Their upstream MIT license is included as `LICENSE.lobe-icons`. Model vendor
marks are chosen from the model's namespace, separately from its API provider.
Local Gemma models use the Ollama mark, matching their installed runtime.
Cloud Gemma models use the Google DeepMind mark. Both marks appear without a
surrounding badge or border.

The Configuration provider library also uses these local assets. Monochrome
Ollama, OpenRouter, OpenAI, Kimi/Moonshot, Groq, xAI, and OpenCode marks inherit
the current foreground color through a CSS mask. Colored vendor marks retain
their source colors.
