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


---

## T14. A setting you did not send is not a setting you did not choose

**Symptom.** A test submitted a print job through a real print dialog after closing one of the
driver's panes with **Cancel**. The job arrived without the attribute under test, which was the
expected failure and was recorded as such. What nobody looked at was the rest of the ticket:

```
<vendor>Intent2 = <absent>    <vendor>ProfileID = <absent>    <vendor>MediaType = <absent>
```

Every vendor option had gone, not just the one being measured. The run was nearly filed as
*"the attribute did not survive"* — a true statement that would have buried the larger one.

**Why the absence is worse than a wrong value.** A scheduler does not send "nothing" for an
unset option. **CUPS fills every unset option from the PPD's `*Default…` at print time.** So a
stripped ticket is not a neutral ticket; it is a ticket carrying the manufacturer's factory
defaults, which on the driver in question were:

```
*Default<vendor>Intent2:   5    perceptual rendering  -> colour management ON
*Default<vendor>ProfileID: 1    the generic profile   -> colour-managed on EVERY medium
*Default<vendor>MediaType: 51   a glossy photo stock  -> the wrong paper
```

A cancelled pane therefore does not degrade gracefully — and the reason took a second pass to
state correctly, which is itself part of this trap.

**The first write-up gave a single mechanism:** the profile option defaults to the one value
that colour-manages on every medium. That is true only when the platform's colour-matching key
is present as its *application* value — and the ticket the claim was drawn from carried the
*vendor* value, because the test script never set the application one. The conclusion was
right; the stated route was not the route that ticket took.

**Measured properly, it is a disjunction — and that is stronger than the single cell was.**
Seven cells, each with a discriminating control that restores the suspected lever on its own:

| stripped ticket carries | emitted | restore the intent alone | restore the profile alone |
|---|---|---|---|
| colour-matching = **application** | colour-managed | still colour-managed | **honoured** |
| colour-matching = **vendor** | colour-managed | **honoured** | — |
| colour-matching **absent** | colour-managed | **honoured** | — |

Two different levers, two different routes, **and no state in which a stripped ticket comes
out honoured.** The danger is not one unlucky cell; it is that no survivable cell exists.

**And the layer was wrong too.** "The scheduler fills unset options from the PPD default" is
not what the receipt shows: the option string handed to the driver has those keys **absent**,
not expanded. It is the **driver** applying its own defaults, one layer further down. Same
outcome, different mechanism — and "same outcome" is exactly why nobody would have checked.

**The control that turned it into a finding.** The same interaction had already been captured
from a real application that re-writes its settings immediately before submitting. Like for
like, one variable:

| | intent | media | outcome |
|---|---|---|---|
| application that **re-asserts** at submission | correct | present | not colour-managed |
| test script that **does not** | absent | absent | colour-managed, wrong paper |

That pair is what identified the re-assertion as load-bearing. It had been in that
application's source for months, re-writing values that were "already set", looking exactly
like the kind of line a tidy-up deletes.

**Guards.**

1. **Read the whole ticket, not the field you are testing.** The interesting failure is often
   in the columns you did not ask about. A diff against a known-good ticket costs nothing and
   would have surfaced this immediately.
2. **Never treat an absent option as neutral.** Ask what the layer below substitutes for it.
   "Not sent" and "sent as the default" are the same thing to a printer and opposite things to
   a reader.
3. **A value set before a dialog is a request; only a value written after the dialog, and read
   back off the submitted job, is a fact.** Anything a user interface can rebuild, it will
   rebuild — and it will do so without an error.
4. **Protect the code that looks redundant.** If a line re-writes state that is already
   correct on the happy path, a happy-path test passes with it deleted. Pin it with a test
   built from the *damaged* state instead — start from an emptied settings object and assert
   the values are present at the far end. Otherwise the protection survives only as long as
   nobody tidies up.


---

## T15. The key you send is not always the key you read back — and the vendor you tested first decided whether you noticed

**Symptom.** A verification step read a driver option off a submitted job and reported it
**absent**. The option had been set, the submission succeeded, and the job printed correctly.
The verifier had been exercised against one vendor for weeks and had never once been wrong.

**Cause.** The platform's print system does not always preserve the *spelling* of a vendor
option name between the settings object and the queued job. An option sent as `VEND_Option`
can arrive on the ticket as `VEND.Option` — underscore rewritten to a dot. Which spelling you
get depends on the submission route: a job made through the real print dialog used one, a job
submitted programmatically used the other, and a third key appeared on the ticket in **both**
spellings at once.

**Why it hid for so long, and this is the part worth keeping.** The first vendor's option
names contain **no underscore at all**. There was nothing to rewrite, so every test passed,
and the assumption *"the key I sent is the key I read"* was never once challenged. The bug was
not in the code that was tested; it was in a code path that only a second vendor could reach.

**Why it was the worst possible place for it.** The verifier's job was to catch a missing
colour setting — and a missing colour setting is precisely the state that means *colour
management is on*. Reading the wrong spelling made every one of that vendor's colour keys
report as absent. **The check written to catch the fault would have reported the fault's own
signature as normal**, on every job, while looking perfectly healthy on the vendor it was
developed against.

**How it was found.** Not by review, and not by reasoning about the code. By running the
identical check against a **second vendor's queue** because someone asked whether the work
generalised. It failed on the first attempt.

**Guards.**

1. **Normalise before comparing.** When reading any option off a submitted job, accept every
   spelling the platform might use — it is three lines and it is vendor-neutral.
2. **A missing key must never be read as a benign result.** Decide explicitly what absence
   means for each option; where absence is the dangerous state (see T14), a lookup miss and a
   genuinely absent value must be distinguishable.
3. **Run your verifier against a second vendor before believing it generalises.** Not to test
   the *vendor* — to test the *verifier*. A tool exercised against one example encodes that
   example's incidental properties, and the ones it encodes are invisible precisely because
   they never vary.
4. **Prefer the property that cannot silently differ.** Where a check can be written against
   something structural rather than a name, write it that way.

This is the mirror of T13. There, a rule derived from one queue was wrong about a second. Here,
*code* derived from one vendor was wrong about a second — and in both cases the first example
was not merely unrepresentative, it was unrepresentative in a way that made the error
impossible to see from inside it.


---

## T16. Two ways to set the same key, and only one of them is the key

**Symptom.** A tool wrote the platform's colour-matching option into the print job's settings
dictionary — the obvious place, the same place every driver option goes, and the place where
every driver option had been landing correctly for weeks. The job came back carrying that
option set to **the opposite value**.

The first reading was that the platform had overridden the request. It had not. Reading the
whole ticket instead of the one key showed what had actually happened:

```
wrote nothing                 AP_ColorMatchingMode = <platform's own value>
wrote the settings dictionary AP.ColorMatchingMode = <our value>            <- respelled
                              AP_ColorMatchingMode = <platform's own value> <- still there
wrote the print settings      AP_ColorMatchingMode = <our value>            <- ONE key
wrote both                    both spellings, both our value
```

**Cause.** The platform's own options and the driver's options are not stored in the same
place, even though one API accepts both. A value put in the **dictionary** arrives on the job
under a **respelled** name, as an extra option — while the platform continues to emit its own
spelling with its own value, exactly as if nothing had been written. The API accepted the
write, reported no error, and stored it. It simply was not the same key.

**Why it is dangerous rather than untidy.** The job then carries **two contradictory answers
to the same question**, and this was the question of whether the print is colour-managed.
Anything reading one spelling reports "off"; anything reading the other reports "on"; both
are reading the real ticket, and both are confident. It is T15's two-spelling problem, except
that here **the tool itself created the second spelling** while believing it had set the first.

**How it was found, and this is the part worth keeping.** Not by review — by a verification
step that compared *everything that was asked for* against *everything the job carried*, and
refused to check only the keys the current investigation was about. The tool that had been
exercising this path for weeks excluded that key from its pass condition, so no number of
runs of it could ever have shown this.

**Guards.**

1. **After submitting, diff what you asked for against what the job carries — all of it.**
   Not the field under test. A key that "was set" and a key that "arrived" are different
   claims (T4), and a key that arrived *under a different name* is a third.
2. **A write that returns no error is not a write that took effect.** Where an API offers two
   routes to what looks like one setting, establish by measurement which one the far end
   reads, with a control that lands in every cell.
3. **Never exclude a key from a pass condition because it is "not what this run is about".**
   That exclusion is what made this invisible; the excluded key was the decisive one.


---

## T17. A parser that assumed the order of the fields, and nearly deleted the evidence

**Symptom.** A tool identified its own print job by writing a unique token into the job's name
and searching the queue for it. The parser walked the scheduler's reply, started a new record
whenever it saw a job id, and attached each following attribute to that record. It looked
right, it read cleanly, and it returned a job id every time.

**Cause.** The scheduler emits the **name before the id**:

```
job-name  = probe-ALPHA
job-id    = 989
job-state = pending-held
job-name  = probe-BETA
job-id    = 990
```

So every name was attached to the **previous** job. "The job whose name carries my token"
returned **the job submitted just before ours** — on the machine this ran on, one of nineteen
held jobs belonging to the user, holding evidence that could not be recreated. The next step
in the tool was to cancel it.

**Why nothing caught it.** The tool always returned *an* id, the id always existed, and the
job it pointed at was always real. Every check that asked "did I get a job?" passed. On a
queue where our job is the only job — which is every developer's first test — the wrong answer
and the right answer are the same number.

**How it was found.** By a control that compared the id the tool reported against the job
actually left on the queue afterwards. They differed by one.

**Guards.**

1. **Never assume the order of fields inside a record.** Group by *a key repeating*, which
   needs no assumption, rather than by *one particular key appearing*.
2. **Test the identification with more than one record present**, and with the record you
   want in a position other than last. One-record tests cannot distinguish an off-by-one from
   a correct answer.
3. **Re-verify ownership at the moment of the destructive call**, not once, earlier, on trust
   — the same discipline as verifying at the boundary (T4). A second, independent check at
   the point of damage catches this class of bug on its own.
4. **A regression guard must be shown to fail against the bug.** Keep the broken parser in
   the test as the mutation control; a guard that passes against both versions is decoration.


---

## T18. WITHDRAWN — the trap that was itself a false finding

> ### ⚠ THIS ENTRY WAS WRONG. It is kept, and kept first, because it is the only entry here
> ### that was published as a finding and then refuted, and that is worth more than the
> ### finding would have been.

**What it claimed.** That a documented rule — *"the paper types this driver overrides are the
ones the manufacturer ships no per-paper colour profile for"* — had been refuted by the
project's own measurements, on ten paper types. It named them. It was written into a tool, two
internal documents and this file, and a correction was drafted for a public issue.

**What was actually true.** The rule was right. The refutation was an artefact of the code
that read the driver description file. The manufacturer suffixes many of its colour-profile
filenames with a variant marker that the paper's own name does not carry:

```
profile filename fragment   BarytaPhotoPaper-P   ->  normalised: barytaphotopaperp
paper name                  Baryta Photo Paper   ->  normalised: barytaphotopaper
                                                                  ^ no match
```

Nine of twenty-five papers failed to match that way and were reported as having no profile.
Corrected, the counts are **17 papers with a profile and 8 without** — and the 8, minus two
documented exceptions, are exactly the 6 the rule names. The original claim was **precisely
right, including its two exceptions.**

**How the false finding was produced, and this is the part to keep.** A new feature computed a
**count** from the mapping — *"17 of 25 paper types"* — and printed it next to a measured six.
The disagreement was real and worth chasing. The error was in what happened next: the count
was treated as evidence against the standing claim, and the claim was overturned, without
re-deriving the count from the source file the mapping came from. Ten minutes of printing all
twenty-five rows and reading them would have shown the suffix immediately.

**A number that contradicts a standing claim is a reason to check BOTH, not to overturn one.**
The new number is exactly as likely to be wrong as the old one — more so, if it comes from
code written that afternoon and the claim has been stable for weeks. Rank them by how much
each has been checked, not by which is newer.

This is the mirror of T14. There, a claim was **true for the wrong reason** and the reason had
to be corrected. Here, a claim was **declared false on a wrong number** and the claim had to be
restored. Both were caught only by going back to the raw source and reading it.

**The one real defect underneath it**, which the false finding hid: the matcher failed
**silently**. Every paper it could not match simply became *"this paper has no profile"* — a
plausible answer, so nothing looked wrong, and that answer drives a substitution and an
explanation shown to a user. That has been fixed by registering both spellings, and — the part
that generalises — by adding a coverage check the caller can assert on, so a matcher that
matches nothing can no longer report a confident empty result.

**Guards.**

1. **Before overturning a checked claim, re-derive the new number from the raw source**, by
   hand, and print every row. Not a summary count — the rows.
2. **Rank evidence by how much it has been checked, not by how recent it is.** A number
   produced by new code is the least-checked thing in the comparison.
3. **A matcher must be able to say it could not match.** Expose the coverage; assert on it.
   A silent false negative that lands on a plausible value is invisible by construction.
4. **When a correction propagates into several files, check the push state before anything
   else.** Here nothing had been pushed, so it was a local revert rather than a public
   retraction — but that was luck, not process.


---

## T19. A check that ran, matched nothing, and reported the nothing as a pass

**Symptom.** Three separate instruments, in three separate rounds, returned a clean result
because they examined **nothing at all**:

* a comparison of two print streams reported them **identical** — it was looking for raster
  blocks in a container that has none, so it compared an empty list with an empty list;
* a containment check on an install package reported every file **confined to the expected
  directory** — it had globbed for the manifest at the wrong path, found no files, and every
  one of zero files was inside the directory;
* a sweep reported twelve measurement cells collected — it matched "the newest output file"
  and accepted it the moment it was non-empty, so it read every file **mid-write**. Every size
  came out an exact multiple of 64 KB.

All three exited zero. All three printed something that read like success.

**Cause.** The instrument's *domain* was empty, and every one of these checks was written as
*"is there anything wrong in what I found?"* rather than *"did I find anything?"*. An empty
domain satisfies a universal claim vacuously: **all zero files were confined; all zero blocks
were identical.**

**How each was caught.** Never by reading the code. By a control that had to produce a
non-empty result:

* the stream comparison had a control pair that *must* differ — it said "identical" too, and
  that is what exposed it;
* the containment check was caught by reading the output rather than the exit status, and
  noticing the file count was zero;
* the sweep was caught by its **landing receipt**: all twelve cells reported the option had not
  been delivered, because the truncated files did not contain it.

**Guards.**

1. **Assert the denominator.** Before interpreting any "all clear", assert that the thing
   examined more than nothing: `n > 0`, and ideally the *expected* n.
2. **Every checker needs a positive control that makes it fire.** A check that cannot be made
   to fail on demand is not a check. Keep the failing input in the test suite.
3. **"Not yet finished" and "finished and empty" are different states.** When reading a file
   another process is writing, wait on that process's completion, not on the file's size.
   Sizes that are suspiciously round are a symptom of reading mid-write.
4. **Prefer identity to recency.** Match output to the job that produced it by an id you
   control, never by "the newest file in the directory".

This is the same lesson as the completeness control — *an absence proves nothing until the
instrument is shown able to detect a presence* — arriving from the other side: **an emptiness
proves nothing until the instrument is shown able to find something.**

---

## T20. Two controls contradicted each other — because "the hash" was two different hashes

**Symptom.** A determinism control had passed twice, on two vendors, in the strongest possible
form: *"same configuration, every repeat byte-identical, no clock and no job nonce at all."* On
the strength of it, a **byte-identity disqualifier** — *two models that emit identical output
are one device measured twice* — was used to retract two published headlines. Then an agent ran
the same configuration again in a later batch and got a **different hash**, and stopped: if the
capture is not deterministic, the disqualifier is worthless and so are both retractions.

**Cause.** Both observations were right. They were **not measurements of the same thing**. The
determinism control and the disqualifier hashed the **masked payload block** — the driver's
image data, located by parsing the container. The "different hash" hashed the **whole file**,
which on that vendor begins with a 248-byte header carrying a wall-clock field and a per-job
id. Two quantities, one word: *"the hash"*.

**How it was killed.** By the repeats *inside a single batch*, which the three candidate
explanations disagree about:

```
per-job nonce           -> the hash differs on EVERY job, same batch included
batch position / state  -> the hash is constant within a batch, differs between batches
capture read mid-write  -> the size at first sight differs from the size after settling

measured: 6 identical jobs, one batch, consecutive -> 6 distinct whole-file hashes
          the same 6, and 6 more from a later batch -> ONE payload hash
          every byte that varied lay at offset 54-55 and 96-99; the payload spans 248..75613
```

The nondeterminism was **per job**, so "which batch" never entered into it. Nothing about the
render moved: every capture was the same length, and the varying bytes were a fixed-length
field written in place.

**Why it hid.** The vendor whose stream has **no** nonce was the one whose evidence was
recorded as a whole-file hash — correct there, and stricter than a payload hash. The vendor
whose stream **does** carry a nonce was the one whose evidence was recorded as a payload hash —
also correct. Each artefact was right; nothing recorded *which quantity it was*, so the moment
one was compared against the other they contradicted, and the contradiction looked like a
failure of the instrument rather than of the label.

**Guards.**

1. **Name the quantity in the artefact, not in the prose around it.** `sha256` is not a field
   name. `payload_sha256` and `whole_file_sha256` are, and an artefact that carries both can
   never be read as the other one.
2. **A byte-identity claim must state the masking it rests on** — and the disqualifier above is
   now written as *"identical **after the stream's known nonces are masked**"*. Without that
   clause it is not a test, because on a nonce-bearing stream nothing is ever identical and on a
   nonce-free stream the clause costs nothing.
3. **When two controls contradict, the first question is whether they measured the same
   quantity** — not which one is broken. Both may be sound, as here.
4. **Separate a per-item effect from a position effect with repeats inside one batch.** They
   make opposite predictions there, and it is the cheapest measurement in the set. The batch-to-
   batch comparison — the one that raised the alarm — cannot tell them apart at all.
5. **Nonce status is a property of the stream and belongs beside the verdict**, per vendor, as
   a row: *does this stream carry a per-job nonce, where, and what was masked?* It was known for
   three vendors out of four and written down for none of them.

---

## T21. The hash of nothing — a guard for the instance is not a guard for the class

**Symptom.** A retention artefact, written specifically so that published claims could be
audited after the raw captures were gone, reported a group of **14 captures with identical
payloads**. They were not identical. They were fourteen *empty* payloads compared with each
other, and their shared fingerprint was
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` — **the sha256 of the empty
string**.

**Cause.** The artefact selected its inputs on one weak signal (a byte sequence that another
vendor's streams happen to contain), swallowed 14 captures from a different vendor, and its
parser returned an empty payload for each. Nothing was empty *on disk*; the emptiness was
created by a parser running on input it could not decode. `[] == []` is True, so they grouped.

**Why it deserves its own entry.** This happened **inside the artefact written to prevent
T19**, by the same author, **one commit after writing the zero-length guard.** The guard was
real and correct — it checked that no *file* was zero bytes. The bug was a zero-length
*payload* from a non-zero file. **A guard aimed at one instance of a class does not immunise
against the class**, and the author who has just written the guard is the least likely person
to notice the next instance, because they believe the area is covered.

**How it was caught.** Not by review. By a cheap check written for a different reason — "no
recorded cell may state a size of 0" — which fired on the artefact the moment it was added.

**Guards.**

1. **Make the tripwire definitional and universal, not per-parser.** The digest of the empty
   input is never a datum, for any vendor, in any artefact, forever. Assert it over *every*
   hash-shaped field at any depth, in the shared gate — not in each parser, where it must be
   remembered.
2. **Distinguish "empty on disk" from "empty after parsing".** They are different failures with
   the same smell, and a guard against one reads as covering both.
3. **Select inputs on a positive identifier, not on the absence of an error.** "Contains this
   byte sequence" is not "is this vendor's stream". Identify positively, then require that the
   parser actually decoded something.
4. **When you write a guard, ask what else is in its class, and put the check where it cannot
   be forgotten.** The gate, not the script.


---

## T22. "The grouping was mine" — a recomputation that nearly retracted a correct claim

**Symptom.** A published table said a driver's raster payload is byte-identical across *"four
papers of one family"*. Recomputing it from scratch — with a new, correct guard excluding
failed captures — produced **a difference**, on one paper. The recomputation was clean, the
guard was right, the control fired. It looked like a retraction.

**Cause.** The recomputation put **five** papers in the row. The fifth, "Baryta Photo Paper",
is a *different* paper family and it **doubles the plane count** — a resolution change, not a
colour transform. The publication had said "four papers of one family" and meant exactly that.
**The claim was right; the grouping was the new code's.**

**What makes it worth recording separately from T18.** T18 is *"a number that contradicts a
standing claim is a reason to check both"*. This is the sharper case: the new number was
computed **correctly**, by a **better-guarded** instrument, and was still wrong — because the
error was not in the arithmetic but in **which rows were put in the bucket**. Re-deriving the
number more carefully would not have caught it. Only reading what the claim actually *said* —
"of one family" — and checking what the fifth row *was* did.

**And the difference was real and useful.** Once removed from the row it did not belong in, the
fifth paper became its own observation, and the colour lever was inert there too — which
**strengthened** the headline it had appeared to refute.

**Guards.**

1. **Read the scope words in the claim before choosing operands.** "Four papers of one family",
   "three models of one package", "on plain paper" are part of the claim, not decoration.
2. **When a recomputation disagrees, suspect the new grouping before the old number.** The
   grouping is the least-reviewed thing in the comparison — it was invented minutes ago.
3. **An outlier is a question, not a verdict.** Ask what the outlier *is* before deciding what
   it *means*. Here one lookup — the paper's own name — settled it.


---

## T23. A description-file keyword holding a path is not evidence the filter will follow it

**Symptom.** Two vendors, the same blocker: a print filter that resolves things by absolute
path under the system's driver directory, which an unprivileged investigator cannot create. On
vendor A this cost **five installed packages**. On vendor B it cost nothing — its filter reads
the driver root from a **keyword in the description file**, so one edited line redirected the
whole tree, no install and no interposition.

The obvious inference — *"vendor A's description files also carry path keywords; the install was
avoidable"* — is wrong, and it looked strong: vendor A's files carry **ten** absolute-path
keywords, one of them literally the driver root, **and** a trace had shown the filter looking
for exactly that path.

**Cause.** Those ten keywords are consumed by the **print system and the print-dialog plug-in**
— setup tools, icons, localisation bundles — not by the filter. Scanning the filter binaries
settles it in one command each:

```
vendor A filter    description-file keywords named: 0 of 10    absolute path literals: 4
                   (including its own framework directory -- which is why four
                    framework packages were needed, not just the driver)
vendor B filter    driver-root keyword named: 1                absolute path literals: 0
```

**The generalisable form:** *a keyword holding a path proves the **print system** can be told
where something is. Only the binary can say whether the **filter** asks.*

**And the escape is vendor-specific.** On the two vendors where this has been checked it is
**data on one and code on the other**. "Blockers of this shape are usually redirectable" is not
supported and should not spread — the useful habit is the cheap check, not the expectation.

**Guards.**

1. **Read the strings before reaching for `DYLD_INSERT_LIBRARIES`.** Vendor B's filter is 8 KB
   and its entire search behaviour is four string literals. Interposition is the expensive
   answer to a question a one-line scan may settle.
2. **Check the consumer, not the declaration.** Grep the binary for the keyword name. Present
   means data; absent means code, whatever the description file contains.
3. **Ask the avoidability question anyway, and in public.** Here the answer was "no, the install
   was necessary" — but it was worth asking, and an approver who asks whether they approved
   something avoidable is doing the job. A "no" that has been checked is worth more than a "no"
   that was assumed.

---

## T24. The cheapest source of truth was our own earlier notes, twice

**Symptom.** A driver family was selected, extracted, mirrored (270 files), repointed and run —
and then found to be unmeasurable, because both of its colour-management options are
**single-valued**: there is no second value to request, so there is no request whose honouring
could be measured. The round could not have produced a verdict under any circumstances.

**Cause.** The project's own survey document already said so, in a table, in one line:

> *"<vendor> laser (UFR/PS) | none — matching options are single-value in these PPDs"*

Nobody read it. The selection was made from package names and binary structure — both genuinely
informative, both about *feasibility* — without checking the one source that spoke to
*worthwhileness*.

**The second instance, same week, different clothes.** A vendor's driver-download service is
reached by a per-file id embedded in a URL. Earlier work used it successfully and recorded the
**URL shape** — and not one id. The service is still live; the route is unusable from our own
notes, and the ids must be rediscovered from the vendor's per-model pages.

**Why it is worth an entry of its own.** Both failures were in the *opposite* direction from
the usual one. The usual trap is trusting an old note too much (T18). This is trusting it too
little — or rather never looking, because prior art feels like *background* while a fresh
measurement feels like *work*. It is the cheapest evidence in the project and the least read,
and being the author of the earlier note is no protection: in both cases the same team wrote it.

**Guards.**

1. **Make the sweep a mechanical first step, not a habit.** A script that greps every prior-art
   source for the vendor/family, and **exits non-zero when it finds nothing** — so "there is no
   prior art" becomes a visible claim rather than a silent assumption.
2. **Require the quote, not the intention.** The selection note must contain the lines the sweep
   returned. "I checked" is unfalsifiable; a quotation is not.
3. **"Prior work says no lever" changes the round; it does not end it.** Confirm or refute the
   old claim cheaply — re-read the current option values and say whether it still holds. A
   five-minute confirmation is a result. Rebuilding a measurement of something with nothing to
   vary is not.
4. **Record what you fetch, at the moment you fetch it.** URLs, file ids, package filenames —
   into the provenance record as they are used, never at write-up time. A route that worked once
   and was not written down is a route you do not have.

---

## T25. `otool -L` answers "what does this link?", not "what will this open?"

**Symptom.** A vendor print filter was checked for redistributable independence the standard
way — `otool -L` showed **system libraries only, no vendor frameworks** — and was declared
*self-contained*, therefore measurable from a scratch directory with **no install**. That test
had been correct on an earlier vendor, where a filter with the same profile really did run
unmodified out of an extracted package.

Here it ran and died immediately with an unhelpful status, and the *first* diagnosis blamed the
wrong process (see below).

**Cause.** The filter loads its **colour-conversion framework at runtime, by absolute path**:

```
strings:   /Library/Printers/<vendor>/<tree>/Libraries/EPConvertManager.framework
otool -L:  EPConvertManager appears 0 times      <- not linked, so linkage analysis is blind
```

Because it is opened rather than linked, `otool -L`, `nm -u` and the whole static-dependency
toolchain cannot see it, and **`DYLD_LIBRARY_PATH`/`DYLD_FRAMEWORK_PATH` do not redirect it** —
those act on install names, not on a runtime open of a literal path.

**Why it mattered rather than merely failing.** A *newer* build of the filter was being run from
a scratch copy while an *older* build of the vendor's driver was installed at the real path. So
the process was new code driving **the old colour framework** — the two differed by 592 bytes
and a different hash, and 793 files differed across the trees. Had it produced output, it would
have been a measurement of a combination that exists nowhere.

**The second error, recorded because it is the more embarrassing one.** The first reading of the
job log said the *upstream* rasteriser had failed and the vendor filter never ran — and
concluded, correctly by that reading, "not evidence about the vendor's filter". The log said the
opposite; the two exit lines were read in the wrong causal order. Running the upstream stage
**alone** settled it in one command: it returned rc=0 and a full-size raster.

**Guards.**

1. **"Self-contained" has two meanings — linkage and resources.** Static analysis proves the
   first. Only `strings` for absolute paths, plus a filesystem trace, speaks to the second.
   Say which one you checked.
2. **Grep the binary for the vendor's own installed tree before claiming zero footprint.** One
   command, and it is the same habit as T23: read the strings.
3. **Never mix versions.** Running build *N* of a filter against build *M* of its data is not a
   measurement of either. If the tree is installed, check that what you are running matches it.
4. **When two processes in a pipeline both fail, isolate before assigning cause.** Exit lines
   are not ordered by causality, and the consumer dying makes the producer fail too. Run each
   stage alone; the one that fails on its own is the one that failed.
