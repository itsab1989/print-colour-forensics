# Measured findings — macOS 15.7.9 (24G830), CUPS 2.3.4, Apple Silicon

Every number here was produced with the methods and controls in `METHOD.md`. Anything not
measured is marked **UNPROVEN**. Hardware: one classic-driver photo inkjet ("Printer A", a
Canon PRO-300-class CNIJ driver), one classic-driver inkjet ("Printer B", an Epson
ET-8550-class driver), and one queue with **no device behind it** — a leftover record for a
printer that had been disposed of. That third queue was originally described as a raw
pass-through queue and was cited as evidence in F4 and F7; **both citations are withdrawn**
(`TRAPS.md` T13). Nothing measured from it describes a printer.

The driverless/IPP-Everywhere path is instead measured against a **software IPP Everywhere
printer** stood up locally (`ippeveprinter`, CUPS 2.4.19) — see F15, including what a
software printer cannot tell you.

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

Both classic-driver queues rejected it.

> **⚠ The third queue's result is WITHDRAWN as evidence.** It was recorded as *"the raw queue
> accepted it"*. That queue was not raw — it was **driverless** (F7, corrected) — and, worse,
> **it had no device behind it at all**: the printer had been disposed of and only the local
> queue record remained, so CUPS held none of its capabilities. What the test measured is that
> **cupsd accepts a format for a queue with nothing attached**. It says nothing about a raw
> queue, nothing about a driverless queue, and nothing about any printer. See `TRAPS.md` T13.

**What still stands from F4:** format support is per-queue and must be negotiated by reading
`document-format-supported`, never guessed and retried. That follows from the two
classic-driver rejections on their own.

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

## F7 — Queue classification, and a trap **(CORRECTED — the original was backwards)**

> **Withdrawn 2026-08-24.** This entry read: *"A queue whose device URI was
> `ipps://…/ipp/print` reported `printer-make-and-model = "Local Raw Printer"` — a raw queue,
> not driverless. Classify from the model string and the presence of a PPD."* **That is
> false.** `Local Raw Printer` is CUPS's placeholder for a queue with **no PPD**; a
> driverless queue carries it too. The queue was driverless. Following this entry's advice
> shipped a misclassification in our own tooling — `TRAPS.md` T13.

**Corrected rule**, verified against three queues on one machine (two classic-driver, one
driverless):

```
PPD present?                      -> classic driver queue   (URI scheme is irrelevant here)
else scheme ipp/ipps/dnssd/mdns   -> driverless / IPP Everywhere
else scheme socket/lpd/usb/...    -> raw pass-through
```

The order is load-bearing: **both classic-driver queues on that machine use `dnssd://`**, so
a scheme-first rule misfiles them, and a model-string rule misfiles the driverless one.
Placeholders (`Local Raw Printer`, `Unknown`, empty) must be treated as *absent*, never as a
value.

**And check that anything answered.** A queue can outlive its device. Assert at least one
attribute that only a device supplies — `urf-supported`, `print-color-mode-supported`,
`pwg-raster-document-type-supported`, `media-type-supported`, `printer-device-id`. Do **not**
use `ipp-features-supported`, `printer-uuid`, `marker-colors` or `document-format-supported`:
the scheduler generates those on every queue, live or dead, and a liveness check built on them
cannot fail.

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

**Caveat, now narrowed — see F15:** this originally rested on the specification plus
attributes synthesised by a scheduler for a queue with no device. It is now measured against
a conformant IPP Everywhere printer, with a positive control. What is still missing is
**hardware**.

## F15 — What a conformant driverless printer actually advertises, measured

Measured against a real IPP Everywhere / AirPrint printer served locally by `ippeveprinter`
(CUPS 2.4.19). No paper, no ink, no hardware: the "printer" is a program with real IPP
attributes and a real job pipeline. This replaces every earlier number taken from a queue that
had no device behind it (F4, F7, `TRAPS.md` T13).

**A conformant COLOUR driverless printer, default attribute set:**

| attribute | value | consequence |
|---|---|---|
| `print-color-mode-supported` | `auto, color, monochrome` | chooses colour **versus** monochrome. Nothing chooses whether a transform runs |
| `print-rendering-intent-supported` | `auto` | PWG 5100.13 defines exactly six values — absolute, auto, perceptual, relative, relative-bpc, saturation — and **every one is a managed intent**. There is no `none` and no `off` |
| `pwg-raster-document-type-supported` | `black_1, sgray_8, srgb_8, srgb_16` | **every value is an ICC-defined space.** No raw device colour offered |
| `urf-supported` | `CP1, IS1-…, MT1-…, RS600, SRGB24, V1.4, W8` | Apple's raster format is an sRGB space by definition |
| `printer-icc-profiles` | absent | when present it names the profiles the printer *will* use; it is not an escape from using one |
| `color-supported` | `true` | says the device can print colour, nothing about management |

**The positive control (TRAPS T3):** a second printer configured to advertise
`device3_8, device3_16` — the raw device types PWG 5102.4 defines as `deviceN_8`/`deviceN_16`
for N = 1..15, which CUPS parses over exactly that range
(`cups/raster-stream.c:307-312`). **The probe detects them.** So "a conformant colour
driverless printer offers no raw device colour" is a measured absence: the same check returns
FAIL on the first printer and PASS on the second.

**Controls on the job path (TRAPS T2, T9):**

* the submitted PDF arrives at the print command **byte-identical** (same md5) — the harness
  can see the document;
* every attribute sent appears in the printer's own environment receipt — **10/10 landed**
  across `print-color-mode` × `print-rendering-intent`;
* the capture script reads the document from `argv[1]`, not stdin. Reading stdin yields 0
  bytes, which would have been recorded as *"the document arrived empty"*.

**What this CANNOT establish — stated before it is used:**

1. **A software printer has no firmware, no ink and no colour engine.** Everything here is
   about what the *attribute model* offers and what a *job carries*. A real printer's firmware
   may differ in every respect that matters.
2. **`ippeveprinter` does not validate attribute values.** It accepts
   `print-rendering-intent=none`, a value it does not advertise, with `successful-ok` — and it
   keeps accepting it under `ipp-attribute-fidelity=true`, where RFC 8011 §15 requires the job
   to be rejected and the attribute reported as unsupported. **That is this implementation's
   laxity, not IPP's behaviour and not a real printer's.** No conclusion above rests on it, and
   in particular *"driverless printers accept an unmanaged intent"* is **not** a finding.

**Net position, unchanged in substance and now earned:** IPP has no attribute meaning *"do not
colour-manage"*. The only standardised route to unmanaged values is a `deviceN` raster type
that the printer must advertise. Check for it, use it when present, report UNPROVEN when not,
and reach for a measured sheet in every other case.


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

## F12b — Closing a driver pane with **Cancel** discards the application's locks *in the dialog*, but not *on the wire*

A follow-up to F12 that names one cause of the reversion, and separates two things that are
easily conflated: what the dialog shows, and what the job carries.

**On screen** (a locking application, real print dialog, nothing submitted):

| step | observed |
|---|---|
| dialog opens with three colour keys locked | paper preselected correctly; rendering intent **greyed**, reading *no correction*. **The paper menu remains fully selectable** — locking the per-paper profile key greys nothing the user needs |
| change the paper, close a pane with **Cancel**, reopen it | **every lock is gone**: the controls are editable again, the paper has reverted to the PPD default, the intent reads *Perceptual* |

**On the wire** (the same action with a print attached, captured from a paused queue):

| job | pane closed with Cancel | submitted ticket |
|---|---|---|
| A | Color Matching | unchanged — identical to the uncancelled control apart from one unrelated key |
| B | **Quality & Media**, after changing the paper | **media reverted to the PPD default**, and the per-paper profile key followed it. **The colour keys were preserved.** |

**Two findings, and both are methodological as much as they are about this driver.**

1. **The dialog's state and the submitted ticket can disagree in EITHER direction.** Here the
   dialog showed *unlocked, Perceptual* while the job carried *locked, no correction* — the
   mirror image of the more familiar failure where a greyed control lies in the safe
   direction. Neither is evidence about the other. See `TRAPS.md` T12.
2. **What made the colour keys survive is that the application wrote them again at
   submission time.** A lock applied in the dialog is not durable; a re-assertion at
   submission is. Any application relying on dialog locks alone is relying on the user not
   pressing Cancel.

**The consequence that generalises past colour.** Job B carries a correct colour flag and the
wrong paper. It passes every colour check available and is still an invalid characterisation
print, because media drives ink laydown. **Verifying only the colour keys is insufficient:
media and quality must be verified on the submitted job as well** — and unlike every
vendor-gate finding in this document, that check needs no vendor knowledge at all.

**Not established here:** whether quality reverts by this route (in job B the user had left
quality at its default, so its quality keys are what he chose, not a substitution — the
quality reversion evidence is F12's jobs 5 → 6). Which *other* panes behave like Quality &
Media is untested; only two were tried, and they differed.

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


---

## F8 — A vendor's raster filter overrides "no colour correction" for certain media, for EVERY application

**Vendor:** Printer A (a current consumer photo inkjet), macOS 15.7.9, vendor CUPS driver.

Requesting the driver's own "no colour correction" value and reading the flag the filter
forwards to the printer, across all 25 media types the PPD declares:

| outcome | n | media |
|---|---|---|
| honoured | 15 | every photo, fine-art, canvas and disc medium |
| **silently overridden to the photo intent** | **6** | the plain / postcard / greeting-card / card-stock group |
| filter emits nothing and polls indefinitely | 4 | four matte and fine-art media |

Deterministic, **one-way** (asking for the photo intent yields the photo intent on every
medium — the driver only ever moves *towards* colour management), and the PPD declares **no
`UIConstraints`** announcing any of it.

**Every medium with a per-paper ICC profile in the PPD honoured the request: 13 of 13
measured, 0 overridden.** Of the 8 with no per-paper profile, 6 override; the two exceptions
are printable-disc types, which are not paper.

### It is not application-specific, and that is the important part
The same override fires for a job captured from **the operating system's own bundled PDF
viewer** — a ticket containing none of the profiling application's keys. To use a custom ICC
profile correctly the *application* manages colour and the driver must be set to "no colour
correction"; this is the identical request. So on those six media, **every colour-managed
print from every application is asking the driver to colour-manage it on top of the
application's own conversion.** Double colour management, invisible in the UI.

### A second, application-side trigger for the same flag
The same filter also keys on Apple's `AP_ColorMatchingMode`. With
`AP_ApplicationColorMatching` present, the honoured/overridden decision stops depending on
media and depends **only** on whether a per-paper profile selector is also named. One rule
covers a 108-cell cross with no exceptions, and predicted **12 of 12** real captured tickets
with the rule fixed and committed in advance:

> If `AP_ApplicationColorMatching` is set, only the per-paper profile selector decides.
> Otherwise only the media decides.


The consequence for any application that sets that Apple key "to disable colour management":
if it does not *also* name a per-paper profile selector, it earns the colour-managed flag on
every medium — worse than sending nothing at all.

> #### ⚠ And there are two ways to set that key, only one of which sets it
> Added 2026-08-24, measured in four cells with a driver option landing in every cell as the
> positive control (see `TRAPS.md` **T16**). Writing the Apple key into the print job's
> **settings dictionary** — the same place every driver option goes, and where every driver
> option arrives correctly — is **not** the same as setting it on the **print settings**:
>
> ```
> wrote nothing                  <Apple key, underscore spelling> = <platform's own value>
> wrote the settings dictionary  <Apple key, DOT spelling>        = <our value>
>                                <Apple key, underscore spelling> = <platform's own value>
> wrote the print settings       <Apple key, underscore spelling> = <our value>   (one key)
> ```
>
> The dictionary write is accepted, reported no error, and stored — and the job then carries
> **two contradictory answers to the question of whether it is colour-managed**. An
> application that sets the key this way has not disabled colour management; it has added a
> second opinion next to the platform's own. Set it on the print settings, and then read it
> back **off the submitted job** rather than out of the object you wrote to. The selector is never transmitted to the
printer (identical payload; the stream's header differs only in its clock), so it is a
host-side conditional, not a claim made to the hardware.

**Boundary.** All of the above is the flag on the wire. The filter's raster payload is
byte-identical either way, so what the printer *does* with the flag is not observable from the
computer. Only a printed, measured sheet closes that step.

## F16 — A cancelled driver pane strips **every** vendor option, and the scheduler substitutes the PPD defaults

Measured through a real macOS print dialog with the vendor's own print-dialog extension
loaded, against a private scheduler whose backend writes the job to a file. No paper, no ink.

**The interaction:** open the driver's Quality & Media pane, change the paper, close **that
pane** with **Cancel**, then print.

**The submitted ticket:**

```
<vendor>Intent2 = <absent>    <vendor>ProfileID = <absent>    <vendor>MediaType = <absent>
job-hold-until  = no-hold  (the attribute set before the dialog was also gone)
```

**And absent is not neutral.** An option the ticket does not carry takes the PPD's `*Default…`
value. Note the layer: the option string handed to the driver shows these keys **absent**
rather than expanded, so it is the **driver** applying its own defaults, not the scheduler
substituting them into the ticket. Proven for the media by identity — the vendor stream from a
stripped ticket is byte-identical to one naming media `51` explicitly, and differs from one
naming `42`, which is the control showing the field moves at all. On this PPD:

| option | PPD default | effect |
|---|---|---|
| `*Default…Intent2` | `5` — perceptual | **colour management ON**, against an explicit request for none |
| `*Default…ProfileID` | `1` — the generic profile | colour-managed on **every** medium (F13's rule) |
| `*Default…MediaType` | `51` — a glossy photo stock | **the wrong paper**, i.e. the wrong ink laydown |

**The failure does not degrade gracefully, and it arrives by either of two routes** depending
on the platform colour-matching key. Seven cells, each with a discriminating control that
restores the suspected lever alone:

| stripped ticket carries | emitted | restore intent alone | restore profile alone | route |
|---|---|---|---|---|
| `AP_ApplicationColorMatching` | colour-managed | still colour-managed | **honoured** | the **profile** defaults to the generic value (F13, F17) |
| `AP_VendorColorMatching` | colour-managed | **honoured** | — | the **intent** defaults to perceptual |
| no such key | colour-managed | **honoured** | — | the **intent** defaults to perceptual |

**There is no state in which a stripped ticket comes out honoured.** That disjunction is the
finding — not one unlucky combination, but the absence of a survivable one.

**The control, and it is what makes this a finding rather than an anecdote.** The same
interaction was captured from a real application that re-writes its settings immediately
before submitting. One variable:

| | intent | media | what reaches the printer |
|---|---|---|---|
| application that **re-asserts** at submission | correct (`1001`) | present | **not** colour-managed |
| test script that **does not** | `<absent>` | `<absent>` | **colour-managed, wrong paper** |

**Consequence for any application that sets driver options.** Options set *before* the print
dialog cannot be relied upon to reach the job — a single cancelled pane discards them, with
nothing on screen to say so and no error anywhere. The only reliable pattern is:

1. write the options **after** the dialog returns, not before it opens;
2. **read the submitted job back** and verify them there (`Get-Job-Attributes`), never out of
   the settings object you wrote into;
3. treat the code that re-writes them as load-bearing, and pin it with a test built from an
   **emptied** settings object — a happy-path test passes with that code deleted.

**Limits.** One vendor's print-dialog extension, one OS version. Whether another vendor's PDE
rebuilds the settings dictionary the same way on Cancel is **UNPROVEN**. The consequence does
not depend on the answer, because verifying the submitted job covers all of them; but do not
write that any particular vendor is safe. See `TRAPS.md` T14.

## F17 — A driver's own default option value can be the one that defeats its own "no colour management" setting

Stated separately from F16 because it is a property of the **shipped printer description**,
independent of any application's behaviour, and it is what makes F16's failure silent.

The PPD ships:

```
*Default<vendor>MediaType: 51     a glossy photo stock
*Default<vendor>ProfileID: 1      the GENERIC profile
```

Two observations, and the second is the serious one.

1. **The two defaults do not agree with each other.** Media 51 pairs with profile `3`
   (`..._G1_<that paper>.icc`), not `1`. The PPD's resting state is internally inconsistent.
2. **The chosen default is the single worst value in the table.** Measured over a 108-cell
   cross (F13): with the Apple key `AP_ApplicationColorMatching` present — the state any
   application using the platform's colour-matching convention puts a job in —
   `ProfileID = 1` causes the driver to **colour-manage on every medium**, while any
   per-paper value (`≥ 2`) causes it to **honour** an explicit "no colour correction".

**So the driver ships with the one default that defeats its own no-colour setting**, and it
applies to every job that does not explicitly name a profile. The vendor's own print-dialog
extension computes a consistent pairing and never lands there. Every other route does:
command-line submission, any application that sets the no-colour option and reasonably assumes
that is sufficient, and any job whose options were discarded by a cancelled pane (F16).

**Why this is worth recording as a general finding.** The usual mental model is that a
default is a safe or neutral choice and that an explicitly-set option overrides it. Here the
default is neither safe nor neutral, and the explicitly-set no-colour option does **not**
override it — a second, undocumented option decides, and its default is the harmful one.

**Guard, for anyone auditing a driver they did not write.** Do not treat `*Default…` values as
a benign baseline. Enumerate them, and for every option your measurements show to be
decisive, check **what the default is** and whether it sits on the safe side. A driver whose
default lands on the harmful branch turns "the user did not configure this" into "the user
configured it wrongly", silently, for every application.

**Limits.** One vendor, one model family, one driver build. Whether other vendors' defaults
sit on the safe side of their own decisive options is **UNPROVEN** and is exactly the kind of
thing that must be measured per driver rather than assumed.

---

## F18 — The precondition for opening a vendor's driver at all

Anyone repeating this work meets this before they meet any question about colour, so it is
recorded here rather than left to be rediscovered.

**To measure what a printer driver does with a colour request you must run that vendor's own
filter. The precondition for that is not "can the driver package be downloaded" — it is
"is the driver installed on this machine, or is its filter self-contained".**

Two vendors' filters were opened in this investigation. Both were opened because **the
machine's owner owns those printers and their drivers were already installed**. Those filters
reach sibling components and resources by absolute path, and those paths resolve for that
reason — not because those vendors are architecturally more open than any other.

A third vendor was probed from an extracted package. Every step people assume is the hard part
worked:

```
the vendor's driver packages are still served, and expand without installing anything
the filter binary extracts cleanly
it is x86_64, from 2017; on an arm64 host with Rosetta 2 present, it executes
its five framework dependencies were found across other packages of the same driver
    family, staged in a scratch directory, and every demanded version matched
the binary loads with no dynamic-linker errors, and runs
under a private print scheduler with the vendor's own PPD it executes and speaks the
    scheduler's protocol -- it is genuinely that vendor's filter running
```

It then failed for a reason that has nothing to do with colour and nothing to do with any of
the above:

```
STATE: + cups-missing-filter-error       exit 1, no output
```

> ⚠ **CORRECTED TWICE, AND THE MECHANISM IS STILL NOT ESTABLISHED.** This paragraph first
> said the filter *"spawns a sibling by hard-coded absolute path"*, naming a helper found with
> `strings`. **That was an inference from a string, not an observation of a call.** Interposing
> the spawn/exec and file-opening families and logging every path — before redirecting anything
> — showed that helper is **never requested** in the log. A second version then named the
> filter's check for its own installed location as the cause. **That is not established
> either**: redirecting those checks to the extracted tree made them succeed, and the filter
> failed at exactly the same point, with the same message, as it had with no redirect at all.
>
> **And the instrument is not proven complete**, which is the part that matters most. The
> binary's imported symbols include `lstat$INODE64` and `NSTask`, while the interposer targets
> plain `lstat` and the C-level spawn family. **So "the log does not contain path X" does not
> establish "path X is never requested."** Both stated mechanisms are withdrawn; only the
> observations below are claimed.

**What IS observed, and is enough for the practical conclusion:**

```
the filter reads its own bundle, the PPD and its whole XML data tree from an extracted
    directory successfully -- none of that requires installation
it then emits, and stops:      STATE: + cups-missing-filter-error      exit 1, no output
identical standalone and under a real scheduler  -> its own decision, not a missing environment
redirecting every /Library/Printers/<vendor>/... path it checks, with a receipt proving each
    redirect fired, did NOT advance it past that point
```

**The practical conclusion is unchanged and does not depend on knowing the mechanism: the
filter will not do useful work from an extracted package, and the remedy available is to
install the driver.** Why it refuses is, at the time of writing, **unproven** — and a stated
mechanism that has already been wrong twice is worth less than the observation.

**Consequences for anyone planning this work:**

* neither budget nor package availability is the limiting factor;
* **a survey across many vendors needs either a machine where those drivers may be installed,
  or a filter that happens to be self-contained** — and self-containment cannot be assumed of
  any vendor;
* what stays reachable *without* installing anything is the **host layer** — what the
  operating system's own rasteriser does with a given PPD. That needs the PPD alone, and it
  was measured that way for 80 models of one vendor. It answers a different question, and must
  never be reported as though the vendor's filter had been opened.

**A naming note that explains a whole class of results cheaply.** In at least one vendor's
packages, driver families are named for the **imaging model** they use — a PostScript family
and a raster family sitting side by side under near-identical names (`…P1` vs `…R1`). Rows
that "could not be run" through a host rasteriser were overwhelmingly the PostScript ones,
which never reach that rasteriser at all. Check which family a package contains before
downloading the large one: in this case the colour raster family was **9.6 MB** against
**166 MB** for the obvious choice.

---

## F19 — How many devices were actually measured, and the selection error that inflated it

**Corrected 2026-08-25, after the machine's owner asked the right question:** if the unit of
proof is the *model* rather than the vendor, is the work on the first two vendors even
finished? It is not, and the reason is a selection error worth publishing on its own.

### The disqualifier that settles it

Two models are **one measurement repeated** — whatever their names, and whatever their
description files say — if they emit **byte-identical output once the stream's known per-job
nonces are masked**, or output differing only by a model identifier. That test is cheap and it
is the last word. It was not being run.

**The masking clause is load-bearing and was added on 2026-08-25, after it caused a false
alarm** (TRAPS T20). Three of the four vendors here emit a clock, a job id or both; on such a
stream nothing is ever byte-identical and the raw test always says "different". Two of the four
rounds compared a **masked payload**, two compared a **whole file**, and both were right for
their vendor — but nothing recorded which, so the moment one was read as the other the two
controls contradicted. **State the quantity and the masking, per vendor, beside the verdict:**

```
vendor   per-job nonce in the raw stream                what the verdict compared
  A      YES - job GUID + a datetime field, 32 bytes    the normalised stream
  B      YES - a clock field and a job id, header only  the parsed payload block
  C      NO  - none in 81 captures, 8 runs, 2 sessions   the whole file (stricter, and valid)
  D      two models NO; the third YES, 176 bytes        parsed command fields; the third
                                                        model was refused as undecodable
```

**And the conclusion the test licenses is narrower than "one device."** It says the *host-side
rendering* is one and the same. Whether the products are one device depends on whether the
stream carries anything that could distinguish them — vendor B's does (a per-model constant
byte), **vendor C's does not**: its streams contain no model string of any kind, and its three
description files declare the same filter, the same imageable area and the same option counts.
For the purpose of counting *measurements* the distinction does not matter — identical bytes
are one datum however they arose. For the purpose of counting *devices* it decides the claim.

### What it showed, applied to every round

```
vendor    models named   genuinely distinct   verdicts found
   A            1                 1                  1
   B            4                 1                  1     <- payloads differ by ONE byte,
   C            3                 1                  1        at one offset: a model id
   D            3                 3                  3     <- 75,365 of 75,366 identical
```

* **Vendor B's four** — two of them regional badges of the other two — differ by a single byte
  at a single offset. One device, four names.
* **Vendor C's three** — same driver family, same generation, same product line — are
  **byte-identical**, and that stream carries no nonce, so the raw comparison is the right one
  here. Three names, **one rendering**; and because the stream carries no model identifier at
  all, that is as far as the evidence reaches — it does not establish one *chassis*.
* **Vendor D's three** — different renderer families in the vendor's own data, different output
  languages, different generations — are genuinely three devices.

### The pattern, which is the finding

**Every set that was chosen for convenience "agreed". The one set chosen to be genuinely
different disagreed — completely: the colour request was carried on one model, silently
discarded on the second, and undecodable on the third.**

So *"the models of a driver family behave alike"* is at present supported by **no evidence at
all**: every apparent instance of it was one device measured repeatedly, and the only genuine
test of it failed. **Six genuinely distinct devices** have been measured across four vendors —
1, 1, 1 and 3.

### Guards for anyone doing this work

1. **Publish the difference criterion before selecting the models**, not after seeing the
   result. Renderer/engine name from the vendor's own data is the strongest signal; a different
   filter binary, technology or product line next; differing declared option sets last.
2. **Run the byte-identity check before writing the verdict.** It costs one comparison and it
   is the only test that cannot be argued with.
3. **Report genuinely distinct devices, never model names.** A vendor with four badges on one
   chassis is a sample of one.
4. **Treat "they agree" as the extraordinary claim.** On the only honest test so far, a single
   driver family disagreed with itself three ways.
