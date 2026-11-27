---
title: "Edicoes, desfazer e carga de celulas vao em fila no cliente (servidor e multi-thread)"
author: JemersonBarros
date: 2026-11-27
branch: main
cost: { minutes: 9, tokens: 155320 }
id: l-0d762314
scope: repo
status: active
src: agent
touches:
  - app/pzms/__init__.py
  - app/pzms/project.py
  - app/pzms/server.py
  - app/ui/app.css
  - app/ui/app.js
  - app/ui/export.js
  - app/ui/gen.js
  - app/ui/index.html
  - app/ui/loot.js
---

## Decided
- O servidor e ThreadingHTTPServer: /api/edit, /api/undo e /api/cell rodam em paralelo e chegavam fora de ordem. Um Ctrl+Z podia passar na frente da ultima edicao do pincel, e um blob velho de celula sobrescrevia um novo (o tile sobreposto "sumia").
- O cliente agora serializa: serial()/S.editChain para edit/undo/redo; cellChain (por celula) para loadCell. applyChanged recarrega a celula mesmo se ela ainda estiver carregando (a fila garante a ordem).
- Op "remove":[tiles] no Project.apply tira so esses tiles (pincel/area no modo apagar, Ver em area). erase aceita floor:false para preservar piso+overlay.
- Ver: clique = um quadrado; arrastar = /api/area_tiles (contagem por tile) com remover por tipo ou todos.
- Renomes: Spawn -> Itens/"Spawn de itens"; aba Gerar -> "Lugar real"; Pegar -> Copiar. Versao 0.2.3.
- /api/cell manda Cache-Control: no-store. Antes todo binario saia com max-age=60, e a mesma URL (cx, cy, chunks) voltava do cache do navegador com o chunk velho: o pincel arrastado nao aparecia e um clique depois fazia "piscar".
- _send so poe o Cache-Control padrao se a rota nao mandar o seu.

## Watch out
- Toda chamada nova que mexa no projeto deve passar por serial() no cliente, senao volta a corrida.

In the code: app/ui/app.js serial/flush/undo/loadCell/applyChanged/inspectArea; app/pzms/project.py apply/erase; app/pzms/server.py _area_tiles.
- Nova rota binaria cujo conteudo muda com a edicao precisa de no-store.

In the code: app/pzms/server.py _cell e Handler._send.
