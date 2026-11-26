"""Build a BO2 world lightmap (DXT5, three stacked tiles) from a BO1 map's lightmaps.

BO1 (pimp_shader_lmap, translated from Nacht's zone): secondaryB (16_16) holds two intensities X, Y (* 31.875);
secondary (5_6_5, two halves stacked: top s1 at v/2, bottom s2 at v/2 + 1/2) holds chroma in R and B (green implied)
and a direction term in G. Per texel:
    a = s2.g * 4 - 2, b = s1.g * 4 - 2, w = saturate(0.4 + 0.6 * 2^-(a^2 + b^2))
    R = 4X s1.r + 4wY s2.r,  G = 2X(1 - s1.r - s1.b) + 2wY(1 - s2.r - s2.b),  B = 4X s1.b + 4wY s2.b
BO2 (pimp_shader_lmap): tile 0 ambient rgb / a, tile 1 directional rgb / a, tile 2 direction (xyz * 2 - 1).
First stage: all of BO1's light goes to the ambient tile; the directional tile is black, the direction points up.
"""
import numpy as np

import xenos_tex as X


def tiled_index(w, h, bpb):
    """For each linear block (row-major, w x h blocks), its block index in the tiled surface."""
    ys, xs = np.mgrid[0:h, 0:w]
    xs, ys = xs.ravel().astype(np.int64), ys.ravel().astype(np.int64)
    aligned = (w + 31) & ~31
    log_bpp = (bpb >> 2) + ((bpb >> 1) >> (bpb >> 2))
    macro = ((xs >> 5) + (ys >> 5) * (aligned >> 5)) << (log_bpp + 7)
    micro = ((xs & 7) + ((ys & 6) << 2)) << log_bpp
    off = macro + ((micro & ~15) << 1) + (micro & 15) + ((ys & 8) << (3 + log_bpp)) + ((ys & 1) << 4)
    return ((((off & ~511) << 3) + ((off & 448) << 2) + (off & 63) + ((ys & 16) << 7) +
             (((((ys & 8) >> 2) + (xs >> 3)) & 3) << 6)) >> log_bpp)


def untile(data, w, h, bpb):
    idx = tiled_index(w, h, bpb)
    src = np.frombuffer(data, np.uint8)
    blocks = src[(idx[:, None] * bpb + np.arange(bpb)).ravel()]
    return blocks.reshape(h, w, bpb)


def tile(blocks, w, h, bpb):
    aw, ah = (w + 31) & ~31, (h + 31) & ~31
    out = np.zeros(aw * ah * bpb, np.uint8)
    idx = tiled_index(w, h, bpb)
    out[(idx[:, None] * bpb + np.arange(bpb)).ravel()] = blocks.reshape(-1)
    return out.tobytes()


def swap16(a):
    return a.reshape(-1, 2)[:, ::-1].reshape(a.shape)


def bo1_light(secondary, secondary_b, w, h):
    """secondary: raw tiled 5_6_5, w x 2h; secondary_b: raw tiled 16_16, w x h. Returns float32 (h, w, 3)."""
    s = swap16(untile(secondary, w, 2 * h, 2)).reshape(2 * h, w, 2).astype(np.uint16)
    v = s[..., 0] | (s[..., 1] << 8)
    r, g, b = ((v >> 11) & 31) / 31.0, ((v >> 5) & 63) / 63.0, (v & 31) / 31.0
    s1 = (r[:h], g[:h], b[:h])
    s2 = (r[h:], g[h:], b[h:])
    t = swap16(untile(secondary_b, w, h, 4)).reshape(h, w, 4).astype(np.uint32)
    xi = (t[..., 0] | (t[..., 1] << 8)) / 65535.0 * 31.875
    yi = (t[..., 2] | (t[..., 3] << 8)) / 65535.0 * 31.875
    a = s2[1] * 4 - 2
    bb = s1[1] * 4 - 2
    wgt = np.clip(0.4 + 0.6 * np.exp2(-(a * a + bb * bb)), 0, 1)
    R = 4 * xi * s1[0] + 4 * wgt * yi * s2[0]
    G = 2 * xi * (1 - s1[0] - s1[2]) + 2 * wgt * yi * (1 - s2[0] - s2[2])
    B = 4 * xi * s1[2] + 4 * wgt * yi * s2[2]
    return np.clip(np.stack([R, G, B], -1), 0, None).astype(np.float32)


def rgba_over_a(light):
    """BO2's rgb / a encoding: rgb = light / m, a = 1 / m with m = max(1, max channel)."""
    m = np.maximum(1.0, light.max(-1))
    m = np.minimum(m, 255.0)
    return np.concatenate([light / m[..., None], (1.0 / m)[..., None]], -1)


def dxt5(img):
    """img: float (H, W, 4) in 0..1, H and W multiples of 4. Returns (H/4, W/4, 16) uint8 little-endian blocks."""
    h, w = img.shape[:2]
    q = np.clip(np.round(img * 255), 0, 255).astype(np.int32)
    blk = q.reshape(h // 4, 4, w // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(h // 4, w // 4, 16, 4)
    # alpha: 8-value mode (a0 > a1), indices by nearest
    a = blk[..., 3]
    a0, a1 = a.max(-1), a.min(-1)
    a0 = np.where(a0 == a1, np.minimum(a0 + 1, 255), a0)
    a1 = np.where(a0 == a1, np.maximum(a1 - 1, 0), a1)
    pal = np.stack([a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)], -1)  # (.., 8)
    ai = np.abs(a[..., :, None] - pal[..., None, :]).argmin(-1).astype(np.uint64)
    abits = np.zeros(ai.shape[:-1], np.uint64)
    for k in range(16):
        abits |= ai[..., k] << np.uint64(3 * k)
    # color: endpoints = per-channel max / min, 4-color mode (c0 > c1), indices by nearest
    c = blk[..., :3]
    hi, lo = c.max(-2), c.min(-2)

    def to565(x):
        return ((x[..., 0] >> 3) << 11) | ((x[..., 1] >> 2) << 5) | (x[..., 2] >> 3)

    c0, c1 = to565(hi), to565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    hi, lo = np.where(swap[..., None], lo, hi), np.where(swap[..., None], hi, lo)
    same = c0 == c1
    cpal = np.stack([hi, lo, (2 * hi + lo) // 3, (hi + 2 * lo) // 3], -2)  # (.., 4, 3)
    d = ((c[..., :, None, :] - cpal[..., None, :, :]) ** 2).sum(-1)
    ci = np.where(same[..., None], 0, d.argmin(-1)).astype(np.uint32)
    cbits = np.zeros(ci.shape[:-1], np.uint32)
    for k in range(16):
        cbits |= ci[..., k] << np.uint32(2 * k)
    out = np.zeros(c0.shape + (16,), np.uint8)
    out[..., 0], out[..., 1] = a0, a1
    for k in range(6):
        out[..., 2 + k] = (abits >> np.uint64(8 * k)) & np.uint64(255)
    out[..., 8], out[..., 9] = c0 & 255, c0 >> 8
    out[..., 10], out[..., 11] = c1 & 255, c1 >> 8
    for k in range(4):
        out[..., 12 + k] = (cbits >> np.uint32(8 * k)) & np.uint32(255)
    return out


def build(light, width, height):
    """BO2 lightmap pixels (tiled, 8-in-16) of width x height (height = 3 tiles) from a light image (h, w, 3)."""
    th = height // 3
    ys = (np.arange(th) * light.shape[0] // th).clip(0, light.shape[0] - 1)
    xs = (np.arange(width) * light.shape[1] // width).clip(0, light.shape[1] - 1)
    amb = rgba_over_a(light[ys][:, xs][..., ::-1])  # the 360 reads these DXT colors blue-first: swap R and B
    black = np.zeros((th, width, 4), np.float32)
    black[..., 3] = 1.0
    up = np.zeros((th, width, 4), np.float32)
    up[...] = (0.5, 0.5, 1.0, 1.0)
    img = np.concatenate([amb, black, up], 0)
    blocks = dxt5(img)
    tiled = np.frombuffer(tile(blocks, width // 4, height // 4, 16), np.uint8)
    return swap16(tiled.copy()).tobytes()


def preview(light, path):
    v = np.clip(np.sqrt(light / max(1e-6, np.percentile(light, 99))) * 255, 0, 255).astype(np.uint8)
    X.png(path, v.shape[1], v.shape[0], [bytes(r) for r in v.reshape(v.shape[0], -1)])
