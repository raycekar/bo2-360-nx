"""Xbox 360 (Xenos) texture helpers: tiled block addressing, 8-in-16 byte order, DXT1/DXT5 blocks, a PNG writer for
checks. usage (check): python -I xenos_tex.py <zone> <file pos hex> <width> <height> dxt1|dxt5 <out.png>"""
import struct
import sys
import zlib


def tiled_offset(x, y, width_blocks, bytes_per_block):
    """Index (in blocks) of block (x, y) in a tiled 2D surface (XGAddress2DTiledOffset)."""
    aligned = (width_blocks + 31) & ~31
    log_bpp = (bytes_per_block >> 2) + ((bytes_per_block >> 1) >> (bytes_per_block >> 2))
    macro = ((x >> 5) + (y >> 5) * (aligned >> 5)) << (log_bpp + 7)
    micro = ((x & 7) + ((y & 6) << 2)) << log_bpp
    offset = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + log_bpp)) + ((y & 1) << 4)
    return (((offset & ~511) << 3) + ((offset & 448) << 2) + (offset & 63) + ((y & 16) << 7) +
            (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)) >> log_bpp


def swap16(b):
    """8-in-16 byte order <-> little endian (swap each pair of bytes)."""
    a = bytearray(b)
    a[0::2], a[1::2] = b[1::2], b[0::2]
    return bytes(a)


def untile(data, w, h, bpb):
    """Linear (row-major) blocks from a tiled surface; w, h in blocks."""
    out = bytearray(w * h * bpb)
    for y in range(h):
        for x in range(w):
            o = tiled_offset(x, y, w, bpb) * bpb
            out[(y * w + x) * bpb:(y * w + x + 1) * bpb] = data[o:o + bpb]
    return bytes(out)


def tile(linear, w, h, bpb):
    """The tiled surface for linear blocks; its size is the aligned surface size."""
    aw, ah = (w + 31) & ~31, (h + 31) & ~31
    out = bytearray(aw * ah * bpb)
    for y in range(h):
        for x in range(w):
            o = tiled_offset(x, y, w, bpb) * bpb
            out[o:o + bpb] = linear[(y * w + x) * bpb:(y * w + x + 1) * bpb]
    return bytes(out)


def rgb565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def dxt1_colors(block):
    """block: 8 bytes, little endian (after swap16)."""
    c0, c1, bits = struct.unpack("<HHI", block)
    a, b = rgb565(c0), rgb565(c1)
    if c0 > c1:
        pal = [a, b, tuple((2 * p + q) // 3 for p, q in zip(a, b)), tuple((p + 2 * q) // 3 for p, q in zip(a, b))]
    else:
        pal = [a, b, tuple((p + q) // 2 for p, q in zip(a, b)), (0, 0, 0)]
    return [pal[(bits >> (2 * i)) & 3] for i in range(16)]


def png(path, w, h, rgb_rows):
    raw = b"".join(b"\0" + bytes(r) for r in rgb_rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
                           chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def main():
    zone, pos, w, h, fmt, out = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], \
        sys.argv[6]
    if fmt == "565":  # one pixel per "block"
        data = open(zone, "rb").read()[pos:pos + w * h * 2 * 2]
        lin = swap16(untile(data, w, h, 2))
        step = max(1, w // 512)
        rows = [bytearray(b"".join(bytes(rgb565(struct.unpack_from("<H", lin, 2 * (y * w + x))[0]))
                                   for x in range(0, w, step))) for y in range(0, h, step)]
        png(out, len(range(0, w, step)), len(rows), rows)
        print("wrote", out)
        return
    bpb = 8 if fmt == "dxt1" else 16
    bw, bh = w // 4, h // 4
    data = open(zone, "rb").read()[pos:pos + bw * bh * bpb * 2]
    lin = swap16(untile(data, bw, bh, bpb))
    step = max(1, w // 512)  # a small preview
    rows = []
    for py in range(0, h, step):
        row = bytearray()
        by, iy = py // 4, py % 4
        for px in range(0, w, step):
            bx, ix = px // 4, px % 4
            blk = lin[(by * bw + bx) * bpb:(by * bw + bx + 1) * bpb]
            row += bytes(dxt1_colors(blk[-8:])[iy * 4 + ix])
        rows.append(row)
    png(out, len(range(0, w, step)), len(rows), rows)
    print("wrote", out)


if __name__ == "__main__":
    main()
