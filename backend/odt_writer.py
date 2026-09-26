"""Geração manual de arquivos ODT (Open Document Text).

Um arquivo .odt é um ZIP contendo XML. Este módulo monta cada arquivo
interno do ZIP na ordem exigida pela especificação ODF:

1. mimetype          - primeiro item, SEM compressão (zipfile.ZIP_STORED)
2. styles.xml        - estilos globais (títulos, negrito, código...)
3. content.xml       - conteúdo (gerado de odt_content a partir dos blocos)
4. meta.xml          - metadados (autor, data de criação)
5. META-INF/manifest.xml - lista os arquivos do pacote

Fluxo completo do projeto:

    markdown ─md_parser→ blocos ─odt_content→ content.xml ─aqui→ .odt
"""

import zipfile
from pathlib import Path

from md_parser import Block, parse
from odt_content import build_content_xml
from styles import build_styles_xml, normalizar as normalizar_estilos

# A ordem importa: a spec da ODF exige que "mimetype" seja o primeiro
# arquivo do ZIP e venha sem compressão, para que leitores identifiquem
# o formato sem precisar descomprimir tudo.
MIMETYPE = "application/vnd.oasis.opendocument.text"

MANIFEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest
    xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
    manifest:version="1.3">
  <manifest:file-entry
      manifest:full-path="/"
      manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry
      manifest:full-path="content.xml"
      manifest:media-type="text/xml"/>
  <manifest:file-entry
      manifest:full-path="styles.xml"
      manifest:media-type="text/xml"/>
  <manifest:file-entry
      manifest:full-path="meta.xml"
      manifest:media-type="text/xml"/>
</manifest:manifest>
"""

# Estilos nomeados usados pelo content.xml.
# Cada estilo usado em text:style-name="..." DEVE existir aqui (styles.xml
# ou automatic-styles), senão o editor aplica o padrão — ou falha.
#
# O styles.xml em si é gerado pelo styles.py (o painel de estilos da
# interface manda os valores; com os padrões ele reproduz o visual
# antigo). PONTOS CRÍTICOS descobertos testando contra o ONLYOFFICE (x2t):
# 1. SEM <office:automatic-styles> (page-layout) + <office:master-styles>
#    no fim do styles.xml, o x2t DESCARTA o styles.xml inteiro → nada
#    formatado. É obrigatório mesmo sem "página" explícita.
# 2. Estilos de título precisam de style:default-outline-level="N",
#    senão <text:h> é rebaixado para <text:p> (título vira texto comum).
# 3. Sublinhado: usar style:text-underline-* (formato do LibreOffice);
#    fo:text-decoration é ignorado pelo x2t.
# 4. Fontes: svg:font-family como ATRIBUTO do <style:font-face>
#    (a forma de elemento-filho é descartada).
STYLES_XML = build_styles_xml()

META_XML = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
    office:version="1.3">
  <office:meta>
    <meta:generator>mdToDocs</meta:generator>
  </office:meta>
</office:document-meta>
"""


def _check_well_formed(name: str, xml: str) -> None:
    """Valida que o XML é bem formado antes de embalar.

    Um XML mal formado faz o editor abrir o documento EM BRANCO
    (falha silenciosa) — esta checagem evita isso.
    """
    import xml.etree.ElementTree as ET

    try:
        ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f"XML inválido em {name}: {e}") from e


def _manifest_com_partes(
    objetos: list[tuple[str, str]],
    imagens: list[tuple[str, bytes, str]],
) -> str:
    """Manifesto + entradas das pastas "Object N" (fórmulas) e
    "Pictures" (imagens embutidas, cada uma com seu media-type)."""
    entradas = "".join(
        f"""  <manifest:file-entry
      manifest:full-path="{nome}/"
      manifest:version="1.3"
      manifest:media-type="application/vnd.oasis.opendocument.formula"/>
  <manifest:file-entry
      manifest:full-path="{nome}/content.xml"
      manifest:media-type="text/xml"/>
"""
        for nome, _ in objetos
    )
    entradas += "".join(
        f"""  <manifest:file-entry
      manifest:full-path="{path}"
      manifest:media-type="{mime}"/>
"""
        for path, _, mime in imagens
    )
    if not entradas:
        return MANIFEST_XML
    return MANIFEST_XML.replace("</manifest:manifest>", entradas + "</manifest:manifest>")


def render_odt(
    blocks: list[Block],
    math_dims: list[tuple[float, float]] | None = None,
    base_dir: str | Path | None = None,
    estilos: dict | None = None,
) -> bytes:
    """Gera os bytes do .odt a partir da árvore de blocos (em memória).

    `math_dims` (opcional) = medidas reais das fórmulas em cm, feitas
    no preview pelo navegador — ver build_content_xml.
    `base_dir` (opcional) = pasta do .md no CLI, para imagens com
    caminho relativo (a API não envia — não tem acesso ao disco).
    `estilos` (opcional) = dict do painel de estilos; normalizado em
    styles.normalizar e aplicado ao styles.xml + à área útil (margens).
    """
    import io

    e = normalizar_estilos(estilos)
    styles_xml = build_styles_xml(e)
    content_xml, objetos, imagens = build_content_xml(
        blocks, math_dims, base_dir=base_dir, estilos=e
    )
    manifest_xml = _manifest_com_partes(objetos, imagens)

    for name, xml in [
        ("content.xml", content_xml),
        ("styles.xml", styles_xml),
        ("meta.xml", META_XML),
        ("META-INF/manifest.xml", manifest_xml),
        # partes de fórmula: "Object N/content.xml" contém o MathML
        *[(f"{nome}/content.xml", mathml) for nome, mathml in objetos],
    ]:
        _check_well_formed(name, xml)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as odt:
        # ZIP_STORED = sem compressão, exigido pela spec para o mimetype
        odt.writestr(
            zipfile.ZipInfo("mimetype"),
            MIMETYPE,
            compress_type=zipfile.ZIP_STORED,
        )
        odt.writestr("styles.xml", styles_xml, compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr("content.xml", content_xml, compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr("meta.xml", META_XML, compress_type=zipfile.ZIP_DEFLATED)
        odt.writestr(
            "META-INF/manifest.xml",
            manifest_xml,
            compress_type=zipfile.ZIP_DEFLATED,
        )
        for nome, mathml in objetos:
            odt.writestr(
                f"{nome}/content.xml",
                mathml,
                compress_type=zipfile.ZIP_DEFLATED,
            )
        for path, dados, _ in imagens:
            # binário da imagem em Pictures/ (compressão normal da ODF)
            odt.writestr(path, dados, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


def write_odt(
    output_path: str | Path,
    blocks: list[Block],
    base_dir: str | Path | None = None,
    estilos: dict | None = None,
) -> Path:
    """Gera um .odt em disco a partir da árvore de blocos do md_parser."""
    output_path = Path(output_path)
    output_path.write_bytes(render_odt(blocks, base_dir=base_dir, estilos=estilos))
    return output_path


def convert_markdown_file(md_path: str | Path, odt_path: str | Path) -> Path:
    """Converte um arquivo .md em .odt (função de alto nível)."""
    md_path = Path(md_path)
    texto = md_path.read_text(encoding="utf-8")
    # imagens com caminho relativo ("foto.png") resolvem ao lado do .md
    return write_odt(odt_path, parse(texto), base_dir=md_path.resolve().parent)


if __name__ == "__main__":
    import logging
    import sys

    logging.basicConfig(level=logging.WARNING)

    amostra = """\
# Artigo de Exemplo

Este parágrafo tem **negrito**, *itálico*, `código inline` e um
[link](https://example.com) — gerado do markdown ao ODT.

## Lista

- primeiro item
- segundo item
  - aninhado

1. um
2. dois

> Uma citação em itálico
> com barra lateral.

```python
print("bloco de código")
```
"""
    if len(sys.argv) == 3:
        path = convert_markdown_file(sys.argv[1], sys.argv[2])
    else:
        path = write_odt("exemplo.odt", parse(amostra))
    print(f"Gerado: {path}")
