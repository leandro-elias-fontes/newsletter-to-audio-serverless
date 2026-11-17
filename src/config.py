"""Configurações centralizadas da aplicação via variáveis de ambiente."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parâmetros de execução carregados do ambiente ou arquivo .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key_1: str = Field(..., min_length=1)
    gemini_api_key_2: str = Field(default="")
    gemini_model: str = Field(default="gemini-3.8-flash")

    gmail_client_id: str = Field(default="")
    gmail_client_secret: str = Field(default="")
    gmail_refresh_token: str = Field(default="")
    gmail_query: str = Field(default="is:unread newer_than:1d")
    max_emails_per_run: int = Field(default=15, ge=1, le=50)

    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    tts_voice: str = Field(default="pt-BR-AntonioNeural")
    tts_rate: str = Field(default="+5%")

    enable_local_cache: bool = Field(default=True)
    cache_db_path: str = Field(default=".cache_gemini.sqlite")

    def get_gemini_keys(self) -> list[str]:
        """Retorna lista não vazia de chaves Gemini configuradas para rotação."""
        keys = [self.gemini_api_key_1.strip()]
        if self.gemini_api_key_2.strip():
            keys.append(self.gemini_api_key_2.strip())
        return keys
