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
    types = []
    with contextlib.redirect_stdout(io.StringIO()):
        z.run()  # the whole zone: the clipMap is wherever it is
    h = [h for i, t, h in z.assets if t == 12][-1]
    return z.mem, h


def convert(source, name):
    """source: (memory, header) from load_t5_clipmap, or a pickle {"t5": (pages, header)} from earlier runs."""
    if isinstance(source, str):
        d = pickle.load(open(source, "rb"))
        m = Z.Mem()
        m.pages, h = d["t5"]
    else:
        m, h = source
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

    s = Stream()
    # ---- the zone root: XAssetList {stringList {0, 0}, depends {0, 0}, assetCount 1, assets -1}
    s.put(struct.pack(">6i", 0, 0, 0, 0, 1, -1), block_data=False)
    s.align(3)
    s.put(struct.pack(">ii", COL_MAP_MP, -1))  # XAsset[1] in block 5
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
    hset(0x98, clusters), hset(0x9C, cluster_bytes), hset(0xA0, -1 if clusters * cluster_bytes else 0)
    hset(0xA4, c.f(0xA8))  # vised
    t5_ents = c.f(0xAC)  # BO1 MapEnts {name, entityString, numEntityChars}
    ents_text = m.read(m.u32(t5_ents + 4), m.u32(t5_ents + 8)) if t5_ents else b""
    hset(0xA8, -1 if ents_text else 0)  # MapEnts follows inline (BO2 registers it as the map_ents asset)
    hset(0xAC, -1)  # box_brush follows
    # box_model (cmodel_t, inline at 0xB0, 0x4C): T5 keeps it inline at 0xB4 as mins, maxs, radius, leaf (0x48)
    bm = m.read(h + 0xB4, 0x48)
    hdr[0xB0:0xB0 + 0x1C] = bm[:0x1C]
    hdr[0xB0 + 0x1C:0xB0 + 0x20] = u32(0)  # info
    hdr[0xB0 + 0x20:0xB0 + 0x4C] = bm[0x1C:0x48]
    # 0xFC..: originalDynEntCount, dynEntCount[4], lists, constraints, ropes: all 0; checksum copied
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
        s.put(m.read(c.f(0xA4), clusters * cluster_bytes))
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
    convert.log = s.log
    body = bytes(s.out)
    virtual = (s.pos + 0xFFFF) & ~0xFFF
    return struct.pack(">II8I", len(body), 0, TEMP_BLOCK, 0, 0, 0, 0, virtual, 0, 0) + body


def main():
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else "maps/mp/zm_nacht.d3dbsp"
    z = convert(load_t5_clipmap(sys.argv[1], sys.argv[2]), name)
    open(sys.argv[3], "wb").write(z)
    print("wrote", sys.argv[3], len(z), "bytes")


if __name__ == "__main__":
    main()
