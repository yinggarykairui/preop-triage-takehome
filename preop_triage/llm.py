"""LLM provider abstraction with structured outputs, disk cache and fail-safe errors.

- Provider/model are configurable (LLM_PROVIDER, model argument).
- Temperature 0, strict JSON schema from the pydantic model.
- Responses are cached on disk keyed by a hash of (provider, model, prompt, schema),
  so harness reruns and the determinism check are free and reproducible.
- Any failure raises LLMError; callers degrade to UNKNOWN (A17).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "llm"


class LLMError(Exception):
    """Any provider, timeout, schema or parse failure."""


class Provider(Protocol):
    name: str

    def complete(self, *, model: str, instructions: str, user_text: str, schema_model: type[T], schema_name: str) -> dict:
        """Return the parsed JSON object (not yet validated)."""


class OpenAIProvider:
    name = "openai"

    def __init__(self, timeout_s: float = 60.0, max_retries: int = 2) -> None:
        from openai import OpenAI  # lazy so the rule engine works without the SDK

        self._client = OpenAI(timeout=timeout_s, max_retries=max_retries)

    def complete(self, *, model: str, instructions: str, user_text: str, schema_model: type[T], schema_name: str) -> dict:
        kwargs: dict = {}
        # Reasoning models reject sampling params; everything else is pinned to 0.
        if not (model.startswith("o") or model.startswith("gpt-5")):
            kwargs["temperature"] = 0
        resp = self._client.responses.parse(
            model=model,
            instructions=instructions,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user_text}]}],
            text_format=schema_model,
            **kwargs,
        )
        parsed = resp.output_parsed
        if parsed is None:
            raise LLMError(f"empty structured output from {model}")
        return parsed.model_dump()


def make_provider(name: str | None = None) -> Provider:
    name = (name or os.environ.get("LLM_PROVIDER") or "openai").lower()
    if name == "openai":
        return OpenAIProvider(timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "60")))
    raise LLMError(f"unknown LLM provider {name!r}; set LLM_PROVIDER=openai")


@dataclass
class LLMStats:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    errors: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, attr: str, msg: str | None = None) -> None:
        with self._lock:
            setattr(self, attr, getattr(self, attr) + 1)
            if msg:
                self.errors.append(msg)


class CachedLLM:
    """Structured extraction with a content-addressed disk cache."""

    def __init__(
        self,
        model: str,
        provider: Provider | None = None,
        cache_dir: Path | None = None,
        use_cache: bool | None = None,
    ) -> None:
        self.model = model
        self._provider = provider
        self.cache_dir = Path(cache_dir or os.environ.get("LLM_CACHE_DIR") or DEFAULT_CACHE_DIR)
        env_disable = os.environ.get("LLM_DISABLE_CACHE", "").lower() in {"1", "true", "yes"}
        self.use_cache = (not env_disable) if use_cache is None else use_cache
        self.stats = LLMStats()

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = make_provider()
        return self._provider

    @property
    def provider_name(self) -> str:
        if self._provider is not None:
            return self._provider.name
        return os.environ.get("LLM_PROVIDER", "openai")

    def _key(self, instructions: str, user_text: str, schema_model: type[BaseModel], schema_name: str) -> str:
        payload = {
            "provider": os.environ.get("LLM_PROVIDER", "openai"),
            "model": self.model,
            "instructions": instructions,
            "user_text": user_text,
            "schema_name": schema_name,
            "schema": schema_model.model_json_schema(),
            "temperature": 0,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def extract(self, *, instructions: str, user_text: str, schema_model: type[T], schema_name: str) -> T:
        """Return a validated model instance or raise LLMError. Never returns partial data."""
        key = self._key(instructions, user_text, schema_model, schema_name)
        path = self.cache_dir / f"{key}.json"
        if self.use_cache and path.exists():
            try:
                cached = json.loads(path.read_text())
                self.stats.bump("cache_hits")
                return schema_model.model_validate(cached["response"])
            except Exception:
                pass  # corrupt cache entry: fall through and re-fetch
        self.stats.bump("calls")
        started = time.time()
        try:
            raw = self.provider.complete(
                model=self.model,
                instructions=instructions,
                user_text=user_text,
                schema_model=schema_model,
                schema_name=schema_name,
            )
            parsed = schema_model.model_validate(raw)
        except Exception as exc:  # provider errors, timeouts, validation errors
            self.stats.bump("failures", f"{schema_name}: {type(exc).__name__}: {exc}")
            raise LLMError(f"{schema_name}: {type(exc).__name__}: {exc}") from exc
        if self.use_cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "model": self.model,
                        "schema_name": schema_name,
                        "latency_s": round(time.time() - started, 3),
                        "response": parsed.model_dump(),
                    },
                    indent=1,
                    sort_keys=True,
                )
            )
            os.replace(tmp, path)
        return parsed
