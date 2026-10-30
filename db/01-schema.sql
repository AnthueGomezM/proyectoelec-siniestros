-- =============================================================================
-- Esquema relacional · Triaje de Siniestros con Agente IA
-- Motor: PostgreSQL 16. Se aplica automáticamente al crear el contenedor de BD
-- (docker-entrypoint-initdb.d). Idempotente: usa IF NOT EXISTS.
--
-- Cinco áreas:
--   1. policies              -> datos de póliza que consulta el agente (herramienta)
--   2. claims                -> siniestros reportados
--   3. claim_assessments     -> resultado del triaje (1:1 con claims)
--   4. agent_runs/steps      -> TRAZAS del agente: una fila por paso, visible en la UI
--   5. claim_status_history  -> auditoría de decisiones humanas
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Pólizas. Fuente de verdad estructurada: por esto NO se usa RAG
--    (ver docs/decisiones.md). La herramienta consultar_poliza hace SELECT exacto.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS policies (
    customer_id     VARCHAR(64)   PRIMARY KEY,
    holder_name     VARCHAR(120)  NOT NULL,
    product         VARCHAR(16)   NOT NULL,
    status          VARCHAR(16)   NOT NULL,
    coverage_limit  NUMERIC(12,2) NOT NULL,
    deductible      NUMERIC(12,2) NOT NULL,
    valid_from      DATE          NOT NULL,
    valid_to        DATE          NOT NULL,
    city            VARCHAR(80),
    CONSTRAINT ck_policies_product CHECK (product IN ('AUTO', 'MEDICAL', 'HOME')),
    CONSTRAINT ck_policies_status  CHECK (status IN ('ACTIVE', 'LAPSED', 'CANCELLED'))
);

-- -----------------------------------------------------------------------------
-- 2. Siniestros. El id es el trackingId que recibe el cliente.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claims (
    id                 UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id        VARCHAR(64)   NOT NULL,
    claim_type         VARCHAR(16)   NOT NULL,
    description        VARCHAR(5000) NOT NULL,
    gps_latitude       NUMERIC(9,6),
    gps_longitude      NUMERIC(9,6),
    incident_timestamp TIMESTAMPTZ   NOT NULL,
    estimated_cost     NUMERIC(12,2),
    status             VARCHAR(16)   NOT NULL DEFAULT 'PENDING',
    status_reason      VARCHAR(2000),
    reviewed_by        VARCHAR(64),
    reviewed_at        TIMESTAMPTZ,
    received_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT now(),
    version            BIGINT        NOT NULL DEFAULT 0,
    CONSTRAINT ck_claims_type   CHECK (claim_type IN ('AUTO', 'MEDICAL', 'HOME')),
    CONSTRAINT ck_claims_status CHECK (status IN ('PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED')),
    CONSTRAINT ck_claims_lat    CHECK (gps_latitude  IS NULL OR gps_latitude  BETWEEN -90  AND 90),
    CONSTRAINT ck_claims_lon    CHECK (gps_longitude IS NULL OR gps_longitude BETWEEN -180 AND 180)
);

CREATE INDEX IF NOT EXISTS idx_claims_status_received ON claims (status, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_claims_customer        ON claims (customer_id, received_at DESC);

-- Búsqueda de siniestros parecidos SIN embeddings: índice de texto completo en español.
-- Es determinista, explicable y no necesita servicio de vectores (ver docs/decisiones.md).
CREATE INDEX IF NOT EXISTS idx_claims_fts
    ON claims USING GIN (to_tsvector('spanish', description));

-- -----------------------------------------------------------------------------
-- 3. Evaluación del triaje. UNIQUE(claim_id) hace idempotente el reproceso:
--    si el agente corre dos veces sobre el mismo siniestro, se actualiza, no se duplica.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claim_assessments (
    claim_id              UUID          PRIMARY KEY REFERENCES claims (id) ON DELETE CASCADE,
    urgency_level         VARCHAR(16)   NOT NULL,
    urgency_score         NUMERIC(8,2)  NOT NULL DEFAULT 0,
    keywords              JSONB         NOT NULL DEFAULT '[]',
    inconsistencies       JSONB         NOT NULL DEFAULT '[]',
    inconsistencies_flag  BOOLEAN       NOT NULL DEFAULT false,
    recommended_action    VARCHAR(32)   NOT NULL,
    sla_minutes           INTEGER,
    assigned_adjuster     VARCHAR(64),
    agent_summary         TEXT,
    provider              VARCHAR(32)   NOT NULL,
    model                 VARCHAR(64)   NOT NULL,
    run_id                UUID,
    assessed_at           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT ck_assessment_urgency CHECK (urgency_level IN ('CRITICAL', 'HIGH', 'LOW')),
    CONSTRAINT ck_assessment_action  CHECK (recommended_action IN
        ('ASSIGN_AGENT_IMMEDIATELY', 'HUMAN_VALIDATION_2H', 'AUTO_APPROVE', 'FAST_TRACK_REVIEW', 'MANUAL_REVIEW'))
);

CREATE INDEX IF NOT EXISTS idx_assessments_urgency ON claim_assessments (urgency_level, assessed_at DESC);

-- -----------------------------------------------------------------------------
-- 4. TRAZAS DEL AGENTE. Una fila por corrida y una por paso.
--    Todo lo que la UI muestra en vivo sale de estas dos tablas: nada es simulado.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_runs (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id        UUID         REFERENCES claims (id) ON DELETE CASCADE,
    provider        VARCHAR(32)  NOT NULL,
    model           VARCHAR(64)  NOT NULL,
    status          VARCHAR(24)  NOT NULL DEFAULT 'RUNNING',
    stop_reason     VARCHAR(64),
    degraded        BOOLEAN      NOT NULL DEFAULT false,
    iterations      INTEGER      NOT NULL DEFAULT 0,
    tokens_in       INTEGER      NOT NULL DEFAULT 0,
    tokens_out      INTEGER      NOT NULL DEFAULT 0,
    latency_ms      INTEGER,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    CONSTRAINT ck_run_status CHECK (status IN
        ('RUNNING', 'COMPLETED', 'FAILED', 'AWAITING_CONFIRMATION', 'LIMIT_REACHED'))
);

CREATE INDEX IF NOT EXISTS idx_runs_claim ON agent_runs (claim_id, started_at DESC);

CREATE TABLE IF NOT EXISTS agent_steps (
    id          BIGSERIAL    PRIMARY KEY,
    run_id      UUID         NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    idx         INTEGER      NOT NULL,
    kind        VARCHAR(24)  NOT NULL,
    name        VARCHAR(64),
    detail      TEXT,
    input       JSONB        NOT NULL DEFAULT '{}',
    output      JSONB        NOT NULL DEFAULT '{}',
    latency_ms  INTEGER      NOT NULL DEFAULT 0,
    tokens_in   INTEGER      NOT NULL DEFAULT 0,
    tokens_out  INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_step_kind CHECK (kind IN
        ('llm_call', 'tool_call', 'limit', 'error', 'confirmation', 'fallback', 'final'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_steps_run_idx ON agent_steps (run_id, idx);

-- -----------------------------------------------------------------------------
-- 5. Auditoría de decisiones (automáticas y humanas).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claim_status_history (
    id             BIGSERIAL     PRIMARY KEY,
    claim_id       UUID          NOT NULL REFERENCES claims (id) ON DELETE CASCADE,
    from_status    VARCHAR(16),
    to_status      VARCHAR(16)   NOT NULL,
    justification  VARCHAR(2000),
    changed_by     VARCHAR(64)   NOT NULL,
    changed_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_history_claim ON claim_status_history (claim_id, changed_at);
