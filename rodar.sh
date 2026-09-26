#!/usr/bin/env bash
# rodar.sh — sobe o mdToDocs (container) e confirma que está respondendo.
#
#   ./rodar.sh                 sobe/reconstrói e mostra o status
#   ./rodar.sh logs            acompanha os logs (Ctrl+C sai, container segue)
#   ./rodar.sh stop            para o container
#   ./rodar.sh restart         reinicia (útil depois de mexer no compose)
#
# Endereço: http://localhost:8321
set -euo pipefail
cd "$(dirname "$0")"   # sempre na raiz do projeto

URL="http://localhost:8321"

# o grupo docker pode ainda não estar ativo no shell atual → tenta sem
# sudo primeiro e cai para "sudo -n" (sem pedir senha) se precisar
if docker info >/dev/null 2>&1; then
  DC=(docker compose)
elif sudo -n docker info >/dev/null 2>&1; then
  DC=(sudo docker compose)
else
  echo "ERRO: docker indisponível (daemon parado ou sem permissão)." >&2
  echo "Tente: sudo systemctl start docker" >&2
  exit 1
fi

subir() {
  echo "→ Build (usa cache se nada mudou) + start..."
  "${DC[@]}" up -d --build

  echo -n "→ Aguardando responder"
  for _ in $(seq 1 30); do
    if curl -sf "$URL/api/health" >/dev/null 2>&1; then
      echo " ok"
      echo
      echo "✓ mdToDocs no ar: $URL"
      echo "  status: $(curl -s "$URL/api/health")"
      echo
      echo "  logs:    $0 logs"
      echo "  parar:   $0 stop"
      echo "  código:  edite backend/ ou frontend/ — backend reinicia sozinho"
      return 0
    fi
    echo -n "."
    sleep 1
  done
  echo
  echo "ERRO: não respondeu em 30s — veja os logs:" >&2
  echo "  ${DC[*]} logs --tail 30" >&2
  exit 1
}

case "${1:-up}" in
  up)     subir ;;
  logs)   exec "${DC[@]}" logs -f --tail 50 ;;
  stop)   "${DC[@]}" down; echo "✓ parado (imagem mantida)" ;;
  restart) "${DC[@]}" restart; echo "✓ reiniciado" ;;
  *)
    echo "uso: $0 [up|logs|stop|restart]" >&2
    exit 2
    ;;
esac
