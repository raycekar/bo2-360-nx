"""Converts a BO1 (T5) clipMap, as loaded by zoneload.py, into a BO2 (T6) 360 zone holding one col_map_mp asset.

The stream is written in the order BO2's Load_clipMap_t (TU18 0x822BD3C8) reads it, with block 5 positions and
alignment simulated exactly, so pointers shared between arrays (brush side and node planes, brush sides, leaf brush
lists) can be written as offsets: ((block << 29) | offset) + 1.

usage: python -I t6clip.py <decoded BO1 zone> <BO1 default.image.bin> <out.zone> [--name maps/mp/zm_nacht.d3dbsp]
Not yet converted: static models (their XModels), dynamic entities. mapEnts carries BO1's entity string as is. The output loads completely through
BO2's own Load_clipMap_t (zoneload.py --game t6), and every shared pointer resolves to the same data as in BO1.
"""
import pickle
import struct
import sys

sys.path.append(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import zoneload as Z  # noqa: E402

COL_MAP_MP = 13
BLOCK = 5
TEMP_BLOCK = 0x12AC


class Stream:
    """The zone body, with the block 5 position the loader would have."""

    def __init__(self):
        self.runtime = 0  # bytes the loader allocates in block 1 (runtime, not in the file)
        self.out = bytearray()
        self.pos = 0  # block 5 offset
        self.log = []

    def align(self, a):
        self.pos = (self.pos + a) & ~a

    def put(self, b, block_data=True):
        self.log.append((len(self.out) + 40, len(b)))
        self.out += b
        if block_data:
            self.pos += len(b)

    def ref(self, offset):
        return ((BLOCK << 29) | offset) + 1


def u32(v):
    return struct.pack(">I", v & 0xFFFFFFFF)


class T5Clip:
    """Reads the BO1 clipMap fields (360 offsets) from zoneload memory."""

    def __init__(self, mem, h):
        self.m, self.h = mem, h

    def f(self, off):
        return self.m.u32(self.h + off)

    def arr(self, ptr_off, count, size):
        p = self.f(ptr_off)
        return self.m.read(p, count * size) if p and count else b""


def load_t5_clipmap(zone, image):
    """Runs BO1's loader up to and including the zone's col_map_sp; returns (memory, header)."""
    import contextlib
    import io
    z = Z.Zone(zone, image, "t5")
    with contextlib.redirect_stdout(io.StringIO()):
        z.run()  # the whole zone: the clipMap is wherever it is
    h = [h for i, t, h in z.assets if t == 12][-1]
    load_t5_clipmap.zone = z
    return z.mem, h


def open_source(source, name):
    """source: (memory, header) from load_t5_clipmap, or a pickle {"t5": (pages, header)} from earlier runs."""
    if isinstance(source, str):
        d = pickle.load(open(source, "rb"))
        m = Z.Mem()
        m.pages, h = d["t5"]
    else:
        m, h = source
    return m, h, name


def write_clipmap(s, m, h, name, vis_pad=0, ents_text=None):
    """vis_pad: extra zero bytes after the cluster visibility (with one cluster, as BO1 maps have): used to give the
    asset an exact stream size when it replaces another map's (tools: splice)."""
    c = T5Clip(m, h)
    planes_n, planes_p = c.f(0x08), c.f(0x0C)
    mats_n = c.f(0x18)
    sides_n, sides_p = c.f(0x20), c.f(0x24)
    nodes_n, leafs_n = c.f(0x28), c.f(0x30)
    lbn_n, lb_n, lb_p = c.f(0x38), c.f(0x40), c.f(0x44)
    verts_n, bverts_n, uinds_n, tris_n = c.f(0x50), c.f(0x58), c.f(0x60), c.f(0x68)
    parts_n, aabb_n, cmodels_n = c.f(0x7C), c.f(0x84), c.f(0x8C)
    brushes_n = c.f(0x94) >> 16
    clusters, cluster_bytes = c.f(0x9C), c.f(0xA0)
    # ---- clipMap_t header (block 0, temp): pointers -1 where data follows, offsets/0 elsewhere
    hdr = bytearray(0x14C)

    def hset(off, v):
        hdr[off:off + 4] = u32(v)

    hset(0x00, -1)
    hset(0x04, 0)
    hset(0x08, planes_n), hset(0x0C, -1 if planes_n else 0)
    hset(0x10, mats_n), hset(0x14, -1 if mats_n else 0)
    hset(0x18, sides_n), hset(0x1C, -1 if sides_n else 0)
    hset(0x20, lbn_n), hset(0x24, -1 if lbn_n else 0)
    hset(0x28, lb_n), hset(0x2C, -1 if lb_n else 0)
    hset(0x30, bverts_n), hset(0x34, -1 if bverts_n else 0)
    hset(0x38, uinds_n), hset(0x3C, -1 if uinds_n else 0)
    hdr[0x40:0x42] = struct.pack(">H", brushes_n)
    hset(0x44, -1 if brushes_n else 0)
    hset(0x48, 0), hset(0x4C, 0), hset(0x50, 0)  # brushBounds, brushContents, pInfo
    hset(0x54, 0), hset(0x58, 0)  # no static models yet (their XModels are not converted)
    hset(0x5C, nodes_n), hset(0x60, -1 if nodes_n else 0)
    hset(0x64, leafs_n), hset(0x68, -1 if leafs_n else 0)
    hset(0x6C, verts_n), hset(0x70, -1 if verts_n else 0)
    hset(0x74, tris_n), hset(0x78, -1 if tris_n else 0), hset(0x7C, -1 if tris_n else 0)
    hset(0x80, parts_n), hset(0x84, -1 if parts_n else 0)
    hset(0x88, aabb_n), hset(0x8C, -1 if aabb_n else 0)
    hset(0x90, cmodels_n), hset(0x94, -1 if cmodels_n else 0)
    assert vis_pad == 0 or clusters == 1, "visibility padding needs a single cluster"
    hset(0x98, clusters), hset(0x9C, cluster_bytes + vis_pad), hset(0xA0, -1 if clusters * cluster_bytes else 0)
    hset(0xA4, c.f(0xA8))  # vised
    t5_ents = c.f(0xAC)  # BO1 MapEnts {name, entityString, numEntityChars}
    if ents_text is None:  # BO1's entity string as is, unless a translated one is given
        ents_text = m.read(m.u32(t5_ents + 4), m.u32(t5_ents + 8)) if t5_ents else b""
    elif not ents_text.endswith(b"\0"):
        ents_text += b"\0"  # numEntityChars counts the terminator, as BO1's does
    hset(0xA8, -1 if ents_text else 0)  # MapEnts follows inline (BO2 registers it as the map_ents asset)
    hset(0xAC, -1)  # box_brush follows
    # box_model (cmodel_t, inline at 0xB0, 0x4C): T5 keeps it inline at 0xB4 as mins, maxs, radius, leaf (0x48)
    bm = m.read(h + 0xB4, 0x48)
    hdr[0xB0:0xB0 + 0x1C] = bm[:0x1C]
    hdr[0xB0 + 0x1C:0xB0 + 0x20] = u32(0)  # info
    hdr[0xB0 + 0x20:0xB0 + 0x4C] = bm[0x1C:0x48]
    # 0xFC: originalDynEntCount, dynEntCount[4] (u16: client, -, server, -); 0x108/0x10C def lists (block 5);
    # pose 0x110/0x114, client 0x118/0x11C, server 0x120/0x124, collision 0x128..0x134 lists (block 1, run time).
    # No placed dynamic entities: a client pool of spare slots only. Constraints and ropes: none. Checksum copied.
    hdr[0xFC:0x106] = struct.pack(">5H", 0, DYNENT_POOL, 0, 0, 0)
    hset(0x108, -1), hset(0x110, -1), hset(0x118, -1), hset(0x128, -1)
    hset(0x148, c.f(0x148))
    s.put(bytes(hdr), block_data=False)  # the header goes to the temp block

    # ---- Load_clipMap_t body (block 5)
    s.align(0)
    s.put(name.encode() + b"\0")
    # ClipInfo arrays
    s.align(3)
    planes_off = s.pos
    s.put(c.arr(0x0C, planes_n, 20))
    s.align(3)
    mats = c.arr(0x1C, mats_n, 72)  # T5 dmaterial_t: char[64], surfaceFlags, contentFlags
    s.put(b"".join(u32(-1) + mats[i * 72 + 64:i * 72 + 72] for i in range(mats_n)))
    for i in range(mats_n):
        s.align(0)
        s.put(mats[i * 72:i * 72 + 64].split(b"\0")[0] + b"\0")
    s.align(3)
    sides_off = s.pos
    t5_sides = c.arr(0x24, sides_n, 12)
    out_sides = bytearray()
    for i in range(sides_n):
        plane = struct.unpack_from(">I", t5_sides, i * 12)[0]
        out_sides += u32(s.ref(planes_off + (plane - planes_p))) + t5_sides[i * 12 + 4:i * 12 + 12]
    s.put(bytes(out_sides))
    # leaf brush nodes: 0x14 each; leaf data (leafBrushCount > 0) points into the leaf brush array
    s.align(3)
    lbn = bytearray(c.arr(0x3C, lbn_n, 20))
    lbs_off_holder = []
    lbn_fix = []
    inline_lists = []
    for i in range(lbn_n):
        count = struct.unpack_from(">h", lbn, i * 20 + 2)[0]
        if count > 0:
            p = struct.unpack_from(">I", lbn, i * 20 + 0x08)[0]
            if lb_p <= p < lb_p + 2 * lb_n:
                lbn_fix.append((i, (p - lb_p) // 2))
            else:  # BO1 kept this node's list inline: so does BO2 (-1, read right after the node array)
                lbn[i * 20 + 8:i * 20 + 12] = u32(-1)
                inline_lists.append(m.read(p, 2 * count))
    lbn_pos = s.pos
    s.put(bytes(lbn))  # patched below once the leaf brush array's offset is known
    for data in inline_lists:
        s.align(1)
        s.put(data)
    s.align(1)
    lb_off = s.pos
    s.put(c.arr(0x44, lb_n, 2))
    lbn_start = s.out.rfind(bytes(lbn), 0, len(s.out) - lb_n * 2)
    for i, index in lbn_fix:
        s.out[lbn_start + i * 20 + 0x08:lbn_start + i * 20 + 0x0C] = u32(s.ref(lb_off + index * 2))
    s.align(3)
    bverts_off, bverts_p = s.pos, c.f(0x5C)
    s.put(c.arr(0x5C, bverts_n, 12))
    s.align(1)
    s.put(c.arr(0x64, uinds_n, 2))
    # brushes: 0x60 each, 128-aligned; sides -> offsets into the brush side array, verts inline
    s.align(0x7F)
    t5_br = c.arr(0x98, brushes_n, 0x60)
    out_br = bytearray()
    t5_sides_p = sides_p
    vert_lists = []
    for i in range(brushes_n):
        b = bytearray(t5_br[i * 0x60:(i + 1) * 0x60])
        sp = struct.unpack_from(">I", b, 0x20)[0]
        b[0x20:0x24] = u32(s.ref(sides_off + (sp - t5_sides_p))) if sp else u32(0)
        nv, vp = struct.unpack_from(">II", b, 0x54)
        # BO2 reads a single vec3 when verts is -1: brush verts must point into ClipInfo.brushVerts (as in BO1)
        b[0x58:0x5C] = u32(s.ref(bverts_off + (vp - bverts_p)) if (vp and nv) else 0)
        out_br += b
    s.put(bytes(out_br))
    # nodes: plane -> offset
    s.align(3)
    t5_nodes = c.arr(0x2C, nodes_n, 8)
    s.put(b"".join(u32(s.ref(planes_off + (struct.unpack_from(">I", t5_nodes, i * 8)[0] - planes_p))) +
                   t5_nodes[i * 8 + 4:i * 8 + 8] for i in range(nodes_n)))
    s.align(3)
    s.put(c.arr(0x34, leafs_n, 0x2C))
    s.align(3)
    s.put(c.arr(0x54, verts_n, 12))
    s.align(1)
    s.put(c.arr(0x6C, tris_n, 6))
    s.align(0)
    s.put(m.read(c.f(0x70), ((tris_n * 3 + 31) >> 5) * 4))
    s.align(3)
    t5_parts = c.arr(0x80, parts_n, 20)  # T5: triCount, borderCount, pad, firstTri, nuinds, fuind, borders
    s.put(b"".join(t5_parts[i * 20:i * 20 + 1] + bytes(3) + t5_parts[i * 20 + 4:i * 20 + 16] for i in range(parts_n)))
    s.align(15)
    s.put(c.arr(0x88, aabb_n, 32))
    s.align(3)
    t5_cm = c.arr(0x90, cmodels_n, 0x48)  # T5 cmodel_t: mins, maxs, radius, leaf (0x2C)
    s.put(b"".join(t5_cm[i * 0x48:i * 0x48 + 0x1C] + u32(0) + t5_cm[i * 0x48 + 0x1C:(i + 1) * 0x48]
                   for i in range(cmodels_n)))
    if clusters * cluster_bytes:
        s.align(0)
        s.put(m.read(c.f(0xA4), clusters * cluster_bytes) + bytes(vis_pad))
    if ents_text:  # Load_MapEnts (0x822B4860): struct (temp block), name, entity string; no triggers (as Nuketown)
        s.put(struct.pack(">iii6I", -1, -1, len(ents_text), 0, 0, 0, 0, 0, 0), block_data=False)
        s.align(0)
        s.put(name.encode() + b"\0")
        s.align(0)
        s.put(ents_text)
    # box_brush: 0x60, 16-aligned, its sides and verts inline
    s.align(15)
    bb = bytearray(m.read(c.f(0xB0), 0x60))
    ns, sp = struct.unpack_from(">II", bb, 0x1C)
    nv, vp = struct.unpack_from(">II", bb, 0x54)
    bb[0x20:0x24] = u32(-1 if ns and sp else 0)
    bb[0x58:0x5C] = u32(-1 if nv and vp else 0)
    s.put(bytes(bb))
    if ns and sp:
        s.align(3)
        sides = m.read(sp, ns * 12)
        s.put(b"".join(u32(-1) + sides[i * 12 + 4:i * 12 + 12] for i in range(ns)))
        for i in range(ns):
            s.align(3)
            s.put(m.read(struct.unpack_from(">I", sides, i * 12)[0], 20))
    if nv and vp:
        s.align(3)
        s.put(m.read(vp, 12))  # BO2 reads one vec3 here
    # dynamic entities (Load: 0x822BC658): no placed ones, but the client pool's spare slots, which the game fills at
    # run time (zombie gibs, CreateDynEntAndLaunch). Without a pool the first gib wrote through a null pointer.
    s.align(3)
    s.put(DYNENT_SPARE * DYNENT_POOL)


# DynEntityDef (84 bytes): a spare slot as Nuketown's 256 are (all zero but four 0x01FF words at 0x3C)
DYNENT_SPARE = bytes(0x3C) + b"\x01\xff" * 4 + bytes(84 - 0x44)
DYNENT_POOL = 256  # Nuketown: 60 placed + 256 spare client dynamic entities


def write_comworld(s, m, h, name):
    """BO1 ComWorld (360: name, isInUse, primaryLightCount, primaryLights, then water/burnable data that BO2 dropped)
    as BO2's (0x10: name, isInUse, count, lights; Load_ComWorld 0x822B4BD0). ComPrimaryLight: BO1 0xDC bytes, BO2 0xC4
    (lights 0x822B4B48): the same up to mipDistance (0x48); BO2 adds dAttenuation and roundness, drops specularColor
    and attenuation; diffuse, falloff, angle, aAbB and the cookie controls follow; then defName (a string)."""
    n, lp = m.u32(h + 8), m.u32(h + 12)
    s.put(struct.pack(">iiIi", -1, 0, n, -1 if n else 0), block_data=False)
    s.align(0)
    s.put(name.encode() + b"\0")
    if not n:
        return
    s.align(3)
    lights, names = bytearray(), []
    for i in range(n):
        t5 = m.read(lp + 0xDC * i, 0xDC)
        t6 = bytearray(0xC4)
        t6[0:6] = t5[0:6]  # type, canUseShadowMap, exponent, priority, cullDist
        t6[8:0x48] = t5[8:0x48]  # color, dir, origin, radius, cone, limits, mipDistance
        t6[0x48:0x4C] = struct.pack(">f", 1.0)  # dAttenuation
        t6[0x50:0x60] = t5[0x48:0x58]  # diffuseColor
        t6[0x60:0x70] = t5[0x78:0x88]  # falloff
        t6[0x70:0x80] = t5[0x88:0x98]  # angle
        t6[0x80:0x90] = t5[0x98:0xA8]  # aAbB
        t6[0x90:0xC0] = t5[0xA8:0xD8]  # cookieControl0..2
        dn = m.u32(lp + 0xDC * i + 0xD8)
        t6[0xC0:0xC4] = u32(-1 if dn else 0)
        names.append(m.read(dn, 64).split(b"\0")[0] if dn else None)
        lights += t6
    s.put(bytes(lights))
    for nm in names:
        if nm is not None:
            s.align(0)
            s.put(nm + b"\0")


NODE_TYPES = {8: 6, 9: 7, 10: 8}  # BO1 cover wide right/left, pillar -> BO2 cover right/left, pillar


def write_gameworld(s, m, h, name, strings):
    """BO1 GameWorldSp (0x2C: name, PathData) as BO2's GameWorldMp (0x2C; Load_GameWorldMp 0x822BC138, PathData
    0x822BBF20). PathData: BO1 {nodeCount, nodes, basenodes, chainNodeCount, chainNodeForNode, nodeForChainNode,
    visBytes, pathVis, nodeTreeCount, nodeTree} -> BO2 {nodeCount, originalNodeCount, nodes, basenodes, visBytes,
    pathVis, smoothBytes, smoothCache, nodeTreeCount, nodeTree}. pathnode_t 0x80 -> 0x90 (nodes 0x822B37D0 /
    0x822B3660): the constant part is re-laid out, spawnflags become an int, script strings are renumbered into this
    zone's list (strings: a ScriptStrings), the runtime parts stay zero. pathlink_s 12 -> 16 bytes (adds flags).
    Base nodes live in block 1 (runtime): nothing in the file. The node tree keeps child offsets; leaves inline.
    Not stored by BO1, set to the most common Nuketown values: node spawnflags |= 0x300000, link flags 0x28."""
    p = h + 4
    n_nodes, nodes = m.u32(p), m.u32(p + 4)
    vis_bytes, vis = m.u32(p + 0x18), m.u32(p + 0x1C)
    tree_n, tree = m.u32(p + 0x20), m.u32(p + 0x24)
    s.put(struct.pack(">i", -1) + struct.pack(">IIiiIiIiIi", n_nodes, n_nodes, -1 if n_nodes else 0,
                                                -1 if n_nodes else 0, vis_bytes, -1 if vis_bytes else 0, 0, 0,
                                                tree_n, -1 if tree_n else 0), block_data=False)
    s.align(0)
    s.put(name.encode() + b"\0")
    links = []
    if n_nodes:
        s.align(3)
        out = bytearray()
        for i in range(n_nodes):
            t5 = m.read(nodes + 0x80 * i, 0x80)
            t6 = bytearray(0x90)
            t6[0:4] = u32(NODE_TYPES.get(struct.unpack_from(">I", t5, 0)[0], struct.unpack_from(">I", t5, 0)[0]))
            t6[4:8] = u32(struct.unpack_from(">H", t5, 4)[0] | 0x300000)
            for k in range(5):  # targetname, script_linkName, script_noteworthy, target, animscript
                t6[8 + 2 * k:10 + 2 * k] = struct.pack(">H", strings.index(struct.unpack_from(">H", t5, 6 + 2 * k)[0]))
            t6[0x14:0x38] = t5[0x10:0x34]  # animscriptfunc, origin, angle, forward, radius, minUseDistSq
            t6[0x38:0x3C] = t5[0x34:0x38]  # wOverlapNode
            count = struct.unpack_from(">H", t5, 0x3E)[0]
            t6[0x3C:0x3E] = struct.pack(">H", count)
            lp = struct.unpack_from(">I", t5, 0x40)[0]
            t6[0x40:0x44] = u32(-1 if (count and lp) else 0)
            links.append(m.read(lp, 12 * count) if (count and lp) else b"")
            out += t6
        out += bytes(0x90 * 128)  # BO2 streams nodeCount + 128 nodes: spare slots for nodes added at run time
        s.runtime += 16 + 16 * (n_nodes + 128)  # base nodes (16 bytes, 16-aligned) go to block 1: size it
        s.put(bytes(out))
        for data in links:
            if data:
                s.align(3)
                s.put(b"".join(data[12 * k:12 * k + 8] + bytes([0x28]) + data[12 * k + 8:12 * k + 12] + bytes(3)
                               for k in range(len(data) // 12)))
    if vis_bytes:
        s.align(0)
        s.put(m.read(vis, vis_bytes))
    if tree_n:
        s.align(3)
        t5_tree = m.read(tree, 16 * tree_n)
        out = bytearray(t5_tree)
        leaves = []
        for i in range(tree_n):
            if struct.unpack_from(">i", t5_tree, 16 * i)[0] >= 0:  # children: offsets into this array
                pass
            else:
                cnt, np_ = struct.unpack_from(">iI", t5_tree, 16 * i + 8)
                out[16 * i + 12:16 * i + 16] = u32(-1 if cnt else 0)
                leaves.append(m.read(np_, 2 * cnt) if cnt else b"")
        tree_off = s.pos
        for i in range(tree_n):
            if struct.unpack_from(">i", t5_tree, 16 * i)[0] >= 0:
                for k in range(2):
                    c = struct.unpack_from(">I", t5_tree, 16 * i + 8 + 4 * k)[0]
                    out[16 * i + 8 + 4 * k:16 * i + 12 + 4 * k] = u32(s.ref(tree_off + (c - tree)))
        s.put(bytes(out))
        for data in leaves:
            if data:
                s.align(1)
                s.put(data)


class ScriptStrings(list):
    """The zone's script string list: index 0 is the empty string; BO1 indices are mapped through .index()."""

    def __init__(self, t5_strings):
        super().__init__([""])
        self.t5 = t5_strings
        self.map = {0: 0}

    def index(self, t5_index):
        if t5_index not in self.map:
            self.map[t5_index] = len(self)
            self.append(self.t5[t5_index])
        return self.map[t5_index]


def t5_script_strings(m, lst):
    """The BO1 zone's script strings, from the XAssetList zoneload.py read (SCRATCH): {count, strings, ...}."""
    count, arr = m.u32(lst), m.u32(lst + 4)
    return [m.read(m.u32(arr + 4 * i), 256).split(b"\0")[0].decode("latin-1") if arr else "" for i in range(count)]


def write_zone(assets, strings=()):
    """assets: [(type, writer(stream))]; strings: the zone's script strings (written after the asset list header, as
    BO2's Load_ScriptStringList 0x822AEFE8 reads them). Returns the zone (XFile header + body)."""
    s = Stream()
    s.put(struct.pack(">6i", len(strings), -1 if strings else 0, 0, 0, len(assets), -1), block_data=False)
    if strings:
        s.align(3)
        s.put(u32(-1) * len(strings))
        for st in strings:
            s.align(0)
            s.put(st.encode("latin-1") + b"\0")
    s.align(3)
    s.put(b"".join(struct.pack(">ii", t, -1) for t, _ in assets))
    for _, w in assets:
        w(s)
    convert.log = s.log
    body = bytes(s.out)
    virtual = (s.pos + 0xFFFF) & ~0xFFF
    runtime = (s.runtime + 0xFFF) & ~0xFFF
    # block 2 (runtime physical): the skinned verts buffer, maxSkinnedVerts * 64 (Nuketown declares the same 0xA00000)
    skinned = 163840 * 64
    return struct.pack(">II8I", len(body), 0, TEMP_BLOCK, runtime, skinned, 0, 0, virtual, 0, 0) + body


def convert(source, name, z5=None):
    m, h, name = open_source(source, name)
    # SkinnedVertsDef (360: 0x10 = name, maxSkinnedVerts, two buffers of maxSkinnedVerts * 32 bytes in the runtime
    # physical block; Load 0x822B6590): every BO2 map zone has one (Nuketown: "skinnedverts", 163840); without it
    # loading the map stops with "Could not load default asset 'skinnedverts'".
    assets = [(56, lambda s: (s.put(struct.pack(">iIii", -1, 163840, -1, -1), block_data=False), s.align(0),
                              s.put(b"skinnedverts\0")))]
    strings = ScriptStrings(t5_script_strings(m, Z.SCRATCH) if z5 is not None else [""])
    if z5 is not None:
        com = [hh for i, t, hh in z5.assets if t == 14]
        if com:
            assets.append((14, lambda s: write_comworld(s, m, com[-1], name)))
        game = [hh for i, t, hh in z5.assets if t == 15]
        if game:
            # the string list is written before the assets: collect the names the nodes use first
            p = game[-1] + 4
            for i in range(m.u32(p)):
                for k in range(5):
                    strings.index(m.u16(m.u32(p + 4) + 0x80 * i + 6 + 2 * k))
            assets.append((16, lambda s: write_gameworld(s, m, game[-1], name, strings)))
    assets.append((COL_MAP_MP, lambda s: write_clipmap(s, m, h, name)))
    return write_zone(assets, strings if len(strings) > 1 else ())


def main():
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "maps/mp/zm_nacht.d3dbsp"
    source = load_t5_clipmap(sys.argv[1], sys.argv[2])
    z = convert(source, name, load_t5_clipmap.zone)
    open(sys.argv[3], "wb").write(z)
    print("wrote", sys.argv[3], len(z), "bytes")


if __name__ == "__main__":
    main()
