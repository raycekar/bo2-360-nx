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
        self.pos = struct.unpack(f">{n}I", self.read(0x18, 4 * n))
        raw = struct.unpack(f">{n}H", self.read(0x18 + 4 * n + 2, 2 * n))
        self.sizes = [s & 0x7FFF for s in raw]
        self.flags = [s >> 15 for s in raw]

    def read(self, off, n):
        self.f.seek(self.base + off)
        return self.f.read(n)

    def pixels(self, index, size):
        """A part's pixels: the part starts with a u32 offset (rounded up to 16) to one LZX stream (XMem style, no
        frame headers) holding one mip level of `size` bytes (tiled, 8-in-16, as in a zone)."""
        got = self.part(index)
        if got is None:
            return None
        data, _ = got
        start = (struct.unpack(">I", data[:4])[0] + 15) & ~15
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "inspect"))
        import ff_shaders
        out = bytearray()
        lzx = ff_shaders.Lzx()
        # frames of at most 0x8000 output share one LZX state
        src = data[start:]
        try:
            out += lzx.decompress(src, size) if size <= 0x8000 else self._big(lzx, src, size)
        except Exception:  # noqa: BLE001
            return None
        return bytes(out)

    @staticmethod
    def _big(lzx, src, size):
        return lzx.decompress(src, size)

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
