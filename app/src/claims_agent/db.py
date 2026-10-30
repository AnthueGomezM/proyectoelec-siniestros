"""Acceso a PostgreSQL con psycopg 3 (pool asíncrono).

SQL explícito, sin ORM: las consultas son pocas, se leen de un vistazo y cualquiera
del equipo puede explicarlas línea por línea en la sustentación.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)


class Database:
    """Fachada de datos. Una instancia por proceso."""

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 8) -> None:
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            timeout=10,
            max_lifetime=300,
            kwargs={"row_factory": dict_row, "autocommit": True,
                    "application_name": "claims-agent"},
            name="claims-db",
        )

    async def open(self) -> None:
        await self._pool.open(wait=False)

    async def close(self) -> None:
        await self._pool.close()

    async def ping(self) -> bool:
        try:
            async with self._pool.connection(timeout=3) as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception as exc:  # noqa: BLE001 - el health check nunca debe lanzar
            log.warning("La base de datos no responde", extra={"error": str(exc)})
            return False

    # ------------------------------------------------------------------ siniestros

    async def create_claim(self, *, customer_id: str, claim_type: str, description: str,
                           latitude: float | None, longitude: float | None,
                           incident_timestamp: datetime) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO claims (customer_id, claim_type, description, gps_latitude,
                                    gps_longitude, incident_timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, customer_id, claim_type, description, gps_latitude, gps_longitude,
                          incident_timestamp, status, received_at
                """,
                (customer_id, claim_type, description, latitude, longitude, incident_timestamp),
            )
            row = await cur.fetchone()
        return dict(row)  # type: ignore[arg-type]

    async def get_claim(self, claim_id: UUID) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT c.*, a.urgency_level, a.urgency_score, a.keywords, a.inconsistencies,
                       a.inconsistencies_flag, a.recommended_action, a.sla_minutes,
                       a.assigned_adjuster, a.agent_summary, a.provider, a.model,
                       a.run_id, a.assessed_at
                FROM claims c
                LEFT JOIN claim_assessments a ON a.claim_id = c.id
                WHERE c.id = %s
                """,
                (claim_id,),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_claims(self, *, urgency: Sequence[str] | None = None,
                          status: Sequence[str] | None = None,
                          claim_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if urgency:
            where.append("a.urgency_level = ANY(%s)")
            params.append(list(urgency))
        if status:
            where.append("c.status = ANY(%s)")
            params.append(list(status))
        if claim_type:
            where.append("c.claim_type = %s")
            params.append(claim_type)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                SELECT c.id, c.customer_id, c.claim_type, c.description, c.status,
                       c.incident_timestamp, c.received_at, c.estimated_cost,
                       a.urgency_level, a.urgency_score, a.inconsistencies_flag,
                       a.recommended_action, a.assigned_adjuster, a.run_id
                FROM claims c
                LEFT JOIN claim_assessments a ON a.claim_id = c.id
                {clause}
                ORDER BY CASE a.urgency_level
                           WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'LOW' THEN 2 ELSE 3 END,
                         c.received_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def update_status(self, claim_id: UUID, status: str, justification: str | None,
                            user: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute("SELECT status FROM claims WHERE id = %s FOR UPDATE", (claim_id,))
                current = await cur.fetchone()
                if current is None:
                    return None
                await conn.execute(
                    """
                    UPDATE claims
                       SET status = %s, status_reason = %s, reviewed_by = %s,
                           reviewed_at = now(), updated_at = now(), version = version + 1
                     WHERE id = %s
                    """,
                    (status, justification, user, claim_id),
                )
                await conn.execute(
                    """
                    INSERT INTO claim_status_history (claim_id, from_status, to_status, justification, changed_by)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (claim_id, current["status"], status, justification, user),
                )
        return await self.get_claim(claim_id)

    async def history(self, claim_id: UUID) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT from_status, to_status, justification, changed_by, changed_at
                FROM claim_status_history WHERE claim_id = %s ORDER BY changed_at, id
                """,
                (claim_id,),
            )
            return [dict(r) for r in await cur.fetchall()]

    # ------------------------------------------------------------------ herramientas del agente

    async def get_policy(self, customer_id: str) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT customer_id, holder_name, product, status, coverage_limit, deductible,
                       valid_from, valid_to, city,
                       (CURRENT_DATE BETWEEN valid_from AND valid_to) AS vigente
                FROM policies WHERE customer_id = %s
                """,
                (customer_id,),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def search_similar(self, description: str, claim_type: str | None,
                             limit: int = 3, exclude: UUID | None = None) -> list[dict[str, Any]]:
        """Búsqueda de texto completo en español sobre siniestros ya resueltos.

        Alternativa deliberada a un índice vectorial: ver docs/decisiones.md § Datos.
        """
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                SELECT id, claim_type, description, estimated_cost, status, received_at,
                       ROUND(ts_rank(to_tsvector('spanish', description),
                                     plainto_tsquery('spanish', %s))::numeric, 4) AS relevancia
                FROM claims
                WHERE to_tsvector('spanish', description) @@ plainto_tsquery('spanish', %s)
                  AND (%s::text IS NULL OR claim_type = %s)
                  AND (%s::uuid IS NULL OR id <> %s)
                  AND status IN ('APPROVED', 'REJECTED')
                ORDER BY relevancia DESC, received_at DESC
                LIMIT %s
                """,
                (description, description, claim_type, claim_type, exclude, exclude, limit),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def save_assessment(self, *, claim_id: UUID, urgency: str, score: float,
                              keywords: list[dict[str, Any]], inconsistencies: list[dict[str, Any]],
                              action: str, sla_minutes: int | None, summary: str | None,
                              provider: str, model: str, run_id: UUID | None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO claim_assessments (claim_id, urgency_level, urgency_score, keywords,
                                               inconsistencies, inconsistencies_flag, recommended_action,
                                               sla_minutes, agent_summary, provider, model, run_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (claim_id) DO UPDATE SET
                    urgency_level = EXCLUDED.urgency_level,
                    urgency_score = EXCLUDED.urgency_score,
                    keywords = EXCLUDED.keywords,
                    inconsistencies = EXCLUDED.inconsistencies,
                    inconsistencies_flag = EXCLUDED.inconsistencies_flag,
                    recommended_action = EXCLUDED.recommended_action,
                    sla_minutes = EXCLUDED.sla_minutes,
                    agent_summary = EXCLUDED.agent_summary,
                    provider = EXCLUDED.provider,
                    model = EXCLUDED.model,
                    run_id = EXCLUDED.run_id,
                    assessed_at = now()
                """,
                (claim_id, urgency, score, Jsonb(keywords), Jsonb(inconsistencies),
                 bool(inconsistencies), action, sla_minutes, summary, provider, model, run_id),
            )

    async def assign_adjuster(self, claim_id: UUID, adjuster: str, motivo: str) -> bool:
        async with self._pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute("SELECT status FROM claims WHERE id = %s FOR UPDATE", (claim_id,))
                row = await cur.fetchone()
                if row is None:
                    return False
                await conn.execute(
                    "UPDATE claim_assessments SET assigned_adjuster = %s WHERE claim_id = %s",
                    (adjuster, claim_id),
                )
                await conn.execute(
                    """
                    UPDATE claims SET status = 'IN_REVIEW', status_reason = %s, updated_at = now()
                     WHERE id = %s AND status = 'PENDING'
                    """,
                    (motivo, claim_id),
                )
                await conn.execute(
                    """
                    INSERT INTO claim_status_history (claim_id, from_status, to_status, justification, changed_by)
                    VALUES (%s, %s, 'IN_REVIEW', %s, %s)
                    """,
                    (claim_id, row["status"], motivo, f"agente→{adjuster}"),
                )
        return True

    # ------------------------------------------------------------------ trazas

    async def create_run(self, claim_id: UUID | None, provider: str, model: str) -> UUID:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO agent_runs (claim_id, provider, model) VALUES (%s, %s, %s) RETURNING id",
                (claim_id, provider, model),
            )
            row = await cur.fetchone()
        return row["id"]  # type: ignore[index]

    async def add_step(self, run_id: UUID, *, idx: int, kind: str, name: str | None = None,
                       detail: str | None = None, input: dict[str, Any] | None = None,
                       output: dict[str, Any] | None = None, latency_ms: int = 0,
                       tokens_in: int = 0, tokens_out: int = 0) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO agent_steps (run_id, idx, kind, name, detail, input, output,
                                         latency_ms, tokens_in, tokens_out)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id, idx) DO NOTHING
                """,
                (run_id, idx, kind, name, detail, Jsonb(input or {}), Jsonb(output or {}),
                 latency_ms, tokens_in, tokens_out),
            )

    async def finish_run(self, run_id: UUID, *, status: str, stop_reason: str | None,
                         iterations: int, tokens_in: int, tokens_out: int,
                         latency_ms: int, degraded: bool, provider: str, model: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                UPDATE agent_runs
                   SET status = %s, stop_reason = %s, iterations = %s, tokens_in = %s,
                       tokens_out = %s, latency_ms = %s, degraded = %s, provider = %s,
                       model = %s, finished_at = now()
                 WHERE id = %s
                """,
                (status, stop_reason, iterations, tokens_in, tokens_out, latency_ms,
                 degraded, provider, model, run_id),
            )

    async def get_run(self, run_id: UUID) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT * FROM agent_runs WHERE id = %s", (run_id,))
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_steps(self, run_id: UUID, after_idx: int = -1) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM agent_steps WHERE run_id = %s AND idx > %s ORDER BY idx",
                (run_id, after_idx),
            )
            return [dict(r) for r in await cur.fetchall()]

    async def latest_run_for_claim(self, claim_id: UUID) -> dict[str, Any] | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT * FROM agent_runs WHERE claim_id = %s ORDER BY started_at DESC LIMIT 1",
                (claim_id,),
            )
            row = await cur.fetchone()
        return dict(row) if row else None

    async def connection(self) -> AsyncConnection:  # pragma: no cover - utilidad para scripts
        return await self._pool.getconn()
