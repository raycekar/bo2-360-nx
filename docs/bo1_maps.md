# Black Ops 1 maps (optional, experimental)

This fork, **bo2-360-nx_extended**, adds an optional add-on that brings Black Ops 1 Zombies maps into Black Ops II:
**the BO1 map, with BO2 gameplay.** Like the DLC, it is built from your own game files and is off unless you install
it. Nothing from either game is stored in this repository.

## Status

| Map | Globe | Playable | Looks like |
| --- | --- | --- | --- |
| Nacht der Untoten (`zm_nacht`) | pin and start menu (TranZit's pin and Nuketown's map images for now) | yes: Nacht's collision, paths, entities and an edited map script; round 1, zombies come in through open windows | Nacht's geometry with Nacht's lightmap light, one stand-in Nuketown material; no props. Nacht's own textures: built, not yet tested in game |

Known: opening the globe in the first seconds after start can miss pins (it builds its list once while the packs
still mount); backing out and reopening fixes it.

## Install and remove

```
python -I tools/install_bo1_maps.py --game <game folder> --content <user root>/0000000000000000/415608C3
python -I tools/install_bo1_maps.py --game <game folder> --content ... --remove
```

The installer writes a DLC pack in BO2's unused fifth slot (`dlc5.id`, `dlc5_load_zm.ff`) and adds
`bo2zm_custom_maps = true` to `bo2zm.toml`. The map zones themselves are still built by hand (pipeline below); folding
that into the installer is on the plan.

## How the pack works

* `dlc5.id` makes map pack index 7 owned (DLC table 0x82976DF8: `MENU_DLC5_MAPS`, mask 0x100). The pack folder sorts
  after the retail packs, so they mount first.
* `dlc5_load_zm.ff` (`t6zone.py`): string tables and localize entries; zones from the pack are accepted unsigned
  (`app/src/bo2zm_dlc.cpp` hooks the RSA check `sub_822AA8D0`, only with `bo2zm_custom_maps`).
* Merged tables: the pack's `zm/mapsTable.csv` / `zm/gametypesTable.csv` hold only new rows; the hook copies the game's
  rows in front, resolves `@<row>+<n>` placeholders and `=<row>` replacement rows, rebuilds the hash index, and the map
  list (`sub_8244E4C8`) and start locations (`sub_8244EAB8` → `sub_8244E790`) are parsed again.
* Globe: `menus.lua` lists the custom maps in `CoD.SelectMapZombie.GetMaps` while the globe builds and answers
  `UIExpression.TableLookup` for their rows until the merged table is in place.
* Map zones get `<map>_patch` only when listed in the zone loader's table at 0x8296EBD8: the hook points its unused
  `common_mp` entry at `zm_nacht`.
* Diagnostics: a map script can `setdvar( "bo2zm_map_trace", ... )`; the app logs each new value as
  `[map script] ...`. Unresolved GSC imports are logged as `[gsc] unresolved import ...`.

## Pipeline (Nacht, by hand for now)

Base: Nuketown's zones renamed in place (`nuked` → `nacht`, same length: `zm_nacht.ff`, `zm_nacht_patch.ff`,
`en_zm_nacht_loc.ff`, `zm_nacht.ipak`, `zmb_nacht_*` sound banks). Tools in `tools/bo1_maps/`:

```
python -I nacht_ents.py ents_nacht.txt ents_nuked.txt ents_nacht_bo2.txt aliases.json      # entities
python -I reloc_scan.py zm_nacht_from_nuked.zone relocs.bin default_mp.image.bin           # once per base zone
python -I splice_world.py zm_nacht_from_nuked.zone <footprint>.json zombie_cod5_prototype.zone default.image.bin \
    zm_nacht.zone --ents ents_nacht_bo2.txt --aliases aliases.json --bo2-image default_mp.image.bin \
    --relocs relocs.bin [--paks "0=<BO1 disc iso>::images.pak;3=img_dlc1.pak"] --gfx [--materials]   # world, lightmap, textures
python -I zm_nacht/script_edits.py decompiled/t6 nacht_src                                  # map script
gsc-tool -m comp -g t6 -s xb2 -w decompiled/t6 nacht_src
python -I inject_gsc.py zm_nacht_patch.zone zm_nacht_patch_new.zone compiled/t6 maps/mp/zm_nacht.gsc maps/mp/zm_nacht_standard.gsc
```
then encode both zones (signed layout) into the pack. Scripts are decompiled from your zones with
[gsc-tool](https://github.com/xensik/gsc-tool) 1.6.2; only the edits live here.

## Remaining plan

1. **Textures (in progress).** Done: BO1's image packs decode (LZO1X, below) and `splice_world.py --materials
   --paks ...` gives each of Nacht's 72 color textures its own material with its pixels (largest mip only).
   In game: textures show. The template's own normal map made every surface sparkle (fine white dots); the new
   materials now use the base zone's `$identitynormalmap` (`--keep-normal` keeps the template's). The dark green
   look came from Nuketown's lighting (Lighting, below); with it neutralised the map shows its own warm light.
   Decals and blend layers use BO2 decal/blend templates; sky and shadow-only surfaces are hidden (Surface kinds).
   Next (optional polish): Nacht's own light grid, lights and probe cubemaps; then Nacht's normal maps, mips, sky.
2. **Props and windows: new assets.** Copy XModels/XAnims/zbarriers between zones with references rewritten (the
   relocating rebuild can add asset-list entries and script strings): Nacht's props, TranZit's
   `zmcore_basicwoodbarrier` and its 12 board animations (then `nacht_ents.py --windows`).
3. **Clean-ups.** Nuketown's outdoor bounds and static models (its 13 occluders, GfxWorld 0x438/0x43C, 68 B: flags,
   name[16], 4 points, hid Nacht's walls by view angle: `splice_world.no_occluders` collapses them to a point); Nacht's 20 primary lights (com_map);
   sounds and music; pin and start-location images; globe order and the early-globe pin race (rebuild pins after
   `ReparseMapsTable`); the diagnostic Lua wrappers.
4. **Install path.** Fold the pipeline into `tools/install_bo1_maps.py`.
5. **More maps.** Relocation removes the size limits (table below); each map needs its own entity/zone translation and
   map script edits.

## Reference

### Zone interpreter (`zoneload.py`)

Runs each game's own `Load_*` code in a small PowerPC interpreter with the stream API reimplemented.
BO1 (TU11 `default.image.bin`): `Load_Stream` 0x821F0668, alloc 0x821F05F8, push/pop 0x821F04F0/0x821F0578,
offset→pointer 0x821F0790, link 0x821EC8B0, root 0x821DA420, `Load_XAsset` 0x821EB078; Nacht's world assets: com_map
#377, gfx_map #416, game_map_sp #417, col_map_sp #418. BO1 file blocks: 0, 4, 5, 6 inline; block 2 stored after the
stream in block order, gap free.
BO2 (TU18 `default_mp.image.bin`): `Load_Stream` 0x822CC1D8 (file blocks 0, 5, 6; 1–2 runtime; 3 stored after the
last asset in block order; 7 neither read nor advanced), pointer 0x822CC380, alias 0x822CC358, link 0x822C6B18,
script strings 0x822AEFE8, `Load_XAsset` 0x822C4578; Nuketown's world: gfx_map #1040, game_map_mp #1041,
col_map_mp #1045. Helpers: `asset_trace.py` (every stream read of one asset, with the header field pointing at it),
`trace_summary.py`.

### Relocating rebuild

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

* `reloc_scan.py` records every stored block offset (each word converted by 0x822CC380 or 0x822CC358) with its file
  position (the root's own reads report through `zoneload.raw_hook`). Nuketown's map zone: 144,832 offsets, all into
  block 5, 84 s.
* `zone_rebuild.py`: replaces file ranges with data of any size, shifts every offset past an edit (boundaries compared
  with the original offset), fixes the header sizes, applies same-size patches after relocation, and reports offsets
  pointing into replaced data. Size changes must keep alignment: 4096 for the asset total (sound banks align to 2048),
  128 between regions that hold 128-aligned data.
* Checks: all other assets keep their exact footprint (`footprint.py`); memory after the edits matches, shifted.

### Collision, paths, entities, map script

* Collision (`t6clip.py`): BO2 groups planes … brushes into `ClipInfo`; dmaterial_t → ClipMaterial; cStaticModel
  0x50 → 0x54; CollisionPartition 20 → 16; cmodel_t gains `info`; brush verts must point into `ClipInfo.brushVerts`
  (a -1 pointer reads one vec3); some leaf brush lists stay inline. Entities go into its inline MapEnts.
* Paths: pathnode_t 0x80 → 0x90, pathlink 12 → 16 (flags 0x28), node types 8/9/10 renumbered, BO2 streams nodeCount
  + 128 nodes, visibility n(n-1)/8 bytes; node script strings are renumbered into the zone's list (BO1 `autoNN`
  targetnames are absent: set to none).
* Entities (`nacht_ents.py`): zones (start, box room, upstairs), door/debris, 42 spawners → spawn-location structs,
  8 wallbuys mapped to BO2 weapons/models, the box → `zbarrier_zmcore_MagicBox`; Nuketown's worldspawn, lights and
  spawner entities; BO1 script models, boards, wall chalk dropped. Traversal names reuse Nuketown's (`pfN_auto2108`,
  `zm_mantle_over_40`).
* Windows: BO2 zombies tear boards only through `zbarrier` entities, which need the zbarrier asset of that type
  (`zmcore_basicwoodbarrier`, in TranZit's zone with the `o_zombie_board_<n>_pull/_repair` animations).
  `nacht_ents.py --windows` writes all 12 windows (same prefab layout as BO2: goal struct, barrier and begin node +3,
  repair trigger +44, end node +80); off until the asset can be added.
* Map script: the client scripts stay Nuketown's, so the server keeps the same client fields (perk / Pack-a-Punch
  settings on), otherwise `EXE_CLIENT_FIELD_MISMATCH`.

### Render world (`t6gfx.py`)

Edits Nuketown's world in regions: streaming trees + leaf refs (BO1 negatives = static models, dropped); BSP planes,
nodes, cells (56 → 48 B), AABB trees (40 B both), portals (68 → 92 B: + bounds) and probe lists; vertices; brush
models (60 → 64 B); one tail region from the shadow lists to the surfaces (shadow lists emptied, light regions /
visibility data / static model instances copied); with `--materials` also the material list and new materials.

* Header pairs (BO1 → BO2): planes 0x08, nodes 0x0C, surfaces 0x10, streamInfo 0x14, cells 0x154/0x168 →
  0x174/0x188, draw 0x16C → 0x18C, vertices 0x208/0x20C → 0x1A8 (count) 0x1AC/0x1B0 (vd0 bytes/data), second stream
  0x1DC/0x1E0 (8 B per vertex, 128-aligned), indices 0x25C/0x260 → 0x204/0x208, models 0x2BC/0x2C0 → 0x274/0x278,
  world bounds 0x2C4 → 0x27C, materialMemory 0x2E0/0x2E4 → 0x298/0x29C, dpvs 0x3B0.. → 0x36C.. (sorted surfaces
  0x3BC, surfaces 0x3C4).
* BO2 world vertex (28 B): position 4 × s16 (xyz + binormal sign), color, uv half2, packed normal and tangent,
  lightmap uv 2 × unorm16. Positions are quantized per surface: `pos = q * scale + offset` (the surface's first vec4;
  Nuketown uses 0.25). Each surface gets its own copy of the vertices it uses (16-byte aligned groups, `vo0` = byte
  offset). BO1 indices are relative to the surface's first vertex.
* Surface 80 → 96 B: BO2 prepends the vec4; then mins + vo0, maxs + vo1, firstVertex, himip, vertexCount,
  triCount, baseIndex, material (alias to `&materialMemory[i].material`), lightmap/probe/light/flags, bounds.
* Materials must be quantized-world ones (`wq`/`wqc`, flags 0x30); `wpc` expects another vertex format.
* Alignment found the hard way: the tail's copied part holds 128-aligned data; dummy static surfaces (outside every
  draw range) pad the sorted list so the asset's change reaches a multiple of 4096. They carry a real material and no
  triangles: with a null material the renderer crashed in play (sub_828A72F0 reads material + 80 for each surface of
  a draw list; crash dumps: `dmp_stack.py` + `llvm-symbolizer` with `bo2zm.pdb`).
* Open: a second in-play crash, a memset to guest 0x20 (thread F800002C, game code), seen since the first render
  world build.

### Lightmaps (`t6lightmap.py`)

* BO2 (`pimp_shader_lmap`): one DXT5 image per lightmap with three tiles stacked vertically (v/3, +1/3, +2/3):
  ambient rgb/a, directional rgb/a, direction xyz*2-1. Nuketown's lightmap 0: 2048 × 3072 at block 3 + 0x16C000.
* BO1 (`pimp_shader_lmap` from Nacht's zone): secondaryB (16_16) X, Y * 31.875; secondary (5_6_5, top/bottom halves
  s1/s2: chroma in R/B, direction terms in G): a = s2.g*4-2, b = s1.g*4-2, w = saturate(0.4 + 0.6*2^-(a²+b²));
  R = 4X s1.r + 4wY s2.r, G = 2X(1-s1.r-s1.b) + 2wY(1-s2.r-s2.b), B = 4X s1.b + 4wY s2.b. The DXT1 primary (a
  shadow mask) isn't used by the basic world shader. Nacht: secondary at block 2 + 0x3F5000, secondaryB + 0x5F5000.
* First stage: all light into the ambient tile, black directional, up direction, written over Nuketown's lightmap 0.
* Image headers (BO1 0x9C, BO2 0xD4) share their first 0x50 bytes: D3D fetch constant at 0x1C (words byte-swapped:
  format = dword1 & 0x3F: 0x12 DXT1, 0x14 DXT4_5, 0x04 5_6_5, 0x19 16_16; size = dword2), data size 0x38, w/h 0x3C.
* `xenos_tex.py`: Xenos tiling, 8-in-16 swap, DXT/5_6_5 decode to PNG.
* Shaders: `tools/inspect/ff_shaders.py` (`find_shaders` also works on a decoded BO1 zone) and the kit's
  `bo2zm_hlsl.exe <in> <out> <shader_common.h>` translate them.

### Lighting (`splice_world.neutral_lighting`)

* BO2 GfxLightGrid at GfxWorld 0x22C: sunPrimaryLightIndex, mins/maxs (3 x u16 each), offset (float), rowAxis,
  colAxis, rowDataStart 0x248, rawRowData size/ptr 0x24C/0x250, entries 0x254/0x258 (4 B: u16 coeff index, primary
  light, visibility), colors 0x25C/0x260 (none in Nuketown), coeffs 0x264/0x268 (27 x u16 biased by 0x8000: 9 SH
  terms x rgb, DC first), sky grid volumes 0x26C/0x270. GfxWorld 0x104/0x108: sun primary light index, primary
  light count.
* ComWorld (com_map, asset type 14): header 16 B, name, then ComPrimaryLight records of 0xC4 B (type u8: 1 sun,
  2 spot, 5 omni; colour vec3 at +8). Nuketown's are cyan and green and placed in its coordinates.
* Reflection probes (GfxWorld 0x18C count, 0x190 array): 0x50 B each: origin, 12 floats of lighting terms (the
  first three an rgb balance, mean ~1), image 0x3C (-1: header follows; Nuketown's pixels stream from its ipak
  except `*reflection_probe0`, 0x18000 B inline), volumes, count, mip bias 0x4C. Cells list probe indices (bytes).
* What made Nacht dark and green: Nuketown's grid (blue-green, red ~30% low) lit models; surfaces and cells kept
  BO1's primary light and probe indices, which picked Nuketown's lights (green/cyan, overexposed walls) and probes
  (one is strongly green: the gun's tint). The probes' rgb balance terms were not the cause.
* For now: every grid sample is the same grey (`--grid-level`, default 0.3 x Nuketown's median), Nuketown's primary
  lights (sun included) are dark, surfaces use light 0 and surfaces and cells probe 0 (`--surface-lights` /
  `--surface-probes` keep BO1's indices; `--keep-lighting` skips the grid and lights). Lightmap gain 3 fits.

### Surface kinds (`t6mat.surface_kind`)

* BO1 material sort key (byte at +9): 4 opaque, 0x0C decals (chalk, stains, fences, papers), 0x0A/0x0B/0x0D/0x2B
  blend layers drawn over coplanar geometry, 5 sky, 0x11 water. Drawn as opaque world surfaces, blend layers and
  decals z-fight with the surface below (flicker) and sky surfaces show the sky texture as a wall.
* Now: decals clone `wqc/zm_nacht_dec_burntstain_01`, blend layers `wqc/wood_burned_blend` (Nuketown's records), and
  their surfaces get flags 0x2X (Nuketown's decal/blend surfaces; opaque 0x3X, low nibble kept); sky,
  `shadowcaster` and `caulk_shadow` surfaces get no triangles (BO2 draws the sky with its sky model). Nacht: 1,612
  opaque, 181 blend, 89 decal, 29 hidden. `--all-opaque` or `--kinds blend,decal` for comparisons.
* Loader alignment found with `asset_trace.py` + `T6GFX_TAIL_LOG`: material stateBits align to 8.

### Materials (`t6mat.py`)

* BO2 inline material: header 0x68 (temp block; counts at 0x4C: textures, constants, stateBits; technique set 0x54),
  name, textures (16 B: hash, name start/end, sampler, semantic 2 color / 5 normal / 8 specular, 0, image), inline
  images (header 0xD4 + name; pixels in block 3), constants (32 B), stateBits (8 B). BO1 texture entries are the same.
  Nuketown keeps pixels in the zone for only 4 of its 465 world materials (the rest stream from `.ipak`).
* New materials clone `wqc/wood_burned` (normal map reference kept, color map inline) and go after Nuketown's last
  material, before the world's outdoor image (file 0x3DC6299, block 5 0x3854A18; new pixels at block 3 0xBFF000).
  The zone builds and loads in the interpreter; every other asset keeps its footprint (asset 3120 differs only
  by 4 bytes of temp block, harmless).

### BO1 image packs (`pak2.py`, `lzo1x.py`)

* Most BO1 textures are streamed: of Nacht's 72 world color textures only a few have pixels in the zone. Packs: the
  disc's `images.pak` (2.2 GB, 45,833 entries; read in place from the ISO), `images_low.pak`, and per DLC
  `img_dlcN.pak` (Rezurrection: `img_dlc1.pak` 4,954 entries, `img_dlc5.pak` 1,542;
  `tools/inspect/stfs_extract.py <package> --only <name>`).
* Which pack: a part id's top byte is the pack type. Type 0 = `images`, 1 = `images_low` (opened at 0x82589400),
  2 = the patch pack; other types come from the map's `_load` zone, whose type 0x27 assets name a pack and its type:
  `zombie_cod5_prototype_load` -> `img_dlc1` type 3 (and `snd_dlc1`). Open: sub_8231E858; lookup: sub_8231D030.
* File (big endian): `pak2`, timestamp, u32 ?, count, sector size 0x800, data start, u32 ?; at 0x1C count x u32
  start sectors (absolute; -1 absent), then count x u16 sizes in sectors (low 15 bits; top bit 1 = compressed).
* Part: stored (flag 0) = the pixels as they are; compressed: u32 W (top bit a flag), zeros to W; at W: u32 0,
  compressed size, uncompressed size, then one **LZO1X** stream. Each part is one mip level, tiled and 8-in-16 like
  zone pixels. (The GPU job queued after a read, sub_825BE020, is only a memexport copy.)
* Streamed image header: size 0 and 1x1 at 0x38/0x3C (placeholders); at 0x54 up to 4 parts of 12 B: u32
  (cumulative offset << 4 | level), u16 w, u16 h, u32 part id. The fetch constant at 0x1C already has the full size;
  dword4 bits 6-9 = max mip level; dword5 = dimension, packed mips, mip address.
* `t6mat.streamed` takes the largest part as a one-level inline image: max mip 0, no mip address, size/w/h/levels
  at 0x38, pixel pointer -1. A streamed header's key can match an inline image's, so size 0 at 0x38 means streamed
  (an image with no pixels makes the loader align block 5 to 4096, which breaks the relocation).
* Open: parts under 128 pixels on a side (trims, chalk: 512×32, 32×512, 256×32, …) hold fewer bytes than a tiled
  surface of that size needs (512×32 DXT1: 0x2000 stored, 0x6800 addressed), so their layout is something else;
  they're padded to the full tiled size and will look wrong until that's decoded.
