"""Application configuration via pydantic-settings."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_env: str = "development"
    log_level: str = "INFO"

    # OpenCode GO (LLM chat)
    opencode_go_api_key: str = ""
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"
    default_model: str = "deepseek-v4-flash"
    perceive_model: str = "deepseek-v4-flash"
    summary_model: str = "deepseek-v4-flash"
    allowed_models: str = "deepseek-v4-flash,glm-5.2"

    # Google Gemini (solo embeddings)
    google_api_key: str = ""
    # NOTA: usamos ``gemini-embedding-001`` (no ``gemini-embedding-2``) porque
    # este último no soporta ``embed_content`` con ``contents=[a, b, c]``
    # (devuelve un solo embedding agregado, lo cual rompe el upsert a
    # Chroma por longitudes inconsistentes). 001 sí respeta el shape
    # batch → lista de embeddings.
    embedding_model: str = "gemini-embedding-001"

    # Database
    database_url: str = "sqlite:///./data/tutoria.db"

    # Chroma
    chroma_persist_dir: str = "./chroma_data"
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # JWT
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 43200

    # Uploads (Fase 4)
    upload_dir: str = "./data/uploads"
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB

    @property
    def allowed_models_list(self) -> list[str]:
        return [m.strip() for m in self.allowed_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
