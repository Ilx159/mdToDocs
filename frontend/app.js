/* mdToDocs — editor com live preview + exportação via API.
 *
 * Fluxo de exportação:
 *   textarea → POST /api/convert → bytes .odt → download no navegador
 * O servidor nunca guarda nada; persistimos o texto no localStorage.
 */

const editor = document.getElementById("editor");
const preview = document.getElementById("preview");
const filenameInput = document.getElementById("filename");
const statusEl = document.getElementById("status");
const abrirInput = document.getElementById("abrir-md");
const btnModoWeb = document.getElementById("modo-web");
const btnModoOdt = document.getElementById("modo-odt");

// Mesma biblioteca do backend (md_parser) → preview fiel ao ODT gerado
const md = window.markdownit("commonmark").enable("table");
if (window.markdownitFootnote) {
  // notas de rodapé: mesma extensão usada no backend (mdit-py-plugins)
  md.use(window.markdownitFootnote);
}
if (window.texmath && window.temml) {
  // matemática $...$/$$...$$: mesmo plugin do backend; o engine temml
  // converte LaTeX → MathML (o backend usa latex2mathml — mesmo destino)
  md.use(window.texmath, { engine: window.temml, delimiters: "dollars" });
}

// validateLink padrão só aceita data:image/(gif|png|jpeg|webp) —
// estendemos para svg/bmp (igual ao _valida_link do backend; script
// dentro de SVG carregado por <img> não executa). javascript:/file:
// continuam bloqueados dos dois lados.
md.validateLink = (url) => {
  const u = url.trim().toLowerCase();
  if (/^(vbscript|javascript|file|data):/.test(u)) {
    return /^data:image\/(gif|png|jpeg|webp|svg\+xml|bmp);/.test(u);
  }
  return true;
};

const STORAGE_KEY = "mdtodocs:documento";
const MODO_KEY = "mdtodocs:modo";

// "web" = visual de site | "odt" = aproxima a página A4 do .odt exportado
let modo = "web";

const EXEMPLO = `<!-- toc -->
<!-- numbering -->

# Meu artigo

Escreva em **markdown** e veja o resultado ao lado.
A equação $E=mc^2$ aparece no meio do texto.

## Seções

- item um
- item dois

> citação

| Esquerda | Centro | Direita |
|:---------|:------:|--------:|
| a        | b      | c       |

Uma nota de rodapé[^nota].

[^nota]: Notas viram nota real de página no .odt.

\\newpage

\`\`\`python
print("código")
\`\`\`
`;

// ---------- utilidades ----------

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function setStatus(texto) {
  statusEl.textContent = texto;
}

// ---------- live preview (renderiza enquanto digita) ----------

function renderizarPreview() {
  preview.innerHTML = `<div class="pagina">${md.render(editor.value)}</div>`;
  estruturaPreview();
  // ![alt](img:nome) → objectURL da biblioteca (IndexedDB)
  resolverImagensPreview();
  if (modo === "odt") {
    // imagens são reais nos dois modos (o .odt embute o binário em
    // Pictures/ — ver backend/odt_content.py); só as notas mudam
    posicionarNotas();
  }
}

// ---------- estrutura do artigo: numeração, sumário, quebras ----------
// Espelha o _resolver_estrutura do backend:
//   <!-- numbering -->  → títulos ganham "1", "1.1", "1.1.1"...
//   <!-- toc -->        → o comentário vira lista de links (#sec_N)
//   parágrafo \newpage  → vira divisor "quebra de página"
// Só títulos DIRETOS do .pagina participam (igual ao backend, que
// considera apenas o nível raiz).
function estruturaPreview() {
  const pagina = preview.querySelector(".pagina");
  if (!pagina) return;

  // acha os marcadores (nós comentário preservados pelo innerHTML;
  // o data de um nó comentário NÃO inclui os <!-- -->)
  let temToc = false;
  let temNum = false;
  const walker = document.createTreeWalker(pagina, NodeFilter.SHOW_COMMENT);
  const comentarios = [];
  while (walker.nextNode()) comentarios.push(walker.currentNode);
  for (const c of comentarios) {
    const marca = c.data.trim().toLowerCase();
    if (marca === "toc") temToc = true;
    if (marca === "numbering") temNum = true;
  }

  // \newpage → divisor visual (no .odt real é uma quebra de verdade)
  pagina.querySelectorAll("p").forEach((p) => {
    if (p.textContent.trim() === "\\newpage") {
      const hr = document.createElement("hr");
      hr.className = "quebra";
      p.replaceWith(hr);
    }
  });

  // títulos: âncora + numeração
  const titulos = [...pagina.children].filter((el) => /^H[1-6]$/.test(el.tagName));
  const contadores = [0, 0, 0, 0, 0, 0, 0];
  titulos.forEach((h, i) => {
    h.id = `sec_${i + 1}`; // mesmo nome do bookmark no .odt
    if (temNum) {
      const nivel = Number(h.tagName[1]);
      contadores[nivel] += 1;
      for (let k = nivel + 1; k <= 6; k++) contadores[k] = 0;
      const num = contadores.slice(1, nivel + 1).join(".");
      h.insertBefore(document.createTextNode(`${num} `), h.firstChild);
    }
  });

  // sumário: troca o comentário por links para os títulos
  if (temToc) {
    const alvo = comentarios.find((c) => c.data.trim().toLowerCase() === "toc");
    if (alvo) {
      const ul = document.createElement("ul");
      ul.className = "toc";
      for (const h of titulos) {
        const a = document.createElement("a");
        a.href = `#${h.id}`;
        a.className = `toc-n${h.tagName[1]}`;
        a.textContent = h.textContent;
        const li = document.createElement("li");
        li.appendChild(a);
        ul.appendChild(li);
      }
      alvo.replaceWith(ul);
    }
  }
}

// O navegador não pagina (isso exigiria um motor de paginação), mas
// quando o conteúdo cabe numa folha só, tiramos o bloco de notas do
// fluxo e o ancoramos no pé da folha — como o .odt real faz. Usamos
// posição absoluta (e não margem) porque o Firefox trata a margem do
// <hr> de forma inconsistente na hora de calcular a altura do
// container, o que deixaria a medição ~9px errada. Se não couber,
// as notas fluem logo após o conteúdo (comportamento de antes).
function posicionarNotas() {
  const pagina = preview.querySelector(".pagina");
  const notas = preview.querySelector("section.footnotes");
  if (!pagina || !notas) return;

  // desfaz um posicionamento anterior (resize/fonts) para medir limpo
  const wrapper = preview.querySelector(".notas-pe");
  if (wrapper) {
    const pai = wrapper.parentNode;
    while (wrapper.firstChild) pai.insertBefore(wrapper.firstChild, wrapper);
    wrapper.remove();
  }

  const cs = getComputedStyle(pagina);
  const padTop = parseFloat(cs.paddingTop);
  const padBottom = parseFloat(cs.paddingBottom);
  const topoUtil = pagina.getBoundingClientRect().top + padTop;
  const alturaUtil = pagina.clientHeight - padTop - padBottom;
  const fimNotas = notas.getBoundingClientRect().bottom - topoUtil;
  if (alturaUtil - fimNotas <= 1) return; // não coubeu numa folha

  // coubeu: régua + notas vão para o pé da folha (.notas-pe no CSS
  // ancora em position absolute na borda do conteúdo da .pagina)
  const sep = preview.querySelector("hr.footnotes-sep");
  const bloco = document.createElement("div");
  bloco.className = "notas-pe";
  (sep || notas).parentNode.insertBefore(bloco, sep || notas);
  if (sep) bloco.appendChild(sep);
  bloco.appendChild(notas);
}

// Mede o MathML já renderizado pelo navegador → tamanho real de cada
// fórmula em cm (a API usa isso no draw:frame; sem isso o backend
// estima pelo código LaTeX e pode cortar fórmulas largas).
// Ordem do DOM = ordem em que o backend gera os quadros (a única
// divergência conhecida é fórmula dentro de nota, cujo corpo no
// preview fica no fim do documento).
function medirFormulas() {
  const pxParaCm = 2.54 / 96; // CSS assume 96dpi
  return Array.from(preview.querySelectorAll("math"), (el) => {
    const r = el.getBoundingClientRect();
    return [
      Math.round(r.width * pxParaCm * 1000) / 1000,
      Math.round(r.height * pxParaCm * 1000) / 1000,
    ];
  });
}

const renderizarDebounced = debounce(renderizarPreview, 120);
editor.addEventListener("input", renderizarDebounced);

// ---------- modo do preview (web x odt) ----------

function setModo(novo) {
  modo = novo;
  preview.classList.toggle("odt", novo === "odt");
  btnModoWeb.classList.toggle("ativo", novo === "web");
  btnModoOdt.classList.toggle("ativo", novo === "odt");
  localStorage.setItem(MODO_KEY, novo);
  renderizarPreview();
}

btnModoWeb.addEventListener("click", () => setModo("web"));
btnModoOdt.addEventListener("click", () => setModo("odt"));

// ---------- painel de estilos ----------
// Mesmo dicionário do backend (backend/styles.py): normalizar() lá e
// normalizarEstilos() aqui aplicam os MESMOS limites — o preview vira
// variáveis CSS em #preview e o .odt recebe o styles.xml equivalente.
const ESTILOS_KEY = "mdtodocs:estilos";

const ESTILOS_PADRAO = {
  fonte: "Liberation Serif",
  tamanho: 12,            // pt
  entrelinha: 1.2,        // multiplicador
  margemParagrafo: 0.25,  // cm
  margemPagina: 2,        // cm — os 4 lados da A4
  h1: 22, h2: 18, h3: 16, // pt
  h4: 14, h5: 13, h6: 12,
  nota: 10,               // pt — notas de rodapé
};

const ESTILOS_LIMITES = {
  tamanho: [6, 72],
  entrelinha: [1, 3],
  margemParagrafo: [0, 2],
  margemPagina: [0.5, 4],
  h1: [6, 72],
  h2: [6, 72],
  h3: [6, 72],
  h4: [6, 72],
  h5: [6, 72],
  h6: [6, 72],
  nota: [6, 24],
};

let estilos = { ...ESTILOS_PADRAO };

function normalizarEstilos(bruto) {
  const n = { ...ESTILOS_PADRAO };
  if (!bruto || typeof bruto !== "object") return n;

  if (typeof bruto.fonte === "string") {
    // remove o que quebraria atributo XML ou injeção de CSS
    const limpa = bruto.fonte
      .replace(/["'`;<>{}\\&\r\n]/g, "")
      .trim()
      .slice(0, 60);
    if (limpa) n.fonte = limpa;
  }

  for (const [chave, [min, max]] of Object.entries(ESTILOS_LIMITES)) {
    const bruto_ = bruto[chave];
    if (typeof bruto_ === "boolean") continue; // igual ao backend
    const v = typeof bruto_ === "string" ? Number(bruto_) : bruto_;
    if (Number.isFinite(v)) n[chave] = Math.min(Math.max(v, min), max);
  }
  return n;
}

function aplicarEstilos() {
  // variáveis CSS usadas pelas regras .preview.odt (styles.css)
  const css = {
    "--fonte": `"${estilos.fonte}", serif`,
    "--tamanho": `${estilos.tamanho}pt`,
    "--entrelinha": String(estilos.entrelinha),
    "--margem-par": `${estilos.margemParagrafo}cm`,
    "--margem-pag": `${estilos.margemPagina}cm`,
    "--h1": `${estilos.h1}pt`,
    "--h2": `${estilos.h2}pt`,
    "--h3": `${estilos.h3}pt`,
    "--h4": `${estilos.h4}pt`,
    "--h5": `${estilos.h5}pt`,
    "--h6": `${estilos.h6}pt`,
    "--nota": `${estilos.nota}pt`,
  };
  for (const [chave, valor] of Object.entries(css)) {
    preview.style.setProperty(chave, valor);
  }
}

function salvarEstilos() {
  try {
    localStorage.setItem(ESTILOS_KEY, JSON.stringify(estilos));
  } catch {
    // sem espaço: os estilos valem só nesta sessão
  }
}

function restaurarEstilos() {
  const bruto = localStorage.getItem(ESTILOS_KEY);
  if (bruto) {
    try {
      estilos = normalizarEstilos(JSON.parse(bruto));
      return;
    } catch {
      // JSON corrompido → padrão
    }
  }
  estilos = { ...ESTILOS_PADRAO };
}

const painelEstilos = document.getElementById("painel-estilos");

function preencherInputsEstilos() {
  painelEstilos.querySelectorAll("[data-estilo]").forEach((el) => {
    el.value = estilos[el.dataset.estilo];
  });
}

// digitação: delegação — todo input tem data-estilo="chave"
painelEstilos.addEventListener("input", (ev) => {
  const el = ev.target.closest("[data-estilo]");
  if (!el || el.value === "") return; // campo vazio: mantém o valor atual
  estilos = normalizarEstilos({ ...estilos, [el.dataset.estilo]: el.value });
  aplicarEstilos();
  salvarEstilos();
  if (modo === "odt") posicionarNotas(); // margem/tamanho mudam o pé de página
});

// ao sair do campo (change): reescreve com o valor já clampado
// (ex.: digitou 999 → volta mostrando 72)
painelEstilos.addEventListener("change", preencherInputsEstilos);

document.getElementById("abrir-estilos").addEventListener("click", () => {
  // Interface (interface.js) fecha os demais drawers e aplica a
  // geometria salva (fixado na lateral ou flutuante)
  Interface.abrir(painelEstilos, () => {
    // estilos só fazem sentido vendo o documento → força o modo ODT
    if (modo !== "odt") setModo("odt");
    painelEstilos.querySelector("input")?.focus();
  });
});

document.getElementById("restaurar-estilos").addEventListener("click", () => {
  estilos = { ...ESTILOS_PADRAO };
  preencherInputsEstilos();
  aplicarEstilos();
  salvarEstilos();
  if (modo === "odt") posicionarNotas();
});

// ---------- persistência no navegador (localStorage) ----------

function salvar() {
  const hora = new Date().toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ markdown: editor.value, filename: filenameInput.value })
    );
    setStatus(`salvo ${hora}`);
  } catch {
    // cota do localStorage (~5MB): data URI de imagem grande estoura
    setStatus(`não salvou (${hora}): doc grande demais p/ o navegador`);
  }
}

const salvarDebounced = debounce(salvar, 400);
editor.addEventListener("input", salvarDebounced);
filenameInput.addEventListener("input", salvarDebounced);

function restaurar() {
  const bruto = localStorage.getItem(STORAGE_KEY);
  if (bruto) {
    try {
      const dados = JSON.parse(bruto);
      editor.value = dados.markdown ?? "";
      filenameInput.value = dados.filename ?? "documento";
      return;
    } catch {
      // JSON corrompido — cai no exemplo abaixo
    }
  }
  editor.value = EXEMPLO;
}

// ---------- abrir / baixar .md ----------

abrirInput.addEventListener("change", async () => {
  const arquivo = abrirInput.files[0];
  if (!arquivo) return;
  editor.value = await arquivo.text();
  filenameInput.value = arquivo.name.replace(/\.(md|markdown|txt)$/i, "");
  renderizarPreview();
  salvar();
  abrirInput.value = ""; // permite abrir o mesmo arquivo de novo
});

document.getElementById("baixar-md").addEventListener("click", async () => {
  // embute os bytes: o .md baixado é portátil (data URI), como antes
  const { texto } = await resolverImagensMarkdown(editor.value);
  const blob = new Blob([texto], { type: "text/markdown;charset=utf-8" });
  baixarBlob(blob, `${filenameInput.value || "documento"}.md`);
});

function baixarBlob(blob, nome) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nome;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------- inserir imagem (arquivo local → data URI no markdown) ----------
// O data URI deixa o .md autossuficiente: o backend embute o binário
// direto (sem precisar do arquivo no servidor), e o preview mostra já.
const inserirInput = document.getElementById("inserir-imagem");

// insere trecho no cursor (ou no fim) — usado por arquivo e biblioteca
function inserirNoEditor(trecho) {
  const ini = editor.selectionStart ?? editor.value.length;
  const fim = editor.selectionEnd ?? ini;
  editor.value =
    editor.value.slice(0, ini) + trecho + editor.value.slice(fim);
  editor.selectionStart = editor.selectionEnd = ini + trecho.length;
  editor.focus();
}

inserirInput.addEventListener("change", async () => {
  const arquivo = inserirInput.files[0];
  inserirInput.value = ""; // permite escolher o mesmo arquivo de novo
  if (!arquivo) return;

  const dataUrl = await new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(arquivo);
  });

  const alt = arquivo.name.replace(/\.[^.]+$/, "");
  inserirNoEditor(`![${alt}](${dataUrl})`);
  renderizarPreview();
  salvar();
});

// ---------- biblioteca de imagens (IndexedDB) ----------
// Ver frontend/biblioteca.js — guarda os bytes; aqui só a UI:
// importar (botão/arrastar), listar, inserir ![alt](img:nome) e excluir.
// O markdown referencia pelo NOME; preview e export resolvem nome → bytes.

const painelImagens = document.getElementById("painel-imagens");
const listaImagens = document.getElementById("lista-imagens");
const bibliotecaVazia = document.getElementById("biblioteca-vazia");
const importarInput = document.getElementById("importar-imagem");

// regex global ÚNICA p/ referências `![alt](img:nome)`
const RE_IMG_REF = /!\[([^\]]*)\]\(img:([^)]+)\)/g;

function nomeDaRef(ref) {
  // aceita nome digitado %20codificado; nomeSeguro nunca gera "%"
  try {
    return decodeURIComponent(ref);
  } catch {
    return ref;
  }
}

// preview: <img src="img:nome"> → objectURL (cache da biblioteca).
// Se não achar, deixa o src img: — o CSS marca com tracejado vermelho.
function resolverImagensPreview() {
  preview.querySelectorAll('img[src^="img:"]').forEach((img) => {
    const nome = nomeDaRef(img.getAttribute("src").slice(4));
    Biblioteca.url(nome).then((url) => {
      if (url) img.src = url;
    });
  });
}

// export/baixar: reescreve `img:nome` → data URI (o backend continua
// sem saber da biblioteca — vê o mesmo data URI de sempre).
async function resolverImagensMarkdown(texto) {
  const refs = [...new Set([...texto.matchAll(RE_IMG_REF)].map((m) => m[2]))];
  const mapa = new Map();
  const faltando = [];
  for (const ref of refs) {
    const dataUri = await Biblioteca.dataUri(nomeDaRef(ref));
    if (dataUri) mapa.set(ref, dataUri);
    else faltando.push(nomeDaRef(ref));
  }
  const resolvido = texto.replace(RE_IMG_REF, (full, _alt, ref) =>
    mapa.has(ref) ? full.replace(`(img:${ref})`, `(${mapa.get(ref)})`) : full
  );
  return { texto: resolvido, faltando };
}

async function carregarListaImagens() {
  const registros = await Biblioteca.listar();
  listaImagens.innerHTML = "";
  bibliotecaVazia.hidden = registros.length > 0;

  for (const reg of registros) {
    const li = document.createElement("li");
    li.className = "item-imagem";

    const botao = document.createElement("button");
    botao.type = "button";
    botao.className = "item-botoeira";
    botao.title = "Inserir no texto";
    const img = document.createElement("img");
    img.alt = reg.nome;
    img.src = (await Biblioteca.url(reg.nome)) || "";
    const cap = document.createElement("span");
    cap.className = "item-nome";
    cap.textContent = reg.nome;
    botao.append(img, cap);
    botao.addEventListener("click", () => {
      const alt = reg.nome.replace(/\.[^.]+$/, "");
      inserirNoEditor(`![${alt}](img:${reg.nome})`);
      renderizarPreview();
      salvar();
    });

    const excluir = document.createElement("button");
    excluir.type = "button";
    excluir.className = "item-excluir";
    excluir.textContent = "✕";
    excluir.title = "Excluir da biblioteca";
    excluir.addEventListener("click", async () => {
      await Biblioteca.excluir(reg.nome);
      await carregarListaImagens();
      renderizarPreview(); // referência no .md vira placeholder
      setStatus(`"${reg.nome}" excluída da biblioteca`);
    });

    li.append(botao, excluir);
    listaImagens.appendChild(li);
  }
}

async function importarArquivos(files) {
  const arquivos = [...files].filter((f) => f.type.startsWith("image/"));
  if (!arquivos.length) return;
  for (const f of arquivos) {
    // MESMO nome substitui (nome = identidade do link no .md)
    await Biblioteca.salvar(f.name, f);
  }
  await carregarListaImagens();
  renderizarPreview(); // substituições aparecem já no preview
  setStatus(
    arquivos.length === 1
      ? "1 imagem na biblioteca"
      : `${arquivos.length} imagens na biblioteca`
  );
}

importarInput.addEventListener("change", async () => {
  await importarArquivos(importarInput.files);
  importarInput.value = "";
});

// arrastar e soltar sobre a zona do painel
const zonaImagens = document.getElementById("zona-imagens");
for (const ev of ["dragover", "dragenter"]) {
  zonaImagens.addEventListener(ev, (e) => {
    e.preventDefault();
    zonaImagens.classList.add("arrastando");
  });
}
for (const ev of ["dragleave", "drop"]) {
  zonaImagens.addEventListener(ev, (e) => {
    e.preventDefault();
    zonaImagens.classList.remove("arrastando");
  });
}
zonaImagens.addEventListener("drop", (e) => {
  importarArquivos(e.dataTransfer.files);
});

document.getElementById("abrir-imagens").addEventListener("click", () => {
  // só um drawer por vez (Interface fecha os outros)
  Interface.abrir(painelImagens, async () => {
    await carregarListaImagens();
  });
});

// ---------- exportar .odt ----------

document.getElementById("exportar-odt").addEventListener("click", async () => {
  setStatus("convertendo...");
  try {
    // img:nome → data URI (bytes vêm da biblioteca IndexedDB)
    const { texto, faltando } = await resolverImagensMarkdown(editor.value);
    const resp = await fetch("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        markdown: texto,
        filename: filenameInput.value || "documento",
        // medidas reais das fórmulas do preview (cm) — ver medirFormulas()
        math_dims: medirFormulas(),
        // painel de estilos → styles.xml + margens do .odt
        estilos: { ...estilos },
      }),
    });

    if (!resp.ok) {
      let detalhe = `HTTP ${resp.status}`;
      try {
        const erro = await resp.json();
        detalhe = erro.detail ?? detalhe;
      } catch {
        // corpo não era JSON
      }
      throw new Error(detalhe);
    }

    const blob = await resp.blob();
    const nome = (filenameInput.value || "documento").replace(/\.odt$/i, "");
    baixarBlob(blob, `${nome}.odt`);
    setStatus(
      faltando.length
        ? `ODT baixado — ${faltando.length} imagem(ns) fora da biblioteca`
        : "ODT baixado"
    );
  } catch (e) {
    setStatus("falha na exportação");
    alert(`Não foi possível exportar:\n${e.message}`);
  }
});

// ---------- checagem do servidor ----------

async function checarServidor() {
  try {
    const resp = await fetch("/api/health");
    if (!resp.ok) throw new Error();
    setStatus("servidor ok");
  } catch {
    setStatus("servidor OFFLINE");
  }
}

// ---------- inicialização ----------

setModo(localStorage.getItem(MODO_KEY) === "odt" ? "odt" : "web");
restaurar();
restaurarEstilos();
preencherInputsEstilos();
aplicarEstilos();
renderizarPreview();
checarServidor();

// a fonte da matemática carrega depois → remede as fórmulas e as notas
if (document.fonts && document.fonts.ready) {
  document.fonts.ready.then(() => {
    if (modo === "odt") posicionarNotas();
  });
}
// largura da janela muda o layout → recalcula o pé de página
window.addEventListener(
  "resize",
  debounce(() => {
    if (modo === "odt") posicionarNotas();
  }, 200)
);
