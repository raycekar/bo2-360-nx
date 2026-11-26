"""Loads a decoded BO1 (T5) or BO2 (T6) Xbox 360 zone by running that game's own zone loader code in a small
PowerPC interpreter. The stream API (Load_Stream, block push/pop, alloc, offset-to-pointer, strings, file reads) is
implemented here; every Load_* function of the game runs as is, so the in-memory layout is exactly the 360's.

usage: python -I zoneload.py <zone> --image <decrypted program> [--game t5|t6] [--stop N]   (loads assets 0..N-1; prints each asset's type and header address)
As a module: Zone(path).run(stop) then .mem / .assets [(index, type, header)].
"""
import struct
import sys

IMAGE = "default.image.bin"  # pass --image: BO1 TU11 default.image.bin (t5) or BO2 TU18 default_mp.image.bin (t6)
BASE = 0x82000000
T5_TYPES = """xmodelpieces physpreset physconstraints destructibledef xanim xmodel material pixelshader techset image sound
sound_patch col_map_sp col_map_mp com_map game_map_sp game_map_mp map_ents gfx_map lightdef ui_map font menufile menu
localize weapon weapondef weaponvariant snddriverglobals fx impactfx aitype mptype mpbody mphead character xmodelalias
rawfile stringtable packindex xGlobals ddl glasses texturelist emblemset""".split()

# Addresses of the stream API and the zone root in each game's program (found from the loader code, see
# docs/bo1_maps.md). T5: BO1 TU11 default.image.bin (7 blocks); T6: BO2 TU18 default_mp.image.bin (8 blocks).
PROFILES = {
    "t5": dict(load_stream=0x821F0668, alloc=0x821F05F8, push=0x821F04F0, pop=0x821F0578, inc=0x821F0610,
               to_pointer=0x821F0790, load_xstring=0x821F07B8, load_file=0x821D9FF0, script_string=0x821F0850,
               link=0x821EC8B0, read_string=0x821DA178, read_some=0x821D9EB0,
               load_script_strings=0x821DAB88, load_xasset=0x821EB078,
               var_list=0x8286C0D4, var_script_strings=0x8286C3A8, var_xasset=0x8286BFC4,
               g_pos=0x82B98148, g_index=0x82BA0168, g_blocks=0x82B98144, nblocks=7, list_size=0x10,
               file_blocks=(0, 4, 5, 6), code=(0x821D8000, 0x821F2000), saverest=(0x825EA800, 0x825EAC00)),
    "t6": dict(load_stream=0x822CC1D8, alloc=0x822CC168, push=0x822CC060, pop=0x822CC0E8, inc=0x822CC180,
               to_pointer=0x822CC380, load_xstring=0x822CC3A8, load_file=0x822AD5D8, script_string=None,
               link=0x822C6B18, read_string=0x822AD728, read_some=None,
               load_script_strings=0x822AEFE8, load_xasset=0x822C4578,
               var_list=0x82DB3D14, var_script_strings=0x82DB40A0, var_xasset=0x82DB3BA4,
               g_pos=0x832E5CA0, g_index=0x832E5CC4, g_blocks=0x832E5C9C, nblocks=8, list_size=0x18,
               file_blocks=(0, 5, 6), code=(0x822A0000, 0x822D0000), saverest=(0x82915E00, 0x82916200)),
}
BLOCK_BASE = 0x40000000  # block i lives at BLOCK_BASE + i * 0x08000000
STACK_TOP, SCRATCH = 0x7F000000, 0x7E000000
RETURN = 0x7FFFFFF0  # sentinel return address


class Mem:
    def __init__(self):
        self.pages = {}

    def page(self, a):
        p = self.pages.get(a >> 16)
        if p is None:
            p = self.pages[a >> 16] = bytearray(0x10000)
        return p

    def read(self, a, n):
        out = bytearray()
        while n:
            p, o = self.page(a), a & 0xFFFF
            k = min(n, 0x10000 - o)
            out += p[o:o + k]
            a, n = a + k, n - k
        return bytes(out)

    def write(self, a, b):
        i = 0
        while i < len(b):
            p, o = self.page(a + i), (a + i) & 0xFFFF
            k = min(len(b) - i, 0x10000 - o)
            p[o:o + k] = b[i:i + k]
            i += k

    def u8(self, a):
        return self.page(a)[a & 0xFFFF]

    def u16(self, a):
        return int.from_bytes(self.read(a, 2), "big")

    def u32(self, a):
        if (a & 0xFFFF) <= 0xFFFC:
            p = self.page(a)
            o = a & 0xFFFF
            return (p[o] << 24) | (p[o + 1] << 16) | (p[o + 2] << 8) | p[o + 3]
        return int.from_bytes(self.read(a, 4), "big")

    def u64(self, a):
        return int.from_bytes(self.read(a, 8), "big")

    def w8(self, a, v):
        self.page(a)[a & 0xFFFF] = v & 0xFF

    def w16(self, a, v):
        self.write(a, (v & 0xFFFF).to_bytes(2, "big"))

    def w32(self, a, v):
        self.write(a, (v & 0xFFFFFFFF).to_bytes(4, "big"))

    def w64(self, a, v):
        self.write(a, (v & 0xFFFFFFFFFFFFFFFF).to_bytes(8, "big"))


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def s32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def rotl32(v, n):
    v &= 0xFFFFFFFF
    return ((v << n) | (v >> (32 - n))) & 0xFFFFFFFF if n else v


def mask32(mb, me):
    m = 0
    for b in range(32):
        if (mb <= me and mb <= b <= me) or (mb > me and (b >= mb or b <= me)):
            m |= 1 << (31 - b)
    return m


class Zone:
    def __init__(self, path, image=IMAGE, game="t5"):
        self.game = game
        self.p = P = PROFILES[game]
        self.mem = Mem()
        img = open(image, "rb").read()
        self.mem.write(BASE, img)
        self.code = img
        self.file = open(path, "rb").read()
        self.fpos = 0
        self.r = [0] * 32
        self.f = [0] * 32
        self.cr = [0] * 8  # per field: bit 3 lt, 2 gt, 1 eq
        self.lr = self.ctr = 0
        self.steps = 0
        self.unknown = {}
        self.assets = []
        self.stack = []
        hle = {"load_stream": self.hle_load_stream, "alloc": self.hle_alloc, "push": self.hle_push,
               "pop": self.hle_pop, "inc": self.hle_inc, "to_pointer": self.hle_to_pointer,
               "load_xstring": self.hle_xstring, "load_file": self.hle_load_file, "script_string": lambda: None,
               "read_string": self.hle_read_string, "read_some": self.hle_read_some, "link": self.hle_link}
        self.hle = {P[k]: f for k, f in hle.items() if P.get(k)}
        self.decoded = {}
        self.max_steps = 0
        self.pool = 0x30000000  # copies of asset headers
        self.hot = {}

    # ---- stream state (g_streamPos / g_streamPosIndex kept in guest memory too) ----
    @property
    def pos(self):
        return self.mem.u32(self.p["g_pos"])

    @pos.setter
    def pos(self, v):
        self.mem.w32(self.p["g_pos"], v)

    @property
    def index(self):
        return self.mem.u32(self.p["g_index"])

    @index.setter
    def index(self, v):
        self.mem.w32(self.p["g_index"], v)

    def read_file(self, n):
        b = self.file[self.fpos:self.fpos + n]
        if len(b) < n:
            raise EOFError(f"zone ended at {self.fpos:#x} (wanted {n} bytes)")
        self.fpos += n
        return b

    def hle_load_stream(self):
        at_start, ptr, size = self.r[3] & 0xFF, self.r[4] & 0xFFFFFFFF, s32(self.r[5])
        self.trace = (getattr(self, "trace", []) + [(hex(self.lr), at_start, hex(ptr), size, self.index)])[-8:]
        self.r[3] = 1
        if at_start and size:
            if self.game == "t6" and self.index == 7:  # streamer reserve: BO2 neither reads nor advances
                self.r[3] = 0
                return
            if self.index not in self.p["file_blocks"]:  # runtime blocks: not in the file
                self.mem.write(ptr, bytes(size))
                self.r[3] = 0
            else:
                self.mem.write(ptr, self.read_file(size))
            self.pos = self.pos + size

    def hle_alloc(self):
        a = self.r[3]
        self.pos = (self.pos + a) & ~a & 0xFFFFFFFF
        self.r[3] = self.pos

    def hle_inc(self):
        self.pos = self.pos + self.r[3]

    def hle_push(self):
        new = self.r[3]
        self.stack.append((self.index, self.pos))
        self.block_pos[self.index] = self.pos
        self.index = new
        self.pos = self.block_pos[new]

    def hle_pop(self):
        old_index, old_pos = self.stack.pop()
        if self.index == 0:  # the temp block is freed on pop
            self.block_pos[0] = old_pos if old_index == 0 else self.block_pos[0]
        else:
            self.block_pos[self.index] = self.pos
        self.index = old_index
        self.pos = self.block_pos[old_index] if old_index != 0 or self.index != 0 else old_pos
        if old_index == 0:
            self.pos = old_pos

    def hle_to_pointer(self):
        pp = self.r[3]
        v = (self.mem.u32(pp) - 1) & 0xFFFFFFFF
        self.mem.w32(pp, BLOCK_BASE + (v >> 29) * 0x08000000 + (v & 0x1FFFFFFF))

    def hle_xstring(self):
        dest = self.mem.u32(self.r[3])
        e = self.file.index(b"\0", self.fpos)
        s = self.file[self.fpos:e + 1]
        self.fpos = e + 1
        self.mem.write(dest, s)
        self.pos = self.pos + len(s)

    def hle_link(self):
        """DB_LinkXAssetEntry(XAsset*): the header was built in the temp block (reused by the next asset); like the
        game's asset pools, keep a copy (0x2000 bytes: more than any T5 asset header) and return the entry."""
        header = self.mem.u32(self.r[3] + 4)
        copy = self.pool
        self.pool += 0x2000
        self.mem.write(copy, self.mem.read(header, 0x2000))
        self.mem.w32(self.r[3] + 4, copy)

    def hle_read_string(self):  # sub_821DA178(dest): reads a 0-terminated string from the file, returns its length
        dest = self.r[3]
        e = self.file.index(b"\0", self.fpos)
        s = self.file[self.fpos:e + 1]
        self.fpos = e + 1
        self.mem.write(dest, s)
        self.r[3] = len(s)

    def hle_read_some(self):  # sub_821D9EB0(dest, size, &read)
        b = self.read_file(self.r[4])
        self.mem.write(self.r[3], b)
        self.mem.w32(self.r[5], len(b))

    def hle_load_file(self):
        self.mem.write(self.r[3], self.read_file(self.r[4]))

    # ---- interpreter ----
    def call(self, addr, *args):
        for i, a in enumerate(args):
            self.r[3 + i] = a & 0xFFFFFFFF
        self.r[1] = STACK_TOP
        self.lr = RETURN
        pc = addr
        while pc != RETURN:
            pc = self.step(pc)
            if self.max_steps and self.steps > self.max_steps:
                hot = sorted(self.hot.items(), key=lambda kv: -kv[1])[:12] if self.hot else []
                raise RuntimeError(f"step limit at pc {pc:#x}; hot: {[(hex(a), n) for a, n in hot]}")
            if self.max_steps and self.steps > self.max_steps - 20000:
                self.hot[pc] = self.hot.get(pc, 0) + 1
        return self.r[3]

    def setcr(self, field, a, b, signed=True):
        if signed:
            a, b = s32(a), s32(b)
        else:
            a, b = a & 0xFFFFFFFF, b & 0xFFFFFFFF
        self.cr[field] = 8 if a < b else (4 if a > b else 2)

    def cr0(self, v):
        self.setcr(0, v, 0)

    def crbit(self, bi):
        return (self.cr[bi >> 2] >> (3 - (bi & 3))) & 1

    def branch_ok(self, bo, bi):
        if not (bo & 4):
            self.ctr = (self.ctr - 1) & 0xFFFFFFFF
            ctr_ok = (self.ctr != 0) ^ bool(bo & 2)
        else:
            ctr_ok = True
        cond_ok = bool(bo & 16) or (self.crbit(bi) == ((bo >> 3) & 1))
        return ctr_ok and cond_ok

    def step(self, pc):
        if pc in self.hle:
            self.hle[pc]()
            return self.lr
        if not (BASE <= pc < BASE + len(self.code)):
            raise RuntimeError(f"pc out of image: {pc:#x}")
        self.steps += 1
        w = self.mem.u32(pc)
        op = w >> 26
        rd, ra, rb = (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31
        r, m = self.r, self.mem
        imm = w & 0xFFFF
        simm = s16(imm)
        ea = lambda: ((r[ra] if ra else 0) + simm) & 0xFFFFFFFF  # noqa: E731
        nxt = pc + 4
        if op == 18:  # b
            li = w & 0x03FFFFFC
            if li & 0x02000000:
                li -= 0x04000000
            tgt = (li if w & 2 else pc + li) & 0xFFFFFFFF
            if w & 1:
                self.lr = nxt
                if tgt not in self.hle and not self.known(tgt):
                    self.unknown[tgt] = self.unknown.get(tgt, 0) + 1
                    r[3] = r[3]  # unknown callee: treated as returning r3 unchanged
                    return nxt
            return tgt
        if op == 16:  # bc
            bo, bi = rd, ra
            bd = w & 0xFFFC
            if bd & 0x8000:
                bd -= 0x10000
            if self.branch_ok(bo, bi):
                if w & 1:
                    self.lr = nxt
                return (bd if w & 2 else pc + bd) & 0xFFFFFFFF
            return nxt
        if op == 19:
            xo = (w >> 1) & 0x3FF
            if xo == 16:  # bclr
                if self.branch_ok(rd, ra):
                    tgt = self.lr
                    if w & 1:
                        self.lr = nxt
                    return tgt
                return nxt
            if xo == 528:  # bcctr
                if self.branch_ok(rd | 4, ra):
                    if w & 1:
                        self.lr = nxt
                        if not self.known(self.ctr):
                            self.unknown[self.ctr] = self.unknown.get(self.ctr, 0) + 1
                            return nxt
                    return self.ctr
                return nxt
            if xo == 0:  # mcrf
                self.cr[rd >> 2] = self.cr[ra >> 2]
                return nxt
            if xo in (33, 129, 193, 225, 257, 289, 417, 449, 150):  # cr logic / isync: rarely matter here
                if xo == 193:  # crxor
                    bt = rd
                    v = self.crbit(ra) ^ self.crbit(rb)
                    f, b = bt >> 2, 3 - (bt & 3)
                    self.cr[f] = (self.cr[f] & ~(1 << b)) | (v << b)
                return nxt
            raise RuntimeError(f"op19 xo {xo} at {pc:#x}")
        if op == 14:  # addi
            r[rd] = ((r[ra] if ra else 0) + simm) & 0xFFFFFFFF
        elif op == 15:  # addis
            r[rd] = ((r[ra] if ra else 0) + (simm << 16)) & 0xFFFFFFFF
        elif op == 7:
            r[rd] = (s32(r[ra]) * simm) & 0xFFFFFFFF
        elif op == 8:  # subfic
            r[rd] = (simm - s32(r[ra])) & 0xFFFFFFFF
        elif op in (12, 13):  # addic
            r[rd] = (r[ra] + simm) & 0xFFFFFFFF
            if op == 13:
                self.cr0(r[rd])
        elif op == 10:
            self.setcr(rd >> 2, r[ra], imm, signed=False)
        elif op == 11:
            self.setcr(rd >> 2, r[ra], simm)
        elif op == 24:
            r[ra] = r[rd] | imm
        elif op == 25:
            r[ra] = (r[rd] | (imm << 16)) & 0xFFFFFFFF
        elif op == 26:
            r[ra] = r[rd] ^ imm
        elif op == 27:
            r[ra] = r[rd] ^ (imm << 16)
        elif op == 28:
            r[ra] = r[rd] & imm
            self.cr0(r[ra])
        elif op == 29:
            r[ra] = r[rd] & (imm << 16)
            self.cr0(r[ra])
        elif op in (20, 21, 23):  # rlwimi, rlwinm, rlwnm
            sh = rb if op != 23 else r[rb] & 31
            mb, me = (w >> 6) & 31, (w >> 1) & 31
            mk = mask32(mb, me)
            v = rotl32(r[rd], sh) & mk
            r[ra] = (v | (r[ra] & ~mk)) & 0xFFFFFFFF if op == 20 else v
            if w & 1:
                self.cr0(r[ra])
        elif op in (32, 33):
            a = ea()
            r[rd] = m.u32(a)
            if op == 33:
                r[ra] = a
        elif op in (34, 35):
            a = ea()
            r[rd] = m.u8(a)
            if op == 35:
                r[ra] = a
        elif op in (40, 41):
            a = ea()
            r[rd] = m.u16(a)
            if op == 41:
                r[ra] = a
        elif op == 42:
            r[rd] = s16(m.u16(ea())) & 0xFFFFFFFF
        elif op in (36, 37):
            a = ea()
            m.w32(a, r[rd])
            if op == 37:
                r[ra] = a
        elif op in (38, 39):
            a = ea()
            m.w8(a, r[rd])
            if op == 39:
                r[ra] = a
        elif op in (44, 45):
            a = ea()
            m.w16(a, r[rd])
            if op == 45:
                r[ra] = a
        elif op in (48, 49):  # lfs: keep raw bits
            a = ea()
            self.f[rd] = ("s", m.u32(a))
            if op == 49:
                r[ra] = a
        elif op in (50, 51):
            a = ea()
            self.f[rd] = ("d", m.u64(a))
            if op == 51:
                r[ra] = a
        elif op in (52, 53):
            a = ea()
            v = self.f[rd]
            m.w32(a, v[1] if isinstance(v, tuple) and v[0] == "s" else 0)
            if op == 53:
                r[ra] = a
        elif op in (54, 55):
            a = ea()
            v = self.f[rd]
            m.w64(a, v[1] if isinstance(v, tuple) and v[0] == "d" else 0)
            if op == 55:
                r[ra] = a
        elif op == 58:  # ld / ldu
            ds = s16(w & 0xFFFC)
            a = ((r[ra] if ra else 0) + ds) & 0xFFFFFFFF
            r[rd] = m.u64(a) & 0xFFFFFFFF
            self.hi = getattr(self, "hi", {})
            if (w & 3) == 1:
                r[ra] = a
        elif op == 62:  # std / stdu
            ds = s16(w & 0xFFFC)
            a = ((r[ra] if ra else 0) + ds) & 0xFFFFFFFF
            m.w64(a, r[rd])
            if (w & 3) == 1:
                r[ra] = a
        elif op == 31:
            self.op31(pc, w, rd, ra, rb)
        elif op == 0 and w == 0:
            raise RuntimeError(f"zero word at {pc:#x}")
        else:
            raise RuntimeError(f"opcode {op} ({w:#010x}) at {pc:#x}")
        return nxt

    def known(self, tgt):
        """Functions we run: the loader code region and the register save/restore helpers."""
        a, b = self.p["code"]
        c, d = self.p["saverest"]
        return a <= tgt < b or c <= tgt < d

    def op31(self, pc, w, rd, ra, rb):
        r, m = self.r, self.mem
        xo = (w >> 1) & 0x3FF
        rc = w & 1
        idx = lambda: ((r[ra] if ra else 0) + r[rb]) & 0xFFFFFFFF  # noqa: E731
        res = None
        if xo == 266:
            res = r[rd] = (r[ra] + r[rb]) & 0xFFFFFFFF
        elif xo == 10:  # addc
            res = r[rd] = (r[ra] + r[rb]) & 0xFFFFFFFF
        elif xo == 40:
            res = r[rd] = (r[rb] - r[ra]) & 0xFFFFFFFF
        elif xo == 8:  # subfc
            res = r[rd] = (r[rb] - r[ra]) & 0xFFFFFFFF
        elif xo == 104:
            res = r[rd] = (-r[ra]) & 0xFFFFFFFF
        elif xo == 235:
            res = r[rd] = (s32(r[ra]) * s32(r[rb])) & 0xFFFFFFFF
        elif xo == 11:
            res = r[rd] = ((r[ra] * r[rb]) >> 32) & 0xFFFFFFFF
        elif xo == 75:
            res = r[rd] = ((s32(r[ra]) * s32(r[rb])) >> 32) & 0xFFFFFFFF
        elif xo == 491:
            b = s32(r[rb])
            res = r[rd] = (int(s32(r[ra]) / b) & 0xFFFFFFFF) if b else 0
        elif xo == 459:
            res = r[rd] = (r[ra] // r[rb]) if r[rb] else 0
        elif xo == 28:
            res = r[ra] = r[rd] & r[rb]
        elif xo == 60:
            res = r[ra] = r[rd] & ~r[rb] & 0xFFFFFFFF
        elif xo == 444:
            res = r[ra] = r[rd] | r[rb]
        elif xo == 412:
            res = r[ra] = (r[rd] | ~r[rb]) & 0xFFFFFFFF
        elif xo == 316:
            res = r[ra] = r[rd] ^ r[rb]
        elif xo == 124:
            res = r[ra] = ~(r[rd] | r[rb]) & 0xFFFFFFFF
        elif xo == 24:
            n = r[rb] & 63
            res = r[ra] = (r[rd] << n) & 0xFFFFFFFF if n < 32 else 0
        elif xo == 536:
            n = r[rb] & 63
            res = r[ra] = (r[rd] >> n) if n < 32 else 0
        elif xo == 792:
            n = r[rb] & 63
            res = r[ra] = (s32(r[rd]) >> min(n, 31)) & 0xFFFFFFFF
        elif xo == 824:
            res = r[ra] = (s32(r[rd]) >> rb) & 0xFFFFFFFF
        elif xo == 922:
            res = r[ra] = s16(r[rd] & 0xFFFF) & 0xFFFFFFFF
        elif xo == 954:
            v = r[rd] & 0xFF
            res = r[ra] = (v - 0x100 if v & 0x80 else v) & 0xFFFFFFFF
        elif xo == 26:
            v = r[rd] & 0xFFFFFFFF
            res = r[ra] = 32 - v.bit_length()
        elif xo == 0:
            self.setcr(rd >> 2, r[ra], r[rb])
        elif xo == 32:
            self.setcr(rd >> 2, r[ra], r[rb], signed=False)
        elif xo in (23, 55):
            a = idx()
            r[rd] = m.u32(a)
            if xo == 55:
                r[ra] = a
        elif xo in (151, 183):
            a = idx()
            m.w32(a, r[rd])
            if xo == 183:
                r[ra] = a
        elif xo == 279:
            r[rd] = m.u16(idx())
        elif xo == 343:
            r[rd] = s16(m.u16(idx())) & 0xFFFFFFFF
        elif xo == 407:
            m.w16(idx(), r[rd])
        elif xo == 87:
            r[rd] = m.u8(idx())
        elif xo == 215:
            m.w8(idx(), r[rd])
        elif xo == 21:
            r[rd] = m.u64(idx()) & 0xFFFFFFFF
        elif xo == 149:
            m.w64(idx(), r[rd])
        elif xo == 534:  # lwbrx
            r[rd] = int.from_bytes(m.read(idx(), 4), "little")
        elif xo == 339:
            spr = ((w >> 16) & 31) | (((w >> 11) & 31) << 5)
            r[rd] = self.lr if spr == 8 else self.ctr if spr == 9 else 0
        elif xo == 467:
            spr = ((w >> 16) & 31) | (((w >> 11) & 31) << 5)
            if spr == 8:
                self.lr = r[rd]
            elif spr == 9:
                self.ctr = r[rd]
        elif xo == 19:  # mfcr
            v = 0
            for f in range(8):
                v = (v << 4) | self.cr[f]
            r[rd] = v
        elif xo == 144:  # mtcrf
            pass
        elif xo in (598, 854, 86, 278, 246, 54, 1014, 470, 982):  # sync, eieio, dcbf, dcbt, dcbtst, dcbst, dcbz...
            if xo == 1014:  # dcbz: zero 128 bytes
                a = idx() & ~127
                m.write(a, bytes(128))
        elif xo == 58:  # cntlzd -> treat as 32
            v = r[rd] & 0xFFFFFFFF
            res = r[ra] = 32 + (32 - v.bit_length()) if v else 64
        else:
            raise RuntimeError(f"op31 xo {xo} ({w:#010x}) at {pc:#x}")
        if rc and res is not None:
            self.cr0(res)

    # ---- the zone ----
    def run(self, stop=None, verbose=False):
        P = self.p
        nb = P["nblocks"]
        hdr = self.read_file(8 + 4 * nb)
        blocks = struct.unpack_from(f">{nb}I", hdr, 8)
        self.block_pos = {i: BLOCK_BASE + i * 0x08000000 for i in range(nb)}
        self.index, self.pos = 0, self.block_pos[0]
        table = SCRATCH + 0x100  # g_streamBlocks: {data, size} per block
        for i in range(nb):
            self.mem.w32(table + 8 * i, self.block_pos[i])
            self.mem.w32(table + 8 * i + 4, blocks[i])
        self.mem.w32(P["g_blocks"], table)
        main_block = 4 if self.game == "t5" else 5
        lst = SCRATCH
        self.r_push(main_block)
        self.mem.write(lst, self.read_file(P["list_size"]))
        self.mem.w32(P["var_list"], lst)
        self.r_push(main_block)
        self.mem.w32(P["var_script_strings"], lst)
        self.call(P["load_script_strings"], 0)
        self.r_pop()
        if self.game == "t6":  # depends: an array of string pointers
            dcount, dptr = self.mem.u32(lst + 8), self.mem.u32(lst + 12)
            if dptr:
                self.r[3] = 3
                self.hle_alloc()
                arr = self.r[3]
                self.mem.w32(lst + 12, arr)
                self.mem.write(arr, self.read_file(4 * dcount))
                self.pos = self.pos + 4 * dcount
                for i in range(dcount):
                    if self.mem.u32(arr + 4 * i) == 0xFFFFFFFF:
                        self.mem.w32(arr + 4 * i, self.pos)
                        e = self.file.index(b"\0", self.fpos)
                        s_ = self.file[self.fpos:e + 1]
                        self.fpos = e + 1
                        self.mem.write(self.pos, s_)
                        self.pos = self.pos + len(s_)
        count_off = 8 if self.game == "t5" else 0x10
        count, aptr = self.mem.u32(lst + count_off), self.mem.u32(lst + count_off + 4)
        if aptr:
            self.r[3] = 3
            self.hle_alloc()
            assets = self.r[3]
            self.mem.w32(lst + count_off + 4, assets)
            self.mem.write(assets, self.read_file(count * 8))
            self.pos = self.pos + count * 8
            n = count if stop is None else min(stop, count)
            for i in range(n):
                a = assets + 8 * i
                self.mem.w32(P["var_xasset"], a)
                try:
                    self.call(P["load_xasset"], 0)
                except Exception as e:
                    raise RuntimeError(f"asset {i} type {self.mem.u32(a)} (file {self.fpos:#x}): {e}") from e
                t, h = self.mem.u32(a), self.mem.u32(a + 4)
                self.assets.append((i, t, h))
                if verbose:
                    print(f"{i:4} type {t:3} header {h:#010x}  file {self.fpos:#x}  steps {self.steps}", flush=True)
        self.r_pop()
        return blocks

    def r_push(self, i):
        self.r[3] = i
        self.hle_push()

    def r_pop(self):
        self.hle_pop()


def main():
    stop = int(sys.argv[sys.argv.index("--stop") + 1]) if "--stop" in sys.argv else None
    image = sys.argv[sys.argv.index("--image") + 1] if "--image" in sys.argv else IMAGE
    game = sys.argv[sys.argv.index("--game") + 1] if "--game" in sys.argv else "t5"
    z = Zone(sys.argv[1], image, game)
    if "--max-steps" in sys.argv:
        z.max_steps = int(sys.argv[sys.argv.index("--max-steps") + 1])
    try:
        z.run(stop, verbose=True)
    finally:
        print("file position", hex(z.fpos), "of", hex(len(z.file)), "steps", z.steps)
        if z.unknown:
            print("calls outside the loader (skipped):", {hex(k): v for k, v in sorted(z.unknown.items())[:20]})


if __name__ == "__main__":
    main()
