"""Recompute every number in RESULTS.md from the CSV files in this folder (stdlib only).

    python3 data/reproduce.py
"""
import csv
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent


def rows(name):
    with open(HERE / f"{name}.csv", newline="") as f:
        return list(csv.DictReader(f))


def num(x):
    return float(x) if x not in ("", None) else None


decisions = rows("decisions")
markets = {m["market_id"]: m for m in rows("markets")}
trades = rows("paper_trades")

print(f"Decisions: {len(decisions)} on {len({d['market_id'] for d in decisions})} markets, "
      f"{decisions[0]['created_at'][:10]} → {decisions[-1]['created_at'][:10]}")
for decision, n in Counter(d["decision"] for d in decisions).most_common():
    print(f"  {decision:<20} {n:>5}  {n / len(decisions):.1%}")

print("\nBoth agents answered (share of decisions):")
by_month = {}
for d in decisions:
    ok = d["claude_probability"] != "" and d["challenger_probability"] != ""
    total, good = by_month.get(d["created_at"][:7], (0, 0))
    by_month[d["created_at"][:7]] = (total + 1, good + ok)
for month, (total, good) in sorted(by_month.items()):
    print(f"  {month}: {good:>4} / {total:<4} {good / total:.0%}")
total_good = sum(g for _, g in by_month.values())
print(f"  all:     {total_good} / {len(decisions)} {total_good / len(decisions):.0%}")

# Brier score on markets whose last price is ≥ 0.97 or ≤ 0.03 (outcome_proxy), decisions where both agents answered.
scored = []
for d in decisions:
    outcome = markets[d["market_id"]]["outcome_proxy"]
    probs = [num(d[k]) for k in ("market_probability", "claude_probability", "challenger_probability", "consensus_probability")]
    if outcome != "" and None not in probs:
        scored.append((d, int(outcome), probs))


def brier(sample, label):
    n = len(sample)
    scores = [sum((p[i] - o) ** 2 for _, o, p in sample) / n for i in range(4)]
    print(f"  {label:<28} n={n:<4} markets={len({d['market_id'] for d, _, _ in sample}):<3} "
          + "  ".join(f"{name} {s:.4f}" for name, s in zip(("market", "claude", "openai", "consensus"), scores)))
    return scores


print("\nBrier score (lower is better):")
all_scores = brier(scored, "all decisions")
first, seen = [], set()
for item in sorted(scored, key=lambda x: x[0]["created_at"]):
    if item[0]["market_id"] not in seen:
        seen.add(item[0]["market_id"])
        first.append(item)
brier(first, "first decision per market")
brier([s for s in scored if 0.10 <= s[2][0] <= 0.90], "market price 10–90%")

closed = [t for t in trades if t["status"] == "closed"]
open_ = [t for t in trades if t["status"] == "open"]
realized = sum(num(t["realized_pnl"]) for t in closed)
unrealized = sum(num(t["unrealized_pnl"]) or 0 for t in open_)
stake = sum(num(t["stake_usd"]) for t in trades)
print(f"\nPaper portfolio: {len(trades)} trades, ${stake:.2f} staked, sides {dict(Counter(t['side'] for t in trades))}")
print(f"  closed {len(closed)}: wins {sum(num(t['realized_pnl']) > 0 for t in closed)}, "
      f"losses {sum(num(t['realized_pnl']) <= 0 for t in closed)}, realized ${realized:+.2f}")
print(f"  open {len(open_)}: unrealized ${unrealized:+.2f}")
print(f"  net ${realized + unrealized:+.2f} ({(realized + unrealized) / stake:+.1%})")

assert all_scores[0] < min(all_scores[1:]), "the market price should beat every agent on resolved markets"
