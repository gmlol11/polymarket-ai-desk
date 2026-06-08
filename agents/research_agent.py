from typing import Any


def research_market(market: dict[str, Any]) -> dict[str, Any]:
    question = (market.get("question") or "").lower()
    category_guess = market.get("category_guess") or "unknown"
    quality_score = int(market.get("quality_score") or 0)
    yes_price = float(market.get("yes_price") or 0)
    liquidity = float(market.get("liquidity") or 0)
    volume = float(market.get("volume") or 0)

    notes = []
    modelable = True
    research_priority = "medium"

    has_weak_proxy = "before gta" in question or "gta vi" in question

    if category_guess == "meme":
        modelable = False
        research_priority = "low"
        notes.append("Market appears meme-like or low-modelability.")

    if has_weak_proxy:
        notes.append("Market uses weak proxy / unusual resolution framing.")
        if category_guess not in ["crypto", "politics"]:
            research_priority = "low"

    if category_guess == "sports":
        notes.append("Sports market with clear resolution criteria.")
        research_priority = "medium"

    if category_guess == "crypto":
        notes.append("Crypto market; external price dynamics and macro context may matter.")
        research_priority = "high"

    if category_guess == "politics":
        notes.append("Politics/geopolitics market; external news and official statements may matter.")
        research_priority = "high"

    if liquidity >= 100000:
        notes.append("High liquidity.")
    elif liquidity < 10000:
        notes.append("Low liquidity; execution risk may be material.")

    if volume >= 1000000:
        notes.append("High volume.")
    elif volume < 10000:
        notes.append("Low volume; market may be noisy.")

    if yes_price <= 0.05 or yes_price >= 0.95:
        notes.append("Price is too close to 0/1; limited upside unless model has strong disagreement.")
        research_priority = "low"

    if quality_score >= 70 and modelable:
        recommended_next_step = "send_to_prediction_agent"
    elif quality_score >= 45:
        recommended_next_step = "watch"
    else:
        recommended_next_step = "skip"

    return {
        **market,
        "research": {
            "modelable": modelable,
            "research_priority": research_priority,
            "recommended_next_step": recommended_next_step,
            "notes": notes,
        },
    }


def research_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [research_market(market) for market in markets]
