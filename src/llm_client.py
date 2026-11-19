"""Cliente Google Gemini com rotação de chaves, backoff e fallback automático de modelo (503/429)."""

import hashlib
import sqlite3
import time
from pathlib import Path
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

FALLBACK_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
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
        model: str = "gemini-3.5-flash-lite",
        cache: SQLitePromptCache | None = None,
    ) -> None:
        if not api_keys:
            raise ValueError("Pelo menos uma chave da API Gemini deve ser fornecida.")
        self._api_keys = api_keys
        self._model = model
        self._cache = cache
        self._key_index = 0
        self._cached_candidates: list[str] | None = None

    def _next_client(self) -> genai.Client:
        key = self._api_keys[self._key_index % len(self._api_keys)]
        self._key_index += 1
        return genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=20000),
        )

    def _candidate_models(self) -> list[str]:
        if self._cached_candidates is not None:
            if self._model in self._cached_candidates:
                ordered = [self._model] + [
                    m for m in self._cached_candidates if m != self._model
                ]
                self._cached_candidates = ordered
            return list(self._cached_candidates)

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
                    and not any(x in name for x in ("tts", "image", "audio", "embedding", "1.5"))
                    and name not in models
                ):
                    models.append(name)
        except Exception as exc:  # noqa: BLE001
            print(f"[Gemini] Aviso ao listar modelos dinâmicos: {exc}", flush=True)

        self._cached_candidates = models
        return list(self._cached_candidates)

    def _promote_model(self, working_model: str) -> None:
        """Promove o modelo que respondeu com sucesso para evitar retentativas lentas nos próximos e-mails."""
        self._model = working_model
        if self._cached_candidates is not None:
            self._cached_candidates = [working_model] + [
                m for m in self._cached_candidates if m != working_model
            ]

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
                    self._promote_model(candidate_model)
                    if self._cache:
                        self._cache.set(self._model, prompt, raw_json, schema_name)
                    print(f"[Gemini] Classificação concluída via {candidate_model}.", flush=True)
                    return parsed
                except (
                    genai_errors.APIError,
                    ValidationError,
                    httpx.HTTPError,
                    OSError,
                    Exception,  # noqa: BLE001
                ) as exc:
                    last_exc = exc
                    print(
                        f"[Gemini] Falha em {candidate_model} (tentativa {attempt + 1}/{len(self._api_keys)}): "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
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
                    self._promote_model(candidate_model)
                    if self._cache and text:
                        self._cache.set(self._model, prompt, text, "text")
                    print(f"[Gemini] Roteiro gerado com sucesso via {candidate_model}.", flush=True)
                    return text
                except (
                    genai_errors.APIError,
                    httpx.HTTPError,
                    OSError,
                    Exception,  # noqa: BLE001
                ) as exc:
                    last_exc = exc
                    print(
                        f"[Gemini] Falha em {candidate_model} (tentativa {attempt + 1}/{len(self._api_keys)}): "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    time.sleep(1.5 * (attempt + 1))

        raise RuntimeError(f"Falha em todas as chaves/modelos Gemini: {last_exc}") from last_exc
