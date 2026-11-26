"""Translate Nacht der Untoten's BO1 entity string into the entities BO2's Zombies scripts read.

usage: python -I nacht_ents.py <nacht ents.txt> <nuketown ents.txt> <out ents.txt> <out aliases.json>

Both inputs are the plain entity strings of the decoded zones (BO1 zombie_cod5_prototype, BO2 zm_nuked); nothing from
either game is stored here. The aliases file maps BO1 script strings to strings that already exist in the BO2 zone
(splice_world.py uses it for the path nodes, so the nodes and their entities agree).

Kept from Nacht: player starts, intermission cameras, path nodes, zone volumes, door/debris triggers and their brush
models, static brush models. Window boards, BO1 script models, lights, audio and easter-egg triggers are dropped
(their models and scripts do not exist in BO2). Rewritten: zombie spawners become spawn-location structs, wall
weapons become BO2 wallbuy structs, the mystery box becomes a BO2 MagicBox zbarrier. From Nuketown: worldspawn and
lights (the render world is still Nuketown's), the zombie/dog spawner entities, mp_global_intermission."""
import json
import re
import sys

LOCATION = "zstandard_nacht"
ZONES = ("start_zone", "box_zone", "upstairs_zone")
SPAWNER_ZONE = {"start_zone_spawners": "start_zone_spawners", "box_zone_spawners": "box_zone_spawners",
                "upstairs_zone_spawners": "upstairs_zone_spawners", "zombie_spawner_door": "box_zone_spawners"}
# BO1 wall weapon -> (BO2 weapon, BO2 wall model): weapons and models Nuketown's zone already has
WALLBUYS = {
    "zombie_kar98k": ("m14_zm", "t6_wpn_ar_m14_world"),
    "zombie_m1carbine": ("beretta93r_zm", "t6_wpn_pistol_b2023r_world"),
    "zombie_thompson": ("mp5k_zm", "t6_wpn_smg_mp5_world"),
    "zombie_doublebarrel": ("rottweil72_zm", "t6_wpn_shotty_olympia_world"),
    "zombie_doublebarrel_sawed": ("ak74u_zm", "t6_wpn_smg_ak74u_world"),
    "zombie_shotgun": ("870mcs_zm", "t6_wpn_shotty_870mcs_world"),
    "zombie_bar": ("m16_zm", "t6_wpn_ar_m16a2_world"),
    "stielhandgranate": ("sticky_grenade_zm", "semtex_bag"),
}
ANIMSCRIPTS = {"zombie_mantle_over_40": "zm_mantle_over_40"}


def parse(txt):
    return [dict(re.findall(r'"([^"]*)" "([^"]*)"', b)) for b in re.findall(r"\{(.*?)\}", txt, re.S)]


def write(ents):
    return "".join("{\n" + "".join(f'"{k}" "{v}"\n' for k, v in e.items()) + "}\n" for e in ents)


def main():
    nacht = parse(open(sys.argv[1], encoding="latin-1").read())
    # the map zone is Nuketown's with "nuked" renamed to "nacht" (same length): its asset names say nacht
    nuked = parse(open(sys.argv[2], encoding="latin-1").read().replace("nuked", "nacht"))
    by_target = {}
    for e in nacht:
        if "targetname" in e:
            by_target.setdefault(e["targetname"], []).append(e)
    out, aliases = [], dict(ANIMSCRIPTS)

    # Nuketown entities the engine and the common scripts need
    for e in nuked:
        c = e["classname"]
        if c == "worldspawn" or c == "light" or c.startswith("actor_"):
            out.append(e)
    intermission = next(e for e in nacht if e["classname"] == "info_intermission")
    out.append({"classname": "mp_global_intermission", "origin": intermission["origin"],
                "angles": intermission.get("angles", "0 0 0")})

    # negotiation (traversal) pairs: reuse Nuketown's names, which are in the zone's script string list
    nuked_neg = [e["targetname"] for e in nuked if e["classname"] == "node_negotiation_end"]
    nacht_neg = [e["targetname"] for e in nacht if e["classname"] == "node_negotiation_end"]
    for i, name in enumerate(nacht_neg):
        aliases[name] = nuked_neg[i]

    boards = set()
    for e in nacht:  # window boards: what the exterior_goal structs target
        if e.get("targetname") == "exterior_goal" and "target" in e:
            boards.add(e["target"])
    for e in nacht:  # wall weapon chalk: what the weapon models on the wall target (BO1 materials, no BO2 model)
        if e["classname"] == "trigger_use" and e.get("targetname") == "weapon_upgrade":
            for shown in by_target.get(e.get("target", ""), []):
                if "target" in shown:
                    boards.add(shown["target"])
    wallbuy = 0
    for e in nacht:
        c, t = e["classname"], e.get("targetname", "")
        if c in ("info_player_start", "info_intermission", "info_volume"):
            out.append(e)
        elif c.startswith("node_"):
            n = dict(e)
            for k in ("targetname", "target", "animscript"):
                if n.get(k) in aliases:
                    n[k] = aliases[n[k]]
            out.append(n)
        elif c == "script_brushmodel":
            if t in boards or t.endswith("_chalk") or t == "mature_blood":
                continue
            n = dict(e)
            if n.get("target") == "zombie_spawner_door":
                del n["target"]
            out.append(n)
        elif c in ("trigger_use", "trigger_use_touch") and t in ("zombie_debris", "zombie_door"):
            out.append(e)
        elif c == "script_struct" and t == "initial_spawn_points":
            n = dict(e, script_noteworthy="initial_spawn", script_string=LOCATION)
            out.append(n)
        elif c == "script_struct" and (t == "intermission" or re.fullmatch(r"auto(5[89]|6[0-5])", t)):
            out.append(e)
        elif c.startswith("actor_zombie"):
            out.append({"classname": "script_struct", "targetname": SPAWNER_ZONE[t], "origin": e["origin"],
                        "angles": e.get("angles", "0 0 0"), "script_noteworthy": "spawn_location",
                        "script_string": "find_flesh"})
        elif c == "trigger_use" and t == "weapon_upgrade":
            weapon, model = WALLBUYS[e["zombie_weapon_upgrade"]]
            shown = by_target.get(e.get("target", ""), [e])[0]  # the BO1 weapon model on the wall
            wallbuy += 1
            name = f"nacht_wallbuy_{wallbuy}"
            out.append({"classname": "script_struct", "targetname": "weapon_upgrade", "zombie_weapon_upgrade": weapon,
                        "origin": shown["origin"], "angles": shown.get("angles", "0 0 0"), "target": name})
            out.append({"classname": "script_struct", "targetname": name, "model": model, "origin": shown["origin"],
                        "angles": shown.get("angles", "0 0 0")})
        elif c == "script_origin" and t == "chest_origin":
            box = next(n for n in nuked if n.get("script_noteworthy") == "start_chest1_zbarrier")
            out.append({"classname": "script_struct", "targetname": "treasure_chest_use",
                        "script_noteworthy": "start_chest", "zombie_cost": "950", "origin": e["origin"],
                        "angles": e["angles"]})
            out.append(dict(box, script_noteworthy="start_chest_zbarrier", origin=e["origin"], angles=e["angles"]))

    # one respawn point per zone; players come back at the start room's spawn structs
    start = next(e for e in nacht if e["classname"] == "info_player_start")
    for zone in ZONES:
        out.append({"classname": "script_struct", "targetname": "player_respawn_point", "script_noteworthy": zone,
                    "script_string": LOCATION, "target": "initial_spawn_points", "origin": start["origin"],
                    "angles": start.get("angles", "0 0 0"), "radius": "1000", "script_int": "1000"})
    for e in out:
        e.pop("guid", None)
    text = write(out)
    open(sys.argv[3], "w", encoding="latin-1", newline="\n").write(text)
    json.dump(aliases, open(sys.argv[4], "w"), indent=1)
    kinds = {}
    for e in out:
        kinds[e["classname"]] = kinds.get(e["classname"], 0) + 1
    print(len(out), "entities,", len(text), "bytes,", wallbuy, "wall weapons;", kinds)


if __name__ == "__main__":
    main()
