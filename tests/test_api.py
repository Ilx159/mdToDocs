#!/usr/bin/env python3
"""Suíte da API HTTP contra o servidor vivo (MDTODOCS_URL).

Sobe o servidor com ./rodar.sh (ou aponte MDTODOCS_URL para outro host,
ex.: MDTODOCS_URL=http://10.0.0.2:8321).
"""
import json
import re

from _common import (BASE, abrir, check, imagem_uri, png_bytes,
                     post_convert, requisitar, resumo)

print(f"servidor alvo: {BASE}")

# ------------------------------------------------------------ saúde/front
print("\n— saúde e frontend —")
st, _, corpo = requisitar("GET", "/api/health")
check(st == 200, "GET /api/health → 200")
dados = json.loads(corpo) if st == 200 else {}
check(dados.get("status") == "ok", "health devolve status ok")
check(bool(dados.get("version")), "health devolve versão")

st, _, corpo = requisitar("GET", "/")
check(st == 200, "GET / → 200 (frontend)")
html = corpo.decode("utf-8", "replace")
check("<title>mdToDocs" in html, "index.html com título")
check('id="editor"' in html, "editor no index.html")
st, _, _ = requisitar("GET", "/nao-existe-isto")
check(st == 404, "arquivo estático inexistente → 404")

# -------------------------------------------------------- conversão feliz
print("\n— conversão feliz —")
st, hd, corpo = post_convert("# Olá\n\n**forte**", filename="artigo")
check(st == 200, "POST /api/convert → 200")
check(hd.get("content-type", "").startswith(
    "application/vnd.oasis.opendocument.text"), "Content-Type ODT")
disp = hd.get("content-disposition", "")
check('filename="artigo.odt"' in disp, "Content-Disposition artigo.odt")
check(hd.get("content-length") == str(len(corpo)), "Content-Length correto")
z = abrir(corpo)
check(z.testzip() is None, "corpo é um zip íntegro")
check(z.read("mimetype") == b"application/vnd.oasis.opendocument.text",
      "corpo é ODF texto válido")
cx = z.read("content.xml").decode()
check("Olá" in cx and 'text:style-name="Strong"' in cx,
      "conteúdo convertido (título + negrito)")

st, _, corpo = post_convert("")
check(st == 200 and abrir(corpo).read("mimetype") ==
      b"application/vnd.oasis.opendocument.text",
      "markdown vazio → 200 com ODT válido")

# -------------------------------------------------------------- filename
print("\n— sanitização do filename —")
st, hd, _ = post_convert("oi", filename="")
check('filename="documento.odt"' in hd.get("content-disposition", ""),
      "filename vazio → documento.odt")
st, hd, _ = post_convert("oi", filename="já é.odt")
check('filename="já é.odt"' in hd.get("content-disposition", ""),
      ".odt existente não é duplicado")
st, hd, _ = post_convert('oi', filename='pasta/ilegal:*?"<>|.md')
m = re.search(r'filename="([^"]+)"', hd.get("content-disposition", ""))
fn = m.group(1) if m else ""
check(fn.endswith(".odt") and not set('/:*?"<>|\\') & set(fn),
      f"nome perigoso sanitizado ({fn!r})")
st, hd, _ = post_convert("oi", filename="ação")
check(st == 200 and "ação.odt" in hd.get("content-disposition", ""),
      "filename com acento aceito")

# ---------------------------------------------------------------- erros
print("\n— erros —")
st, _, _ = post_convert("x" * 2_000_001)
check(st == 413, "markdown >2MB → 413")
st, _, corpo = requisitar("POST", "/api/convert",
                          datos=b"{markdown: quebrado",
                          headers={"Content-Type": "application/json"})
check(st == 422, "JSON inválido → 422")
st, _, corpo = requisitar("POST", "/api/convert",
                          datos=json.dumps({"filename": "sem md"}).encode(),
                          headers={"Content-Type": "application/json"})
check(st == 422 and b"markdown" in corpo, "campo markdown ausente → 422")
st, _, _ = post_convert("oi", estilos="não-dict")
check(st == 422, "estilos não-dict → 422 (pydantic)")
st, _, _ = post_convert("oi", math_dims=["x"])
check(st == 422, "math_dims inválido → 422 (pydantic)")

# -------------------------------------------------------------- estilos
print("\n— estilos via API —")
st, _, corpo = post_convert("# t", estilos={"tamanho": 15, "h1": 30,
                                            "margemPagina": 3.5,
                                            "fonte": "Verdana", "nota": 14})
sx = abrir(corpo).read("styles.xml").decode()
check('fo:font-size="15pt"' in sx and 'fo:font-size="30pt"' in sx,
      "estilos custom aplicados via API")
check('fo:margin-top="3.5cm"' in sx, "margem da página via API")
check('svg:font-family="Verdana"' in sx, "fonte custom via API")
st, _, corpo = post_convert("# t", estilos={"fonte": 'Foo"><evil x="'})
sx = abrir(corpo).read("styles.xml").decode()
check("<evil" not in sx and 'svg:font-family="Foo' in sx,
      "injeção XML na fonte sanitizada")

# -------------------------------------------------------- doc completo
print("\n— documento completo de ponta a ponta —")
md_doc = (
    "<!-- toc -->\n\n# Um\n\n"
    "Texto **forte**, `cod`, [l](https://x.org), nota[^1], $x^2$.\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
    "\\newpage\n\n## Dois\n\n[^1]: fim.\n"
)
st, _, corpo = post_convert(md_doc)
check(st == 200, "documento completo → 200")
z = abrir(corpo)
cx = z.read("content.xml").decode()
check('text:style-name="Toc1"' in cx, "toc no documento")
check('text:style-name="PageBreak"' in cx, "newpage no documento")
check("<text:note" in cx, "footnote no documento")
check("Object 1/content.xml" in z.namelist(), "fórmula em Object 1")
check('<table:table table:name="Tabela1"' in cx, "tabela no documento")
check('xlink:href="https://x.org"' in cx, "link no documento")
check('text:style-name="InlineCode"' in cx, "código inline no documento")

# -------------------------------------------------- stateless/determinismo
print("\n— statelessness —")
st, _, c1 = post_convert("# Um")
st, _, c2 = post_convert("# Dois")
st, _, c3 = post_convert("# Um")
z1, z2, z3 = (abrir(c) for c in (c1, c2, c3))
check(z1.read("content.xml") != z2.read("content.xml"),
      "payloads diferentes → content.xml diferente")
check(z1.read("content.xml") == z3.read("content.xml")
      and z1.read("styles.xml") == z3.read("styles.xml"),
      "mesmo payload → mesmo conteúdo (stateless)")

# -------------------------------------------------------- metadados
print("\n— metadados via API —")
st, _, corpo = post_convert(
    "# Doc", meta={"titulo": "Relatório & Plano", "autor": "Zé",
                   "data": "2026-10-30", "capa": True})
check(st == 200, "convert com meta → 200")
z = abrir(corpo)
mx = z.read("meta.xml").decode()
cx = z.read("content.xml").decode()
check("<dc:title>Relatório &amp; Plano</dc:title>" in mx,
      "dc:title escapado via API")
check("<dc:creator>Zé</dc:creator>" in mx, "dc:creator via API")
check("<meta:creation-date>2026-10-30</meta:creation-date>" in mx,
      "creation-date via API")
check('CapaTitulo">Relatório &amp; Plano<' in cx, "capa no content via API")
check(">30/10/2026<" in cx, "data formatada na capa via API")

st, _, corpo = post_convert("# Doc", meta={"capa": "sim"})
check(st == 200 and b"CapaTitulo" not in abrir(corpo).read("content.xml"),
      "capa string não liga a capa (booleano estrito)")

st, _, _ = post_convert("x", meta="nao-dict")
check(st == 422, "meta não-dict → 422 (pydantic)")

# -------------------------------------------------------------- imagens
print("\n— imagens pela API —")
uri_png = imagem_uri(png_bytes(4, 2), "image/png")
st, _, corpo = post_convert(f"![a]({uri_png})")
check(st == 200 and "Pictures/img1.png" in abrir(corpo).namelist(),
      "data URI de imagem embutido via API")
st, _, corpo = post_convert("![i](http://127.0.0.1:1/x.png)")
z = abrir(corpo)
check(not any(n.startswith("Pictures/") for n in z.namelist()),
      "URL privada não gera Pictures (SSRF na API)")
check("[imagem:" in z.read("content.xml").decode(),
      "fallback textual para imagem bloqueada")

resumo("api")
