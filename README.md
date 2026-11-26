<p align="center">
  <img src="docs/images/banner.png" alt="bo2-360-nx_extended" width="100%">
</p>

<p align="center">
  <b>bo2-360-nx_extended: the Black Ops 1 Zombies maps, playable in the Black Ops II recompilation.</b><br>
  The BO1 map, with BO2 gameplay. Built from your own game files.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Nintendo%20Switch-E60012?style=for-the-badge&logo=nintendoswitch&logoColor=white" alt="Nintendo Switch">
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--3.0-blue?style=for-the-badge" alt="License: GPL-3.0"></a>
  <img src="https://img.shields.io/badge/status-experimental-orange?style=for-the-badge" alt="Status: experimental">
</p>

---

## The goal

Play the classic Black Ops 1 Zombies maps again with **local four-player split screen**, on the Switch and on
Windows. This fork builds on [bo2-360-nx](https://github.com/AlvaroEPena/bo2-360-nx), a static recompilation of
Black Ops II (Xbox 360) that already runs Zombies natively with split screen for up to four players. The fork adds an
**optional, experimental add-on** that converts BO1's Zombies maps (from the Xbox 360 game files) into BO2 maps:
**BO1's world, BO2's gameplay** (its weapons, perks, HUD, AI and split screen).

> [!IMPORTANT]
> **No game data is included, and none ever will be.** You need your own Xbox 360 copies of Black Ops II (with Title
> Update 18) and Black Ops 1 (with its map packs for the DLC maps). Everything is converted on your PC from your
> files; the result is yours alone and must not be shared. This repository holds only tools, code and notes.

## Contents

[Status](#status) · [The maps](#the-maps) · [How a map is converted](#how-a-map-is-converted) ·
[Findings so far](#findings-so-far) · [Next steps](#next-steps) · [Building](#building) ·
[The base game](#the-base-game) · [Credits](#credits) · [License](#license)

## Status

**Nacht der Untoten is playable, still rough.** It shows on the Zombies globe with its own start location, loads
into BO1's map, and plays BO2 Zombies in it.

| Part | State |
| --- | --- |
| Globe and menus | Nacht has a pin and a start location menu (stand-in pin and preview images for now) |
| Collision and movement | Nacht's own, converted: walls, floors, stairs, clipping |
| Zombie paths | Nacht's path nodes and links, converted; zombies spawn at Nacht's spawners and reach the players |
| Doors, debris, zones | Nacht's door and two debris piles open and unlock their zones (start, box room, upstairs) |
| Wall weapons | Nacht's 8 wall buys, mapped to BO2 weapons |
| Mystery box | At Nacht's spot, facing the right way |
| Geometry | Nacht's own world geometry |
| Textures | Nacht's own textures, decoded from BO1's image packs; decals and blend layers drawn as overlays |
| Lighting | Nacht's own baked light (lightmap); a neutral light grid stands in for the dynamic lighting |
| Windows | Open: zombies climb through, but there are no boards to repair yet |
| Props | Missing (BO1's static models are not converted yet), which leaves some see-through gaps |
| Sounds and music | Still the base map's |
| Install | The map zones are built with the tools by hand; the installer adds the map pack, not the map yet |

Recent fixes: sparkling surfaces (normal maps), a dark green tint (the base map's lights and light grid), walls
vanishing by view angle (the base map's occluders), flickering overlays (decals drawn as walls), and two in-game
crashes (a renderer read of a padding surface, and gibs with no dynamic-entity pool). The latest crash fix still
needs a play test with the ray gun.

## The maps

Every Zombies map of Black Ops 1 on the Xbox 360, in the order they are planned. Render world sizes (MB) are measured
from the game files; the relocating rebuild means none is bound by the base map's size (Nuketown's is 30.0).

| Map | BO1 zone | Comes from | Render world | State |
| --- | --- | --- | --- | --- |
| Nacht der Untoten | `zombie_cod5_prototype` | Rezurrection map pack | 17.5 | **playable, in progress** |
| Verrückt | `zombie_cod5_asylum` | Rezurrection map pack | 24.6 | planned |
| Shi No Numa | `zombie_cod5_sumpf` | Rezurrection map pack | 43.5 | planned |
| Der Riese | `zombie_cod5_factory` | Rezurrection map pack | 37.7 | planned |
| Kino der Toten | `zombie_theater` | the game disc | 44.1 | planned |
| "Five" | `zombie_pentagon` | the game disc | 40.4 | planned |
| Ascension | `zombie_cosmodrome` | First Strike map pack | 42.2 | planned |
| Call of the Dead | `zombie_coast` | Escalation map pack | 39.1 | planned |
| Shangri-La | `zombie_temple` | Annihilation map pack | 41.8 | planned |
| Moon | `zombie_moon` | Rezurrection map pack | 39.9 | planned |

Dead Ops Arcade is a different game mode (top-down), not a Zombies map, and is not planned.

## How a map is converted

Both games run on the same engine family and the same Xbox 360 hardware, so most of a map's data has a BO2
counterpart that differs in layout rather than in kind. The converter reads BO1's data, rewrites it into BO2's
layouts, and puts it into a BO2 map zone. In order:

1. **Read BO1's map zone.** The zone's loader is BO1's own code: a small PowerPC interpreter
   (`tools/bo1_maps/zoneload.py`) runs the game's `Load_*` functions from your decrypted executable, so every structure
   lands in memory exactly as the game builds it. The same interpreter loads BO2 zones to check the result.
2. **Start from a BO2 map.** A BO2 Zombies map zone of your own (Nuketown, renamed) gives the container: assets,
   script strings, sounds, effects and the map script that BO2's gameplay expects.
3. **Convert each part of the world** and splice it in place of the base map's:
   * collision (planes, brushes, triangles, the AABB tree, brush models, materials) and the entity string;
   * zombie paths (nodes, links, visibility) and the game world;
   * entities: spawners, zones, doors and debris, wall buys, the mystery box, windows, translated to BO2's prefabs;
   * the render world: BSP, cells and portals, vertices (re-quantized per surface), indices, surfaces, brush models;
   * the lightmap: BO1's baked light re-encoded in BO2's format;
   * textures: BO1's image packs decoded and each texture placed in a new BO2 material.
4. **Rebuild the zone with relocation.** BO1's data rarely has the size of what it replaces, so the rebuild records
   every pointer in the base zone and moves each one past an edit, keeping alignment (`reloc_scan.py`,
   `zone_rebuild.py`). Every other asset keeps its exact layout, which is checked asset by asset.
5. **Edit the map script.** BO2's map script is decompiled from your zone with
   [gsc-tool](https://github.com/xensik/gsc-tool), edited for the BO1 map (zones, doors, box location), compiled and
   written back. Only the edits are stored here.
6. **Install as a map pack.** The map goes into BO2's unused fifth DLC slot, so the globe lists it like DLC, and the
   app accepts the pack's zones and merges its rows into the game's map tables.

Every step is checked in the interpreter before the game ever runs it, and crashes in play are traced with the
game's own symbols back to the recompiled function and the data it read.

Full notes, layouts and commands: **[docs/bo1_maps.md](docs/bo1_maps.md)**.

## Findings so far

The things that made the difference, in short (details and offsets in [docs/bo1_maps.md](docs/bo1_maps.md)):

* **Layouts mostly carry over.** Collision, paths and render world structures exist in both games; many grew by a
  field or changed order (path nodes 0x80 → 0x90 bytes, surfaces 80 → 96, cells 56 → 48, portals gain bounds, brush
  models gain padding). Vertices are packed differently: BO2 quantizes positions per surface.
* **The base map's size is not a limit.** With pointer relocation the converted world can be larger or smaller than
  the base map's.
* **BO1's textures stream from image packs** (`.pak`): a simple sector table, with each mip level stored raw or as
  one LZO1X stream, in the same GPU tiling as zone pixels. They decode and copy straight into BO2 images.
* **Lighting is per map data, not per material.** BO1's lightmap converts to BO2's three-tile format. The light grid,
  local lights, reflection probes and occluders of the base map must not be kept: they tint, light and hide the new
  map by the old map's coordinates.
* **Material kinds matter.** BO1 marks decals and blend layers by their sort key; drawn as ordinary walls they
  flicker against the wall below, and sky surfaces show their texture. BO2 decal and blend materials fix both.
* **Runtime pools come from the map.** The collision map sizes the dynamic entity pool that zombie gibs use; an empty
  one crashes on the first gib.
* **Windows need BO2's barrier asset.** Zombies only tear boards through BO2's barrier entities and their animations,
  which come from another map's zone: the next step is copying assets between zones.

## Next steps

1. **Verify the crash fixes** in a longer play session (ray gun, explosives, several rounds).
2. **Props and windows:** copy assets between zones (models, animations, the barrier asset) so Nacht gets its props
   and repairable windows.
3. **Clean-ups:** the base map's remaining static models and outdoor bounds; Nacht's own lights; sounds and music;
   the pin and start location images.
4. **Installer:** fold the whole conversion into `tools/install_bo1_maps.py`, so one command builds the maps from
   your files.
5. **Polish:** Nacht's own light grid, reflection probes, normal maps, mipmaps and sky.
6. **The next maps,** starting with Verrückt, each with its own entity translation and map script edits.

## Building

1. **Build the base game** with the upstream project's kit, from your own Black Ops II files: see
   [Installing](https://github.com/AlvaroEPena/bo2-360-nx#installing) upstream. The app in this repository adds the
   pieces the add-on needs (`app/src/bo2zm_dlc.cpp`, `app/src/ui/menus.lua`).
2. **Install the map pack:**
   ```
   python -I tools/install_bo1_maps.py --game <game folder> --content <user root>/0000000000000000/415608C3
   ```
   It writes the pack (map tables, names, the globe pin) and turns on `bo2zm_custom_maps` in `bo2zm.toml`.
   `--remove` takes it out again.
3. **Build the map zone** from your BO1 files with the tools in `tools/bo1_maps/` (by hand for now; the steps are in
   [docs/bo1_maps.md](docs/bo1_maps.md#pipeline-nacht-by-hand-for-now)). Python 3 with NumPy is needed.

## The base game

bo2-360-nx is a static recompilation of Black Ops II (Xbox 360, Title Update 18): the game's PowerPC code is
translated ahead of time into C++ and compiled for the Switch and for x86-64 PCs, and a Vulkan renderer of its own
draws the game. It brings every Zombies map, Multiplayer with bots, the Campaign, split screen for up to four
players, System Link and online play, a GSC script loader and built-in cheats. Everything about it, from features to
installing, is in the [upstream README](https://github.com/AlvaroEPena/bo2-360-nx#readme) and in this repository's
[docs/features.md](docs/features.md), [docs/script-mods.md](docs/script-mods.md) and
[docs/technical.md](docs/technical.md).

## Credits

* **bo2-360-nx** by AlvaroEPena: the recompilation this fork is built on
  ([Discord](https://discord.gg/b8qchp7WjX), [Ko-fi](https://ko-fi.com/varo)).
* [gsc-tool](https://github.com/xensik/gsc-tool) for decompiling and compiling map scripts, and OpenAssetTools for
  its documentation of the fastfile format.
* The upstream projects and libraries, with their licenses, are listed in
  [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

GPL-3.0 ([LICENSE](LICENSE)); bundled upstream code keeps its own notices, listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Call of Duty, Call of Duty: Black Ops and Call of Duty: Black Ops II are trademarks of Activision Publishing, Inc.
Nintendo Switch is a trademark of Nintendo. Xbox 360 is a trademark of Microsoft. This project is not affiliated with
or endorsed by any of them, and it contains no game data.
