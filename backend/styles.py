"""Modelo de estilos do documento → styles.xml do ODT.

O painel de estilos da interface edita um dicionário simples:

    {"fonte": "Liberation Serif", "tamanho": 12, "entrelinha": 1.2,
     "margemParagrafo": 0.25, "margemPagina": 2,
     "h1": 22, ..., "h6": 12, "nota": 10}

Este módulo:
  1. normalizar()  — valida/clampa cada valor (o cliente pode mandar
     qualquer coisa; chaves desconhecidas são ignoradas);
  2. build_styles_xml() — injeta os valores no template do styles.xml
     (mesmo XML de antes, agora parametrizado).

O MESMO dicionário também é usado pelo odt_content, porque a margem
da página muda a área útil (21cm − 2×margem), que define a largura
das tabelas e o teto das imagens.
"""

import re

# limites de cada valor: o backend manda, o frontend espelha p/ UX
_LIMITES = {
    "tamanho": (6, 72),           # pt — corpo do texto
    "entrelinha": (1.0, 3.0),     # multiplicador (1.2 = 120%)
    "margemParagrafo": (0.0, 2.0),  # cm abaixo de cada parágrafo
    "margemPagina": (0.5, 4.0),   # cm — os 4 lados da A4
    "h1": (6, 72),                # pt — títulos
    "h2": (6, 72),
    "h3": (6, 72),
    "h4": (6, 72),
    "h5": (6, 72),
    "h6": (6, 72),
    "nota": (6, 24),              # pt — notas de rodapé
}

# valores padrão = o visual de antes de existir o painel
PADRAO = {
    "fonte": "Liberation Serif",
    "tamanho": 12,
    "entrelinha": 1.2,
    "margemParagrafo": 0.25,
    "margemPagina": 2,
    "h1": 22,
    "h2": 18,
    "h3": 16,
    "h4": 14,
    "h5": 13,
    "h6": 12,
    "nota": 10,
}

# remove caracteres perigosos p/ atributo XML / injeção de CSS
_FONTE_INVALIDA = re.compile(r"""["'`;<>{}\\&\r\n]""")


def normalizar(bruto: object) -> dict:
    """Devolve um dicionário completo e dentro dos limites.

    Aceita dict vazio/None/chaves erradas — sempre sai PADRAO + o que
    era válido. Valores fora do limite são clamped (não rejeitados),
    bool não conta como número.
    """
    estilos = dict(PADRAO)
    if not isinstance(bruto, dict):
        return estilos

    fonte = bruto.get("fonte")
    if isinstance(fonte, str):
        limpa = _FONTE_INVALIDA.sub("", fonte).strip()[:60]
        if limpa:
            estilos["fonte"] = limpa

    for chave, (minimo, maximo) in _LIMITES.items():
        valor = bruto.get(chave)
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            estilos[chave] = min(max(float(valor), minimo), maximo)
    return estilos


def _n(valor: float) -> str:
    """12.0 → '12' | 0.25 → '0.25' (sem zeros sobrando no XML)."""
    return f"{valor:g}"


def _faces_xml(fonte: str) -> str:
    """style:font-face de cada fonte usada: a base + Liberation Mono
    (necessária p/ código inline e blocos de código)."""
    faces = [f"""    <style:font-face style:name="{fonte}"
                     svg:font-family="{fonte}"/>"""]
    if fonte != "Liberation Mono":
        faces.append("""    <style:font-face style:name="Liberation Mono"
                     svg:font-family="Liberation Mono"/>""")
    return "\n".join(faces)


def build_styles_xml(estilos: dict | None = None) -> str:
    """Gera o styles.xml completo com os estilos aplicados."""
    e = normalizar(estilos)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
    xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
    office:version="1.2">
  <office:font-face-decls>
{_faces_xml(e["fonte"])}
  </office:font-face-decls>
  <office:styles>
    <style:default-style style:family="paragraph">
      <style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="{_n(e["margemParagrafo"])}cm" style:line-height="{_n(e["entrelinha"] * 100)}%"/>
      <style:text-properties style:font-name="{e["fonte"]}" fo:font-size="{_n(e["tamanho"])}pt"/>
    </style:default-style>

    <style:style style:name="Standard" style:family="paragraph">
      <style:text-properties style:font-name="{e["fonte"]}" fo:font-size="{_n(e["tamanho"])}pt"/>
    </style:style>

    <style:style style:name="TextBody" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-top="0cm" fo:margin-bottom="{_n(e["margemParagrafo"])}cm"/>
    </style:style>

    <style:style style:name="Heading1" style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="1">
      <style:paragraph-properties fo:margin-top="0.6cm" fo:margin-bottom="0.3cm"/>
      <style:text-properties fo:font-size="{_n(e["h1"])}pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Heading2" style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="2">
      <style:paragraph-properties fo:margin-top="0.5cm" fo:margin-bottom="0.25cm"/>
      <style:text-properties fo:font-size="{_n(e["h2"])}pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Heading3" style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="3">
      <style:paragraph-properties fo:margin-top="0.4cm" fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-size="{_n(e["h3"])}pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Heading4" style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="4">
      <style:paragraph-properties fo:margin-top="0.4cm" fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-size="{_n(e["h4"])}pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Heading5" style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="5">
      <style:paragraph-properties fo:margin-top="0.3cm" fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-size="{_n(e["h5"])}pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Heading6" style:family="paragraph" style:parent-style-name="Standard" style:default-outline-level="6">
      <style:paragraph-properties fo:margin-top="0.3cm" fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-size="{_n(e["h6"])}pt" fo:font-weight="bold"/>
    </style:style>

    <style:style style:name="Strong" style:family="text">
      <style:text-properties fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Emphasis" style:family="text">
      <style:text-properties fo:font-style="italic"/>
    </style:style>
    <style:style style:name="InlineCode" style:family="text">
      <style:text-properties style:font-name="Liberation Mono" fo:background-color="#eeeeee"/>
    </style:style>
    <style:style style:name="Link" style:family="text">
      <style:text-properties fo:color="#0000ee"
                             style:text-underline-style="solid"
                             style:text-underline-width="auto"
                             style:text-underline-color="#0000ee"/>
    </style:style>

    <style:style style:name="CodeBlock" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:background-color="#f5f5f5"
                                  fo:border="0.5pt solid #dddddd"
                                  fo:padding="0.2cm"
                                  fo:margin-top="0.2cm"
                                  fo:margin-bottom="0.2cm"/>
      <style:text-properties style:font-name="Liberation Mono" fo:font-size="10pt"/>
    </style:style>

    <style:style style:name="Blockquote" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-left="0.5cm"
                                  fo:margin-right="0.5cm"
                                  fo:border-left="2pt solid #888888"
                                  fo:padding-left="0.3cm"
                                  fo:margin-top="0.2cm"
                                  fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-style="italic" fo:color="#555555"/>
    </style:style>

    <style:style style:name="HorizontalRule" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:border-bottom="0.5pt solid #999999"
                                  fo:margin-top="0.3cm"
                                  fo:margin-bottom="0.3cm"/>
    </style:style>

    <!-- quebra de página explícita (\\newpage no markdown) -->
    <style:style style:name="PageBreak" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:break-before="page"
                                  fo:margin-top="0cm"
                                  fo:margin-bottom="0cm"/>
    </style:style>

    <!-- sumário: um nível de recuo por 0.75cm (mesmo passo das listas) -->
    <style:style style:name="Toc1" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:margin-left="0cm" fo:margin-top="0.1cm" fo:margin-bottom="0.1cm"/>
    </style:style>
    <style:style style:name="Toc2" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:margin-left="0.75cm" fo:margin-top="0.1cm" fo:margin-bottom="0.1cm"/>
    </style:style>
    <style:style style:name="Toc3" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:margin-left="1.5cm" fo:margin-top="0.1cm" fo:margin-bottom="0.1cm"/>
    </style:style>
    <style:style style:name="Toc4" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:margin-left="2.25cm" fo:margin-top="0.1cm" fo:margin-bottom="0.1cm"/>
    </style:style>
    <style:style style:name="Toc5" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:margin-left="3cm" fo:margin-top="0.1cm" fo:margin-bottom="0.1cm"/>
    </style:style>
    <style:style style:name="Toc6" style:family="paragraph" style:parent-style-name="TextBody">
      <style:paragraph-properties fo:margin-left="3.75cm" fo:margin-top="0.1cm" fo:margin-bottom="0.1cm"/>
    </style:style>

    <style:style style:name="Footnote" style:family="paragraph" style:parent-style-name="Standard">
      <style:text-properties fo:font-size="{_n(e["nota"])}pt"/>
    </style:style>
  </office:styles>
  <office:automatic-styles>
    <style:page-layout style:name="pm1">
      <style:page-layout-properties fo:page-width="21cm" fo:page-height="29.7cm"
                                    style:print-orientation="portrait"
                                    fo:margin-top="{_n(e["margemPagina"])}cm" fo:margin-bottom="{_n(e["margemPagina"])}cm"
                                    fo:margin-left="{_n(e["margemPagina"])}cm" fo:margin-right="{_n(e["margemPagina"])}cm"/>
    </style:page-layout>
  </office:automatic-styles>
  <office:master-styles>
    <style:master-page style:name="Standard" style:page-layout-name="pm1"/>
  </office:master-styles>
</office:document-styles>
"""
