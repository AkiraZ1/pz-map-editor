# GOAL — J' PZ MAP STUDIO (native map editor for Project Zomboid B42)

## Goal (done when)
A desktop app for macOS and Windows that creates and edits Project Zomboid maps directly, working with **B42 42.21 and 42.22**. It must:
1. Open or create a map and show it in an isometric view, with low-resolution vanilla sprites. Painting ground, sidewalk, road, walls, floors and objects works per cell, with undo/redo.
2. Offer a **catalog of ready vanilla buildings by type**. Example: pick "Community center" to see the list of every vanilla community center, with thumbnails, then place it on the map with a click and rotation. Same for pharmacies, gas stations, houses, police, schools and the rest.
3. Have a **"Generate from a real place"** feature: an OSM area becomes a map, using the São Paulo generator.
4. Export directly to a ready mod folder (lotheader/lotpack/chunkdata, map.info, spawnpoints, objects.lua, worldmap.xml), with no WorldEd or TileZed step. The exported map must load in game on 42.21 and 42.22.
5. Re-render incrementally: an edit re-renders only the cells or tiles that changed.

## Mandatory distribution (avoid SmartScreen and Gatekeeper)
- The executable is **built locally on each user's machine**, so it carries no internet quarantine flag and needs no signing.
- The installer delivers everything **semi-ready**: sources plus a toolchain that is already embedded and pre-compiled (for example a portable Python runtime and prebuilt dependencies). The user installs no SDK, compiler, Python, Node or Rust. A single script/double click (`install.command` on Mac, `install.cmd`/`install.ps1` on Windows) compiles or links **only the final executable** and creates the shortcut.
- Only the executable is built locally. Everything else is already done.
- Vanilla sprites, buildings and tiles are **read from the user's own PZ installation** (auto-detect via Steam on Mac and Windows, with a manual option) and converted to low resolution on first run, into a local cache. Do not redistribute game assets.
- Supported versions: 42.21 and 42.22. When a new version comes out, the owner updates the app, so no automatic compatibility is needed.

## Base to reuse (read, don't edit): ~/Zomboid/Workshop/saopaulo
- `scripts/gen.py`
  - `finish_cell` writes the B42 lotheader/lotpack (LOTP v1, 256 cells, 1024 chunks).
  - `write_meta` handles map.info, spawn, zones.py, worldmap.py and annotations.py.
  - The furniture and interiors are FURNISH/ISLAND/islands, with vanilla loot by room name.
  - The incremental mode is block_key/cached_block/put.
- `scripts/lego.py`
  - `read_cell` reads the lotpack.
  - `load_packs` and `sprite` read the .pack files (Tiles2x).
  - `scripts/lego.py` (scene render).
- `scripts/gameview.py`
  - isometric renderer with real sprites;
  - WebP tiles;
  - incremental manifest per cell (cell_sigs/cell_tiles/pyramid).
- `scripts/pz_tiles.py` packs custom tiles. `fonte/vanilla/tiles.json` holds the tile definitions.
- Reference sprite packs: `~/pz-ws-sandbox/ref/texturepacks`.
- Lessons already learned (read `.trail/learnings` in saopaulo):
  - `floors_exterior_street_01_18` is all black;
  - displaycase gets no pharmacy loot;
  - signs use WallOverlay with attachedW/N.

## Vanilla building catalog
- Each vanilla building's RoomDefs (names plus rects) come from the vanilla lotheaders in the user's install.
- Cut out each building (all floors, squares, objects) and classify it by room names (communitycenter, pharmacy, gasstore, police, school…).
- Generate a thumbnail with the iso renderer.
- Save to the local cache as a prefab (cut from the user's own game, never shipped).

## Suggested stack (agent's call, justify it)
- Core in Python, reusing the code above.
- UI: Tauri or a native webview, with a WebGL iso canvas.
- Local build of only the launcher/executable, with everything else pre-compiled in the package.

## Rules
- Do not edit ~/Zomboid/Workshop/saopaulo (reference only).
- Search code only with graft/trail. Memory only through ai-memory.
- Reply in PT-BR, briefly.
- Report progress at each milestone (MVP 1–5 above) and finish with: how to install, how to use, and in-game test results on 42.21/42.22.


## App name (owner's decision)
The app is called **J' PZ MAP STUDIO** (exactly that, with the apostrophe). Use it in the window title, the installer, the shortcut, the About screen and the bundle (`J' PZ MAP STUDIO.app` on Mac, `J' PZ MAP STUDIO.exe` on Windows). If a filesystem or identifier does not accept the apostrophe, use `jpzmapstudio` only in the internal id or package name.

## Progress panel (mandatory, based on the São Paulo panel)
Every long operation (generate from a real place, render, packing, export) shows a progress panel inside the app, modeled on the São Paulo one. The reference is the ai-memory procedure `procedures/painel-progresso-tempo-real`. The code to read and port:
- `~/Zomboid/Workshop/saopaulo/scripts/progresso.py`
- `~/Zomboid/Workshop/saopaulo/scripts/painel_progresso.py`

The panel shows:
- **MACRO:** the sequence of steps (✔ done, ▶ current, · pending), a bar with a percentage, time elapsed and an estimate of time left. The bar counts the fraction of the unit of work in progress, so it never sits still for minutes.
- **Liveness:** green "working" (CPU in use or a file recently written), yellow "stopped?" and grey "idle". Never show a bare "no update for N min", which looks like a hang.
- **MICRO:** every worker with what it is doing right now (block, step, cell k/n), its CPU and memory, plus the last file written.
- **LOG:** the last lines of the operation's log.
- Workers report through a small API (`mark(step, done, total, msg)`, `finish`, and `micro(step, key, msg, fraction)`, one entry per worker). Progress reporting must never invalidate incremental caches.

## Editing tools that the São Paulo work needed (owner's request)
These are first-class tools in J' PZ MAP STUDIO. Each one is also available as data in the export.
1. **Zombies per group of tiles.** Pick a set of tiles, cells or areas (a brush or rectangle) and set the zombie density: none, low, medium, high or a number. Export to the zombie spawn map (`ZombieSpawnMap` / zpop in the chunkdata, depending on the version) and keep a heat overlay visible in the view.
2. **Container and area spawns.** For each container (fridge, shelf, counter, wardrobe and so on), each room or each painted area, define what spawns. Three ways can be mixed in the same container or area:
   - **vanilla item groups**: the distribution and procedural lists read from the game's `Distributions.lua` / `ProceduralDistributions.lua`, with search;
   - **single items**: any vanilla item, with chance, count and condition;
   - **custom groups**: groups the user builds by mixing vanilla groups and single items, saved and reusable across maps.

   Export to the mod's distributions Lua (room definition plus container → list), merged without overwriting vanilla.
3. **Contextual tools.** When a tool is opened (for example Wall), the side panel switches to that tool's groups: the wall group appears on the right with a searchable list of its sprites (by sheet, family and orientation). The same goes for floor, roof, door, window, furniture, vegetation, signs and the rest.
   - Each panel lists the tool's items, its own spawn groups when they apply, and its properties.
   - The user can create custom groups for any tool.
4. **Room definitions.** Paint or select a room and give it a vanilla room type (kitchen, pharmacy, gasstore, bathroom and so on), which drives the vanilla loot and the spawns. Export goes into the lotheader.
5. Everything above has undo/redo and is saved in the project.

## Loading window with the creator's name
Every long operation (generating, rendering, exporting, packing) opens a loading window or overlay with the progress panel. While the app is busy, the bottom bar of the window always shows the creator credit: **"J' PZ MAP STUDIO — criado por Jemerson Barros"**. The same credit appears in the About screen.

## Vanilla buildings and "Generate from a real place": what each needs
- **Vanilla buildings (catalog by type):** read from the user's Project Zomboid install, either the vanilla maps (`media/maps/Muldraugh, KY` and the rest) or the game's .tbx and .lot files. Find the install automatically through Steam's libraryfolders.vdf on Mac and Windows, and ask for the folder if it is not found. Nothing from the game is redistributed.
- **Generate from a real place requires an OpenStreetMap file supplied by the user** (`.osm.pbf` or `.osm`). The app does not download the whole planet. Include an **in-app tutorial** (a step-by-step screen with images or text) on how to get the file:
  1. **Small area (a neighborhood):** openstreetmap.org → Export → select the area → download a `.osm` file (limit of about 50k nodes).
  2. **Larger area:** BBBike extract (extract.bbbike.org), draw the area, choose the "Protocolbuffer (PBF)" format and receive it by email or link. Alternatively, the Overpass API with a ready-made query.
  3. **City or state:** download.geofabrik.de, then the continent, country and region, and download the `.osm.pbf`.
  - The tutorial ends with "open the file in J' PZ MAP STUDIO → choose the area on the map → Generate".
  - The app validates the file: format, whether it covers the chosen area, and a size estimate of cells and generation time before it starts.
  - Optional extra sources, such as building footprints with height (GeoSampa in São Paulo), are explained in the same tutorial as "improves heights and footprints".
