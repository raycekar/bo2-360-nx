"""Replace a BO2 zone's col_map_mp and game_map_mp with a converted BO1 map's, keeping every other asset's stream
position (each replacement starts where the original started in block 5 and is padded to end where it ended).
usage: python -I splice_world.py <bo2 zone> <footprint.json> <bo1 zone> <bo1 image> <out zone>"""
import contextlib
import io
import json
import struct
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import t6clip as T  # noqa: E402
import zoneload as Z  # noqa: E402

GAME, COL = 16, 13
# Nacht's lightmap images in BO1's block 2 (from asset_trace.py of its world) and Nuketown's lightmap 0 in BO2's
# block 3 (2048 x 3072 DXT5, 0x600000 bytes)
NACHT_LM = {"secondary": 0x3F5000, "secondary_b": 0x5F5000}
NUKED_LM0 = 0x16C000
NUKED_LM_HEADER = 0x349C597  # Nuketown's lightmap 0 image header (non-streamed): the new images' template
TEMPLATE_MATERIAL = 0x3DC4FCC  # Nuketown's wqc/wood_burned record: the new materials' template
BO2_IMAGE = "work/dump_tu18/default_mp.image.bin"  # the decrypted TU18 program (the build writes it)


def bo2_strings(zone):
    z = Z.Zone(zone, BO2_IMAGE, "t6")
    with contextlib.redirect_stdout(io.StringIO()):
        z.run(1)  # the script string list is read before the first asset
    count, arr = z.mem.u32(Z.SCRATCH), z.mem.u32(Z.SCRATCH + 4)
    return [z.mem.read(z.mem.u32(arr + 4 * i), 256).split(b"\0")[0].decode("latin-1") for i in range(count)]


class FixedStrings:
    """Map BO1 script string indices to the BO2 zone's existing list (by text; 0 when absent)."""

    def __init__(self, t5, t6, aliases=None):
        self.t5, self.lookup, self.missing = t5, {s: i for i, s in enumerate(t6)}, set()
        self.aliases = dict(aliases or {})
        self.node_names = [(tuple(float(v) for v in o.split()), n)
                           for o, n in self.aliases.pop("_node_targetnames", {}).items()]
        self.named = 0

    def node_name(self, origin):
        """String index for a node that gets a targetname by position, or None."""
        for o, n in self.node_names:
            if sum((a - b) ** 2 for a, b in zip(o, origin)) < 0.25:
                if n not in self.lookup:
                    raise SystemExit(f"node name {n} is not in the BO2 zone's script strings")
                self.named += 1
                return self.lookup[n]
        return None

    def index(self, i):
        if not i:
            return 0
        s = self.aliases.get(self.t5[i], self.t5[i])
        if s not in self.lookup:
            self.missing.add(s)
        return self.lookup.get(s, 0)


def gameworld(start, end, m, h, name, strings, target_nodes, smooth_pad, extra_leaf=False):
    s = T.Stream()
    s.pos = start
    strings.named = 0  # fit() builds this several times; the count is for the last build
    p = h + 4
    n_nodes, nodes = m.u32(p), m.u32(p + 4)
    vis_bytes, vis = m.u32(p + 0x18), m.u32(p + 0x1C)
    tree_n, tree = m.u32(p + 0x20), m.u32(p + 0x24)
    N = max(n_nodes, target_nodes)
    new_vis = N * (N - 1) // 8  # 2 bits per node pair, triangular: the first n's pairs come first
    s.put(struct.pack(">i", -1) + struct.pack(">IIiiIiIiIi", N, N, -1, -1, new_vis, -1, smooth_pad,
                                                -1 if smooth_pad else 0, tree_n, -1 if tree_n else 0),
          block_data=False)
    s.align(0)
    s.put(name.encode() + b"\0")
    s.align(3)
    out, links = bytearray(), []
    for i in range(n_nodes):
        t5 = m.read(nodes + 0x80 * i, 0x80)
        t6 = bytearray(0x90)
        ty = struct.unpack_from(">I", t5, 0)[0]
        t6[0:4] = T.u32(T.NODE_TYPES.get(ty, ty))
        t6[4:8] = T.u32(struct.unpack_from(">H", t5, 4)[0] | 0x300000)
        for k in range(5):  # targetname, target, animscript, script_linkname, script_noteworthy
            t6[8 + 2 * k:10 + 2 * k] = struct.pack(">H", strings.index(struct.unpack_from(">H", t5, 6 + 2 * k)[0]))
        named = strings.node_name(struct.unpack_from(">3f", t5, 0x14))
        if named is not None:  # a window's begin node carries the window's name (nacht_ents.py)
            t6[8:10] = struct.pack(">H", named)
        t6[0x14:0x3C] = t5[0x10:0x38]
        count = struct.unpack_from(">H", t5, 0x3E)[0]
        t6[0x3C:0x3E] = struct.pack(">H", count)
        lp = struct.unpack_from(">I", t5, 0x40)[0]
        t6[0x40:0x44] = T.u32(-1 if (count and lp) else 0)
        links.append(m.read(lp, 12 * count) if (count and lp) else b"")
        out += t6
    for i in range(n_nodes, N):  # spare nodes so the node and base node arrays keep the original sizes
        dummy = bytearray(0x90)
        dummy[0x18:0x24] = struct.pack(">3f", 0.0, 0.0, -30000.0)
        dummy[0x38:0x3C] = b"\xff\xff\xff\xff"
        out += dummy
    out += bytes(0x90 * 128)
    s.put(bytes(out))
    for data in links:
        if data:
            s.align(3)
            s.put(b"".join(data[12 * k:12 * k + 8] + bytes([0x28]) + data[12 * k + 8:12 * k + 12] + bytes(3)
                           for k in range(len(data) // 12)))
    s.runtime += 16 * (N + 128)
    s.align(0)
    s.put(m.read(vis, vis_bytes) + bytes(new_vis - vis_bytes))
    if smooth_pad:
        s.align(0)
        s.put(bytes(smooth_pad))
    s.align(3)
    t5_tree = m.read(tree, 16 * tree_n)
    tout, leaves = bytearray(t5_tree), []
    tree_off = s.pos
    for i in range(tree_n):
        if struct.unpack_from(">i", t5_tree, 16 * i)[0] >= 0:
            for k in range(2):
                c = struct.unpack_from(">I", t5_tree, 16 * i + 8 + 4 * k)[0]
                tout[16 * i + 8 + 4 * k:16 * i + 12 + 4 * k] = T.u32(s.ref(tree_off + (c - tree)))
        else:
            cnt, np_ = struct.unpack_from(">iI", t5_tree, 16 * i + 8)
            tout[16 * i + 12:16 * i + 16] = T.u32(-1 if cnt else 0)
            data = m.read(np_, 2 * cnt) if cnt else b""
            if extra_leaf and cnt and not any(leaves):  # repeat a node in the first leaf: 2 bytes, to fit the end
                tout[16 * i + 8:16 * i + 12] = T.u32(cnt + 1)
                data += data[-2:]
            leaves.append(data)
    s.put(bytes(tout))
    for data in leaves:
        if data:
            s.align(1)
            s.put(data)
    return s


def clipmap(start, m, h, name, vis_pad, ents_text=None):
    s = T.Stream()
    s.pos = start
    T.write_clipmap(s, m, h, name, vis_pad=vis_pad, ents_text=ents_text)
    return s


def fit(build, start, end, label):
    """Find the padding that makes the stream end exactly at end (block 5)."""
    base = build(0, False)
    need = end - base.pos
    if need < 0:
        raise SystemExit(f"{label}: Nacht's data is {-need:#x} bytes larger than the original")
    for extra in (False, True):
        for pad in range(max(0, need - 8), need + 8):
            s = build(pad, extra)
            if s.pos == end:
                print(f"{label}: padded {pad} bytes, extra leaf entry {extra}, ends at {s.pos:#x}")
                return s
    raise SystemExit(f"{label}: no padding ends at {end:#x}")


def fit_aligned(build, end, label, align=4096):
    """With relocation: the smallest padding whose end differs from the original's by a multiple of align (so the
    data after it keeps its alignment: sound banks align their data to 2048 in block 5); the asset may be larger or
    smaller than the original."""
    natural = build(0, False).pos
    target = end + -((end - natural) // align) * align if natural > end else end - ((end - natural) // align) * align
    for extra in (False, True):
        for pad in range(max(0, target - natural - 8), target - natural + 8):
            s = build(pad, extra)
            if s.pos == target:
                print(f"{label}: padded {pad} bytes, extra leaf entry {extra}, ends at {s.pos:#x} "
                      f"({s.pos - end:+#x} against the original)")
                return s
    raise SystemExit(f"{label}: no padding ends at {target:#x}")


def main():
    bo2_zone, fp_path, bo1_zone, bo1_image, out = sys.argv[1:6]
    opt = dict(zip(sys.argv[6::2], sys.argv[7::2]))  # --ents <translated entity string> --aliases <json>
    ents_text = open(opt["--ents"], "rb").read() if "--ents" in opt else None
    aliases = json.load(open(opt["--aliases"])) if "--aliases" in opt else None
    global BO2_IMAGE
    BO2_IMAGE = opt.get("--bo2-image", BO2_IMAGE)
    fp = json.load(open(fp_path))
    info = {t: (i, f0, b0, f1, b1) for i, t, f0, b0, f1, b1 in fp if t in (GAME, COL)}
    m, h = T.load_t5_clipmap(bo1_zone, bo1_image)
    z5 = T.load_t5_clipmap.zone
    game_h = [hh for i, t, hh in z5.assets if t == 15][-1]
    strings = FixedStrings(T.t5_script_strings(m, Z.SCRATCH), bo2_strings(bo2_zone), aliases)
    name = "maps/mp/zm_nacht.d3dbsp"
    gi, gf0, gb0, gf1, gb1 = info[GAME]
    target_nodes = 889  # keeps the runtime block (base nodes) the size Nuketown's had
    ci, cf0, cb0, cf1, cb1 = info[COL]
    relocs = opt.get("--relocs")  # reloc_scan.py's table: replacements may then have any size
    gfx_edits, gfx_patches, mg = [], [], 0
    if relocs and "--gfx" in sys.argv:  # the render world too (t6gfx.py); it comes before the game world
        import t6gfx
        gfx_h = [hh for i, t, hh in z5.assets if t == 18][-1]
        base = open(bo2_zone, "rb").read()
        mat = t6gfx.find_material(bo2_zone, BO2_IMAGE, opt["--material"], base) if "--material" in opt else None
        mats = None
        if "--materials" in sys.argv:  # Nacht's own color textures (t6mat.py)
            import re
            import t6mat
            z2, images = t6mat.bo1_images(bo1_zone, bo1_image, 417)
            m2 = z2.mem
            gh2 = [hh for i, t, hh in z2.assets if t == 18][-1]
            surf_n2 = m2.u32(gh2 + 0x10)
            surfs2 = m2.u32(gh2 + 0x408)
            surf_mats = [m2.u32(surfs2 + 80 * s + 0x30) for s in range(surf_n2)]
            bo1 = open(bo1_zone, "rb").read()
            block2 = bo1[len(bo1) - struct.unpack_from(">I", bo1, 8 + 4 * 2)[0]:]

            def name_of(img):
                raw = m2.read(m2.u32(img + 0x94), 64).split(b"\0")[0].decode("latin-1")
                return re.sub(r"[^A-Za-z0-9_]", "_", raw) or "img"

            mats = t6mat.build(m2, surf_mats, images, block2, base, TEMPLATE_MATERIAL,
                               base[NUKED_LM_HEADER:NUKED_LM_HEADER + 0xD4], name_of, bo1)
            print(f"materials: {mats['count']} new (one per Nacht color texture), "
                  f"{sum(len(p) for p in mats['pixels']) // 1024} KB of pixels")
        gfx_edits, gfx_patches, mg = t6gfx.convert(m, gfx_h, base, mat, mats)
        print(f"gfx_map: {len(gfx_edits)} regions, {mg:+#x} bytes in block 5")
    if relocs:
        g = fit_aligned(lambda pad, extra: gameworld(gb0["5"] + mg, gb1["5"] + mg, m, game_h, name, strings,
                                                     target_nodes, pad, extra), gb1["5"] + mg, "game_map_mp")
        dg = g.pos - (gb1["5"] + mg)  # everything after the game world moves by dg, the collision included
        c = fit_aligned(lambda pad, extra: clipmap(cb0["5"] + mg + dg, m, h, name, pad, ents_text),
                        cb1["5"] + mg + dg, "col_map_mp")
        dc = c.pos - (cb1["5"] + mg + dg)
    else:
        g = fit(lambda pad, extra: gameworld(gb0["5"], gb1["5"], m, game_h, name, strings, target_nodes, pad, extra),
                gb0["5"], gb1["5"], "game_map_mp")
        c = fit(lambda pad, extra: clipmap(cb0["5"], m, h, name, pad, ents_text), cb0["5"], cb1["5"], "col_map_mp")
    if strings.node_names:  # fit() builds the game world several times: count one build's worth
        print(f"named nodes: {strings.named} of {len(strings.node_names)} expected")
    if strings.missing:
        print("script strings not in the BO2 zone (set to none):", sorted(strings.missing)[:20])
    d = open(bo2_zone, "rb").read()
    if relocs:
        import zone_rebuild as R
        new, changed, mismatched = R.rebuild(d, R.load_relocs(relocs), gfx_edits + [
            (gf0, gf1, bytes(g.out), {5: (gb1["5"], dg)}),
            (cf0, cf1, bytes(c.out), {5: (cb1["5"], dc)})], patches=gfx_patches)
        print(f"relocated: {changed} offsets shifted, {mismatched} table entries did not match the file, "
              f"{len(R.rebuild.dangling)} pointed into replaced data")
    else:
        new = d[:gf0] + bytes(g.out) + d[gf1:cf0] + bytes(c.out) + d[cf1:]
    if gfx_edits:  # the lightmap: Nacht's light in Nuketown's lightmap 0 (same size, in the deferred block 3 at the end)
        import t6lightmap as L
        bo1 = open(bo1_zone, "rb").read()
        tail5 = len(bo1) - struct.unpack_from(">I", bo1, 8 + 4 * 2)[0]  # BO1's block 2, stored last
        light = L.bo1_light(bo1[tail5 + NACHT_LM["secondary"]:tail5 + NACHT_LM["secondary"] + 0x200000],
                            bo1[tail5 + NACHT_LM["secondary_b"]:tail5 + NACHT_LM["secondary_b"] + 0x200000], 512, 1024)
        pixels = L.build(light, 2048, 3072)
        new = bytearray(new)
        tail6 = len(new) - struct.unpack_from(">I", new, 8 + 4 * 3)[0]  # BO2's block 3, stored last
        at = tail6 + NUKED_LM0
        assert len(pixels) == 0x600000, hex(len(pixels))
        new[at:at + len(pixels)] = pixels
        new = bytes(new)
        print("lightmap: Nacht's light written into lightmap 0")
    open(out, "wb").write(new)
    print("wrote", out, len(new), "bytes")


if __name__ == "__main__":
    main()
