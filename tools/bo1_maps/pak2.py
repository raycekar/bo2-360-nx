"""BO1 (T5) Xbox 360 image packs ("pak2": images.pak, images_low.pak, img_dlcN.pak), read-only.

Layout (big endian): "pak2", u32 timestamp, u32 ?, u32 count, u32 sector size (0x800), u32 data start; at 0x18
count u32 start sectors (absolute; -1 absent), then 2 bytes, then count u16 sizes in sectors (low 15 bits; the top
bit is a flag). The game looks a part up as table[id & 0xFFFFFF] (BO1 TU11 sub_8231D030 / sub_8231D0A0); the id's top
byte picks the pack. A pack can be read from a file or from inside a disc image (xiso).
"""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "install"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class Pak:
    def __init__(self, path, iso_member=None):
        if iso_member:
            import xiso
            self.iso = xiso.Xiso(path)
            entry = next(e for e in self.iso.walk() if e[0].lower() == iso_member.lower())
            self.base, self.size = self.iso.base + entry[1] * 0x800, entry[2]
            self.f = self.iso.f
        else:
            self.f = open(path, "rb")
            self.base, self.size = 0, os.path.getsize(path)
        head = self.read(0, 0x18)
        assert head[:4] == b"pak2", head[:4]
        _, self.field, self.count, self.sector, self.data_start = struct.unpack_from(">5I", head, 4)
        n = self.count
        self.pos = struct.unpack(f">{n}I", self.read(0x1C, 4 * n))
        raw = struct.unpack(f">{n}H", self.read(0x1C + 4 * n, 2 * n))
        self.sizes = [s & 0x7FFF for s in raw]
        self.flags = [s >> 15 for s in raw]

    def read(self, off, n):
        self.f.seek(self.base + off)
        return self.f.read(n)

    def pixels(self, index):
        """A part's pixels (one mip level, tiled, 8-in-16, as in a zone), or None. Part: u32 W, zeros to W; at W:
        u32 0, u32 compressed size, u32 uncompressed size, then one LZO1X stream."""
        got = self.part(index)
        if got is None:
            return None
        data, compressed = got
        if not compressed:
            return data
        w = struct.unpack(">I", data[:4])[0] & 0x7FFFFFFF  # the top bit: a flag, meaning not known
        _, comp, unc = struct.unpack_from(">3I", data, w)
        import lzo1x
        out = lzo1x.decompress(data[w + 12:w + 12 + comp], unc)
        if len(out) != unc:
            raise lzo1x.LzoError(f"part {index:#x}: {len(out):#x} bytes, expected {unc:#x}")
        return out

    def part(self, index):
        """(raw bytes, flag) of entry index, or None."""
        if index >= self.count or self.pos[index] == 0xFFFFFFFF:
            return None
        return self.read(self.pos[index] * self.sector, self.sizes[index] * self.sector), self.flags[index]


if __name__ == "__main__":
    pak = Pak(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("0x") else None)
    print(f"count {pak.count} sector {pak.sector:#x} data start {pak.data_start:#x} field {pak.field:#x}")
    for a in sys.argv[2:]:
        if a.startswith("0x"):
            i = int(a, 16)
            got = pak.part(i)
            print(hex(i), None if got is None else (len(got[0]), got[1], got[0][:24].hex()))
