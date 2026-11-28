---
title: "Release do app sai como tag anotada e gh release com o zip, nao com --target"
author: JemersonBarros
date: 2026-11-27
branch: main
cost: { minutes: 1, tokens: 3572 }
id: l-f83d311d
scope: repo
status: active
src: agent
touches:
  - LICENSE
  - README.en.md
  - README.md
  - docs/img/banner-en.svg
  - docs/img/banner.svg
  - docs/img/catalogo.jpg
  - docs/img/cidade.jpg
  - docs/img/editor.jpg
  - docs/img/lugar-real.jpg
  - app/pzms/__init__.py
---

## Decided
- O repo e publico (GPL-3.0). Cada versao vira uma release no GitHub com o zip de `tools/make_dist.py`. O `README.md`/`README.en.md` apontam para `releases/latest`, entao o botao e o selo de versao se atualizam sozinhos.
- So a versao atual vai para Releases; as antigas ficam so em `dist/` (fora do git).
- README e LICENSE mudam por PR, nao direto na main.

## Tried and ruled out
- `gh release create --target <sha curto>`: o GitHub responde HTTP 422 (`target_commitish is invalid`).

## Watch out
- Ordem: bump em `app/pzms/__init__.py` -> commit -> `tools/make_dist.py` -> `git tag -a vX.Y.Z <sha>` + push da tag -> `gh release create vX.Y.Z dist/jpzmapstudio-X.Y.Z.zip --verify-tag --latest`.
- Confira o `digest` do asset (`gh release view vX.Y.Z --json assets`) contra o `shasum -a 256` local.
- As capturas do README ficam em `docs/img/`; nada com caminho pessoal (`/Users/...`).
- Depois da release: VirusTotal pelo portal do Atelier (sem chave de API). Digite a URL de download do zip na aba URL e abra `gui/file/<sha256>`. Com 0 deteccoes, selo shields `VirusTotal-0 deteccoes` linkado ao relatorio no `README.md`, no `README.en.md` e nas notas (`gh release edit --notes-file`). O hash muda a cada versao.

In the code: tools/make_dist.py, app/pzms/__init__.py (__version__), README.md, README.en.md, docs/img/.
