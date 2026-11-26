"""Convert a BO1 render world (gfx_map) into edits of a BO2 base map's render world (zone_rebuild.py applies them).

First stage: Nacht's geometry with the base map's materials. Replaced: streaming trees, BSP planes and nodes, cells
(AABB trees, portals, probe lists), vertices (quantized per surface), the second vertex stream, indices, brush models,
shadow geometry lists (emptied), the sorted surface list and the surfaces. Everything else (sun, fog, light grid,
probes, lightmaps, materials, static models) stays the base map's for now. Layouts: docs/bo1_maps.md.

Alignment: data between edited regions must keep its alignment, so each region's size change is kept a multiple of
128 (or 16 where noted), and the whole asset's a multiple of 4096 (sound banks later in the zone align to 2048).
"""
import math
import os
import struct

# Nuketown's render world (zm_nuked.ff asset 1040, from asset_trace.py): absolute file positions in the decoded zone
# and block 5 offsets of each region's first array and of the next untouched data.
BASE = {
    "header": 0x341C784,
    "stream": (0x341CBE4, 0x34345EC, 0x2EC0F50, 0x2ED8958),     # streaming trees + leafRefs
    "bsp": (0x34351F0, 0x3499A29, 0x2ED955C, 0x2F3DDEC),        # planes, nodes, cells with trees/portals/probes
    "verts": (0x349C852, 0x3AEB5D6, 0x2F3F580, 0x358E354),      # vd0, second stream, indices
    "models": (0x3D90CC6, 0x3D92FC6, 0x3833A50, 0x3835D50),
    # shadow lists ... surfaces, as one region; the middle parts are copied: (file start, file end, b5 start, b5 end)
    "tail": (0x3DC6376, 0x3EC6CA4, 0x3854A28, 0x3955380),
    "tail_middle": (0x3DC7246, 0x3DC86AA, 0x38558F8, 0x3856D80),  # light regions, visibility data
    "tail_smodels": (0x3DCD3BC, 0x3DDF884, 0x385BA94, 0x386DF5C),  # static model instances
    "vd0_size": 0x523A30, "s2_default": 0x528CC, "s2_size": 0x68444,
    "primary_lights": 18, "probes": 26,
    # the material list (465 entries of 8 bytes) and where Nuketown's inline materials end (file, block 5);
    # the last material image's pixels end at this block 3 offset
    "mat_array_end": (0x3D93E4E, 0x3836BD8), "mat_count": 465, "mats_end": 0x3854A18, "b3_insert": 0xBFF000,
    # the world's outdoor image loads right after the materials: header + name (file), 16 bytes of block 5
    "outdoor": (0x3DC6299, 0x3DC6376, 0x10),
}
BLOCK = 5
# a surface's primary light index is BO1's numbering, which picks one of the base map's lights; False: none (0)
SURFACE_LIGHTS = True
SURFACE_PROBES = True  # likewise the reflection probe indices (surfaces, cell lists); False: probe 0


def u32(v):
    return struct.pack(">I", v & 0xFFFFFFFF)


def ref(off):
    return ((BLOCK << 29) | off) + 1


def unorm16(f):
    return max(0, min(65535, round(f * 65535)))


def half(f):
    return struct.unpack(">H", struct.pack(">e", max(-65504.0, min(65504.0, f))))[0]


class Out:
    """One region's file bytes and the block 5 position the loader will have."""

    def __init__(self, pos):
        self.b, self.pos, self.log = bytearray(), pos, []

    def align(self, a):
        self.pos = (self.pos + a) & ~a

    def put(self, data, align=0):
        self.align(align)
        start = self.pos
        self.b += data
        self.pos += len(data)
        self.log.append((start, len(data)))
        return start

    def copy(self, data, span):  # base data copied as is: its file bytes, and the block 5 span it had
        self.b += data
        self.pos += span


class T5World:
    def __init__(self, m, h):
        self.m, self.h = m, h

    def f(self, off):
        return self.m.u32(self.h + off)

    def arr(self, ptr_off, count, size):
        p = self.f(ptr_off)
        return self.m.read(p, count * size) if p and count else b""


def find_material(zone_path, image, name, data):
    """The base surfaces' 8-byte material field (alias slot offset + byte fields) of a plain (flags 0x30) material."""
    import contextlib
    import io
    import zoneload as Z
    f0, f1 = BASE["tail_smodels"][1], BASE["tail"][1]
    keys = {data[k + 0x40:k + 0x48] for k in range(f0, f1 - 95, 96)}
    z = Z.Zone(zone_path, image, "t6")
    with contextlib.redirect_stdout(io.StringIO()):
        z.run(1041)
    for key in sorted(keys):
        if key[7] != 0x30:
            continue
        v = struct.unpack(">I", key[:4])[0]
        slot = Z.BLOCK_BASE + 5 * 0x08000000 + ((v - 1) & 0x1FFFFFFF)
        mat = z.mem.u32(slot)  # the slot holds the material; its first field is the name
        if z.mem.read(z.mem.u32(mat), 96).split(b"\0")[0].decode("latin-1") == name:
            return key
    raise SystemExit(f"material {name} not on the base map's world surfaces")


def convert(m, h, data, material=None, mats=None):
    """m, h: BO1 memory and render world header (zoneload); data: the decoded base zone.
    Returns (edits, patches, total block 5 change) for zone_rebuild.rebuild."""
    w = T5World(m, h)
    edits, patches = [], []
    hdr = BASE["header"]
    moved = [0]

    def patch(off, value):
        patches.append((hdr + off, u32(value)))

    def region(name, build, tries, multiple=128):
        """build(o, extra) for extra = 0, 1, ... until the size change is a multiple of `multiple`."""
        f0, f1, b0, b1 = BASE[name]
        for extra in range(tries):
            o = Out(b0 + moved[0])
            info = build(o, extra)
            delta = o.pos - b1 - moved[0]
            if delta % multiple == 0:
                edits.append((f0, f1, bytes(o.b), {BLOCK: (b1, delta)}))
                moved[0] += delta
                return info, extra
        raise SystemExit(f"{name}: no padding makes the size change a multiple of {multiple}")

    # dummy static surfaces after Nacht's (no draw range covers them): they lengthen the sorted surface list so the
    # last region's size change can reach a multiple of 4096 (its other parts change in steps of 32 bytes)
    surf_n, static_n = w.f(0x10), w.f(0x3B8)
    old_sorted = (BASE["tail_smodels"][2] - BASE["tail_middle"][3])  # Nuketown's list, aligned to 4
    kstatic = next(k for k in range(32) if ((2 * (static_n + k) + 3) & ~3) % 32 == old_sorted % 32)

    def sidx(i):  # surface index after the dummies are inserted
        return i + kstatic if i >= static_n else i

    # ---- streaming trees and leaf references (BO2 lists surfaces only; BO1's negatives are static models) ----
    tree_n, leaf_n = w.f(0x14), w.f(0x1C)
    trees = w.arr(0x18, tree_n, 32)
    leaves = struct.unpack(f">{leaf_n}i", w.arr(0x20, leaf_n, 4))
    before = [0]
    for v in leaves:
        before.append(before[-1] + (v >= 0))
    kept = [sidx(v) for v in leaves if v >= 0]

    def build_stream(o, extra):
        tb = bytearray()
        for i in range(tree_n):
            first, count, child, nchild = struct.unpack_from(">HHHH", trees, 32 * i)
            mins, maxs = struct.unpack_from(">3f", trees, 32 * i + 8), struct.unpack_from(">3f", trees, 32 * i + 20)
            size = sum((b - a) ** 2 for a, b in zip(mins, maxs))  # BO2's extra float: a size measure
            tb += struct.pack(">3fI3fIfHHHHI", *mins, 0, *maxs, 0, size, before[first],
                              before[first + count] - before[first], child, nchild, 0)
        o.put(bytes(tb), 15)
        o.put(b"".join(u32(v) for v in kept + [0] * extra), 3)  # extra: unused references (padding)
        return len(kept) + extra

    leaf_total, _ = region("stream", build_stream, 64)
    patch(0x14, tree_n)
    patch(0x1C, leaf_total)

    # ---- BSP planes and nodes; cells with their AABB trees, portals (+ bounds) and probe lists ----
    plane_n, node_n, cell_n = w.f(0x08), w.f(0x0C), w.f(0x154)
    planes, nodes = w.arr(0x158, plane_n, 20), w.arr(0x15C, node_n, 2)
    cells, cell_ptr = w.arr(0x168, cell_n, 56), w.f(0x168)

    def build_bsp(o, extra):
        o.put(planes, 3)
        o.put(nodes + bytes(2 * extra), 1)  # extra: unused nodes (padding)
        body = bytearray()
        for i in range(cell_n):
            c = cells[56 * i:56 * i + 56]
            tcount, pcount, rcount = struct.unpack_from(">I", c, 24)[0], struct.unpack_from(">I", c, 32)[0], c[48]
            body += c[0:24] + u32(tcount) + u32(-1 if tcount else 0) + u32(pcount) + u32(-1 if pcount else 0)
            body += bytes([rcount]) + bytes(3) + u32(-1 if rcount else 0)
        cells_at = o.put(bytes(body), 3)
        for i in range(cell_n):
            c = cells[56 * i:56 * i + 56]
            tcount, tptr = struct.unpack_from(">II", c, 24)
            pcount, pptr = struct.unpack_from(">II", c, 32)
            rcount, rptr = c[48], struct.unpack_from(">I", c, 52)[0]
            if tcount:
                tb = bytearray(m.read(tptr, 40 * tcount))
                for k in range(tcount):  # no static model lists (BO1's static models are not converted)
                    struct.pack_into(">HI", tb, 40 * k + 0x1E, 0, 0)  # smodelIndexCount, smodelIndexes
                o.put(bytes(tb), 3)
            if pcount:
                pb, verts = bytearray(), []
                for k in range(pcount):
                    p = m.read(pptr + 68 * k, 68)
                    vptr, vcount = struct.unpack_from(">I", p, 0x24)[0], p[0x28]
                    vb = m.read(vptr, 12 * vcount) if vcount and vptr else b""
                    pts = [struct.unpack_from(">3f", vb, 12 * j) for j in range(vcount)] or [(0.0, 0.0, 0.0)]
                    lo = [min(q[a] for q in pts) for a in range(3)]
                    hi = [max(q[a] for q in pts) for a in range(3)]
                    target = (struct.unpack_from(">I", p, 0x20)[0] - cell_ptr) // 56
                    pb += p[0:0x20] + u32(ref(cells_at + 48 * target)) + u32(-1 if vb else 0) + p[0x28:0x44]
                    pb += struct.pack(">6f", *lo, *hi)
                    verts.append(vb)
                o.put(bytes(pb), 3)
                for vb in verts:
                    if vb:
                        o.put(vb, 3)
            if rcount:
                o.put(m.read(rptr, rcount) if SURFACE_PROBES else bytes(rcount), 0)  # BO1 probe indices
        o.align(3)  # the reflection probes follow
        return extra

    extra_nodes, _ = region("bsp", build_bsp, 64)
    patch(0x08, plane_n)
    patch(0x0C, node_n + extra_nodes)
    patch(0x174, cell_n)

    # ---- vertices: each surface gets its own quantized copy of the vertices it uses (28 bytes each) ----
    surf_n, static_n = w.f(0x10), w.f(0x3B8)
    surfs = w.arr(0x408, surf_n, 80)
    vptr, iptr = w.f(0x20C), w.f(0x260)
    vd0, idx, surf_info = bytearray(), [], []
    for s in range(surf_n):
        b = surfs[80 * s:80 * s + 80]
        fv = struct.unpack_from(">I", b, 0x1C)[0]
        tc = struct.unpack_from(">H", b, 0x22)[0]
        bi = struct.unpack_from(">I", b, 0x24)[0]
        ix = struct.unpack(f">{3 * tc}H", m.read(iptr + 2 * bi, 6 * tc)) if tc else ()
        used = sorted(set(ix))
        remap = {v: n for n, v in enumerate(used)}
        mins, maxs = struct.unpack_from(">3f", b, 0x38), struct.unpack_from(">3f", b, 0x44)
        center = [(a + c) / 2 for a, c in zip(mins, maxs)]
        extent = max([c - a for a, c in zip(mins, maxs)] + [1.0])
        scale = 2.0 ** max(-2, math.ceil(math.log2(extent / 2 / 32000)))  # Nuketown uses 0.25
        while len(vd0) % 16:
            vd0 += b"\0"
        vo0 = len(vd0)
        for v in used:
            raw = m.read(vptr + 44 * (fv + v), 44)
            x, y, z, bsign = struct.unpack_from(">4f", raw, 0)
            q = [max(-32768, min(32767, round((c - o_) / scale))) for c, o_ in zip((x, y, z), center)]
            u, t = struct.unpack_from(">2f", raw, 20)
            lu, lt = struct.unpack_from(">2f", raw, 28)
            vd0 += struct.pack(">4h", *q, -1 if bsign < 0 else 1) + raw[16:20] + struct.pack(">2H", half(u), half(t))
            vd0 += raw[36:40] + raw[40:44] + struct.pack(">2H", unorm16(lu), unorm16(lt))  # lightmap UV: 2 x unorm16
        surf_info.append((center, scale, vo0, len(used), len(idx), tc))
        idx.extend(remap[v] for v in ix)
    longest = max([i[3] for i in surf_info] + [1])
    s2_file = BASE["verts"][0] + BASE["vd0_size"]
    default = data[s2_file + BASE["s2_default"]:s2_file + BASE["s2_size"]]
    s2 = (default * (8 * longest // len(default) + 1))[:8 * longest]  # one shared block for every surface

    def build_verts(o, extra):
        o.put(bytes(vd0), 127)
        o.put(s2, 127)
        o.put(b"".join(struct.pack(">H", v) for v in idx) + bytes(4 * extra), 3)  # extra: unused indices
        o.align(3)
        return extra

    extra_idx, _ = region("verts", build_verts, 64)
    patch(0x1A8, len(vd0) // 28)
    patch(0x1AC, len(vd0))
    patch(0x1DC, len(s2))
    patch(0x204, len(idx) + 2 * extra_idx)

    # ---- brush models (60 -> 64 bytes) and the world bounds ----
    model_n = w.f(0x2BC)
    models = w.arr(0x2C0, model_n, 60)

    mat_list = {}  # with mats: the materialMemory list grows (the region then runs to its end)
    if mats:
        f0, f1, b0, b1 = BASE["models"]
        arr_f0 = f1
        BASE["models"] = (f0, BASE["mat_array_end"][0], b0, BASE["mat_array_end"][1])
        old_list = data[arr_f0:BASE["mat_array_end"][0]]
        memory = old_list[4:8]  # the first entry's memory size, for every new entry

    def build_models(o, extra):
        body = bytearray()
        for i in range(model_n):
            mdl = models[60 * i:60 * i + 60]
            start = struct.unpack_from(">i", mdl, 56)[0]
            body += mdl[0:28] + bytes(4) + mdl[28:56] + struct.pack(">i", sidx(start) if start >= 0 else start)
        body = bytes(body)
        nmodels, npad = (extra % 2, extra // 2) if mats else (extra, 0)
        dummy = bytes(56) + u32(0) + u32(-1)  # extra models with no surfaces (padding)
        o.put(body + dummy * nmodels, 3)
        if mats:  # the material list: Nuketown's entries, then the new materials, then padding materials
            mat_list["at"] = o.put(old_list + (u32(-1) + memory) * (mats["count"] + npad), 3)
            mat_list["pad"] = npad
        o.align(3)
        return nmodels

    extra_models, _ = region("models", build_models, 64 if mats else 4)
    patch(0x274, model_n + extra_models)
    if mats:
        patch(0x298, BASE["mat_count"] + mats["count"] + mat_list["pad"])
    for k in range(6):
        patch(0x27C + 4 * k, w.f(0x2C4 + 4 * k))

    # the material every surface uses for now: the base map's most used world material (block 5, after the edits
    # above, so its new offset includes their changes)
    tf0, tf1, tb0, tb1 = BASE["tail"]
    base_surfs = data[BASE["tail_smodels"][1]:tf1]
    count = {}
    for k in range(len(base_surfs) // 96):
        key = base_surfs[96 * k + 0x40:96 * k + 0x48]
        count[key] = count.get(key, 0) + 1
    # plain quantized-world surfaces (flags 0x30: e.g. wqc/wood_burned); "wpc" materials expect another vertex format
    common = material or max((k for k in count if k[7] == 0x30), key=count.get)
    mat = ((struct.unpack(">I", common[0:4])[0] - 1) & 0x1FFFFFFF) + moved[0]

    # ---- shadow lists, (copied) light regions and visibility data, sorted surfaces, (copied) static model
    # instances, surfaces: one region. Padding: the first light's static model list (2-byte steps) and dummy
    # surfaces at the end (96 bytes each) ----
    mf0, mf1, mb0, mb1 = BASE["tail_middle"]
    sf0, sf1, sb0, sb1 = BASE["tail_smodels"]
    sorted_idx = w.arr(0x400, static_n, 2) + b"".join(struct.pack(">H", static_n + k) for k in range(kstatic))
    out = bytearray()
    for s in range(surf_n):
        b = surfs[80 * s:80 * s + 80]
        if s == static_n:
            out += bytes(96) * kstatic  # the dummy static surfaces
        center, scale, vo0, n, base_index, tc = surf_info[s]
        kind = mats["surf_kind"][s] if mats else "opaque"
        if kind == "hidden":  # sky and shadow-only surfaces: no triangles (BO2 draws its sky with the sky model)
            tc = 0
        out += struct.pack(">4f", *center, scale)
        out += b[0x00:0x0C] + u32(vo0) + b[0x10:0x1C] + u32(0)  # vertex offsets: vd0 bytes, second stream
        out += u32(0) + b[0x28:0x2C] + struct.pack(">HHI", n, tc, base_index)
        mref = mat_list["at"] + 8 * (BASE["mat_count"] + mats["surf_map"][s]) if mats else mat
        light = min(b[0x36], BASE["primary_lights"] - 1) if SURFACE_LIGHTS else 0
        probe = min(b[0x35], BASE["probes"] - 1) if SURFACE_PROBES else 0
        # flags: high nibble 3 for opaque world surfaces, 2 for blend layers and decals (as Nuketown's)
        flags = (common[7] & 0x0F) | (0x20 if kind in ("blend", "decal") else common[7] & 0xF0)
        out += u32(ref(mref)) + bytes([0, probe, light, flags])
        out += b[0x38:0x50]
    if surf_n == static_n:
        out += bytes(96) * kstatic
    surface_bytes = bytes(out)

    pieces = (mats["pieces"] + [p for k in range(mat_list["pad"]) for p in mats["pad"](k)]) if mats else []

    def build_tail(o, extra):
        nlist, ndummy = extra % 64, extra // 64
        for piece in pieces:  # the new materials, loaded after Nuketown's (temp-block parts take no block 5 space)
            if piece[0] == "temp":
                o.b += piece[1]
            else:
                o.put(piece[1], piece[2])
        if mats:  # the outdoor image, as it was
            of0, of1, ospan = BASE["outdoor"]
            o.copy(data[of0:of1], ospan)
        lights = bytearray(12 * BASE["primary_lights"])
        if nlist:  # padding: the first light's static model list (Nuketown's model 0, far away)
            struct.pack_into(">HHII", lights, 0, 0, nlist, 0, 0xFFFFFFFF)
        o.put(bytes(lights), 3)
        if nlist:
            o.put(bytes(2 * nlist), 1)
        o.align(3)
        if (o.pos - mb0 - moved[0]) % 128:  # the visibility data in the copied part is 128-aligned
            return None
        o.copy(data[mf0:mf1], mb1 - mb0)
        o.put(sorted_idx, 1)
        o.align(3)
        o.copy(data[sf0:sf1], sb1 - sb0)
        o.put(surface_bytes + bytes(96) * ndummy, 15)
        o.align(3)
        return ndummy

    # the last region also brings the whole asset's change to a multiple of 4096
    f0, f1, b0, b1 = BASE["tail"]
    if mats:
        b0 = BASE["mats_end"]  # the new materials start where Nuketown's last one ended
        f0 = BASE["outdoor"][0]
    for extra in range(64 * 160):
        o = Out(b0 + moved[0])
        ndummy = build_tail(o, extra)
        if ndummy is None:
            continue
        delta = o.pos - b1 - moved[0]
        if (moved[0] + delta) % 4096 == 0:
            if os.environ.get("T6GFX_TAIL_LOG"):  # debugging: the planned block 5 position of each piece
                with open(os.environ["T6GFX_TAIL_LOG"], "w") as f:
                    f.writelines(f"{s:#x} {n:#x}\n" for s, n in o.log)
            edits.append((f0, f1, bytes(o.b), {BLOCK: (b1, delta)}))
            moved[0] += delta
            break
    else:
        raise SystemExit("tail: no padding makes the asset's size change a multiple of 4096")
    patch(0x10, surf_n + kstatic + ndummy)
    lit0, lit1, dec0, dec1, em0, em1 = (w.f(0x3BC + 4 * k) for k in range(6))
    total_static = static_n + kstatic
    for off, v in ((0x370, total_static), (0x374, lit0), (0x378, lit1), (0x37C, dec0), (0x380, dec1),
                   (0x384, em0), (0x388, em1), (0x38C, em1), (0x390, em1), (0x398, (total_static + 127) // 128 * 128)):
        patch(off, v)
    if mats and mats["pixels"]:  # the new images' pixels: in block 3 (stored at the file's end), after Nuketown's
        px = b"".join(mats["pixels"])
        block3_file = len(data) - struct.unpack_from(">I", data, 8 + 4 * 3)[0]
        at = block3_file + BASE["b3_insert"]
        edits.append((at, at, px, {3: (BASE["b3_insert"], len(px))}))
    return edits, patches, moved[0]
