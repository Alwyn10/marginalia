import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-change-me")
    # Any OpenAI-compatible chat endpoint works: Ollama (free, local), Groq, Gemini, etc.
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "ollama")
    llm_model: str = os.getenv("LLM_MODEL", "llama3.2")
    data_dir: str = os.getenv("DATA_DIR", "./data")
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "10"))
    top_k: int = int(os.getenv("TOP_K", "5"))
    # If the best search hit scores below this (cosine similarity), treat the question as too broad to search.
    overview_threshold: float = float(os.getenv("OVERVIEW_THRESHOLD", "0.18"))


settings = Settings()
