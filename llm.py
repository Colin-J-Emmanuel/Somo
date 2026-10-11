"""Model router: Gemini first, Claude as automatic failover.

Every model call in Somo goes through `structured()` or `text()`, so failover,
timeouts and provider logging live in one place.
"""
import base64
import os
import sys
import time
from dataclasses import dataclass

from dotenv import load_dotenv
from pydantic import BaseModel

import config

load_dotenv()


@dataclass
class Image:
    data: bytes
    mime: str


_gemini = None
_claude = None


def _gemini_client():
    global _gemini
    if _gemini is None:
        from google import genai
        from google.genai import types
        _gemini = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=config.GEMINI_TIMEOUT_S * 1000),
        )
    return _gemini


def _claude_client():
    global _claude
    if _claude is None:
        import anthropic
        _claude = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=config.CLAUDE_TIMEOUT_S,
            max_retries=1,
        )
    return _claude


def claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _is_transient(error: Exception) -> bool:
    text = str(error).lower()
    return any(s in text for s in ("503", "429", "500", "unavailable", "resource_exhausted", "timeout", "timed out", "deadline"))


# ---------- Gemini ----------

def _gemini_structured(prompt: str, schema: type[BaseModel], image: Image | None, model: str):
    from google.genai import types
    contents = [types.Part.from_bytes(data=image.data, mime_type=image.mime), prompt] if image else prompt
    response = _gemini_client().models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema),
    )
    if response.parsed is not None:
        return response.parsed
    return schema.model_validate_json(response.text)


def _gemini_text(prompt: str, model: str) -> str:
    return _gemini_client().models.generate_content(model=model, contents=prompt).text


# ---------- Claude ----------

def _claude_json_schema(schema: type[BaseModel]) -> dict:
    """Pydantic schema -> Claude structured-output schema (needs additionalProperties: false)."""
    s = schema.model_json_schema()
    s["additionalProperties"] = False
    for definition in s.get("$defs", {}).values():
        definition["additionalProperties"] = False
    return s


def _claude_structured(prompt: str, schema: type[BaseModel], image: Image | None):
    """Claude's native JSON-schema output mode: the reply is guaranteed to match the schema."""
    content = []
    if image:
        if image.mime not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            raise ValueError(f"Claude can't read {image.mime}; use PNG or JPEG photos")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": image.mime, "data": base64.b64encode(image.data).decode()},
        })
    content.append({"type": "text", "text": prompt})
    response = _claude_client().messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
        # sent via extra_body so it works on any anthropic SDK version
        extra_body={"output_config": {"format": {"type": "json_schema", "schema": _claude_json_schema(schema)}}},
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return schema.model_validate_json(text)


def _claude_text(prompt: str) -> str:
    response = _claude_client().messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in response.content if b.type == "text")


# ---------- Router ----------

_gemini_down_until = 0.0  # circuit breaker: skip Gemini until this timestamp


def _route(gemini_call, claude_call, label: str):
    """Try Gemini (one quick retry on a transient error), then Claude. Returns (result, provider)."""
    global _gemini_down_until
    last_error = None
    if time.time() < _gemini_down_until and claude_available():
        start = time.time()
        result = claude_call()
        _log(label, "claude (gemini cooling down)", start)
        return result, "claude"
    for attempt in range(2):
        try:
            start = time.time()
            result = gemini_call()
            _log(label, "gemini", start)
            return result, "gemini"
        except Exception as e:  # noqa: BLE001
            last_error = e
            msg = str(e).lower()
            timed_out = any(s in msg for s in ("timeout", "timed out", "deadline", "504"))
            if timed_out:
                break  # already waited the full budget: don't wait again, fail over now
            if not _is_transient(e) and "validat" not in msg:
                break  # a real error (bad request, bad key): go straight to failover
            if attempt == 0:
                time.sleep(1)  # a quick 503/429: one short retry
    if _is_transient(last_error):
        _gemini_down_until = time.time() + config.GEMINI_COOLDOWN_S
    if claude_available():
        print(f"  [{label}] Gemini failed ({_short(last_error)}), failing over to Claude", file=sys.stderr)
        start = time.time()
        result = claude_call()
        _log(label, "claude", start)
        return result, "claude"
    raise RuntimeError(f"Gemini failed and no ANTHROPIC_API_KEY for failover: {last_error}")


def structured(prompt: str, schema: type[BaseModel], image: Image | None = None):
    return _route(
        lambda: _gemini_structured(prompt, schema, image, config.GEMINI_MODEL),
        lambda: _claude_structured(prompt, schema, image),
        schema.__name__,
    )


def text(prompt: str, gemini_model: str | None = None):
    """Plain text. Defaults to Gemini; pass config.GEMMA_MODEL for cheap checks."""
    model = gemini_model or config.GEMINI_MODEL
    return _route(lambda: _gemini_text(prompt, model), lambda: _claude_text(prompt), model)


def _short(e: Exception) -> str:
    return str(e).split("\n")[0][:80]


def _log(label: str, provider: str, start: float):
    print(f"  [{label}] {provider} {time.time() - start:.1f}s", file=sys.stderr)