from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb"
    test_database_url: str = "postgresql+psycopg://kb:kb@localhost:5432/kb_test"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # Models
    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    llm_model: str = "qwen3.5:4b"
    llm_temperature: float = 0.1
    llm_num_ctx: int = 4096
    llm_timeout: float = 300
    # Used only when LLM_PROVIDER=openai (any OpenAI-compatible endpoint). Off by default.
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # Retrieval and answering
    refusal_threshold: float = 0.3
    top_k: int = 5
    retrieval_candidates: int = 30  # per search (dense and lexical) before fusion
    rerank_top_n: int = 15  # candidates passed to the cross-encoder
    gap_min_occurrences: int = 3  # K: a cluster of gaps is shown to managers only with >= K occurrences
    gap_similarity: float = 0.60  # cosine similarity to join an existing cluster of similar questions


@lru_cache
def get_settings() -> Settings:
    return Settings()
