# syntax=docker/dockerfile:1
# =============================================================================
# Imagen de la aplicación. Una sola etapa: no hay compilación, solo dependencias
# de Python, así que una multi-etapa no ahorraría nada y sí haría el build más lento.
# Contexto de build: la RAÍZ del repositorio.
#   docker build -f app/Dockerfile -t claims-agent .
# =============================================================================
FROM python:3.12-slim

# Capa de dependencias: solo se reconstruye si cambia requirements.txt.
WORKDIR /app
COPY app/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Código de la aplicación (incluye el dashboard en src/claims_agent/web).
COPY app/src ./src

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    APP_PORT=8000

# Usuario sin privilegios: el contenedor no corre como root.
# /data/uploads se crea aquí (con el dueño correcto) porque Docker copia los
# permisos del directorio de la imagen al volumen nombrado la primera vez que se monta.
RUN mkdir -p /data/uploads \
    && useradd --system --uid 10001 --create-home appuser \
    && chown -R appuser /app /data
USER 10001

EXPOSE 8000

# El healthcheck es el que hace que `depends_on: service_healthy` funcione de verdad.
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status==200 else 1)"

CMD ["uvicorn", "--factory", "claims_agent.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
