# mdToDocs — servidor FastAPI + frontend estático
FROM python:3.13-slim

WORKDIR /app

# dependências primeiro → cache de camadas só invalida se requirements mudar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# código depois
COPY backend/ backend/
COPY frontend/ frontend/

# usuário sem privilégios (o daemon rootless/normal não importa aqui)
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

# porta interna = 8321 (mesma do host) para casar com o mapeamento do
# CasaOS, que usa uma porta única (target = published = port_map)
EXPOSE 8321

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8321/api/health', timeout=2)"

# frontend é servido pelo próprio FastAPI (main.py monta StaticFiles
# a partir de Path(__file__) — independe do diretório de trabalho)
CMD ["uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8321"]
