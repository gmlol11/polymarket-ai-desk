from typing import Any


SPORT_KEYWORDS = [
    "world cup",
    "nba",
    "nhl",
    "fifa",
    "finals",
    "stanley cup",
    "win the",
]

MEME_KEYWORDS = [
    "jesus",
    "album before",
]

WEAK_PROXY_KEYWORDS = [
    "gta",
    "before gta",
]

CRYPTO_KEYWORDS = [
    "bitcoin",
    "btc",
    "ethereum",
    "crypto",
]

GEOPOLITICS_KEYWORDS = [
    "china",
    "taiwan",
    "trump",
    "president",
    "election",
    "war",
    "invade",
    "invades",
]


def classify_market(question: str) -> str:
    q = question.lower()

    if any(keyword in q for keyword in SPORT_KEYWORDS):
        return "sports"

    if any(keyword in q for keyword in CRYPTO_KEYWORDS):
        return "crypto"

    if any(keyword in q for keyword in GEOPOLITICS_KEYWORDS):
        return "politics"

    if any(keyword in q for keyword in MEME_KEYWORDS):
        return "meme"

    return "unknown"


def score_market(market: dict[str, Any]) -> dict[str, Any]:
    question = market.get("question") or ""
    q = question.lower()
    category_guess = classify_market(question)

    liquidity = float(market.get("liquidity") or 0)
    volume = float(market.get("volume") or 0)
    yes_price = float(market.get("yes_price") or 0)

    score = 50
    reasons = []

    if liquidity >= 100000:
        score += 20
        reasons.append("high liquidity")
    elif liquidity >= 10000:
        score += 10
        reasons.append("acceptable liquidity")
    else:
        score -= 20
        reasons.append("low liquidity")

    if volume >= 1000000:
        score += 15
        reasons.append("high volume")
    elif volume >= 10000:
        score += 5
        reasons.append("acceptable volume")
    else:
        score -= 15
        reasons.append("low volume")

    if 0.15 <= yes_price <= 0.85:
        score += 10
        reasons.append("price is in analyzable range")
    else:
        score -= 10
        reasons.append("price is too close to edge")

    if any(keyword in q for keyword in WEAK_PROXY_KEYWORDS):
        score -= 20
        reasons.append("weak proxy / unusual resolution framing")

    if category_guess == "meme":
        score -= 50
        reasons.append("meme / low-modelability market")

    if category_guess == "sports":
        score += 5
        reasons.append("clear sports resolution")

    if category_guess in ["crypto", "politics"]:
        score += 10
        reasons.append("potentially researchable market")

    score = max(0, min(100, score))

    if score >= 70:
        risk_flag = "analyze"
    elif score >= 45:
        risk_flag = "watch"
    else:
        risk_flag = "skip"

    return {
        **market,
        "category_guess": category_guess,
        "quality_score": score,
        "risk_flag": risk_flag,
        "reason": "; ".join(reasons),
    }


def score_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_market(market) for market in markets]
    return sorted(scored, key=lambda item: item["quality_score"], reverse=True)