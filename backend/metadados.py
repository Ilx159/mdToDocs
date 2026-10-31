"""Metadados do documento → meta.xml e página de capa.

O cliente (modal de Configurações) manda um dict opcional:

    {"titulo": "Meu artigo", "autor": "Ana", "data": "2026-10-30",
     "capa": true}

normalizar() valida/clampa cada campo (o cliente pode mandar qualquer
coisa; isto é, strings perigosas perdem caracteres de controle e o
tamanho é limitado). `capa` só é True quando é booleano True de
verdade — string "sim" não liga a capa.

Duas saídas:
  - meta.xml  → <dc:title>/<dc:creator>/<meta:creation-date>
  - content.xml → parágrafos CapaTitulo/CapaAutor/CapaData + PageBreak
    (só quando `capa` está ligado e há pelo menos um campo)
"""
import re

# teto de cada campo (caracteres) — evita meta.xml gigante
_LIMITES = {"titulo": 200, "autor": 120, "data": 60}

# caracteres de controle que quebram XML/texto (\\x7f = DEL)
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# <meta:creation-date> exige xsd:AAAA-MM-DD; data diferente não vai pro
# meta.xml (a capa mostra o texto livre como está)
_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalizar(bruto: object) -> dict:
    """Devolve {titulo, autor, data, capa} sempre dentro dos limites."""
    meta = {"titulo": "", "autor": "", "data": "", "capa": False}
    if not isinstance(bruto, dict):
        return meta

    for campo, teto in _LIMITES.items():
        valor = bruto.get(campo)
        if isinstance(valor, str):
            meta[campo] = _CONTROLE.sub("", valor).strip()[:teto]
    meta["capa"] = bruto.get("capa") is True
    return meta


def data_iso(iso: str) -> bool:
    """True se a data está no formato AAAA-MM-DD (xsd:date)."""
    return bool(_DATA_ISO.match(iso))


def data_brasil(iso: str) -> str:
    """AAAA-MM-DD → DD/MM/AAAA (formato da capa); se não parsear, o
    texto livre é exibido como veio."""
    if not data_iso(iso):
        return iso
    return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"
