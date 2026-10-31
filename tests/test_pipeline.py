#!/usr/bin/env python3
"""Suíte do pipeline: parser → ODT sem passar pela rede.

Cobre: estrutura do ZIP, escapes/Unicode, títulos/listas, estilos
(styles.normalizar + build_styles_xml + aplicação no render), diretivas
(toc, numbering, \\newpage), notas de rodapé, fórmulas MathML, tabelas,
imagens (data URI, formatos, limites, SSRF) e o CLI de arquivos.
"""
import base64
import io
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from _common import (abrir, check, conteudo, estilos_xml, gerar, imagem_uri,
                     parte, pictures, png_bytes, resumo)

from styles import PADRAO, build_styles_xml, normalizar  # noqa: E402

# ---------------------------------------------------------------- estrutura
print("\n— estrutura do ODT —")
odt = gerar("# Título\n\nCorpo com **forte**.")
z = abrir(odt)
nomes = z.namelist()
check(nomes[0] == "mimetype", "mimetype é a 1ª entrada do zip")
check(z.read("mimetype") == b"application/vnd.oasis.opendocument.text",
      "mimetype = ODF text")
check(z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED,
      "mimetype sem compressão (spec ODF)")
for p in ("content.xml", "styles.xml", "meta.xml", "META-INF/manifest.xml"):
    check(p in nomes, f"{p} presente")
check(z.testzip() is None, "zip íntegro (CRC)")
check(b"<office:document-content" in z.read("content.xml"),
      "content.xml é office:document-content")

try:
    for p in ("content.xml", "styles.xml", "meta.xml",
              "META-INF/manifest.xml"):
        ET.fromstring(z.read(p))
    bem_formado = True
except ET.ParseError:
    bem_formado = False
check(bem_formado, "todos os XMLs bem-formados (ElementTree)")

# ------------------------------------------------------------- escapes/i18n
print("\n— escapes e Unicode —")
cx = conteudo(gerar('Texto com `<div>` e a & b.\n\n"aspas" '
                    "e 'ticks' — ção avião hambúrguer 🚀"))
check("&lt;div&gt;" in cx, "tag literal escapada (&lt;div&gt;)")
check("<div" not in cx, "sem tag real <div> no XML")
check("a &amp; b" in cx, "& escapado como &amp;")
check('"aspas"' in cx, "aspas preservadas no texto")
check("ção" in cx and "avião" in cx and "hambúrguer" in cx,
      "acentos preservados (UTF-8)")
check("🚀" in cx, "emoji preservado")

# ------------------------------------------------------ títulos e listas
print("\n— títulos e listas —")
odt6 = gerar("\n\n".join(("#" * i) + f" Nível {i}" for i in range(1, 7)))
cx = conteudo(odt6)
for n in range(1, 7):
    check(f'text:style-name="Heading{n}"' in cx, f"H{n} usa estilo Heading{n}")
sx = estilos_xml(odt6)
for n in range(1, 7):
    check(f'style:name="Heading{n}"' in sx, f"styles.xml define Heading{n}")
check('text:outline-level="6"' in cx, "outline-level do H6")

cx = conteudo(gerar("- um\n- dois\n  - aninhado\n\n1. a\n2. b"))
check('<text:list text:style-name="BulletList">' in cx,
      "lista com estilo BulletList")
check('<text:list text:style-name="OrderedList">' in cx,
      "lista com estilo OrderedList")
check('<text:list-style style:name="BulletList">' in cx,
      "definição BulletList no automatic-styles")
check('<text:list-style style:name="OrderedList">' in cx,
      "definição OrderedList no automatic-styles")
check(cx.count("<text:list-item>") == 5, "5 itens (3 bullets + 2 números)")

# ------------------------------------------------- estilos: blocos comuns
print("\n— estilos: blocos e spans —")
odt_b = gerar(
    "> citação aqui\n\n---\n\n**forte** e *fraco* com `cod` e "
    "[link](https://exemplo.org)\n\n```python\nprint(1)\nprint(2)\n```")
cx = conteudo(odt_b)
check('text:style-name="Blockquote"' in cx, "citação estilizada")
check('text:style-name="HorizontalRule"' in cx, "hr estilizado")
check('text:style-name="Strong"' in cx, "negrito (Strong)")
check('text:style-name="Emphasis"' in cx, "itálico (Emphasis)")
check('text:style-name="InlineCode"' in cx, "código inline estilizado")
check('text:style-name="CodeBlock"' in cx, "bloco de código estilizado")
check(cx.count("<text:line-break/>") == 1, "2 linhas de código = 1 line-break")
check('<text:a xlink:href="https://exemplo.org"' in cx,
      "link externo com href absoluto")
check('style:font-face style:name="Liberation Mono"' in estilos_xml(odt_b),
      "face monoespaçada declarada no styles.xml")

# --------------------------------------------------------- estilos: valores
print("\n— styles.normalizar (limites e validação) —")
check(normalizar(None) == PADRAO, "None → padrão")
check(normalizar(["não", "dict"]) == PADRAO, "entrada não-dict → padrão")
check(normalizar({"inexistente": 9}) == PADRAO, "chave desconhecida ignorada")
check(normalizar({"tamanho": 100})["tamanho"] == 72.0, "tamanho clampado em 72")
check(normalizar({"tamanho": 1})["tamanho"] == 6.0, "tamanho clampado em 6")
check(normalizar({"tamanho": True})["tamanho"] == PADRAO["tamanho"],
      "bool não conta como número")
check(normalizar({"entrelinha": 9})["entrelinha"] == 3.0, "entrelinha até 3.0")
check(normalizar({"entrelinha": 0.5})["entrelinha"] == 1.0, "entrelinha ≥ 1.0")
check(normalizar({"margemPagina": 99})["margemPagina"] == 4.0,
      "margem da página até 4cm")
check(normalizar({"margemParagrafo": -5})["margemParagrafo"] == 0.0,
      "margem de parágrafo ≥ 0")
check(normalizar({"nota": 999})["nota"] == 24.0, "nota até 24pt")
check(normalizar({"h1": 200, "h6": 0})["h1"] == 72.0
      and normalizar({"h1": 200, "h6": 0})["h6"] == 6.0,
      "títulos clampados nos dois extremos")
check(normalizar({"fonte": 'A"b\'c`;<>{}\\&\nZ'})["fonte"] == "AbcZ",
      "caracteres perigosos removidos da fonte")
check(normalizar({"fonte": "   "})["fonte"] == PADRAO["fonte"],
      "fonte vazia → padrão")
check(len(normalizar({"fonte": "x" * 200})["fonte"]) == 60,
      "fonte longa cortada em 60 caracteres")

print("\n— styles.build_styles_xml (template) —")
sx0 = build_styles_xml()
check('style:font-name="Liberation Serif"' in sx0, "fonte padrão no default")
check('fo:font-size="12pt"' in sx0, "corpo padrão 12pt")
check('style:line-height="120%"' in sx0, "entrelinha padrão 120%")
check('fo:margin-top="2cm"' in sx0, "margem de página padrão 2cm")
check(re.search(r'style:name="Heading1"[^>]*>.*?fo:font-size="22pt"',
                sx0, re.S), "H1 padrão 22pt")
check(re.search(r'style:name="Footnote"[^>]*>.*?fo:font-size="10pt"',
                sx0, re.S), "nota padrão 10pt")

sx = build_styles_xml({"fonte": "Verdana", "tamanho": 15, "entrelinha": 1.5,
                       "margemParagrafo": 0.5, "margemPagina": 3.5,
                       "h1": 30, "h2": 27, "nota": 8})
check('svg:font-family="Verdana"' in sx, "fonte custom no font-face")
check('fo:font-size="15pt"' in sx, "corpo custom 15pt")
check('style:line-height="150%"' in sx, "entrelinha custom 150%")
check('fo:margin-bottom="0.5cm"' in sx, "margem de parágrafo custom")
check('fo:margin-top="3.5cm"' in sx and 'fo:margin-left="3.5cm"' in sx,
      "margem da página custom nos 4 lados")
check(re.search(r'style:name="Heading1"[^>]*>.*?fo:font-size="30pt"',
                sx, re.S), "H1 custom 30pt")
check(re.search(r'style:name="Heading2"[^>]*>.*?fo:font-size="27pt"',
                sx, re.S), "H2 custom 27pt")
check(re.search(r'style:name="Footnote"[^>]*>.*?fo:font-size="8pt"',
                sx, re.S), "nota custom 8pt")
sx = build_styles_xml({"fonte": "Verdana"})
check('style:name="Verdana"' in sx and 'style:name="Liberation Mono"' in sx,
      "faces base + Mono declaradas")
sx = build_styles_xml({"fonte": "Liberation Mono"})
check(sx.count('style:name="Liberation Mono"') == 1,
      "fonte Mono não duplica a face")

print("\n— estilos aplicados pelo render_odt —")
sx = estilos_xml(gerar("# x", estilos={"tamanho": 15, "h1": 30,
                                       "margemPagina": 3.5,
                                       "fonte": "Verdana", "nota": 14}))
check('fo:font-size="15pt"' in sx and 'fo:font-size="30pt"' in sx,
      "render aplica corpo/título custom")
check('fo:margin-top="3.5cm"' in sx, "render aplica margem custom")
check(re.search(r'style:name="Footnote"[^>]*>.*?fo:font-size="14pt"',
                sx, re.S), "render aplica tamanho da nota")
sx = estilos_xml(gerar("# x"))
check('fo:margin-top="2cm"' in sx and re.search(
    r'style:name="Heading1"[^>]*>.*?fo:font-size="22pt"', sx, re.S),
    "sem estilos → padrão no render")

# ----------------------------------------------------------- diretivas
print("\n— diretivas: \\newpage, toc, numbering —")
cx = conteudo(gerar("antes\n\n\\newpage\n\ndepois"))
check('text:style-name="PageBreak"' in cx, "\\newpage vira PageBreak")
check('<text:p text:style-name="PageBreak"/>' in cx, "parágrafo PageBreak vazio")
check('fo:break-before="page"' in estilos_xml(gerar("\\newpage")),
      "estilo PageBreak com break-before=page")

md_toc = "<!-- toc -->\n\n# Introdução\n\ntexto\n\n## Detalhes\n\nmais"
cx = conteudo(gerar(md_toc))
check('text:style-name="Toc1"' in cx, "entrada Toc1 no sumário")
check('text:style-name="Toc2"' in cx, "entrada Toc2 no sumário")
check('xlink:href="#sec_1"' in cx, "link do sumário para #sec_1")
check('text:bookmark text:name="sec_1"' in cx, "bookmark sec_1 no título")
check("Introdução" in cx, "texto do título dentro do sumário")
cx = conteudo(gerar("# Introdução\n\ntexto"))
check("Toc1" not in cx and "text:bookmark" not in cx,
      "sem marcador toc: sem sumário nem bookmark")

md_num = "<!-- numbering -->\n\n# Primeiro\n\n## Sub\n\n# Segundo"
cx = conteudo(gerar(md_num))
check(">1 Primeiro</text:h>" in cx, "H1 numerado '1'")
check(">1.1 Sub</text:h>" in cx, "H2 numerado '1.1'")
check(">2 Segundo</text:h>" in cx, "segundo H1 numerado '2'")
cx = conteudo(gerar("# Primeiro\n\n## Sub"))
check(">Primeiro</text:h>" in cx and ">Sub</text:h>" in cx,
      "sem marcador: títulos sem numeração")

cx = conteudo(gerar("<!-- toc -->\n\n<!-- numbering -->\n\n# Um\n\n## Dois"))
check(">1 Um</text:a>" in cx, "sumário com numeração ('1 Um')")
check(">1.1 Dois</text:a>" in cx, "subentrada do sumário numerada")

# ------------------------------------------------------------ footnotes
print("\n— notas de rodapé —")
odt = gerar("Nota[^a] e outra[^b].\n\n[^a]: Primeira nota.\n\n"
            "[^b]: Segunda nota.")
cx = conteudo(odt)
check("<text:note" in cx, "nota de rodapé gerada")
check('text:note-class="footnote"' in cx, "classe footnote")
check("<text:note-citation>1</text:note-citation>" in cx, "citação 1")
check("<text:note-citation>2</text:note-citation>" in cx, "citação 2")
check('text:id="ftn1"' in cx and 'text:id="ftn2"' in cx, "ids ftn1/ftn2")
check("Primeira nota." in cx, "corpo da nota 1")
check("Segunda nota." in cx, "corpo da nota 2")
check('text:style-name="Footnote"' in cx, "corpo com estilo Footnote")
check(re.search(r'style:name="Footnote"[^>]*>.*?fo:font-size="10pt"',
                estilos_xml(odt), re.S), "nota padrão 10pt")
sx = estilos_xml(gerar("N[^1].\n\n[^1]: x.", estilos={"nota": 14}))
check(re.search(r'style:name="Footnote"[^>]*>.*?fo:font-size="14pt"',
                sx, re.S), "nota custom 14pt via render")

# ---------------------------------------------------------------- math
print("\n— fórmulas (MathML em Object N) —")
odt = gerar("Fórmula $x^2$ aqui e outra $e=mc^2$.")
z = abrir(odt)
cx = conteudo(odt)
check("Object 1/content.xml" in z.namelist(), "parte Object 1 no zip")
check("Object 2/content.xml" in z.namelist(), "parte Object 2 no zip")
mathml = z.read("Object 1/content.xml").decode()
check(mathml.startswith("<?xml"), "MathML com declaração XML")
check("<math" in mathml, "elemento <math> presente")
check("<semantics>" in mathml, "mathml com <semantics> (roundtrip x2t)")
manifest = z.read("META-INF/manifest.xml").decode()
check('full-path="Object 1/content.xml"' in manifest,
      "manifesto declara Object 1")
check('xlink:href="./Object 1"' in cx, "quadro aponta para ./Object 1")
check('svg:width="1.00cm"' in cx, "largura estimada mínimo 1cm (x^2)")
check(re.search(r'svg:width="\d+\.\d\dcm" svg:height="\d+\.\d\dcm"', cx),
      "quadro com width/height em cm")

cx = conteudo(gerar("$a+b$", math_dims=[(3.0, 0.8)]))
check('svg:width="3.00cm"' in cx and 'svg:height="0.80cm"' in cx,
      "math_dims do preview respeitadas")
cx = conteudo(gerar("$a+b$", math_dims=[(99.0, 0.1)]))
check('svg:width="17.00cm"' in cx and 'svg:height="0.40cm"' in cx,
      "dims clampadas nos tetos (17cm x 0.4cm)")
cx = conteudo(gerar("$a+b$", math_dims=[(3.0, 0.8), (9.0, 9.0)]))
check('svg:width="3.00cm"' in cx, "dims excedentes ignorados sem quebrar")

odt = gerar("$$\nE = mc^2\n$$")
mathml = abrir(odt).read("Object 1/content.xml").decode()
check('display="block"' in mathml, "fórmula em bloco → display=block")
cx = conteudo(odt)
check('<text:p text:style-name="TextBody">' in cx,
      "fórmula de bloco em parágrafo próprio")

# -------------------------------------------------------------- tabelas
print("\n— tabelas —")
md_tab = ("| Nome | Qtd | Status |\n|:---|:---:|---:|\n"
          "| a | 1 | ok |\n| b | x |")
odt = gerar(md_tab)
cx = conteudo(odt)
check('<table:table table:name="Tabela1"' in cx, "tabela nomeada Tabela1")
check('table:number-columns-repeated="3"' in cx, "3 colunas declaradas")
check("<table:table-header-rows>" in cx, "linha de cabeçalho repetível")
check(cx.count("<table:table-row>") == 3, "3 linhas (cabeçalho + 2 dados)")
check(cx.count("<table:table-cell") == 9, "9 células (linhas curtas completadas)")
check('style:column-width="5.667cm"' in cx,
      "largura de coluna = área útil / 3 (17/3)")
check('<text:p text:style-name="TRight"></text:p>' in cx,
      "célula faltante da linha 2 fica vazia com alinhamento da coluna")
check('<text:p text:style-name="TCenter">' in cx,
      "célula da coluna centralizada usa TCenter")
check('text:style-name="Strong"' in cx, "célula de cabeçalho em negrito")
check('style:name="Tabela1Cel"' in cx, "estilo automático de célula")
cx = conteudo(gerar(md_tab, estilos={"margemPagina": 3}))
check('style:column-width="5.000cm"' in cx,
      "coluna acompanha margem da página (15/3)")

# -------------------------------------------------------------- imagens
print("\n— imagens: formatos e estrutura —")
uri_png = imagem_uri(png_bytes(4, 2), "image/png")
odt = gerar(f"![vermelho]({uri_png})")
z = abrir(odt)
check(pictures(odt) == ["Pictures/img1.png"], "PNG embutido (Pictures/img1.png)")
manifest = z.read("META-INF/manifest.xml").decode()
check('full-path="Pictures/img1.png"' in manifest, "manifesto declara img1.png")
check("image/png" in manifest, "media-type image/png no manifesto")
cx = conteudo(odt)
check('xlink:href="Pictures/img1.png"' in cx, "draw:image aponta para img1.png")
check("<draw:image" in cx, "elemento draw:image presente")
check(re.search(r'svg:width="\d+\.\d\dcm" svg:height="\d+\.\d\dcm"', cx),
      "imagem com dimensões em cm")

from PIL import Image as PILImage  # noqa: E402


def _bytes(fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    PILImage.new("RGB", (8, 4), (0, 128, 255)).save(buf, fmt, **kw)
    return buf.getvalue()


svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
       b'<rect width="100" height="50" fill="red"/></svg>')
uris = [
    imagem_uri(png_bytes(), "image/png"),
    imagem_uri(_bytes("JPEG"), "image/jpeg"),
    imagem_uri(_bytes("GIF"), "image/gif"),
    imagem_uri(_bytes("WEBP"), "image/webp"),
    imagem_uri(_bytes("BMP"), "image/bmp"),
    imagem_uri(svg, "image/svg+xml"),
]
md_todos = "\n\n".join(f"![f{i}]({u})" for i, u in enumerate(uris))
odt = gerar(md_todos)
pics = pictures(odt)
check(pics == ["Pictures/img1.png", "Pictures/img2.jpg",
               "Pictures/img3.gif", "Pictures/img4.webp",
               "Pictures/img5.bmp", "Pictures/img6.svg"],
      "6 formatos embutidos com extensões corretas")
manifest = abrir(odt).read("META-INF/manifest.xml").decode()
check(all(t in manifest for t in ("image/png", "image/jpeg", "image/gif",
                                  "image/webp", "image/bmp", "image/svg+xml")),
      "media-types de todos os formatos no manifesto")

odt = gerar(f"![a]({uri_png})\n\n![b]({uri_png})")
check(pictures(odt) == ["Pictures/img1.png"], "imagem repetida = 1 cópia")
check(conteudo(odt).count('xlink:href="Pictures/img1.png"') == 2,
      "mesma imagem referenciada 2x")
check(len(pictures(gerar("# sem imagem"))) == 0,
      "chamada seguinte sem imagem não herda Pictures (reset de estado)")

print("\n— imagens: recusas e guardas —")
odt = gerar("![x](data:text/html;base64,PGJvZHk+)")
check(pictures(odt) == [] and "<draw:image" not in conteudo(odt),
      "data: de tipo não-imagem rejeitado (whitelist anti-XSS)")
odt = gerar("![x](data:image/png;base64,@@@lixo@@@)")
check(pictures(odt) == [], "base64 corrompido não gera Pictures")
check("[imagem: x]" in conteudo(odt), "fallback textual '[imagem: x]'")
grande = os.urandom(10 * 1024 * 1024 + 100)
odt = gerar(f"![g]({imagem_uri(grande, 'image/png')})")
check(pictures(odt) == [] and "[imagem: g]" in conteudo(odt),
      "imagem >10MB recusada com fallback")
odt = gerar("![i](http://127.0.0.1:1/x.png)")
check(pictures(odt) == [] and "[imagem:" in conteudo(odt),
      "URL em host privado bloqueada (SSRF)")
cx = conteudo(gerar("[clique](javascript:alert(1))"))
check('xlink:href="javascript' not in cx, "javascript: não vira link")

import odt_content as oc  # noqa: E402

check(oc._host_permitido("127.0.0.1") is False, "loopback bloqueado")
check(oc._host_permitido("10.0.0.2") is False, "rede privada 10/8 bloqueada")
check(oc._host_permitido("169.254.169.254") is False,
      "link-local (metadata cloud) bloqueado")
check(oc._host_permitido("localhost") is False, "localhost bloqueado")
check(oc._host_permitido("93.184.216.34") is True, "IP público permitido")
os.environ["MDTODOCS_REDE_LOCAL"] = "1"
check(oc._host_permitido("127.0.0.1") is True,
      "MDTODOCS_REDE_LOCAL=1 libera a rede local")
del os.environ["MDTODOCS_REDE_LOCAL"]

# ------------------------------------------------------- metadados/capa
print("\n— metadados: normalização, meta.xml e capa —")
from metadados import data_brasil, normalizar as normalizar_meta  # noqa: E402

m = normalizar_meta({"titulo": "T\x00este", "autor": "  Ana  ",
                     "data": "2026-10-30", "capa": True})
check(m["titulo"] == "Teste", "caracteres de controle removidos do título")
check(m["autor"] == "Ana", "autor aparado (strip)")
check(m["capa"] is True, "capa booleana true ligada")
check(normalizar_meta({"capa": "sim"})["capa"] is False,
      "capa só liga com booleano true (string não vale)")
check(normalizar_meta("lixo")["titulo"] == "", "entrada não-dict → padrão")
check(len(normalizar_meta({"titulo": "x" * 500})["titulo"]) == 200,
      "título limitado a 200 caracteres")
check(data_brasil("2026-10-30") == "30/10/2026", "ISO → DD/MM/AAAA")
check(data_brasil("31/12/2026") == "31/12/2026", "texto livre passa direto")

odt = gerar("# Corpo", meta={"titulo": "Meu Título", "autor": "Ana Silva",
                             "data": "2026-10-30", "capa": True})
cx, mx = conteudo(odt), parte(odt, "meta.xml")
check('<text:p text:style-name="CapaTitulo">Meu Título</text:p>' in cx,
      "capa com título")
check('CapaAutor">Ana Silva<' in cx, "capa com autor")
check('CapaData">30/10/2026<' in cx, "data ISO formatada na capa")
check('<text:p text:style-name="PageBreak"/>' in cx,
      "capa termina em quebra de página")
check(cx.find("CapaTitulo") < cx.find('text:style-name="Heading1"'),
      "capa ANTES do corpo")
check('style:name="CapaTitulo"' in cx, "estilos da capa no automatic-styles")
check("<dc:title>Meu Título</dc:title>" in mx, "dc:title no meta.xml")
check("<dc:creator>Ana Silva</dc:creator>" in mx, "dc:creator no meta.xml")
check("<meta:creation-date>2026-10-30</meta:creation-date>" in mx,
      "creation-date ISO do cliente")
check('xmlns:dc=' in mx, "namespace dc declarado no meta.xml")

odt = gerar("x", meta={"titulo": "A & B <c>", "capa": True})
check("<dc:title>A &amp; B &lt;c&gt;</dc:title>" in parte(odt, "meta.xml"),
      "título escapado no meta.xml")
check("A &amp; B &lt;c&gt;" in conteudo(odt), "título escapado na capa")

odt = gerar("# x")
mx, cx = parte(odt, "meta.xml"), conteudo(odt)
check("<meta:generator>mdToDocs</meta:generator>" in mx and "<dc:title>" not in mx,
      "sem meta → só o generator")
check("CapaTitulo" not in cx, "sem capa ativada → sem página de capa")

cx = conteudo(gerar("# x", meta={"capa": True}))
check("CapaTitulo" not in cx and "PageBreak" not in cx,
      "capa ligada mas sem campos → nada gerado")

odt = gerar("# x", meta="lixo")
check("<dc:title>" not in parte(odt, "meta.xml") and "CapaTitulo" not in conteudo(odt),
      "meta não-dict → comportamento padrão")

odt = gerar("x", meta={"titulo": "T", "data": "31/12/2026", "capa": True})
check(re.search(r"<meta:creation-date>\d{4}-\d{2}-\d{2}</meta:creation-date>",
                parte(odt, "meta.xml")),
      "data não-ISO → creation-date de hoje (xsd:date válido)")
check(">31/12/2026<" in conteudo(odt), "texto livre da data aparece na capa")

# ------------------------------------------------------------------- CLI
print("\n— CLI de arquivos —")
from md_parser import parse  # noqa: E402
from odt_writer import convert_markdown_file, write_odt  # noqa: E402

with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    md = t / "doc.md"
    md.write_text("# CLI ok\n\ntexto com acentuação.\n", encoding="utf-8")
    out = convert_markdown_file(md, t / "doc.odt")
    check(out.exists() and out.read_bytes() == gerar(md.read_text(
        encoding="utf-8")), "convert_markdown_file gera .odt idêntico")

    o2 = t / "x.odt"
    write_odt(o2, parse("# via write_odt"))
    check(o2.read_bytes() == gerar("# via write_odt"),
          "write_odt = render_odt em disco")

    PILImage.new("RGB", (4, 4), (1, 2, 3)).save(t / "foto.png", "PNG")
    md.write_text("![foto](foto.png)\n", encoding="utf-8")
    out = convert_markdown_file(md, t / "foto.odt")
    check(pictures(out.read_bytes()) == ["Pictures/img1.png"],
          "imagem relativa resolve ao lado do .md (base_dir)")

    check(pictures(gerar("![foto](foto.png)")) == [],
          "API sem base_dir recusa caminho relativo")

    sub = t / "sub"
    sub.mkdir()
    (t / "fora.png").write_bytes(png_bytes())
    md.write_text("![f](../fora.png)\n", encoding="utf-8")
    out = convert_markdown_file(md, sub / "n.odt")
    check(pictures(out.read_bytes()) == [],
          "imagem fora da pasta do .md bloqueada (traversal)")

resumo("pipeline")
