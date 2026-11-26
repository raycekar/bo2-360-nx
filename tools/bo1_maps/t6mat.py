"""Nacht's own textures in the converted render world: one BO2 material per unique BO1 color texture.

Each new material copies a base-map world material (`TEMPLATE`, e.g. wqc/wood_burned: a normal map and a color map,
both referencing images loaded earlier) and swaps the color map for an inline image holding the BO1 texture's pixels
(both games use Xbox 360 GPU textures: the first 0x50 bytes of a BO1 image header carry over, the pixels copy as
they are). Materials are appended to the world's materialMemory list; surfaces point at their entry's pointer field.

BO2 material record (stream order): header 0x68 (name -1, 0x4C: texture/constant/stateBits counts, 0x54 technique
set, 0x58 textures -1, 0x5C constants, 0x60 stateBits -1), name, textures (16 B each: hash, name start/end, sampler,
semantic, 0, image), per inline image: header 0xD4 (name -1 at 0xCC) + name (pixels in block 3), stateBits (8 B each).
"""
import contextlib
import io
import struct

import zoneload as Z

T5_IMAGE = 9


def image_key(m, hdr_addr):
    """An image header's identity that survives the copies: its name hash and its fetch constant's size word."""
    return m.read(hdr_addr + 0x98, 4) + m.read(hdr_addr + 0x24, 4)


def bo1_images(zone, image, stop):
    """Runs BO1's loader; returns (zone, {image key: (block 2 offset, size)}): each image header (0x9C, temp block)
    is followed by its pixels' read in block 2."""
    z = Z.Zone(zone, image, "t5")
    last_header = [None]
    out = {}
    orig_stream = z.hle_load_stream

    def stream():
        at_start, ptr, size = z.r[3] & 0xFF, z.r[4] & 0xFFFFFFFF, Z.s32(z.r[5])
        is_header = at_start and size == 0x9C and z.index == 0
        orig_stream()
        if is_header:
            last_header[0] = ptr
        elif at_start and size and z.index in (2, 6) and last_header[0] is not None:
            # block 2 is stored after the stream (offset in it); block 6 inline in the stream (file position)
            where = ("b2", ptr - Z.BLOCK_BASE - 2 * 0x08000000) if z.index == 2 else ("file", z.fpos - size)
            out[image_key(z.mem, last_header[0])] = (where, size)
            last_header[0] = None

    z.hle[z.p["load_stream"]] = stream
    with contextlib.redirect_stdout(io.StringIO()):
        z.run(stop)
    return z, out


def color_image(m, mat):
    """A BO1 material's primary color map image (semantic 2, 'c' 'p'), or None."""
    count = m.read(mat, 0x80)[0x67]
    table = m.u32(mat + 0x74)
    for e in range(count):
        _, ns, ne, _, sem, _, img = struct.unpack(">IBBBBII", m.read(table + 16 * e, 16))
        if sem == 2 and ns == ord("c") and ne == ord("p"):
            return img
    return None


def template(data, rec_pos):
    """The base material record at rec_pos: header, its name length, texture table, stateBits."""
    hdr = bytearray(data[rec_pos:rec_pos + 0x68])
    name_end = data.index(b"\0", rec_pos + 0x68) + 1
    tcount, ccount, scount = hdr[0x4C], hdr[0x4D], hdr[0x4E]
    p = name_end
    textures = data[p:p + 16 * tcount]
    p += 16 * tcount
    assert all(struct.unpack_from(">I", textures, 16 * e + 12)[0] != 0xFFFFFFFF for e in range(tcount)), \
        "template textures must all reference earlier images"
    consts = data[p:p + 32 * ccount]
    p += 32 * ccount
    bits = data[p:p + 8 * scount]
    return hdr, textures, consts, bits


def streamed(m, img, packs):
    """(header, pixels) of a streamed BO1 image's largest mip from its image pack, as a one-level image; or None.
    From 0x54 the header lists up to 4 mip parts of 12 bytes: u32 (offset << 4 | level), u16 width, u16 height,
    u32 part id (top byte: pack type, see pak2.py)."""
    hdr = bytearray(m.read(img, 0x9C))
    best = None
    for k in range(4):
        _, w, h, pid = struct.unpack_from(">IHHI", hdr, 0x54 + 12 * k)
        if pid and (best is None or w * h > best[0] * best[1]):
            best = (w, h, pid)
    if best is None or (best[2] >> 24) not in packs:
        return None
    w, h, pid = best
    px = packs[pid >> 24].pixels(pid & 0xFFFFFF)
    if px is None:
        return None
    # a tiled surface spans whole 32 x 32 block tiles; parts under 128 pixels on a side are stored smaller (layout not
    # known yet): pad so the GPU never reads past this image
    bpb = 8 if struct.unpack_from("<I", hdr, 0x20)[0] & 0x3F in (0x12, 0x52) else 16
    tiled = ((w // 4 + 31) & ~31) * ((h // 4 + 31) & ~31) * bpb
    px = px + bytes(max(0, tiled - len(px)))
    # fetch constant (0x1C, six little-endian words): one level, no mip address, no packed mips
    dw4 = struct.unpack_from("<I", hdr, 0x2C)[0] & ~(0xF << 6)
    struct.pack_into("<I", hdr, 0x2C, dw4)
    struct.pack_into("<I", hdr, 0x30, struct.unpack_from("<I", hdr, 0x30)[0] & 0x600)
    struct.pack_into(">IHHHBBI", hdr, 0x38, len(px), w, h, 1, 1, 0, len(px) >> 8)
    return bytes(hdr), px


def image_header(bo1_hdr, image_template):
    """BO2 image header (0xD4) for a BO1 one (0x9C): the D3D texture and size fields carry over."""
    h = bytearray(image_template)
    h[0:0x50] = bo1_hdr[0:0x50]
    h[0x48:0x4C] = b"\xff\xff\xff\xff"  # pixels: inline (in block 3), as in BO2's own images
    h[0x50:0xCC] = bytes(0xCC - 0x50)
    h[0xCC:0xD0] = b"\xff\xff\xff\xff"
    h[0xD0:0xD4] = bo1_hdr[0x98:0x9C]
    return bytes(h)


def build(m, surfs_mats, images, bo1_block2, data, template_pos, image_template, name_of, bo1_file=b"", packs=None):
    """Returns {pieces, pixels (padded to 4096), surf_map (surface -> new material index), count, pad(k)}.
    surfs_mats: BO1 material address per surface; packs: {pack type: pak2.Pak} for streamed images."""
    hdr, textures, consts, bits = template(data, template_pos)
    unique, index_of = [], {}
    surf_map = []
    stream = {}
    for mat in surfs_mats:
        img = color_image(m, mat) if mat else None
        # streamed: no pixels in the zone (a streamed header's size at 0x38 is 0; its key can match an inline image's)
        if img is not None and (image_key(m, img) not in images or m.u32(img + 0x38) == 0):
            if img not in stream:
                stream[img] = streamed(m, img, packs or {})
            if stream[img] is None:
                img = None
        if img not in index_of:
            index_of[img] = len(unique)
            unique.append(img)
        surf_map.append(index_of[img])
    # pieces: ("temp", bytes) in the temp block (no block 5 space), ("b5", bytes, align) in block 5
    pieces, pixels = [], []
    for k, img in enumerate(unique):
        h = bytearray(hdr)
        h[0x00:0x04] = b"\xff\xff\xff\xff"
        tex = bytearray(textures)
        inline = False
        if img:
            for e in range(len(tex) // 16):
                if tex[16 * e + 7] == 2:  # the color map becomes an inline image
                    tex[16 * e + 12:16 * e + 16] = b"\xff\xff\xff\xff"
                    inline = True
        pieces.append(("temp", bytes(h)))
        pieces.append(("b5", f"nacht/{name_of(img) if img else 'none'}_{k}".encode() + b"\0", 0))
        pieces.append(("b5", bytes(tex), 3))
        if inline:
            if img in stream:
                bo1_hdr, px = stream[img]
            else:
                (kind, off), size = images[image_key(m, img)]
                bo1_hdr = m.read(img, 0x9C)
                px = bo1_block2[off:off + size] if kind == "b2" else bo1_file[off:off + size]
            pieces.append(("temp", image_header(bo1_hdr, image_template)))
            pieces.append(("b5", f"nacht_{name_of(img)}_{k}".encode() + b"\0", 0))
            pixels.append(px + bytes((-len(px)) % 4096))
        if consts:
            pieces.append(("b5", consts, 15))
        pieces.append(("b5", bits, 3))
    def pad(k):  # a padding material: the template as it is (its own images), under a new name
        h = bytearray(hdr)
        h[0x00:0x04] = b"\xff\xff\xff\xff"
        out = [("temp", bytes(h)), ("b5", f"nacht/pad_{k}".encode() + b"\0", 0), ("b5", bytes(textures), 3)]
        if consts:
            out.append(("b5", consts, 15))
        return out + [("b5", bits, 3)]

    return {"pieces": pieces, "pixels": pixels, "surf_map": surf_map, "count": len(unique), "pad": pad}
