#!/usr/bin/env python3
"""Roda todas as suítes de teste e soma as verificações.

    .venv/bin/python tests/run.py

As suítes de API/UI precisam do servidor no ar (./rodar.sh); a de
pipeline roda 100% offline. MDTODOCS_URL muda o alvo (ex.: o servidor
da LAN).
"""
import re
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
SUITES = ("test_pipeline.py", "test_api.py", "test_ui.py")

totais: dict[str, int] = {}
falhou = False

for nome in SUITES:
    print(f"\n=== {nome} ===", flush=True)
    proc = subprocess.Popen(
        [sys.executable, str(AQUI / nome)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    total = 0
    assert proc.stdout is not None
    for linha in proc.stdout:
        sys.stdout.write(linha)
        m = re.search(r"SUITE_TOTAL:(\d+)", linha)
        if m:
            total = int(m.group(1))
    proc.wait()
    totais[nome] = total
    if proc.returncode != 0:
        falhou = True

print("\n" + "=" * 56)
for nome, n in totais.items():
    print(f"{nome:24} {n} verificações ok")
print(f"{'TOTAL':24} {sum(totais.values())} verificações ok")
sys.exit(1 if falhou else 0)
