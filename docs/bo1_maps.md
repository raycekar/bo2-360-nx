# Black Ops 1 maps (optional, experimental)

This fork, **bo2-360-nx_extended**, adds an optional add-on that brings Black Ops 1 Zombies maps into Black Ops II:
**the BO1 map, with BO2 gameplay.** Like the DLC, it is built from your own game files and is off unless you install
it.

## Status

| Map | Globe pin | Start location menu | Playable |
| --- | --- | --- | --- |
| Nacht der Untoten (`zm_nacht`) | yes (TranZit's pin image for now) | yes (Nuketown's small map image for now) | not yet: Start reports the missing `maps/mp/zm_nacht.d3dbsp` |

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

## Next

1. Convert Nacht's map zone. BO1 360 zones decode (Salsa20 with the flag-0 key from the BO1 executable, one shared
   200-entry IV table, deflate chunks up to `0xC000`). The T5 asset list then has to be rewritten as T6 assets:
   clipMap, ComWorld, GameWorld, GfxWorld, images, models, scripts. OpenAssetTools has T5 and T6 structures but no
   T6 writer for the world assets.
2. Nacht's own pin image (`menu_zm_map_signpost_*`) and start location map image.
3. The globe steps to Nacht from TranZit in the opposite direction to before. The order follows `GetMaps`; sort it
   by column 16 if it matters.
