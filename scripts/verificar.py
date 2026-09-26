#!/usr/bin/env python3
"""Verificação visual: .md → .odt → .pdf → .png.

Uso:
    scripts/verificar.py arquivo.md [-o DIR]

Passos:
  1. gera o .odt com o pipeline do projeto (md_parser + odt_writer)
  2. converte para PDF com LibreOffice headless (renderizador de verdade)
  3. renderiza cada página em PNG (pdftoppm) para inspeção visual
  4. extrai o texto do PDF e lista o que chegou lá
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# dependências do projeto vivem no .venv — se chamado fora dele,
# reexecuta lá dentro (ex.: shebang do sistema não tem latex2mathml etc.)
# (comparamos sys.prefix, não exec_path: .venv/bin/python é symlink)
_venv_py = ROOT / ".venv" / "bin" / "python"
if _venv_py.exists() and Path(sys.prefix) != ROOT / ".venv":
    import os
    os.execv(str(_venv_py), [str(_venv_py), str(Path(__file__).resolve()), *sys.argv[1:]])

sys.path.insert(0, str(ROOT / "backend"))


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, **kw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("md", type=Path, help="arquivo markdown de entrada")
    ap.add_argument("-o", "--outdir", type=Path, default=None,
                    help="pasta de saída (padrão: temp)")
    args = ap.parse_args()

    if not args.md.exists():
        print(f"erro: {args.md} não existe", file=sys.stderr)
        return 1

    outdir = args.outdir or Path(tempfile.mkdtemp(prefix="mdtodocs_"))
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. md → odt (o nosso código)
    from md_parser import parse
    from odt_writer import write_odt

    odt = outdir / f"{args.md.stem}.odt"
    write_odt(
        odt,
        parse(args.md.read_text(encoding="utf-8")),
        # imagens com caminho relativo resolvem ao lado do .md
        base_dir=args.md.resolve().parent,
    )
    print(f"ODT  {odt}")

    # 2. odt → pdf (LibreOffice headless)
    # -env:UserInstallation isolado: não interfere com perfil/instância gráfica
    res = run([
        "soffice", "--headless",
        "-env:UserInstallation=file:///tmp/lo_mdToDocs",
        "--convert-to", "pdf", "--outdir", str(outdir), str(odt),
    ])
    pdf = outdir / f"{args.md.stem}.pdf"
    if res.returncode != 0 or not pdf.exists():
        print(f"falha no LibreOffice:\n{res.stdout}\n{res.stderr}", file=sys.stderr)
        return 1
    print(f"PDF  {pdf}")

    # 3. pdf → png por página
    run(["pdftoppm", "-png", "-r", "96", str(pdf), str(outdir / "pagina")])
    pngs = sorted(outdir.glob("pagina-*.png")) or sorted(outdir.glob("pagina*.png"))
    for p in pngs:
        print(f"PNG  {p}")

    # 4. o que de fato chegou ao PDF renderizado
    txt = run(["pdftotext", str(pdf), "-"]).stdout
    print(f"texto extraído: {len(txt.split())} palavras, "
          f"{len(txt.splitlines())} linhas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
