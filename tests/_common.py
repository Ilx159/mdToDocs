"""Suporte compartilhado das suítes — scripts puros, sem pytest.

Cada teste importa daqui: monta o sys.path do backend, expõe um
contador de verificações (check/resumo) e helpers de geração de ODT
e requisição HTTP contra o servidor vivo.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# URL do servidor para as suítes HTTP/UI (sobe com ./rodar.sh)
BASE = os.environ.get("MDTODOCS_URL", "http://localhost:8321").rstrip("/")

_ok = 0
_falhas: list[str] = []


def check(cond: object, msg: str) -> None:
    """Registra uma verificação; não aborta — reúne todas as falhas."""
    global _ok
    if cond:
        _ok += 1
        print(f"  ok    {msg}")
    else:
        _falhas.append(msg)
        print(f"  FALHA {msg}")


def resumo(nome: str) -> None:
    """Imprime o resumo da suíte e sai com código 0 (tudo ok) ou 1."""
    total = _ok + len(_falhas)
    print(f"\n{nome}: {_ok}/{total} verificações passaram")
    print(f"SUITE_TOTAL:{_ok}")
    for f in _falhas:
        print(f"  falhou: {f}")
    sys.exit(1 if _falhas else 0)


def gerar(md: str, estilos: dict | None = None,
          math_dims: list | None = None, base_dir=None,
          meta: dict | str | None = None) -> bytes:
    """markdown → bytes do .odt direto pelo pipeline (sem HTTP)."""
    from md_parser import parse
    from odt_writer import render_odt
    return render_odt(parse(md), math_dims=math_dims,
                      base_dir=base_dir, estilos=estilos, meta=meta)


def abrir(odt: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(odt))


def parte(odt: bytes, nome: str) -> str:
    with abrir(odt) as z:
        return z.read(nome).decode("utf-8")


def conteudo(odt: bytes) -> str:
    return parte(odt, "content.xml")


def estilos_xml(odt: bytes) -> str:
    return parte(odt, "styles.xml")


def pictures(odt: bytes) -> list[str]:
    with abrir(odt) as z:
        return [n for n in z.namelist() if n.startswith("Pictures/")]


def png_bytes(largura: int = 4, altura: int = 2,
              cor: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    from PIL import Image as PILImage
    buf = io.BytesIO()
    PILImage.new("RGB", (largura, altura), cor).save(buf, "PNG")
    return buf.getvalue()


def imagem_uri(dados: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(dados).decode()}"


def requisitar(metodo: str, caminho: str, datos: bytes | dict | None = None,
               headers: dict | None = None) -> tuple[int, dict, bytes]:
    """HTTP contra o servidor vivo; devolve (status, headers, corpo).

    Servidor fora do ar → (0, {}, b"") para virar FALHA legível.
    """
    h = dict(headers or {})
    body: bytes | None
    if isinstance(datos, dict):
        body = json.dumps(datos).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    else:
        body = datos
    req = urllib.request.Request(BASE + caminho, data=body,
                                 method=metodo, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except (urllib.error.URLError, OSError):
        return 0, {}, b""


def post_convert(markdown: str, filename: str = "documento",
                 estilos=None, math_dims=None,
                 meta=None) -> tuple[int, dict, bytes]:
    payload: dict = {"markdown": markdown, "filename": filename}
    if estilos is not None:
        payload["estilos"] = estilos
    if math_dims is not None:
        payload["math_dims"] = math_dims
    if meta is not None:
        payload["meta"] = meta
    return requisitar("POST", "/api/convert", datos=payload)
