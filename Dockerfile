FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py index.html ./
COPY static ./static
# roda sem ser root; /dados é onde ficam os arquivos se você não usar PostgreSQL (monte um volume aí)
RUN useradd --create-home app && mkdir -p /dados && chown app /dados
USER app
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8000\")}/api/saude', timeout=4)"
# um processo só: os avisos automáticos e os caches ficam na memória dele
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
