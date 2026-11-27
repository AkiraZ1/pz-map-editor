#!/bin/bash
# Instalador do J' PZ MAP STUDIO para macOS (duplo clique).
# Baixa o Python portatil (python-build-standalone, versao fixa, sha256 conferido), instala as wheels
# prontas que vieram no pacote e monta o "J' PZ MAP STUDIO.app" NESTA maquina (sem quarentena,
# sem assinatura, sem Xcode). Destino: ~/Applications (ou PZMS_INSTALL_DIR).
set -euo pipefail

APP_NAME="J' PZ MAP STUDIO"
PBS_TAG="20261124"
PY_VER="3.12.16"
SHA_ARM64="9d6d9d0d85feda3f9cb4eb3e048f0fed21ed280feda087927eaa4fbc7124826f"
SHA_X64="6d7ef4efa1adf65f312e6e865040ce03ef8a4bd7e1b45415193295c9ffc0dbdd"

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${PZMS_INSTALL_DIR:-$HOME/Applications}"
CACHE="${PZMS_DL_CACHE:-$HOME/Library/Caches/jpzmapstudio/dl}"

fail() { echo; echo "ERRO: $*"; echo "Nada foi alterado em $DEST."; echo; read -r -p "Enter para fechar..." _ || true; exit 1; }
trap 'fail "falhou na linha $LINENO"' ERR

echo "== $APP_NAME: instalador macOS"
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" = "1" ]; then
  TARGET=mac-arm64; TRIPLE=aarch64-apple-darwin; SHA="$SHA_ARM64"
else
  TARGET=mac-x64; TRIPLE=x86_64-apple-darwin; SHA="$SHA_X64"
fi
TARBALL="cpython-${PY_VER}+${PBS_TAG}-${TRIPLE}-install_only_stripped.tar.gz"
URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${TARBALL//+/%2B}"

[ -f "$SRC/app/pzms/main.py" ] || fail "pacote incompleto (falta app/pzms/main.py em $SRC)"
[ -f "$SRC/launcher/build.py" ] || fail "pacote incompleto (falta launcher/build.py)"

mkdir -p "$CACHE" "$DEST"
TGZ="$CACHE/$TARBALL"
check() { [ -f "$1" ] && [ "$(shasum -a 256 "$1" | awk '{print $1}')" = "$SHA" ]; }
if [ -f "$SRC/runtime/$TARBALL" ] && check "$SRC/runtime/$TARBALL"; then
  TGZ="$SRC/runtime/$TARBALL"
elif ! check "$TGZ"; then
  echo "-- baixando Python $PY_VER portatil ($TARGET)..."
  if [ -t 1 ]; then PB=--progress-bar; else PB=-sS; fi
  curl -fL --retry 3 $PB -o "$TGZ.part" "$URL" || fail "download do Python falhou ($URL)"
  mv -f "$TGZ.part" "$TGZ"
  check "$TGZ" || { rm -f "$TGZ"; fail "sha256 do Python nao confere (download corrompido ou adulterado)"; }
fi
echo "-- Python conferido (sha256 ok)"

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/jpzms.XXXXXX")"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT
BUNDLE="$STAGE/$APP_NAME.app"
mkdir -p "$BUNDLE/Contents/Resources"
tar -xzf "$TGZ" -C "$BUNDLE/Contents/Resources"
PY="$BUNDLE/Contents/Resources/python/bin/python3"
"$PY" -c 'import sys; assert sys.version_info[:2] == (3, 12)' || fail "Python extraido nao roda"

echo "-- instalando dependencias prontas e montando o .app..."
"$PY" -I "$SRC/launcher/build.py" --target "$TARGET" --src "$SRC" --bundle "$BUNDLE"

# nada do que foi criado aqui deve levar quarentena (o zip baixado leva; os arquivos novos nao)
xattr -dr com.apple.quarantine "$BUNDLE" 2>/dev/null || true

FINAL="$DEST/$APP_NAME.app"
RUNF="${PZMS_HOME:-$HOME/Library/Application Support/jpzmapstudio}/running.json"
RESUME=""
running() { pgrep -f "$FINAL/Contents/MacOS/" >/dev/null 2>&1; }
wait_exit() { for _ in $(seq 1 "$1"); do running || return 0; sleep 0.5; done; ! running; }
if running; then
  echo "-- $APP_NAME aberto: salvando o projeto e fechando para atualizar..."
  RESUME=1
  PORT="$(sed -n 's/.*"port": *\([0-9][0-9]*\).*/\1/p' "$RUNF" 2>/dev/null || true)"
  if [ -n "$PORT" ]; then
    curl -fsS -m 20 -X POST -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$PORT/api/shutdown" >/dev/null 2>&1 || true
  fi
  # versao antiga (sem /api/shutdown): pede para o app sair; a janela salva o projeto ao fechar
  wait_exit 20 || osascript -e 'tell application "J'"'"' PZ MAP STUDIO" to quit' >/dev/null 2>&1 || true
  wait_exit 40 || fail "nao consegui fechar o $APP_NAME; feche a janela e rode o instalador de novo"
fi
rm -rf "$FINAL"
mv "$BUNDLE" "$FINAL"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$FINAL" >/dev/null 2>&1 || true
trap - ERR

echo
echo "== Pronto: $FINAL"
echo "   Seus dados ficam em ~/Library/Application Support/jpzmapstudio (nao sao apagados ao reinstalar)."
if [ -z "${PZMS_NO_LAUNCH:-}" ]; then
  if [ -n "$RESUME" ]; then open "$FINAL" --args --resume; else open "$FINAL"; fi
fi
