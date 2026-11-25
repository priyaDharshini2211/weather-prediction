"""Thin wrapper around any OpenAI-compatible chat endpoint (Ollama, Groq, vLLM, ...)."""
import json
import logging
import re
import time
from functools import lru_cache

from django.conf import settings
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, BadRequestError, OpenAI

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The language model could not be reached or returned unusable output."""


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    return OpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY, timeout=settings.LLM_TIMEOUT)


RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6


def _create_with_retry(**kwargs):
    """Hosted models regularly answer 429/503 under load; retry with exponential backoff before giving up."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _client().chat.completions.create(**kwargs)
        except APIStatusError as error:
            if error.status_code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                raise
            logger.warning("LLM returned %s, retrying (%d/%d)", error.status_code, attempt, MAX_ATTEMPTS)
            time.sleep(min(2 * attempt, 8))


def chat(messages: list[dict], *, temperature: float = 0.2, json_mode: bool = False, max_tokens: int = 900) -> str:
    # Reasoning models (Gemma 4, Gemini 3.x ...) spend part of max_tokens on hidden "thinking"; reserve room for it.
    budget = max_tokens + settings.LLM_REASONING_TOKENS
    kwargs = {"model": settings.LLM_MODEL, "messages": messages, "temperature": temperature, "max_tokens": budget}
    try:
        try:
            if json_mode:
                response = _create_with_retry(**kwargs, response_format={"type": "json_object"})
            else:
                response = _create_with_retry(**kwargs)
        except BadRequestError:
            if not json_mode:
                raise
            # Some servers do not support response_format; the prompt still asks for JSON.
            response = _create_with_retry(**kwargs)
    except (APIConnectionError, APITimeoutError) as error:
        raise LLMError(f"cannot reach {settings.LLM_BASE_URL} ({type(error).__name__}). Is the model server running?") from error
    except APIError as error:
        raise LLMError(f"model server returned an error: {getattr(error, 'message', error)}") from error

    content = strip_reasoning(response.choices[0].message.content or "")
    if not content:
        raise LLMError("the model returned an empty response")
    return content


def strip_reasoning(text: str) -> str:
    """Remove <thought>/<think> blocks some reasoning models inline into the reply (including unterminated ones)."""
    text = re.sub(r"<(thought|think)>.*?</\1>", "", text, flags=re.DOTALL)
    text = re.sub(r"<(thought|think)>.*", "", text, flags=re.DOTALL)  # cut off mid-thought
    return text.strip()


def chat_json(messages: list[dict], *, temperature: float = 0.0, max_tokens: int = 500) -> dict:
    """Ask for a JSON object and parse it tolerantly (models sometimes wrap it in prose or code fences)."""
    raw = chat(messages, temperature=temperature, json_mode=True, max_tokens=max_tokens)
    return parse_json_object(raw)


def parse_json_object(raw: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("the model did not return a JSON object")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise LLMError("the model returned malformed JSON") from error
    if not isinstance(parsed, dict):
        raise LLMError("the model returned JSON that is not an object")
    return parsed
