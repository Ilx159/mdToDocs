#!/usr/bin/env python3
"""Suíte de UI: selenium + Firefox headless contra MDTODOCS_URL.

Requer o servidor no ar (./rodar.sh) e geckodriver/Firefox no PATH.
Cobre: carga, editor→preview, modos, drawers, modal, tema, persistência
(localStorage) e export com filename custom.
"""
import json
import time

from _common import BASE, check, resumo

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

print(f"servidor alvo: {BASE}")

opts = Options()
opts.add_argument("-headless")
d = webdriver.Firefox(options=opts)
d.set_page_load_timeout(30)
wait = WebDriverWait(d, 15)

try:
    # 1. carga
    d.get(BASE + "/")
    wait.until(EC.visibility_of_element_located((By.ID, "editor")))
    check(d.find_element(By.ID, "preview") is not None,
          "página carrega (editor + preview)")

    # 2. markdown → preview
    ed = d.find_element(By.ID, "editor")
    ed.clear()
    ed.send_keys("# Olá **mundo**\n\ntexto com `cod` e $x^2$.")
    wait.until(lambda _: "mundo" in d.find_element(By.ID, "preview").text)
    prev = d.find_element(By.ID, "preview")
    check("Olá" in prev.text and prev.find_elements(By.TAG_NAME, "strong"),
          "preview reflete título e negrito")
    check(bool(prev.find_elements(By.TAG_NAME, "math")),
          "fórmula renderizada como <math> no preview")
    check(bool(prev.find_elements(By.TAG_NAME, "code")),
          "código inline no preview")

    # 3. modos Web/ODT
    d.find_element(By.ID, "modo-odt").click()
    wait.until(EC.element_to_be_clickable((By.ID, "modo-web")))
    check("ativo" in d.find_element(By.ID, "modo-odt").get_attribute("class"),
          "modo ODT ativa")
    d.find_element(By.ID, "modo-web").click()
    check("ativo" in d.find_element(By.ID, "modo-web").get_attribute("class"),
          "volta para modo Web")

    # 4. painel de estilos + persistência
    d.find_element(By.ID, "abrir-estilos").click()
    wait.until(EC.visibility_of_element_located((By.ID, "painel-estilos")))
    check(d.find_element(By.ID, "painel-estilos").is_displayed(),
          "painel de estilos abre")
    tam = d.find_element(By.CSS_SELECTOR, '[data-estilo="tamanho"]')
    d.execute_script("arguments[0].scrollIntoView({block:'center'})", tam)
    tam.click()
    tam.send_keys(Keys.CONTROL, "a")
    tam.send_keys("13")
    time.sleep(0.4)
    valor = d.execute_script("return arguments[0].value", tam)
    check(valor == "13", f"input do tamanho aceita o novo valor ({valor!r})")
    est = json.loads(d.execute_script(
        "return localStorage.getItem('mdtodocs:estilos') || '{}'"))
    check(str(est.get("tamanho")) in ("13", "13.0"),
          "edição de estilo persiste no localStorage "
          f"(tamanho={est.get('tamanho')!r})")
    d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)
    check(not d.find_element(By.ID, "painel-estilos").is_displayed(),
          "Escape fecha o drawer de estilos")

    # 5. biblioteca de imagens
    d.find_element(By.ID, "abrir-imagens").click()
    wait.until(EC.visibility_of_element_located((By.ID, "painel-imagens")))
    check(d.find_element(By.ID, "painel-imagens").is_displayed(),
          "gaveta da biblioteca abre")
    check(d.find_element(By.ID, "biblioteca-vazia").is_displayed(),
          "estado vazio da biblioteca (perfil limpo)")
    d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)
    check(not d.find_element(By.ID, "painel-imagens").is_displayed(),
          "Escape fecha a biblioteca")

    # 6. modal de configurações
    d.find_element(By.ID, "abrir-config").click()
    wait.until(EC.visibility_of_element_located((By.ID, "modal-config")))
    check(d.find_element(By.ID, "modal-config").is_displayed(),
          "modal de configurações abre")
    d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)
    check(not d.find_element(By.ID, "modal-config").is_displayed(),
          "Escape fecha o modal")

    # 7. tema alterna e persiste
    tema0 = d.find_element(By.TAG_NAME, "html").get_attribute("data-tema")
    d.find_element(By.ID, "alternar-tema").click()
    time.sleep(0.3)
    tema1 = d.find_element(By.TAG_NAME, "html").get_attribute("data-tema")
    check(tema0 != tema1, f"tema alterna ({tema0} → {tema1})")
    cfg = json.loads(d.execute_script(
        "return localStorage.getItem('mdtodocs:config') || '{}'"))
    check(cfg.get("tema") in ("claro", "escuro"),
          f"tema salvo na config ({cfg.get('tema')!r})")

    # 8. documento + tema restaurados no reload
    time.sleep(0.5)  # debounce do salvamento
    d.refresh()
    wait.until(EC.visibility_of_element_located((By.ID, "editor")))
    check("mundo" in d.find_element(By.ID, "editor").get_attribute("value"),
          "markdown restaurado após reload")
    check(d.find_element(By.TAG_NAME, "html").get_attribute("data-tema")
          == tema1, "tema restaurado após reload (sem flash)")

    # 9. modo persiste no reload
    d.find_element(By.ID, "modo-odt").click()
    time.sleep(0.3)
    d.refresh()
    wait.until(EC.visibility_of_element_located((By.ID, "modo-odt")))
    check("ativo" in d.find_element(By.ID, "modo-odt").get_attribute("class"),
          "modo ODT persiste após reload")
    d.find_element(By.ID, "modo-web").click()

    # 10. toolbar do editor (envolver seleção) + atalho Ctrl+B
    d.execute_script("""
        const ed = document.getElementById('editor');
        ed.value = 'palavra forte aqui';
        ed.selectionStart = 0;
        ed.selectionEnd = 7;
        ed.dispatchEvent(new Event('input', { bubbles: true }));
    """)
    d.find_element(By.CSS_SELECTOR, '[data-fmt="negrito"]').click()
    wait.until(lambda _: d.find_element(By.ID, "editor")
               .get_attribute("value").startswith("**"))
    check(d.find_element(By.ID, "editor").get_attribute("value")
          == "**palavra** forte aqui",
          "toolbar negrito envolve a seleção")

    ed = d.find_element(By.ID, "editor")
    ed.click()
    d.execute_script("""
        const ed = document.getElementById('editor');
        ed.selectionStart = 12;
        ed.selectionEnd = 17;
    """)
    ed.send_keys(Keys.CONTROL, "b")
    wait.until(lambda _: d.find_element(By.ID, "editor")
               .get_attribute("value").count("**") == 4)
    check(d.find_element(By.ID, "editor").get_attribute("value")
          == "**palavra** **forte** aqui",
          "atalho Ctrl+B negrito a palavra sob o cursor")

    # 11. sumário navegável
    d.execute_script("""
        const ed = document.getElementById('editor');
        ed.value = '# Primeira\\n\\ntexto\\n\\n## Segunda\\n\\nmais texto';
        ed.dispatchEvent(new Event('input', { bubbles: true }));
    """)
    wait.until(lambda _: "Primeira" in d.find_element(By.ID, "preview").text)
    d.find_element(By.ID, "abrir-sumario").click()
    wait.until(EC.visibility_of_element_located((By.ID, "sumario")))
    links = d.find_element(By.ID, "sumario").find_elements(By.TAG_NAME, "a")
    check(len(links) == 2 and "Segunda" in links[1].text,
          f"sumário lista os títulos do documento ({len(links)} entradas)")
    d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)
    check(not d.find_element(By.ID, "sumario").is_displayed(),
          "Escape fecha o sumário")

    # 12. slug do H1 vira o nome do arquivo
    d.execute_script("""
        const ed = document.getElementById('editor');
        ed.value = '# Relatório Anual 2026\\n\\ntexto';
        ed.dispatchEvent(new Event('input', { bubbles: true }));
    """)
    wait.until(lambda _: d.find_element(By.ID, "filename")
               .get_attribute("value") == "relatorio-anual-2026")
    nome = d.find_element(By.ID, "filename").get_attribute("value")
    check(nome == "relatorio-anual-2026",
          f"slug do H1 no filename, sem acentos ({nome!r})")

    # 13. destaque de sintaxe (highlight.js)
    fence = "`" * 3
    d.execute_script("""
        const ed = document.getElementById('editor');
        ed.value = arguments[0];
        ed.dispatchEvent(new Event('input', { bubbles: true }));
    """, f"# Código\n\n{fence}python\nimport os\n{fence}")
    wait.until(lambda _: bool(d.find_element(By.ID, "preview")
               .find_elements(By.CSS_SELECTOR, "code.hljs .hljs-keyword")))
    check(bool(d.find_element(By.ID, "preview")
           .find_elements(By.CSS_SELECTOR, "code.hljs .hljs-keyword")),
          "hljs destaca o bloco de código")

    # 14. metadados + página de capa (modal ⚙ → Documento)
    d.find_element(By.ID, "abrir-config").click()
    wait.until(EC.visibility_of_element_located((By.ID, "modal-config")))
    d.find_element(By.ID, "meta-titulo").send_keys("Meu Relatório")
    d.find_element(By.ID, "meta-autor").send_keys("Ana Souza")
    d.execute_script("""
        const data = document.getElementById('meta-data');
        data.value = '2026-10-30';
        data.dispatchEvent(new Event('input', { bubbles: true }));
        document.getElementById('meta-capa').click();
    """)
    time.sleep(0.5)
    prev = d.find_element(By.ID, "preview")
    check("Meu Relatório" in prev.text,
          "capa aparece no preview com o título")
    check("30/10/2026" in prev.text,
          "data ISO formatada DD/MM/AAAA na capa")
    check(bool(prev.find_elements(By.CSS_SELECTOR, ".capa-titulo")),
          "bloco .capa-titulo presente no preview")
    salvo = json.loads(d.execute_script(
        "return localStorage.getItem('mdtodocs:metadados') || 'null'")
        or "null")
    check(bool(salvo) and salvo.get("capa") is True
          and salvo.get("titulo") == "Meu Relatório",
          "metadados persistem no localStorage")
    d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)
    check(not d.find_element(By.ID, "modal-config").is_displayed(),
          "Escape fecha o modal após editar metadados")

    # 15. presets de estilos
    d.find_element(By.ID, "abrir-estilos").click()
    wait.until(EC.visibility_of_element_located((By.ID, "painel-estilos")))
    d.find_element(By.CSS_SELECTOR,
                   '#preset-estilos [data-valor="academico"]').click()
    time.sleep(0.4)
    est = json.loads(d.execute_script(
        "return localStorage.getItem('mdtodocs:estilos') || '{}'"))
    check(str(est.get("entrelinha")) in ("1.5", "1.50"),
          f"preset Acadêmico aplica entrelinha 1.5 "
          f"({est.get('entrelinha')!r})")
    check("ativo" in d.find_element(
        By.CSS_SELECTOR, '#preset-estilos [data-valor="academico"]'
    ).get_attribute("class"), "preset aplicado fica destacado")
    d.find_element(By.ID, "restaurar-estilos").click()
    time.sleep(0.3)
    check("ativo" in d.find_element(
        By.CSS_SELECTOR, '#preset-estilos [data-valor="padrao"]'
    ).get_attribute("class"),
        "restaurar padrão marca o preset Padrão")
    d.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    time.sleep(0.3)

    # 16. nome manual não é sobrescrito pelo slug
    fn = d.find_element(By.ID, "filename")
    fn.clear()
    fn.send_keys("meu-doco")
    d.execute_script("""
        const ed = document.getElementById('editor');
        ed.value = '# Outro Título Bem Diferente\\n\\ntexto';
        ed.dispatchEvent(new Event('input', { bubbles: true }));
    """)
    time.sleep(0.7)
    check(d.find_element(By.ID, "filename").get_attribute("value")
          == "meu-doco",
          "nome manual não é sobrescrito pelo slug do H1")

    # 17. export com filename custom + payload com metadados
    d.execute_script("""
        window.__conv = [];
        const orig = window.fetch;
        window.fetch = async function(...a){
            const r = await orig.call(window, ...a);
            if (String(a[0]).includes('/api/convert')) {
                let corpo = {};
                try { corpo = JSON.parse((a[1] && a[1].body) || '{}'); }
                catch (e) { /* corpo não era JSON */ }
                window.__conv.push({
                    ok: r.ok,
                    disp: r.headers.get('content-disposition') || '',
                    corpo: corpo
                });
            }
            return r;
        };
    """)
    d.find_element(By.ID, "exportar-odt").click()
    wait.until(lambda _: d.execute_script("return window.__conv.length") > 0)
    conv = d.execute_script("return window.__conv[0]")
    check(conv["ok"], "export chama POST /api/convert com 200")
    check("meu-doco.odt" in conv["disp"],
          "Content-Disposition usa o filename digitado "
          f"({conv['disp']!r})")
    meta_env = (conv.get("corpo") or {}).get("meta") or {}
    check(meta_env.get("titulo") == "Meu Relatório",
          "payload leva meta.titulo "
          f"({meta_env.get('titulo')!r})")
    check(meta_env.get("capa") is True,
          "payload leva meta.capa=true")
    wait.until(lambda _: "baixad" in
               d.find_element(By.ID, "status").text.lower())
    check("ODT baixado" in d.find_element(By.ID, "status").text,
          "status mostra 'ODT baixado'")
finally:
    d.quit()

resumo("ui")
