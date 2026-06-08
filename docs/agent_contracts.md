# Agent Contracts

## Schema Version

All agent outputs include `"schema_version": "1.0"` and `"generated_at"` (ISO 8601 UTC).

---

## Market Input

```json
{
  "id": 21,
  "polymarket_id": "558936",
  "question": "Will France win the 2026 FIFA World Cup?",
  "category_guess": "sports",
  "yes_price": 0.171,
  "no_price": 0.829,
  "volume": 34068885.5745,
  "liquidity": 863417.7518,
  "end_date": "2026-07-20T00:00:00",
  "quality_score": 100,
  "risk_flag": "analyze",
  "research": {
    "modelable": true,
    "research_priority": "medium",
    "recommended_next_step": "send_to_prediction_agent",
    "notes": []
  }
}
```

---

## Analyst Output (`claude_analyst`)

```json
{
  "schema_version": "1.0",
  "agent_name": "claude_analyst",
  "market_id": 21,
  "generated_at": "2026-06-08T10:15:00Z",
  "estimated_probability": 0.23,
  "confidence": 0.67,
  "recommended_side": "YES",
  "summary": "France stronger than market implies given squad depth and recent form.",
  "key_factors": [
    "Squad depth",
    "Recent form"
  ],
  "risks": [
    "Injuries to key players",
    "Tournament variance"
  ]
}
```

---

## Challenger Output (`openai_challenger`)

```json
{
  "schema_version": "1.0",
  "agent_name": "openai_challenger",
  "market_id": 21,
  "generated_at": "2026-06-08T10:15:05Z",
  "estimated_probability": 0.14,
  "confidence": 0.55,
  "recommended_side": "NO",
  "disagreement_reason": "Analyst may be overweighting historical performance; current squad has key absences.",
  "alternative_view": "Market price already reflects France's reputation premium; true probability is lower."
}
```

---

## Consensus Output (`consensus_agent`)

```json
{
  "schema_version": "1.0",
  "agent_name": "consensus_agent",
  "market_id": 21,
  "generated_at": "2026-06-08T10:15:10Z",
  "market_probability": 0.171,
  "claude_probability": 0.23,
  "challenger_probability": 0.14,
  "consensus_probability": 0.19,
  "edge": 0.019,
  "confidence": 0.61,
  "recommended_side": "YES",
  "decision": "WATCH",
  "reason": "Edge too small relative to confidence level."
}
```

---

## Decision Values

- `BET` — edge is large enough, confidence is sufficient
- `WATCH` — promising but edge or confidence too low
- `SKIP` — no edge or market is not modelable
- `NEEDS_MORE_RESEARCH` — conflicting signals, escalate

## Recommended Side Values

- `YES`
- `NO`
- `NONE`
