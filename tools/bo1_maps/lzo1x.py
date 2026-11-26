"""LZO1X decompressor (checked, pure Python): BO1's image pack parts are LZO1X streams."""


class LzoError(Exception):
    pass


def decompress(src, outlen=None):
    out = bytearray()
    ip = 0
    n = len(src)

    def byte():
        nonlocal ip
        if ip >= n:
            raise LzoError("input overrun")
        ip += 1
        return src[ip - 1]

    def literals(k):
        nonlocal ip
        if ip + k > n:
            raise LzoError("literal overrun")
        out.extend(src[ip:ip + k])
        ip += k

    def match(dist, length):
        s = len(out) - dist
        if s < 0:
            raise LzoError(f"lookbehind {dist} at {len(out)}")
        if dist >= length:
            out.extend(out[s:s + length])
        else:
            for i in range(length):
                out.append(out[s + i])

    def extended(base):
        t = 0
        while True:
            b = byte()
            if b:
                return t + base + b
            t += 255

    # state: literals copied right before this instruction (0, 1-3, or 4 for a longer run)
    t = byte()
    state = 0
    if t > 17:
        literals(t - 17)
        state = 4 if t - 17 >= 4 else t - 17
        t = byte()
    while True:
        if t < 16:
            if state == 0:  # a literal run
                literals((extended(15) if t == 0 else t) + 3)
                state = 4
                t = byte()
                continue
            if state == 4:
                match(1 + 0x0800 + (t >> 2) + (byte() << 2), 3)
            else:
                match(1 + (t >> 2) + (byte() << 2), 2)
        elif t >= 64:
            match(1 + ((t >> 2) & 7) + (byte() << 3), (t >> 5) + 1)
        elif t >= 32:
            length = (t & 31) or extended(31)
            b0, b1 = byte(), byte()
            match(1 + ((b0 | (b1 << 8)) >> 2), length + 2)
            t = b0
        else:
            length = (t & 7) or extended(7)
            b0, b1 = byte(), byte()
            dist = ((t & 8) << 11) + ((b0 | (b1 << 8)) >> 2)
            if dist == 0:
                return bytes(out)  # end of stream
            match(dist + 0x4000, length + 2)
            t = b0
        if outlen is not None and len(out) > outlen:
            raise LzoError("output overrun")
        state = t & 3
        literals(state)
        t = byte()
