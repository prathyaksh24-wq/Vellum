"""Memory engines Vellum runs itself, so users need no Docker.

- ``embeddings_route``: one OpenAI-compatible embeddings endpoint backed by
  Vellum's own embedding model, shared by every engine.
- ``postgres``: one embedded PostgreSQL (pg0) instance for the engines.
- ``llm_routing``: maps the model the user chose at onboarding to each
  engine's LLM settings.
- ``supervisor``: starts, health-checks, restarts and stops engine processes.
"""
