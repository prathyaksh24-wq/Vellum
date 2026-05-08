from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenRouter
    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )
    primary_model: str = Field(default="google/gemma-4-31b-it", alias="PRIMARY_MODEL")
    fallback_model: str = Field(default="qwen/qwen3.5-35b-a3b", alias="FALLBACK_MODEL")
    fast_model: str = Field(default="google/gemma-3-12b-it", alias="FAST_MODEL")

    # Obsidian
    obsidian_vault_path: Path = Field(alias="OBSIDIAN_VAULT_PATH")
    agent_notes_folder: str = Field(default="Agent", alias="AGENT_NOTES_FOLDER")

    # Qdrant
    qdrant_local_path: Path | None = Field(default=Path("data/embeddings/qdrant-local"), alias="QDRANT_LOCAL_PATH")
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")

    # Privacy
    enable_pii_scrubbing: bool = Field(default=True, alias="ENABLE_PII_SCRUBBING")
    zdr_only: bool = Field(default=True, alias="ZDR_ONLY")
    min_retrieval_score: float = Field(default=0.65, alias="MIN_RETRIEVAL_SCORE")
    max_context_chunks: int = Field(default=5, alias="MAX_CONTEXT_CHUNKS")
    max_context_tokens: int = Field(default=3000, alias="MAX_CONTEXT_TOKENS")

    # MCP
    filesystem_mcp_path: Path = Field(alias="FILESYSTEM_MCP_PATH")
    apify_mcp_url: str = Field(default="https://mcp.apify.com", alias="APIFY_MCP_URL")
    apify_api_token: str = Field(default="", alias="APIFY_API_TOKEN")
    apify_amazon_actor: str = Field(default="scrapeai/amazon-product-scraper", alias="APIFY_AMAZON_ACTOR")
    mcp_timeout_seconds: int = Field(default=300, alias="MCP_TIMEOUT_SECONDS")

    # Agent
    thread_id: str = Field(default="default", alias="THREAD_ID")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )
    enable_nightly_digest: bool = Field(default=True, alias="ENABLE_NIGHTLY_DIGEST")
    enable_vault_watcher: bool = Field(default=True, alias="ENABLE_VAULT_WATCHER")
    vault_watcher_debounce_seconds: float = Field(default=2.0, alias="VAULT_WATCHER_DEBOUNCE_SECONDS")

    @field_validator("obsidian_vault_path", "filesystem_mcp_path", "qdrant_local_path", mode="before")
    @classmethod
    def expand_path(cls, value: str | Path | None) -> Path | None:
        if value in (None, ""):
            return None
        return Path(str(value)).expanduser()

    @model_validator(mode="after")
    def validate_paths_and_privacy(self) -> "Settings":
        self.obsidian_vault_path = self.obsidian_vault_path.resolve()
        self.filesystem_mcp_path = self.filesystem_mcp_path.resolve()
        if self.qdrant_local_path is not None:
            self.qdrant_local_path = self.qdrant_local_path.resolve()

        if not self.obsidian_vault_path.exists():
            raise ValueError(f"Obsidian vault path does not exist: {self.obsidian_vault_path}")
        if not self.obsidian_vault_path.is_dir():
            raise ValueError(f"Obsidian vault path is not a directory: {self.obsidian_vault_path}")
        if not self.filesystem_mcp_path.exists():
            raise ValueError(f"Filesystem MCP path does not exist: {self.filesystem_mcp_path}")
        if not self.filesystem_mcp_path.is_dir():
            raise ValueError(f"Filesystem MCP path is not a directory: {self.filesystem_mcp_path}")
        if not self.filesystem_mcp_path.resolve().is_relative_to(self.obsidian_vault_path):
            raise ValueError("Filesystem MCP path must stay inside the Obsidian vault path.")
        if not self.zdr_only:
            raise ValueError("ZDR_ONLY must remain true for this privacy-first agent.")
        if not 0 <= self.min_retrieval_score <= 1:
            raise ValueError("MIN_RETRIEVAL_SCORE must be between 0 and 1.")
        if self.max_context_chunks < 1:
            raise ValueError("MAX_CONTEXT_CHUNKS must be at least 1.")
        if self.max_context_tokens < 1:
            raise ValueError("MAX_CONTEXT_TOKENS must be at least 1.")
        if self.mcp_timeout_seconds < 1:
            raise ValueError("MCP_TIMEOUT_SECONDS must be at least 1.")
        if self.vault_watcher_debounce_seconds < 0:
            raise ValueError("VAULT_WATCHER_DEBOUNCE_SECONDS cannot be negative.")
        if not self.apify_mcp_url.startswith(("https://", "http://")):
            raise ValueError("APIFY_MCP_URL must be an HTTP(S) URL.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
