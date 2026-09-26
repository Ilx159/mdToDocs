"""Parser Markdown → estrutura intermediária de blocos.

Por que uma estrutura intermediária?

    markdown  ──parse──▶  [blocos/nós]  ──gerar──▶  XML do ODT

O parser (markdown-it-py) entende o markdown; este módulo organiza os
tokens dele numa árvore de nós simples. Assim, gerar o ODT é só
percorrer a árvore — não precisa mais se preocupar com markdown.
"""

import logging
import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.texmath import texmath_plugin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Nós INLINE (conteúdo de um parágrafo/título: texto, negrito, link...)
# ---------------------------------------------------------------------------

@dataclass
class Text:
    value: str


@dataclass
class Softbreak:
    """Quebra de linha suave no markdown (fim de linha, sem blank line)."""


@dataclass
class LineBreak:
    """Quebra forçada (duas espaços + Enter, ou \\\\ no fim da linha)."""


@dataclass
class Strong:
    children: list = field(default_factory=list)


@dataclass
class Emph:
    children: list = field(default_factory=list)


@dataclass
class InlineCode:
    value: str


@dataclass
class Link:
    href: str
    children: list = field(default_factory=list)


@dataclass
class Image:
    src: str
    alt: str = ""


@dataclass
class FootnoteRef:
    """Referência a uma nota de rodapé — `texto[^id]`.

    Depois do parse, `num` ganha o número exibido e `blocks` aponta para
    o conteúdo da definição `[^id]: ...` (resolvido em `_resolver_notas`).
    """
    label: str
    num: int | None = None
    blocks: list = field(default_factory=list)  # list[Block] da definição


@dataclass
class MathInline:
    """Matemática inline: `$x^2$` — guarda o LaTeX cru; a conversão
    para MathML acontece na hora de gerar o ODT (odt_content)."""
    latex: str


Inline = (
    Text
    | Softbreak
    | LineBreak
    | Strong
    | Emph
    | InlineCode
    | Link
    | Image
    | FootnoteRef
    | MathInline
)


# ---------------------------------------------------------------------------
# Tabelas
# ---------------------------------------------------------------------------

@dataclass
class TableCell:
    children: list[Inline] = field(default_factory=list)
    header: bool = False  # célula de cabeçalho (th)
    align: str | None = None  # left | center | right


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)


@dataclass
class Table:
    rows: list[TableRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Nós de BLOCO (parágrafo, título, lista, código, citação...)
# ---------------------------------------------------------------------------

@dataclass
class Paragraph:
    children: list[Inline] = field(default_factory=list)


@dataclass
class Heading:
    level: int  # 1..6
    children: list[Inline] = field(default_factory=list)
    # preenchidos em _resolver_estrutura:
    num: str | None = None       # "1.2" quando a numeração está ativa
    bookmark: str | None = None  # "sec_3" — âncora para links do sumário


@dataclass
class CodeBlock:
    content: str
    info: str = ""  # linguagem declarada depois de ```


@dataclass
class Blockquote:
    children: list = field(default_factory=list)  # list[Block]


@dataclass
class ListItem:
    children: list = field(default_factory=list)  # list[Block]


@dataclass
class BulletList:
    items: list[ListItem] = field(default_factory=list)


@dataclass
class OrderedList:
    items: list[ListItem] = field(default_factory=list)
    start: int = 1


@dataclass
class HorizontalRule:
    """Linha horizontal (--- ou *** sozinhos no markdown)."""


# ---------------------------------------------------------------------------
# Estrutura de artigo: quebra de página, sumário, numeração
# ---------------------------------------------------------------------------

@dataclass
class PageBreak:
    """Quebra de página explícita: parágrafo contendo só `\\newpage`."""


@dataclass
class TocEntry:
    """Uma linha do sumário."""
    level: int      # 1..6
    text: str       # título (já numerado, se a numeração estiver ativa)
    bookmark: str   # nome da âncora do título (ex.: "sec_3")


@dataclass
class Toc:
    """Marcador `<!-- toc -->` — as entradas são preenchidas em
    `_resolver_estrutura` a partir dos títulos do documento."""
    entries: list[TocEntry] = field(default_factory=list)


@dataclass
class Numbering:
    """Marcador `<!-- numbering -->` — ativa `1`, `1.1`, `1.1.1` nos títulos."""


# ---------------------------------------------------------------------------
# Notas de rodapé
# ---------------------------------------------------------------------------

@dataclass
class FootnoteDef:
    """Uma definição `[^id]: conteúdo` — conteúdo são blocos (pode ter
    vários parágrafos)."""
    label: str
    children: list = field(default_factory=list)  # list[Block]


@dataclass
class Footnotes:
    """Agrupador das definições (markdown-it emite todas no fim do doc).

    No ODT as definições NÃO viram uma seção no fim: cada referência
    carrega a sua definição para dentro de <text:note> (nota real de
    página). Este bloco fica na árvore só para exibição/debug.
    """
    defs: list[FootnoteDef] = field(default_factory=list)


@dataclass
class MathBlock:
    """Fórmula em bloco: `$$ ... $$` (linha própria)."""
    latex: str


Block = (
    Paragraph
    | Heading
    | CodeBlock
    | Blockquote
    | BulletList
    | OrderedList
    | Table
    | HorizontalRule
    | Footnotes
    | MathBlock
    | PageBreak
    | Toc
    | Numbering
)


# validateLink padrão do markdown-it: bloqueia data: fora de
# gif/png/jpeg/webp (whitelist anti-XSS). Nós permitemos também
# svg/bmp — em <img> o navegador não executa script de SVG, e
# javascript:/vbscript:/file: continuam bloqueados.
_DATA_IMAGE_OK = re.compile(r"^data:image/(gif|png|jpeg|webp|svg\+xml|bmp);")
_PROTO_BLOQUEADO = re.compile(r"^(vbscript|javascript|file|data):")


def _valida_link(url: str) -> bool:
    """Como MarkdownIt.validateLink, estendendo os data:image permitidos."""
    url = url.strip().lower()
    if _PROTO_BLOQUEADO.search(url):
        return bool(_DATA_IMAGE_OK.search(url))
    return True


def _build_parser() -> MarkdownIt:
    """Parser CommonMark + extensões: tabelas, notas e matemática."""
    md = (
        MarkdownIt("commonmark")
        .enable("table")
        .use(footnote_plugin)
        .use(texmath_plugin)
    )
    md.validateLink = _valida_link  # type: ignore[method-assign]
    return md


def _inline_text(tokens: list | None) -> str:
    """Achata tokens inline em texto puro (usado no alt de imagem).

    tokens pode ser None: `![](url)` (alt vazio) vem sem filhos.
    """
    return "".join(
        t.content for t in (tokens or []) if t.type in ("text", "code_inline")
    )


def _parse_inline(tokens: list, target: list[Inline]) -> None:
    """Converte os tokens inline do markdown-it em nós Inline.

    Usa uma pilha: ao ver `strong_open` cria um nó Strong e passa a
    inserir nele; ao ver `strong_close` volta para o nível anterior.
    """
    stack: list[list] = [target]
    for tok in tokens:
        t = tok.type
        if t == "text":
            stack[-1].append(Text(tok.content))
        elif t == "softbreak":
            stack[-1].append(Softbreak())
        elif t == "hardbreak":
            stack[-1].append(LineBreak())
        elif t == "code_inline":
            stack[-1].append(InlineCode(tok.content))
        elif t in ("strong_open", "em_open"):
            node: Strong | Emph = Strong() if t == "strong_open" else Emph()
            stack[-1].append(node)
            stack.append(node.children)
        elif t in ("strong_close", "em_close"):
            stack.pop()
        elif t == "link_open":
            node = Link(href=tok.attrGet("href") or "")
            stack[-1].append(node)
            stack.append(node.children)
        elif t == "link_close":
            stack.pop()
        elif t == "image":
            stack[-1].append(
                Image(src=tok.attrGet("src") or "", alt=_inline_text(tok.children))
            )
        elif t == "footnote_ref":
            # o label (id da nota) vem em meta, não em attrs
            stack[-1].append(FootnoteRef(label=str(tok.meta.get("label", ""))))
        elif t == "math_inline":
            stack[-1].append(MathInline(latex=tok.content))
        else:
            logger.warning("token inline não suportado: %s", t)


def parse(markdown: str) -> list[Block]:
    """Converte texto markdown numa lista de blocos."""
    tokens = _build_parser().parse(markdown)

    root: list[Block] = []
    # pilha de listas de filhos: o topo é onde inserir o nó atual
    stack: list[list] = [root]

    for tok in tokens:
        t = tok.type
        if t == "heading_open":
            node = Heading(level=int(tok.tag[1]))
            stack[-1].append(node)
            stack.append(node.children)
        elif t == "paragraph_open":
            node = Paragraph()
            stack[-1].append(node)
            stack.append(node.children)
        elif t == "inline":
            _parse_inline(tok.children, stack[-1])
        elif t in ("heading_close", "paragraph_close"):
            stack.pop()
        elif t == "fence":
            stack[-1].append(CodeBlock(content=tok.content, info=tok.info.strip()))
        elif t == "code_block":
            stack[-1].append(CodeBlock(content=tok.content))
        elif t == "blockquote_open":
            node = Blockquote()
            stack[-1].append(node)
            stack.append(node.children)
        elif t == "blockquote_close":
            stack.pop()
        elif t == "bullet_list_open":
            node = BulletList()
            stack[-1].append(node)
            stack.append(node.items)
        elif t == "ordered_list_open":
            node = OrderedList(start=int(tok.attrs.get("start", 1)))
            stack[-1].append(node)
            stack.append(node.items)
        elif t in ("bullet_list_close", "ordered_list_close"):
            stack.pop()
        elif t == "list_item_open":
            node = ListItem()
            stack[-1].append(node)
            stack.append(node.children)
        elif t == "list_item_close":
            stack.pop()
        elif t == "table_open":
            node = Table()
            stack[-1].append(node)
            stack.append(node.rows)
        elif t == "tr_open":
            node = TableRow()
            stack[-1].append(node)
            stack.append(node.cells)
        elif t in ("th_open", "td_open"):
            # alinhamento vem em attrs: style="text-align:center"
            estilo = tok.attrGet("style") or ""
            align = estilo.removeprefix("text-align:") or None
            node = TableCell(header=(t == "th_open"), align=align)
            stack[-1].append(node)
            stack.append(node.children)
        elif t in ("th_close", "td_close", "tr_close", "table_close"):
            stack.pop()
        elif t in ("thead_open", "thead_close", "tbody_open", "tbody_close"):
            # agrupamento sem estrutura própria — linhas/células bastam
            pass
        elif t == "hr":
            stack[-1].append(HorizontalRule())
        elif t == "footnote_block_open":
            node = Footnotes()
            stack[-1].append(node)
            stack.append(node.defs)
        elif t == "footnote_open":
            node = FootnoteDef(label=str(tok.meta.get("label", "")))
            stack[-1].append(node)
            stack.append(node.children)
        elif t in ("footnote_close", "footnote_block_close"):
            stack.pop()
        elif t == "footnote_anchor":
            # marcador interno do plugin (âncora de volta à referência)
            pass
        elif t == "math_block":
            stack[-1].append(MathBlock(latex=tok.content))
        elif t == "html_block":
            # marcadores de estrutura: <!-- toc --> e <!-- numbering -->
            marca = re.sub(r"\s+", "", tok.content.lower())
            if marca == "<!--toc-->":
                stack[-1].append(Toc())
            elif marca == "<!--numbering-->":
                stack[-1].append(Numbering())
            else:
                logger.warning("html de bloco ignorado: %r", tok.content.strip())
        else:
            logger.warning("token de bloco não suportado: %s", t)

    _resolver_notas(root)
    _resolver_estrutura(root)
    return root


# ---------------------------------------------------------------------------
# Estrutura de artigo (quebras, numeração, sumário)
# ---------------------------------------------------------------------------

def _resolver_estrutura(root: list[Block]) -> None:
    """Aplica as marcações de estrutura do artigo.

    - parágrafo contendo só `\\newpage` vira PageBreak;
    - `<!-- numbering -->` liga a numeração dos títulos (1, 1.1, 1.1.1);
    - `<!-- toc -->` preenche as entradas do sumário a partir dos
      títulos do nível raiz, cada um com âncora `sec_N` (mesmo nome
      usado como id no preview).

    Só os títulos do nível raiz participam — o preview espelha essa
    escolha selecionando apenas h1..h6 diretos do container.
    """
    # 1) \newpage → PageBreak
    for i, b in enumerate(root):
        if (
            isinstance(b, Paragraph)
            and len(b.children) == 1
            and isinstance(b.children[0], Text)
            and b.children[0].value.strip() == r"\newpage"
        ):
            root[i] = PageBreak()

    tem_toc = any(isinstance(b, Toc) for b in root)
    tem_num = any(isinstance(b, Numbering) for b in root)

    # 2) numeração sequencial por nível (1, 1.1, 1.2.3...)
    contadores = [0] * 7
    for h in (b for b in root if isinstance(b, Heading)):
        contadores[h.level] += 1
        for nivel_mais_fundo in range(h.level + 1, 7):
            contadores[nivel_mais_fundo] = 0
        if tem_num:
            h.num = ".".join(str(contadores[n]) for n in range(1, h.level + 1))

    # 3) âncoras + entradas do sumário
    if tem_toc:
        titulos = [b for b in root if isinstance(b, Heading)]
        for i, h in enumerate(titulos, start=1):
            h.bookmark = f"sec_{i}"
        entradas = [
            TocEntry(
                level=h.level,
                text=f"{h.num} {_inline_plano(h.children)}" if h.num
                else _inline_plano(h.children),
                bookmark=h.bookmark or "",
            )
            for h in titulos
        ]
        for b in root:
            if isinstance(b, Toc):
                b.entries = list(entradas)


# ---------------------------------------------------------------------------
# Resolução das notas de rodapé
# ---------------------------------------------------------------------------

def _resolver_notas(root: list[Block]) -> None:
    """Preenche cada FootnoteRef com número e conteúdo da sua definição.

    As definições vêm TODAS no fim do documento (padrão markdown-it),
    mas no ODT a nota precisa aparecer na página em que a REFERÊNCIA
    está — por isso carregamos o conteúdo para dentro do ref.
    """
    # 1) coleta definições em ordem → número exibido = ordem das defs
    defs: dict[str, FootnoteDef] = {}
    for b in root:
        if isinstance(b, Footnotes):
            for fd in b.defs:
                defs.setdefault(fd.label, fd)

    nums = {label: i + 1 for i, label in enumerate(defs)}

    # 2) percorre a árvore marcando as referências
    def aplicar_inline(nodes: list[Inline]) -> None:
        for n in nodes:
            if isinstance(n, FootnoteRef):
                fd = defs.get(n.label)
                if fd is None:
                    logger.warning("nota referenciada sem definição: [^%s]", n.label)
                else:
                    n.num = nums[n.label]
                    n.blocks = fd.children
            elif isinstance(n, (Strong, Emph, Link)):
                aplicar_inline(n.children)

    def aplicar(blocos: list[Block]) -> None:
        for b in blocos:
            if isinstance(b, (Paragraph, Heading)):
                aplicar_inline(b.children)
            elif isinstance(b, Blockquote):
                aplicar(b.children)
            elif isinstance(b, (BulletList, OrderedList)):
                for item in b.items:
                    aplicar(item.children)
            elif isinstance(b, Table):
                for row in b.rows:
                    for cell in row.cells:
                        aplicar_inline(cell.children)

    aplicar(root)


# ---------------------------------------------------------------------------
# Visualização da árvore (para debug/estudo)
# ---------------------------------------------------------------------------

def dump(blocks: list[Block], indent: int = 0) -> str:
    linhas = []
    for b in blocks:
        prefix = "  " * indent
        if isinstance(b, Heading):
            extra = f" num={b.num!r}" if b.num else ""
            linhas.append(f"{prefix}Heading h{b.level}{extra}")
            linhas.append(dump_inline(b.children, indent + 1))
        elif isinstance(b, Paragraph):
            linhas.append(f"{prefix}Paragraph")
            linhas.append(dump_inline(b.children, indent + 1))
        elif isinstance(b, CodeBlock):
            primeira = b.content.strip().splitlines()[:1]
            linhas.append(f"{prefix}CodeBlock lang={b.info!r} {primeira}")
        elif isinstance(b, Blockquote):
            linhas.append(f"{prefix}Blockquote")
            linhas.append(dump(b.children, indent + 1))
        elif isinstance(b, (BulletList, OrderedList)):
            nome = "OrderedList" if isinstance(b, OrderedList) else "BulletList"
            extra = f" start={b.start}" if isinstance(b, OrderedList) and b.start != 1 else ""
            linhas.append(f"{prefix}{nome}{extra}")
            for item in b.items:
                linhas.append(f"{prefix}  ListItem")
                linhas.append(dump(item.children, indent + 2))
        elif isinstance(b, Table):
            linhas.append(f"{prefix}Table {len(b.rows)} linhas")
            for row in b.rows:
                desc = ", ".join(
                    ("TH:" if c.header else "TD:")
                    + (f"{c.align}|" if c.align else "")
                    + _inline_plano(c.children)
                    for c in row.cells
                )
                linhas.append(f"{prefix}  Row [{desc}]")
        elif isinstance(b, HorizontalRule):
            linhas.append(f"{prefix}HorizontalRule")
        elif isinstance(b, Footnotes):
            linhas.append(f"{prefix}Footnotes ({len(b.defs)} definições)")
            for fd in b.defs:
                linhas.append(f"{prefix}  FootnoteDef [^{fd.label}]")
                linhas.append(dump(fd.children, indent + 2))
        elif isinstance(b, MathBlock):
            linhas.append(f"{prefix}MathBlock {b.latex!r}")
        elif isinstance(b, PageBreak):
            linhas.append(f"{prefix}PageBreak")
        elif isinstance(b, Numbering):
            linhas.append(f"{prefix}Numbering (marcador)")
        elif isinstance(b, Toc):
            linhas.append(f"{prefix}Toc ({len(b.entries)} entradas)")
            for e in b.entries:
                linhas.append(
                    f"{prefix}  TocEntry h{e.level} {e.text!r} -> {e.bookmark}"
                )
    return "\n".join(l for l in linhas if l)


def _inline_plano(nodes: list[Inline]) -> str:
    """Achata nós inline em texto puro (para visualização em tabelas)."""
    partes = []
    for n in nodes:
        if isinstance(n, Text):
            partes.append(n.value)
        elif isinstance(n, InlineCode):
            partes.append(f"`{n.value}`")
        elif isinstance(n, (Strong, Emph, Link)):
            partes.append(_inline_plano(n.children))
        elif isinstance(n, Image):
            partes.append(f"[img {n.alt}]")
    return "".join(partes)


def dump_inline(nodes: list[Inline], indent: int = 0) -> str:
    prefix = "  " * indent
    linhas = []
    for n in nodes:
        if isinstance(n, Text):
            linhas.append(f"{prefix}Text {n.value!r}")
        elif isinstance(n, (Softbreak, LineBreak)):
            linhas.append(f"{prefix}{type(n).__name__}")
        elif isinstance(n, InlineCode):
            linhas.append(f"{prefix}InlineCode {n.value!r}")
        elif isinstance(n, Strong):
            linhas.append(f"{prefix}Strong")
            linhas.append(dump_inline(n.children, indent + 1))
        elif isinstance(n, Emph):
            linhas.append(f"{prefix}Emph")
            linhas.append(dump_inline(n.children, indent + 1))
        elif isinstance(n, Link):
            linhas.append(f"{prefix}Link href={n.href!r}")
            linhas.append(dump_inline(n.children, indent + 1))
        elif isinstance(n, Image):
            linhas.append(f"{prefix}Image src={n.src!r} alt={n.alt!r}")
        elif isinstance(n, FootnoteRef):
            linhas.append(f"{prefix}FootnoteRef [^{n.label}] num={n.num}")
        elif isinstance(n, MathInline):
            linhas.append(f"{prefix}MathInline {n.latex!r}")
    return "\n".join(l for l in linhas if l)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    amostra = """\
# Artigo de Exemplo

Texto com **negrito**, *itálico* e `código`.

## Seções

- item simples
- item com [link](https://example.com)
  - aninhado

1. primeiro
2. segundo

> Uma citação
> com duas linhas.

```python
print("oi")
```
"""
    blocos = parse(amostra)
    print(dump(blocos))
