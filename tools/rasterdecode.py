#!/usr/bin/env python3
"""rasterdecode — decode a CUPS raster stream to pixel values.

    python3 rasterdecode.py out.raster
    python3 rasterdecode.py out.raster --colours 20

################  READ THIS BEFORE TRUSTING ANY 16-BIT RESULT  ################
#                                                                             #
#  The HEADER and the PIXEL DATA do not use the same byte order.              #
#                                                                             #
#  The header's byte order is given by the magic word ("RaS2"/"RaS3" vs       #
#  "2SaR"/"3SaR").  The *samples* are written in HOST order, which on a       #
#  little-endian machine is little-endian even when the header is big-endian. #
#                                                                             #
#  Decoding 16-bit samples with the header's order byte-swaps every value     #
#  and produces output that is indistinguishable from colour management:      #
#      (1000, 2000, 3000)  ->  (59395, 53255, 47115)                          #
#  This exact bug once produced "93 % of patch pixels differ from the source" #
#  and was briefly believed to be a root cause.  See docs/TRAPS.md T1.        #
#                                                                             #
#  It is INVISIBLE on 8-bit-derived data, because every k*257 value           #
#  (0x8080, 0xE6E6, ...) is a byte palindrome and survives the swap.          #
#                                                                             #
#  CONTROL: put a value you chose (e.g. 1000) into the source and confirm     #
#  you read 1000 back, not 59395.  --sample-endian lets you try both.         #
#                                                                             #
###############################################################################

WHAT IT PROVES: the exact values that reached the CUPS raster.
WHAT IT CANNOT PROVE: what the vendor filter below it does with them.
Portable: pure stdlib (numpy optional, only for the fast colour census).
"""
from __future__ import annotations
import argparse, collections, struct, sys

MAGIC = {b"RaSt": (">", 1), b"tSaR": ("<", 1),
         b"RaS2": (">", 2), b"2SaR": ("<", 2),
         b"RaS3": (">", 3), b"3SaR": ("<", 3)}

FIELDS = ["AdvanceDistance", "AdvanceMedia", "Collate", "CutMedia", "Duplex",
          "HWResolutionX", "HWResolutionY", "BBox0", "BBox1", "BBox2", "BBox3",
          "InsertSheet", "Jog", "LeadingEdge", "Margins0", "Margins1", "ManualFeed",
          "MediaPosition", "MediaWeight", "MirrorPrint", "NegativePrint", "NumCopies",
          "Orientation", "OutputFaceUp", "PageSizeX", "PageSizeY", "Separations",
          "TraySwitch", "Tumble", "cupsWidth", "cupsHeight", "cupsMediaType",
          "cupsBitsPerColor", "cupsBitsPerPixel", "cupsBytesPerLine", "cupsColorOrder",
          "cupsColorSpace", "cupsCompression", "cupsRowCount", "cupsRowFeed", "cupsRowStep"]


def _header(h, endian, ver):
    d = {n: h[i * 64:(i + 1) * 64].split(b"\0")[0].decode("latin1")
         for i, n in enumerate(("MediaClass", "MediaColor", "MediaType", "OutputType"))}
    off = 256
    d.update(dict(zip(FIELDS, struct.unpack(endian + "41I", h[off:off + 164])))); off += 164
    if ver >= 2:
        d["cupsNumColors"] = struct.unpack(endian + "I", h[off:off + 4])[0]; off += 4
        f = struct.unpack(endian + "7f", h[off:off + 28]); off += 28
        d["cupsBorderlessScalingFactor"], d["cupsPageSize"], d["cupsImagingBBox"] = f[0], f[1:3], f[3:7]
        d["cupsInteger"] = struct.unpack(endian + "16I", h[off:off + 64]); off += 64
        d["cupsReal"] = struct.unpack(endian + "16f", h[off:off + 64]); off += 64
        d["cupsString"] = [h[off + i * 64:off + (i + 1) * 64].split(b"\0")[0].decode("latin1")
                           for i in range(16)]; off += 1024
        for n in ("cupsMarkerType", "cupsRenderingIntent", "cupsPageSizeName"):
            d[n] = h[off:off + 64].split(b"\0")[0].decode("latin1"); off += 64
    return d


def _rle(data, pos, hdr):
    bpp = max(1, hdr["cupsBitsPerPixel"] // 8)
    bpl, height = hdr["cupsBytesPerLine"], hdr["cupsHeight"]
    out, lines = bytearray(), 0
    while lines < height and pos < len(data):
        rep = data[pos] + 1; pos += 1
        line = bytearray()
        while len(line) < bpl and pos < len(data):
            n = data[pos]; pos += 1
            if n < 128:
                line += data[pos:pos + bpp] * (n + 1); pos += bpp
            else:
                c = 257 - n; line += data[pos:pos + bpp * c]; pos += bpp * c
        out += bytes(line[:bpl]) * rep; lines += rep
    return bytes(out), pos


def pages(path):
    d = open(path, "rb").read()
    if d[:4] not in MAGIC:
        raise SystemExit(f"not a CUPS raster stream (magic {d[:4]!r})")
    endian, ver = MAGIC[d[:4]]
    hsize, pos, out = (1796 if ver >= 2 else 420), 4, []
    while pos + hsize <= len(d):
        hdr = _header(d[pos:pos + hsize], endian, ver); pos += hsize
        n = hdr["cupsBytesPerLine"] * hdr["cupsHeight"]
        if ver == 3:                     # v3 = uncompressed
            raw, pos = d[pos:pos + n], pos + n
        else:                            # v1/v2 = RLE
            raw, pos = _rle(d, pos, hdr)
        out.append((hdr, raw, ver))
        if pos >= len(d) - 4:
            break
    return out


def census(hdr, raw, step=100, sample_endian="<"):
    """Sampled colour census.  sample_endian: '<' host/little (correct on x86 and
    Apple Silicon), '>' only if you have PROVEN it with a known value."""
    bpp = hdr["cupsBitsPerPixel"] // 8
    bpc = hdr["cupsBitsPerColor"]
    n = hdr.get("cupsNumColors") or max(1, hdr["cupsBitsPerPixel"] // max(bpc, 1))
    bpl = hdr["cupsBytesPerLine"]
    c = collections.Counter()
    for y in range(0, hdr["cupsHeight"], step):
        row = raw[y * bpl:(y + 1) * bpl]
        if len(row) < bpl:
            break
        for x in range(0, hdr["cupsWidth"], step):
            px = row[x * bpp:(x + 1) * bpp]
            if len(px) < bpp:
                continue
            c[struct.unpack(sample_endian + "H" * n, px) if bpc == 16 else tuple(px)] += 1
    return c


def main():
    ap = argparse.ArgumentParser(description="decode a CUPS raster stream")
    ap.add_argument("path")
    ap.add_argument("--colours", type=int, default=15)
    ap.add_argument("--step", type=int, default=100)
    ap.add_argument("--sample-endian", choices=["<", ">"], default="<",
                    help="byte order of 16-bit SAMPLES; default '<' (host). See the note at the top.")
    a = ap.parse_args()
    for hdr, raw, ver in pages(a.path):
        print(f"\nraster v{ver}  data={len(raw)} bytes")
        for k in ("cupsWidth", "cupsHeight", "HWResolutionX", "cupsBitsPerColor",
                  "cupsBitsPerPixel", "cupsColorSpace", "cupsNumColors",
                  "cupsCompression", "cupsPageSizeName", "cupsRenderingIntent"):
            if k in hdr:
                print(f"  {k}: {hdr[k]}")
        c = census(hdr, raw, a.step, a.sample_endian)
        print(f"  distinct sampled colours: {len(c)}")
        for col, cnt in c.most_common(a.colours):
            print(f"    {col} x{cnt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
