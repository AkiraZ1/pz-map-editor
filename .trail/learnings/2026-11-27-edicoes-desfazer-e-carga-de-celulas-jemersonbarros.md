---
title: "Edicoes, desfazer e carga de celulas vao em fila no cliente (servidor e multi-thread)"
author: JemersonBarros
date: 2026-11-27
branch: main
cost: { minutes: 50, tokens: 809536 }
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
- Escada vanilla (medida em Muldraugh): degrau B no quadrado de partida, M e T seguem para (-1,0) na W e (0,-1) na N; o patamar e o 4o quadrado no andar de cima; em cima dos 3 degraus nao ha piso, so parede lateral/grade.
- Modo descer: o quadrado sob o mouse e o patamar; a escada vai em z-1, comecando 3 quadrados antes.
- Ao por a escada sai mobilia e a parede que fecha a passagem (lado d ou canto NW; porta fica). No canto NW fica so a metade do outro lado (CornerNorthWall / CornerWestWall).
- A previa esconde os quadrados resultantes nos chunks normais via uniform hide[] no shader (max 24) e desenha o resultado como ghost.
- Portao de garagem (prop GarageDoor 1-6): partes W correm S->N e partes N correm W->E; ao espelhar/girar, troca pela parte de mesmo numero relativo e inverte a ordem quando o sentido do eixo inverte.
- Faixas de rodovia: eixo reto ate 15 graus; acima disso usa os tiles angulados vanilla (lanelines.py).
- Each extra tile source (an installed mod with .pack + .tiles, or the project's PNG sheets) becomes its own atlas cache in the same format as the vanilla one. It is merged in place into the vanilla dicts at runtime. Kinds and catalog hold references to those dicts, so the merge has to mutate them instead of replacing them.
- Vanilla wins when a sprite name is duplicated. The palette is cached per set of extras (a hash in the file name), so vanilla's palette.json is never overwritten.
- When the server changes extras, it bumps the atlas `sig`. The UI polls the status and reloads the page when the sig no longer matches. The project stays open on the server, so boot shows it again.
- Mods that provide sheets the opened map already uses (read from the lotheader tile tables) are added automatically to project meta `tilemods`.
- The export does NOT write `require=` into mod.info, because the B42 format is uncertain. It writes `pack=` and `tiledef=` for the project's own sheets and shows in the UI which mods must be enabled.
- The export now writes `require=` into 42/mod.info, listing the mods whose tiles the map uses (meta tilemods). This replaces the earlier decision not to write it.
- Format confirmed in the local B42 mods: one line `require=IdA,IdB`, plain ids separated by commas, no backslash.

In the code: app/pzms/export.py, where it writes mod.info.

## Watch out
- Toda chamada nova que mexa no projeto deve passar por serial() no cliente, senao volta a corrida.

In the code: app/ui/app.js serial/flush/undo/loadCell/applyChanged/inspectArea; app/pzms/project.py apply/erase; app/pzms/server.py _area_tiles.
- Nova rota binaria cujo conteudo muda com a edicao precisa de no-store.

In the code: app/pzms/server.py _cell e Handler._send.
Fechar antes da UI reabrir nao pode perder o resume pendente: shutdown sem projeto regrava app.resume.
Para testar o instalador sem tocar no app real, use PZMS_HOME, PZMS_INSTALL_DIR e PZMS_NO_LAUNCH. O RUNF do install.command respeita PZMS_HOME. O fallback do osascript mira o app pelo NOME e fecharia a instalacao real.

In the code: app/pzms/routes_session.py; app/pzms/main.py (--resume); app/ui/app.js resumeSession/postView; install.command e install.ps1 (bloco "aberto: salvando").
- Uma tile de portao para todas as partes era o bug do espelho: sempre mapear por (folha, i//8, lado, parte).
- Ainda ha um pequeno artefato de faixa nas juncoes reta/curva.

In the code: app/pzms/routes_stairs.py (plan, stair_sets), app/ui/stairs.js, app/ui/gl.js (setHide), app/pzms/catalog.py (garage_part), app/pzms/streets.py, app/pzms/lanelines.py.
- PNG sheet: 2x tiles are 128x256 px, grid of 8 columns (1024 px wide), height a multiple of 256, RGBA. The floor diamond sits at the bottom of the cell (y 192-256). A 1x sheet (64x128) is upscaled 2x.
- Sheet names must match `^[A-Za-z][A-Za-z0-9_]*_\d\d$`. Tile name = sheet_index, where index = row*cols + col.
- Empty cells (no alpha) do not become tiles. A pixel spilling into the next cell creates a 1x1 tile.
- The tiledef fileNumber is 2000 + crc32 % 7000, chosen to avoid colliding with vanilla and common mods.

In the code: app/pzms/modtiles.py, app/pzms/routes_tiles.py, Assets.set_extras in app/pzms/assets.py, app/ui/tilesets.js.

## Tried and ruled out
- Calibrar com save: os saves locais sao MP (cliente) e so tem zpop_virtual.bin (roupas), sem contagem por celula. A conta densidade->zumbis esta em libPZPopMan.dylib.

In the code: app/pzms/zombies.py sim/vanilla_ref/servers/_defines; app/pzms/routes_zombies.py _zombies_sim; app/ui/zombies.js estimate.
pkill/SIGTERM como ultimo recurso: mata sem salvar. Se nao fechar, o instalador falha e pede para fechar a mao.
Chrome headless com --dump-dom nao serve para testar o boot: sem WebGL a UI nao chega a reabrir. Com CDP e swiftshader funciona.
