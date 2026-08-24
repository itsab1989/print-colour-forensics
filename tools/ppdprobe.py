#!/usr/bin/env python3
"""ppdprobe — what colour levers does a PPD actually expose?

Answers four questions the usual "is there a no-colour-management option?"
survey never asked, and which appear to be the structural reason one vendor
behaves and another does not:

  1. no-CM UI lever        e.g. Epson EPIJ_CMat=3, Canon CNIJIntent2=1001
  2. ICC qualifier chain   which options select *cupsICCProfile (cupsICCQualifier1/2/3)
  3. IDENTITY ESCAPE       does the qualifier option have a "None"/0 value whose
                           *cupsICCProfile is a plain working-space profile
                           (sRGB/AdobeRGB/Generic) rather than a paper profile?
  4. AP custom matching    *APSupportsCustomColorMatching plus whether the PPD
                           actually declares *APCustomColorMatchingProfile
                           choices, or only a forced default.

WHAT IT PROVES: what the driver *offers*. Nothing more.
WHAT IT CANNOT PROVE: that any of it is honoured by the vendor's filter or by
the printer. On macOS 15.7.9 / CUPS 2.3.4 the host rasteriser was measured to
ignore *cupsICCProfile entirely -- so a PPD's ICC chain can be structurally
interesting and still have no effect on that OS. Verify by measurement.

POSITIVE CONTROL: run it against a PPD you have edited (e.g. change a
*Default... line, or delete the identity escape) and confirm the report changes.

Usage:
    python3 ppdprobe.py /etc/cups/ppd/*.ppd
    python3 ppdprobe.py --csv corpus/*.ppd > matrix.csv
Portable: pure stdlib, works anywhere a PPD file can be read.
"""
from __future__ import annotations
import re, sys, pathlib, csv

NO_CM_VALUE = (r"no\s+colou?r\s+adjustment", r"application[\s-]*(managed|controlled)",
               r"(managed|controlled)\s+by\s+application",
               r"no\s+colou?r\s+(management|matching|correction)",
               r"colou?r\s+(management|matching|correction)\s+off", r"uncalibrated")
CM_OPT = (r"colou?r.*(match|manag)", r"(match|manag).*colou?r",
          r"colou?r\s*(setting|option|mode|correction|control|process|transform)",
          r"^rgb\s+colou?r$")
GENERIC_OFF = (r"^\s*off\s*$", r"^\s*none\s*$", r"^\s*application(\s+matching)?\s*$",
               r"^\s*device\s*$")
# A profile path/name that is a working space, not a paper/device profile.
WORKING_SPACE = re.compile(r"(sRGB|AdobeRGB|Adobe RGB|Generic RGB|GenericRGB|"
                           r"ColorSync/Profiles/[^/\"]*(sRGB|Generic|Adobe))", re.I)


def options(text: str):
    lines = text.splitlines()
    openui = re.compile(r'^\*OpenUI\s+\*([A-Za-z0-9_]+)\s*/([^:]*):\s*PickOne', re.I)
    i = 0
    while i < len(lines):
        m = openui.match(lines[i])
        if not m:
            i += 1; continue
        key, label = m.group(1), m.group(2).strip()
        vals, j = [], i + 1
        vre = re.compile(rf'^\*{re.escape(key)}\s+([^\s/]+)\s*/([^:]*):')
        while j < len(lines) and not lines[j].startswith("*CloseUI"):
            vm = vre.match(lines[j])
            if vm: vals.append((vm.group(1), vm.group(2).strip()))
            j += 1
        yield key, label, vals
        i = j + 1


def probe(path: str) -> dict:
    t = pathlib.Path(path).read_text(errors="replace")
    opts = list(options(t))
    defaults = dict(re.findall(r'^\*Default([A-Za-z0-9_]+):\s*(\S+)', t, re.M))

    levers = []
    for key, label, vals in opts:
        is_cm = any(re.search(r, label, re.I) for r in CM_OPT)
        for val, vlabel in vals:
            if any(re.search(r, vlabel, re.I) for r in NO_CM_VALUE):
                levers.append(f"{key}={val}"); break
            if is_cm and any(re.match(r, vlabel, re.I) for r in GENERIC_OFF):
                levers.append(f"{key}={val}"); break

    quals = {n: m.group(1) for n in (1, 2, 3)
             for m in [re.search(rf'^\*cupsICCQualifier{n}:\s*(\S+)', t, re.M)] if m}
    icc = re.findall(r'^\*cupsICCProfile\s+(\S+?)/([^:]*):\s*"([^"]*)"', t, re.M)

    # identity escape: an ICC entry whose target is a plain working space
    escapes = [(sel, name) for sel, name, target in icc
               if WORKING_SPACE.search(target) or WORKING_SPACE.search(name)]

    # is the qualifier option's default the escape?
    qual_key = quals.get(2) or quals.get(3) or quals.get(1)
    qual_default = defaults.get(qual_key) if qual_key else None
    default_is_escape = None
    if qual_key and qual_default is not None:
        default_is_escape = any(sel.strip(".").split(".")[-1] == qual_default
                                or sel.split(".")[-2:] == [qual_default, ""]
                                or qual_default in sel.split(".")
                                for sel, _ in escapes)

    ap_supports = bool(re.search(r'^\*APSupportsCustomColorMatching:\s*True', t, re.M))
    ap_choices = re.findall(r'^\*APCustomColorMatchingProfile\s+(\S+)/', t, re.M)
    ap_default = (re.search(r'^\*APDefaultCustomColorMatchingProfile:\s*(\S+)', t, re.M) or [None])
    ap_default = ap_default.group(1) if hasattr(ap_default, "group") else None

    final = [m.group(1) for m in re.finditer(r'^\*cupsFilter2?:\s*"(\S+)\s', t, re.M)]
    return {
        "ppd": pathlib.Path(path).name,
        "model": (re.search(r'^\*ModelName:\s*"([^"]*)"', t, re.M) or [None]) and
                 (re.search(r'^\*ModelName:\s*"([^"]*)"', t, re.M).group(1)
                  if re.search(r'^\*ModelName:\s*"([^"]*)"', t, re.M) else ""),
        "no_cm_levers": ";".join(levers) or "-",
        "icc_entries": len(icc),
        "icc_qualifiers": ",".join(f"{k}:{v}" for k, v in sorted(quals.items())) or "-",
        "identity_escape": ";".join(n for _, n in escapes) or "NONE",
        "default_is_escape": default_is_escape,
        "ap_custom_matching": ap_supports,
        "ap_choices": ",".join(ap_choices) or "-",
        "ap_forced_default": ap_default or "-",
        "final_types": ",".join(t2 for t2 in final if t2 != "application/vnd.cups-command") or "-",
    }


def main(argv):
    as_csv = "--csv" in argv
    paths = [a for a in argv[1:] if not a.startswith("--")]
    rows = []
    for p in paths:
        try: rows.append(probe(p))
        except Exception as exc: print(f"  {p}: ERROR {exc}", file=sys.stderr)
    if as_csv:
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows); return 0
    for r in rows:
        print(f"\n{r['ppd']}  ({r['model']})")
        print(f"   no-CM lever(s)        : {r['no_cm_levers']}")
        print(f"   final content type    : {r['final_types']}")
        print(f"   cupsICCProfile entries: {r['icc_entries']}   qualifiers: {r['icc_qualifiers']}")
        print(f"   IDENTITY ESCAPE       : {r['identity_escape']}"
              + (f"   (is the default: {r['default_is_escape']})" if r['identity_escape'] != 'NONE' else ""))
        print(f"   AP custom matching    : supported={r['ap_custom_matching']}  "
              f"choices={r['ap_choices']}  forced_default={r['ap_forced_default']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
