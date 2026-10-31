"""API FastAPI — expõe a conversão markdown → ODT como serviço HTTP.

Endpoint principal:

    POST /api/convert
    body: {"markdown": "# Título\\n\\nTexto **forte**", "filename": "artigo"}
    resposta: bytes do arquivo .odt (Content-Disposition: attachment)

O servidor é STATELESS: nada é salvo aqui — o download acontece no
navegador do usuário (combina com a decisão de persistir no cliente).

Para rodar, na raiz do projeto:

    .venv/bin/uvicorn main:app --app-dir backend --reload
"""

import hashlib
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from md_parser import parse
from odt_writer import render_odt

app = FastAPI(title="mdToDocs", version="0.1.0")

# media-type oficial do ODF text — faz o navegador tratar como arquivo
ODT_MEDIA_TYPE = "application/vnd.oasis.opendocument.text"


class ConvertRequest(BaseModel):
    markdown: str = Field(..., description="Conteúdo markdown a converter")
    filename: str = Field("documento", description="Nome base do arquivo .odt")
    math_dims: list[tuple[float, float]] | None = Field(
        None,
        description=(
            "Medidas reais das fórmulas do preview em cm "
            "[largura, altura], em ordem de aparição; se ausentes, "
            "o backend estima pelo tamanho do código LaTeX"
        ),
    )
    estilos: dict | None = Field(
        None,
        description=(
            "Estilos do painel (fonte, tamanhos, margens...); "
            "valores ausentes/fora do limite caem no padrão "
            "(ver styles.normalizar)"
        ),
    )
    meta: dict | None = Field(
        None,
        description=(
            "Metadados do documento {titulo, autor, data, capa}; "
            "capa só liga com booleano true (ver metadados.normalizar)"
        ),
    )


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


def _safe_filename(name: str) -> str:
    """Remove caracteres perigosos para o header Content-Disposition."""
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" ._") or "documento"
    if not base.endswith(".odt"):
        base += ".odt"
    return base


@app.post("/api/convert")
def convert(req: ConvertRequest) -> Response:
    """Converte markdown em .odt e devolve os bytes para download."""
    if len(req.markdown) > 2_000_000:
        raise HTTPException(status_code=413, detail="markdown muito grande")

    blocks = parse(req.markdown)
    try:
        data = render_odt(
            blocks, math_dims=req.math_dims, estilos=req.estilos,
            meta=req.meta,
        )
    except ValueError as e:
        # XML invalido gerado internamente — erro de desenvolvimento,
        # mas devolvemos 422 para não derrubar o servidor
        raise HTTPException(status_code=422, detail=str(e)) from e

    filename = _safe_filename(req.filename)
    return Response(
        content=data,
        media_type=ODT_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


# Arquivos estáticos do frontend (index.html, app.js, ...).
# O mount "/" vai DEPOIS das rotas /api — o Starlette casa rotas na ordem
# em que foram registradas, então /api continua com prioridade.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _versao_frontend() -> str:
    """Hash curto do conteúdo do frontend — muda a cada deploy."""
    h = hashlib.sha256()
    for p in sorted(FRONTEND_DIR.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(FRONTEND_DIR)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


VERSAO_FRONTEND = _versao_frontend()

# href/src relativos de .css/.js ganham ?v=<hash> no index servido —
# quebra o cache de browsers/CDN que ainda guardam os arquivos de
# deploys antigos (max-age de 4h), sem exigir hard refresh do usuário
_RECURSO_REF = re.compile(r'((?:href|src)=")([^"?]+\.(?:css|js))(")')


def _resposta_index() -> HTMLResponse:
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = _RECURSO_REF.sub(rf'\g<1>\g<2>?v={VERSAO_FRONTEND}\g<3>', html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return _resposta_index()


@app.get("/index.html", include_in_schema=False)
def index_arquivo() -> HTMLResponse:
    return _resposta_index()


# HTML nunca fica velho e .css/.js revalidam a cada visita (304 quando
# não mudaram): sem isso o Cloudflare/browser servem arquivos de um
# deploy anterior junto com o HTML novo (botões sem estilo/sem ação).
@app.middleware("http")
async def _cache_control_frontend(request, call_next):
    resposta = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resposta.headers["Cache-Control"] = "no-cache"
    return resposta


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
