/* interface.js — casca da UI: tema, Configurações, split arrastável
 * e drawers (Estilos/Imagens) que flutuam ou se fixam na lateral.
 *
 * Persistência: localStorage "mdtodocs:config" (um JSON só) +
 * "mdtodocs:drawer:<id>" por painel. O script no <head> do index.html
 * aplica o tema antes do 1º paint; aqui reforçamos e cuidamos das trocas.
 */
(function () {
  "use strict";

  const CHAVE = "mdtodocs:config";

  const PADRAO = {
    tema: "sistema",        // "claro" | "escuro" | "sistema"
    destaque: "#2f6fed",
    animacoes: true,
    fonte: "mono",          // "mono" | "serif" | "sans"
    tamanhoEditor: 14,      // px (12–20)
    proporcao: 0.45,        // fração da largura p/ o editor (0.2–0.8)
  };

  const FONTES = {
    mono: '"SF Mono", "Fira Code", Consolas, monospace',
    serif: '"Liberation Serif", Georgia, serif',
    sans: 'system-ui, -apple-system, "Segoe UI", sans-serif',
  };

  const LARGURA_DRAWER = 320;
  const ZONA_BORDA = 70;   // px da borda que ativam o encaixe

  let config = { ...PADRAO };

  // ---------- config: ler / validar / salvar / aplicar ----------

  function lerConfig() {
    let bruto = null;
    try {
      bruto = JSON.parse(localStorage.getItem(CHAVE) || "{}");
    } catch {
      // JSON corrompido → padrões
    }
    const c = { ...PADRAO };
    if (bruto && typeof bruto === "object") {
      if (["claro", "escuro", "sistema"].includes(bruto.tema)) c.tema = bruto.tema;
      if (typeof bruto.destaque === "string" &&
          /^#[0-9a-f]{6}$/i.test(bruto.destaque)) {
        c.destaque = bruto.destaque;
      }
      if (typeof bruto.animacoes === "boolean") c.animacoes = bruto.animacoes;
      if (Object.hasOwn(FONTES, bruto.fonte)) c.fonte = bruto.fonte;
      const t = Number(bruto.tamanhoEditor);
      if (Number.isFinite(t)) c.tamanhoEditor = Math.min(20, Math.max(12, Math.round(t)));
      const p = Number(bruto.proporcao);
      if (Number.isFinite(p)) c.proporcao = Math.min(0.8, Math.max(0.2, p));
    }
    return c;
  }

  function salvarConfig() {
    try {
      localStorage.setItem(CHAVE, JSON.stringify(config));
    } catch {
      // sem espaço: config vale só nesta sessão
    }
  }

  function temaResolvido() {
    if (config.tema === "claro") return "claro";
    if (config.tema === "escuro") return "escuro";
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "escuro"
      : "claro";
  }

  function aplicarConfig() {
    const r = document.documentElement;
    r.dataset.tema = temaResolvido();
    r.dataset.animacoes = config.animacoes ? "on" : "off";
    r.style.setProperty("--primario", config.destaque);
    r.style.setProperty("--fonte-editor", FONTES[config.fonte] || FONTES.mono);
    r.style.setProperty("--tamanho-editor", `${config.tamanhoEditor}px`);
    sincronizarModal();
  }

  // se o sistema trocar o esquema de cor e o tema for "sistema", reage
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (config.tema === "sistema") aplicarConfig();
    });

  // ---------- modal de Configurações ----------

  const modal = document.getElementById("modal-config");

  function abrirModal() {
    modal.hidden = false;
  }
  function fecharModal() {
    modal.hidden = true;
  }

  document.getElementById("abrir-config").addEventListener("click", abrirModal);
  document.getElementById("fechar-config").addEventListener("click", fecharModal);
  // clique no fundo fecha (clique no .modal não vaza p/ cá por causa do target)
  modal.addEventListener("click", (e) => {
    if (e.target === modal) fecharModal();
  });

  function sincronizarModal() {
    // segmentados (tema/fonte): marca o botão ativo
    for (const [grupo, valor] of [
      ["cfg-tema", config.tema],
      ["cfg-fonte", config.fonte],
    ]) {
      document.querySelectorAll(`#${grupo} button`).forEach((b) => {
        b.classList.toggle("ativo", b.dataset.valor === valor);
      });
    }
    // amostras de cor + cor personalizada
    document.querySelectorAll(".amostra").forEach((a) => {
      a.classList.toggle(
        "ativo",
        a.dataset.cor.toLowerCase() === config.destaque.toLowerCase()
      );
    });
    document.getElementById("cfg-cor-custom").value = config.destaque;
    // animações + tamanho do editor
    document.getElementById("cfg-animacoes").checked = config.animacoes;
    document.getElementById("cfg-tamanho").value = config.tamanhoEditor;
    document.getElementById("cfg-tamanho-valor").textContent =
      `${config.tamanhoEditor}px`;
  }

  // tema
  document.getElementById("cfg-tema").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-valor]");
    if (!b) return;
    config.tema = b.dataset.valor;
    salvarConfig();
    aplicarConfig();
  });

  // cor de destaque (amostras e seletor customizado)
  document.getElementById("cfg-destaque").addEventListener("click", (e) => {
    const a = e.target.closest(".amostra");
    if (!a) return;
    config.destaque = a.dataset.cor;
    salvarConfig();
    aplicarConfig();
  });
  document.getElementById("cfg-cor-custom").addEventListener("input", (e) => {
    if (!/^#[0-9a-f]{6}$/i.test(e.target.value)) return;
    config.destaque = e.target.value;
    salvarConfig();
    aplicarConfig();
  });

  // animações
  document.getElementById("cfg-animacoes").addEventListener("change", (e) => {
    config.animacoes = e.target.checked;
    salvarConfig();
    aplicarConfig();
  });

  // fonte do editor
  document.getElementById("cfg-fonte").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-valor]");
    if (!b || !Object.hasOwn(FONTES, b.dataset.valor)) return;
    config.fonte = b.dataset.valor;
    salvarConfig();
    aplicarConfig();
  });

  // tamanho do editor
  document.getElementById("cfg-tamanho").addEventListener("input", (e) => {
    const v = Number(e.target.value);
    if (!Number.isFinite(v)) return;
    config.tamanhoEditor = Math.min(20, Math.max(12, Math.round(v)));
    salvarConfig();
    aplicarConfig();
  });

  // restaurar divisão padrão
  document.getElementById("cfg-reset-divisoria").addEventListener("click", () => {
    config.proporcao = PADRAO.proporcao;
    aplicarProporcao();
    salvarConfig();
  });

  // ---------- botão de tema no header (alterna claro ↔ escuro) ----------

  document.getElementById("alternar-tema").addEventListener("click", () => {
    config.tema = temaResolvido() === "claro" ? "escuro" : "claro";
    salvarConfig();
    aplicarConfig();
  });

  // ---------- altura da barra (drawers/modo usam de variável) ----------

  function medirBarra() {
    const barra = document.querySelector(".barra");
    if (barra) {
      document.documentElement.style.setProperty(
        "--barra-h",
        `${barra.offsetHeight}px`
      );
    }
  }

  // ---------- split: divisória arrastável (proporção salva) ----------

  function aplicarProporcao() {
    document.getElementById("painel-editor").style.width =
      `${(config.proporcao * 100).toFixed(2)}%`;
  }

  function configurarSplit() {
    const divisor = document.getElementById("divisor");
    const split = document.getElementById("split");
    let arrastando = false;

    aplicarProporcao();

    divisor.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      arrastando = true;
      divisor.classList.add("arrastando");
      document.body.classList.add("sem-selecao");
      divisor.setPointerCapture(e.pointerId);
    });

    divisor.addEventListener("pointermove", (e) => {
      if (!arrastando) return;
      const r = split.getBoundingClientRect();
      const p = (e.clientX - r.left) / r.width;
      config.proporcao = Math.min(0.8, Math.max(0.2, p));
      aplicarProporcao();
    });

    const terminar = (e) => {
      if (!arrastando) return;
      arrastando = false;
      divisor.classList.remove("arrastando");
      document.body.classList.remove("sem-selecao");
      try {
        divisor.releasePointerCapture(e.pointerId);
      } catch {
        // pointer já liberado
      }
      salvarConfig();
    };
    divisor.addEventListener("pointerup", terminar);
    divisor.addEventListener("pointercancel", terminar);
  }

  // ---------- drawers: abrir/fechar, flutuar, fixar ----------

  function chaveDrawer(el) {
    return `mdtodocs:drawer:${el.id}`;
  }

  function lerEstado(el) {
    try {
      const g = JSON.parse(localStorage.getItem(chaveDrawer(el)) || "null");
      if (g && ["fixado", "flutuante"].includes(g.estado)) return g;
    } catch {
      // JSON corrompido → padrão
    }
    return { estado: "fixado", lado: "direita" };
  }

  function salvarEstado(el) {
    const g = { estado: el.dataset.estado || "fixado" };
    if (g.estado === "fixado") {
      g.lado = el.dataset.lado || "direita";
    } else {
      g.x = parseFloat(el.style.left);
      g.y = parseFloat(el.style.top);
    }
    try {
      localStorage.setItem(chaveDrawer(el), JSON.stringify(g));
    } catch {
      // sem espaço: geometria vale só nesta sessão
    }
  }

  function alturaBarra() {
    return parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue("--barra-h")
    ) || 49;
  }

  function aplicarGeometria(el, g) {
    el.dataset.estado = g.estado;
    if (g.estado === "fixado") {
      el.dataset.lado = g.lado || "direita";
      el.style.left = ""; // CSS do estado fixado manda
      el.style.top = "";
    } else {
      delete el.dataset.lado;
      el.style.left = `${Number.isFinite(g.x) ? g.x : innerWidth - LARGURA_DRAWER - 24}px`;
      el.style.top = `${Number.isFinite(g.y) ? g.y : alturaBarra() + 16}px`;
    }
    atualizarBotaoFixar(el);
  }

  // mantém um drawer flutuante dentro da viewport (clamp)
  function ajustarPosicao(el) {
    if (el.dataset.estado !== "flutuante") return;
    const maxX = Math.max(8, innerWidth - LARGURA_DRAWER - 8);
    const maxY = Math.max(alturaBarra() + 8, innerHeight - 80);
    const x = Math.min(maxX, Math.max(8, parseFloat(el.style.left)));
    const y = Math.min(maxY, Math.max(alturaBarra() + 8, parseFloat(el.style.top)));
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
  }

  function atualizarBotaoFixar(el) {
    const btn = el.querySelector(".btn-fixar");
    if (!btn) return;
    const fixado = el.dataset.estado === "fixado";
    btn.classList.toggle("ativo", fixado);
    btn.title = fixado ? "Soltar (flutuar)" : "Fixar na lateral";
  }

  function alternarFixar(el) {
    if (el.dataset.estado === "fixado") {
      const g = lerEstado(el);
      g.estado = "flutuante";
      if (!Number.isFinite(g.x)) {
        g.x = innerWidth - LARGURA_DRAWER - 24;
        g.y = alturaBarra() + 16;
      }
      aplicarGeometria(el, g);
      ajustarPosicao(el);
    } else {
      aplicarGeometria(el, { estado: "fixado", lado: el.dataset.lado || "direita" });
    }
    salvarEstado(el);
  }

  // lado da borda p/ encaixe, ou null
  function ladoDaBorda(x) {
    if (x <= ZONA_BORDA) return "esquerda";
    if (x >= innerWidth - ZONA_BORDA) return "direita";
    return null;
  }

  const zonaEncaixe = document.getElementById("zona-encaixe");

  function mostrarZona(lado) {
    zonaEncaixe.hidden = !lado;
    if (lado) zonaEncaixe.dataset.lado = lado;
  }

  function configurarDrawer(el) {
    const topo = el.querySelector(".drawer-topo");
    let arrastando = false;
    let dx = 0;
    let dy = 0;

    topo.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return; // botões do topo não arrastam
      e.preventDefault();
      // saindo do estado fixado: captura o retângulo atual como flutuante
      if (el.dataset.estado !== "flutuante") {
        const r = el.getBoundingClientRect();
        aplicarGeometria(el, {
          estado: "flutuante",
          x: r.left,
          y: r.top,
        });
      }
      const r = el.getBoundingClientRect();
      dx = e.clientX - r.left;
      dy = e.clientY - r.top;
      arrastando = true;
      el.style.transition = "none"; // segue o mouse sem atraso
      document.body.classList.add("sem-selecao");
      topo.setPointerCapture(e.pointerId);
    });

    topo.addEventListener("pointermove", (e) => {
      if (!arrastando) return;
      el.style.left = `${e.clientX - dx}px`;
      el.style.top = `${e.clientY - dy}px`;
      mostrarZona(ladoDaBorda(e.clientX));
    });

    const terminar = (e) => {
      if (!arrastando) return;
      arrastando = false;
      el.style.transition = ""; // volta a animar (encaixe/soltar)
      document.body.classList.remove("sem-selecao");
      mostrarZona(null);
      try {
        topo.releasePointerCapture(e.pointerId);
      } catch {
        // pointer já liberado
      }
      const lado = ladoDaBorda(e.clientX);
      if (lado) {
        aplicarGeometria(el, { estado: "fixado", lado });
      } else {
        const r = el.getBoundingClientRect();
        aplicarGeometria(el, {
          estado: "flutuante",
          x: Math.round(r.left),
          y: Math.round(r.top),
        });
        ajustarPosicao(el);
      }
      salvarEstado(el);
    };
    topo.addEventListener("pointerup", terminar);
    topo.addEventListener("pointercancel", terminar);

    el.querySelector(".btn-fixar")?.addEventListener("click", () => {
      alternarFixar(el);
    });
    el.querySelector(".btn-fechar")?.addEventListener("click", () => {
      fechar(el);
    });
  }

  function fechar(el) {
    el.hidden = true;
  }

  // fecha os demais drawers, aplica geometria salva e mostra com animação
  function abrir(el, aoAbrir) {
    document.querySelectorAll(".drawer").forEach((o) => {
      if (o !== el) o.hidden = true;
    });
    aplicarGeometria(el, lerEstado(el));
    el.hidden = false;
    ajustarPosicao(el);
    // reinicia a animação de entrada
    el.classList.remove("entrando");
    void el.offsetWidth;
    el.classList.add("entrando");
    if (typeof aoAbrir === "function") aoAbrir();
  }

  // Escape fecha drawers abertos e o modal
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    document.querySelectorAll(".drawer").forEach(fechar);
    fecharModal();
  });

  // ---------- resize da janela ----------

  window.addEventListener("resize", () => {
    medirBarra();
    document
      .querySelectorAll('.drawer[data-estado="flutuante"]:not([hidden])')
      .forEach(ajustarPosicao);
  });

  // ---------- inicialização ----------

  config = lerConfig();
  aplicarConfig();
  medirBarra();
  configurarSplit();
  document.querySelectorAll(".drawer").forEach(configurarDrawer);

  window.Interface = { abrir, fechar };
})();
