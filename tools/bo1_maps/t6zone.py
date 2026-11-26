"""Writes small BO2 (T6) Xbox 360 zones: string tables and localized text, the way the TU18 loader reads them.

Zone body (big endian; every pointer -1: the data follows inline; the loader applies alignment in memory only):
  XFile header: size, externalSize, blockSize[8]
  XAssetList: stringList {count, ptr}, dependCount, depends, assetCount, assets (-1), XAsset[] {type, -1}
  LocalizeEntry: {value -1, name -1}, value\\0, name\\0
  StringTable: {name -1, columnCount, rowCount, values -1, cellIndex -1}, name\\0, cells {-1, hash}[], each cell's
  string\\0, cellIndex u16[] (cells sorted by hash, then column)
Fastfile (signed layout, "TAff0100"): version 146, the PHEEBs71 auth block copied from one of the player's own
fastfiles (with this zone's name), then XChunks: [u32 size][deflate (raw, -15) of up to 0x7FC0 bytes], the 40-byte
header in a chunk of its own, Salsa20 per stream (4 streams, 200 IVs each, SHA-1 feedback), as the game's
decrypt_stream expects. The signature does not verify: bo2zm_custom_maps accepts it (app/src/bo2zm_dlc.cpp).
The key is rebuilt from the player's decrypted default_mp image (tools/inspect/ff_shaders.py); it is never written.
"""
import hashlib
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inspect"))
import ff_shaders as F  # noqa: E402

VERSION = 146
STREAMS, PIECE, VIRTUAL_BLOCK = 4, 0x8000 - 0x40, 0x80000
TEMP_BLOCK = 0x12AC  # every retail zone declares this temp block size
ASSET_LOCALIZE, ASSET_STRINGTABLE = 25, 43  # TU18 asset type name table at 0x8296DCF0


def cell_hash(s):
    """The game's string table cell hash: djb2 over lower case (OpenAssetTools Common::Com_HashString, T6)."""
    h = 5381
    for c in s.encode("latin-1"):
        h = (h * 33 + (c | 0x20 if 0x41 <= c <= 0x5A else c)) & 0xFFFFFFFF
    return h - (1 << 32) if h & 0x80000000 else h


def stringtable(name, rows, capacity=0):
    cols = max(len(r) for r in rows)
    rows = [list(r) + [""] * (cols - len(r)) for r in rows] + [[""] * cols] * max(0, capacity - len(rows))
    cells = [c for r in rows for c in r]
    hashes = [cell_hash(c) for c in cells]
    out = bytearray(struct.pack(">iIiii", -1, cols, len(rows), -1, -1)) + name.encode() + b"\0"
    out += b"".join(struct.pack(">ii", -1, h) for h in hashes)
    out += b"".join(c.encode("latin-1") + b"\0" for c in cells)
    order = sorted(range(len(cells)), key=lambda i: (hashes[i], i % cols))
    return bytes(out + b"".join(struct.pack(">H", i) for i in order))


def zone(tables=(), texts=()):
    """tables: (name, rows, capacity); texts: (key, value)."""
    body = bytearray(struct.pack(">iiiiii", 0, 0, 0, 0, len(texts) + len(tables), -1))
    body += struct.pack(">ii", ASSET_LOCALIZE, -1) * len(texts)
    body += struct.pack(">ii", ASSET_STRINGTABLE, -1) * len(tables)
    for key, value in texts:
        body += struct.pack(">ii", -1, -1) + value.encode("latin-1") + b"\0" + key.encode("latin-1") + b"\0"
    for name, rows, capacity in tables:
        body += stringtable(name, rows, capacity)
    virtual = (len(body) + 0x1FFF) & ~0xFFF  # room for the loader's in-memory alignment
    return struct.pack(">II8I", len(body), 0, TEMP_BLOCK, 0, 0, 0, 0, virtual, 0, 0) + bytes(body)


def _encrypt_stream(key, name, stream, chunks):
    nm = name.encode("latin-1")[:31]
    row = STREAMS * 20
    ivs = [bytearray(nm[((i * row + stream * 20 + b) // 4) % len(nm)] for b in range(20)) for i in range(200)]
    out, idx = [], 0
    for plain in chunks:
        out.append(F.xor_bytes(plain, F.salsa20_keystream(key, bytes(ivs[idx][:8]), len(plain))))
        digest = hashlib.sha1(plain).digest()
        idx = (idx + 1) % 200
        for b in range(20):
            ivs[idx][b] ^= digest[b]
    return out


def fastfile(body, name, xex_image, auth_from):
    """body: zone() output; auth_from: any retail BO2 fastfile (its PHEEBs71 block is reused)."""
    auth = open(auth_from, "rb").read()[12:12 + 300]
    assert auth[:8] == b"PHEEBs71", auth_from
    pieces = [body[:40]] + [body[i:i + PIECE] for i in range(40, len(body), PIECE)]
    chunks = []
    for p in pieces:
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        chunks.append(c.compress(p) + c.flush())
    key = F.key_from_xex_image(xex_image)[0]
    for s in range(STREAMS):
        chunks[s::STREAMS] = _encrypt_stream(key, name, s, chunks[s::STREAMS])
    out = bytearray(b"TAff0100" + struct.pack(">I", VERSION) + auth[:12] + name.encode()[:31].ljust(32, b"\0") +
                    auth[44:])
    vb = len(out) % VIRTUAL_BLOCK
    for c in chunks:
        if vb + 4 > VIRTUAL_BLOCK:
            out += bytes(VIRTUAL_BLOCK - vb)
            vb = 0
        out += struct.pack(">I", len(c)) + c
        vb = (vb + 4 + len(c)) % VIRTUAL_BLOCK
    out += bytes(0x40)
    return bytes(out + bytes((-len(out)) % 0x40))
