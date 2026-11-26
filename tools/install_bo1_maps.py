"""Installs the Black Ops 1 maps add-on (optional, experimental): BO1 maps in BO2 Zombies, "BO1 map, BO2 gameplay".

Status: Nacht der Untoten shows on the Zombies globe and its start location menu works; the map itself is not
converted yet (starting it reports the missing maps/mp/zm_nacht.d3dbsp). See docs/bo1_maps.md.

A BO1 map arrives as a DLC pack in BO2's unused fifth slot ("dlc5": map pack index 7), laid out the way
tools/install_dlc.py lays out the retail packs:
  <content>/00000002/<pack>/dlc5.id            makes the slot owned
  <content>/00000002/<pack>/dlc5_load_zm.ff    the map's rows for zm/mapsTable.csv and zm/gametypesTable.csv and its
                                               text, merged into the game's own tables at run time (bo2zm_dlc.cpp)
  <content>/Headers/00000002/<pack>.header
and the setting bo2zm_custom_maps = true is added to bo2zm.toml (it lets the game load the pack's unsigned zone and
list the map). Nothing from the game is shipped: the rows and text in tools/bo1_maps/<map>/ are this project's own,
and the zone is encrypted with the key rebuilt from your decrypted game (never written anywhere).

usage: python -I tools/install_bo1_maps.py --game <game folder: bo2zm.toml, update/> --content <user root>/
       0000000000000000/415608C3 [--image work/dump_tu18/default_mp.image.bin] [--remove]
"""
import argparse
import csv
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "bo1_maps"))
import t6zone  # noqa: E402

PACK = "FFFF000000000000000000000000000000DC5BO141"  # sorts after the retail packs: they mount first
TITLE_ID, MARKETPLACE = 0x415608C3, 0x00000002
MAPS = ["zm_nacht"]
CAPACITY = {"zm/mapstable.csv": 64, "zm/gametypestable.csv": 128}  # room for the game's rows plus ours


def header(display, file_name):
    """XCONTENT_AGGREGATE_DATA (device, type, UTF-16 display name, file name, title id) and the license mask."""
    out = struct.pack(">II", 1, MARKETPLACE) + display.encode("utf-16-be")[:256].ljust(256, b"\0")
    out += file_name.encode()[:42].ljust(0x140 - 0x108, b"\0")
    return out + struct.pack(">II", TITLE_ID, 0) + struct.pack("<I", 0x100)


def rows(path):
    with open(path, newline="") as f:
        return [r for r in csv.reader(f) if r]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--game", required=True, help="the game folder (bo2zm.toml, update/)")
    ap.add_argument("--content", required=True, help="<user root>/0000000000000000/415608C3")
    ap.add_argument("--image", default=os.path.join(HERE, "..", "work", "dump_tu18", "default_mp.image.bin"))
    ap.add_argument("--remove", action="store_true", help="uninstall: remove the pack and turn the setting off")
    a = ap.parse_args()
    pack_dir = os.path.join(a.content, "%08X" % MARKETPLACE, PACK)
    header_path = os.path.join(a.content, "Headers", "%08X" % MARKETPLACE, PACK + ".header")
    toml = os.path.join(a.game, "bo2zm.toml")
    text = open(toml, encoding="utf-8").read() if os.path.exists(toml) else ""
    lines = [l for l in text.splitlines() if not l.strip().startswith("bo2zm_custom_maps")]
    if a.remove:
        shutil.rmtree(pack_dir, ignore_errors=True)
        if os.path.exists(header_path):
            os.remove(header_path)
        open(toml, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print("removed the Black Ops 1 maps pack; bo2zm_custom_maps is off")
        return
    tables = {name: [] for name in CAPACITY}
    texts = []
    for m in MAPS:
        d = os.path.join(HERE, "bo1_maps", m)
        tables["zm/mapstable.csv"] += rows(os.path.join(d, "mapstable.csv"))
        tables["zm/gametypestable.csv"] += rows(os.path.join(d, "gametypes.csv"))
        texts += [tuple(l.rstrip("\r\n").split("=", 1)) for l in open(os.path.join(d, "text.txt"), encoding="latin-1")
                  if "=" in l]
    auth_from = os.path.join(a.game, "update", "en_patch_loc_zm.ff")  # any retail fastfile: its auth block layout
    body = t6zone.zone([(n, r, CAPACITY[n]) for n, r in tables.items()], texts)
    ff = t6zone.fastfile(body, "dlc5_load_zm", a.image, auth_from)
    os.makedirs(pack_dir, exist_ok=True)
    os.makedirs(os.path.dirname(header_path), exist_ok=True)
    open(os.path.join(pack_dir, "dlc5_load_zm.ff"), "wb").write(ff)
    open(os.path.join(pack_dir, "dlc5.id"), "wb").write(b"// dlc5 \r\n")
    open(header_path, "wb").write(header("Black Ops 1 Maps", PACK))
    lines += ["", "# Black Ops 1 maps add-on (tools/install_bo1_maps.py)", "bo2zm_custom_maps = true"]
    open(toml, "w", encoding="utf-8").write("\n".join(lines).rstrip("\n").replace("\n\n\n", "\n\n") + "\n")
    print(f"installed the Black Ops 1 maps pack ({', '.join(MAPS)}): {pack_dir}")


if __name__ == "__main__":
    main()
