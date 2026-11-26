# Black Ops 1 maps (optional, experimental)

This fork, **bo2-360-nx_extended**, adds an optional add-on that brings Black Ops 1 Zombies maps into Black Ops II:
**the BO1 map, with BO2 gameplay.** Like the DLC, it is built from your own game files and is off unless you install
it.

## Status

| Map | Globe pin | Start location menu | Playable |
| --- | --- | --- | --- |
| Nacht der Untoten (`zm_nacht`) | yes (TranZit's pin image for now) | yes (Nuketown's small map image for now) | partly: Nacht's collision, paths and entities with BO2 gameplay reach round 1 and zombies attack; it still looks like (dark) Nuketown, since the render world is not converted |

## Install and remove

```
python -I tools/install_bo1_maps.py --game <game folder> --content <user root>/0000000000000000/415608C3
python -I tools/install_bo1_maps.py --game <game folder> --content ... --remove
```

`--image` defaults to `work/dump_tu18/default_mp.image.bin` (the decrypted TU18 program that the build writes).
The installer writes a DLC pack in BO2's unused fifth slot and adds `bo2zm_custom_maps = true` to `bo2zm.toml`.
Nothing from either game is stored in this repository. The rows and text in `tools/bo1_maps/<map>/` are this
project's own, and the pack's zone is encrypted with the key rebuilt from your decrypted game.

## How it works

* **Pack:** `dlc5.id` makes map pack index 7 owned (the DLC table at `0x82976DF8` has `MENU_DLC5_MAPS`, mask
  `0x100`). The pack folder's name sorts after the retail packs, so they mount first. Mounting earlier delayed
  Vengeance past the globe's first map list, and Buried went missing.
* **Zone `dlc5_load_zm.ff`** (`tools/bo1_maps/t6zone.py`): string tables (asset type 43) and localize entries (25),
  in the signed layout with an auth block borrowed from a retail fastfile.
* **Unsigned zones** (`app/src/bo2zm_dlc.cpp`, only with `bo2zm_custom_maps`): `sub_822AA8D0`, the RSA signature
  check, reports a pass.
* **Merged tables:** a zone loaded later does not replace a registered asset. The pack's `zm/mapsTable.csv` and
  `zm/gametypesTable.csv` hold only the new rows, plus empty rows for room. The hook copies the game's rows in front
  of them, resolves `@<row>+<n>` placeholders (for example `@maxnum_map+0`, the next free map index), applies
  `=<row>` replacement rows (`maxnum_map`, `maxnum_startloc`, `startloc_gamemode_map`), rebuilds the hash index and
  points the registered table at the result.
* **Re-parsing:** the map list (`sub_8244E4C8`) and the start locations (`sub_8244EAB8` → `sub_8244E790`) are
  built at startup and when DLC mounts, before any DLC load zone is loaded. They are parsed again after the merge.
* **Globe:** `LUI.createMenu.SelectMapZM` builds its pins once, before the pack's zone loads. With the setting on,
  `menus.lua` lists the custom maps in `CoD.SelectMapZombie.GetMaps` while the globe builds, and
  `UIExpression.TableLookup` answers for their rows until the merged table is in place.
* Each row type in `zm/gametypesTable.csv` has its own index sequence (type 5: start locations; type 6: start
  location × mode), and the parsers read only up to the count rows.

## Nacht's map zone: what is known

* The BO1 zone is `zombie_cod5_prototype` (Rezurrection; "prototype" is BO1's internal name for Nacht). The
  decoded zone has 903 assets, and the world assets are consecutive: com_map (#377), lightdef, 37 techsets,
  gfx_map (#416), game_map_sp (#417), col_map_sp (#418). The asset data starts at 0x4A19.
* The map name `maps/zombie_cod5_prototype.d3dbsp` is stored inline **once**; the other world assets point back to it.
* OpenAssetTools' PC `clipMap_t` (T5) header pattern (name, isInUse, planeCount, planes = -1, ...) is **not**
  found in the 360 zone. The 360 layout differs.
* A run of 2,782 plane-like 20-byte records (unit normal, dist, type ≤ 3) sits at 0x12FE372. Its second byte after
  the type reads 8, so it may not be `cplane_s` as on the PC. Unconfirmed.
* **Done: `tools/bo1_maps/t5load.py` loads BO1 zones by running BO1's own loader code** (TU11 `default.image.bin`)
  in a small PowerPC interpreter. The stream API is reimplemented: `Load_Stream` 0x821F0668, alloc 0x821F05F8,
  push/pop 0x821F04F0/0x821F0578, offset→pointer 0x821F0790, `DB_LinkXAssetEntry` 0x821EC8B0 (keeps a copy of the
  header), file reads 0x821D9FF0/0x821D9EB0/0x821DA178. The root is driven like `DB_LoadXFileInternal`
  (0x821DA420): header, XAssetList, script strings (0x821DAB88), then `Load_XAsset` (0x821EB078) per asset. Nacht's
  first 419 assets, through col_map_sp, load in about 12 s. clipMap: 2,782 planes, 916 static models,
  216 materials, 4,759 brush sides, 918 nodes, 1,089 leafs, 12,461 verts. BO1's `Load_clipMap_t` is 0x821E5B28
  (0x14C bytes). BO2's is 0x822BD3C8 (0x14C bytes, with `ClipInfo` inline at +8, loaded by 0x822BCB08; then
  pInfo +0x50, static models +0x54/+0x58, nodes +0x5C/+0x60, leafs +0x64/+0x68); `Load_Stream` 0x822CC1D8.
* **`tools/bo1_maps/zoneload.py` now runs both games' loaders** (`--game t5|t6`). BO2 profile (TU18
  `default_mp.image.bin`): `Load_Stream` 0x822CC1D8 (file blocks 0, 5, 6; 1–2 zeroed; 3–4 deferred to the end of
  the file; 7 neither read nor advanced), alloc 0x822CC168, inc 0x822CC180, push/pop 0x822CC060/0x822CC0E8,
  pointer 0x822CC380 / alias 0x822CC358, string 0x822CC3A8 → read 0x822AD728, file read 0x822AD5D8, link
  0x822C6B18, script strings 0x822AEFE8, `Load_XAsset` 0x822C4578 (root 0x822ADA38). Nuketown Zombies
  (`zm_nuked.ff`, 148 MB) loads completely; its world assets are gfx_map #1040, game_map_mp #1041 and
  col_map_mp #1045. Nuketown's clipMap leaves `brushBounds`/`brushContents` null.
* Header comparison (360 offsets; T5 left, T6 right): BO1 counts and pointers sit at 0x08–0xB0 in PC order. BO2
  groups planes, materials, brush sides, leaf brush nodes, leaf brushes, brush verts, uinds and brushes into
  `ClipInfo` (0x08–0x4C), then pInfo 0x50, staticModels 0x54, nodes 0x5C, leafs 0x64 (0x2C bytes each, as in T5),
  verts 0x6C, tris 0x74, partitions 0x80, aabbTrees 0x88, cmodels 0x90, numClusters 0x98, visibility 0xA0,
  mapEnts 0xA8, box_brush 0xAC. BO1-only: leafsurfaces, borders. In the BO1 TU11 image (`default.image.bin`), find
  `Load_clipMap_t` / `Load_clipMap_tPtr` (the asset load switch is indexed by type; col_map_sp is type 12 in the 360
  enum). Read the field order and sizes from its stream reads, then write a T5 clipMap reader that starts at a
  found header and checks itself with the counts.

### Collision converted (2026-11-25)

`tools/bo1_maps/t6clip.py <BO1 zone> <BO1 default.image.bin> <out.zone>` turns Nacht's col_map_sp into a BO2
col_map_mp zone. It writes in BO2's Load_clipMap_t order and simulates block 5 positions with alignment, so shared
pointers are offsets, as in retail zones. BO2's loader reads the output to its last byte, and every pointer
resolves to the same data as in BO1: 4,759 brush sides with their planes, 918 nodes, 3,970 leaf brush nodes,
2,874 leaf brush lists, brushes, leafs, verts, tris, AABB trees and collision materials.

Lessons learned on the way:
* T5 → T6 struct changes: `ClipInfo` grouping. dmaterial_t (char[64] + flags) becomes ClipMaterial (name pointer +
  flags). cStaticModel gains `contents` (0x50 → 0x54). CollisionPartition drops borders (20 → 16 bytes).
  cmodel_t gains `ClipInfo* info` (null in retail). Unchanged: planes, brush sides, nodes, brushes, leafs,
  AABB trees, leaf brush nodes.
* BO2 reads **one vec3** when a brush's `verts` is -1: brush verts must point into `ClipInfo.brushVerts`.
* Some BO1 leaf brush nodes keep their brush list inline (not in `leafbrushes`). Those stay -1, written right
  after the node array.
* Still missing: static models (they need the XModels), mapEnts (the entity string), dynamic entities.

### World data converted: com_map, game_map_mp, col_map_mp (+ map_ents)

`t6clip.py` now writes a zone with three world assets, which loads completely through BO2's loader:
* **com_map**: 20 primary lights. BO1 ComPrimaryLight is 0xDC bytes, BO2's 0xC4 (see `write_comworld`).
* **game_map_mp**: 670 path nodes, 56,029 bytes of path visibility, a 399-node tree (598 child/leaf checks match
  BO1). BO2 streams **nodeCount + 128** nodes (spare runtime slots). pathnode_t is 0x80 → 0x90 and pathlink_s
  12 → 16 bytes. Node types 8/9/10 are renumbered (BO2 has no wide cover). Script strings (targetname, ...) are
  renumbered into the zone's own string list (BO2 `Load_ScriptStringList` 0x822AEFE8; remap per field 0x822CC438).
  Base nodes live in block 1 (runtime): no file data. Guessed defaults (BO1 does not store them; most common in
  Nuketown): node spawnflags |= 0x300000, link flags 0x28.
* **col_map_mp** with **map_ents** inline.

### In game (2026-11-25 evening)

1. **The Nacht slot loads a real map.** Nuketown's zones renamed in place (`nuked` → `nacht`, same length, so no
   offsets move: zm_nacht.ff, zm_nacht_patch.ff, en_zm_nacht_loc.ff, zm_nacht.ipak, zmb_nacht_* sound banks) start a
   match from Nacht's globe pin. Two engine details were needed: map zones get their `<map>_patch` zone only when
   listed in the zone loader's table at 0x8296EBD8, so the hook points its unused `common_mp` entry at zm_nacht; and
   unresolved GSC imports are now always logged (`[gsc] unresolved import ...`).
2. **Nacht's collision and path network replace Nuketown's** (`tools/bo1_maps/splice_world.py`). Each replacement
   starts at the original's block 5 position and is padded to end at the same place (collision: cluster visibility;
   paths: 889 nodes with inert spares, the visibility table extended (2 bits per node pair, triangular), the
   smoothing cache, one repeated leaf entry for 4-byte parity). BO2's loader confirms all 2,133 later assets keep
   their positions. In game the zone loads and the intro reads "NACHT DER UNTOTEN / SURVIVAL", but the match does not
   start: Nuketown's scripts look for their own spawn structs, zones and barriers in the entity string, and get
   Nacht's BO1 entities instead.

### Entities and map script (2026-11-25 night): round 1 on Nacht

With Nacht's BO1 entity string in the zone, Nuketown's map script found none of its spawn points, zones or boxes and
the match never left the intro card. Two parts fix that:

1. **Entities** (`tools/bo1_maps/nacht_ents.py`): Nacht's entity string is rewritten into what BO2's Zombies scripts
   read. Kept: player starts, intermission cameras, path nodes, the 15 zone volumes (start, box room, upstairs), the
   door and debris triggers with their brush models, static brush models. Rewritten: the 42 BO1 zombie spawners become
   `<zone>_spawners` spawn-location structs; 8 wall weapons become BO2 wallbuy structs with BO2 weapons and models
   from Nuketown's zone (Kar98k → M14, M1 Carbine → B23R, Thompson → MP5, double barrel → Olympia, sawed-off →
   AK74u, trench gun → Remington 870, BAR → M16, stielhandgranate → Semtex); the box becomes a `zbarrier_zmcore_MagicBox`.
   From Nuketown: worldspawn and lights (the render world is still Nuketown's), the zombie and dog spawner entities.
   Dropped: window boards, BO1 script models (their XModels are not in the zone), wall chalk (brush models past
   Nuketown's render models: drawing `*147` crashed the renderer's model streaming), audio and Easter-egg triggers.
   Traversal node names reuse Nuketown's (`pfN_auto2108`, `zm_mantle_over_40`), so the path nodes' script strings
   resolve; `splice_world.py --ents <file> --aliases <json>` writes both.
2. **Map script**: Nuketown's `maps/mp/zm_nacht.gsc` (renamed with the zone) is decompiled with
   [gsc-tool](https://github.com/xensik/gsc-tool) 1.6.2, edited by `tools/bo1_maps/zm_nacht/script_edits.py` (no game
   script is stored here), compiled again and written over the original inside `zm_nacht_patch` by `inject_gsc.py`
   (same length, zero padded). The client scripts are still Nuketown's, so the server keeps registering the same
   client fields (perk and Pack-a-Punch settings stay on); otherwise the client disconnects with
   `EXE_CLIENT_FIELD_MISMATCH`.

Diagnostics: a map script can `setdvar( "bo2zm_map_trace", ... )`; with `bo2zm_custom_maps` on, the app logs each new
value as `[map script] ...`. The game itself prints script errors only in developer builds.

Steps used (paths are examples; the zones come from your own game files):
```
python -I nacht_ents.py ents_nacht.txt ents_nuked.txt ents_nacht_bo2.txt aliases.json
python -I splice_world.py zm_nacht_from_nuked.zone <footprint>.json zombie_cod5_prototype.zone default.image.bin \
    zm_nacht.zone --ents ents_nacht_bo2.txt --aliases aliases.json --bo2-image default_mp.image.bin
python -I zm_nacht/script_edits.py decompiled/t6 nacht_src
gsc-tool -m comp -g t6 -s xb2 -w decompiled/t6 nacht_src
python -I inject_gsc.py zm_nacht_patch.zone zm_nacht_patch_new.zone compiled/t6 maps/mp/zm_nacht.gsc maps/mp/zm_nacht_standard.gsc
```
then encode both zones (signed layout) into the pack.

Known gaps: no window barricades (zombies walk in through open windows; BO2's `_zm_blockers` still has the BO1 board
code path, untested), no perks (as in the original Nacht), BO1 pathnode targetnames `autoNN` are not in the zone's
string list (set to none), only one player respawn location (the start room).

### Windows (barricades): what they need

* BO2 zombies tear boards only through a `zbarrier` entity (`tear_into_building` reads chunk health, attack slots and
  animation states from it); BO1-style board brush models are not enough.
* BO1 and BO2 windows share the prefab layout: the `exterior_goal` struct; 3 units in, the barrier and the mantle's
  begin node (which must carry the barrier's targetname); +44 the repair trigger struct (radius 36, height 64); +80 the
  end node. `nacht_ents.py --windows` writes all 12 of Nacht's windows this way (TranZit's
  `zbarrier_zmcore_BasicWoodBarrier` keys), and `splice_world.py` names the begin nodes (`_node_targetnames`).
* A `zbarrier_<type>` entity needs the **zbarrier asset** (type 61) of that name: the game stops with "Could not load
  default asset ... zbarrier zmcore_BasicWoodBarrier". Nuketown's zone has only `zmcore_MagicBox`. The window asset
  (`zmcore_basicwoodbarrier`, ~580 bytes: a 560-byte header in the temp block, the name in block 5) and the board
  animations `o_zombie_board_<n>_pull` / `_repair` are in TranZit's zone (`zm_transit.ff`); the board models
  (`p6_anim_zm_barricade_board_0<n>`, `_upgrade`, `_collision`) and the zombies' tear/enter animations are already in
  Nuketown's.
* So windows wait for copying assets between zones. The map zone's asset list is in block 5 with the asset data, so
  adding entries there would move every pointer; the copies need a zone of their own that loads with the map, and the
  references inside them (block offsets into TranZit's zone, script strings) rewritten.

### Render world (gfx_map): first measurements

* Sizes (block deltas while the asset loads). Nacht (BO1 #416): 11.0 MB virtual (block 4), 6.5 MB physical (block 2:
  vertex and image data), 0.7 MB runtime (block 1); header 0x4A8. Nuketown (BO2 #1040): 18.3 MB virtual (block 5),
  11.7 MB delayed (block 3), 0.75 MB runtime (block 1). Nacht fits in Nuketown's footprint with room to spare, so the
  splice approach works here too; a different base map is not needed for space.
* Both games stream the **materials and images first used by the world inside the world asset** (BO1: 124 material
  headers and 181 image headers; BO2 Nuketown: ~466 material-sized groups). So a converted world can carry Nacht's own
  materials and textures inside the spliced asset, pointing at techsets that already exist in Nuketown's zone.
* Load traces: `asset_trace.py <zone> t5|t6 <asset> <out>` (every Load_Stream with block, size, destination and the
  header field that points at it, plus pointer conversions); `trace_summary.py` collapses one. BO1 header fields with
  arrays: 0x18, 0x20, 0x3C, 0x100, 0x158–0x188, 0x20C (5.4 MB), 0x234, 0x260, 0x2A0–0x2E4, 0x38C–0x3FC. BO2:
  0x18, 0x20, 0x100–0x140, 0x178–0x1A4, 0x1B0 (5.4 MB), 0x1D8 (block 7), 0x1E0, 0x208, 0x248–0x29C, 0x344–0x3FC.

* Struct differences (OpenAssetTools' T5/T6 headers, PC layouts; the 360 traces are authoritative where they
  differ): BO1 `GfxWorldDraw` has one `GfxWorldVertex` array (xyz, binormalSign, color, texCoord, lmapCoord, packed
  normal and tangent: 44 bytes) plus a vertex-layer stream and three lightmap textures per array; BO2 has two packed
  vertex streams (`vd0`, `vd1`, sizes in bytes), an index buffer and two lightmap textures. BO2 adds fog, LUT and
  sky-grid volumes, spherical-harmonics lighting on static models and reflection probes, siege skins and hero lights;
  BO1 has world LOD chains and per-surface sky lists that BO2 dropped. Cells, portals, AABB trees, surfaces
  (`srfTriangles_t` + material + lightmap/probe/light indices + bounds) and brush models keep their shape.

### Fitting every BO1 map: relocating zone rebuild

Measured world sizes (MB; render world = data + vertex/image data; paths include the BO1 → BO2 growth):

| BO1 map | render world | collision | paths | | BO2 base | render world | collision | paths |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Nacht | 17.5 | 1.8 | 0.24 | | Nuketown | 30.0 | 3.7 | 0.38 |
| Verrückt | 24.6 | 2.3 | 1.03 | | TranZit | 38.7 | 10.3 | 1.59 |
| Shi No Numa | 43.5 | 5.7 | 1.74 | | Die Rise | 26.4 | 6.9 | 0.62 |
| Der Riese | 37.7 | 5.9 | 0.46 | | Mob of the Dead | 27.4 | 6.0 | 0.64 |
| Kino der Toten | 44.1 | 5.7 | 0.74 | | Buried | 23.7 | 6.4 | 0.68 |
| Five | 40.4 | 5.0 | 0.63 | | Origins | 26.8 | 7.1 | 0.82 |
| Ascension | 42.2 | 6.3 | 0.71 | | | | | |
| Call of the Dead | 39.1 | 7.7 | 1.29 | | | | | |
| Shangri-La | 41.8 | 8.5 | 0.37 | | | | | |
| Moon | 39.9 | 8.6 | 1.04 | | | | | |

Padding into a base map's slots fits only Nacht and Verrückt into Nuketown, and no base fits every map. So zones are
now **rebuilt with relocation** instead:

* `reloc_scan.py <zone> <out.bin> <image>` runs BO2's loader over the whole zone and records every stored block
  offset (each word converted by `DB_ConvertOffsetToPointer` 0x822CC380 or `DB_ConvertOffsetToAlias` 0x822CC358)
  with its file position; the root's own reads (depends and asset arrays) report through `zoneload.raw_hook`.
  Nuketown's map zone: 144,832 offsets, all into block 5, in 84 s.
* `zone_rebuild.py`: replace file ranges with data of any size; every offset past an edit is shifted (each boundary is
  compared with the original offset), the header's sizes are fixed, and offsets from outside into replaced data are
  reported (or remapped by a caller-supplied function). Shifts must be multiples of 4096: sound banks align their data
  to 2048 in block 5, so other shifts change their padding and everything after them.
* `splice_world.py ... --relocs <table>` writes Nacht's paths and collision at their natural sizes (the zone shrinks
  by 2.16 MB). Checked: all 3,179 assets load; every other asset keeps its exact footprint; memory after the edits
  matches the padded build word for word (shifted); in game the match reaches round 1.
* Inbound references: none point into the collision or paths; into Nuketown's render world, 35,809 come from its
  collision (replaced anyway) and 2 from elsewhere (one asset-list entry, one model, asset 3152) — these must be kept
  when the render world is replaced.
* The deferred block 3 is stored after the last asset in block order (Nuketown: 21,516,288 bytes = its header size),
  so render data there can be edited and shifted the same way.

The same rebuild will add assets (new asset-list entries are block 5 data at the zone's start), e.g. the window
barrier and its animations, and extend the script string list.

### Render world layouts (360; from the load traces and the data)

Header: BO1 0x4A8 bytes, BO2 0x460. Field pairs (BO1 → BO2): planeCount 0x08 → 0x08, nodeCount 0x0C → 0x0C,
surfaceCount 0x10 → 0x10, streamInfo 0x14 → 0x14 (aabbTreeCount, trees, leafRefCount, leafRefs), sunLight 0x100 →
0x100, primaryLightCount 0x114 → 0x108, dpvsPlanes 0x154 → 0x174 (cellCount, planes 20 B, nodes u16,
sceneEntCellBits), cellBitsCount/cells 0x164/0x168 → 0x184/0x188, draw 0x16C → 0x18C (probeCount, probes,
probeTextures, lightmapCount, lightmaps, lightmap textures), vertexCount 0x208 → 0x1A8, vertices 0x20C (44 B each) →
vertexDataSize0 0x1AC + vd0 0x1B0 (28 B each), BO1 layer data 0x230/0x234 → vertexDataSize1 0x1D4 + vd1 0x1D8 (block 7,
not in the file), indexCount 0x25C + indices 0x260 → 0x1DC + 0x1E0, light grid 0x284 → 0x204, brush models 0x2BC/0x2C0
→ 0x298/0x29C, materialMemory 0x2E0/0x2E4 (124 in Nacht, materials inline) → after 0x29C (~1,960 nested reads),
dpvs 0x3B0 → 0x36C (smodelCount, staticSurfaceCount, lit/decal(BO1)/trans(BO2)/emissive ranges, vis data counts and
runtime arrays, sortedSurfIndex u16 0x400 → 0x3BC, smodelInsts 40 B → 36 B 0x404 → 0x3C0, surfaces 80 B → 96 B
0x408 → 0x3C4, smodelDrawInsts 44 B → 240 B 0x410 → 0x3C8 (BO2: static models' XModels inline after it)).

* **BO2 world vertex (28 B, vd0)**: position as 4 × s16 (x, y, z, binormal sign), color RGBA8, texcoord half2, packed
  normal, packed tangent, lightmap coord (2 × 16-bit). The world shaders (`*world_quant`) decode
  `pos = q * vertexToObjectOffsetScale.w + vertexToObjectOffsetScale.xyz`, set per surface.
* **Surface** (BO1 80 B → BO2 96 B): BO2 starts with that vec4 (offset xyz, scale w; Nuketown uses 0.25), then the
  shared `srfTriangles_t` (mins + vertex data offset 0, maxs + vertex data offset 1, firstVertex, himipRadiusInvSq,
  vertexCount u16, triCount u16, baseIndex), material, lightmap/probe/primary light/flags bytes, bounds.
* **Cell** 56 B → 48 B (BO2 drops cullGroupCount/cullGroups); AABB tree nodes 40 B in both; planes 20 B and BSP
  nodes u16 in both.
* Shaders: `tools/inspect/ff_shaders.py <ff> --dump` extracts a zone's shaders; the kit's `bo2zm_hlsl.exe <in> <out>
  <shader_common.h>` translates them (inputs and constants readable).

Plan: edit Nuketown's render world array by array with the relocating rebuild (fields not converted yet stay
Nuketown's): vertices, indices, surfaces + sortedSurfIndex + dpvs counts, cells with their trees and portals, BSP planes
and nodes, brush models; static models, occluders and shadow-geometry lists emptied; materials mapped to Nuketown's at
first, then Nacht's own. Keep each edit's size change a multiple of 128 (pad a count-flexible array in it) and the
asset's total a multiple of 4096.

### Render world converted: Nacht's geometry renders (2026-11-25 night)

`t6gfx.py` (called by `splice_world.py ... --relocs <table> --gfx`) edits Nuketown's world in five regions:
streaming trees + leaf refs; BSP planes, nodes, cells with AABB trees, portals (+ bounds) and probe lists; vertices
(each surface its own quantized copy, 16-byte aligned groups, offset/scale vec4 per surface), the second stream (one
shared default block), indices; brush models; one tail region from the shadow lists to the surfaces (shadow lists
emptied; light regions, visibility data and static model instances copied as they were; sorted surfaces; surfaces).
In game the match reaches round 1 and Nacht's rooms, beams and stairs render.

What it took (checks: footprints of all other assets unchanged; the world's simulated size equals the loader's):
* Second vertex stream (header 0x1DC/0x1E0, 8 B per vertex, offset `vo1`): 128-aligned, not 4096. Index buffer:
  header 0x204/0x208 (Nuketown 400,264 indices). Surface `vo0` = byte offset into vd0.
* The tail's copied part holds 128-aligned visibility data, so its start must keep its position modulo 128.
* The sorted surface list's size change was 16 mod 32 while dummy surfaces move in steps of 32: dummy static surfaces
  (outside every draw range) are inserted after Nacht's static ones; brush models and leaf refs are renumbered.
* Material: surfaces point at alias slots (slot → material). The material must be a quantized-world one (`wq`/`wqc`,
  flags 0x30, e.g. `wqc/wood_burned`): `wpc` materials expect another vertex format (a black wire was picked first).

Not yet: Nacht's materials and textures (everything is one Nuketown material), lightmaps (Nuketown's, with Nacht's UVs:
over-bright), the lightmap coordinate format (written as half floats, unverified), light grid, reflection probes, sky,
static models (props), occluders and outdoor bounds (still Nuketown's).

## Remaining plan (in order)

1. **Lightmaps and lighting.** Confirm the BO2 lightmap coordinate format (half float vs 16-bit unorm) from a
   `*world_quant` shader's fetch and Nuketown's data. Convert Nacht's lightmap images (inline in its world, block 2)
   to BO2 images and replace Nuketown's lightmap array (header 0x198/0x19C, images inline after it). Then the light
   grid (0x22C..0x26C: BO1 colors → BO2 entries + SH coeffs), reflection probes (0x18C/0x190) and the sun/sky.
2. **Materials and textures.** Nacht's 124 world materials and 181 images are inline in its world. For each: convert
   the image (both games use Xbox 360 GPU textures; header layouts differ), then write a BO2 material that copies a
   Nuketown `wq`/`wqc` material of the same kind (opaque, alpha-tested, decal, layered) and swaps its images. Insert
   them in the world's material list (materialMemory, 0x298/0x29C) with the relocating rebuild; surfaces point at
   them. Layered/blended materials need the second vertex stream (vd1, block 7) — check what fills it.
3. **Static models (props)** and **window barricades**: new assets. Copy XModels/XAnims between zones with references
   rewritten (the relocating rebuild can add asset-list entries and script strings): Nacht's props (BO1 XModels →
   BO2), TranZit's `zmcore_basicwoodbarrier` zbarrier and its 12 board animations (then `nacht_ents.py --windows`).
4. **Clean-ups.** Nuketown's occluders and outdoor bounds (zero them), its static models (no longer referenced; drop
   or move), primary lights (com_map: Nacht's 20 lights), Nacht's sounds and music, the pin and start-location images,
   globe order, removal of the diagnostic Lua wrappers.
5. **Install path.** Fold every step into `tools/install_bo1_maps.py`: decode the user's BO1 and BO2 zones, rename
   Nuketown's zones, scan relocations, convert (collision, paths, entities, render world, scripts via gsc-tool),
   rebuild, encode, install. Nothing from either game in the repository.
6. **More maps.** Relocation removes the size limits (table above), so the same pipeline should take Verrückt, Shi No
   Numa, Der Riese and the rest; each needs its own entity/zone translation and map script edits.

## Next

* **Render world**: pair the BO1 and BO2 header fields (traces above), convert vertices/indices/surfaces/cells, map
  Nacht's materials onto BO2 techsets. Start by decoding BO2's `vd0`/`vd1` vertex formats from Nuketown's data.
* **Copy assets between zones** (a zone of our own loaded with the map; references rewritten): first the window
  asset and its 12 board animations (then `--windows`), later Nacht's own models, materials and images.
* **Render world (gfx_map)**, then Nacht's own lights (com_map), models and textures, so it looks like Nacht.
* Fold the steps above into `install_bo1_maps.py`.

1. Convert Nacht's map zone. BO1 360 zones decode (Salsa20 with the flag-0 key from the BO1 executable, one shared
   200-entry IV table, deflate chunks up to `0xC000`). The T5 asset list then has to be rewritten as T6 assets:
   clipMap, ComWorld, GameWorld, GfxWorld, images, models, scripts. OpenAssetTools has T5 and T6 structures but no
   T6 writer for the world assets.
2. Nacht's own pin image (`menu_zm_map_signpost_*`) and start location map image.
3. The globe steps to Nacht from TranZit in the opposite direction to before. The order follows `GetMaps`; sort it
   by column 16 if it matters.
