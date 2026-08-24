# Method — finding out what an OS does to a print job's colour

Measured on **macOS 15.7.9 (24G830), CUPS 2.3.4, Apple Silicon**. Where a technique is
portable it says so. Read `TRAPS.md` first.

## Rule zero: no null result without a positive control

Most of what you want to know is a negative — "this option does *not* change the output",
"the colour is *not* altered here". A negative is only meaningful if you have proven your
instrument can detect a positive. Every method below states its control. Skipping it is how
you ship a fabricated root cause; see `TRAPS.md` T1 and T3.

Two controls are usually needed and they are different:

* **Mutation control** — prove the thing you edited is the thing being read.
  (Change a `*Default...` line in your PPD copy; confirm the output header changes.)
* **Sensitivity control** — prove the instrument can see the *kind* of change you are
  hunting. (Retag the source colour space; confirm decoded pixels move.)

## The layers, and what each can hide

```
   your application
        |  (1) what it spools           <- ippcapture.py
   OS print system  (PrintCore / cupsd)
        |  (2) host rasteriser          <- cgpdftoraster_harness.py + rasterdecode.py
   CUPS raster
        |  (3) vendor filter            <- cupsdsandbox + canon_stream.py
   vendor command stream
        |  (4) firmware                 <- only a printed, measured sheet
   paper
```

You can instrument 1–3 with no ink. **Layer 4 is not observable from the computer at all.**

---

## M1 — What does the application actually spool? (portable)

`tools/ippcapture.py` is a minimal IPP/1.1 server that impersonates a print queue and
writes every job's **full ticket** and **document bytes** to disk. It has no backend, so
nothing can reach a printer.

```bash
python3 tools/ippcapture.py &                 # listens on 127.0.0.1:16631
CUPS_SERVER=localhost:16631 lp -d <queue> file.pdf
```

**macOS note, measured:** `~/.cups/client.conf` with `ServerName` is **ignored** — the
client library still used the system scheduler. `CUPS_SERVER` **works**, for both the CUPS
client tools *and* PrintCore, so GUI applications launched with it enumerate and spool into
your capture server:

```bash
open -a "Some App" --env CUPS_SERVER=localhost:16631
```

`CUPS_SERVER` is also strictly safer than `client.conf`: it is process-scoped, so the
user's ambient printing is never redirected.

**Proves:** the exact bytes and job attributes an application submits.
**Cannot prove:** anything about what happens after submission.
**Control:** submit a file with a known unique byte pattern and confirm it round-trips.

Optionally serve the real vendor PPD (`IPP_PPD=`) so the client loads the vendor's print
dialog plug-in; the tool answers `CUPS-Get-PPD` and `GET /printers/<q>.ppd`.

---

## M2 — What does the host rasteriser do? (macOS-specific)

Run Apple's real filter offline against a real PPD, then decode the raster and compare
pixel values:

```bash
PPD=/etc/cups/ppd/<queue>.ppd \
  /usr/libexec/cups/filter/cgpdftoraster 1 user title 1 "<options>" < in.pdf > out.raster
python3 tools/rasterdecode.py out.raster
```

The equivalent for image input is `cgimagetopdf` (image → PDF) followed by
`cgpdftoraster`. This is how you find out whether a path tags your data.

**Proves:** exactly which pixel values reach the CUPS raster, for a given option set.
**Cannot prove:** what the vendor filter below it does.
**Controls:** both of them (mutation + sensitivity), as above.

Two results worth knowing before you start (see `FINDINGS-macos.md`): untagged
`/DeviceRGB` passes through **bit-exact at 16 bits**, and `cgimagetopdf` **tags** whatever
you give it as sRGB with `/Intent /Perceptual`.

---

## M3 — Run the vendor filter under a scheduler you control (macOS/Linux)

Vendor filters usually cannot be invoked by hand: they want a real CUPS environment and
will crash or block without it. The system `cupsd` is root-only
(`-r-x------ root:wheel`), so you cannot use it — **build your own**.

`tools/cupsdsandbox/` has the full recipe. The short version:

1. Build CUPS from source with `--prefix=$HOME/<sandbox>` (do not `make install` the
   launchd step; it targets a read-only system path and fails harmlessly).
2. Point `ServerBin` at your prefix, symlink the OS filters in, copy the OS mime files,
   set `FileDevice Yes`, listen on a high port.
3. Add a queue with the real vendor PPD.
4. Replace the **backend** with a capture program so the vendor stream lands in a file
   instead of a printer.

Three obstacles you will hit, all solved in the recipe:

* **`cups-exec` exits 101.** That is `errno + 100` = `EPERM` from `setuid`/`setgid`: a
  non-root scheduler cannot drop privileges. Replace `libexec/cups/daemon/cups-exec` with
  a shim that skips the sandbox profile and the uid/gid change (`cupsexec.c`). Note the
  argument layout is `cups-exec [-g GID] [-n NICE] [-u UID] /profile /program argv0 …` —
  the profile comes *after* the options, so scan for the first existing executable path.
* **Backends are sandboxed.** Write your captures to `$TMPDIR`, which the profile allows.
* **The vendor filter may need a plausible `DEVICE_URI`.** With none it may crash; with an
  unreachable one it may report a communication error and poll for ever. Because the
  scheduler is yours, you can give the queue the vendor's expected URI scheme and still
  replace that scheme's backend with your capture program.

**Proves:** whether a job option changes the vendor filter's output at all, and which
options are inert. This is the only ink-free way into that layer.
**Third control, and the one most easily skipped: prove each option ARRIVED.** Vendor streams
usually echo the job settings in a header. Parse it and assert per run that the value you set
is the value the driver received. Without that, "the option changed nothing" is
indistinguishable from "the option never landed" — and the second is far more common. See
`TRAPS.md` T9. This check is also how a *silent override* is discovered: a driver that
accepts your setting and records a different one.
**Cannot prove:** what the change *means* — the stream is proprietary.
**Two controls, and the second is the one people skip:**

1. Run the same configuration ≥ 2× and normalise until repeats are byte-identical
   (`vendorstream.py`). Nonces are common; see `TRAPS.md` T5.
2. **Parse the stream; never diff it positionally.** These containers put option values in a
   text header, and a value one byte longer than another shifts everything after it — a
   naive comparison then reports ~100 % difference from a flag change that altered no image
   data at all. `pcl3parse.py` extracts the raster transfers so payloads can be compared
   element-for-element. This trap produced, and briefly published, a completely wrong
   conclusion here; see `TRAPS.md` T8.

Expect the possibility that the answer is **"the filter changes nothing"** — some drivers
forward the colour decision to the printer as a flag and emit identical data either way. If
so, that is a strong result: it means host-side verification is impossible *in principle*
for that driver, and only a measured print can settle anything.

---

## M4 — What levers does the driver even offer? (portable)

```bash
python3 tools/ppdprobe.py /etc/cups/ppd/*.ppd
python3 tools/ppdprobe.py --csv corpus/*.ppd > matrix.csv
```

Beyond the usual "is there a no-colour-management option", it reports the **ICC qualifier
chain** and whether the PPD provides an **identity escape** — a `None`/`0` value on the
qualifier option whose `*cupsICCProfile` is a plain working space rather than a paper
profile. That distinction differs sharply between vendors and is worth surveying across a
corpus.

**Proves:** what the driver offers. **Cannot prove:** that any of it is honoured.

---

## M4b — Read the job, not the dialog (portable, no ink)

Pause the queue. Jobs then wait instead of printing, and every one of them can be read in
full with `getJobAttributes`. This keeps **everything** real — the real queue, the real
driver, the real dialog and plug-in, the user's own hands — and costs nothing.

```bash
python3 tools/ticketwatch.py --list                  # confirm the queue is paused
python3 tools/ticketwatch.py -q <queue>              # watch, label each job as it lands
python3 tools/ticketwatch.py -q <queue> --jobs 341=baseline,342=after-switch
```

The tool refuses to run against a queue that is not paused, summarises **foreign-vendor key
contamination** separately from ordinary differences, and prints one row per setting that
changed between jobs.

Two things this method has already shown that no amount of code reading would:

* **The dialog can display a different value from the one the job carries** — in both
  directions. Diagnose from the job, never from the pane.
* **A print-settings object is not necessarily per-printer.** Vendor keys can survive a
  printer switch and ride out on a job for a different make, including keys that declare the
  data's source colour space. Check every job for keys belonging to a vendor that is not the
  target printer's.

## M5 — The part you cannot do on the computer

Nothing above reaches the firmware, and no analysis of a closed filter proves what its
output means on paper. To settle direction you must print and measure.

The cheap decisive form: print the **same** small target once per candidate configuration
(the configuration is a property of the job, so they cannot share a sheet), measure, and
compare. Colour management can only **equal or reduce** chroma, so the configuration with
the highest chroma on the solid primaries is the least-managed one. This is a *comparison*,
so it needs no absolute threshold and cannot false-positive on a legitimately small-gamut
paper — every candidate is printed on that same paper.

If two configurations measure identical, the lever between them is inert. That is a fact
you cannot obtain any other way.

## Cost and blind spots

| method | ink | needs root | portable | blind to |
|---|---|---|---|---|
| M1 capture | none | no | yes | everything after submission |
| M2 host raster | none | no | macOS | vendor filter, firmware |
| M3 scheduler sandbox | none | no (build your own) | macOS/Linux | meaning of the stream, firmware |
| M4 PPD probe | none | no | yes | whether anything is honoured |
| M5 measure | a few ml | no | yes | nothing — but needs an instrument |

## Other platforms

**Windows** shares none of this chain: no CUPS, no PPD filters. The equivalent questions
are asked of the printer driver's DEVMODE and the GDI/XPS print path, and the OS-side
colour decision lives in WCS/ICM. **Linux/CUPS** shares PPD levers, `ippcapture.py`,
`ppdprobe.py`, `rasterdecode.py` and the scheduler sandbox, but not Apple's
`cgpdftoraster`/`cgimagetopdf` — there the host rasteriser is typically Ghostscript or
`pdftoraster`, and the same M2 technique applies with those binaries substituted.

## Before every push: the scrub scan

```sh
python3 tools/scrub_scan.py --self-test     # prove the patterns still reject their bait
python3 tools/scrub_scan.py .               # scan the tree
```

The scan must report **0 findings** and the name check must report **loaded**, not `NOT RUN`.
Those are two different results and they must never be read as the same one: a scanner that
was given no names cannot have found one.

**What it looks for, and why each entry is there** — this list is a record of things that
leaked or nearly leaked, not a guess:

| pattern | why |
|---|---|
| device URIs containing a hardware identifier | a queue's `device-uri` names the physical device (`?uuid=…`, or a `.local.` name derived from it). It appears in ordinary `lpstat -v` output, so it arrives in a paste without anyone choosing to include it. Publish the **scheme only** |
| bare UUIDs | printer and device identifiers |
| email addresses | the project's `…@users.noreply.github.com` address is the only permitted one, and it is the only one exempted |
| home directory paths | `/Users/<name>/…` names the account holder |
| mDNS hostnames | derived from the machine or the device |
| serial-number fields | device serials |
| names of people, customers, accounts, private products | loaded from a list held **outside every repository** (`~/.print-colour-forensics-names`) — a scanner that carries the words it hunts for publishes them itself, which the first version of this script duly did |

`--self-test` builds bait for each pattern **from string fragments** so the literals never
appear in the file, then asserts each one is rejected and that the permitted noreply address
is not. A guard nobody has watched reject anything is not a guard.
