"""Collapse an asset_trace.py log: stream reads grouped by consecutive caller, with header fields and pointer counts.
usage: python -I trace_summary.py <trace.txt>"""
import re
import sys

rows = []
for line in open(sys.argv[1]):
    m = re.match(r"S lr=(\w+) block=(\d) size=(\w+) dest=(\w+)(?: hdr\+(\S+))? file=(\w+)", line)
    if m:
        lr, block, size, dest, hdr, fpos = m.groups()
        size = int(size, 16)
        if rows and rows[-1][0] == "S" and rows[-1][1] == lr and rows[-1][2] == block and not hdr:
            rows[-1][3] += size
            rows[-1][4] += 1
        else:
            rows.append(["S", lr, block, size, 1, hdr or "", fpos])
    elif line.startswith("P "):
        m = re.match(r"P lr=(\w+) at=\w+(?: hdr\+(\S+))?", line)
        if rows and rows[-1][0] == "P" and rows[-1][1] == m.group(1) and not m.group(2):
            rows[-1][4] += 1
        else:
            rows.append(["P", m.group(1), "", 0, 1, m.group(2) or "", ""])
for r in rows:
    if r[0] == "S":
        print(f"S {r[1]} b{r[2]} {r[3]:#9x} x{r[4]:<5} {('hdr+' + r[5]) if r[5] else '':12} {r[6]}")
    else:
        print(f"P {r[1]}            x{r[4]:<5} {('hdr+' + r[5]) if r[5] else ''}")
