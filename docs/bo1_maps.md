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

## Next

1. Convert Nacht's map zone. BO1 360 zones decode (Salsa20 with the flag-0 key from the BO1 executable, one shared
   200-entry IV table, deflate chunks up to `0xC000`). The T5 asset list then has to be rewritten as T6 assets:
   clipMap, ComWorld, GameWorld, GfxWorld, images, models, scripts. OpenAssetTools has T5 and T6 structures but no
   T6 writer for the world assets.
2. Nacht's own pin image (`menu_zm_map_signpost_*`) and start location map image.
3. The globe steps to Nacht from TranZit in the opposite direction to before. The order follows `GetMaps`; sort it
   by column 16 if it matters.
