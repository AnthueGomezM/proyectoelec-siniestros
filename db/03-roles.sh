#!/bin/sh
# =============================================================================
# Rol de SOLO LECTURA para las herramientas del agente (mínimo privilegio).
#
# Por qué: el agente lee texto que escribe un desconocido (el relato del siniestro). Si una
# inyección o una alucinación lo desvía, lo que pueda hacer lo decide la BASE DE DATOS, no el
# prompt. Este rol solo puede leer lo estrictamente necesario:
#
#   agent_policies (vista)  -> la póliza SIN el nombre del titular
#   claims (6 columnas)     -> lo que usa la búsqueda de siniestros parecidos
#   claim_attachments       -> ruta y tipo de la foto (para analizarla)
#
# No ve hashes, correos, datos de titulares ni el historial; no puede escribir, aunque lo
# intente (default_transaction_read_only). La única escritura del agente, asignar_ajustador,
# la hace la conexión normal de la app y solo tras la aprobación de una persona.
#
# Se ejecuta solo al crear el volumen de la base. En una base que ya existe (idempotente):
#     docker compose exec db sh /docker-entrypoint-initdb.d/03-roles.sh
# =============================================================================
set -e

: "${AGENT_DB_PASSWORD:?Falta AGENT_DB_PASSWORD (contraseña del rol claims_agent_ro)}"

psql -v ON_ERROR_STOP=1 -v agent_pwd="$AGENT_DB_PASSWORD" \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'

-- Crear el rol si no existe; fijar siempre la contraseña (permite rotarla).
SELECT format('CREATE ROLE claims_agent_ro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'agent_pwd')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claims_agent_ro') \gexec
SELECT format('ALTER ROLE claims_agent_ro PASSWORD %L', :'agent_pwd') \gexec

-- Aunque alguien lograra ejecutar un INSERT/UPDATE con este rol, la sesión lo rechaza.
ALTER ROLE claims_agent_ro SET default_transaction_read_only = on;

-- Vista enmascarada: la póliza sin holder_name. Se evalúa con los permisos de su dueño,
-- así el rol no necesita ningún acceso a la tabla policies.
CREATE OR REPLACE VIEW agent_policies AS
    SELECT customer_id, product, status, coverage_limit, deductible, valid_from, valid_to, city,
           (CURRENT_DATE BETWEEN valid_from AND valid_to) AS vigente
      FROM policies;

-- Partir de cero y conceder solo lo necesario.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM claims_agent_ro;
GRANT USAGE ON SCHEMA public TO claims_agent_ro;
GRANT SELECT ON agent_policies TO claims_agent_ro;
GRANT SELECT (id, claim_type, description, estimated_cost, status, received_at) ON claims TO claims_agent_ro;
GRANT SELECT (claim_id, file_path, mime_type, size_bytes) ON claim_attachments TO claims_agent_ro;
SQL

echo "03-roles: rol claims_agent_ro listo (solo lectura)."
