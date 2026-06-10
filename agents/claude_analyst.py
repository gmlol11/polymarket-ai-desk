import json
import os
from datetime import datetime, timezone
from typing import Any

import anthropic

SCHEMA_VERSION = "1.0"
MODEL = "claude-opus-4-8"

# Adaptive thinking tokens count toward max_tokens. With the old 1024 budget,
# hard questions (e.g. Fed rate markets) spent nearly the whole budget on
# thinking and the JSON answer was truncated mid-string — the chronic
# "Unterminated string" / "Expecting value" analyst failures.
MAX_TOKENS = 4096

SYSTEM_PROMPT = """\
You are a prediction market analyst. Given a Polymarket binary-outcome market,
estimate the true probability that the event resolves YES, independent of the
current market price. Think carefully, then return a single JSON object with
exactly these fields:

{
  "estimated_probability": <float 0.0–1.0>,
  "confidence": <float 0.0–1.0>,
  "recommended_side": <"YES" | "NO">,
  "summary": <one sentence>,
  "key_factors": [<string>, ...],
  "risks": [<string>, ...]
}

Rules:
- estimated_probability is your best-guess true probability for YES.
- confidence is how sure you are of that estimate (not the probability itself).
- recommended_side is YES if estimated_probability > market_price, else NO.
- key_factors: 2–5 bullet-points supporting your estimate.
- risks: 2–4 things that could make you wrong.
- Return ONLY the JSON object, no prose."""


def _build_user_message(market: dict[str, Any]) -> str:
    question = market.get("question", "")
    yes_price = market.get("yes_price", "unknown")
    no_price = market.get("no_price", "unknown")
    volume = market.get("volume", "unknown")
    liquidity = market.get("liquidity", "unknown")
    end_date = market.get("end_date", "unknown")
    category = market.get("category_guess", "unknown")
    research = market.get("research", {})
    notes = research.get("notes", [])

    lines = [
        f"Question: {question}",
        f"Category: {category}",
        f"Current market price — YES: {yes_price}, NO: {no_price}",
        f"Volume: {volume}",
        f"Liquidity: {liquidity}",
        f"Resolution date: {end_date}",
    ]
    if notes:
        lines.append("Research notes: " + "; ".join(notes))

    return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse model output, tolerating markdown fences or stray prose around the JSON."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def analyze_market(market: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)

    raw = None
    last_exc: Exception | None = None
    for _attempt in range(2):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_user_message(market)}],
        )

        text = "".join(
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        )

        try:
            raw = _extract_json(text)
            break
        except json.JSONDecodeError as exc:
            if response.stop_reason == "max_tokens":
                last_exc = ValueError(
                    f"Response truncated at {MAX_TOKENS} tokens: {exc}"
                )
            else:
                last_exc = exc

    if raw is None:
        raise last_exc if last_exc else ValueError("No JSON in analyst response")

    return {
        "schema_version": SCHEMA_VERSION,
        "agent_name": "claude_analyst",
        "market_id": market.get("id"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "estimated_probability": float(raw["estimated_probability"]),
        "confidence": float(raw["confidence"]),
        "recommended_side": raw["recommended_side"],
        "summary": raw.get("summary", ""),
        "key_factors": raw.get("key_factors", []),
        "risks": raw.get("risks", []),
    }


def analyze_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for market in markets:
        try:
            analysis = analyze_market(market)
        except Exception as exc:
            analysis = {
                "schema_version": SCHEMA_VERSION,
                "agent_name": "claude_analyst",
                "market_id": market.get("id"),
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error": str(exc),
            }
        results.append({**market, "analyst": analysis})
    return results
