FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Sin OCR ni torch en este proyecto: la imagen se mantiene liviana a proposito
# para entrar en los planes gratuitos que nos frenaron la vez pasada.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./

ARG INSTALL_DEV=false
RUN if [ "$INSTALL_DEV" = "true" ]; then \
      pip install -r requirements-dev.txt; \
    else \
      pip install -r requirements.txt; \
    fi

COPY . .
RUN chmod +x start.sh

EXPOSE 8000

# El arranque pasa por un guion porque la forma exec de CMD no expande
# variables, y Railway inyecta el puerto por entorno. Ver backend/start.sh, que
# ademas explica por que va con un solo worker.
CMD ["./start.sh"]
