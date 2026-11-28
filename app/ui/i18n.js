// J' PZ MAP STUDIO - idiomas.
// O codigo e escrito em portugues; em ingles, este arquivo traduz o que aparece na tela, inclusive o que
// e criado depois (MutationObserver): textos, title/placeholder, titulo da janela e textos do canvas.
// O idioma vem do sistema (navigator.language: pt* = portugues, o resto = ingles) ou da escolha salva
// na tela Sobre (localStorage "pzms.lang"). Texto sem traducao fica em portugues, nunca quebra.
"use strict";
(function () {
  const pick = () => {
    const q = new URLSearchParams(location.search).get("lang");      // ?lang=en|pt: troca e grava a escolha
    if (q === "pt" || q === "en") { try { localStorage.setItem("pzms.lang", q); } catch (e) { /* sem storage */ } return q; }
    try { const s = localStorage.getItem("pzms.lang"); if (s === "pt" || s === "en") return s; } catch (e) { /* sem storage */ }
    const l = (navigator.languages && navigator.languages[0]) || navigator.language || "pt";
    return /^pt\b/i.test(l) ? "pt" : "en";
  };
  const LANG = pick();
  window.PZMS_LANG = LANG;
  window.setLang = l => { try { localStorage.setItem("pzms.lang", l); } catch (e) { /* sem storage */ } location.reload(); };
  document.documentElement.lang = LANG === "en" ? "en" : "pt-BR";
  if (LANG !== "en") { window.tr = s => s; return; }

  // ------------------------------------------------------------ frases exatas (texto sem espacos nas pontas)
  const EN = {
    // topo e ferramentas
    "Sobre": "About", "Novo": "New", "Novo projeto": "New project", "Abrir": "Open", "Abrir projeto": "Open project",
    "Salvar": "Save", "Salvar (Ctrl/Cmd+S)": "Save (Ctrl/Cmd+S)", "Desfazer": "Undo", "Desfazer (Ctrl/Cmd+Z)": "Undo (Ctrl/Cmd+Z)",
    "Refazer": "Redo", "Refazer (Ctrl/Cmd+Shift+Z)": "Redo (Ctrl/Cmd+Shift+Z)", "Andar": "Floor",
    "Andar abaixo (PageDown)": "Floor down (PageDown)", "Andar acima (PageUp)": "Floor up (PageUp)",
    "Tiles extras": "Extra tiles", "Usar tiles de mods instalados ou criar tiles novos a partir de um PNG":
      "Use tiles from installed mods or create new tiles from a PNG",
    "Nenhum projeto aberto": "No project open",
    "Ver": "View", "Inspecionar (V)": "Inspect (V)", "Pincel": "Brush", "Pincel (B)": "Brush (B)",
    "Area": "Area", "Area retangular (G)": "Rectangle area (G)", "Parede": "Wall", "Paredes (W)": "Walls (W)",
    "Apagar": "Erase", "Borracha (E)": "Eraser (E)", "Copiar": "Copy",
    "Copiar tile: clique num quadrado e o tile do topo vira o item do pincel (I)":
      "Copy tile: click a square and its top tile becomes the brush item (I)",
    "Sala": "Room", "Salas (M)": "Rooms (M)", "Predio": "Building", "Colocar predio (P)": "Place building (P)",
    "Zumbis": "Zombies", "Zumbis (Z)": "Zombies (Z)", "Itens": "Items",
    "Spawn de itens: o que nasce em salas e containers (L)": "Item spawns: what spawns in rooms and containers (L)",
    "Ruas": "Streets", "Ruas e avenidas (U)": "Streets and avenues (U)", "Escada": "Stairs",
    "Escada: subir ou descer, ja abre o piso (S)": "Stairs: up or down, opens the floor for you (S)",
    "Tiles": "Tiles", "Predios": "Buildings", "Lugar real": "Real place", "Exportar": "Export",
    "criar um mapa novo a partir de um lugar real (OpenStreetMap)": "create a new map from a real place (OpenStreetMap)",
    "Acao": "Action", "Tamanho": "Size", "Modo": "Mode", "Densidade": "Density",
    "[ ] muda  -  R gira": "[ ] resize  -  R rotates", "-  R gira": "-  R rotates", "-  arraste para paredes": "-  drag for walls",
    "coloca o item escolhido (X alterna)": "places the chosen item (X toggles)",
    "tira o item escolhido (X alterna)": "removes the chosen item (X toggles)",
    "Buscar tile ou objeto...": "Search tile or object...", "Buscar predio...": "Search building...",
    "Buscar tipo (ex.: kitchen, pharmacy, policestorage)...": "Search type (e.g. kitchen, pharmacy, policestorage)...",
    "- mostrando 300, use a busca": "- showing 300, use search", "nada encontrado": "nothing found",
    "Todos": "All", "Outros": "Others", "Propriedades": "Properties", "Tags": "Tags",
    "carregando sprites...": "loading sprites...", "salvo automaticamente": "saved automatically",
    "projeto criado": "project created", "projeto reaberto de onde parou": "project reopened where you left off",
    "abra um projeto primeiro": "open a project first", "nada mudou": "nothing changed",
    "nada mudou (fora das celulas ou mesmo valor)": "nothing changed (outside the cells or same value)",
    "WebGL2 indisponivel": "WebGL2 unavailable", "servidor indisponivel:": "server unavailable:", "servidor indisponivel": "server unavailable", "porao": "basement",
    "nao deu para copiar: selecione o texto": "couldn't copy: select the text",

    // paleta (categorias do servidor)
    "Terreno": "Ground", "Rua e calcada": "Street and sidewalk", "Pisos": "Floors", "Paredes": "Walls",
    "Portas e janelas": "Doors and windows", "Telhados": "Roofs", "Escadas": "Stairs", "Moveis": "Furniture",
    "Cozinha e banheiro": "Kitchen and bathroom", "Lojas e servicos": "Shops and services", "Luz e fixos": "Lights and fixtures",
    "Vegetacao": "Vegetation", "Cercas e muros": "Fences and walls", "Veiculos e rua": "Vehicles and street",
    "Placas": "Signs", "Decoracao e itens": "Decoration and items", "Tiles de mods e do projeto": "Mod and project tiles",
    "Eletros e cozinha": "Appliances and kitchen", "Fixos": "Fixtures", "Lojas e locais": "Shops and places",

    // catalogo de predios
    "Casas": "Houses", "Casa": "House", "Hoteis e moteis": "Hotels and motels", "Lojas": "Shops",
    "Restaurantes e bares": "Restaurants and bars", "Escritorios e servicos": "Offices and services", "Saude": "Health",
    "Policia, bombeiro e militar": "Police, fire and military", "Escolas": "Schools", "Igrejas": "Churches",
    "Industria e galpoes": "Industry and warehouses", "Fazenda e rural": "Farm and rural", "Lazer": "Leisure",
    "Abandonados": "Abandoned", "+ porao": "+ basement",
    "Montar catalogo": "Build catalog", "montando catalogo...": "building catalog...",
    "O catalogo e montado a partir dos predios do mapa vanilla da sua instalacao do jogo (leva cerca de 1 minuto, so na primeira vez).":
      "The catalog is built from the vanilla map buildings in your game install (takes about 1 minute, only the first time).",
    "Escolha um predio na aba Predios": "Pick a building in the Buildings tab",
    "escolha um predio na aba Predios": "pick a building in the Buildings tab",
    "clique coloca  -  R espelha  -  Shift+R gira 90 graus (aproximado)": "click places  -  R mirrors  -  Shift+R rotates 90 degrees (approximate)",
    "girado (aproximado)": "rotated (approximate)", "R espelha, Shift+R gira": "R mirrors, Shift+R rotates",
    "do catalogo": "from the catalog", "espelhado": "mirrored", "original": "original",

    // novo/abrir/sobre/jogo
    "Novo mapa": "New map", "Nome do mapa": "Map name", "Meu Mapa": "My Map", "Tamanho (celulas)": "Size (cells)",
    "1 celula = 256x256 quadrados": "1 cell = 256x256 squares", "celula inicial (mapa proprio)": "starting cell (own map)",
    "Preencher com grama": "Fill with grass", "Criar": "Create", "Cancelar": "Cancel", "Fechar": "Close", "Voltar": "Back",
    "Crie um mapa novo, abra um existente ou gere a partir de um lugar real.": "Create a new map, open an existing one or generate one from a real place.",
    "Criar de lugar real": "Create from a real place", "pasta do projeto": "project folder", "projeto em": "project in",
    "Onde esta o Project Zomboid?": "Where is Project Zomboid?",
    "Nao achei a instalacao pela Steam. Aponte a pasta do jogo (ProjectZomboid, o .app no Mac ou a pasta media). Os sprites sao lidos dela e convertidos num cache local; nada do jogo e redistribuido.":
      "I couldn't find the install through Steam. Point to the game folder (ProjectZomboid, the .app on Mac or the media folder). Sprites are read from it and converted into a local cache; nothing from the game is redistributed.",
    "pasta do Project Zomboid": "Project Zomboid folder", "Usar esta pasta": "Use this folder", "jogo nao encontrado": "game not found",
    "Preparando sprites (so na primeira vez)": "Preparing sprites (first time only)",
    "Sprites e predios sao lidos da sua propria instalacao e guardados em cache local; nada do jogo e redistribuido.":
      "Sprites and buildings are read from your own install and kept in a local cache; nothing from the game is redistributed.",
    "J' PZ MAP STUDIO — criado por Jemerson Barros": "J' PZ MAP STUDIO — created by Jemerson Barros",
    "Continuar em segundo plano": "Continue in background", "Atencao": "Warning", "Idioma": "Language",

    // inspecionar / area / apagar / paredes / salas
    "Clique: tiles do quadrado  -  Arraste: tiles da area (remover um tipo ou todos de uma vez)":
      "Click: tiles of the square  -  Drag: tiles of the area (remove one type or all at once)",
    "Arraste para preencher um retangulo com o item escolhido": "Drag to fill a rectangle with the chosen item",
    "Arraste: tira o item escolhido do retangulo (sem item: apaga o topo)": "Drag: removes the chosen item from the rectangle (no item: erases the top)",
    "Desligado: piso e misturas do chao ficam; so o que esta em cima e apagado": "Off: floor and ground blends stay; only what's on top is erased",
    "apagar chao": "erase ground", "apagar area": "erase area", "apagar pincel": "erase brush",
    "Clique para copiar o tile do topo (vira o item do pincel)": "Click to copy the top tile (it becomes the brush item)",
    "nenhum tile aqui": "no tile here", "remover tile": "remove tile", "remover na area": "remove in area",
    "remover tudo da area": "remove everything in the area", "remover todos (filtro atual)": "remove all (current filter)",
    "Remover": "Remove", "Excluir": "Delete", "Editar": "Edit", "Tirar": "Remove",
    "Parede (arraste: retangulo/linha)": "Wall (drag: rectangle/line)", "Porta (clique)": "Door (click)", "Janela (clique)": "Window (click)",
    "Porta": "Door", "Janela": "Window", "Material": "Material", "Orientacoes (R gira)": "Orientations (R rotates)",
    "clique na borda (fica amarela): as 4 bordas do quadrado servem  -  a moldura vem da parede escolhida":
      "click the edge (it turns yellow): all 4 edges of the square work  -  the frame comes from the chosen wall",
    "parede N": "wall N", "parede W": "wall W", "porta N": "door N", "porta O": "door W", "janela N": "window N", "janela O": "window W",
    "na parede N": "on wall N", "na parede W": "on wall W", "canto NW": "NW corner", "sobre o piso": "on the floor",
    "objeto solido": "solid object", "lado norte": "north side", "lado oeste": "west side", "(so N)": "(N only)", "(so W)": "(W only)",
    "usa o piso escolhido no catalogo (aba Tiles)": "uses the floor chosen in the catalog (Tiles tab)",
    "escolha um piso no catalogo primeiro": "pick a floor in the catalog first", "escolha um objeto no catalogo primeiro": "pick an object in the catalog first",
    "Arraste para criar sala  -  clique numa sala troca o tipo  -  comece o arraste dentro de uma sala para juntar ao predio  -  Alt+clique apaga o predio":
      "Drag to create a room  -  click a room to change its type  -  start dragging inside a room to join its building  -  Alt+click deletes the building",
    "O tipo define o loot vanilla e quais zumbis aparecem. Selecionado:": "The type sets the vanilla loot and which zombies appear. Selected:",
    "tipo salvo": "type saved", "nao listado": "unlisted", "Fora de sala (externo)": "Outside a room (exterior)",
    "Posicao no mundo": "World position",

    // escadas
    "R gira  -  clique poe a escada e abre o caminho (Ctrl+Z desfaz)": "R rotates  -  click places the stairs and opens the way (Ctrl+Z undoes)",
    "escada para o andar de cima": "stairs to the floor above", "escada para o andar de baixo": "stairs to the floor below",
    "sobe para nordeste (N)": "goes up to the northeast (N)", "sobe para noroeste (W)": "goes up to the northwest (W)",
    "o quadrado e o degrau de baixo; abre o piso do andar de cima": "the square is the bottom step; opens the floor above",
    "o quadrado e o patamar deste andar; a escada vai no andar de baixo": "the square is this floor's landing; the stairs go on the floor below",
    "subir": "up", "descer": "down", "Direcao": "Direction",

    // zumbis
    "pintar": "paint", "somar": "add", "tirar": "remove", "conta-gotas": "eyedropper", "nenhuma": "none", "nenhum": "none",
    "baixa": "low", "media": "medium", "alta": "high", "Nenhum": "None", "Baixa": "Low", "Alta": "High", "Muito alta": "Very high",
    "Insano": "Insane", "Normal": "Normal",
    "borda suave": "soft edge", "borda do pincel vai sumindo (transicao entre areas)": "the brush edge fades out (blend between areas)",
    "calor sempre": "always show heat", "mostrar o calor com outras ferramentas": "show the heat map with other tools",
    "preencher tudo": "fill all", "aplica a densidade atual no mapa inteiro (Ctrl+Z desfaz)": "applies the current density to the whole map (Ctrl+Z undoes)",
    "limpar tudo": "clear all", "zera todo o mapa (Ctrl+Z desfaz)": "clears the whole map (Ctrl+Z undoes)", "zumbis: limpar tudo": "zombies: clear all",
    "estimar": "estimate", "define a densidade": "sets the density",
    "pega a densidade de um chunk (ou Alt+clique em qualquer modo)": "picks the density of a chunk (or Alt+click in any mode)",
    "soma ao que ja tem": "adds to what's there", "subtrai do que ja tem": "subtracts from what's there",
    "aumentar (seta para cima)": "increase (up arrow)", "diminuir (seta para baixo)": "decrease (down arrow)",
    "chunks  [ ]": "chunks  [ ]", "Shift+arrastar = retangulo": "Shift+drag = rectangle", "Alt+clique = conta-gotas": "Alt+click = eyedropper",
    "Shift+arrastar = area": "Shift+drag = area", "mapa sem zumbis pintados": "map with no painted zombies", "Mapa sem zumbis pintados.": "Map with no painted zombies.",
    "Estimativa de zumbis": "Zombie estimate", "Populacao": "Population", "Inicio": "Start", "Pico": "Peak", "Dia do pico": "Peak day", "Dia": "Day",
    "x Normal": "x Normal",
    "indice relativo de zumbis com os multiplicadores do sandbox (populacao, inicio, pico)": "relative zombie index with the sandbox multipliers (population, start, peak)",
    "Indice relativo, nao contagem exata: o jogo faz a conta final no codigo nativo. Use para comparar mapas e configuracoes.":
      "A relative index, not an exact count: the game does the final math in native code. Use it to compare maps and settings.",
    "Multiplicadores lidos do jogo instalado (defines.lua) e das configuracoes de servidor salvas em ~/Zomboid/Server.":
      "Multipliers read from the installed game (defines.lua) and from the server settings saved in ~/Zomboid/Server.",
    "valores medidos nos lotheaders vanilla do B42: cidade 3-4, centro 6-10": "values measured in the B42 vanilla lotheaders: town 3-4, downtown 6-10",
    "Indice relativo, nao contagem exata: o jogo faz a conta final no codigo nativo.": "A relative index, not an exact count: the game does the final math in native code.",
    "Use para comparar mapas e configuracoes.": "Use it to compare maps and settings.",
    "Config": "Config", "Configuracao": "Settings", "Server": "Server",

    // ruas
    "nova rua": "new street", "(nova rua)": "(new street)", "apagar rua": "delete street", "ruas do mapa": "map streets",
    "clique no mapa para comecar a rua  -  clique numa rua para editar": "click the map to start a street  -  click a street to edit it",
    "clique para comecar uma rua": "click to start a street",
    "cada clique poe um ponto  -  duplo clique ou Enter termina  -  Esc cancela": "each click adds a point  -  double-click or Enter finishes  -  Esc cancels",
    "arraste um ponto ou a linha  -  Shift+arrastar move a rua  -  Alt+clique tira um ponto  -  Delete apaga":
      "drag a point or the line  -  Shift+drag moves the street  -  Alt+click removes a point  -  Delete deletes",
    "arraste ponto/linha  -  Shift move a rua  -  Alt+clique tira ponto": "drag point/line  -  Shift moves the street  -  Alt+click removes a point",
    "apaga a rua e devolve o chao de antes (Ctrl+Z desfaz)": "deletes the street and restores the ground (Ctrl+Z undoes)",
    "a rua precisa de 2 pontos": "the street needs 2 points", "a rua precisa de 2 pontos (Delete apaga a rua)": "the street needs 2 points (Delete deletes the street)",
    "a rua precisa de pelo menos 2 pontos": "the street needs at least 2 points", "rua grande demais": "street too big", "rua nao existe": "street does not exist",
    "Pista": "Lanes", "pista (sem faixa)": "road (no lane line)", "Faixas": "Lane lines", "de cada lado": "on each side", "a cada": "every",
    "tracejado a cada": "dashed every", "(0 = continua)": "(0 = solid)", "amarela gasta": "faded yellow", "amarela": "yellow", "branca": "white", "cinza": "gray",
    "curva suave": "smooth curve", "arredonda a linha entre os pontos": "rounds the line between the points",
    "liga/desliga a calcada dos dois lados": "turns the sidewalk on both sides on/off", "meio-fio no asfalto encostado na calcada": "curb on the asphalt next to the sidewalk",
    "poste de luz na calcada, lados alternados": "street lights on the sidewalk, alternating sides",
    "calcada": "sidewalk", "meio-fio": "curb", "postes": "street lights", "rua": "street", "pilar": "pillar",

    // tiles extras
    "Tiles de mods instalados": "Tiles from installed mods",
    "Marque os mods cujos tiles voce quer na paleta. Os que o mapa aberto ja usa entram sozinhos. No jogo, esses mods precisam estar ativos junto com o seu mapa.":
      "Check the mods whose tiles you want in the palette. The ones the open map already uses are added automatically. In game, these mods must be enabled along with your map.",
    "Nenhum mod com tiles (.pack + .tiles) achado na Workshop, em ~/Zomboid/mods nem na Steam.":
      "No mod with tiles (.pack + .tiles) found in the Workshop, in ~/Zomboid/mods or in Steam.",
    "Usar mods marcados": "Use checked mods", "montando tiles dos mods...": "building mod tiles...", "montando tiles extras...": "building extra tiles...",
    "tiles extras prontos: recarregando...": "extra tiles ready: reloading...", "tiles extras:": "extra tiles:",
    "Folhas PNG do projeto (tiles novos)": "Project PNG sheets (new tiles)", "Folha PNG nova:": "New PNG sheet:", "Adicionar folha": "Add sheet",
    "escolha o PNG": "choose the PNG", "Escolher imagem...": "Choose image...", "folha adicionada: montando...": "sheet added: building...",
    "Nome da folha: letras/numeros/_ terminando em _01 (ex.: meumapa_placas_01); cada tile vira meumapa_placas_01_0, _1...":
      "Sheet name: letters/numbers/_ ending in _01 (e.g. mymap_signs_01); each tile becomes mymap_signs_01_0, _1...",
    "cada tile ocupa 128x256 px (tamanho 2x do jogo), em grade de 8 colunas: a folha tem 1024 px de largura e altura multipla de 256":
      "each tile takes 128x256 px (the game's 2x size), in an 8-column grid: the sheet is 1024 px wide and its height is a multiple of 256",
    "(1 a 8 linhas = 8 a 64 tiles). PNG RGBA com fundo transparente. O losango do piso fica no pe da celula (faixa y 192-256, 128x64).":
      "(1 to 8 rows = 8 to 64 tiles). RGBA PNG with a transparent background. The floor diamond sits at the foot of the cell (y band 192-256, 128x64).",
    "Folha 1x (64x128 por tile, 512 px de largura) tambem serve: ela e ampliada 2x.": "A 1x sheet (64x128 per tile, 512 px wide) also works: it is scaled up 2x.",
    "(linha x 8 + coluna).": "(row x 8 + column).",

    // spawn de itens (loot)
    "Spawn de itens": "Item spawns", "Spawn de itens: clique numa sala (ou area da ferramenta Sala)": "Item spawns: click a room (or an area from the Room tool)",
    "Spawn de itens: todas as regras": "Item spawns: all rules", "Regras": "Rules", "Regras de spawn...": "Spawn rules...", "Todas as regras": "All rules",
    "Nova regra": "New rule", "Nova regra de spawn": "New spawn rule", "Editar regra": "Edit rule", "Regra de spawn": "Spawn rule", "Salvar regra": "Save rule",
    "Grupos de spawn": "Spawn groups", "Grupos...": "Groups...", "clique = pintar so esta peca com o Pincel": "click = paint only this piece with the Brush", "vazio": "empty", "lado oeste": "west side", "lado norte": "north side", "canto": "corner", "pilar": "pillar", "piso": "floor", "camada": "layer", "objeto": "object", "Grupos": "Groups", "Grupos personalizados": "Custom groups", "Grupos vanilla": "Vanilla groups", "Itens avulsos": "Single items",
    "Novo grupo": "New group", "Novo grupo de spawn": "New spawn group", "Salvar grupo": "Save group", "Salvar como grupo...": "Save as group...",
    "Pecas do grupo": "Group parts", "nome do grupo": "group name", "o grupo esta vazio": "the group is empty", "a regra esta vazia": "the rule is empty",
    "nenhum grupo ainda": "no groups yet", "nenhum grupo criado (botao Grupos)": "no group created (Groups button)", "nenhum item avulso": "no single items",
    "nenhuma regra para esta sala": "no rules for this room", "nenhuma regra. Clique numa sala do mapa ou crie uma regra aqui.": "no rules. Click a room on the map or create a rule here.",
    "Nenhuma ainda.": "None yet.", "Sala / area": "Room / area", "Container": "Container", "Rolagens": "Rolls", "Lua": "Lua", "Ver Lua": "View Lua",
    "Lua gerado no export": "Lua generated on export", "previa do Lua do export": "preview of the export Lua",
    "Loot vanilla desta sala (o que o jogo ja poe)": "Vanilla loot of this room (what the game already adds)",
    "Substituir o loot vanilla deste container": "Replace the vanilla loot of this container", "SUBSTITUI o vanilla:": "REPLACES vanilla:",
    "Tambem valem aqui (sala all)": "Also apply here (room all)", "Sortear 1 lista por rolagem (como o vanilla)": "Pick 1 list per roll (like vanilla)",
    "(1 lista por rolagem)": "(1 list per roll)",
    "como o jogo: cada rolagem sorteia UMA das listas, pelo peso; desligado = cada lista rola": "like the game: each roll picks ONE of the lists by weight; off = every list rolls",
    "pesos (chance relativa de cada lista):": "weights (relative chance of each list):", "quantas vezes cada grupo vanilla e sorteado": "how many times each vanilla group is rolled",
    "cada grupo e sorteado com as regras do jogo, por cima do loot normal": "each group is rolled with the game's rules, on top of the normal loot",
    "chance %": "chance %", "cond %": "cond %", "chance exata por container; cond vazia = condicao normal do jogo": "exact chance per container; empty cond = the game's normal condition",
    "Grupo = conjunto reutilizavel de grupos vanilla + itens. Use nas regras de qualquer sala.": "Group = a reusable set of vanilla groups + items. Use it in the rules of any room.",
    "transformar em grupo reutilizavel": "turn into a reusable group", "copia editavel do vanilla": "editable copy of vanilla",
    "Editar cria uma regra ja preenchida com as listas do jogo, que substitui o vanilla daquele container. Listas so de certos moveis (ex.: pia) ficam de fora.":
      "Edit creates a rule pre-filled with the game's lists that replaces vanilla in that container. Lists only for certain furniture (e.g. sink) are left out.",
    "itens fixos (sem procList)": "fixed items (no procList)", "lista de ProceduralDistributions.lua": "ProceduralDistributions.lua list",
    "sala/container de Distributions.lua": "Distributions.lua room/container", "so no Distributions.lua": "only in Distributions.lua",
    "Distributions": "Distributions", "Freezer": "Freezer", "neste projeto (com desfazer)": "in this project (with undo)",
    "no meu perfil (todos os mapas)": "in my profile (all maps)", "copiar para este projeto": "copy to this project", "copiar para o perfil": "copy to profile",
    "-> perfil": "-> profile", "-> projeto": "-> project", "perfil": "profile", "projeto": "project",
    "* = do perfil (vale para todos os mapas; ao salvar a regra ele e copiado para o projeto)":
      "* = from the profile (applies to all maps; saving the rule copies it into the project)",
    "todas as salas do mapa (e containers fora de sala)": "all rooms of the map (and containers outside rooms)",
    "fora de sala: use uma regra com sala all ou crie a sala com a ferramenta Sala (M)": "outside a room: use a rule with room all or create the room with the Room tool (M)",
    "sala sem loot vanilla (area propria): so recebe o que voce definir aqui": "room without vanilla loot (own area): only gets what you set here",
    "nome proprio (area): sem loot vanilla; so nasce o que estiver nas regras": "own name (area): no vanilla loot; only what's in the rules spawns",
    "atencao: com sala ou container \"all\" isso apaga o loot vanilla de muitos containers": "warning: with room or container \"all\" this erases the vanilla loot of many containers",
    "nome: letras, numeros, espaco . - _ /, ate 80": "name: letters, numbers, space . - _ /, up to 80",
    "sala/container: so letras, numeros, _ e -": "room/container: letters, numbers, _ and - only",
    "buscar (en/pt/tile)": "search (en/pt/tile)", "clique: spawns": "click: spawns", "-- sem regras: o export nao grava o arquivo": "-- no rules: export doesn't write the file",

    // exportar / workshop
    "Exportar para mod": "Export to mod", "Exportar mod": "Export mod",
    "Monta a pasta do mod pronta para o Build 42 (lotheader, lotpack, chunkdata, map.info, spawnpoints, objects.lua, worldmap e spawns). So celulas alteradas sao copiadas de novo.":
      "Builds the mod folder ready for Build 42 (lotheader, lotpack, chunkdata, map.info, spawnpoints, objects.lua, worldmap and spawns). Only changed cells are copied again.",
    "ID do mod": "Mod ID", "letras, numeros, _ ou - (tambem e o nome da pasta do mapa)": "letters, numbers, _ or - (also the map folder name)",
    "Titulo": "Title", "Descricao": "Description", "Autor": "Author", "Pasta de mods": "Mods folder", "Escolher...": "Choose...",
    "padrao: ~/Zomboid/mods": "default: ~/Zomboid/mods",
    "Preparar para a Steam Workshop (capa, workshop.txt, .vdf e comando do steamcmd)": "Prepare for the Steam Workshop (cover, workshop.txt, .vdf and steamcmd command)",
    "No jogo: Mods -> ative o mod -> Novo jogo -> escolha o mapa na lista de locais de inicio.": "In game: Mods -> enable the mod -> New Game -> pick the map in the spawn location list.",
    "Ja existe um mod com esse ID que nao foi feito por este app. Troque o ID.": "A mod with this ID already exists and wasn't made by this app. Change the ID.",
    "Capa (preview.png)": "Cover (preview.png)", "capa salva no projeto": "cover saved in the project",
    "sem capa: usa a miniatura do mapa. Qualquer imagem; ela e cortada no centro em quadrado 512x512.": "no cover: uses the map thumbnail. Any image; it is center-cropped to a 512x512 square.",
    "Visibilidade": "Visibility", "publico": "public", "privado": "private", "so amigos": "friends only", "unlisted": "unlisted",
    "ID publicado": "Published ID", "vazio = item novo": "empty = new item",
    "depois do 1o envio, o ID do item (fica no .vdf); assim os proximos envios atualizam o mesmo item": "after the 1st upload, the item ID (kept in the .vdf); then later uploads update the same item",
    "Nota da versao": "Version note", "o que mudou nesta versao": "what changed in this version", "Usuario Steam": "Steam user",
    "so o usuario; a senha o steamcmd pede": "username only; steamcmd asks for the password",
    "so para montar o comando; senha e Steam Guard voce digita no steamcmd": "only to build the command; you type the password and Steam Guard in steamcmd",
    "separadas por ; (as do Workshop do PZ: Build 42, Map...)": "separated by ; (the PZ Workshop ones: Build 42, Map...)",
    "Enviar para a Workshop": "Upload to the Workshop", "Com o steamcmd instalado, rode no terminal:": "With steamcmd installed, run in the terminal:",
    "1o envio cria um item novo: depois copie o ID (saida do steamcmd ou URL do item) para o campo ID publicado.":
      "The 1st upload creates a new item: then copy the ID (steamcmd output or item URL) into the Published ID field.",
    "Ou pelo jogo: menu principal -> Workshop -> a pasta aparece na lista.": "Or through the game: main menu -> Workshop -> the folder shows up in the list.",
    "Pasta pronta (Contents/mods, preview.png, workshop.txt, workshop_build.vdf):": "Ready folder (Contents/mods, preview.png, workshop.txt, workshop_build.vdf):",
    "nota (opcional)": "note (optional)",

    // lugar real
    "Criar mapa de um lugar real": "Create a map from a real place",
    "Transforma um trecho do OpenStreetMap num mapa editavel: ruas, calcadas, predios com salas e moveis, agua, parques e arvores. 1 quadrado = 1 metro.":
      "Turns a piece of OpenStreetMap into an editable map: streets, sidewalks, buildings with rooms and furniture, water, parks and trees. 1 square = 1 meter.",
    "Como conseguir o arquivo do OpenStreetMap": "How to get the OpenStreetMap file",
    "Area pequena (um bairro)": "Small area (a neighborhood)", "Area maior (varios bairros)": "Larger area (several neighborhoods)",
    "Cidade ou estado inteiro": "Whole city or state", "Fontes extras (opcional)": "Extra sources (optional)", "Criar o mapa": "Create the map",
    "Abra openstreetmap.org e va ate o lugar.": "Open openstreetmap.org and go to the place.",
    "Clique em Exportar (barra de cima) e depois em \"Selecionar manualmente uma area diferente\".": "Click Export (top bar) and then \"Manually select a different area\".",
    "Ajuste o retangulo e clique em Exportar: baixa um arquivo map.osm.": "Adjust the rectangle and click Export: it downloads a map.osm file.",
    "Limite do site: cerca de 50 mil nos (um bairro). Para mais, use as opcoes abaixo.": "Site limit: about 50k nodes (a neighborhood). For more, use the options below.",
    "Abra extract.bbbike.org.": "Open extract.bbbike.org.", "Desenhe a area no mapa (ou digite os limites).": "Draw the area on the map (or type the bounds).",
    "Em Format escolha \"Protocolbuffer (PBF)\", informe um e-mail e clique em extract.": "In Format choose \"Protocolbuffer (PBF)\", enter an e-mail and click extract.",
    "Em alguns minutos chega um link para baixar o .osm.pbf.": "In a few minutes you get a link to download the .osm.pbf.",
    "Alternativa: Overpass API (overpass-turbo.eu) com a consulta pronta \"(nwr({{bbox}});); out meta;\" e Exportar -> raw OSM data.":
      "Alternative: Overpass API (overpass-turbo.eu) with the ready query \"(nwr({{bbox}});); out meta;\" and Export -> raw OSM data.",
    "Abra download.geofabrik.de.": "Open download.geofabrik.de.", "Clique no continente, depois no pais e na regiao.": "Click the continent, then the country and the region.",
    "Baixe o arquivo .osm.pbf (o de um estado tem de 100 MB a 1 GB).": "Download the .osm.pbf file (a state's is 100 MB to 1 GB).",
    "Arquivos grandes sao lidos so na area escolhida, mas a leitura inicial demora mais.": "Large files are read only in the chosen area, but the first read takes longer.",
    "Contornos de predio com altura melhoram as alturas e os formatos dos predios.": "Building footprints with height improve building heights and shapes.",
    "Exemplo: GeoSampa em Sao Paulo (edificacoes com numero de pavimentos).": "Example: GeoSampa in São Paulo (buildings with number of floors).",
    "Informe o arquivo em \"Fonte extra\" abaixo; sem ela, a altura vem das tags building:levels do OSM.": "Set the file in \"Extra source\" below; without it, height comes from the OSM building:levels tags.",
    "Abra o arquivo no J' PZ MAP STUDIO (botao Escolher arquivo).": "Open the file in J' PZ MAP STUDIO (Choose file button).",
    "Arraste no mapa para escolher a area (cada quadradinho e uma celula de 256 m).": "Drag on the map to choose the area (each small square is a 256 m cell).",
    "Confira a estimativa de celulas e tempo e clique em Criar mapa do lugar.": "Check the cell and time estimate and click Create map of the place.",
    "Arquivo OSM (.osm ou .osm.pbf)": "OSM file (.osm or .osm.pbf)", "/caminho/para/area.osm.pbf": "/path/to/area.osm.pbf", "Escolher arquivo...": "Choose file...",
    "lendo o arquivo...": "reading the file...", "Arquivo valido": "Valid file", "cobre a area escolhida": "covers the chosen area",
    "o arquivo NAO cobre a area escolhida inteira": "the file does NOT cover the whole chosen area",
    "arraste no mapa para escolher a area": "drag on the map to choose the area", "Fonte extra": "Extra source",
    "opcional: contornos com altura (.gpkg/.geojson/.shp)": "optional: footprints with height (.gpkg/.geojson/.shp)",
    "melhora alturas e formatos dos predios (ex.: GeoSampa)": "improves building heights and shapes (e.g. GeoSampa)",
    "Criar mapa do lugar": "Create map of the place", "Nome": "Name",

    // progresso
    "nenhum worker ativo": "no active worker", "aguardando workers...": "waiting for workers...", "falta —": "left —",
    "nenhum processo rodando": "no process running", "e nenhum arquivo gravado ainda": "and no file written yet",
    "salvar": "save", "celulas": "cells", "worldmap": "worldmap", "metadados": "metadata", "workshop": "workshop", "ler osm": "read osm",
    "sprites": "sprites", "atlas": "atlas", "paleta": "palette", "predios": "buildings", "gravar": "write",
    "salvando o projeto": "saving the project", "montando atlas": "building atlas", "montando categorias": "building categories",
    "map.info, spawnpoints, objects": "map.info, spawnpoints, objects", "pasta do Workshop": "Workshop folder", "lendo": "reading",
    "rasterizando fontes": "rasterizing sources", "planejando escadas, celas, letreiros": "planning stairs, cells, signs",
    "salvando raster e spawns": "saving raster and spawns", "lendo definicoes de tiles": "reading tile definitions",
    "procurando tiles de mods": "looking for mod tiles", "folhas do projeto": "project sheets", "gerando miniatura": "generating thumbnail",
    "Montando catalogo de predios vanilla": "Building the vanilla building catalog", "Preparando sprites do jogo": "Preparing game sprites",

    // erros do servidor
    "nenhum projeto aberto": "no project open", "cache de sprites ainda nao foi gerado": "sprite cache not generated yet",
    "cache nao pronto": "cache not ready", "catalogo nao pronto": "catalog not ready", "celula fora do projeto": "cell outside the project",
    "area grande demais": "area too big", "area grande demais (max ~256x256)": "area too big (max ~256x256)", "area invalida": "invalid area",
    "area invalida: confira latitude/longitude (sul < norte, oeste < leste)": "invalid area: check latitude/longitude (south < north, west < east)",
    "escolha a area no mapa antes de gerar": "choose the area on the map before generating", "escolha o arquivo .osm ou .osm.pbf": "choose the .osm or .osm.pbf file",
    "o arquivo precisa ser .osm ou .osm.pbf": "the file must be .osm or .osm.pbf",
    "dialogo nativo indisponivel; cole o caminho do arquivo": "native dialog unavailable; paste the file path",
    "dialogo nativo indisponivel; digite o caminho": "native dialog unavailable; type the path",
    "escolha o PNG da folha": "choose the sheet PNG", "folha nao encontrada": "sheet not found", "ja existe uma folha vanilla com esse nome": "a vanilla sheet with this name already exists",
    "nome da folha: letras/numeros/_ terminando em _01 (ex.: meumapa_placas_01)": "sheet name: letters/numbers/_ ending in _01 (e.g. mymap_signs_01)",
    "nome invalido (letras, numeros, espaco . - _ /, ate 80)": "invalid name (letters, numbers, space . - _ /, up to 80)",
    "faltou loot": "loot missing", "imagem grande demais (max 30 MB)": "image too big (max 30 MB)", "imagem invalida": "invalid image",
    "ID do mod: so letras, numeros, _ e -": "Mod ID: letters, numbers, _ and - only", "json invalido": "invalid json",
    "nao achei a pasta media do Project Zomboid nesse caminho": "couldn't find the Project Zomboid media folder at this path",
    "nao encontrado": "not found", "nao ha andar abaixo": "there is no floor below", "nenhum chunk": "no chunk",
    "nenhuma escada no cache": "no stairs in the cache", "pasta sem project.json": "folder without project.json", "predio desconhecido": "unknown building",
    "prepare os sprites do jogo primeiro": "prepare the game sprites first", "projeto sem celulas": "project without cells",
    "tamanho invalido (1 a 64 celulas por lado)": "invalid size (1 to 64 cells per side)",
    "tipo de sala invalido (use o nome vanilla, ex.: kitchen)": "invalid room type (use the vanilla name, e.g. kitchen)",
    "pasta do jogo nao encontrada: sem listas vanilla nem busca de itens": "game folder not found: no vanilla lists or item search",
    "apagar salas": "delete rooms",

    // palavras soltas
    "adicionar": "add", "apagar": "erase", "editar": "edit", "remover": "remove", "mover": "move", "usar": "use", "salvo": "saved",
    "todos": "all", "tudo": "everything", "topo": "top", "vazio": "empty", "janela": "window", "porta": "door", "parede": "wall",
    "paredes": "walls", "piso": "floor", "pisos": "floors", "objeto": "object", "objetos": "objects", "terreno": "ground", "pincel": "brush",
    "tipo": "type", "personalizado": "custom", "camada": "layer", "canto": "corner", "quadrados": "squares", "qtd": "qty", "jogo": "game",
  };

  // ------------------------------------------------------------ padroes (texto com numeros/nomes)
  const t1 = s => tr(s);
  const PAT = [
    [/^Andar (-?\d+)$/, "Floor $1"],
    [/^servidor: (.+)$/, "server: $1"],
    [/^\.\.\. mais (\d+)$/, "... $1 more"],
    [/^\.\.\. (\d+) no total$/, "... $1 in total"],
    [/^SUBSTITUI o vanilla: (.+)$/, (m, x) => `REPLACES vanilla: ${t1(x)}`],
    [/^(.+) \(1 lista por rolagem\)$/, (m, x) => `${t1(x)} (1 list per roll)`],
    [/^(.+) \((lado oeste|lado norte|canto|pilar|janela O|janela N|porta O|porta N)\)$/, (m, a, b) => `${a} (${t1(b)})`],
    [/^(.*)\[(piso|camada|parede|objeto)\](.*)$/, (m, a, b, c) => `${a}[${t1(b)}]${c}`],
    [/^copiou (.+)$/, "copied $1"],
    [/^faixa (.+)$/, (m, x) => `lane line ${t1(x)}`],
    [/^sala (\S+)$/, "room $1"],
    [/^(\d+)\. (.+)$/, (m, n, x) => `${n}. ${t1(x)}`],
    [/^(.+) \(so ([NW])\)$/, "$1 ($2 only)"],
    [/^Jogo (\S+) \(nao testado\)$/, "Game $1 (not tested)"],
    [/^Jogo (\S+)$/, "Game $1"],
    [/^(.*)  -  (\d+) celula\(s\)$/, "$1  -  $2 cell(s)"],
    [/^(\d+) predio\(s\)$/, "$1 building(s)"],
    [/^(\d+) itens$/, "$1 items"],
    [/^(\d+) predios$/, "$1 buildings"],
    [/^(\d+) predio\(s\) - mostrando 300, use a busca$/, "$1 building(s) - showing 300, use search"],
    [/^Casa (\d+) quartos?$/, (m, n) => `House, ${n} bedroom${n === "1" ? "" : "s"}`],
    [/^(\d+) andar(es)?$/, (m, n) => `${n} floor${n === "1" ? "" : "s"}`],
    [/^(\d+x\d+)  -  aparece (\d+)x no mapa vanilla$/, "$1  -  appears $2x in the vanilla map"],
    [/^aparece em (\d+) predio\(s\) vanilla$/, "appears in $1 vanilla building(s)"],
    [/^(\d+) item\(ns\)$/, "$1 item(s)"],
    [/^(\d+) regra\(s\)$/, "$1 rule(s)"],
    [/^\+(\d+) regra\(s\) all$/, "+$1 rule(s) all"],
    [/^Regras \((\d+)\)$/, "Rules ($1)"],
    [/^Grupos \((\d+)\)$/, "Groups ($1)"],
    [/^\+(\d+) so p\/ certos moveis$/, "+$1 only for certain furniture"],
    [/^(.*) \(pesos do jogo\)$/, "$1 (game weights)"],
    [/^(\d+) de (\d+) chunks com zumbis \(([\d.]+)%\), media ([\d.]+), max (\d+)$/, "$1 of $2 chunks with zombies ($3%), average $4, max $5"],
    [/^densidade (\d+) \((.+)\)$/, (m, n, l) => `density ${n} (${t1(l)})`],
    [/^densidade (\d+)$/, "density $1"],
    [/^zumbis: mapa inteiro (.+)$/, (m, v) => `zombies: whole map ${t1(v)}`],
    [/^zumbis (nenhuma|baixa|media|alta|[+-]?\d+)( \(.+\))?$/, (m, v, r) => `zombies ${t1(v)}${r || ""}`],
    [/^zumbis (.+)$/, (m, v) => `zombies ${t1(v)}`],
    [/^chunk (-?\d+),(-?\d+): (\d+) \(acima do vanilla\)$/, "chunk $1,$2: $3 (above vanilla)"],
    [/^chunk (-?\d+),(-?\d+): (\d+)$/, "chunk $1,$2: $3"],
    [/^, (\d+) acima do vanilla$/, ", $1 above vanilla"],
    [/^dias 0-(\d+)$/, "days 0-$1"],
    [/^Dia (\d+)$/, "Day $1"],
    [/^Indice no dia (\d+): (.+)$/, "Index on day $1: $2"],
    [/^\(pico no dia (\d+): (.+)\)$/, "(peak on day $1: $2)"],
    [/^Comparado ao mesmo mapa no Normal \(inicio\): (.+)x hoje, (.+)x no pico\.$/, "Compared to the same map on Normal (start): $1x today, $2x at the peak."],
    [/^Mapa: soma das densidades (.+) em (\d+) chunks de (\d+) celula\(s\)\.$/, "Map: sum of densities $1 in $2 chunks of $3 cell(s)."],
    [/^Equivale a (.+) celula\(s\) media\(s\) de Muldraugh \(media (.+), cidade densa (.+)\)\.$/, "Equals $1 average Muldraugh cell(s) (average $2, dense town $3)."],
    [/^zumbis: (\d+) de (\d+) chunks com densidade \(([\d.]+)%\)(.*)$/, (m, a, b, c, r) => `zombies: ${a} of ${b} chunks with density (${c}%)${r.replace(/chunks acima de (\d+) \(maximo vanilla\)/, "chunks above $1 (vanilla max)")}`],
    [/^Quadrado (-?\d+), (-?\d+), andar (-?\d+)$/, "Square $1, $2, floor $3"],
    [/^(-?\d+), (-?\d+)  andar (-?\d+)  -  celula (-?\d+),(-?\d+)$/, "$1, $2  floor $3  -  cell $4,$5"],
    [/^Area (\d+) x (\d+) \((.+) a (.+)\), andar (-?\d+)$/, "Area $1 x $2 ($3 to $4), floor $5"],
    [/^Sala (\d+x\d+) no andar (-?\d+)$/, "Room $1 on floor $2"],
    [/^Trocar tipo da sala "(.*)"$/, "Change type of room \"$1\""],
    [/^sala agora e (.+)$/, "room is now $1"],
    [/^sala (.+) -> (.+)$/, "room $1 -> $2"],
    [/^juntar ao predio da sala "(.*)" \(mesmo predio: alarme, chave e loot juntos\)$/, "join the building of room \"$1\" (same building: shared alarm, key and loot)"],
    [/^nenhum; usar "(.*)" assim mesmo$/, "none; use \"$1\" anyway"],
    [/^usar "(.*)" \(nome proprio: so os itens das regras de Spawn de itens\)$/, "use \"$1\" (own name: only items from the Item spawn rules)"],
    [/^(\d+) tipo\(s\) de tile em (\d+) quadrado\(s\)\. Cada remocao e um passo do Ctrl\+Z\.$/, "$1 tile type(s) in $2 square(s). Each removal is one Ctrl+Z step."],
    [/^remover (.+) da area$/, (m, x) => `remove ${t1(x)} from the area`],
    [/^colocado: (.+)$/, "placed: $1"],
    [/^orientacao aproximada: (\d+) telhado\(s\)\/fachada\(s\) ajustados$/, "approximate orientation: $1 roof(s)/facade(s) adjusted"],
    [/^(.+): tirar ponto$/, "$1: remove point"],
    [/^(.+): mover ponto$/, "$1: move point"],
    [/^(.+): novo ponto$/, "$1: new point"],
    [/^(.+): mover$/, "$1: move"],
    [/^(\d+) ponto\(s\) - duplo clique\/Enter termina, Esc cancela$/, "$1 point(s) - double-click/Enter finishes, Esc cancels"],
    [/^\(nova rua\)  -  (\d+) no mapa$/, "(new street)  -  $1 on the map"],
    [/^nova (.+)$/, "new $1"],
    [/^editar (.+)$/, "edit $1"],
    [/^apagar (.+)$/, "delete $1"],
    [/^pistas \((\d+) faixas?\)$/, (m, n) => `lanes (${n} lane line${n === "1" ? "" : "s"})`],
    [/^(.+) \((\d+) tiles\)$/, "$1 ($2 tiles)"],
    [/^(\d+) folha\(s\) PNG do projeto foram junto no mod \(pack \+ \.tiles\)\.$/, "$1 project PNG sheet(s) went into the mod (pack + .tiles)."],
    [/^O mapa usa tiles destes mods \(ja estao no require= do mod\.info; na Workshop marque-os tambem como itens requeridos\): (.+)$/,
      "The map uses tiles from these mods (already in mod.info require=; on the Workshop also mark them as required items): $1"],
    [/^O mapa usa folhas que nenhum mod instalado tem \(aparecem vazias\): (.+)$/, "The map uses sheets that no installed mod has (they show up empty): $1"],
    [/^Ultimo export: (\d+) celula\(s\) em ([\d.]+)s$/, "Last export: $1 cell(s) in $2s"],
    [/^mod exportado: (.+)$/, "mod exported: $1"],
    [/^mapa gerado: (.+)$/, "map generated: $1"],
    [/^Atualiza o item (.+)\.$/, "Updates item $1."],
    [/^Ja existe (.+) que nao foi feito por este app: troque o ID\.$/, "$1 already exists and wasn't made by this app: change the ID."],
    [/^pasta: (.+)$/, "folder: $1"],
    [/^capa 512x512, (\d+) KB \(tambem vira o poster do mod\)$/, "512x512 cover, $1 KB (also becomes the mod poster)"],
    [/^Salvo em (.+)$/, "Saved in $1"],
    [/^Versao (\S*)  -  editor de mapas para Project Zomboid B42 \((.*)\)\.$/, "Version $1  -  map editor for Project Zomboid B42 ($2)."],
    [/^Jogo detectado: (.*)  -  (.*)$/, "Game detected: $1  -  $2"],
    [/^Lendo os tiles do seu jogo (.*) e gerando um atlas reduzido em cache local\.$/, "Reading the tiles of your game $1 and building a reduced atlas in a local cache."],
    [/^Desfazer: (.+)$/, "Undo: $1"], [/^Refazer: (.+)$/, "Redo: $1"],
    [/^estimativa: (\d+) celula\(s\), cerca de (.+) para gerar$/, "estimate: $1 cell(s), about $2 to generate"],
    [/^formato (\S+)  -  (.+) nos  -  (.+) ways$/, "format $1  -  $2 nodes  -  $3 ways"],
    [/^S (\S+)  O (\S+)  N (\S+)  L (\S+)  -  (.+) km  -  ~(\d+) celula\(s\)$/, "S $1  W $2  N $3  E $4  -  $5 km  -  ~$6 cell(s)"],
    [/^Gerando (.+)$/, "Generating $1"], [/^Exportando mod (.+)$/, "Exporting mod $1"],
    [/^decorrido (.+)$/, "elapsed $1"], [/^falta ~(.+)$/, "~$1 left"], [/^ultimo passo ha (.+)$/, "last step $1 ago"],
    [/^ultimo arquivo: (.+) ha (.+)$/, "last file: $1 $2 ago"], [/^ha (.+)$/, "$1 ago"],
    [/^trabalhando \(cpu (\d+)%(.*)\)$/, (m, c, r) => `working (cpu ${c}%${r.replace(/, ultimo arquivo ha (.+)$/, ", last file $1 ago")})`],
    [/^parado\? cpu (\d+)% e nada gravado ha (.+)$/, "stopped? cpu $1% and nothing written for $2"],
    [/^parado\? cpu (\d+)% e nenhum arquivo gravado ainda$/, "stopped? cpu $1% and no file written yet"],
    [/^inicio: (.+)$/, "start: $1"],
    [/^celula (-?\d+),(-?\d+)$/, "cell $1,$2"], [/^celula (\d+)_(\d+) \((\d+)\/(\d+)\)$/, "cell $1_$2 ($3/$4)"],
    [/^bloco (\d+)_(\d+)$/, "block $1_$2"], [/^(\d+) celula\(s\) do cache$/, "$1 cell(s) from cache"],
    [/^(\d+)\/(\d+) predio (\d+)\/(\d+)$/, "$1/$2 building $3/$4"],
    [/^recortando predios de (\d+) celulas$/, "cutting buildings from $1 cells"],
    [/^(\d+)\/(\d+) celulas · (\d+) predios unicos \((\d+) no mapa\)$/, "$1/$2 cells · $3 unique buildings ($4 on the map)"],
    [/^(\d+) predios unicos de (\d+)$/, "$1 unique buildings of $2"],
    [/^gravando prefabs (\d+)\/(\d+)$/, "writing prefabs $1/$2"], [/^reduzindo sprites (\d+)\/(\d+)$/, "reducing sprites $1/$2"],
    [/^gravando pagina (\d+)\/(\d+)$/, "writing page $1/$2"], [/^pagina (\d+)\/(\d+)$/, "page $1/$2"],
    [/^lendo tiles de (.+)$/, "reading tiles of $1"],
    [/^Spawn de itens: sala "(.*)"$/, "Item spawns: room \"$1\""],
    [/^Grupo "(.*)"$/, "Group \"$1\""], [/^grupo "(.*)" salvo no perfil$/, "group \"$1\" saved to profile"],
    [/^grupo "(.*)" removido do perfil$/, "group \"$1\" removed from profile"],
    [/^grupo de spawn (.+)$/, "spawn group $1"], [/^remover grupo de spawn (.+)$/, "remove spawn group $1"], [/^importar grupo (.+)$/, "import group $1"],
    [/^grupos: (.+)$/, "groups: $1"], [/^spawn: remover regra (.+)$/, "spawn: remove rule $1"],
    [/^perfil  -  (.+)$/, "profile  -  $1"],
    [/^projeto  -  (.+)  -  usado em (\d+) regra\(s\)$/, "project  -  $1  -  used in $2 rule(s)"],
    [/^substituido pela regra: (.+)$/, "replaced by the rule: $1"],
    [/^container "(.*)": loot vanilla pelo tipo da sala\.$/, "container \"$1\": vanilla loot by room type."],
    [/^containers desta sala no vanilla: (.+)$/, "this room's containers in vanilla: $1"],
    [/^sala vanilla: containers (.*); o loot normal continua, as regras somam \(a nao ser as marcadas para substituir\)$/,
      "vanilla room: containers $1; the normal loot stays, rules add to it (except the ones marked to replace)"],
    [/^buscar entre (\d+) listas e (\d+) sala\/container$/, "search among $1 lists and $2 room/container"],
    [/^buscar item: nome base, ingles ou portugues \((\d+) no jogo\)$/, "search item: base name, English or Portuguese ($1 in the game)"],
    [/^mostrar mais \((\d+)\)$/, "show more ($1)"],
    [/^Mapa feito no J' PZ MAP STUDIO: (.+)$/, "Map made in J' PZ MAP STUDIO: $1"],
    [/^arquivo nao encontrado: (.+)$/, "file not found: $1"], [/^fonte extra nao encontrada: (.+)$/, "extra source not found: $1"],
    [/^arquivo OSM invalido: (.+)$/, "invalid OSM file: $1"],
    [/^ja existe um projeto em (.+?)(; troque o nome)?$/, (m, p, t) => `a project already exists in ${p}${t ? "; change the name" : ""}`],
    [/^ja existe um mod '(.+)' que nao foi feito por este app em (.+); troque o ID$/, "a mod '$1' not made by this app already exists in $2; change the ID"],
    [/^ja existe (.+) que nao foi feito por este app; troque o ID ou a pasta do Workshop$/, "$1 already exists and wasn't made by this app; change the ID or the Workshop folder"],
    [/^densidade fora de 0\.\.(\d+): (.+)$/, "density outside 0..$1: $2"], [/^nivel invalido: (.+)$/, "invalid level: $1"],
    [/^rota desconhecida (.+)$/, "unknown route $1"], [/^capa: (.+)$/, "cover: $1"], [/^miniatura nao gerada: (.+)$/, "thumbnail not generated: $1"],
    [/^catalogo: (\d+) predios unicos de (\d+) em (.+) s$/, "catalog: $1 unique buildings of $2 in $3 s"],
    [/^pronto: (\d+) sprites em (\d+) paginas \((\d+) s\)$/, "done: $1 sprites in $2 pages ($3 s)"],
  ];

  // ------------------------------------------------------------ tradutor
  const EX = new Map(Object.entries(EN));
  const memo = new Map();
  const SPLITS = ["\n", "  -  ", " · ", " — ", " + "];
  function core(s) {
    if (EX.has(s)) return EX.get(s);
    for (const [re, rep] of PAT) if (re.test(s)) return s.replace(re, rep);
    for (const sep of SPLITS) {
      if (!s.includes(sep)) continue;
      const parts = s.split(sep), out = parts.map(p => { const m = p.match(/^(\s*)([\s\S]*?)(\s*)$/); return m[1] + (m[2] ? (core(m[2]) ?? m[2]) : "") + m[3]; });
      const j = out.join(sep); if (j !== s) return j;
    }
    if (/[.!?] [A-Z]/.test(s)) {          // varias frases num texto so: traduz frase a frase
      const parts = s.split(/(?<=[.!?]) (?=[A-Z])/);
      if (parts.length > 1) { const out = parts.map(p => core(p) ?? p).join(" "); if (out !== s) return out; }
    }
    const c = s.indexOf(": ");          // "prefixo: mensagem do servidor"
    if (c > 0) {
      const a = s.slice(0, c), b = s.slice(c + 2), ta = core(a), tb = core(b);
      if (ta != null || tb != null) return (ta ?? a) + ": " + (tb ?? b);
    }
    return null;
  }
  function tr(s) {
    if (typeof s !== "string" || !s) return s;
    if (memo.has(s)) return memo.get(s);
    const m = s.match(/^(\s*)([\s\S]*?)(\s*)$/);
    let o = s;
    if (m[2] && /[A-Za-z]/.test(m[2])) { const c = core(m[2]); if (c != null) o = m[1] + c + m[3]; }
    if (memo.size > 20000) memo.clear();
    memo.set(s, o);
    return o;
  }
  window.tr = tr;

  // ------------------------------------------------------------ DOM, atributos, titulo e canvas
  const ATTRS = ["title", "placeholder", "aria-label", "alt"];
  const NOTXT = "textarea,script,style,[contenteditable],[data-noi18n]";
  function text(n) {
    const p = n.parentElement;
    if (!p || p.closest(NOTXT)) return;
    const t = tr(n.data); if (t !== n.data) n.data = t;
  }
  function attrs(el) {
    if (el.closest && el.closest("[data-noi18n]")) return;
    for (const a of ATTRS) { const v = el.getAttribute && el.getAttribute(a); if (v) { const t = tr(v); if (t !== v) el.setAttribute(a, t); } }
    if (el.tagName === "INPUT" && /^(button|submit|reset)$/i.test(el.type) && el.value) { const t = tr(el.value); if (t !== el.value) el.value = t; }
  }
  function walk(root) {
    if (root.nodeType === 3) return text(root);
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) attrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === 3 ? text(n) : attrs(n);
  }
  const mo = new MutationObserver(list => {
    for (const r of list) {
      if (r.type === "characterData") text(r.target);
      else if (r.type === "attributes") attrs(r.target);
      else for (const n of r.addedNodes) walk(n);
    }
    if (document.title && tr(document.title) !== document.title) document.title = tr(document.title);
  });
  const start = () => {
    walk(document.body);
    mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  };
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);

  const fill = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (s, ...a) { return fill.call(this, tr(String(s)), ...a); };
})();
