/* mdToDocs — biblioteca de imagens do navegador (IndexedDB).
 *
 * Ideia: importar a imagem UMA vez e referenciá-la no markdown por
 * `![alt](img:nome.png)` — em vez de colar um data URI gigante no .md
 * (que estourava os ~5MB do localStorage).
 *
 * Por que IndexedDB e não localStorage:
 *   - cota grande (centenas de MB por origem)
 *   - guarda Blob nativamente (sem reencodar p/ base64 a cada acesso)
 *   - persiste entre sessões no perfil do navegador
 *
 * O backend NÃO sabe que `img:` existe: o app.js resolve as referências
 * (nome → bytes) antes de renderizar e antes de exportar. Se a imagem
 * não estiver na biblioteca, o link vira placeholder no .odt (o backend
 * já trata src desconhecido assim).
 *
 * contrato (window.Biblioteca):
 *   listar()            → [{nome, tipo, dados, criado}]
 *   salvar(nome, blob)  → nome salvo (nomeSeguro; MESMO nome substitui,
 *                         p/ manter os links do .md válidos)
 *   pegar(nome)         → registro ou null
 *   excluir(nome)       → remove (e revoga a URL do preview)
 *   url(nome)           → objectURL p/ <img> (com cache)
 *   dataUri(nome)       → "data:...;base64,..." p/ exportação (.odt/.md)
 *   nomeSeguro(nome)    → nome sem caminho/chars perigosos
 */

const BIBLIO_NOME = "mdtodocs";
const BIBLIO_STORE = "imagens";

let _db = null;
// nome → objectURL criada (precisa de revoke ao excluir/substituir)
const _urls = new Map();

function idbReq(req) {
  // o padrão do IndexedDB é callback; promisificamos p/ usar async/await
  return new Promise((res, rej) => {
    req.onsuccess = () => res(req.result);
    req.onerror = () => rej(req.error);
  });
}

function abrirBiblioteca() {
  if (_db) return Promise.resolve(_db);
  return new Promise((res, rej) => {
    const req = indexedDB.open(BIBLIO_NOME, 1);
    req.onupgradeneeded = () => {
      // uma entrada por nome de arquivo (keyPath "nome")
      req.result.createObjectStore(BIBLIO_STORE, { keyPath: "nome" });
    };
    req.onsuccess = () => {
      _db = req.result;
      res(_db);
    };
    req.onerror = () => rej(req.error);
  });
}

function escada(db, modo) {
  // transação + objectStore no MESMO tick (a transação fecha sozinha
  // assim que o event loop dá uma volta sem pedidos pendentes)
  return db.transaction(BIBLIO_STORE, modo).objectStore(BIBLIO_STORE);
}

function nomeSeguro(nome) {
  // só o basename (sem pastas), sem caracteres que quebrariam o
  // markdown `](img:...)` ou o sistema de arquivos do navegador
  const base = String(nome).split(/[\\/]/).pop() || "imagem";
  const limpo = base
    .normalize("NFC")
    .replace(/[^A-Za-z0-9À-ÿ._-]/g, "_")
    .replace(/^\.+/, "")
    .slice(0, 100);
  return limpo || "imagem.png";
}

async function listar() {
  const db = await abrirBiblioteca();
  return idbReq(escada(db, "readonly").getAll());
}

async function pegar(nome) {
  const db = await abrirBiblioteca();
  return idbReq(escada(db, "readonly").get(nome));
}

async function salvar(nomeOriginal, blob) {
  const nome = nomeSeguro(nomeOriginal);
  const db = await abrirBiblioteca();
  await idbReq(
    escada(db, "readwrite").put({
      nome,
      tipo: blob.type || "image/png",
      dados: blob,
      criado: Date.now(),
    })
  );
  // substituiu: a URL antiga do preview não serve mais
  if (_urls.has(nome)) {
    URL.revokeObjectURL(_urls.get(nome));
    _urls.delete(nome);
  }
  return nome;
}

async function excluir(nome) {
  const db = await abrirBiblioteca();
  await idbReq(escada(db, "readwrite").delete(nome));
  if (_urls.has(nome)) {
    URL.revokeObjectURL(_urls.get(nome));
    _urls.delete(nome);
  }
}

async function url(nome) {
  if (_urls.has(nome)) return _urls.get(nome);
  const reg = await pegar(nome);
  if (!reg) return null;
  const u = URL.createObjectURL(reg.dados);
  _urls.set(nome, u);
  return u;
}

async function dataUri(nome) {
  const reg = await pegar(nome);
  if (!reg) return null;
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => res(fr.result);
    fr.onerror = () => rej(fr.error);
    fr.readAsDataURL(reg.dados); // usa o tipo salvo junto com o blob
  });
}

window.Biblioteca = {
  listar,
  salvar,
  pegar,
  excluir,
  url,
  dataUri,
  nomeSeguro,
};
