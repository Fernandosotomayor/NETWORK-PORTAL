#!/usr/bin/env bash
# Script para exportar configuraciones organizadas por hostname real del switch
set -euo pipefail

REPO_DIR="/home/ubuntu/monitoring/oxidized/output/switches_STLI.git"
ROUTER_DB="/home/ubuntu/monitoring/oxidized/config/router.db"
OUT_BASE="/home/ubuntu/monitoring/oxidized/archive"

STAMP="$(date '+%Y-%m-%d_%H%M%S')"
MONTH_DIR="$(date '+%Y-%m')"

mkdir -p "$OUT_BASE"

git --git-dir="$REPO_DIR" ls-tree -r --name-only HEAD | while read -r NODE; do
  [ -z "$NODE" ] && continue

  TMP_FILE="$(mktemp)"
  
  # Extraer configuración temporalmente
  if ! git --git-dir="$REPO_DIR" show "HEAD:$NODE" > "$TMP_FILE" 2>/dev/null; then
    echo "Error al extraer config de Git para: $NODE"
    rm -f "$TMP_FILE"
    continue
  fi

  # Buscar el hostname dentro de la configuración
  REAL_HOSTNAME=""
  
  # 1. Probar 'hostname <name>' (Cisco/Planet estándar)
  REAL_HOSTNAME="$(grep -i -E '^[[:space:]]*hostname[[:space:]]+' "$TMP_FILE" | head -n 1 | awk '{print $2}' | tr -d '\r\n\" ' || true)"
  
  # 2. Probar 'system name <name>' (Configuración de sistema Planet)
  if [ -z "$REAL_HOSTNAME" ]; then
    REAL_HOSTNAME="$(grep -i -E '^[[:space:]]*system[[:space:]]+name[[:space:]]+' "$TMP_FILE" | head -n 1 | sed -E 's/^[[:space:]]*system[[:space:]]+name[[:space:]]+//I' | tr -d '\r\n\" ' || true)"
  fi
  
  # 3. Probar '! System Name: <name>' (Comentario de cabecera Planet)
  if [ -z "$REAL_HOSTNAME" ]; then
    REAL_HOSTNAME="$(grep -i -E '^![[:space:]]*System[[:space:]]*Name:[[:space:]]*' "$TMP_FILE" | head -n 1 | sed -E 's/^![[:space:]]*System[[:space:]]*Name:[[:space:]]*//I' | tr -d '\r\n\" ' || true)"
  fi

  # Si no se encuentra un hostname en el backup, usar el nombre del nodo en Oxidized (router.db)
  if [ -z "$REAL_HOSTNAME" ]; then
    REAL_HOSTNAME="$NODE"
  fi

  FOLDER_NAME="$REAL_HOSTNAME"
  NODE_DIR="$OUT_BASE/$FOLDER_NAME/$MONTH_DIR"
  mkdir -p "$NODE_DIR"

  LAST_FILE="$(find "$OUT_BASE/$FOLDER_NAME" -type f -name "${REAL_HOSTNAME}_*.cfg" 2>/dev/null | sort | tail -n 1 || true)"

  if [ -n "${LAST_FILE:-}" ] && cmp -s "$TMP_FILE" "$LAST_FILE"; then
    echo "Sin cambio: $REAL_HOSTNAME"
    rm -f "$TMP_FILE"
    continue
  fi

  OUT_FILE="$NODE_DIR/${REAL_HOSTNAME}_${STAMP}.cfg"
  mv "$TMP_FILE" "$OUT_FILE"
  echo "Exportado: $OUT_FILE"

  # Mantener solo los últimos 10 respaldos históricos para este equipo
  find "$OUT_BASE/$FOLDER_NAME" -type f -name "${REAL_HOSTNAME}_*.cfg" | sort | head -n -10 | while read -r OLD_FILE; do
    echo "Eliminando respaldo antiguo: $OLD_FILE"
    rm -f "$OLD_FILE"
  done
  find "$OUT_BASE/$FOLDER_NAME" -type d -empty -delete || true
done
