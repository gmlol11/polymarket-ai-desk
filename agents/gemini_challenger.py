import json
import os
from datetime import datetime, timezone
from typing import Any

import google.generativeai as genai

SCHEMA_VERSION = "1.0"
MODEL = "gemini-2.0-flash"

SYSTEM_PROMPT = """\
You are a prediction market challenger. A primary analyst has already evaluated
a Polymarket binary-outcome question and produced an estimate. Your job is to
steelman the opposite view, find flaws in the analyst's reasoning, and produce
your own independent probability estimate.

Return a single JSON object with exactly these fields:

{
  "estimated_probability": <float 0.0–1.0>,
  "confidence": <float 0.0–1.0>,
  "recommended_side": <"YES" | "NO">,
  "disagreement_reason": <one sentence explaining where you differ>,
  "alternative_view": <one sentence with the key insight the analyst may have missed>
}

Rules:
- estimated_probability is your own best-guess true probability for YES.
- confidence is how sure you are of that estimate.
- recommended_side is YES if estimated_probability > market_price, else NO.
- Be genuinely critical — do not simply echo the analyst.
- Return ONLY the JSON object, no prose."""


def _build_user_message(market: dict[str, Any], analyst: dict[str, Any]) -> str:
    question = market.get("question", "")
    yes_price = market.get("yes_price", "unknown")
    category = market.get("category_guess", "unknown")
    end_date = market.get("end_date", "unknown")
    research = market.get("research", {})
    notes = research.get("notes", [])

    analyst_prob = analyst.get("estimated_probability", "unknown")
    analyst_side = analyst.get("recommended_side", "unknown")
    analyst_summary = analyst.get("summary", "")
    key_factors = analyst.get("key_factors", [])
    risks = analyst.get("risks", [])

    lines = [
        "=== MARKET ===",
        f"Question: {question}",
        f"Category: {category}",
        f"Current market price — YES: {yes_price}",
        f"Resolution date: {end_date}",
    ]
    if notes:
        lines.append("Research notes: " + "; ".join(notes))

    lines += [
        "",
        "=== ANALYST OUTPUT ===",
        f"Estimated probability (YES): {analyst_prob}",
        f"Recommended side: {analyst_side}",
        f"Summary: {analyst_summary}",
        "Key factors: " + "; ".join(key_factors),
        "Risks acknowledged: " + "; ".join(risks),
        "",
        "Challenge the analyst's view and provide your own estimate.",
    ]

    return "\n".join(lines)


def challenge_market(market: dict[str, Any], analyst: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GOOGLE_API_KEY")
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        model_name=MODEL,
        system_instruction=SYSTEM_PROMPT,
    )

    response = model.generate_content(_build_user_message(market, analyst))
    text = response.text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    raw = json.loads(text)

    return {
        "schema_version": SCHEMA_VERSION,
        "agent_name": "gemini_challenger",
        "market_id": market.get("id"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "estimated_probability": float(raw["estimated_probability"]),
        "confidence": float(raw["confidence"]),
        "recommended_side": raw["recommended_side"],
        "disagreement_reason": raw.get("disagreement_reason", ""),
        "alternative_view": raw.get("alternative_view", ""),
    }


def challenge_markets(markets_with_analyst: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Expects each item to already have an "analyst" key from claude_analyst.
    Returns each item with a "challenger" key added.
    """
    results = []
    for item in markets_with_analyst:
        analyst = item.get("analyst") or {}
        try:
            challenger = challenge_market(item, analyst)
        except Exception as exc:
            challenger = {
                "schema_version": SCHEMA_VERSION,
                "agent_name": "gemini_challenger",
                "market_id": item.get("id"),
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "error": str(exc),
            }
        results.append({**item, "challenger": challenger})
    return results
