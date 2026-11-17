"""Cliente Google Gemini com rotação de chaves, backoff e fallback automático de modelo (503/429)."""

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

FALLBACK_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.8-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.0-flash",
)


class SQLitePromptCache:
    """Cache local simples em SQLite para evitar chamadas repetidas durante desenvolvimento."""

    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS prompt_cache ("
                "cache_key TEXT PRIMARY KEY, response_text TEXT NOT NULL)"
            )

    @staticmethod
    def _hash_key(model: str, prompt: str, schema_name: str) -> str:
        payload = f"{model}::{schema_name}::{prompt}".encode()
        return hashlib.sha256(payload).hexdigest()

    def get(self, model: str, prompt: str, schema_name: str = "text") -> str | None:
        key = self._hash_key(model, prompt, schema_name)
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT response_text FROM prompt_cache WHERE cache_key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def set(self, model: str, prompt: str, response_text: str, schema_name: str = "text") -> None:
        key = self._hash_key(model, prompt, schema_name)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO prompt_cache (cache_key, response_text) VALUES (?, ?)",
                (key, response_text),
            )


class GeminiRotatingClient:
    """Executa chamadas ao Gemini rotacionando chaves e modelos de fallback em caso de 503/429."""

    def __init__(
        self,
        api_keys: list[str],
        model: str = "gemini-3.8-flash",
        cache: SQLitePromptCache | None = None,
    ) -> None:
        if not api_keys:
            raise ValueError("Pelo menos uma chave da API Gemini deve ser fornecida.")
        self._api_keys = api_keys
        self._model = model
        self._cache = cache
        self._key_index = 0

    def _next_client(self) -> genai.Client:
        key = self._api_keys[self._key_index % len(self._api_keys)]
        self._key_index += 1
        return genai.Client(api_key=key)

    def _candidate_models(self) -> list[str]:
        models = [self._model]
        for candidate in FALLBACK_MODELS:
            if candidate not in models:
                models.append(candidate)
        try:
            client = self._next_client()
            for item in client.models.list():
                name = (item.name or "").removeprefix("models/")
                if (
                    "flash" in name
                    and not any(x in name for x in ("tts", "image", "audio", "embedding", "2.0", "1.5", "2.5"))
                    and name not in models
                ):
                    models.append(name)
        except (genai_errors.APIError, OSError):
            pass
        return models

    def generate_structured(self, prompt: str, schema: type[T]) -> T:
        """Gera saída tipada via Pydantic usando Structured Outputs do Gemini com fallback."""
        schema_name = schema.__name__
        if self._cache:
            cached = self._cache.get(self._model, prompt, schema_name)
            if cached:
                return schema.model_validate_json(cached)

        last_exc: Exception | None = None
        for candidate_model in self._candidate_models():
            for attempt in range(len(self._api_keys)):
                client = self._next_client()
                try:
                    response = client.models.generate_content(
                        model=candidate_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            response_mime_type="application/json",
                            response_schema=schema,
                        ),
                    )
                    raw_json = response.text or "{}"
                    parsed = schema.model_validate_json(raw_json)
                    if self._cache:
                        self._cache.set(self._model, prompt, raw_json, schema_name)
                    return parsed
                except (genai_errors.APIError, ValidationError, OSError) as exc:
                    last_exc = exc
                    time.sleep(1.5 * (attempt + 1))

        raise RuntimeError(f"Falha em todas as chaves/modelos Gemini: {last_exc}") from last_exc

    def generate_text(self, prompt: str) -> str:
        """Gera texto livre (roteiro em português) rotacionando chaves e modelos em caso de 503/429."""
        if self._cache:
            cached = self._cache.get(self._model, prompt, "text")
            if cached:
                return cached

        last_exc: Exception | None = None
        for candidate_model in self._candidate_models():
            for attempt in range(len(self._api_keys)):
                client = self._next_client()
                try:
                    response = client.models.generate_content(
                        model=candidate_model,
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=0.4),
                    )
                    text = (response.text or "").strip()
                    if self._cache and text:
                        self._cache.set(self._model, prompt, text, "text")
                    return text
                except (genai_errors.APIError, OSError) as exc:
                    last_exc = exc
                    time.sleep(1.5 * (attempt + 1))

        raise RuntimeError(f"Falha em todas as chaves/modelos Gemini: {last_exc}") from last_exc
