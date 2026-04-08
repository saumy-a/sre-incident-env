# ---
# title: SRE Incident Response Environment
# emoji: 🚨
# colorFrom: red
# colorTo: orange
# sdk: docker
# pinned: false
# app_port: 8000
# base_path: /web
# tags:
#   - openenv
# ---

FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv pip install --system --no-cache \
    "openenv-core[core]>=0.2.2" \
    "fastapi>=0.104.0" \
    "uvicorn[standard]>=0.24.0" \
    "pydantic>=2.0.0" \
    "websockets>=12.0" \
    "gradio>=4.0.0"

COPY . /app/sre_incident_env

ENV PYTHONPATH=/app
ENV ENABLE_WEB_INTERFACE=true
ENV SRE_DEFAULT_TASK=easy

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "sre_incident_env.server.app:app", \
     "--host", "0.0.0.0", "--port", "8000"]
