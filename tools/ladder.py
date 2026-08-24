#!/usr/bin/env python3
"""ladder — for every print queue: what will actually reach the printer?

Answers, per queue and with no ink:
  * queue type          PPD classic-driver / raw pass-through / driverless
  * submission ladder   which of PostScript / PDF / image wins, whether the data
                        arrives TAGGED or UNTAGGED, and at what bit depth
  * driver levers       the "no colour management" option, if one exists
  * ICC qualifier chain and whether an identity escape exists
  * driverless          whether a raw device raster type is advertised

Every check is PASS / FAIL / UNPROVEN.  UNPROVEN is not a soft pass: it means a
lever exists and is delivered, but nothing outside the printer can confirm the
driver honours it.  Only a printed, measured sheet can (see docs/METHOD.md M5).

WHAT IT PROVES: what the print system will do with a job, from its own tables.
WHAT IT CANNOT PROVE: what the vendor filter or the firmware then does.
POSITIVE CONTROL: edit a copy of a PPD (e.g. remove the no-CM value, or change
  *DefaultResolution) , point PPD_DIR at it, and confirm the report changes.

Usage:
    python3 ladder.py                 # every queue
    python3 ladder.py -q <queue>      # one queue
Portable to any CUPS system; the PostScript-reachability test reads the CUPS
mime tables, so it reflects whatever filters are actually installed.
"""
from __future__ import annotations
import argparse, os, pathlib, re, subprocess, sys, textwrap

PASS, FAIL, UNPROVEN, INFO = "PASS", "FAIL", "UNPROVEN", "info"
MARK = {PASS: "[PASS]", FAIL: "[FAIL]", UNPROVEN: "[UNPROVEN]", INFO: "[info]"}
PPD_DIRS = (os.environ.get("PPD_DIR"), "/etc/cups/ppd", "/private/etc/cups/ppd")
MIME_DIRS = ("/usr/share/cups/mime", "/usr/local/share/cups/mime", "/etc/cups")
PWG_DEVICE = tuple(f"device{i}_{b}" for i in range(1, 16) for b in (8, 16))

# ---------------------------------------------------------------------------
# What has ACTUALLY been measured, per driver family, by running that vendor's
# filter under a user-owned CUPS scheduler (docs/METHOD.md M3).
#
# Keyed on a substring of the PPD's *cupsFilter target path.  If a queue's
# filter is not in here, its lever status is reported as NOT MEASURED -- which
# is a weaker statement than "measured and it acts", and must not share wording
# with it.  Add an entry only when you have run the filter and have the diff.
# ---------------------------------------------------------------------------
FILTER_EVIDENCE = {
    "Raster2CanonIJ": {
        "measured": True,
        "finding": "the vendor filter emits BYTE-IDENTICAL image data whatever this option "
                   "is set to. Its stream is PCL-3-style, 3 planes per row (RGB contone, not "
                   "per-ink), and the raster payload was identical across 43 runs varying "
                   "intent, per-paper ICC, media and quality -- it changes only with the "
                   "source image. The option travels as a FLAG in the stream's XML preamble "
                   "(printcolormode_intent = pro | none).",
        "residual": "whether the PRINTER's firmware acts on that flag. The computer never "
                    "performs the transform, so no software here can observe it. This is "
                    "impossible in principle, not merely difficult: only a printed, measured "
                    "sheet can settle it.",
    },
}


def filter_evidence(ppd):
    """Return the measured evidence for this queue's vendor filter, or None."""
    if not ppd:
        return None
    try:
        text = pathlib.Path(ppd).read_text(errors="replace")
    except OSError:
        return None
    for key, ev in FILTER_EVIDENCE.items():
        if key in text:
            return ev
    return None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from ppdprobe import probe as ppd_probe
except Exception:
    ppd_probe = None


def run(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=20, stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
    except Exception as exc:
        return -1, "", str(exc)


def queues():
    _, out, _ = run(["lpstat", "-a"])
    return [l.split()[0] for l in out.splitlines() if l.strip()]


def ppd_path(q):
    for d in PPD_DIRS:
        if not d:
            continue
        p = pathlib.Path(d) / f"{q}.ppd"
        if p.exists():
            return str(p)
    return None


def attrs(q):
    """Printer attributes via pycups if available, else parsed from lpoptions."""
    try:
        import cups
        return cups.Connection().getPrinterAttributes(q)
    except Exception:
        pass
    _, out, _ = run(["lpoptions", "-p", q])
    d = {}
    for m in re.finditer(r"(\S+?)=('[^']*'|\S+)", out):
        k, v = m.group(1), m.group(2).strip("'").replace("\n", " ")
        d[k] = v
    if "printer-make-and-model" in d:
        d["printer-make-and-model"] = " ".join(d["printer-make-and-model"].split())
    return d


def mime_edges():
    edges = []
    for d in MIME_DIRS:
        p = pathlib.Path(d)
        if not p.is_dir():
            continue
        for f in p.glob("*.convs"):
            for line in f.read_text(errors="replace").splitlines():
                parts = line.split("#")[0].split()
                if len(parts) >= 4 and "/" in parts[0] and "/" in parts[1]:
                    edges.append((parts[0], parts[1], parts[3]))
    return edges


def reachable(src, dst, edges):
    seen, stack = {src}, [src]
    while stack:
        cur = stack.pop()
        if cur == dst:
            return True
        for a, b, _ in edges:
            if a == cur and b not in seen:
                seen.add(b); stack.append(b)
    return False


def ps_accepted(ppd, a, edges):
    model = str(a.get("printer-make-and-model", ""))
    if "raw" in model.lower():
        return True, "raw queue — any format is passed through verbatim"
    if not ppd:
        return False, "no PPD and not a raw queue (driverless: PDF/PWG-raster only)"
    finals = [m.group(1) for m in
              re.finditer(r'^\*cupsFilter2?:\s*"(\S+)\s', pathlib.Path(ppd).read_text(errors="replace"), re.M)
              if m.group(1) != "application/vnd.cups-command"]
    for f in finals:
        if reachable("application/postscript", f, edges):
            return True, f"a filter chain exists: application/postscript -> {f}"
    producers = sorted({flt for x, y, flt in edges if y == "application/vnd.cups-raster"})
    return False, ("no filter chain application/postscript -> "
                   + (", ".join(finals) or "<none>")
                   + f"; producers of CUPS raster here: {producers or 'none'}")


def report(status, check, detail=""):
    print(f"  {MARK[status]:11s} {check}")
    for l in textwrap.wrap(detail, 92, initial_indent=" " * 16, subsequent_indent=" " * 16):
        print(l)
    return status


def diagnose(q, edges):
    print(f"\n{'='*96}\nQUEUE: {q}\n{'='*96}")
    ppd, a = ppd_path(q), attrs(q)
    model = str(a.get("printer-make-and-model", "?"))
    raw = "raw" in model.lower()
    kind = "PPD (classic driver)" if ppd else ("RAW (pass-through)" if raw else "driverless / no PPD")
    report(INFO, f"Queue type: {kind}", f"model={model}")

    ok_ps, why = ps_accepted(ppd, a, edges)
    rows = ([("PostScript",  "accepted",             "UNTAGGED DeviceRGB",                      "8/16-bit", True)]
            if ok_ps else
            [("PostScript",  "REJECTED by CUPS",     "-",                                       "-",        False)])
    rows += [
        ("image (TIFF/PNG/JPEG)", "converted by the OS image filter",
         "TAGGED sRGB + /Intent (added by the image->PDF filter)", "source depth", False),
        ("PDF, untagged DeviceRGB", "rasterised directly",
         "UNTAGGED /DeviceRGB", "up to 16-bit", True),
    ]
    print("\n  SUBMISSION LADDER — what reaches the driver for each format you could send:")
    print(f"      {'format':26s} {'outcome':36s} {'tagging':48s} {'bits'}")
    for fmt, outcome, tagging, bits, clean in rows:
        print(f"      {fmt:26s} {outcome:36s} {tagging:48s} {bits}")
    print(f"      PostScript: {why}\n")
    good = [r[0] for r in rows if r[4]]
    report(PASS if good else FAIL,
           "An untagged device-colour submission format is available",
           ("use: " + ", ".join(good)) if good else
           "no format reaching this queue keeps the data untagged — measurement is the only check")

    if ppd and ppd_probe:
        try:
            pr = ppd_probe(ppd)
        except Exception as exc:
            pr = None
            report(UNPROVEN, "PPD could not be parsed", str(exc))
        if pr:
            ev = filter_evidence(ppd)
            if pr["no_cm_levers"] != "-" and ev and ev["measured"]:
                report(PASS, "Host chain is colour-neutral on this driver (measured)",
                       f"{pr['no_cm_levers']} — {ev['finding']} So nothing between the "
                       "application and the printer alters your numbers on this driver.")
                report(UNPROVEN, "Whether the printer honours the no-colour flag",
                       ev["residual"])
            elif pr["no_cm_levers"] != "-":
                report(UNPROVEN, "Driver exposes a 'no colour management' option — NOT MEASURED here",
                       f"{pr['no_cm_levers']} — this can be delivered on the job ticket. This "
                       "vendor's filter has NOT been run under a scheduler sandbox on this "
                       "machine, so unlike a measured driver we cannot say it acts on the option "
                       "at all. Weaker evidence than a measured one. See docs/METHOD.md M3 to "
                       "measure it; that costs no ink.")
            else:
                report(FAIL, "Driver exposes no 'no colour management' option",
                       "this PPD has no option/value meaning 'do not colour-manage'")
            report(INFO, "ICC qualifier chain",
                   f"{pr['icc_entries']} cupsICCProfile entries; qualifiers {pr['icc_qualifiers']}")
            if pr["identity_escape"] != "NONE":
                report(PASS, "PPD offers an identity escape on the ICC qualifier",
                       f"{pr['identity_escape']} (is the default: {pr['default_is_escape']}) — a working-space "
                       "profile rather than a paper profile")
            elif pr["icc_entries"]:
                report(FAIL, "PPD offers NO identity escape on the ICC qualifier",
                       "every ICC entry is a paper profile; there is no 'None' value resolving to a "
                       "working space, so nothing selects an identity destination")
    elif not raw:
        types = [str(t) for t in a.get("pwg-raster-document-type-supported", [])]
        dev = [t for t in types if t in PWG_DEVICE]
        if dev:
            report(PASS, "Printer advertises a raw device-colour raster type",
                   f"{dev} — device values can be requested (PWG 5102.4)")
        elif types:
            report(FAIL, "Printer advertises no raw device-colour raster type",
                   f"{types}: every value is an ICC-defined space. No IPP attribute is defined to mean "
                   "'do not colour-manage' — print-color-mode selects colour vs monochrome and every "
                   "print-rendering-intent value is a managed intent (PWG 5100.13).")
        else:
            report(UNPROVEN, "No PPD and no raster attributes readable",
                   "printer may be offline; re-run with it powered on")
    else:
        report(UNPROVEN, "Raw queue — CUPS passes the data through untouched",
               "nothing is converted here, but the PRINTER decides what to do with it and exposes no "
               "lever that can be read. Only a measured print can settle this.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-q", "--queue")
    args = ap.parse_args()
    _, ver, _ = run(["sw_vers", "-productVersion"])
    _, cv, _ = run(["cups-config", "--version"])
    print(f"ladder — platform={sys.platform} os={ver.strip() or 'n/a'} cups={cv.strip() or 'n/a'}")
    edges = mime_edges()
    print(f"  {len(edges)} format conversions known; producers of CUPS raster: "
          f"{sorted({f for a_, b_, f in edges if b_ == 'application/vnd.cups-raster'}) or 'none'}")
    qs = [args.queue] if args.queue else queues()
    if not qs:
        print("\nNo print queues found."); return 1
    for q in qs:
        diagnose(q, edges)
    print("\n  UNPROVEN is not a soft PASS. The only way to turn it into PASS is to print and measure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
