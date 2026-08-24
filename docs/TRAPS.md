# Traps — experiments that gave convincing, wrong answers

Every item here produced a confident result that survived scrutiny until a control
killed it. Two of them were, briefly, a *root cause*. They are documented because a
method write-up that lists only successes teaches nobody how to avoid the failures.

---

## T1. The byte-order trap — a decoder bug that looks exactly like colour management

**Symptom.** Decoding 16-bit CUPS raster produced "325 foreign colours" and "93 % of
patch-core pixels differ from the source", with the deltas clustered tightly at ±255.
That is a textbook colour-management fingerprint.

**Cause.** In a CUPS raster stream the **header** is big-endian on this platform, but the
**pixel samples are host order (little-endian)**. Decoding samples as big-endian
byte-swaps every 16-bit value.

**How it was killed.** Arithmetic, not more measurement. Byte-swapping the source values
reproduces *every* observed output value exactly:

```
(32895, 32896, 32640) -> swap -> (32640, 32896, 32895)   == observed
(1000,  2000,  3000)  -> swap -> (59395, 53255, 47115)   == observed
(12345, 23456, 34567) -> swap -> (14640, 41051,  1927)   == observed
```

**Why it hid.** On charts derived from 8-bit data it is invisible: every `k × 257` value
(`0x8080`, `0xE6E6`, …) is a byte palindrome and survives the swap unchanged. It only
appears with genuine 16-bit data.

**Guard.** `rasterdecode.py` documents this at the top and exposes both orders. Before
trusting any 16-bit comparison, round-trip a value you control — e.g. put `1000` in the
source and confirm you read `1000`, not `59395`.

---

## T2. The blank-page trap — an invalid file that reads as a dramatic transform

**Symptom.** A tagged-colour-space variant of a generated PDF rasterised to an image whose
every patch had changed to pure white. Spectacular apparent colour management.

**Cause.** The variant was produced by patching bytes into an existing PDF, which broke the
cross-reference table. The rasteriser logged
`CoreGraphics PDF has logged an error` on **stderr** and emitted an empty page. The raster
file was full-length and well-formed, so nothing downstream looked wrong.

**Guard.** Never trust an output whose input you have not validated. Check the filter's
stderr for errors, and render the input independently (e.g. `sips -s format png`) to
confirm it is not blank, *before* measuring. Rebuild variants from scratch rather than
patching binary containers.

---

## T3. The uncontrolled null — five option sets, identical output, wrong conclusion

**Symptom.** Five different job-option sets through a host rasteriser produced
byte-identical output. Conclusion drawn: "these options do nothing here."

**Why it was not yet safe.** Identical output is equally consistent with *the options never
being parsed at all*. The experiment had no control proving the harness could detect any
option-driven change.

**How it was fixed.** Two controls, both of which had to land before the null was accepted:

1. **Mutation control** — copy the PPD, change `*DefaultResolution: 600x600dpi` to
   `300x300dpi`, confirm the raster header changes from 600 to 300. Proves the modified
   file is the one being read.
2. **Sensitivity control** — vary only the *source* colour space of the test file
   (untagged / sRGB / AdobeRGB) and confirm the decoded pixels change. Proves the
   instrument can see a colour transform at all.

Only then does "nothing changed" mean something.

---

## T4. The tautological verification — proving storage, not delivery

A print path "verified" that colour management was off by writing keys into a settings
object and then **reading them back out of the same object**. It always passed. It proved
the value was stored; it said nothing about whether the key reached the job.

**Guard.** Verify at the boundary you care about. Capture the actual submitted job
(`ippcapture.py`) and look for the key on the wire.

---

## T5. Nonces — two runs of the same job are not byte-identical

A vendor's print stream contained a job GUID and a `<datetime>` field. Naive `md5`
comparison of two runs of the *same* configuration showed them as different, which would
have made every comparison meaningless — or, worse, manufactured differences between
configurations that were actually identical.

In one matrix this mattered directly: two configurations appeared to "differ by 2 bytes",
which looked like a small but real effect. Both bytes were the **clock**. The true
difference was zero.

**Guard.** Always run the same configuration at least twice and normalise until the
repeats are byte-identical (`canon_stream.py`). Only then compare configurations.

---

## T6. Reasoning from a stimulus that cannot show the fault

A hardware test using a **neutral wedge** was recorded as proving that a print path was
not colour-managed. But the signature of the fault being hunted is *"chromatic primaries
roll off at the solid while the neutral axis stays clean"*. A neutral wedge is precisely
the stimulus a perceptual gamut mapping barely moves. The test was blind to the fault by
construction, and its clean result was taken as evidence for two years.

**Guard.** Before running a test, state what the fault would look like in *that* stimulus.
If the answer is "not much", change the stimulus.

---

## T7. Assuming a queue is what its name suggests

A queue whose device URI was `ipps://…/ipp/print` was assumed to be a driverless
IPP-Everywhere queue. Its `printer-make-and-model` was **`Local Raw Printer`** — a raw
pass-through queue, which behaves completely differently (it accepts any format verbatim,
including PostScript that PPD queues reject).

**Guard.** Classify queues from `printer-make-and-model` and the presence of a PPD, not
from the device URI. `ladder.py` does this.

---

## T8. The one-byte shift — a positional diff that reports ~100 % difference from a flag change

**Symptom.** Switching a driver's colour option between its two values changed **72 913 of
82 423 bytes** of the vendor's print stream. Conclusion drawn, and briefly published: the
lever demonstrably drives the vendor's colour engine.

**Cause.** The option is recorded in an XML preamble as a *word*:

```
A: <ivec:printcolormode_intent>pro</ivec:printcolormode_intent>
B: <ivec:printcolormode_intent>none</ivec:printcolormode_intent>
```

`none` is one byte longer than `pro`. Every byte after the preamble is therefore shifted by
one, and a naive `a[i] != b[i]` comparison reports almost the entire file as different. The
actual image data was **byte-identical**.

**How it was killed.** By parsing the container instead of diffing it. Extracting the raster
transfers (`ESC * b <n> V/W`) and comparing the payloads directly:

```
plane payload count : 11127 vs 11127
plane payloads that DIFFER: 0 of 11127  (0.0%)
```

**Guard.** *Never* compare structured streams positionally. Parse them and compare
element-for-element, or at minimum align on structure before diffing. A length-changing
field anywhere near the start will otherwise manufacture a total mismatch out of nothing.

This trap is the mirror image of T5: there, a nonce made identical things look different by
2 bytes; here, a 1-byte flag made identical things look different by 72 913. Both were
caught only by parsing rather than hashing.


---

## T9. The uncontrolled null — options that never reached the driver

**Symptom.** A sweep varied the per-paper ICC selector, the media type and the print quality
and reported that none of them changed the vendor's output. Conclusion drawn, and published:
those settings are inert, so a stale value cannot be the cause of a miscoloured print.

**Cause.** The options never arrived. The stream's own XML preamble records what the driver
received, and it showed the quality field sitting at its default in every run and the paper
recorded as a generic "custom" type in every run — including the runs that were supposed to
select four different papers. Only one option in the whole sweep could be *shown* to have
landed.

**Why it is dangerous.** "I changed X and nothing happened" and "X never arrived" produce
identical evidence. A null result about a lever is worthless unless you can point to
something in the output that proves the lever moved.

**How it was killed.** By finding a field in the output that echoes the input, and checking
it every run. When the sweep was repeated with that check, the picture inverted: media *did*
reach the driver (it changed other recorded fields), and one media value made the driver
**silently override** the requested colour setting — the opposite of "inert".

**Guard.** Before believing any null, identify a per-run receipt for the mutation and assert
on it. Most vendor streams echo the job settings somewhere — find that, and make it part of
the harness rather than something you check once.
