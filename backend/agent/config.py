from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Vellum repo root: this file lives at <repo>/backend/agent/config.py,
# so parents[2] is the repo root regardless of how Python was invoked.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_against_repo(p: Path) -> Path:
    """Resolve a path. If absolute, normalize. If relative, anchor to REPO_ROOT."""
    p = Path(p)
    if p.is_absolute():
        return p.resolve()
    return (REPO_ROOT / p).resolve()


class Settings(BaseSettings):
    # Anchor the .env file lookup to REPO_ROOT, not CWD. Otherwise starting
    # uvicorn from backend/ silently fails to load OPENROUTER_API_KEY etc.
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenRouter
    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="OPENROUTER_BASE_URL",
    )

    # Direct provider keys (optional). When set, openai/* models bypass
    # OpenRouter and hit api.openai.com directly. Privacy contract differs:
    # the vendor's own data-retention policy applies, not OpenRouter's ZDR.
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
    )
    primary_model: str = Field(default="google/gemma-4-31b-it", alias="PRIMARY_MODEL")
    fallback_model: str = Field(default="qwen/qwen3.5-35b-a3b", alias="FALLBACK_MODEL")
    fast_model: str = Field(default="google/gemma-3-12b-it", alias="FAST_MODEL")

    # Obsidian
    obsidian_vault_path: Path = Field(alias="OBSIDIAN_VAULT_PATH")
    agent_notes_folder: str = Field(default="Agent", alias="AGENT_NOTES_FOLDER")

    # Vector store (embedded ChromaDB)
    chroma_path: Path | None = Field(default=Path("data/embeddings/chroma"), alias="CHROMA_PATH")

    # Privacy
    enable_pii_scrubbing: bool = Field(default=True, alias="ENABLE_PII_SCRUBBING")
    zdr_only: bool = Field(default=True, alias="ZDR_ONLY")
    min_retrieval_score: float = Field(default=0.65, alias="MIN_RETRIEVAL_SCORE")
    max_context_chunks: int = Field(default=5, alias="MAX_CONTEXT_CHUNKS")
    max_context_tokens: int = Field(default=3000, alias="MAX_CONTEXT_TOKENS")
    enable_vector_search: bool = Field(default=False, alias="ENABLE_VECTOR_SEARCH")
    enable_cross_encoder_rerank: bool = Field(default=False, alias="ENABLE_CROSS_ENCODER_RERANK")
    enable_query_vector_storage: bool = Field(default=False, alias="ENABLE_QUERY_VECTOR_STORAGE")

    # MCP
    filesystem_mcp_path: Path = Field(alias="FILESYSTEM_MCP_PATH")
    apify_mcp_url: str = Field(default="https://mcp.apify.com", alias="APIFY_MCP_URL")
    apify_api_token: str = Field(default="", alias="APIFY_API_TOKEN")
    apify_amazon_actor: str = Field(default="scrapeai/amazon-product-scraper", alias="APIFY_AMAZON_ACTOR")
    apify_youtube_actor: str = Field(default="majdijm/youtube-channel-scraper", alias="APIFY_YOUTUBE_ACTOR")
    playwright_mcp_command: str = Field(default="npx", alias="PLAYWRIGHT_MCP_COMMAND")
    playwright_mcp_args: str = Field(default="-y @playwright/mcp@latest --isolated", alias="PLAYWRIGHT_MCP_ARGS")
    playwright_mcp_allow_mutations: bool = Field(default=False, alias="PLAYWRIGHT_MCP_ALLOW_MUTATIONS")
    github_mcp_url: str = Field(default="https://api.githubcopilot.com/mcp/", alias="GITHUB_MCP_URL")
    github_mcp_token: str = Field(default="", alias="GITHUB_MCP_TOKEN")
    github_pat: str = Field(default="", alias="GITHUB_PAT")
    github_mcp_allow_writes: bool = Field(default=False, alias="GITHUB_MCP_ALLOW_WRITES")
    github_mcp_allow_destructive: bool = Field(default=False, alias="GITHUB_MCP_ALLOW_DESTRUCTIVE")
    git_tool_allow_writes: bool = Field(default=False, alias="GIT_TOOL_ALLOW_WRITES")
    x_tool_allow_private_reads: bool = Field(default=False, alias="X_TOOL_ALLOW_PRIVATE_READS")
    x_tool_allow_posts: bool = Field(default=False, alias="X_TOOL_ALLOW_POSTS")
    obsidian_api_key: str = Field(default="", alias="OBSIDIAN_API_KEY")
    obsidian_mcp_url: str = Field(default="https://127.0.0.1:27124/mcp/", alias="OBSIDIAN_MCP_URL")
    obsidian_mcp_use_stream: bool = Field(default=False, alias="OBSIDIAN_MCP_USE_STREAM")
    obsidian_mcp_verify_ssl: bool = Field(default=False, alias="OBSIDIAN_MCP_VERIFY_SSL")
    obsidian_mcp_allow_writes: bool = Field(default=False, alias="OBSIDIAN_MCP_ALLOW_WRITES")
    obsidian_mcp_allow_destructive: bool = Field(default=False, alias="OBSIDIAN_MCP_ALLOW_DESTRUCTIVE")
    obsidian_mcp_allow_commands: bool = Field(default=False, alias="OBSIDIAN_MCP_ALLOW_COMMANDS")
    context7_mcp_url: str = Field(default="https://mcp.context7.com/mcp", alias="CONTEXT7_MCP_URL")
    context7_api_key: str = Field(default="", alias="CONTEXT7_API_KEY")
    gitmcp_mcp_url: str = Field(default="https://gitmcp.io/docs", alias="GITMCP_MCP_URL")
    context_mode_mcp_command: str = Field(default="npx", alias="CONTEXT_MODE_MCP_COMMAND")
    context_mode_mcp_args: str = Field(default="-y context-mode", alias="CONTEXT_MODE_MCP_ARGS")
    mcp_timeout_seconds: int = Field(default=300, alias="MCP_TIMEOUT_SECONDS")

    # Agent
    thread_id: str = Field(default="default", alias="THREAD_ID")
    cloud_escalation_model: str = Field(default="google/gemini-2.5-pro", alias="CLOUD_ESCALATION_MODEL")
    cloud_escalation_enabled: bool = Field(default=True, alias="CLOUD_ESCALATION_ENABLED")
    honcho_base_url: str = Field(default="http://localhost:8001", alias="HONCHO_BASE_URL")
    honcho_app_id: str = Field(default="vellum", alias="HONCHO_APP_ID")
    honcho_user_id: str = Field(default="default", alias="HONCHO_USER_ID")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        alias="LOG_LEVEL",
    )
    enable_nightly_digest: bool = Field(default=True, alias="ENABLE_NIGHTLY_DIGEST")
    enable_vault_watcher: bool = Field(default=True, alias="ENABLE_VAULT_WATCHER")
    vault_watcher_debounce_seconds: float = Field(default=2.0, alias="VAULT_WATCHER_DEBOUNCE_SECONDS")
    voice_enabled: bool = Field(default=True, alias="VOICE_ENABLED")
    voice_stt_engine: str = Field(default="moonshine", alias="VOICE_STT_ENGINE")
    voice_stt_model: str = Field(default="tiny", alias="VOICE_STT_MODEL")
    voice_tts_engine: str = Field(default="kokoro", alias="VOICE_TTS_ENGINE")
    voice_tts_voice: str = Field(default="af_heart", alias="VOICE_TTS_VOICE")
    voice_tts_speed: float = Field(default=1.0, alias="VOICE_TTS_SPEED")
    voice_model_dir: Path = Field(default=Path("data/models/voice"), alias="VOICE_MODEL_DIR")

    # Computer use
    computer_use_allow_desktop: bool = Field(default=False, alias="COMPUTER_USE_ALLOW_DESKTOP")
    computer_use_screenshot_dir: Path = Field(
        default=Path("data/computer-use/screenshots"),
        alias="COMPUTER_USE_SCREENSHOT_DIR",
    )
    computer_use_activity_overlay: bool = Field(default=True, alias="COMPUTER_USE_ACTIVITY_OVERLAY")
    computer_use_exclusive_control: bool = Field(default=True, alias="COMPUTER_USE_EXCLUSIVE_CONTROL")
    computer_use_guard_watchdog_seconds: float = Field(default=20.0, alias="COMPUTER_USE_GUARD_WATCHDOG_SECONDS")

    @field_validator(
        "obsidian_vault_path",
        "filesystem_mcp_path",
        "chroma_path",
        "voice_model_dir",
        "computer_use_screenshot_dir",
        mode="before",
    )
    @classmethod
    def expand_path(cls, value: str | Path | None) -> Path | None:
        if value in (None, ""):
            return None
        return Path(str(value)).expanduser()

    @model_validator(mode="after")
    def validate_paths_and_privacy(self) -> "Settings":
        # Resolve relative paths against the REPO ROOT, not CWD. Embedded Chroma
        # uses the path as its storage location, so a CWD-dependent path would
        # produce split-brain databases (one when started from Vellum/, another
        # from Vellum/backend/).
        self.obsidian_vault_path = _resolve_against_repo(self.obsidian_vault_path)
        self.filesystem_mcp_path = _resolve_against_repo(self.filesystem_mcp_path)
        if self.chroma_path is not None:
            self.chroma_path = _resolve_against_repo(self.chroma_path)
        self.voice_model_dir = _resolve_against_repo(self.voice_model_dir)
        self.computer_use_screenshot_dir = _resolve_against_repo(self.computer_use_screenshot_dir)

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
        if self.voice_stt_engine not in {"moonshine"}:
            raise ValueError("VOICE_STT_ENGINE must be moonshine.")
        if self.voice_tts_engine not in {"kokoro"}:
            raise ValueError("VOICE_TTS_ENGINE must be kokoro.")
        if self.voice_tts_speed <= 0:
            raise ValueError("VOICE_TTS_SPEED must be greater than 0.")
        if not self.apify_mcp_url.startswith(("https://", "http://")):
            raise ValueError("APIFY_MCP_URL must be an HTTP(S) URL.")
        if not self.github_mcp_url.startswith(("https://", "http://")):
            raise ValueError("GITHUB_MCP_URL must be an HTTP(S) URL.")
        if not self.obsidian_mcp_url.startswith(("https://", "http://")):
            raise ValueError("OBSIDIAN_MCP_URL must be an HTTP(S) URL.")
        if not self.context7_mcp_url.startswith(("https://", "http://")):
            raise ValueError("CONTEXT7_MCP_URL must be an HTTP(S) URL.")
        if not self.gitmcp_mcp_url.startswith(("https://", "http://")):
            raise ValueError("GITMCP_MCP_URL must be an HTTP(S) URL.")

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
