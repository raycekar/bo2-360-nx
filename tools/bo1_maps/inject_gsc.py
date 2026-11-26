"""Replace compiled GSC scripts (ScriptParseTree assets) inside a decoded BO2 zone, in place.

usage: python -I inject_gsc.py <in zone> <out zone> <compiled root> <script path> [...]
e.g.   ... zm_nacht_patch.zone out.zone compiled/t6 maps/mp/zm_nacht.gsc maps/mp/zm_nacht_standard.gsc

A ScriptParseTree streams as {name = -1, len, buffer = -1}, the name, then len bytes of buffer. The new script must be
no larger than the old one: it is written over the old buffer and zero padded, and len is kept, so every later byte of
the zone keeps its position (the GSC header's own offsets and sizes describe the script; the padding is never read)."""
import struct
import sys

src, dst, root = sys.argv[1:4]
data = bytearray(open(src, "rb").read())
for path in sys.argv[4:]:
    key = path.encode() + b"\0"
    new = open(f"{root}/{path}", "rb").read()
    done = 0
    pos = 0
    while (pos := data.find(key, pos)) >= 0:
        head = data[pos - 12:pos]
        if head[:4] == b"\xff" * 4 and head[8:12] == b"\xff" * 4:
            size = struct.unpack(">I", head[4:8])[0]
            start = pos + len(key)
            assert data[start:start + 4] == b"\x80GSC", f"{path}: no GSC object after the name"
            if len(new) > size:
                raise SystemExit(f"{path}: new script is {len(new)} bytes, the zone has room for {size}")
            data[start:start + size] = new + bytes(size - len(new))
            print(f"{path}: {len(new)} bytes written over {size} at {start:#x}")
            done += 1
        pos += len(key)
    if not done:
        raise SystemExit(f"{path}: not found in {src}")
open(dst, "wb").write(data)
