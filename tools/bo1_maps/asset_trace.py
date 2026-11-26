"""Trace how one asset streams in: every Load_Stream (caller, block, size, destination) and pointer conversion, with the
header field that ends up pointing at each destination.
usage: python -I asset_trace.py <zone> t5|t6 <asset index> <out.txt> <header size> <program image>"""
import contextlib
import io
import struct
import sys

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import zoneload as Z  # noqa: E402

zone, game, want, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
hsize = int(sys.argv[5], 0) if len(sys.argv) > 5 else 0x400
image = sys.argv[6] if len(sys.argv) > 6 else ""  # the decrypted program: BO1 default.image.bin / BO2 default_mp.image.bin
if not image:
    raise SystemExit("pass the decrypted program image as the 6th argument")
z = Z.Zone(zone, image, game)
log, state = [], {"on": False, "n": 0, "header": None}
orig_stream, orig_ptr, orig_call = z.hle_load_stream, z.hle_to_pointer, z.call


def stream():
    if state["on"]:
        at_start, ptr, size = z.r[3] & 0xFF, z.r[4] & 0xFFFFFFFF, Z.s32(z.r[5])
        if at_start and size:
            if state["header"] is None:
                state["header"] = ptr
            log.append(("S", z.lr, z.index, size, ptr, z.fpos))
    orig_stream()


def to_ptr():
    if state["on"]:
        pp = z.r[3]
        log.append(("P", z.lr, z.index, 0, pp, z.mem.u32(pp)))
    orig_ptr()


z.hle[z.p["load_stream"]] = stream
z.hle[z.p["to_pointer"]] = to_ptr


def call(addr, *args):
    if addr == z.p["load_xasset"]:
        state["on"] = state["n"] == want
        state["n"] += 1
        r = orig_call(addr, *args)
        if state["on"]:
            state["on"] = False
            raise StopIteration
        return r
    return orig_call(addr, *args)


z.call = call
try:
    with contextlib.redirect_stdout(io.StringIO()):
        z.run()
except RuntimeError as e:
    if not isinstance(e.__cause__, StopIteration):
        raise
h = state["header"]
# the header was copied to the pool by DB_LinkXAssetEntry; read the final header from the last pool copy
header = z.mem.read(z.pool - 0x2000, hsize)
fields = {}
for off in range(0, hsize, 4):
    fields.setdefault(struct.unpack_from(">I", header, off)[0], []).append(off)
with open(out, "w") as f:
    f.write(f"header at {h:#x}; {len(log)} events\n")
    for kind, lr, block, size, ptr, extra in log:
        if kind == "S":
            hf = fields.get(ptr, [])
            f.write(f"S lr={lr:08X} block={block} size={size:#x} dest={ptr:#x}"
                    f"{' hdr+' + ','.join(hex(o) for o in hf) if hf else ''} file={extra:#x}\n")
        else:
            rel = f" hdr+{ptr - h:#x}" if h and 0 <= ptr - h < hsize else ""
            f.write(f"P lr={lr:08X} at={ptr:#x}{rel} value={extra:#x}\n")
    f.write("final header words:\n")
    for off in range(0, hsize, 16):
        f.write(f"{off:04x}: " + " ".join(f"{w:08x}" for w in struct.unpack_from(">4I", header, off)) + "\n")
print(out, len(log), "events")

