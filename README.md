# print-colour-forensics

**How to find out what your operating system actually does to a print job's colour —
and whether the chart you just printed reached the printer untouched.**

If you print ICC profiling targets, you need device values to arrive at the printer
unchanged. Every layer between your application and the paper can silently re-map
them: the OS rasteriser, the vendor's filter, the printer's firmware. Ticking "no
colour management" in a driver dialog proves nothing — and neither does a log line
saying the option was set.

This repository is a set of small, mostly-stdlib tools for **measuring** what really
happens, plus the method and the traps, written up so you can extend it to a printer
nobody here has ever seen.

Nothing here prints anything. Every tool is read-only or writes to a capture file.

## Quickstart — "what will actually reach my printer?"

```bash
python3 tools/ladder.py
```

Prints, for every queue on the machine, which submission format wins, whether the data
reaches the driver **tagged or untagged**, and at what **bit depth** — plus the driver's
colour levers, with per-check `PASS` / `FAIL` / `UNPROVEN`.

Example output (a classic-driver inkjet queue on macOS):

```
  SUBMISSION LADDER — what actually reaches the printer in each configuration:
      configuration            format                      tagging                       bits
   ACTIVE -> native dialog     PrintCore PDF               TAGGED sRGB                   8-bit
             lp, PDF off       PS REJECTED -> raw TIFF     TAGGED sRGB + /Intent          16-bit
             lp, PDF on        PS REJECTED -> exact PDF    UNTAGGED /DeviceRGB            16-bit
```

`UNPROVEN` is never a soft pass. It means a lever exists and is delivered, but nothing
outside the printer can confirm the driver honours it.

## What is in here

| path | what it does |
|---|---|
| `tools/ladder.py` | per-queue submission ladder + lever report (the quickstart) |
| `tools/ppdprobe.py` | PPD capability matrix: no-CM levers, ICC qualifier chain, **identity escape**, AP custom matching |
| `tools/ticketwatch.py` | **pause your queue, print freely, see which settings the driver changed behind your back** |
| `tools/ippcapture.py` | a fake IPP queue that captures what any application spools — ticket **and** document |
| `tools/rasterdecode.py` | CUPS raster → pixel values (**read the endianness note**) |
| `tools/cgpdftoraster_harness.py` | run a host rasteriser offline and diff pixels across option sets |
| `tools/vendorstream.py` | normalise a vendor stream (nonce masking) so two runs are comparable |
| `tools/pcl3parse.py` | parse a PCL-3-style vendor stream into plane transfers — **compare payloads, never bytes** |
| `tools/cupsdsandbox/` | build + run your **own** CUPS scheduler so a vendor filter runs under your control |
| `docs/METHOD.md` | the method, its costs and its blind spots — **start here** |
| `docs/TRAPS.md` | experiments that produced convincing, wrong answers, and how to avoid them |
| `docs/FINDINGS-macos.md` | measured facts for macOS 15.7.9 / CUPS 2.3.4, with numbers |

## Operating rules

**1. No null result without a positive control.** See below.

**2. If you did not change a printer's state, do not "restore" it.** These tools work by
*pausing* a queue so jobs pile up instead of printing. A paused queue looks like a fault, and
the reflex is to resume it. If someone else paused it — a colleague, the user you are helping,
your own earlier self acting deliberately — resuming it releases every held job to the paper.
Before any cleanup that touches a printer, establish whether the state you are about to change
was ever yours to change. This footgun has already been triggered once during development; the
only reason it cost nothing is that the printer happened to be offline.

## The one rule

**No null result without a positive control.**

"I changed the option and the output did not change" and "the option was never parsed"
look identical. Before believing any null, prove your instrument can see a change:
mutate something that *must* alter the output (a `*Default...` line in a copied PPD, the
source colour space of the test file) and confirm your measurement moves.

Two findings in `docs/TRAPS.md` were fabricated root causes that survived review until a
control killed them. Read that file before you trust your own results.

## Portability

`ppdprobe.py`, `rasterdecode.py`, `vendorstream.py` and `ippcapture.py` are pure stdlib
and portable to any CUPS system. `ladder.py` reads CUPS state and is macOS/Linux.
`cgpdftoraster_harness.py` and `nativespool.py` are macOS-specific — they test
Apple's `cgpdftoraster` / `cgimagetopdf` / PrintCore, which do not exist elsewhere.
Windows shares none of this chain; see `docs/METHOD.md`.

## Scope and honesty

Measurements are stated with the OS and CUPS version attached. Anything not measured is
marked unproven. Vendor drivers are closed binaries: this toolkit can prove that a lever
*reaches* them and that they *react* to it, and — with a scheduler sandbox — that nothing
else does. It cannot prove what the reaction means without printing and measuring a sheet.
That limit is the whole argument for verifying by measurement, per printer, per paper.

No vendor PPDs, ICC profiles or driver binaries are redistributed here. Fixtures are
synthetic and hand-written.
