#!/bin/bash
# _probe_fetch.sh — baixa todos os SGS candidatos com curl paralelo (xargs -P16).
# Muito mais rapido que urllib do Python no Windows (que fica travado por proxy).
#
# Args:
#   $1 = arquivo com um SGS code por linha
#   $2 = diretorio de destino (um .json por SGS)

set -eu

CODES_FILE="${1:-_probe_codes.txt}"
OUT_DIR="${2:-_probe_cache}"

mkdir -p "$OUT_DIR"

fetch_one() {
  code="$1"
  out="$OUT_DIR/${code}.json"
  [ -s "$out" ] && return 0
  curl -sS --max-time 20 --retry 2 \
    "https://api.bcb.gov.br/dados/serie/bcdata.sgs.${code}/dados?formato=json" \
    -o "$out.tmp" 2>/dev/null && mv "$out.tmp" "$out" || rm -f "$out.tmp"
}
export -f fetch_one
export OUT_DIR

< "$CODES_FILE" xargs -P 16 -I {} bash -c 'fetch_one "$@"' _ {}

echo "[done] $(ls "$OUT_DIR" | wc -l) arquivos em $OUT_DIR"
