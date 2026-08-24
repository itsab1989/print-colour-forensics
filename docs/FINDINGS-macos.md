# Measured findings — macOS 15.7.9 (24G830), CUPS 2.3.4, Apple Silicon

Every number here was produced with the methods and controls in `METHOD.md`. Anything not
measured is marked **UNPROVEN**. Hardware: one classic-driver photo inkjet ("Printer A", a
Canon PRO-300-class CNIJ driver), one classic-driver inkjet ("Printer B", an Epson
ET-8550-class driver), one raw pass-through queue.

## F1 — The host rasteriser passes untagged device colour through bit-exact

Untagged `/DeviceRGB` PDF → `cgpdftoraster` with Printer A's PPD, 16 bit:

```
source band            raster band            verdict
(32895,32896,32640)    (32895,32896,32640)    exact
(1000,2000,3000)       (1000,2000,3000)       exact
(12345,23456,34567)    (12345,23456,34567)    exact
```

A real 940-patch chart, sampling only patch cores (9×9 uniform erosion, so resampling is
excluded): **421 distinct core colours, 0 not present in the source.**

## F2 — The transform is *source-side*; `cupsICCProfile` is ignored entirely

Varying only the source colour space of an otherwise identical file:

| source | result |
|---|---|
| untagged `/DeviceRGB` | passthrough |
| `/ICCBased` **sRGB** | **identical to untagged** (sRGB→sRGB is identity) |
| `/ICCBased` AdobeRGB | **different** — a real conversion |

And the destination side does nothing at all. With a PPD copy in which **all 18**
`*cupsICCProfile` targets were replaced by a foreign profile, plus an added wildcard
catch-all entry:

```
stock PPD / catch-all / all-foreign, untagged   -> identical, identical, identical
stock / all-foreign, sRGB-tagged                -> identical
stock / all-foreign, AdobeRGB-tagged            -> identical (to each other)
```

**`cgpdftoraster` ignores `*cupsICCProfile` on this OS version** — for untagged,
sRGB-tagged and AdobeRGB-tagged input alike. Adding
`AP_ColorMatchingMode=AP_ApplicationColorMatching` changed nothing in any combination
tested here.

> Widely-repeated claims that the host rasteriser applies a PPD's `cupsICCProfile`
> destination transform *even to untagged device colour* did not reproduce under
> controlled test on this OS version. If you have seen that behaviour, it is worth
> re-checking whether the input was in fact **tagged**.

## F3 — Two common paths silently tag your data

* **`cgimagetopdf`** (the filter that runs when you submit an image such as a TIFF) emits
  `/ColorSpace [/ICCBased …]` whose embedded profile is **`sRGB IEC61966-2.1`**, plus
  `/Intent /Perceptual`. Your untagged chart becomes tagged sRGB.
* **A Cocoa print path** that builds an `NSBitmapImageRep` with `NSDeviceRGBColorSpace`
  (`rep.colorSpace()` → `kCGColorSpaceDeviceRGB`) spools, in the **real** captured job,
  `/ICCBased` with **`sRGB IEC61966-2.1`** at `/BitsPerComponent 8`. Quartz tags it on the
  way out. "Device RGB" in the API name does not survive to the spool.

On this OS the sRGB tag is *benign* (F2: sRGB→sRGB is identity). It would not be benign if
the tag were anything else, and it means the data now carries a declared source space for
anything downstream to convert *from*.

## F4 — PostScript cannot reach a raster device here

The only producer of `application/vnd.cups-raster` on this system is `cgpdftoraster`, from
`application/pdf`. PostScript's only edges are to `application/vnd.cups-postscript`
(`pstops`) and `application/vnd.apple-postscript` (`pstoappleps`). There is **no path** from
PostScript to PDF or to CUPS raster.

Measured on the wire, submitted held so no job was created:

```
$ lp -H hold -d <classic-driver queue> chart.ps
exit 1 — Document format "application/postscript" not supported.
```

Both classic-driver queues rejected it. **The raw queue accepted it** — format support is
per-queue and should be negotiated (`document-format-supported`), not guessed and retried.

## F5 — The driver SILENTLY OVERRIDES "no colour management" for some papers

Printer A's raster filter, run under a user-built CUPS scheduler with a capture backend
(`METHOD.md` M3). Its stream is PCL-3-style (`ESC*t600R`, `ESC*r1A`, mode 4, per-row
`ESC*b<n>V…W`), 3 planes per row, preceded by an XML preamble that records the job settings.

**Controls used, and one of them invalidated three of my own earlier results:**

1. *Determinism* — same configuration ×3 is byte-identical after masking two nonces.
2. *Parse, don't diff* — a positional diff reported 72 913/82 423 bytes changed when only a
   flag word changed length. See `TRAPS.md` T8.
3. *Did the option land?* — the preamble records each setting, so you can check the driver
   actually received it. **It usually had not.** See `TRAPS.md` T9.

### The finding

The preamble carries `<ivec:printcolormode_intent>`, whose value is `none` for "no colour
correction" and `pro` for the photo intent. Requesting **no colour correction** for every
media type the PPD offers:

| media requested | flag actually sent | verdict |
|---|---|---|
| Photo Paper Pro Platinum | `none` | honoured |
| Photo Paper Plus Glossy II | `none` | honoured |
| Baryta Photo Paper | `none` | honoured |
| Lightweight Photo Paper | `none` | honoured |
| **Plain Paper** | **`pro`** | **silently overridden** |
| **Card Stock** | **`pro`** | **silently overridden** |
| Matte Photo / Premium Fine Art Smooth | job rejected by the filter | — |

**Deterministic: 5 runs of Plain Paper, 5× `pro`.** The override is **one-way** — asking for
the photo intent never yields `none`. And the PPD declares **no `UIConstraints`** involving
the intent option, so nothing tells CUPS, the application or the user that the setting is
unavailable on those papers. The job ticket says "no colour correction"; the data sent to
the printer says "photo".

**This is a mechanism by which a chart is colour-managed while every visible indicator says
it is not.** It is invisible to any check that inspects the application's own settings, the
job ticket, or the PPD.

### What the host does to the pixels

* **No cross-channel transform.** Swapping R and B in the source produced **exactly swapped
  planes in 3709 of 3709 rows (100.0 %)**, with the middle plane byte-identical. No matrix,
  LUT, gamut mapping or ink separation can do that — those all mix channels.
* **Neutrals stay neutral.** A neutral source yields three identical planes in 100 % of rows.
* **White produces no data at all** — a uniform 255 image emits zero content rows, so the
  planes are ink quantities, addressed per channel.
* **The intent flag does not change the pixels.** With the flag *verified* to have landed
  (`pro` vs `none` in the preamble), the extracted raster payload is byte-identical. The
  colour decision is passed to the printer, not executed on the computer.

### Withdrawn for lack of a control

Earlier drafts stated that the per-paper ICC selector, media type and print quality are
"inert" because the payload did not change. **Those were uncontrolled nulls**: the preamble
shows quality stayed at its default and the paper was always recorded as a generic custom
type, i.e. the mutations never landed. Media *does* reach the driver's logic — it changes
the intent flag and the quality field — so "media has no effect" is withdrawn outright. What
survives is only the intent result above, where landing was positively verified.

### Still unknown

Whether the printer's firmware honours the flag it is sent. The computer never performs the
transform, so no software here can observe it. Only a printed, measured sheet can settle it.

## F6 — Vendors differ structurally in whether an identity escape exists

`ppdprobe.py` on the two classic-driver PPDs:

```
Printer A     no-CM lever : <vendor intent option> = "No Color Correction"
              ICC entries : 18   qualifier: 2:<vendor ProfileID>
              IDENTITY ESCAPE : NONE
              AP custom matching: supported=True  choices=-  forced_default=sRGB

Printer B     no-CM lever : <vendor matching option>=Off, <vendor source profile>=0
              ICC entries : 9    qualifier: 3:<vendor profile spec>
              IDENTITY ESCAPE : sRGB Profile   (and it is the DEFAULT)
              AP custom matching: supported=True  choices=sRGB,AdobeRGB  forced_default=-
```

Printer B's qualifier option has a `0/None` value whose `*cupsICCProfile` is the system
**sRGB profile** — a working space, not a paper profile — and that value is the PPD
default. Printer A has no such value: every one of its 18 entries is a real paper profile,
and it declares no `*APCustomColorMatchingProfile` choices at all, only a forced sRGB
default.

This is a structural, surveyable difference and a plausible reason two vendors behave
differently. It is **not** proven to be causal on this OS, where the ICC chain is ignored
anyway (F2) — but it would matter on any OS or path where it is not.

## F7 — Queue classification, and a trap

A queue whose device URI was `ipps://…/ipp/print` reported
`printer-make-and-model = "Local Raw Printer"` — a **raw** queue, not driverless. Classify
from the model string and the presence of a PPD.

## F8 — Driverless / AirPrint has no standardised "off"

From the IANA IPP registry:

* `print-color-mode` (PWG 5100.13): `auto, auto-monochrome, bi-level, color, highlight,
  monochrome, process-bi-level, process-monochrome` — **no `device`, `raw` or `none`**.
* `print-rendering-intent` (PWG 5100.13): `absolute, auto, perceptual, relative,
  relative-bpc, saturation` — **every value is a managed intent**.
* `print-color-mode-icc-profiles` exists as a printer attribute: the model is explicitly
  colour-managed.
* PWG 5102.4 **does** define raw device raster types `device1_8` … `device15_16`. That is
  the only standardised route to device values, and the printer must advertise it. Both
  classic-driver queues here advertise only `black_1, sgray_8, srgb_8`.

**For a driverless printer you cannot guarantee colour passthrough from attributes alone.**
Check `pwg-raster-document-type-supported` for a `deviceN` type; if absent, measure.

**Caveat:** no true IPP-Everywhere device was reachable during these tests, so F8 rests on
the specification and on scheduler-synthesised attributes, not on a live AirPrint printer.


## F9 — A print job can carry another manufacturer's settings

Three real jobs, captured from a **paused** queue so nothing printed, with the vendor's own
print-dialog plug-in running (Canon classic driver, "Printer A"):

```
job1: MediaType= 0  ProfileID=1  + 77 EPIJ_* and 12 EPSON.* keys, ColorModel=RGB,
                                   APCustomColorMatchingProfile=sRGB
job2: MediaType=51  ProfileID=3   (no foreign keys)
job3: MediaType= 0  ProfileID=1   (no foreign keys)
```

Job 1 carried **89 settings belonging to a different manufacturer's driver** — an Epson —
on a Canon job, in a session where that other printer had been used. Two of those matter:

* `ColorModel = RGB` — **not a value this PPD offers** (it declares only `RGB16`);
* `APCustomColorMatchingProfile = sRGB` — a key that **declares the data's source space as
  sRGB**, which is an invitation for the system to convert from it.

Both appear **only** on the contaminated job.

**The general rule this establishes:** a print-settings object is not necessarily
per-printer. Vendor-specific keys can survive a printer change within a session and ride
out on a job for a completely different device. An application that carefully sets the right
keys for the selected printer can still ship a job carrying a *previous* printer's keys.

**Explicitly withdrawn:** an earlier draft attributed the `sRGB` key to the PPD's
`*APDefaultCustomColorMatchingProfile: sRGB` being filled in by the print system. The data
refuses that: it would then appear on all three jobs, and it appears on one. The correlation
is with the foreign-key contamination, not with the PPD default.

**Not yet established:** the exact trigger (printer switch inside the dialog vs a previous
completed job vs stored per-app state). A discriminating run plan is in
`EXAMPLE-RUN-PLAN.md`.

## F10 — What the driver's pane displays is not what the job carries

In the same captures, the vendor's colour pane showed **"Perceptual", greyed out**, while
the job on the wire carried the vendor's *no colour correction* value. In a later job the
pane showed "No Color Correction" for the same setting.

**Never diagnose from the driver dialog.** It can display a value the job does not carry,
in either direction. Read the job.

## F11 — Media type can differ from what was selected

Across the three jobs the media type read `0`, then `51`, then `0`, with the per-paper ICC
selector tracking it (`1`, `3`, `1`). The user reports having selected the same paper for
the second and third. This is **user-reported, single-instance** and does not yet separate
"the driver reverted it" from "it was not set that time"; `EXAMPLE-RUN-PLAN.md` set A is
designed to decide it.

Note what it *does* settle: when the plug-in runs, it **does** pair the ICC selector with the
media type correctly. The static mismatch in the PPD's defaults (F6-adjacent) is therefore a
resting-state property, not what the plug-in produces.


## F12 — The driver discards the user's media and quality choice after ONE job

Eleven consecutive real jobs, captured from a **paused** queue (no ink, no paper), eight from
a colour-managed application that locks its colour keys and three from Apple's Preview, which
does not:

| job | app | what the user did | media recorded | quality | intent flag |
|---|---|---|---|---|---|
| 1 | App A | set Plain (after switching from another printer) | Plain | Normal (default) | no-correction |
| 2 | App A | set Plain again | **Platinum (DEFAULT)** | Normal | no-correction |
| 3 | App A | set Plain (repeat) | Plain | Normal | no-correction |
| 4 | App A | **touched nothing** | **Platinum (DEFAULT)** | Normal | no-correction |
| 5 | App A | set Semi-gloss + Fine | Semi-gloss | **Fine** | no-correction |
| 6–8 | App A | **touched nothing** ×3 | **Platinum (DEFAULT)** ×3 | Normal | no-correction |
| 9 | Preview | set Semi-gloss + no-correction | Semi-gloss | Fine | no-correction |
| 10–11 | Preview | **touched nothing** ×2 | **Platinum (DEFAULT)** ×2 | Normal | **PERCEPTUAL** |

**The rule:** an explicit Quality & Media selection survives **one** job. The next job reverts
to the PPD defaults — and if the application has not *locked* the rendering intent, that
reverts too, silently re-enabling colour management against an explicit "no colour correction"
choice.

Reproduced in **Apple's Preview with the profiling application not involved**, so this is the
driver's behaviour, not an application bug.

**What protects you:** the application that set
`AP_ColorMatchingMode = AP_ApplicationColorMatching` held the intent at *no correction* on
**8 of 8** jobs through exactly the interaction that flipped Preview to Perceptual. That lock
works. **What it does not protect:** media and quality, which reverted on 5 of those same 8
jobs. For profiling that matters — media type drives ink limit and laydown.

**Also decoded here:** `CNIJColorMatchingMode` = `1` on all 8 locked jobs and `0` on all 3
unlocked ones, tracking application-managed vs driver-managed exactly.

## F13 — The vendor filter silently OVERRIDES "no colour correction" on plain-paper media

Requesting the driver's *no colour correction* value for **all 25 media types** the PPD
declares, via `lp` (so no print dialog and no vendor plug-in are involved):

| outcome | count | media |
|---|---|---|
| honoured (`none` on the wire) | 15 | every photo, fine-art, canvas and disc media |
| **silently overridden to the photo intent** | **6** | **Plain Paper, Hagaki ×3, Inkjet Greeting Card, Card Stock** |
| job rejected by the filter | 4 | Matte Photo Paper, Premium Fine Art Smooth/Rough, Pro Premium Matte |

Deterministic (5/5 on Plain Paper), and **one-way** — asking for the photo intent never yields
`none`. The PPD declares **no `UIConstraints`** involving the intent option, so nothing warns
CUPS, the application or the user.

**Which layer does it — named from evidence.** The scheduler's own log shows it handed the
filter `CNIJIntent2=1001 CNIJMediaType=0`, and the filter emitted
`printcolormode_intent = pro`. No dialog, no plug-in. **The vendor's raster filter performs
the override.**

**Reproduced on the user's own real jobs.** Two of his held jobs were retrieved intact
(`CUPS-Get-Document`) and replayed with their own ticket options:

```
his job with media=Plain,    intent=no-correction  ->  wire says 'pro'   OVERRIDDEN
his job with media=Platinum, intent=no-correction  ->  wire says 'none'  honoured
```

**Landing control:** media demonstrably reached the filter — it changed the emitted quality
field across the sweep (2 distinct signatures). Without that check this table would be
worthless; see `TRAPS.md` T9.

## F14 — Two vendors, one architecture: the colour decision travels as a flag

The other manufacturer's driver on the same machine was put through the same sandbox. Flipping
its no-colour-adjustment value changed **5 bytes out of 192 110**: three are a job hash, one is
a timestamp, and **one is the colour flag** (`0x06` vs `0x17`, inside a `setq` record). The
image data is untouched.

So on **both** classic drivers tested, the host does not apply or omit a colour transform — it
writes a flag and the printer decides. This is likely to be the norm for host-based inkjet
drivers, and it means **no amount of inspection on the computer can confirm colour passthrough**
for this whole class of device.

*Not tested for the other vendor:* whether it has an equivalent media-dependent override. Its
media option could not be shown to have landed, so that null is not reportable.
