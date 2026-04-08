FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache "openenv-core[core]>=0.2.2" "fastapi>=0.104.0" "uvicorn[standard]>=0.24.0" "pydantic>=2.0.0" "websockets>=12.0"

COPY . /app/sre_incident_env

RUN cd /app && uv pip install --system --no-cache -e /app/sre_incident_env || true

ENV PYTHONPATH=/app
ENV ENABLE_WEB_INTERFACE=true
ENV SRE_DEFAULT_TASK=easy

EXPOSE 7860

CMD ["uvicorn", "sre_incident_env.server.app:app", "--host", "0.0.0.0", "--port", "7860"]
