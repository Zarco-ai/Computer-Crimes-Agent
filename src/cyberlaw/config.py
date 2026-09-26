"""Single source of truth for paths, model names, and prices.

Everything tunable lives here so experiments are a config change, not a code
change. Prices are USD per 1M tokens and are only used for cost *estimates* --
they must be updated by hand when vendors change pricing.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = three levels up from this file (src/cyberlaw/config.py).
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration, populated from the environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Credentials -----------------------------------------------------
    # The Pinecone key keeps its original lowercase name so existing .env
    # files written for the previous version of this project keep working.
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    pinecone_api_key: str = Field(default="", alias="pinecone_apikey")
    wandb_api_key: str = Field(default="", alias="WANDB_API_KEY")

    # --- Paths -----------------------------------------------------------
    raw_html: Path = ROOT / "data" / "raw" / "pe.33.htm"
    processed_dir: Path = ROOT / "data" / "processed"
    logs_dir: Path = ROOT / "logs"
    eval_out_dir: Path = ROOT / "evals_out"

    # --- Models ----------------------------------------------------------
    chat_model: str = Field(default="gpt-4o-mini", alias="CYBERLAW_CHAT_MODEL")
    embed_model: str = Field(
        default="text-embedding-3-small", alias="CYBERLAW_EMBED_MODEL"
    )
    embed_dimensions: int = 1536

    # --- Vector store ----------------------------------------------------
    pinecone_index: str = Field(default="cyberlaw", alias="CYBERLAW_PINECONE_INDEX")
    # New namespace so the previous whole-section vectors stay intact as a
    # rollback / A-B baseline in __default__.
    pinecone_namespace: str = Field(
        default="ch33-atomic-v2", alias="CYBERLAW_PINECONE_NAMESPACE"
    )
    top_k: int = Field(default=6, alias="CYBERLAW_TOP_K")

    # --- Agent -----------------------------------------------------------
    max_agent_steps: int = Field(default=6, alias="CYBERLAW_MAX_AGENT_STEPS")
    temperature: float = 0.0
    # One retry after a citation violation, then a forced refusal.
    max_verifier_retries: int = 1

    # --- Observability ---------------------------------------------------
    tracing_enabled: bool = Field(default=False, alias="CYBERLAW_TRACING_ENABLED")
    weave_project: str = Field(
        default="zzarcai/RAG Prompt Tracking", alias="CYBERLAW_WEAVE_PROJECT"
    )

    # --- Prices (USD per 1M tokens / units) ------------------------------
    price_embed_per_1m: float = 0.02  # text-embedding-3-small
    price_input_per_1m: float = 0.15  # gpt-4o-mini input
    price_output_per_1m: float = 0.60  # gpt-4o-mini output
    price_pinecone_read_per_1m_ru: float = 16.0
    price_pinecone_write_per_1m_wu: float = 4.0

    # --- Derived paths ---------------------------------------------------
    @property
    def chapter_json(self) -> Path:
        """Parsed statute tree (the canonical intermediate artifact)."""
        return self.processed_dir / "chapter33.json"

    @property
    def chunks_jsonl(self) -> Path:
        """Embedding-ready chunks. This file is the contract between the
        chunking strategy and everything downstream."""
        return self.processed_dir / "chunks.jsonl"

    @property
    def registry_json(self) -> Path:
        """Deterministic definition + penalty lookup tables."""
        return self.processed_dir / "registry.json"

    @property
    def query_log(self) -> Path:
        return self.logs_dir / "query_costs.jsonl"

    def ensure_dirs(self) -> None:
        for d in (self.processed_dir, self.logs_dir, self.eval_out_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so config is parsed once per process."""
    return Settings()
