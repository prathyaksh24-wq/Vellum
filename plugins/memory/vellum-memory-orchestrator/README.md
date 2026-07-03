# Vellum Memory Orchestrator

Hermes-style portable wrapper for Vellum's core memory system.

This wrapper preserves the existing backend implementation and registers it through a portable `register(ctx)` entry point.

## Core Memory

- SQLite saved/archived/pending memory
- FTS5 exact search
- Chroma semantic recall
- Honcho user model
- Obsidian memory cards
- `USER.md` and `MEMORY.md`

## Optional Extensions

The wrapper also exposes Vellum's optional external memory extensions:

- Hindsight
- Supermemory
- Holographic local fact memory

These extend the core memory system and do not replace it.
