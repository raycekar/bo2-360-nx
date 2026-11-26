"""Find every stored block offset in a decoded BO2 zone: run the game's own loader (zoneload.py) over the whole zone
and log each pointer conversion (DB_ConvertOffsetToPointer 0x822CC380, DB_ConvertOffsetToAlias 0x822CC358) with the
file position of the word it converts. A zone rebuild uses this table to shift offsets past an edit.

usage: python -I reloc_scan.py <zone> <out.bin> <image>
out.bin: little-endian u32 pairs (file position, stored value); plus <out>.streams.bin: u32 quads
(file position or 0xFFFFFFFF, block, block position, size) for every stream read, in load order."""
import array
import bisect
import contextlib
import io
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import zoneload as Z  # noqa: E402

zone, out = sys.argv[1], sys.argv[2]
image = sys.argv[3]  # the decrypted BO2 program (default_mp.image.bin)
z = Z.Zone(zone, image, "t6")
FILE_BLOCKS = set(z.p["file_blocks"])
ALIAS = 0x822CC358

streams = array.array("I")
# for mapping a memory address back to the file: recent temp-block reads, and per-block sorted lists for the others
recent = []  # (dest, size, fpos) of the last temp-block reads
by_block = {k: ([], []) for k in range(8)}  # block -> (dest starts, (dest, size, fpos))
relocs = array.array("I")
missed = [0]
orig_stream = z.hle_load_stream


def stream():
    at_start, ptr, size = z.r[3] & 0xFF, z.r[4] & 0xFFFFFFFF, Z.s32(z.r[5])
    if at_start and size:
        block = z.index
        infile = block in FILE_BLOCKS and not (block == 7)
        fpos = z.fpos if infile else 0xFFFFFFFF
        streams.extend((fpos, block, (ptr - Z.BLOCK_BASE - block * 0x08000000) & 0xFFFFFFFF, size))
        if infile:
            if block == 0:
                recent.append((ptr, size, fpos))
                if len(recent) > 256:
                    del recent[:128]
            else:
                starts, recs = by_block[block]
                starts.append(ptr)
                recs.append((ptr, size, fpos))
    orig_stream()


def file_pos(addr):
    for dest, size, fpos in reversed(recent):
        if dest <= addr < dest + size:
            return fpos + (addr - dest)
    block = (addr - Z.BLOCK_BASE) // 0x08000000
    if 0 < block < 8:
        starts, recs = by_block[block]
        i = bisect.bisect_right(starts, addr) - 1
        if i >= 0:
            dest, size, fpos = recs[i]
            if dest <= addr < dest + size:
                return fpos + (addr - dest)
    return None


def log(pp):
    v = z.mem.u32(pp)
    fp = file_pos(pp)
    if fp is None:
        missed[0] += 1
    else:
        relocs.extend((fp, v))


orig_ptr = z.hle_to_pointer


def to_ptr():
    log(z.r[3])
    orig_ptr()


def alias():
    pp = z.r[3]
    log(pp)
    v = (z.mem.u32(pp) - 1) & 0xFFFFFFFF
    slot = Z.BLOCK_BASE + (v >> 29) * 0x08000000 + (v & 0x1FFFFFFF)
    z.mem.w32(pp, z.mem.u32(slot))


def raw(dest, size, fpos, block):  # the root's own reads: the depends and asset arrays (block 5)
    streams.extend((fpos, block & 0xFFFFFFFF, (dest - Z.BLOCK_BASE - block * 0x08000000) & 0xFFFFFFFF, size))
    if 0 < block < 8:
        starts, recs = by_block[block]
        starts.append(dest)
        recs.append((dest, size, fpos))


z.raw_hook = raw
z.hle[z.p["load_stream"]] = stream
z.hle[z.p["to_pointer"]] = to_ptr
z.hle[ALIAS] = alias
t0 = time.time()
with contextlib.redirect_stdout(io.StringIO()):
    z.run()
relocs.byteswap() if sys.byteorder == "big" else None
open(out, "wb").write(relocs.tobytes())
open(out + ".streams.bin", "wb").write(streams.tobytes())
print(f"{len(relocs) // 2} stored offsets, {missed[0]} not in file data, {len(streams) // 4} stream reads, "
      f"{time.time() - t0:.0f} s")
