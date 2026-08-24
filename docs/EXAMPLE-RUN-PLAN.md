# Example run plan — deciding between two explanations, with no ink

*A worked example. Substitute your own queue, printer and paper names.*

Your the target printer queue must be **paused** the whole time. Nothing prints; every job just waits,
we read it, and we cancel them all at the end.

Check it is paused before you start:

```bash
python3 ~/print-colour-forensics/tools/ticketwatch.py --list
```

`<your-queue>` must say **STOPPED (paused)**. If it does not:
System Settings ▸ Printers & Scanners ▸ <your printer> ▸ Pause.

After each print, tell me the job number and what you did. At the end:

```bash
python3 ~/print-colour-forensics/tools/ticketwatch.py -q <your-queue> \
    --jobs 341=fresh-canon-only,342=after-epson-switch,...
```

---

## Set A — does the media type really revert? (your original complaint)

The question: when you set **plain paper** and the ticket comes back **Photo Paper Pro
Platinum**, did the driver change it, or was it never set?

Do these **in order**, and please note *exactly* what the Media Type menu showed at the
moment you clicked Print.

| # | what to do | why |
|---|---|---|
| **A1** | Quit the application. Reopen it. Print. Open **Quality & Media**, set **Plain Paper**, **read the menu back aloud** (it should still say Plain Paper), click OK, Print. | a clean baseline where you have confirmed the value on screen |
| **A2** | Without quitting, Print again. **Change nothing at all.** | does an untouched repeat stay the same? |
| **A3** | Print. Open Quality & Media, set **<a photo paper>**, OK. Then Print again, open Quality & Media, set **Plain Paper**, confirm it reads Plain Paper, OK, Print. | switching away and back is where you saw it jump |
| **A4** | Print. Open Quality & Media, set **Plain Paper**, then close that pane with **Cancel** (not OK). Print. | you reported Cancel as a trigger |
| **A5** | Print. Set **Plain Paper**, OK. Then open the **Colour / Rendering Intent** pane, close it with OK. Print. | does touching the colour pane disturb the media? |

**What decides it:** if A1 comes back `CNIJMediaType=0` but A3 or A4 come back `51`, the
driver reverted it — that is the bug, caught. If every run matches what you saw on screen,
the media never reverted and the earlier `51` was simply not set that time.

---

## Set B — do another printer's settings contaminate the target printer job?

Job 338 carried **89 settings from a different manufacturer on a the target printer job**, including one that tells the system
"treat this data as sRGB". We think they rode across from <another printer> being used earlier.

| # | what to do | why |
|---|---|---|
| **B1** | **Quit the application.** Reopen. Print **straight to the target printer** — do not select any other printer first. | clean, no the other printer anywhere in the session |
| **B2** | Without quitting: Print, select the **the other printer** in the dialog, then switch to the **the target printer** in the same dialog, Print. | the printer-switch hypothesis |
| **B3** | Without quitting: Print to the **the other printer** (it is paused too, or cancel it), then Print again and choose the **the target printer**. | a completed the other printer job first |

**What decides it:** B1 should carry **no** `<other-vendor>_*` keys. If B2 or B3 do, settings are
leaking across a printer switch and the application must clear them. If even B1 is contaminated,
it is coming from somewhere else and we look again.

---

## Set C — one extra, if you have the patience

| # | what to do | why |
|---|---|---|
| **C1** | Print with **Plain Paper** selected. | on plain paper the driver was measured to silently override "No Color Correction" |
| **C2** | Print with **<a photo paper>** selected. | on photo paper it was measured to honour it |

We can then compare what the driver *recorded* against what it *sent*.

---

## Finishing up

```bash
python3 ~/print-colour-forensics/tools/ticketwatch.py -q <your-queue> \
    --jobs <id>=A1,<id>=A2,<id>=A3,<id>=A4,<id>=A5,<id>=B1,<id>=B2,<id>=B3
```

It prints a table of exactly what differed between the runs. Then cancel the queued jobs
(the tool offers to) and resume the queue when you are ready:
System Settings ▸ Printers & Scanners ▸ <your printer> ▸ Resume.

Nothing above ever reaches paper.
