---
title: "Edicoes, desfazer e carga de celulas vao em fila no cliente (servidor e multi-thread)"
author: JemersonBarros
date: 2026-11-27
branch: main
cost: { minutes: 19, tokens: 291660 }
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
  - app/pzms/zombies.py
---

## Decided
- O servidor e ThreadingHTTPServer: /api/edit, /api/undo e /api/cell rodam em paralelo e chegavam fora de ordem. Um Ctrl+Z podia passar na frente da ultima edicao do pincel, e um blob velho de celula sobrescrevia um novo (o tile sobreposto "sumia").
- O cliente agora serializa: serial()/S.editChain para edit/undo/redo; cellChain (por celula) para loadCell. applyChanged recarrega a celula mesmo se ela ainda estiver carregando (a fila garante a ordem).
- Op "remove":[tiles] no Project.apply tira so esses tiles (pincel/area no modo apagar, Ver em area). erase aceita floor:false para preservar piso+overlay.
- Ver: clique = um quadrado; arrastar = /api/area_tiles (contagem por tile) com remover por tipo ou todos.
- Renomes: Spawn -> Itens/"Spawn de itens"; aba Gerar -> "Lugar real"; Pegar -> Copiar. Versao 0.2.3.
- /api/cell manda Cache-Control: no-store. Antes todo binario saia com max-age=60, e a mesma URL (cx, cy, chunks) voltava do cache do navegador com o chunk velho: o pincel arrastado nao aparecia e um clique depois fazia "piscar".
- _send so poe o Cache-Control padrao se a rota nao mandar o seu.
- Zumbis > "estimar" mostra um indice relativo: soma das densidades x PopulationMultiplier x multiplicador do dia. O multiplicador vai linear do inicio ao pico (PopulationPeakDay). O usuario escolheu o relativo em vez de calibrar no jogo.
- O nivel "Zumbis" do sandbox so troca PopulationMultiplier (defines.lua: 2.5/1.6/1.2/0.65/0.15/0). Inicio/pico/dia sao opcoes separadas, padrao 1.0/1.5/28.
- Referencia: soma media por celula vanilla de Muldraugh com zumbis (867 celulas, media ~334, p90 1181), em cache no zombie_ref.json.
- Le ~/Zomboid/Server/*_SandboxVars.lua para simular a configuracao do servidor.
O app aberto grava running.json (porta, pid, versao) na pasta de dados e apaga ao sair. O instalador le a porta e chama POST /api/shutdown: salva se houver mudanca, guarda cfg["resume"] (caminho + camera x/y/zoom/andar) e encerra. Depois troca o .app e abre com --resume. No boot, a UI reabre o projeto e a camera uma vez.
A UI manda a camera para /api/view a cada 2s, so quando muda (a janela pywebview nao guarda localStorage entre execucoes).
Versao antiga sem /api/shutdown: o Mac pede quit pelo osascript (a janela salva no on_closing) e o Windows usa CloseMainWindow. --resume sem cfg resume cai no ultimo recente.

## Watch out
- Toda chamada nova que mexa no projeto deve passar por serial() no cliente, senao volta a corrida.

In the code: app/ui/app.js serial/flush/undo/loadCell/applyChanged/inspectArea; app/pzms/project.py apply/erase; app/pzms/server.py _area_tiles.
- Nova rota binaria cujo conteudo muda com a edicao precisa de no-store.

In the code: app/pzms/server.py _cell e Handler._send.
Fechar antes da UI reabrir nao pode perder o resume pendente: shutdown sem projeto regrava app.resume.
Para testar o instalador sem tocar no app real, use PZMS_HOME, PZMS_INSTALL_DIR e PZMS_NO_LAUNCH. O RUNF do install.command respeita PZMS_HOME. O fallback do osascript mira o app pelo NOME e fecharia a instalacao real.

In the code: app/pzms/routes_session.py; app/pzms/main.py (--resume); app/ui/app.js resumeSession/postView; install.command e install.ps1 (bloco "aberto: salvando").

## Tried and ruled out
- Calibrar com save: os saves locais sao MP (cliente) e so tem zpop_virtual.bin (roupas), sem contagem por celula. A conta densidade->zumbis esta em libPZPopMan.dylib.

In the code: app/pzms/zombies.py sim/vanilla_ref/servers/_defines; app/pzms/routes_zombies.py _zombies_sim; app/ui/zombies.js estimate.
pkill/SIGTERM como ultimo recurso: mata sem salvar. Se nao fechar, o instalador falha e pede para fechar a mao.
Chrome headless com --dump-dom nao serve para testar o boot: sem WebGL a UI nao chega a reabrir. Com CDP e swiftshader funciona.
