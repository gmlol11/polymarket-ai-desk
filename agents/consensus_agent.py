from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "1.0"

MIN_EDGE_TO_BET = 0.05
MIN_CONFIDENCE_TO_BET = 0.65
MIN_EDGE_TO_WATCH = 0.02


def _consensus_probability(claude_prob: float, challenger_prob: float) -> float:
    return round((claude_prob + challenger_prob) / 2, 4)


def _edge(consensus_prob: float, market_prob: float, recommended_side: str) -> float:
    if recommended_side == "YES":
        return round(consensus_prob - market_prob, 4)
    if recommended_side == "NO":
        return round((1 - market_prob) - (1 - consensus_prob), 4)
    return 0.0


def _resolve_side(claude_side: str, challenger_side: str, consensus_prob: float, market_prob: float) -> str:
    if claude_side == challenger_side and claude_side in ("YES", "NO"):
        return claude_side
    # disagreement — fall back to whether consensus is above or below market
    if consensus_prob > market_prob:
        return "YES"
    if consensus_prob < market_prob:
        return "NO"
    return "NONE"


def _average_confidence(claude_confidence: float, challenger_confidence: float) -> float:
    return round((claude_confidence + challenger_confidence) / 2, 4)


def _make_decision(
    edge: float, confidence: float, modelable: bool, sides_agree: bool = True
) -> str:
    if not modelable:
        return "SKIP"
    if edge >= MIN_EDGE_TO_BET and confidence >= MIN_CONFIDENCE_TO_BET:
        if sides_agree:
            return "BET"
        return "NEEDS_MORE_RESEARCH"  # good numbers but agents disagree on direction
    if edge >= MIN_EDGE_TO_WATCH:
        return "WATCH"
    if edge < 0:
        return "SKIP"
    return "NEEDS_MORE_RESEARCH"


def _decision_reason(
    decision: str, edge: float, confidence: float, modelable: bool, sides_agree: bool = True
) -> str:
    if not modelable:
        return "Market is not modelable."
    if decision == "BET":
        return f"Edge {edge:.3f}, confidence {confidence:.2f}, agents agree on direction."
    if decision == "WATCH":
        if confidence < MIN_CONFIDENCE_TO_BET:
            return f"Edge {edge:.3f} is acceptable but confidence {confidence:.2f} is below threshold."
        return f"Edge {edge:.3f} too small to bet."
    if decision == "SKIP":
        return f"No positive edge (edge={edge:.3f})."
    if not sides_agree:
        return "Agents disagree on direction — needs more research."
    return "Conflicting signals between analyst and challenger."


def build_consensus(analyst: dict[str, Any], challenger: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    market_prob = float(market.get("yes_price") or 0)
    modelable = market.get("research", {}).get("modelable", True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    analyst_failed = "error" in analyst
    challenger_failed = "error" in challenger

    if analyst_failed:
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_name": "consensus_agent",
            "market_id": market.get("id"),
            "generated_at": now,
            "market_probability": round(market_prob, 4),
            "decision": "NEEDS_MORE_RESEARCH",
            "reason": f"Analyst failed: {analyst.get('error', 'unknown error')}",
        }

    claude_prob = float(analyst.get("estimated_probability") or 0)
    claude_side = analyst.get("recommended_side") or "NONE"
    claude_confidence = float(analyst.get("confidence") or 0)

    if challenger_failed:
        # Analyst-only fallback: lower confidence, no side agreement possible
        consensus_prob = claude_prob
        recommended_side = claude_side
        edge = _edge(consensus_prob, market_prob, recommended_side)
        confidence = round(claude_confidence * 0.75, 4)
        decision = _make_decision(edge, confidence, modelable, sides_agree=False)
        reason = f"Challenger unavailable — analyst-only. {_decision_reason(decision, edge, confidence, modelable, sides_agree=False)}"
        return {
            "schema_version": SCHEMA_VERSION,
            "agent_name": "consensus_agent",
            "market_id": market.get("id"),
            "generated_at": now,
            "market_probability": round(market_prob, 4),
            "claude_probability": claude_prob,
            "challenger_probability": None,
            "consensus_probability": consensus_prob,
            "edge": edge,
            "confidence": confidence,
            "recommended_side": recommended_side,
            "decision": decision,
            "reason": reason,
        }

    challenger_prob = float(challenger.get("estimated_probability") or 0)
    challenger_side = challenger.get("recommended_side") or "NONE"
    challenger_confidence = float(challenger.get("confidence") or 0)

    sides_agree = claude_side == challenger_side and claude_side in ("YES", "NO")

    consensus_prob = _consensus_probability(claude_prob, challenger_prob)
    recommended_side = _resolve_side(claude_side, challenger_side, consensus_prob, market_prob)
    edge = _edge(consensus_prob, market_prob, recommended_side)
    confidence = _average_confidence(claude_confidence, challenger_confidence)
    decision = _make_decision(edge, confidence, modelable, sides_agree)

    return {
        "schema_version": SCHEMA_VERSION,
        "agent_name": "consensus_agent",
        "market_id": market.get("id"),
        "generated_at": now,
        "market_probability": round(market_prob, 4),
        "claude_probability": claude_prob,
        "challenger_probability": challenger_prob,
        "consensus_probability": consensus_prob,
        "edge": edge,
        "confidence": confidence,
        "recommended_side": recommended_side,
        "decision": decision,
        "reason": _decision_reason(decision, edge, confidence, modelable, sides_agree),
    }


def run_consensus(
    markets_with_analyses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Expects each item to have:
      - market fields (id, yes_price, research, ...)
      - "analyst": claude_analyst output dict
      - "challenger": openai_challenger output dict
    """
    results = []
    for item in markets_with_analyses:
        analyst = item.get("analyst") or {}
        challenger = item.get("challenger") or {}
        consensus = build_consensus(analyst, challenger, item)
        results.append({**item, "consensus": consensus})
    return results
