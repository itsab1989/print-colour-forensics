# Examples

Everything here is **synthetic and hand-written**. No vendor PPD, ICC profile, driver
binary or captured vendor stream is redistributed, and nothing here contains personal
data, machine names or device serials.

## `fixture-with-escape.ppd` / `fixture-no-escape.ppd`

Two hand-written PPDs modelling the two archetypes found in the wild. They are the
positive control for `tools/ppdprobe.py`: run it on both and the report must differ.

```bash
python3 ../tools/ppdprobe.py fixture-with-escape.ppd fixture-no-escape.ppd
```

```
fixture-with-escape.ppd  (Example Inkjet With Escape)
   no-CM lever(s)        : XXColorMatch=3
   cupsICCProfile entries: 3   qualifiers: 3:XXProfileSpec
   IDENTITY ESCAPE       : sRGB Profile   (is the default: True)
   AP custom matching    : supported=True  choices=sRGB,AdobeRGB  forced_default=-

fixture-no-escape.ppd  (Example Inkjet No Escape)
   no-CM lever(s)        : YYIntent=1001
   cupsICCProfile entries: 3   qualifiers: 2:YYProfileID
   IDENTITY ESCAPE       : NONE
   AP custom matching    : supported=True  choices=-  forced_default=sRGB
```

The difference is the point. One driver lets you select a destination that is a plain
working space; the other offers only paper profiles and forces an sRGB source default.
See `docs/FINDINGS-macos.md` F6.

## Why no captured streams

A vendor's print stream is the vendor's output and may embed device identifiers. If you
capture your own (`docs/METHOD.md` M3), check it for serials and hostnames before sharing:

```bash
strings -a capture.prn | grep -inE "serial|[0-9A-F]{8}-[0-9A-F]{4}|\.local|[0-9]{1,3}(\.[0-9]{1,3}){3}"
```
