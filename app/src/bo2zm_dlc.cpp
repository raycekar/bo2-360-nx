// DLC map packs: no NEW badge on the Zombies globe.
//
// The globe and start-location menus (Lua in the title update's patch_ui_zm.ff: SeenStartMap, SeenStartLocation,
// SeenGameModeMap, SawGameModeMap in SelectStartLocZombie) keep one bit per map, start location and mode in the
// profile setting unlock_crumbs_zm, and draw a NEW icon for every combination whose bit is clear; opening one sets its
// bit. Installed DLC maps (tools/install_dlc.py) therefore all start as NEW. Measured on the PC: with the setting at
// 16777215 (24 bits set) no map on the globe shows NEW, so every combination's bit is below bit 24.
//
// The profile setter behind the game's "setprofile" console command does nothing until that controller's profile is
// loaded: it first checks a byte at 0x836BAE58 + 2000 + controller * 2008 (one 2008-byte block per controller). So the
// per-frame hook watches that byte and, each time a profile finishes loading, runs "setprofile unlock_crumbs_zm
// 16777215" for that controller with the game's own text runner.

#include "bo2zm_dlc.h"

#include <atomic>
#include <cstring>
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

#include <rex/cvar.h>
#include <rex/hook.h>
#include <rex/logging.h>
#include <rex/runtime.h>
#include <rex/system/xmemory.h>
#include <rex/types.h>

#include <string>
#include <string_view>

#include "bo2zm_autoexec.h"
#include "bo2zm_guest.h"

// Custom maps (Black Ops 1 maps converted by tools/install_bo1_maps.py), off unless that installer turned the setting
// on. Such a map arrives as a DLC pack in the unused fifth slot (dlc5.id: map pack index 7) whose load zone,
// dlc5_load_zm.ff, holds the new rows for zm/mapsTable.csv and zm/gametypesTable.csv and the map's text.
REXCVAR_DEFINE_BOOL(bo2zm_custom_maps, false, "BO2",
                    "Custom maps (tools/install_bo1_maps.py): load unsigned zones and merge their map rows");

// The zone signature check, TU18 sub_822AA8D0: find_hash("sha256"), import the zone RSA key, then rsa_verify_hash over
// the stream's final hash blocks (state 0x82CBC578 + 0x14C) against the signature from the PHEEBs71 auth header
// (state + 0x4C). On success it sets bit 0x80 in the zone's status word (state + 0x3FE8 + [state + 0x4940] * 0x12C) and
// returns 1. Its caller sub_822AA9F0 marks a failure with bit 0x20, after which loading the zone's assets crashes (a
// NULL XAsset in sub_822A9780). A zone we write has no valid signature, so with the setting on a failed check is
// reported as a pass, exactly as the success path leaves the state.
//
// The map list behind the Zombies globe (Lua GetMaps) is built by sub_8244E4C8 from the maps table, and the start
// locations (Lua GetStartLocsZombie, count at 0x83BAF574) by sub_8244E790, called from the game types parser
// sub_8244EAB8. Both run at startup and on PLATFORM_DOWNLOADABLE_CONTENT_CHANGED, before any DLC load zone is loaded,
// so once a custom zone is linked its rows are merged in and both parsers run again.
REX_EXTERN(__imp__sub_8244E4C8);
REX_EXTERN(__imp__sub_8244EAB8);
REX_EXTERN(__imp__sub_822CAE50);  // DB_FindXAssetHeader(type, name, errorIfMissing, wait)
namespace {
std::atomic<int> g_reparse_maps{0};  // frames until the custom rows are merged and the tables parsed again (0 = idle)
std::atomic<bool> g_published{false};
constexpr uint32_t kMapCount = 0x83BB53FC, kMapOwnedCount = 0x83BB5400, kMapEntries = 0x83BB5460, kMapStride = 0x70;
constexpr uint32_t kStartLocCount = 0x83BAF574;
}  // namespace

REX_EXTERN(__imp__sub_822AA8D0);
REX_HOOK_RAW(sub_822AA8D0) {
  __imp__sub_822AA8D0(ctx, base);
  if (ctx.r3.u32 != 0 || !REXCVAR_GET(bo2zm_custom_maps)) {
    return;
  }
  constexpr uint32_t kZoneState = 0x82CBC578;
  const uint32_t slot = rex::byte_swap(*reinterpret_cast<uint32_t*>(base + kZoneState + 0x4940));
  uint32_t* status = reinterpret_cast<uint32_t*>(base + kZoneState + 0x3FE8 + slot * 0x12C);
  *status = rex::byte_swap(rex::byte_swap(*status) | 0x80u);
  std::string zone_name;  // the longest text in the slot's 0x12C-byte entry (the zone's name)
  for (uint32_t k = 0; k < 0x12C; ++k) {
    const char* s = reinterpret_cast<const char*>(base + kZoneState + 0x3FE8 + slot * 0x12C + k);
    size_t n = 0;
    while (n < 64 && k + n < 0x12C && s[n] >= 0x20 && s[n] < 0x7F) ++n;
    if (n > zone_name.size() && (k + n >= 0x12C || s[n] == 0)) zone_name.assign(s, n);
    k += n;
  }
  REXLOG_INFO("[dlc] zone signature does not verify: accepted as a custom zone (slot {}, '{}')", slot, zone_name);
  ctx.r3.u64 = 1;
  g_reparse_maps = 10;  // a few frames: the zone's assets are linked by then
}

namespace {

uint32_t Be32(const uint8_t* base, uint32_t a) { return rex::byte_swap(*reinterpret_cast<const uint32_t*>(base + a)); }
void SetBe32(uint8_t* base, uint32_t a, uint32_t v) { *reinterpret_cast<uint32_t*>(base + a) = rex::byte_swap(v); }
const char* GuestText(uint8_t* base, uint32_t a) { return reinterpret_cast<const char*>(base + a); }
bool SameName(const char* a, const char* b) {  // asset names are case-insensitive (the game asks for "zm/mapsTable.csv")
  for (; *a && *b; ++a, ++b) {
    if (std::tolower(static_cast<unsigned char>(*a)) != std::tolower(static_cast<unsigned char>(*b))) {
      return false;
    }
  }
  return *a == *b;
}

bool GuestReadable(uint8_t* base, uint32_t address) {
#if defined(_WIN32)
  MEMORY_BASIC_INFORMATION info{};
  if (!VirtualQuery(base + address, &info, sizeof(info)) || info.State != MEM_COMMIT) {
    return false;
  }
  const auto end = reinterpret_cast<uintptr_t>(info.BaseAddress) + info.RegionSize;
  return end - reinterpret_cast<uintptr_t>(base + address) >= 256 &&
         (info.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE)) != 0;
#else
  (void)base;
  (void)address;
  return false;
#endif
}

// The game's string table cell hash (OpenAssetTools Common::Com_HashString for T6): djb2 over lower case.
int32_t CellHash(const char* s) {
  uint32_t h = 5381;
  for (; *s; ++s) {
    const unsigned char c = static_cast<unsigned char>(*s);
    h = h * 33 + ((c >= 'A' && c <= 'Z') ? c | 0x20 : c);
  }
  return static_cast<int32_t>(h);
}

// Merges a custom zone's copy of a string table into the game's own. A zone loaded later does not replace an asset
// that is already registered (DB_FindXAssetHeader keeps returning the first one), and the custom copy carries only
// the new rows, so no game data is shipped. Its layout, written by tools/install_bo1_maps.py:
//   rows to append, rows "=<key>,..." that replace the cells of the game's row <key> (counts such as maxnum_map),
//   then empty rows (column 0 empty): room for the game's rows, which are copied in front of ours.
//   A cell "@<key>+<n>" becomes the number in column 1 of the game's row <key> plus n, written over the placeholder.
// The StringTable pool is an array of 20-byte headers {name, columnCount, rowCount, values, cellIndex}; the custom
// copy sits further along in it. The merged table is written into the custom copy's arrays and its header is copied
// over the registered one, so every lookup of the name sees it.
std::vector<uint32_t> g_merged;  // custom tables already merged (their values arrays)

void MergeStringTable(PPCContext& ctx, uint8_t* base, const char* name) {
  constexpr uint32_t kTypeStringTable = 0x2B, kHeader = 20, kScan = 1024, kCell = 8;
  const auto saved = ctx;
  const uint32_t text = (ctx.r1.u32 - 1024) & ~uint32_t(0xF);
  std::strcpy(reinterpret_cast<char*>(base + text), name);
  ctx.r1.u64 = (text - 256) & ~uint64_t(0xF);
  ctx.r3.u64 = kTypeStringTable;
  ctx.r4.u64 = text;
  ctx.r5.u64 = 0;  // no error when missing
  ctx.r6.u64 = 0;
  __imp__sub_822CAE50(ctx, base);
  const uint32_t registered = ctx.r3.u32;
  ctx = saved;
  if (registered < 0x80000000u) {
    return;
  }
  const uint32_t cols = Be32(base, registered + 4);
  uint32_t custom = 0;
  for (uint32_t i = 1; i <= kScan; ++i) {
    const uint32_t h = registered + i * kHeader;
    const uint32_t n = Be32(base, h);
    // Free pool slots hold stale or link pointers: only a header with the same column count whose name is in
    // committed memory is read (reading an unmapped guest page crashed the game).
    if (n < 0x80000000u || n >= 0xF0000000u || Be32(base, h + 4) != cols || !GuestReadable(base, n)) {
      continue;
    }
    if (SameName(GuestText(base, n), name)) {
      custom = h;  // the last one wins: the most recently loaded zone
    }
  }
  if (!custom) {
    return;
  }
  const uint32_t values = Be32(base, custom + 12), index = Be32(base, custom + 16), capacity = Be32(base, custom + 8);
  for (const uint32_t done : g_merged) {
    if (done == values) {
      return;
    }
  }
  const uint32_t game_rows = Be32(base, registered + 8), game_values = Be32(base, registered + 12);
  auto cell_text = [&](uint32_t vals, uint32_t row, uint32_t col) {
    return GuestText(base, Be32(base, vals + (row * cols + col) * kCell));
  };
  auto game_row = [&](const char* key) -> int {
    for (uint32_t r = 0; r < game_rows; ++r) {
      if (std::strcmp(cell_text(game_values, r, 0), key) == 0) {
        return int(r);
      }
    }
    return -1;
  };
  // Our rows, with their placeholders resolved against the game's table.
  std::vector<uint32_t> append, replace;
  for (uint32_t r = 0; r < capacity && cell_text(values, r, 0)[0] != 0; ++r) {
    for (uint32_t c = 0; c < cols; ++c) {
      const uint32_t cell = values + (r * cols + c) * kCell;
      char* s = reinterpret_cast<char*>(base + Be32(base, cell));
      if (s[0] == '@') {
        std::string key(s + 1);
        int add = 0;
        if (const auto plus = key.find('+'); plus != std::string::npos) {
          add = std::atoi(key.c_str() + plus + 1);
          key.resize(plus);
        }
        const int row = game_row(key.c_str());
        const int number = (row < 0 ? 0 : std::atoi(cell_text(game_values, uint32_t(row), 1))) + add;
        const std::string digits = std::to_string(number);
        if (digits.size() <= std::strlen(s)) {
          std::memcpy(s, digits.c_str(), digits.size() + 1);
        }
      }
      SetBe32(base, cell + 4, uint32_t(CellHash(s)));
    }
    (cell_text(values, r, 0)[0] == '=' ? replace : append).push_back(r);
  }
  const uint32_t rows = game_rows + uint32_t(append.size());
  if (rows > capacity) {
    REXLOG_WARN("[dlc] string table '{}': {} game rows + {} custom rows do not fit in {}", name, game_rows,
                append.size(), capacity);
    return;
  }
  // Copy our rows aside, the game's rows to the front, ours after them; "=" rows overwrite the game row's cells.
  std::vector<uint8_t> ours(capacity * cols * kCell);
  std::memcpy(ours.data(), base + values, ours.size());
  std::memcpy(base + values, base + game_values, game_rows * cols * kCell);
  for (size_t i = 0; i < append.size(); ++i) {
    std::memcpy(base + values + (game_rows + i) * cols * kCell, ours.data() + append[i] * cols * kCell, cols * kCell);
  }
  for (const uint32_t r : replace) {
    const char* key = GuestText(base, rex::byte_swap(*reinterpret_cast<uint32_t*>(ours.data() + r * cols * kCell)));
    const int row = game_row(key + 1);
    if (row >= 0) {  // keep the game's key cell, take the rest
      std::memcpy(base + values + (uint32_t(row) * cols + 1) * kCell, ours.data() + (r * cols + 1) * kCell,
                  (cols - 1) * kCell);
    }
  }
  // The lookup index: every cell, sorted by hash and then column.
  std::vector<uint16_t> order(rows * cols);
  for (uint32_t i = 0; i < order.size(); ++i) {
    order[i] = uint16_t(i);
  }
  auto hash_of = [&](uint32_t i) { return int32_t(Be32(base, values + i * kCell + 4)); };
  std::stable_sort(order.begin(), order.end(), [&](uint16_t a, uint16_t b) {
    const int32_t ha = hash_of(a), hb = hash_of(b);
    return ha != hb ? ha < hb : (a % cols) < (b % cols);
  });
  for (uint32_t i = 0; i < order.size(); ++i) {
    *reinterpret_cast<uint16_t*>(base + index + i * 2) = rex::byte_swap(order[i]);
  }
  SetBe32(base, custom + 8, rows);
  std::memcpy(base + registered, base + custom, kHeader);
  g_merged.push_back(values);
  REXLOG_INFO("[dlc] string table '{}': {} custom rows merged into the game's {} ({} replaced)", name, append.size(),
              game_rows, replace.size());
}

// A map zone gets its "<map>_patch" zone only if its name is in the zone loader's table at 0x8296EBD8 (sub_822CB500):
// ten zone names, then ten {patch zone name, 1} pairs. Entry 0 is common_mp (a Multiplayer zone, never loaded in
// Zombies): point it and its pair at a custom map's names, in guest memory of our own.
void RegisterPatchZone(uint8_t* base, const char* map) {
  constexpr uint32_t kZones = 0x8296EBD8, kPairs = kZones + 10 * 4;
  if (std::strcmp(GuestText(base, Be32(base, kZones)), "common_mp") != 0) {
    return;  // not the TU18 table, or already taken
  }
  const std::string patch = std::string(map) + "_patch";
  const uint32_t text = rex::Runtime::instance()->memory()->SystemHeapAlloc(64, 16);
  if (!text) {
    return;
  }
  std::memcpy(base + text, map, std::strlen(map) + 1);
  std::memcpy(base + text + 32, patch.c_str(), patch.size() + 1);
  SetBe32(base, kZones, text);
  SetBe32(base, kPairs, text + 32);
  REXLOG_INFO("[dlc] {} gets its patch zone {}", map, patch);
}

void ReparseMapsTable(PPCContext& ctx, uint8_t* base) {
  MergeStringTable(ctx, base, "zm/mapsTable.csv");
  MergeStringTable(ctx, base, "zm/gametypesTable.csv");
  const auto saved = ctx;
  ctx.r1.u64 = (ctx.r1.u32 - 1024) & ~uint64_t(0xF);
  __imp__sub_8244E4C8(ctx, base);
  ctx = saved;
  ctx.r1.u64 = (ctx.r1.u32 - 1024) & ~uint64_t(0xF);
  __imp__sub_8244EAB8(ctx, base);  // game types and the start location list (sub_8244E790)
  ctx = saved;
  const uint32_t count = Be32(base, kMapCount);
  REXLOG_INFO("[dlc] maps parsed again: {} maps ({} owned), {} start locations", count, Be32(base, kMapOwnedCount),
              Be32(base, kStartLocCount));
  for (uint32_t i = 0; i < count && i < 32; ++i) {
    const uint32_t entry = kMapEntries + i * kMapStride;
    REXLOG_INFO("[dlc]   map {}: '{:.24s}' pack index {}", i, GuestText(base, entry - 0x3C), Be32(base, entry + 0x10));
  }
}

}  // namespace

REXCVAR_DEFINE_BOOL(bo2zm_dlc_maps_seen, true, "BO2",
                    "Marks every Zombies map, start location and mode as already seen in each profile when it loads, "
                    "so installed DLC maps show no NEW badge on the globe");

namespace {

constexpr uint32_t kProfileBlocks = 0x836BAE58;
constexpr uint32_t kProfileBlockSize = 2008;
constexpr uint32_t kProfileLoaded = 2000;  // byte: the profile of that controller is loaded
constexpr int kControllers = 4;
constexpr const char* kAllSeen = "setprofile unlock_crumbs_zm 16777215";

bool g_applied[kControllers] = {};

}  // namespace

// A custom map's scripts report progress in the dvar bo2zm_map_trace (setdvar); log each new value, since the game
// prints its own script errors only in developer builds. Read every frame: FindDvar, then the dvar's string.
static void TraceMapScripts(PPCContext& ctx, uint8_t* base) {
  static uint32_t name = 0;
  static std::string last;
  if (!name) {
    name = rex::Runtime::instance()->memory()->SystemHeapAlloc(32, 16);
    if (!name) return;
    std::strcpy(reinterpret_cast<char*>(base + name), "bo2zm_map_trace");
  }
  const auto saved = ctx;
  ctx.r1.u64 = (ctx.r1.u32 - 512) & ~15u;
  ctx.r3.u64 = name;
  bo2zm::guest::Call<0x82496430>(ctx, base);  // dvar by name
  const auto dvar = ctx.r3.u32;
  uint32_t text = 0;
  if (dvar) {
    ctx.r1.u64 = (saved.r1.u32 - 512) & ~15u;
    ctx.r3.u64 = dvar;
    bo2zm::guest::Call<0x82496990>(ctx, base);  // its current string
    text = ctx.r3.u32;
  }
  ctx = saved;
  if (text < 0x1000 || text > 0xFFFFFF00u) return;
  const char* s = reinterpret_cast<const char*>(base + text);
  size_t n = 0;
  while (n < 200 && s[n]) ++n;
  if (n == 200 || last == std::string_view(s, n)) return;
  last.assign(s, n);
  REXLOG_INFO("[map script] {}", last);
}

void bo2zm::dlc::EveryFrame(PPCContext& ctx, uint8_t* base) {
  if (REXCVAR_GET(bo2zm_custom_maps)) {
    TraceMapScripts(ctx, base);
  }
  if (!g_published.exchange(true)) [[unlikely]] {  // for menus.lua: whether to list the custom maps on the globe
    bo2zm::autoexec::ExecuteCommands(ctx, base, REXCVAR_GET(bo2zm_custom_maps) ? "set bo2zm_custom_maps_ui 1"
                                                                                : "set bo2zm_custom_maps_ui 0");
    if (REXCVAR_GET(bo2zm_custom_maps)) {
      RegisterPatchZone(base, "zm_nacht");
    }
  }
  if (g_reparse_maps.load(std::memory_order_relaxed) > 0 && --g_reparse_maps == 0) [[unlikely]] {
    ReparseMapsTable(ctx, base);
  }
  if (!REXCVAR_GET(bo2zm_dlc_maps_seen)) [[unlikely]] {
    return;
  }
  for (int controller = 0; controller < kControllers; ++controller) {
    const bool loaded =
        base[kProfileBlocks + uint32_t(controller) * kProfileBlockSize + kProfileLoaded] != 0;
    if (!loaded) {
      g_applied[controller] = false;  // signed out or not loaded yet: apply again on the next load
      continue;
    }
    if (g_applied[controller]) [[likely]] {
      continue;
    }
    g_applied[controller] = true;
    REXLOG_INFO("[dlc] profile of controller {} loaded: every Zombies map marked as seen (no NEW badges)", controller);
    bo2zm::autoexec::ExecuteCommands(ctx, base, kAllSeen, controller);
  }
}
