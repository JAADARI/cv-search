"""Thin, typed wrapper around the Azure OpenAI chat API behind APIM.

Responsibilities: authentication header, retries with backoff on transient
errors, strict JSON-schema structured output, optional image inputs, and
token accounting. Everything else (prompts, schemas) lives in callers.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    AzureOpenAI,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from cvsearch.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_TRANSIENT = (RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)


class LLMError(RuntimeError):
    """Raised when the model returns an unusable answer."""


@dataclass(frozen=True)
class ImageInput:
    """A PNG image sent to the vision-capable model."""

    png_bytes: bytes

    def as_content(self) -> dict[str, Any]:
        encoded = base64.b64encode(self.png_bytes).decode()
        return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Replace ``$ref`` nodes by their definition; strict mode forbids keywords next to a ``$ref``."""
    if isinstance(node, dict):
        if "$ref" in node:
            target = _inline_refs(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            return {**target, **siblings}
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _harden(schema: dict[str, Any]) -> None:
    """Close every object and require all its properties, as strict mode demands.

    Walks schema nodes only: the keys of a ``properties`` mapping are field names,
    which may collide with schema keywords (for example a field called ``title``).
    """
    schema.pop("default", None)
    schema.pop("title", None)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        schema["additionalProperties"] = False
        schema["required"] = list(properties)
        for child in properties.values():
            _harden(child)
    if isinstance(schema.get("items"), dict):
        _harden(schema["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        for child in schema.get(key, []):
            _harden(child)


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema accepted by OpenAI strict structured output."""
    raw = model.model_json_schema()
    schema = _inline_refs(raw, raw.get("$defs", {}))
    _harden(schema)
    return schema  # type: ignore[no-any-return]


class LLMClient:
    """Chat completions with structured output."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AzureOpenAI(
            api_version=settings.openai_api_version,
            azure_endpoint=settings.apim_base_url,
            api_key="placeholder",  # required by the SDK; APIM reads the header below
            default_headers={"Ocp-Apim-Subscription-Key": settings.apim_subscription_key.get_secret_value()},
            timeout=settings.llm_timeout_seconds,
            max_retries=0,  # retries are handled by tenacity below
        )

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        wait=wait_random_exponential(multiplier=4, max=60),
        stop=stop_after_attempt(8),
        reraise=True,
    )
    def _complete(self, **kwargs: Any) -> Any:
        return self._client.chat.completions.create(
            model=self._settings.chat_deployment,
            max_completion_tokens=self._settings.max_completion_tokens,
            **kwargs,
        )

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        images: list[ImageInput] | None = None,
        reasoning_effort: str = "low",
    ) -> T:
        """Ask the model for an answer conforming to ``schema``."""
        content: list[dict[str, Any]] | str = (
            [{"type": "text", "text": user}, *(img.as_content() for img in images)] if images else user
        )
        response = self._complete(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": content}],
            reasoning_effort=reasoning_effort,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "strict": True, "schema": strict_schema(schema)},
            },
        )
        choice = response.choices[0]
        usage = response.usage
        logger.info(
            "llm_call schema=%s prompt_tokens=%s completion_tokens=%s finish=%s",
            schema.__name__,
            usage.prompt_tokens,
            usage.completion_tokens,
            choice.finish_reason,
        )
        if choice.finish_reason != "stop" or not choice.message.content:
            raise LLMError(f"Unusable model answer (finish_reason={choice.finish_reason})")
        return schema.model_validate_json(choice.message.content)

    def transcribe(self, images: list[ImageInput]) -> str:
        """Transcribe document images to plain text, one request per image.

        Requests are kept small on purpose: the gateway answers 413 to large multi-image payloads.
        """
        parts = [self._transcribe_one(image) for image in images]
        text = "\n\n".join(part for part in parts if part)
        if not text.strip():
            raise LLMError("Vision transcription returned no text")
        return text

    def _transcribe_one(self, image: ImageInput) -> str:
        response = self._complete(
            messages=[
                {
                    "role": "system",
                    "content": "You are an OCR engine. Transcribe the image verbatim, in natural reading order. "
                    "Output the text only, no commentary. If the image has no text, output nothing.",
                },
                {"role": "user", "content": [{"type": "text", "text": "Transcribe."}, image.as_content()]},
            ],
            reasoning_effort="minimal",
        )
        return (response.choices[0].message.content or "").strip()
