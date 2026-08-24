#!/usr/bin/env python3
"""pcl3parse — structural decoder for a PCL-3-style inkjet command stream.

Many consumer inkjet drivers (Canon CNIJ among them) wrap their raster in the
PCL Level 3 escape syntax:

    ESC * t <n> R      raster resolution
    ESC * r 1 A        begin raster graphics
    ESC * b <n> M      set compression mode for the following plane data
    ESC * b <n> V      transfer <n> bytes of plane data (MORE planes follow in this row)
    ESC * b <n> W      transfer <n> bytes of plane data (LAST plane of this row)
    ESC * r C          end raster graphics

Counting V-then-W runs gives the number of COLOUR PLANES per raster row, and the
per-plane byte totals give a per-ink measure of how much data each plane carries.

WHAT IT PROVES: plane count, per-plane data volume, and how those change between
two job configurations.  For a target made of large flat patches this is a direct
proxy for "which inks the driver decided to use".
WHAT IT CANNOT PROVE: absolute ink amounts.  Plane data is compressed, and this
tool deliberately does NOT guess the compression scheme -- byte volume per plane
is a comparative measure only, valid between two runs of the SAME image.

POSITIVE CONTROL: run it on two streams generated from DIFFERENT images and
confirm the plane profile changes; and on two runs of the SAME configuration and
confirm it does not (pair with vendorstream.normalise).
"""
from __future__ import annotations
import argparse, collections, re, sys

ESC = 0x1B


def commands(data: bytes):
    """Yield (offset, param, group, value, terminator, payload) for each PCL sequence.

    PCL grammar:  ESC <param [!-/]> <group [`-~]> <value> <terminator [@-~]>
    A lowercase terminator means the sequence CONTINUES (combined form:
    ESC * p 160 x 1 Y); an uppercase terminator ends it.
    """
    i, n = 0, len(data)
    while i < n:
        j = data.find(b"\x1b", i)
        if j < 0 or j + 2 >= n:
            return
        param = chr(data[j + 1])
        if not ("!" <= param <= "/"):
            i = j + 1
            continue
        group = chr(data[j + 2])
        k = j + 3
        while k < n:
            m = re.match(rb"([+-]?\d*\.?\d*)([@-~])", data[k:k + 20])
            if not m:
                break
            raw, term = m.group(1).decode(), chr(m.group(2)[0])
            k += m.end()
            val = None
            if raw:
                try:
                    val = int(float(raw))
                except ValueError:
                    val = None
            payload = b""
            if term in "VW" and val is not None:
                payload = data[k:k + val]
                k += val
            yield j, param, group, val, term, payload
            if term.isupper():          # uppercase terminator ends the sequence
                break
        i = max(k, j + 1)


def profile(data: bytes):
    rows, cur, mode, res = [], [], None, None
    planes_total = collections.Counter()
    bytes_total = collections.Counter()
    for off, param, group, val, term, payload in commands(data):
        if param == "*" and group == "t" and term == "R":
            res = val
        elif param == "*" and group == "b" and term == "M":
            mode = val
        elif param == "*" and group == "b" and term in "VW":
            cur.append(len(payload))
            if term == "W":
                rows.append(tuple(cur))
                for idx, sz in enumerate(cur):
                    planes_total[idx] += 1
                    bytes_total[idx] += sz
                cur = []
    return {"resolution": res, "compression_mode": mode, "rows": len(rows),
            "planes_per_row": collections.Counter(len(r) for r in rows),
            "plane_rows": dict(planes_total), "plane_bytes": dict(bytes_total)}


def main():
    ap = argparse.ArgumentParser(description="structural decode of a PCL-3-style print stream")
    ap.add_argument("streams", nargs="+")
    a = ap.parse_args()
    out = {}
    for p in a.streams:
        d = open(p, "rb").read()
        pr = profile(d)
        out[p] = pr
        print(f"\n{p}  ({len(d)} bytes)")
        print(f"  resolution={pr['resolution']}  compression mode={pr['compression_mode']}  raster rows={pr['rows']}")
        print(f"  planes per row: {dict(pr['planes_per_row'])}")
        print(f"  per-plane data bytes: {pr['plane_bytes']}")
    if len(out) == 2:
        (n1, a1), (n2, a2) = out.items()
        print("\n=== per-plane comparison ===")
        keys = sorted(set(a1['plane_bytes']) | set(a2['plane_bytes']))
        print(f"  {'plane':>6} {'A bytes':>10} {'B bytes':>10} {'delta':>10}  {'B/A':>7}")
        for k in keys:
            x, y = a1['plane_bytes'].get(k, 0), a2['plane_bytes'].get(k, 0)
            ratio = (y / x) if x else float("inf")
            print(f"  {k:>6} {x:>10} {y:>10} {y - x:>+10}  {ratio:>7.3f}")
        print(f"\n  A = {n1}\n  B = {n2}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
