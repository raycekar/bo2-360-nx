"""Rebuild a decoded BO2 zone with edits that change sizes: replace a file range with new bytes, shift every stored block
offset that points past the edit (reloc_scan.py's table) and fix the header's sizes.

Library: rebuild(data, relocs, edits) with edits = [(f0, f1, new_bytes, {block: (boundary, delta)})], applied
together; offsets inside an edited file range are the new bytes' own business. Deltas should keep alignment (use
multiples of 4096 for physical data, 128 otherwise).
CLI test: python -I zone_rebuild.py grow-script <zone> <relocs.bin> <footprint.json> <script name> <out.zone>"""
import array
import json
import struct
import sys

MASK = 0x1FFFFFFF


def load_relocs(path):
    a = array.array("I")
    a.frombytes(open(path, "rb").read())
    return list(zip(a[0::2], a[1::2]))


def rebuild(data, relocs, edits, interior=None, patches=()):
    """interior: optional {block: [(old start, old end, fn(old offset) -> new offset or None)]} for offsets that point
    inside replaced data from outside it (e.g. an asset-list entry aliasing a header inside the edited asset)."""
    edits = sorted(edits, key=lambda e: e[0])
    shifts = {}  # block -> list of (boundary, delta)
    for f0, f1, new, deltas in edits:
        for block, (boundary, delta) in deltas.items():
            shifts.setdefault(block, []).append((boundary, delta))
    interior = interior or {}
    dangling = []

    def shift(value, fp=None):
        if value in (0, 0xFFFFFFFF, 0xFFFFFFFE):
            return value
        v = (value - 1) & 0xFFFFFFFF
        block, off = v >> 29, v & MASK
        for start, end, fn in interior.get(block, ()):
            if start <= off < end:
                new = fn(off)
                if new is None:
                    dangling.append((fp, block, off))
                    return value
                return ((block << 29) | new) + 1
        moved = sum(delta for boundary, delta in shifts.get(block, ()) if off >= boundary)  # original offset
        return ((block << 29) | (off + moved)) + 1

    def new_pos(fp):
        out = fp
        for f0, f1, new, _ in edits:
            if fp >= f1:
                out += len(new) - (f1 - f0)
        return out

    def inside(fp):
        return any(f0 <= fp < f1 for f0, f1, _, _ in edits)

    out = bytearray()
    last = 0
    for f0, f1, new, _ in edits:
        out += data[last:f0] + new
        last = f1
    out += data[last:]
    changed = mismatched = 0
    for fp, value in relocs:
        if inside(fp):
            continue
        if struct.unpack_from(">I", data, fp)[0] != value:
            mismatched += 1
            continue
        nv = shift(value, fp)
        if nv != value:
            struct.pack_into(">I", out, new_pos(fp), nv)
            changed += 1
    for fp, b in patches:  # same-size overwrites of unrelocated fields (counts), at their new positions
        assert not inside(fp), "patch inside an edited range"
        out[new_pos(fp):new_pos(fp) + len(b)] = b
    struct.pack_into(">I", out, 0, len(out) - 40)
    for block, lst in shifts.items():
        size = struct.unpack_from(">I", out, 8 + 4 * block)[0]
        struct.pack_into(">I", out, 8 + 4 * block, size + sum(d for _, d in lst))
    rebuild.dangling = dangling
    return bytes(out), changed, mismatched


def main():
    if sys.argv[1] != "grow-script":
        raise SystemExit(__doc__)
    zone, relocs_path, fp_path, script, out = sys.argv[2:7]
    data = open(zone, "rb").read()
    key = script.encode() + b"\0"
    pos = data.find(b"\xff" * 4, 0)
    while True:
        pos = data.find(key, pos + 1)
        if pos < 0:
            raise SystemExit("script not found")
        h = data[pos - 12:pos]
        if h[:4] == b"\xff" * 4 and h[8:] == b"\xff" * 4:
            break
    size = struct.unpack(">I", data[pos - 8:pos - 4])[0]
    end = pos + len(key) + size  # the buffer is the asset's last data
    fp = json.load(open(fp_path))
    asset = next(a for a in fp if a[2] <= pos < a[4])
    boundary = asset[5]["5"]  # the asset's block 5 end
    tail = data[end:asset[4]]  # the loader reads the buffer plus a terminator byte
    assert len(tail) <= 4, (hex(asset[4]), hex(end))
    grow = 4096
    new = bytearray(data[pos - 12:end]) + bytes(grow) + tail
    end = asset[4]
    struct.pack_into(">I", new, 4, size + grow)
    rebuilt, changed, mismatched = rebuild(data, load_relocs(relocs_path),
                                           [(pos - 12, end, bytes(new), {5: (boundary, grow)})])
    open(out, "wb").write(rebuilt)
    print(f"asset {asset[0]}: grew by {grow} at block 5 {boundary:#x}; {changed} offsets shifted, "
          f"{mismatched} table entries did not match the file")


if __name__ == "__main__":
    main()
