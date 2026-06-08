from typing import Any

from psycopg.types.json import Jsonb

from backend.db.connection import get_connection


def save_agent_run(
    market_id: int,
    agent_output: dict[str, Any],
    error: str | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_runs
                    (market_id, agent_name, schema_version,
                     estimated_probability, confidence, recommended_side,
                     output_json, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    market_id,
                    agent_output.get("agent_name"),
                    agent_output.get("schema_version"),
                    agent_output.get("estimated_probability"),
                    agent_output.get("confidence"),
                    agent_output.get("recommended_side"),
                    Jsonb(agent_output),
                    error or agent_output.get("error"),
                ),
            )
        conn.commit()


def save_consensus_decision(
    market_id: int,
    consensus_output: dict[str, Any],
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO consensus_decisions
                    (market_id, market_probability, claude_probability,
                     challenger_probability, consensus_probability,
                     edge, confidence, recommended_side, decision, reason,
                     output_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    market_id,
                    consensus_output.get("market_probability"),
                    consensus_output.get("claude_probability"),
                    consensus_output.get("challenger_probability"),
                    consensus_output.get("consensus_probability"),
                    consensus_output.get("edge"),
                    consensus_output.get("confidence"),
                    consensus_output.get("recommended_side"),
                    consensus_output.get("decision"),
                    consensus_output.get("reason"),
                    Jsonb(consensus_output),
                ),
            )
        conn.commit()


def list_agent_runs(limit: int = 20) -> list[dict[str, Any]]:
    limit = min(limit, 100)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, market_id, agent_name, schema_version,
                       estimated_probability, confidence, recommended_side,
                       output_json, error, created_at
                FROM agent_runs
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def list_consensus_decisions(limit: int = 20) -> list[dict[str, Any]]:
    limit = min(limit, 100)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, market_id, market_probability, claude_probability,
                       challenger_probability, consensus_probability,
                       edge, confidence, recommended_side, decision, reason,
                       output_json, created_at
                FROM consensus_decisions
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]


def get_market_agent_history(market_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, agent_name, schema_version,
                       estimated_probability, confidence, recommended_side,
                       output_json, error, created_at
                FROM agent_runs
                WHERE market_id = %s
                ORDER BY created_at DESC
                """,
                (market_id,),
            )
            columns = [desc[0] for desc in cur.description]
            runs = [dict(zip(columns, row)) for row in cur.fetchall()]

            cur.execute(
                """
                SELECT id, market_probability, claude_probability,
                       challenger_probability, consensus_probability,
                       edge, confidence, recommended_side, decision, reason,
                       output_json, created_at
                FROM consensus_decisions
                WHERE market_id = %s
                ORDER BY created_at DESC
                """,
                (market_id,),
            )
            columns = [desc[0] for desc in cur.description]
            decisions = [dict(zip(columns, row)) for row in cur.fetchall()]

    return {"market_id": market_id, "agent_runs": runs, "consensus_decisions": decisions}
