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

> ### ⚠ THIS ENTRY WAS ITSELF WRONG, AND ITS GUARD CAUSED A SECOND FAILURE — SEE T13
> The original text is kept below, struck through in effect, because the *shape* of the
> mistake is right and the *conclusion* was not. Following its guard produced T13.

**As originally written (WITHDRAWN):** *"A queue whose device URI was `ipps://…/ipp/print`
was assumed to be a driverless IPP-Everywhere queue. Its `printer-make-and-model` was
`Local Raw Printer` — a raw pass-through queue, which behaves completely differently.
**Guard:** classify queues from `printer-make-and-model` and the presence of a PPD, not from
the device URI."*

**What was actually true.** That queue *was* driverless. `Local Raw Printer` is the string
CUPS writes when a queue has **no PPD**, which is equally true of a driverless queue — a
placeholder, not a model and not a queue type. The original reading was correct and the
"correction" inverted it. The guard then told a later reader to classify on the very field
that had caused the error, and a diagnostic shipped doing exactly that (T13).

**The surviving lesson, which is real:** a queue is not what any single field suggests. The
device URI alone is insufficient — on the machine where this happened, both **classic-driver**
queues are reached over `dnssd://`. The model string alone is worse, because it can be a
placeholder. **Corrected guard, and the order matters:**

```
PPD present?                      -> classic driver queue   (the URI scheme is irrelevant here)
else scheme ipp/ipps/dnssd/mdns   -> driverless / IPP Everywhere
else scheme socket/lpd/usb/...    -> raw pass-through
```

Never classify on a placeholder. `ladder.py` implemented the withdrawn guard and is corrected.

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


---

## T10. One at a time — a clean, deterministic, repeated single-key result that was wrong

**Symptom.** A bisect over 48 job options found exactly one key that flipped a driver's
colour flag from "honoured" to "colour-managed" on a photo paper. It survived every
control that had killed earlier claims: deterministic 3/3 in each cell, the opposite value
of the same key gave the opposite result, the host rasteriser's output was md5-identical
with and without it, and the effect reproduced with the vendor filter run directly with no
scheduler at all. By every rule in `METHOD.md` it was a finding.

**It was contradicted by the user's own captured job**, which carried that key with that
value on that same class of paper and came out honoured.

**Cause.** The key is one half of a pair. Its effect depends on whether a per-paper ICC
selector is also named in the same job. The bisect's baseline had that selector absent;
the real job had it set. A one-at-a-time search cannot see that, and every control listed
above is equally blind to it — they all vary one factor while the others sit at whatever
the baseline happened to be.

**How it was resolved.** By crossing: 3 media × 3 values of the colour key × 4 values of
the profile selector × 3 values of a fourth suspect = **108 cells**, each with its
mutation-landing receipt asserted. `CNIJClearInkMode` fell out as irrelevant; one rule
then fitted all 108 cells with zero exceptions, explained both the bisect and the
contradicting real job, and predicted **13 of 13** cells on media it had never seen.

**Guard.** A single-factor result is a hypothesis, not a finding — no matter how many
times it repeats. Before publishing one, cross it with every other factor that differs
between your test and the real case that motivated the work. If you cannot afford the full
cross, at minimum run your candidate against a **real captured job** and check it predicts
that job's outcome. Here that one check was the difference between a correct root cause
and a confidently wrong one.

This is the mirror of T9: there, a null was uncontrolled because the lever never moved.
Here the lever moved, repeatably, and the *conclusion drawn from it* was still wrong
because a second lever was holding still off-screen.


---

## T11. The baseline that was already at the safe value — a null that reversed a shipped recommendation

**Symptom.** A vendor key was swept across all three of its states on a second printer and
recorded as **inert**: the driver's colour receipt byte was unchanged in every cell. The
conclusion — *"this key does nothing on this vendor, so do not send it"* — was written into
a specification and would have been shipped.

**Cause.** Every cell of that sweep also carried the vendor's own colour-off lever at its
**correct** value. With colour management already off by the vendor lever, a key whose only
effect is *"force colour management off"* has nothing left to change. The sweep could not
have detected the effect no matter how many media it covered.

The reversal was found by accident, from a *failed positive control*: replaying the user's
real job ticket, the vendor lever itself turned out to be inert — a second key, injected by
the vendor's print-dialog plug-in and absent from the PPD, disables it. Crossing the three
factors gave one rule that fits 36 of 36 cells:

```
plug-in key present  ->  vendor colour lever IGNORED; the Apple-level key decides
plug-in key absent   ->  vendor colour lever decides, unless the Apple-level key forces off
```

So the key called inert is the **only** thing that turns colour management off for every
print made through the real print dialog. The published advice — *do not send it* — would
have switched colour management **on** for exactly the jobs that matter.

**Why it is not T9 or T10, quite.** T9 is a lever that never arrived; this one arrived and
was recorded as delivered. T10 is a single-factor result that was *positive* and wrong; this
one was *negative* and wrong. The shared root is the same and worth naming separately: **a
one-factor sweep tells you nothing when the baseline sits where the effect cannot show.**

**Guard.** Before believing that a key is inert, ask *what state would this key change, and
is my baseline already in it?* Sweep the suspect key **against the other lever in both of
its states**, not against a fixed known-good one. And when a positive control fails, stop
and diagnose it — that failure is where this was found.


---

## T12. The screen and the wire disagreed — and the *safe-looking* direction was the wrong one to trust

**Symptom.** An application locks three vendor keys in the print dialog. The user changes the
paper, closes a driver pane with **Cancel**, and reopens it: every lock is gone. The controls
are editable, the paper has fallen back to the PPD default, and the rendering intent reads
*Perceptual* — colour management on, against an explicit request for none.

The obvious conclusion, and it was written down before it was tested: *one cancelled pane
silently colour-manages the print.* It explains a long-standing complaint, it matches a report
the user had filed with the vendor years earlier, and it is wrong.

**What the wire said.** The same action with a print attached, captured from a paused queue:
the submitted ticket carried the locked colour keys **intact**. The application re-asserts its
keys at submission time, after the dialog has been torn down. The dialog had been showing a
state that was never submitted.

**And the same job proved the inverse.** That ticket carried the **wrong paper** — reverted to
the PPD default, with the per-paper profile key following it — while the dialog, if reopened,
would have shown exactly that. So in one job:

| | dialog | submitted ticket |
|---|---|---|
| colour keys | unlocked, *Perceptual* | **locked, no correction** |
| paper | reverted to default | **reverted to default** |

The dialog was wrong about colour and right about paper, in the same job, at the same moment.

**Why it is dangerous.** The instinct is to trust whichever source shows the *worse* state, on
the grounds that it is the conservative reading. That instinct produced a false root cause
here. It would equally have missed the paper revert had the dialog happened to look fine — and
the paper revert is the one that actually ruins the print: the job passes every colour check
available and is still invalid, because media drives ink laydown.

**Guard.** **The screen is not the record, and neither is the settings object.** Only the
submitted job is. Read it back at the boundary (`Get-Job-Attributes` on your own job) and
check **every** field you care about — not just the one the current investigation is about.
Do not reason from a dialog to a ticket in either direction, and do not let a check that
covers only colour report a job as good.

This is T4's neighbour. T4 is *"I verified storage and called it delivery."* This is *"I
verified the user interface and called it delivery"* — and it adds the sting that the UI can
be wrong in the safe direction and the alarming direction at the same time.


---

## T13. Our own tool shipped the trap its own comment warns about — and "correcting" it made it worse

**Symptom.** A diagnostic listed a queue as *"driverless / no PPD"*. That looked wrong, so it
was fixed: read `printer-make-and-model`, and if it says `Local Raw Printer`, report a raw
pass-through queue. The queue duly came out as **RAW (pass-through)**, the change was
committed with a comment citing **T7** — *classify a queue from `printer-make-and-model`, not
from its device URI* — and it was reported as a real defect found in our own prototype.

It was a real defect. The correction was also wrong, and more confidently wrong than the bug.

**Cause.** `Local Raw Printer` is not a printer model and not a queue type. It is the string
CUPS writes when a queue **has no PPD**. A driverless IPP Everywhere queue has no PPD either,
so it carries the same placeholder. The queue in question was
`ipps://<host>.local.:631/ipp/print` — **driverless/AirPrint**, the exact category the
original wording had right.

So T7's guard was followed to the letter and produced the opposite of its intent. T7 says the
device URI is not sufficient; it does not say the model string is. **Both fields are weak on
their own, and the placeholder is weaker than the URI**, because a placeholder is a statement
about the *local configuration record* rather than about anything on the network.

**The rule that actually works** needs two fields and an order:

```
PPD present?                      -> classic driver queue   (the URI scheme is irrelevant here)
else scheme ipp/ipps/dnssd/mdns   -> driverless / IPP Everywhere
else scheme socket/lpd/usb/...    -> raw pass-through
```

The ordering is load-bearing: on the machine where this happened, **both classic-driver queues
are reached over `dnssd://`**. A scheme-first rule would have misfiled both of them, which is
how a scheme-only rule earns the reputation T7 gave it.

**And the second failure, which was the expensive one.** The device behind that queue had been
**thrown away months earlier**; only the queue record remained. Nothing had ever answered it,
so CUPS held no live capabilities for it — `urf-supported`, `print-color-mode-supported`,
`pwg-raster-document-type-supported`, `media-type-supported` and `printer-device-id` were all
empty. Every measurement taken from that queue described a stale entry in a configuration file.
One of them had already been written up as a finding about driverless printing:

> *"PostScript is accepted on the driverless queue."*

What that actually measured is that **cupsd will accept a format for a queue with nothing
attached**. It says nothing whatever about a real AirPrint printer. It was a T3 uncontrolled
null with the control missing at the far end — not "the option did not arrive", but "there was
never anything for it to arrive at".

**Guards.**

1. **Never classify anything from a placeholder.** Enumerate your platform's placeholders
   (`Local Raw Printer`, `Unknown`, empty) and treat matching them as *"this field is absent"*,
   never as a value.
2. **Classify on two fields with an explicit precedence**, and write down why the order is that
   way. A rule that depends on one field is one vendor away from being wrong.
3. **Prove the endpoint is alive before measuring it.** Pick attributes that only a *device*
   can supply and assert at least one is present. Be strict about which ones qualify: the first
   attempt here included `ipp-features-supported`, `printer-uuid` and `marker-colors`, all of
   which the scheduler generates itself on every queue — so the dead queue read as live and the
   guard silently passed. A liveness check that cannot fail is not a liveness check.
4. **When a check fails, void the results that came from it — loudly.** Do not leave a stale
   queue's numbers in the report with a footnote; a reader takes tabulated output as data.
5. **A correction deserves the scrutiny of a finding.** This one was published in the same
   breath as *"finding two real defects in our own prototype is the standard"*, which is exactly
   the mood in which a fix goes in unexamined.

The pattern with T7 is worth naming: **T7 is picking the wrong field; T13 is picking the other
wrong field while quoting T7.** A guard that names the field you must not use does not tell you
which field you may.
