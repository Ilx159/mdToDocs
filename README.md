# mdToDocs

Ferramenta web que converte Markdown em arquivos ODT (Open Document Text), pensada para facilitar a criação de artigos com controle total sobre a aparência do documento final.

## Visão geral

- **Entrada:** arquivos Markdown (`.md`) escritos num editor web com preview ao vivo
- **Saída:** arquivo `.odt` válido gerado sob medida (ZIP contendo XML)
- **Uso principal:** criação de artigos, com controle total de estilos (fontes, margens, espaçamento, estrutura)

## Decisões de projeto

| Aspecto | Decisão |
|---|---|
| Linguagem backend | **Python** (possível rewrite futuro em linguagem mais eficiente) |
| Interface | **Web** — hospedada em servidor próprio |
| Stack | **FastAPI + JavaScript vanilla** |
| Preview | **Live preview síncrono** (renderiza enquanto digita) |
| Geração do ODT | **ZIP/XML manual** — controle total de estilos, tabelas e math |
| Estilos | **Editor de estilos na interface** (fontes, tamanhos, margens, espaçamento por elemento) |
| Persistência | **Navegador** (localStorage/IndexedDB) como fallback; **upload/download de arquivos** como fluxo principal |

## Recursos Markdown suportados

- **Básico completo:** títulos, negrito, itálico, listas (ordenadas/desordenadas), links, código (inline e blocos), citações, imagens
- **Tabelas avançadas:** alinhamento de colunas, células complexas
- **Footnotes:** notas de rodapé `[^1]`
- **Math/LaTeX:** fórmulas matemáticas renderizadas no ODT
- **Estrutura de artigo:** quebras de página, sumário automático, numeração de seções

## Escopo da primeira versão (MVP)

1. Editor markdown com live preview
2. Painel de estilos (aparência do ODT)
3. Botão de exportação para `.odt`
4. Upload/download de arquivos `.md`

Fora do MVP (futuro): múltiplos documentos em abas, sumário navegável, temas prontos, undo/redo.

## Status

**MVP implementado**, incluindo todos os itens do escopo:

- Editor markdown com live preview (Web | ODT) — `frontend/app.js`
- Footnotes (`[^1]`), Math/LaTeX (`$...$`), tabelas, imagens embutidas
- **Biblioteca de imagens** (IndexedDB): importa uma vez e o markdown
  linka por `![alt](img:nome.png)`; preview e export resolvem o nome
  para os bytes (o .md fica leve, sem data URI gigante)
- Estrutura de artigo: `\newpage`, `<!-- toc -->`, `<!-- numbering -->`
- **Painel de estilos** (fonte, corpo, entrelinha, margens, títulos H1–H6,
  notas) — mesmo dicionário no preview (variáveis CSS) e no `styles.xml`
  (`backend/styles.py`), com persistência em localStorage
- **Interface refatorada** (`frontend/interface.js`): tema claro/escuro
  (com "seguir sistema" e aplicação antes do 1º paint), ícones com tooltip
  no header, divisória editor/preview arrastável com proporção salva,
  drawers de Estilos/Imagens que **flutuam** (arrastar pelo topo) ou se
  **fixam** na lateral (soltar perto da borda / botão 📌), e modal de
  Configurações (⚙) com cor de destaque, fonte/tamanho do editor e
  animações
- **Docker**: `Dockerfile` (python:3.13-slim, usuário sem privilégios,
  healthcheck) + `docker-compose.yml` com código montado e hot reload do
  backend
- Exportação `.odt` via `POST /api/convert` + upload/download de `.md`

Como rodar (na raiz do projeto):

```bash
./rodar.sh                   # sobe o container e confirma que responde
./rodar.sh logs              # acompanhar | ./rodar.sh stop = parar
# abre http://localhost:8321
# backend com hot reload (--reload); frontend estático reflete na hora

# sem Docker
.venv/bin/uvicorn main:app --app-dir backend --port 8321
```

Validações: `scripts/verificar.py` (ODT → PDF visual), testes unitários
de backend e suíte e2e com Firefox headless (abrir painel, editar estilo,
ver o preview, exportar e conferir o payload).

## Estrutura atual

```
mdToDocs/
├── README.md
├── Dockerfile           # imagem do servidor (python:3.13-slim)
├── docker-compose.yml   # sobe com mounts + hot reload do backend
├── rodar.sh             # sobe/para/logs do container em 1 comando
├── backend/
│   ├── main.py          # FastAPI: endpoints de conversão
│   ├── md_parser.py     # Parsing do Markdown (footnotes, tables, math, estrutura)
│   ├── odt_content.py   # blocos → content.xml (fórmulas, imagens, tabelas)
│   ├── odt_writer.py    # montagem do ZIP/XML do ODT
│   └── styles.py        # modelo de estilos → styles.xml (painel)
├── frontend/
│   ├── index.html       # layout, ícones, drawers e modal de config
│   ├── styles.css       # temas (claro/escuro), modo ODT, drawers, modal
│   ├── interface.js     # tema/config, split, drawers (flutuar/fixar)
│   ├── biblioteca.js    # imagens no navegador (IndexedDB, img:nome)
│   └── app.js           # preview, painéis, persistência, API
└── scripts/
    └── verificar.py     # .md → .odt → .pdf → .png para inspeção visual
```
