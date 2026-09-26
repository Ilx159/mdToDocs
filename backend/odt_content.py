"""Converte a árvore de blocos (md_parser) em content.xml.

Mapeamento bloco → ODF:

    Heading    → <text:h text:outline-level="N">   (título com nível de sumário)
    Paragraph  → <text:p>                          (parágrafo)
    Strong     → <text:span text:style-name="Strong">
    Link       → <text:a xlink:href="...">
    CodeBlock  → <text:p style=CodeBlock> com <text:line-break/> entre linhas
    Listas     → <text:list text:style-name="BulletList|OrderedList">
    Blockquote → filhos com estilo "Blockquote"
    Table      → <table:table> com colunas/células estilizadas
    HRule      → <text:p text:style-name="HorizontalRule">
    PageBreak  → <text:p text:style-name="PageBreak">  (quebra de página)
    Toc        → parágrafos Toc1..Toc6 com links p/ bookmarks
    Numbering  → (nada — a numeração já está nos Heading)
    FootnoteRef→ <text:note> (nota real de página; o corpo carrega a definição)
    Footnotes  → (nada — as definições só existem dentro das <text:note>)
    Math       → <draw:frame><draw:object> apontando para "Object N"
                 (parte do ZIP com o MathML da fórmula)
    Image      → <draw:frame><draw:image> apontando para "Pictures/imgN"
                 (binário embutido no ZIP pelo odt_writer)

A geração de fórmula e de imagem tem EFEITO COLATERAL: além do
content.xml, ela acumula arquivos extras ("Object N/content.xml" e
"Pictures/imgN.png") que o odt_writer embute no ZIP — por isso
build_content_xml devolve (xml, objetos, imagens).
"""

import base64
import ipaddress
import logging
import os
import re
import socket
import struct
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

import latex2mathml.converter

from md_parser import (
    Block,
    Blockquote,
    BulletList,
    CodeBlock,
    Emph,
    Heading,
    HorizontalRule,
    FootnoteRef,
    Footnotes,
    Image,
    Inline,
    InlineCode,
    LineBreak,
    Link,
    ListItem,
    MathBlock,
    MathInline,
    Numbering,
    OrderedList,
    PageBreak,
    Paragraph,
    Softbreak,
    Strong,
    Table,
    TableCell,
    TableRow,
    Text,
    Toc,
)
from styles import normalizar as normalizar_estilos

logger = logging.getLogger(__name__)

# Namespaces usados no content.xml.
# Cada prefixo precisa estar declarado aqui (draw:/svg: entram com a
# fórmula — o quadro da fórmula é <draw:frame> com svg:width/height).
NAMESPACES = """\
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    xmlns:xlink="http://www.w3.org/1999/xlink"
    xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
    xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0\""""

# Estilos de lista vivem em automatic-styles (só existem neste documento).
# Levels 1..3 com marcadores/números diferentes.
_LIST_STYLES = """\
    <text:list-style style:name="BulletList">
      <text:list-level-style-bullet text:level="1" text:bullet-char="•">
        <style:list-level-properties text:space-before="0.75cm" text:min-label-width="0.75cm"/>
      </text:list-level-style-bullet>
      <text:list-level-style-bullet text:level="2" text:bullet-char="◦">
        <style:list-level-properties text:space-before="1.5cm" text:min-label-width="0.75cm"/>
      </text:list-level-style-bullet>
      <text:list-level-style-bullet text:level="3" text:bullet-char="▪">
        <style:list-level-properties text:space-before="2.25cm" text:min-label-width="0.75cm"/>
      </text:list-level-style-bullet>
    </text:list-style>
    <text:list-style style:name="OrderedList">
      <text:list-level-style-number text:level="1" style:num-format="1" style:num-suffix=".">
        <style:list-level-properties text:space-before="0.75cm" text:min-label-width="0.75cm"/>
      </text:list-level-style-number>
      <text:list-level-style-number text:level="2" style:num-format="1" style:num-suffix=".">
        <style:list-level-properties text:space-before="1.5cm" text:min-label-width="0.75cm"/>
      </text:list-level-style-number>
      <text:list-level-style-number text:level="3" style:num-format="1" style:num-suffix=".">
        <style:list-level-properties text:space-before="2.25cm" text:min-label-width="0.75cm"/>
      </text:list-level-style-number>
    </text:list-style>"""


# Alinhamento de parágrafo usado pelas células de tabela.
_ALIGN_STYLES = """\
    <style:style style:name="TLeft" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:text-align="left"/>
    </style:style>
    <style:style style:name="TCenter" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:text-align="center"/>
    </style:style>
    <style:style style:name="TRight" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:text-align="right"/>
    </style:style>"""

# Estilos dinâmicos: cada tabela gera seu próprio estilo de coluna/célula
# (a largura da coluna depende do número de colunas). Preenchido durante
# a geração do corpo e despejado em automatic-styles no final.
_auto_styles: list[str] = []
_table_seq = 0
_note_seq = 0    # gerador de text:id único por nota (ftn1, ftn2, ...)
_object_seq = 0  # gerador de "Object N" por fórmula

# Arquivos extras do pacote: (nome_da_pasta, mathml) — fórmulas ODF.
# O odt_writer lê isto depois de build_content_xml e embute no ZIP.
objetos: list[tuple[str, str]] = []

# Dimensões reais das fórmulas, medidas no preview pelo navegador
# (cm) e enviadas no POST /api/convert. Fila consumida em ordem de
# geração do XML; vazia/ausente → estimativa pelo código LaTeX.
_dims_fila: list[tuple[float, float]] = []

# ---------- imagens ----------
#
# ![alt](src) vira <draw:frame> + <draw:image> apontando para
# "Pictures/imgN.<ext>"; o binário vai para `imagens` e o odt_writer
# embute no ZIP + declara no manifesto.

_MAX_IMAGEM = 10 * 1024 * 1024   # teto por imagem (bytes)
_TIMEOUT_URL = 10                # segundos ao buscar imagem remota

# extensão → media-type declarado no manifesto ODF
_EXT_MEDIA_TYPE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "bmp": "image/bmp",
}

# (caminho no ZIP, binário, media-type) — lido pelo odt_writer
imagens: list[tuple[str, bytes, str]] = []
# src → (caminho, largura_cm, altura_cm): mesma imagem duas vezes = 1 cópia
_imagem_cache: dict[str, tuple[str, float, float]] = {}
_imagem_seq = 0
# pasta do .md no CLI (permite caminho relativo "foto.png");
# None na API — o servidor não tem acesso ao disco do usuário
_base_dir: Path | None = None

# área útil da página (cm) — derivada da margem do painel de estilos:
# largura = 21cm − 2×margem (padrão 2cm → 17cm) e altura = min(24cm,
# 29.7cm − 2×margem). Usada por tabelas, fórmulas e imagens.
_largura_util = 17.0
_altura_util = 24.0

# Estilo do quadro da fórmula (copiado do que o LibreOffice gera).
_FR1_STYLE = """\
    <style:style style:name="fr1" style:family="graphic">
      <style:graphic-properties fo:margin-left="0cm" fo:margin-right="0cm"
                                fo:margin-top="0cm" fo:margin-bottom="0cm"
                                style:vertical-pos="middle"
                                style:vertical-rel="text"
                                draw:ole-draw-aspect="1"/>
    </style:style>"""


def _reset_auto_styles() -> None:
    global _table_seq, _note_seq, _object_seq, _imagem_seq, _base_dir
    global _largura_util, _altura_util
    _auto_styles.clear()
    objetos.clear()
    imagens.clear()
    _imagem_cache.clear()
    _dims_fila.clear()
    _table_seq = 0
    _note_seq = 0
    _object_seq = 0
    _imagem_seq = 0
    _base_dir = None
    _largura_util = 17.0
    _altura_util = 24.0


def _esc(text: str) -> str:
    """Escapa texto para uso dentro de XML (&, <, >)."""
    return escape(text)


def _attr(value: str) -> str:
    """Escapa valor para uso em atributo XML."""
    return escape(value, {'"': "&quot;"})


def _inline_xml(nodes: list[Inline]) -> str:
    out: list[str] = []
    for n in nodes:
        if isinstance(n, Text):
            out.append(_esc(n.value))
        elif isinstance(n, Softbreak):
            # softbreak do markdown = espaço no HTML; mantemos o mesmo
            out.append(" ")
        elif isinstance(n, LineBreak):
            out.append("<text:line-break/>")
        elif isinstance(n, InlineCode):
            out.append(f'<text:span text:style-name="InlineCode">{_esc(n.value)}</text:span>')
        elif isinstance(n, Strong):
            inner = _inline_xml(n.children)
            out.append(f'<text:span text:style-name="Strong">{inner}</text:span>')
        elif isinstance(n, Emph):
            inner = _inline_xml(n.children)
            out.append(f'<text:span text:style-name="Emphasis">{inner}</text:span>')
        elif isinstance(n, Link):
            inner = _inline_xml(n.children)
            href = _attr(n.href)
            out.append(f'<text:a xlink:href="{href}" text:style-name="Link">{inner}</text:a>')
        elif isinstance(n, Image):
            out.append(_image_xml(n))
        elif isinstance(n, FootnoteRef):
            if n.num is None:
                # definição faltando — deixa a sintaxe visível
                out.append(_esc(f"[^{n.label}]"))
            else:
                out.append(_nota_xml(n))
        elif isinstance(n, MathInline):
            out.append(_formula_xml(n.latex))
    return "".join(out)


def _formula_xml(latex: str, display: bool = False,
                 dim: tuple[float, float] | None = None) -> str:
    """LaTeX → quadro ODF apontando para "Object N" (MathML no ZIP).

    O quadro recorta o que extrapolar o tamanho declarado. Quando o
    navegador manda as dimensões reais (`dim` = largura/altura em cm,
    medidas no preview via getBoundingClientRect), usamos elas;
    senão, estimamos pelo tamanho do código LaTeX (sem comandos).
    """
    global _object_seq
    # Dimensão medida no navegador (se o cliente enviou): consome a
    # fila na ordem em que as fórmulas aparecem no XML gerado.
    if dim is None and _dims_fila:
        dim = _dims_fila.pop(0)
    try:
        mathml = latex2mathml.converter.convert(
            latex, display="block" if display else "inline"
        )
    except Exception as exc:  # latex inválido não pode quebrar o documento
        logger.warning("latex inválido (%r): %s", latex, exc)
        return _esc(latex)

    # O x2t (ONLYOFFICE) só reconhece a fórmula se o conteúdo estiver
    # dentro de <semantics> — sem isso ele descarta o objeto inteiro
    # no roundtrip odt→odt (descoberto por bissecção de variantes).
    mathml = re.sub(
        r"(<math\b[^>]*>)(.*?)(</math>)",
        r"\1<semantics>\2</semantics>\3",
        mathml,
        flags=re.DOTALL,
    )
    if not mathml.startswith("<?xml"):
        mathml = '<?xml version="1.0" encoding="UTF-8"?>\n' + mathml

    _object_seq += 1
    nome = f"Object {_object_seq}"
    objetos.append((nome, mathml))

    if dim is not None:
        # medida real do navegador (cm), com tetos de segurança
        largura = min(max(dim[0], 0.5), _largura_util)
        altura = min(max(dim[1], 0.4), 5.0)
    else:
        visivel = re.sub(r"\\[a-zA-Z]+", "", latex).replace(" ", "")
        largura = max(1.0, 0.25 * len(visivel))
        altura = 0.70
    return (
        f'<draw:frame draw:style-name="fr1" draw:name="Object{_object_seq}" '
        f'text:anchor-type="as-char" svg:width="{largura:.2f}cm" '
        f'svg:height="{altura:.2f}cm" draw:z-index="0">'
        f'<draw:object xlink:href="./{nome}" xlink:type="simple" '
        f'xlink:show="embed" xlink:actuate="onLoad"/>'
        f"</draw:frame>"
    )


# ------------------------------------------------------------------
# imagens
# ------------------------------------------------------------------

def _host_permitido(host: str) -> bool:
    """Guarda SSRF: a API não busca imagens em hosts de rede privada.

    Sem isso, quem chama /api/convert faria o SERVIDOR sondar serviços
    internos (169.254.169.254, 127.0.0.1:6379...) em nome de terceiros.
    Quem hospeda o mdToDocs com assets no próprio host pode liberar a
    rede local definindo MDTODOCS_REDE_LOCAL=1.
    """
    if os.environ.get("MDTODOCS_REDE_LOCAL") == "1":
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:10.0.0.1 → 10.0.0.1
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


class _HttpSeguro(urllib.request.HTTPRedirectHandler):
    """Segue redirecionamentos só se o destino também passar na guarda
    (senão um 302 público bastaria para contornar _host_permitido)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlparse(newurl).hostname
        if not host or not _host_permitido(host):
            logger.warning("redirecionamento de imagem bloqueado: %s", newurl)
            return None  # urlopen levanta HTTPError
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER_SEGURO = urllib.request.build_opener(_HttpSeguro)


def _carregar_data_uri(src: str) -> bytes | None:
    """data:image/png;base64,... → binário (fluxo do botão Inserir imagem)."""
    meta, sep, payload = src.partition(",")
    if not sep:
        logger.warning("data URI malformada")
        return None
    try:
        payload = urllib.parse.unquote(payload)  # %2B vira + antes do b64
        if ";base64" in meta:
            dados = base64.b64decode(payload)
        else:
            dados = payload.encode("utf-8")
    except Exception as exc:
        logger.warning("data URI ilegível: %s", exc)
        return None
    if len(dados) > _MAX_IMAGEM:
        logger.warning("imagem data: maior que %d MB", _MAX_IMAGEM // 2**20)
        return None
    return dados


def _carregar_url(url: str) -> bytes | None:
    """Busca imagem remota (http/https) com guarda SSRF + limites."""
    host = urllib.parse.urlparse(url).hostname
    if not host or not _host_permitido(host):
        logger.warning("URL de imagem bloqueada (rede privada/inválida): %s", url)
        return None
    req = urllib.request.Request(url, headers={"User-Agent": "mdToDocs/0.1"})
    try:
        with _OPENER_SEGURO.open(req, timeout=_TIMEOUT_URL) as resp:
            dados = resp.read(_MAX_IMAGEM + 1)
    except Exception as exc:
        logger.warning("falha ao buscar imagem %s: %s", url, exc)
        return None
    if len(dados) > _MAX_IMAGEM:
        logger.warning("imagem remota maior que %d MB: %s", _MAX_IMAGEM // 2**20, url)
        return None
    return dados


def _carregar_imagem(src: str) -> bytes | None:
    """Resolva a origem da imagem em binários (ou None + warning).

    - data:  → embutida no markdown (botão "Inserir imagem" do frontend)
    - http(s) → o servidor busca (guarda SSRF em _host_permitido)
    - caminho relativo ("foto.png") → só no CLI: resolvido contra a
      pasta do .md (base_dir); a API recusa — não há disco do usuário
      do lado do servidor.
    """
    if src.startswith("data:"):
        return _carregar_data_uri(src)
    if src.startswith(("http://", "https://")):
        return _carregar_url(src)
    if _base_dir is not None:
        raiz = _base_dir.resolve()
        caminho = (raiz / src).resolve()
        try:
            caminho.relative_to(raiz)  # recusa ../../etc/passwd
        except ValueError:
            logger.warning("imagem fora da pasta do .md: %s", src)
            return None
        if caminho.is_file() and caminho.stat().st_size <= _MAX_IMAGEM:
            return caminho.read_bytes()
        logger.warning("imagem local não encontrada ou grande demais: %s", src)
        return None
    logger.warning(
        "imagem com caminho local na API (use data: ou URL http): %s", src
    )
    return None


def _formato_imagem(dados: bytes) -> str | None:
    """Detecta o formato pelos primeiros bytes → extensão (ou None)."""
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if dados[:3] == b"\xff\xd8\xff":
        return "jpg"
    if dados[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "webp"
    if dados[:2] == b"BM":
        return "bmp"
    if b"<svg" in dados[:2048]:
        return "svg"
    return None


def _jpeg_dimensoes(dados: bytes) -> tuple[int, int] | None:
    """Percorre os marcadores JPEG até o SOF (carrega altura e largura)."""
    i = 2
    while i + 9 < len(dados):
        if dados[i] != 0xFF:
            i += 1
            continue
        marca = dados[i + 1]
        if marca in (0xD8, 0x01) or 0xD0 <= marca <= 0xD7:
            i += 2
            continue
        tam = int.from_bytes(dados[i + 2 : i + 4], "big")
        if tam < 2:
            break
        # SOF0..SOF15 exceto DHT(0xC4)/JPG(0xC8)/DAC(0xCC)
        if 0xC0 <= marca <= 0xCF and marca not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(dados[i + 5 : i + 7], "big")
            w = int.from_bytes(dados[i + 7 : i + 9], "big")
            return w, h
        i += 2 + tam
    return None


def _webp_dimensoes(dados: bytes) -> tuple[int, int] | None:
    """Canvas do WebP: chunk VP8X (estendido), VP8 (perdido) ou VP8L (sem perdas)."""
    chunk = dados[12:16]
    if chunk == b"VP8X" and len(dados) >= 30:
        w = 1 + int.from_bytes(dados[24:27], "little")
        h = 1 + int.from_bytes(dados[27:30], "little")
        return w, h
    if chunk == b"VP8 " and len(dados) >= 30 and dados[23:26] == b"\x9d\x01\x2a":
        w = int.from_bytes(dados[26:28], "little") & 0x3FFF
        h = int.from_bytes(dados[28:30], "little") & 0x3FFF
        return w, h
    if chunk == b"VP8L" and len(dados) >= 25 and dados[20] == 0x2F:
        b = int.from_bytes(dados[21:25], "little")
        return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
    return None


# unidade de comprimento → cm (para converter width/height do SVG)
_UNIDADES_CM = {"cm": 1.0, "mm": 0.1, "pt": 2.54 / 72, "pc": 2.54 / 6, "in": 2.54}


def _svg_dimensoes(dados: bytes) -> tuple[float, float] | None:
    """Tamanho do SVG em px: atributos width/height (qualquer unidade
    comum); sem eles, o viewBox (unidades viewBox = px).

    Devolve float (sem arredondar): o caminho cm→px→cm do atributo
    perderia precisão com px inteiro (2cm viraria 2.01cm).
    """
    cab = dados[:4096].decode("utf-8", "replace")
    m_w = re.search(r'\bwidth="([\d.]+)\s*([a-z%]*)"', cab, re.I)
    m_h = re.search(r'\bheight="([\d.]+)\s*([a-z%]*)"', cab, re.I)
    if m_w and m_h:
        u_w, u_h = m_w.group(2).lower(), m_h.group(2).lower()
        if u_w != "%" and u_h != "%" and (u_w in _UNIDADES_CM or u_w in ("", "px")) and (
            u_h in _UNIDADES_CM or u_h in ("", "px")
        ):
            px_por_cm = 96 / 2.54
            w = float(m_w.group(1)) * _UNIDADES_CM.get(u_w, 2.54 / 96) * px_por_cm
            h = float(m_h.group(1)) * _UNIDADES_CM.get(u_h, 2.54 / 96) * px_por_cm
            return w, h
    m_vb = re.search(r'\bviewBox="([^"]+)"', cab)
    if m_vb:
        nums = [n for n in re.split(r"[\s,]+", m_vb.group(1).strip()) if n]
        if len(nums) == 4:
            return float(nums[2]), float(nums[3])
    return None


def _dimensoes_px(dados: bytes, fmt: str) -> tuple[float, float] | None:
    """(largura, altura) em px lendo só o cabeçalho — sem decodificar."""
    try:
        if fmt == "png":
            return struct.unpack(">II", dados[16:24])
        if fmt == "gif":
            return struct.unpack("<HH", dados[6:10])
        if fmt == "bmp":
            w = int.from_bytes(dados[18:22], "little", signed=True)
            h = int.from_bytes(dados[22:26], "little", signed=True)
            return w, h
        if fmt == "jpg":
            return _jpeg_dimensoes(dados)
        if fmt == "webp":
            return _webp_dimensoes(dados)
        if fmt == "svg":
            return _svg_dimensoes(dados)
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _dimensoes_cm(dados: bytes, fmt: str) -> tuple[float, float] | None:
    """px → cm a 96dpi (o mesmo cálculo do navegador) com escala que
    mantém a imagem na área útil: _largura_util (A4 − margens) e
    _altura_util (uma folha, teto de 24cm). Proporcional nos dois eixos."""
    dim = _dimensoes_px(dados, fmt)
    if not dim or dim[0] <= 0 or dim[1] <= 0:
        return None
    w = dim[0] * 2.54 / 96
    h = dim[1] * 2.54 / 96
    escala = min(1.0, _largura_util / w, _altura_util / h)
    return w * escala, h * escala


def _frame_imagem(path: str, largura: float, altura: float) -> str:
    """<draw:frame> as-char com <draw:image> embutido (estilo fr1, o
    mesmo das fórmulas — alinha na linha de texto)."""
    return (
        f'<draw:frame draw:style-name="fr1" text:anchor-type="as-char" '
        f'svg:width="{largura:.2f}cm" svg:height="{altura:.2f}cm" '
        f'draw:z-index="0">'
        f'<draw:image xlink:href="{_attr(path)}" xlink:type="simple" '
        f'xlink:show="embed" xlink:actuate="onLoad"/>'
        f"</draw:frame>"
    )


def _image_xml(img: Image) -> str:
    """![alt](src) → quadro ODF; binário vai para o registry `imagens`."""
    global _imagem_seq
    cache = _imagem_cache.get(img.src)
    if cache:
        return _frame_imagem(*cache)

    dados = _carregar_imagem(img.src)
    if dados is None:
        # motivo já logado em _carregar_imagem — deixa a sintaxe visível
        return _esc(f"[imagem: {img.alt or img.src}]")

    fmt = _formato_imagem(dados)
    if fmt is None:
        logger.warning("formato de imagem desconhecido: %.80s", img.src)
        return _esc(f"[imagem: {img.alt or img.src}]")

    dim = _dimensoes_cm(dados, fmt)
    if dim is None:
        logger.warning("não consegui medir %.80s — tamanho padrão", img.src)
        dim = (8.0, 6.0)

    _imagem_seq += 1
    path = f"Pictures/img{_imagem_seq}.{fmt}"
    imagens.append((path, dados, _EXT_MEDIA_TYPE[fmt]))
    _imagem_cache[img.src] = (path, *dim)
    return _frame_imagem(path, dim[0], dim[1])


def _nota_xml(ref: FootnoteRef) -> str:
    """<text:note> — nota de rodapé real (fica no rodapé da página).

    O corpo da nota é o conteúdo da definição `[^id]: ...`; cada
    referência recebe um text:id único no documento.
    """
    global _note_seq
    _note_seq += 1
    corpo = "".join(
        _block_xml(b, paragraph_style="Footnote") for b in ref.blocks
    )
    return (
        f'<text:note text:id="ftn{_note_seq}" text:note-class="footnote">'
        f"<text:note-citation>{ref.num}</text:note-citation>"
        f"<text:note-body>{corpo}</text:note-body>"
        f"</text:note>"
    )


def _list_xml(list_block: BulletList | OrderedList, style_name: str) -> str:
    items: list[str] = []
    for item in list_block.items:
        inner = "".join(_block_xml(b) for b in item.children)
        items.append(f"<text:list-item>{inner}</text:list-item>")
    joined = "".join(items)
    # Ordenadas com start != 1: por ora o ODF numerará a partir de 1
    if isinstance(list_block, OrderedList) and list_block.start != 1:
        logger.warning("lista ordenada start=%s não suportada ainda", list_block.start)
    return f'<text:list text:style-name="{style_name}">{joined}</text:list>'


def _table_xml(table: Table) -> str:
    """Gera <table:table> + estilos automáticos de coluna e célula."""
    global _table_seq
    _table_seq += 1
    n = _table_seq
    ncols = max((len(r.cells) for r in table.rows), default=1)

    cell_style = f"Tabela{n}Cel"
    col_style = f"Tabela{n}Col"
    # Largura útil da página A4: 21cm − 2×margem (padrão 2cm → 17cm)
    largura = _largura_util / ncols
    _auto_styles.append(f"""
    <style:style style:name="{cell_style}" style:family="table-cell">
      <style:table-cell-properties fo:border="0.5pt solid #999999" fo:padding="0.05cm"/>
    </style:style>
    <style:style style:name="{col_style}" style:family="table-column">
      <style:table-column-properties style:column-width="{largura:.3f}cm"/>
    </style:style>""")

    align_para = {"left": "TLeft", "center": "TCenter", "right": "TRight"}
    celula_vazia = (
        f'<table:table-cell table:style-name="{cell_style}" office:value-type="string">'
        f"<text:p/></table:table-cell>"
    )

    def celula(cell: TableCell) -> str:
        inner = _inline_xml(cell.children)
        if cell.header:
            inner = f'<text:span text:style-name="Strong">{inner}</text:span>'
        pstyle = align_para.get(cell.align or "", "TextBody")
        return (
            f'<table:table-cell table:style-name="{cell_style}" office:value-type="string">'
            f'<text:p text:style-name="{pstyle}">{inner}</text:p>'
            f"</table:table-cell>"
        )

    def linha(row: TableRow) -> str:
        # linhas irregulares (markdown quebrado) ganham células vazias
        corpo = "".join(celula(c) for c in row.cells)
        corpo += celula_vazia * (ncols - len(row.cells))
        return f"<table:table-row>{corpo}</table:table-row>"

    # primeira linha 100% th → repete no topo de cada página impressa
    cabecalho = ""
    resto = table.rows
    if table.rows and all(c.header for c in table.rows[0].cells):
        cabecalho = f"<table:table-header-rows>{linha(table.rows[0])}</table:table-header-rows>"
        resto = table.rows[1:]

    colunas = (
        f'<table:table-column table:style-name="{col_style}" '
        f'table:number-columns-repeated="{ncols}"/>'
    )
    linhas = "".join(linha(r) for r in resto)
    return f'<table:table table:name="Tabela{n}">{colunas}{cabecalho}{linhas}</table:table>'


def _toc_xml(toc: Toc) -> str:
    """Sumário estático: parágrafos Toc1..Toc6 com links internos para
    os bookmarks dos títulos.

    Escolhemos lista estática (e não <text:table-of-content> do ODF)
    porque: (1) funciona igual no LibreOffice e no ONLYOFFICE sem
    depender de "atualizar índice" (F9); (2) número de página exigiria
    um motor de paginação, que não temos.
    """
    if not toc.entries:
        return ""
    linhas = []
    for e in toc.entries:
        estilo = f"Toc{min(max(e.level, 1), 6)}"
        href = _attr(f"#{e.bookmark}")
        linhas.append(
            f'<text:p text:style-name="{estilo}">'
            f'<text:a xlink:href="{href}" text:style-name="Link">{_esc(e.text)}</text:a>'
            f"</text:p>"
        )
    return "".join(linhas)


def _block_xml(block: Block, paragraph_style: str = "TextBody") -> str:
    if isinstance(block, Paragraph):
        inner = _inline_xml(block.children)
        return f'<text:p text:style-name="{paragraph_style}">{inner}</text:p>'

    if isinstance(block, Heading):
        inner = _inline_xml(block.children)
        level = block.level
        # âncora do sumário + número da seção (quando ativado)
        marca = (
            f'<text:bookmark text:name="{_attr(block.bookmark)}"/>'
            if block.bookmark
            else ""
        )
        num = f"{_esc(block.num)} " if block.num else ""
        return (
            f'<text:h text:style-name="Heading{level}" '
            f'text:outline-level="{level}">{marca}{num}{inner}</text:h>'
        )

    if isinstance(block, CodeBlock):
        linhas = block.content.rstrip("\n").split("\n")
        corpo = "<text:line-break/>".join(_esc(l) for l in linhas)
        return f'<text:p text:style-name="CodeBlock">{corpo}</text:p>'

    if isinstance(block, Blockquote):
        # cada parágrafo interno vira parágrafo com estilo Blockquote
        return "".join(
            _block_xml(child, paragraph_style="Blockquote")
            for child in block.children
        )

    if isinstance(block, BulletList):
        return _list_xml(block, "BulletList")

    if isinstance(block, OrderedList):
        return _list_xml(block, "OrderedList")

    if isinstance(block, Table):
        return _table_xml(block)

    if isinstance(block, HorizontalRule):
        # parágrafo vazio com borda inferior definida no estilo (styles.xml)
        return '<text:p text:style-name="HorizontalRule"/>'

    if isinstance(block, PageBreak):
        # parágrafo vazio cujo estilo manda o LibreOffice/ONLYOFFICE
        # começar nova página aqui (fo:break-before="page")
        return '<text:p text:style-name="PageBreak"/>'

    if isinstance(block, Toc):
        return _toc_xml(block)

    if isinstance(block, Numbering):
        # só um marcador de ativação — a numeração já foi aplicada
        # nos Heading pelo _resolver_estrutura
        return ""

    if isinstance(block, Footnotes):
        # definições já foram levadas para dentro de cada <text:note>
        return ""

    if isinstance(block, MathBlock):
        # fórmula em bloco: quadro sozinho no parágrafo (linha própria)
        return (
            f'<text:p text:style-name="TextBody">'
            f"{_formula_xml(block.latex, display=True)}</text:p>"
        )

    logger.warning("bloco não suportado: %s", type(block).__name__)
    return ""


def build_content_xml(
    blocks: list[Block],
    math_dims: list[tuple[float, float]] | None = None,
    base_dir: str | Path | None = None,
    estilos: dict | None = None,
) -> tuple[str, list[tuple[str, str]], list[tuple[str, bytes, str]]]:
    """Gera (content_xml, objetos, imagens):
    - objetos: partes "Object N" com o MathML das fórmulas;
    - imagens: pares (caminho Pictures/…, binário, media-type);
    ambos o odt_writer embute no ZIP e declara no manifesto.

    `math_dims` (opcional) são larguras/alturas em cm de cada fórmula,
    medidas no preview pelo navegador; em ordem de aparição. Se a lista
    não bater com o nº de fórmulas do documento, o excedente é ignorado
    e o que faltar cai na estimativa pelo tamanho do LaTeX.

    `base_dir` (opcional) é a pasta do .md no CLI — permite imagem com
    caminho relativo ("foto.png"); na API fica None.

    `estilos` (opcional) = dict do painel de estilos; só a margem da
    página interessa aqui (muda a área útil de tabela/fórmula/imagem).
    """
    global _base_dir, _largura_util, _altura_util
    _reset_auto_styles()
    if base_dir:
        _base_dir = Path(base_dir)
    if estilos is not None:
        margem = normalizar_estilos(estilos)["margemPagina"]
        _largura_util = 21.0 - 2 * margem
        _altura_util = min(24.0, 29.7 - 2 * margem)
    if math_dims:
        _dims_fila.extend((float(w), float(h)) for w, h in math_dims[:2000])
    body = "".join(_block_xml(b) for b in blocks)
    dynamicos = "".join(_auto_styles)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
{NAMESPACES}
    office:version="1.3">
  <office:automatic-styles>
{_LIST_STYLES}
{_ALIGN_STYLES}
{_FR1_STYLE}
{dynamicos}
  </office:automatic-styles>
  <office:body>
    <office:text>
      {body}
    </office:text>
  </office:body>
</office:document-content>
"""
    return xml, list(objetos), list(imagens)
