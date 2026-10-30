"""Dobles de prueba compartidos.

La base de datos y el proveedor se sustituyen por dobles en memoria: la suite corre
en menos de dos segundos, sin PostgreSQL ni red, y es la misma que corre en el
contenedor de pruebas.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from claims_agent.config import Settings
from claims_agent.providers.base import LLMProvider, LLMResponse, Msg, ToolCall, ToolSpec


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="postgresql://test@localhost/test",
        llm_provider="offline",
        agent_max_iterations=6,
        agent_timeout_seconds=10,
        agent_max_tokens=8000,
        agent_require_confirmation=True,
    )


class FakeDB:
    """Base de datos en memoria con la misma superficie que usa el agente."""

    def __init__(self, policy: dict[str, Any] | None = None, similares: list[dict[str, Any]] | None = None) -> None:
        self.runs: dict[uuid.UUID, dict[str, Any]] = {}
        self.steps: dict[uuid.UUID, list[dict[str, Any]]] = {}
        self.assessments: list[dict[str, Any]] = []
        self.asignaciones: list[tuple] = []
        self._policy = policy
        self._similares = similares or []
        self.fallar_en: str | None = None

    async def create_run(self, claim_id, provider, model):  # type: ignore[no-untyped-def]
        run_id = uuid.uuid4()
        self.runs[run_id] = {"id": run_id, "claim_id": claim_id, "provider": provider, "model": model,
                             "status": "RUNNING", "degraded": False, "iterations": 0,
                             "tokens_in": 0, "tokens_out": 0, "stop_reason": None}
        self.steps[run_id] = []
        return run_id

    async def add_step(self, run_id, *, idx, kind, name=None, detail=None, input=None,  # noqa: A002
                       output=None, latency_ms=0, tokens_in=0, tokens_out=0):  # type: ignore[no-untyped-def]
        import datetime
        self.steps.setdefault(run_id, []).append({
            "run_id": run_id, "idx": idx, "kind": kind, "name": name, "detail": detail,
            "input": input or {}, "output": output or {}, "latency_ms": latency_ms,
            "tokens_in": tokens_in, "tokens_out": tokens_out,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        })

    async def finish_run(self, run_id, *, status, stop_reason, iterations, tokens_in,  # type: ignore[no-untyped-def]
                         tokens_out, latency_ms, degraded, provider, model):
        self.runs[run_id].update(status=status, stop_reason=stop_reason, iterations=iterations,
                                 tokens_in=tokens_in, tokens_out=tokens_out, latency_ms=latency_ms,
                                 degraded=degraded, provider=provider, model=model)

    async def get_run(self, run_id):  # type: ignore[no-untyped-def]
        return self.runs.get(run_id)

    async def get_steps(self, run_id, after_idx: int = -1):  # type: ignore[no-untyped-def]
        return [s for s in self.steps.get(run_id, []) if s["idx"] > after_idx]

    async def get_claim(self, claim_id):  # type: ignore[no-untyped-def]
        return {"id": claim_id, "customer_id": "CUST-000123", "claim_type": "AUTO",
                "description": "Choque con heridos y ambulancia en la autopista"}

    async def get_policy(self, customer_id):  # type: ignore[no-untyped-def]
        if self.fallar_en == "consultar_poliza":
            raise RuntimeError("la base de datos se cayó")
        return self._policy

    async def search_similar(self, description, claim_type, limit=3, exclude=None):  # type: ignore[no-untyped-def]
        return self._similares[:limit]

    async def assign_adjuster(self, claim_id, adjuster, motivo):  # type: ignore[no-untyped-def]
        self.asignaciones.append((claim_id, adjuster, motivo))
        return True

    async def save_assessment(self, **kwargs):  # type: ignore[no-untyped-def]
        self.assessments.append(kwargs)


class ScriptedProvider(LLMProvider):
    """Proveedor que devuelve una lista fija de respuestas o lanza excepciones."""

    name = "scripted"

    def __init__(self, guion: list[Any], model: str = "modelo-de-prueba") -> None:
        self.guion = list(guion)
        self._model = model
        self.llamadas = 0
        self.ultimo_timeout: float | None = None

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, *, system: str, messages: list[Msg], tools: list[ToolSpec],
                       max_output_tokens: int, timeout_seconds: float) -> LLMResponse:
        self.llamadas += 1
        self.ultimo_timeout = timeout_seconds
        siguiente = self.guion.pop(0) if self.guion else _texto("Listo.")
        if isinstance(siguiente, Exception):
            raise siguiente
        if callable(siguiente):
            return siguiente(messages)
        return siguiente


def _texto(t: str, tokens_in: int = 100, tokens_out: int = 20) -> LLMResponse:
    return LLMResponse(text=t, tool_calls=(), tokens_in=tokens_in, tokens_out=tokens_out,
                       model="modelo-de-prueba", raw_finish_reason="STOP")


def _herramienta(nombre: str, argumentos: dict[str, Any], tokens_in: int = 100,
                 tokens_out: int = 20) -> LLMResponse:
    return LLMResponse(text=None, tool_calls=(ToolCall(nombre, argumentos),),
                       tokens_in=tokens_in, tokens_out=tokens_out, model="modelo-de-prueba")


@pytest.fixture
def texto():
    return _texto


@pytest.fixture
def herramienta():
    return _herramienta


@pytest.fixture
def fake_db() -> FakeDB:
    return FakeDB(policy={
        "customer_id": "CUST-000123", "holder_name": "Laura P.", "product": "AUTO",
        "status": "ACTIVE", "coverage_limit": 80000000, "deductible": 800000,
        "valid_from": "2026-01-15", "valid_to": "2027-01-14", "city": "Bogotá", "vigente": True,
    })


@pytest.fixture
def claim() -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "customer_id": "CUST-000123",
        "claim_type": "AUTO",
        "description": "Choque en la autopista, hay dos heridos y llamamos a la ambulancia.",
        "incident_timestamp": "2026-10-22T10:00:00Z",
    }
