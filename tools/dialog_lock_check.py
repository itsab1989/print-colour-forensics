#!/usr/bin/env python3
"""dialog_lock_check -- open a REAL print dialog with colour keys LOCKED, and
look at what that greys out.  NOTHING IS PRINTED AND NOTHING IS SPOOLED.

WHY THIS EXISTS
    An application can lock a print setting so the driver's own dialog cannot
    change it.  Locking is also what *greys out* the control -- which is
    usually what you want for a colour setting, and NOT what you want for the
    paper menu.  There is no way to find out which controls a given lock greys
    except to open the dialog on the real driver and look.

WHAT IT DOES
    Opens your printer's normal print dialog with a set of keys locked, waits
    for you to look at it, and then CANCELS.  No job is created, nothing is
    spooled, no ink is used, and your queue is not touched -- paused or not.

USAGE
    python3 dialog_lock_check.py                 # run every variant in turn
    python3 dialog_lock_check.py --list          # just list your printers
    python3 dialog_lock_check.py -q "<queue>"    # pick the printer explicitly

Requires PyObjC (`pip install pyobjc-framework-Cocoa`), which is already present
in most Python installs that drive macOS printing.
"""
from __future__ import annotations
import argparse, sys

try:
    import AppKit, Foundation
except ImportError:
    sys.exit("This needs PyObjC.  Install it with:  pip install pyobjc-framework-Cocoa")

# ---------------------------------------------------------------------------
# The variants.  Each is (name, what we lock, what to look at).
# ---------------------------------------------------------------------------
APP_CM = "AP_ApplicationColorMatching"

VARIANTS = [
    ("A  colour keys only (what most applications set)",
     {"CNIJIntent2": "1001", "AP_ColorMatchingMode": APP_CM},
     ["Rendering Intent should read 'No Color Correction' and be GREYED",
      "the Media Type / paper menu should still be FULLY SELECTABLE"]),

    ("B  colour + the profile selector (the proposed fix)",
     {"CNIJIntent2": "1001", "AP_ColorMatchingMode": APP_CM, "CNIJProfileID": "3"},
     ["Rendering Intent: still 'No Color Correction' and GREYED",
      "the Media Type / paper menu: is it STILL SELECTABLE?  <-- THIS IS THE QUESTION",
      "anything else newly greyed that was not greyed in variant A"]),

    ("C  colour + profile + media locked as well",
     {"CNIJIntent2": "1001", "AP_ColorMatchingMode": APP_CM,
      "CNIJProfileID": "3", "CNIJMediaType": "42"},
     ["the Media Type menu should now read 'Photo Paper Plus Semi-gloss' and be GREYED",
      "is it greyed, or merely preselected and still changeable?",
      "does the Quality control grey as well?"]),
]


def pick_queue(explicit: str | None) -> str:
    # NOTE: NSPrinter uses the printer's DISPLAY name (spaces), not the CUPS queue
    # name (underscores). Accept either -- they differ for most queues.
    names = list(AppKit.NSPrinter.printerNames())
    if explicit:
        if explicit in names:
            return explicit
        loose = explicit.replace("_", " ").replace("-", " ").lower()
        for n in names:
            if n.replace("_", " ").replace("-", " ").lower() == loose:
                return n
        sys.exit(f"'{explicit}' is not one of: {names}")
    if len(names) == 1:
        return names[0]
    print("Printers on this Mac:")
    for i, n in enumerate(names, 1):
        print(f"   {i}. {n}")
    while True:
        raw = input("Which one? (number) ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(names):
            return names[int(raw) - 1]


def run_variant(queue: str, title: str, locked: dict[str, str], look_for: list[str],
                index: int, total: int) -> None:
    print("\n" + "=" * 72)
    print(f"VARIANT {index} of {total} — {title}")
    print("=" * 72)
    print("Locking these settings on the job:")
    for k, v in locked.items():
        print(f"    {k} = {v}")
    print("\nWhen the dialog opens, look at:")
    for line in look_for:
        print(f"    • {line}")
    print("\n  Open 'Printer Options' / 'Quality & Media' and 'Color Matching' to see them.")
    print("  Then press Cancel in the dialog.  NOTHING WILL PRINT EITHER WAY.")
    input("\n  Press Return to open the dialog... ")

    pr = AppKit.NSPrinter.printerWithName_(queue)
    if pr is None:
        print(f"  !! PrintCore cannot see '{queue}'"); return

    view = AppKit.NSView.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, 288, 288))
    pi = AppKit.NSPrintInfo.sharedPrintInfo().copy()
    pi.setPrinter_(pr)
    d = pi.dictionary()
    for key, val in locked.items():
        d.setObject_forKey_(val, key)

    op = AppKit.NSPrintOperation.printOperationWithView_printInfo_(view, pi)
    op.setShowsPrintPanel_(True)
    op.setShowsProgressPanel_(False)
    panel = op.printPanel()
    # Show the full, normal dialog: printer picker, paper size, preview and the
    # driver's own panes -- otherwise there is nothing to look at.
    panel.setOptions_(panel.options()
                      | AppKit.NSPrintPanelShowsCopies
                      | AppKit.NSPrintPanelShowsPageRange
                      | AppKit.NSPrintPanelShowsPaperSize
                      | AppKit.NSPrintPanelShowsOrientation
                      | AppKit.NSPrintPanelShowsPreview)

    AppKit.NSApp.activateIgnoringOtherApps_(True)   # bring the dialog to the front
    # runModalWithPrintInfo_ only DISPLAYS the panel. The print operation is
    # never run, so no job exists whichever button is pressed.
    result = panel.runModalWithPrintInfo_(pi)
    if result == AppKit.NSModalResponseOK:
        print("\n  You pressed Print — that is fine, NOTHING was submitted.")
        print("  This tool only displays the panel; it never runs the print operation.")
    else:
        print("\n  Dialog cancelled.  Nothing was created.")

    after = pi.dictionary()
    print("\n  What the dialog handed back for those keys:")
    for key, want in locked.items():
        got = after.objectForKey_(key)
        got = str(got) if got is not None else "<absent>"
        flag = "unchanged" if got == want else f"CHANGED (we set {want})"
        print(f"    {key:24s} = {got:32s} {flag}")
    print("\n  >>> Please write down, in your own words, what was greyed and what was not.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-q", "--queue")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", type=int, help="run just one variant (1, 2 or 3)")
    a = ap.parse_args()

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyRegular)

    if a.list:
        for n in AppKit.NSPrinter.printerNames():
            print(" ", n)
        return 0

    queue = pick_queue(a.queue)
    print(f"\nPrinter: {queue}")
    print("Nothing below prints, spools, or changes your queue.  Every dialog is cancelled.")

    variants = VARIANTS if a.only is None else [VARIANTS[a.only - 1]]
    for i, (title, locked, look) in enumerate(variants, 1):
        run_variant(queue, title, locked, look, i, len(variants))

    print("\n" + "=" * 72)
    print("Done.  Nothing was printed and nothing was queued.")
    print("The one answer that matters: in VARIANT B, was the paper menu still selectable?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
