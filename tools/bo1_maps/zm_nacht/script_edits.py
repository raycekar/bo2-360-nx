"""Make Nacht's map scripts from the game's own: decompiled maps/mp/zm_nacht.gsc and zm_nacht_standard.gsc (Nuketown's,
renamed with the map zone) are edited here, compiled with gsc-tool and written into zm_nacht_patch (inject_gsc.py).
No game script is stored in this repository; only these edits are.

usage: python -I script_edits.py <decompiled root> <out root>
       (the decompiled root holds maps/mp/zm_nacht.gsc and maps/mp/zm_nacht_standard.gsc, e.g. gsc-tool's
        decompiled/t6 from `gsc-tool -m decomp -g t6 -s xb2 <extracted scripts>`)
then:  gsc-tool -m comp -g t6 -s xb2 -w <decompiled root> <out root>

What changes: main() keeps BO2's Zombies setup and drops Nuketown's own features (rocket, bus, perks from the sky,
mannequins, signs, Easter eggs, its collision fixes); the zones are Nacht's (start, box room, upstairs: one door, two
debris piles); the magic box has Nacht's one location. A trace (dvar bo2zm_map_trace) reports how far startup got;
the app logs it as "[map script]"."""
import os
import re
import sys

MAIN = r'''map_trace( text )
{
    setdvar( "bo2zm_map_trace", text );
}

main()
{
    map_trace( "zm_nacht main" );
    level.level_createfx_callback_thread = ::createfx_callback;
    level.default_game_mode = "zstandard";
    level.default_start_location = "nacht";
    level.revive_machine_spawned = 0;
    level.riser_fx_on_client = 1;
    setup_rex_starts();
    maps\mp\zm_nacht_fx::main();
    maps\mp\zombies\_zm::init_fx();
    maps\mp\animscripts\zm_death::precache_gib_fx();
    level.zombiemode = 1;
    level._no_water_risers = 1;
    precacheshellshock( "default" );
    precacherumble( "damage_light" );
    precachemodel( "fx_axis_createfx" );
    maps\mp\zombies\_load::main();

    if ( getdvar( #"createfx" ) == "1" )
        return;

    maps\mp\teams\_teamset_cdc::level_init();
    maps\mp\gametypes_zm\_spawning::level_use_unified_spawning( 1 );
    level.givecustomloadout = ::givecustomloadout;
    level.precachecustomcharacters = ::precache_team_characters;
    level.givecustomcharacters = ::give_team_characters;
    initcharacterstartindex();
    level.custom_player_fake_death = ::nacht_player_fake_death;
    level.custom_player_fake_death_cleanup = ::nacht_player_fake_death_cleanup;
    level.initial_round_wait_func = ::initial_round_wait_func;
    level.ignore_path_delays = 1;
    level.calc_closest_player_using_paths = 1;
    level.melee_miss_func = ::melee_miss_func;
    level.zombie_init_done = ::zombie_init_done;
    level._zombie_path_timer_override = ::zombie_path_timer_override;
    level.taser_trig_adjustment = ( -7, -2, 0 );
    // the client scripts are still Nuketown's: these settings decide which client fields the server registers, so
    // they stay as Nuketown has them (a mismatch disconnects with EXE_CLIENT_FIELD_MISMATCH)
    level.zombiemode_using_perk_intro_fx = 1;
    level.zombiemode_using_pack_a_punch = 1;
    level.zombiemode_reusing_pack_a_punch = 1;
    level.pap_interaction_height = 47;
    level.zombiemode_using_doubletap_perk = 1;
    level.zombiemode_using_juggernaut_perk = 1;
    level.zombiemode_using_revive_perk = 1;
    level.zombiemode_using_sleightofhand_perk = 1;
    level.register_offhand_weapons_for_level_defaults_override = ::offhand_weapon_overrride;
    level.zombiemode_offhand_weapon_give_override = ::offhand_weapon_give_override;
    level._zombie_custom_add_weapons = ::custom_add_weapons;
    level._allow_melee_weapon_switching = 1;
    level.custom_ai_type = [];
    level.raygun2_included = 1;
    include_weapons();
    include_powerups();
    include_equipment_for_level();
    registerclientfield( "world", "zombie_eye_change", 4000, 1, "int" );
    maps\mp\zombies\_zm::init();
    level thread maps\mp\_sticky_grenade::init();
    maps\mp\zombies\_zm_weap_tazer_knuckles::init();
    maps\mp\zombies\_zm_weap_bowie::init();
    level.legacy_cymbal_monkey = 1;
    maps\mp\zombies\_zm_weap_cymbal_monkey::init();
    maps\mp\zombies\_zm_weap_claymore::init();
    maps\mp\zombies\_zm_weap_ballistic_knife::init();
    level.special_weapon_magicbox_check = ::nacht_special_weapon_magicbox_check;
    precacheitem( "death_throe_zm" );
    level.zones = [];
    level.zone_manager_init_func = ::nacht_zone_init;
    init_zones[0] = "start_zone";
    level thread maps\mp\zombies\_zm_zonemgr::manage_zones( init_zones );
    level.zombie_ai_limit = 24;
    level thread sndswitchannouncervox( "sam" );
    setdvar( "zombiemode_path_minz_bias", 28 );
    level.speed_change_round = 15;
    level.speed_change_max = 5;
    level thread nacht_trace_progress();
    map_trace( "zm_nacht main done" );
}

nacht_trace_progress()
{
    flag_wait( "start_zombie_round_logic" );
    map_trace( "zombie round logic started, spawners " + level.zombie_spawners.size );
    level waittill( "start_of_round" );
    map_trace( "round " + level.round_number + " started" );
}
'''

ZONES = '''nacht_zone_init()
{
    flag_init( "always_on" );
    flag_set( "always_on" );
    add_adjacent_zone( "start_zone", "box_zone", "start_2_box" );
    add_adjacent_zone( "start_zone", "upstairs_zone", "start_2_upstairs" );
    add_adjacent_zone( "box_zone", "upstairs_zone", "box_2_upstairs" );
}
'''

CHESTS = '''nacht_treasure_chest_init()
{
    level.chests = [];
    level.chests[0] = getstruct( "start_chest", "script_noteworthy" );
    maps\\mp\\zombies\\_zm_magicbox::treasure_chest_init( "start_chest" );
}
'''


def replace_function(text, name, new):
    """Replace a top-level function (its name at the start of a line, up to the first '}' at the start of a line)."""
    m = re.search(rf"^{name}\(.*?^\}}\n", text, re.S | re.M)
    if not m:
        raise SystemExit(f"function {name} not found")
    return text[:m.start()] + new + text[m.end():]


def main():
    src, out = sys.argv[1:3]
    os.makedirs(os.path.join(out, "maps", "mp"), exist_ok=True)
    path = os.path.join("maps", "mp", "zm_nacht.gsc")
    text = open(os.path.join(src, path), encoding="latin-1").read().replace("\r\n", "\n")
    text = replace_function(text, "main", MAIN)
    text = replace_function(text, "nacht_zone_init", ZONES)
    open(os.path.join(out, path), "w", encoding="latin-1", newline="\n").write(text)
    path = os.path.join("maps", "mp", "zm_nacht_standard.gsc")
    text = open(os.path.join(src, path), encoding="latin-1").read().replace("\r\n", "\n")
    text = replace_function(text, "nacht_treasure_chest_init", CHESTS)
    open(os.path.join(out, path), "w", encoding="latin-1", newline="\n").write(text)
    print("wrote", out)


if __name__ == "__main__":
    main()
