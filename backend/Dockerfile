# Imagen de producción del Asistente Contable DIAN.
# Incluye Tesseract + Poppler (necesarios para el OCR de PDFs escaneados,
# sección 6 de la especificación) — sin esto, el respaldo OCR no
# funcionaría en el servidor aunque sí funcione en tu computador local.
#
# IMPORTANTE: este Dockerfile espera construirse con el CONTEXTO en la
# raíz del repositorio (donde están las carpetas backend/ y frontend/
# una al lado de la otra), no dentro de backend/. En Render, el campo
# "Docker Build Context Directory" debe ser "." (la raíz del repo) y
# "Dockerfile Path" debe ser "backend/Dockerfile".

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend backend
COPY frontend frontend

WORKDIR /app/backend

EXPOSE 8000

COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]
