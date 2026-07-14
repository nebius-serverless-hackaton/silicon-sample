import asyncio
import random

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAI,
)

from silicon.core.config import get_settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        api_key=settings.nebius_tokenfactory_api_key,
        base_url=settings.nebius_base_url,
    )


def async_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.nebius_tokenfactory_api_key,
        base_url=settings.nebius_base_url,
    )


async def ask(
    client: AsyncOpenAI,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    attempts: int = 5,
    base_delay: float = 1.0,
) -> tuple[str, int, int]:
    """Transport-level retry loop only; contract-level re-asks live in the runner."""
    delay = base_delay
    last: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            await asyncio.sleep(delay * (1 + random.random()))
            delay = min(delay * 2, 30)
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage = resp.usage
            return (
                resp.choices[0].message.content or "",
                usage.prompt_tokens if usage else 0,
                usage.completion_tokens if usage else 0,
            )
        except (APIConnectionError, APITimeoutError) as e:
            last = e
        except APIStatusError as e:
            if e.status_code not in RETRYABLE_STATUS:
                raise
            last = e
            retry_after = e.response.headers.get("retry-after")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
    raise last  # type: ignore[misc]


def check_llm_roundtrip(model: str | None = None) -> str:
    settings = get_settings()
    model_id = model or settings.nebius_tokenfactory_model_dev

    response = client().chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": "Reply with exactly one word: pong"}],
        max_tokens=8,
    )
    text = (response.choices[0].message.content or "").strip()
    return f"OK - model={model_id} replied: {text!r}"
