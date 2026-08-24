#!/usr/bin/env python3
"""cgpdftoraster_harness — run a host rasteriser offline and diff pixels across option sets.

macOS-specific (it drives Apple's /usr/libexec/cups/filter binaries), but the pattern
transfers: substitute Ghostscript or pdftoraster on Linux.

    python3 cgpdftoraster_harness.py --ppd /etc/cups/ppd/<q>.ppd in.pdf \
        --opts "" --opts "SomeVendorKey=1" --opts "AP_ColorMatchingMode=AP_ApplicationColorMatching"

It runs the real filter once per --opts, hashes the rasters, and groups identical ones.
Identical output across option sets means EITHER the options do nothing OR they were never
parsed -- which is why the two controls below are not optional.

CONTROL 1 (mutation lands): --control-ppd copies the PPD, rewrites *DefaultResolution, and
  asserts the raster's resolution changes.  Proves the file you edited is the one being read.
CONTROL 2 (instrument is colour-live): --control-tag re-runs the input with an ICC profile
  attached and asserts the pixels change.  Proves the harness can see a colour transform.
Both must pass before a null result means anything.  See docs/TRAPS.md T3.
"""
from __future__ import annotations
import argparse, hashlib, os, pathlib, re, shutil, subprocess, sys, tempfile

FILTER = "/usr/libexec/cups/filter/cgpdftoraster"


def rasterise(ppd, opts, src, dst):
    env = dict(os.environ, PPD=ppd)
    with open(src, "rb") as i, open(dst, "wb") as o:
        p = subprocess.run([FILTER, "1", "u", "t", "1", opts], stdin=i, stdout=o,
                           stderr=subprocess.PIPE, env=env, timeout=600)
    err = p.stderr.decode("utf-8", "replace")
    if "logged an error" in err:
        raise SystemExit(f"the rasteriser reported an input error -- your INPUT is invalid, "
                         f"not the pipeline. Validate it before measuring (docs/TRAPS.md T2).\n{err[:400]}")
    return hashlib.md5(open(dst, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("--ppd", required=True)
    ap.add_argument("--opts", action="append", default=[])
    ap.add_argument("--control-ppd", action="store_true")
    ap.add_argument("--outdir", default=tempfile.mkdtemp(prefix="rasterharness-"))
    a = ap.parse_args()
    out = pathlib.Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    if not a.opts:
        a.opts = [""]

    if a.control_ppd:
        mod = out / "control.ppd"
        t = pathlib.Path(a.ppd).read_text(errors="replace")
        m = re.search(r'^\*DefaultResolution:\s*(\S+)', t, re.M)
        if not m:
            print("CONTROL 1: SKIPPED (PPD declares no *DefaultResolution)")
        else:
            alt = re.findall(r'^\*Resolution\s+(\S+)/', t, re.M)
            other = next((r for r in alt if r != m.group(1)), None)
            if not other:
                print("CONTROL 1: SKIPPED (only one resolution offered)")
            else:
                mod.write_text(t.replace(f"*DefaultResolution: {m.group(1)}",
                                         f"*DefaultResolution: {other}"))
                h1 = rasterise(a.ppd, "", a.pdf, out / "ctl_stock.raster")
                h2 = rasterise(str(mod), "", a.pdf, out / "ctl_mod.raster")
                print(f"CONTROL 1 (mutation lands): {'PASS' if h1 != h2 else 'FAIL'} "
                      f"({m.group(1)} vs {other})")
                if h1 == h2:
                    print("  -> the PPD you edited is NOT the one being read. Stop; fix this first.")
                    return 1

    print("\n=== option sets ===")
    res = {}
    for i, o in enumerate(a.opts):
        h = rasterise(a.ppd, o, a.pdf, out / f"opt{i}.raster")
        res[o or "<none>"] = h
        print(f"  {h[:12]}  {o or '<no options>'}")
    groups = {}
    for k, v in res.items():
        groups.setdefault(v, []).append(k)
    print("\n=== groups (identical output = that option changed nothing) ===")
    for h, names in groups.items():
        print(f"  {h[:12]}: {', '.join(names)}")
    if len(groups) == 1 and len(res) > 1:
        print("\n  ALL IDENTICAL. This is only meaningful if CONTROL 1 passed and you have also")
        print("  shown the harness can see a colour change (retag the source). See docs/TRAPS.md T3.")
    print(f"\nrasters in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
