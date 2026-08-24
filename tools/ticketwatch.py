#!/usr/bin/env python3
"""ticketwatch — catch a print driver changing your settings behind your back.

THE PROBLEM THIS SOLVES
    You set "no colour management" in the print dialog, you print, and the output
    is colour-managed anyway.  Or the setting silently reverts when you change
    paper.  You cannot see it happen, and the app cannot either.

HOW IT WORKS
    You PAUSE the printer queue.  Jobs then queue up and never reach the printer,
    so nothing prints and no ink is used -- but everything else is completely
    real: your real queue, the real driver, the real print dialog, the real
    vendor plug-in, and your own hands doing whatever broke it last time.
    This tool reads each queued job's full ticket and shows you, at the end,
    exactly which settings differ between jobs you believed were identical.

    Nothing is installed.  Nothing needs a password.  Pausing and resuming are
    normal actions you can also do in System Settings > Printers.

USAGE
    python3 ticketwatch.py --list                       # show queues and pause state
    python3 ticketwatch.py -q <queue>                   # watch (queue must be paused)
    python3 ticketwatch.py -q <queue> --report          # re-print the table and exit

WHAT IT PROVES / CANNOT PROVE
    Proves: what the print system recorded for each job, and what changed between
    jobs.  Cannot prove: what the driver's own filter or the printer's firmware
    then does with those values -- for that you must print and measure.

SAFETY
    * It refuses to watch a queue that is not paused.
    * It never releases, resumes or prints anything by itself.
    * On exit it offers to cancel the queued jobs; resuming the queue is left to
      you, deliberately, so nothing can start printing without your say-so.
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time, datetime, pathlib

try:
    import cups
except ImportError:
    cups = None

NOISE = {
    "time-at-creation", "time-at-processing", "time-at-completed", "job-id",
    "job-uri", "job-printer-up-time", "job-k-octets", "job-media-sheets-completed",
    "job-name", "document-name-supplied", "job-state", "job-state-reasons",
    "job-hold-until", "job-originating-host-name", "job-media-progress",
    "com.apple.print.JobInfo.PMJobName", "job-impressions-completed",
}


def conn():
    if cups is None:
        sys.exit("This tool needs pycups.  Install with:  pip install pycups")
    return cups.Connection()


def queues(c):
    out = {}
    for name, attrs in c.getPrinters().items():
        state = attrs.get("printer-state")
        out[name] = {
            "model": attrs.get("printer-make-and-model", "?"),
            "state": {3: "idle", 4: "processing", 5: "STOPPED (paused)"}.get(state, state),
            "paused": state == 5,
            "accepting": attrs.get("printer-is-accepting-jobs"),
            "reasons": attrs.get("printer-state-reasons", []),
        }
    return out


def cmd_list():
    c = conn()
    print(f"{'queue':32s} {'state':18s} {'accepting':10s} model")
    for n, q in queues(c).items():
        print(f"{n:32s} {str(q['state']):18s} {str(q['accepting']):10s} {q['model']}")
    print("\nTo pause a queue: System Settings > Printers & Scanners > (printer) > Pause,")
    print("or:  cupsdisable <queue>     (may ask for your password)")
    print("A paused queue still ACCEPTS jobs -- they just wait. That is what we want.")


def snapshot(c, queue):
    jobs = {}
    for jid, attrs in c.getJobs(which_jobs="not-completed", my_jobs=False).items():
        if queue in str(attrs.get("job-printer-uri", "")):
            jobs[jid] = attrs
    return jobs


def ticket(c, jid):
    try:
        return c.getJobAttributes(jid)
    except Exception as exc:
        return {"__error__": str(exc)}


def clean(t):
    return {k: v for k, v in t.items() if k not in NOISE and not k.startswith("time-")}


VENDOR_PREFIXES = ("EPIJ", "EPSON", "CNIJ", "Canon", "HP", "Brother", "BR", "Lexmark",
                   "XR", "SEC", "RPS", "Samsung", "Xerox", "Ricoh")
INTERESTING = ("Intent", "Color", "Colour", "Matching", "Profile", "MediaType", "Media",
               "Quality", "Rendering", "ICC", "Gamma", "Gray", "Grey")


def _vendor_of(key):
    for v in VENDOR_PREFIXES:
        if key.startswith(v):
            return v
    return None


def diff_table(records):
    """records: list of dicts {label, jid, ticket}."""
    if not records:
        print("\n  No jobs were captured."); return
    keys = set()
    for r in records:
        keys |= set(clean(r["ticket"]))
    def val(r, k):
        return clean(r["ticket"]).get(k, None)
    changing = [k for k in sorted(keys)
                if len({json.dumps(val(r, k), default=str) for r in records}) > 1]

    print(f"\n{'='*104}\nWHAT CHANGED BETWEEN YOUR JOBS\n{'='*104}")
    print("  jobs:")
    for i, r in enumerate(records):
        print(f"    job{i+1} (id {r['jid']}): {r['label']}")
    if not changing:
        print(f"\n  NOTHING changed between them — every setting was identical in all "
              f"{len(records)} jobs.\n  If the misprint still happens, the cause is NOT in what "
              "the computer sent; it is in the printer.")
        return

    # 1. foreign-vendor contamination, summarised rather than dumped
    print("\n  -- FOREIGN VENDOR KEYS " + "-"*79)
    any_foreign = False
    for i, r in enumerate(records):
        t = clean(r["ticket"])
        vendors = {}
        for k in t:
            v = _vendor_of(k)
            if v:
                vendors.setdefault(v, []).append(k)
        if len(vendors) > 1:
            any_foreign = True
            parts = ", ".join(f"{len(ks)} {v}* keys" for v, ks in sorted(vendors.items()))
            print(f"    job{i+1}: {parts}")
            print(f"           -> settings from more than one printer make are on this job.")
    if not any_foreign:
        print("    none — every job carried keys from a single printer make.")

    # 2. the settings that actually matter
    substantive = [k for k in changing
                   if any(w.lower() in k.lower() for w in INTERESTING)]
    others = [k for k in changing if k not in substantive]
    def render(title, ks):
        if not ks: return
        print(f"\n  -- {title} " + "-"*max(0, 100-len(title)))
        w = min(46, max(len(k) for k in ks) + 2)
        print("    " + "setting".ljust(w) + "".join(f"job{i+1}".ljust(18) for i in range(len(records))))
        print("    " + "-"*(w + 18*len(records)))
        for k in ks:
            row = "    " + k[:w-1].ljust(w)
            for r in records:
                v = val(r, k)
                row += (("(absent)" if v is None else str(v))[:16]).ljust(18)
            print(row)
    render("COLOUR / MEDIA SETTINGS THAT DIFFER", substantive)
    if others:
        print(f"\n  -- {len(others)} other setting(s) also differ "
              f"(mostly the foreign keys above); use --verbose to list them")

    print("\n  HOW TO READ THIS: any row where two jobs you believed were the SAME have")
    print("  different values is the driver changing your settings behind your back.")
    print("  A job carrying another manufacturer's keys is settings leaking across a")
    print("  printer switch — those should not be there at all.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-q", "--queue")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--jobs", help="comma-separated job ids to read directly (held jobs), "
                                   "optionally id=label,id=label")
    ap.add_argument("--files", nargs="*", help="read previously saved ticket .json files")
    ap.add_argument("--out", default=os.path.expanduser("~/.print-forensics/tickets"))
    a = ap.parse_args()

    if a.list or not a.queue:
        cmd_list()
        return 0

    outdir = pathlib.Path(a.out) / a.queue
    outdir.mkdir(parents=True, exist_ok=True)
    c = conn()


    if a.files:
        recs=[]
        for f in a.files:
            d=json.loads(pathlib.Path(f).read_text())
            t=d.get("ticket", d)
            recs.append({"label": d.get("label", pathlib.Path(f).stem),
                         "jid": d.get("jid", "?"),
                         "ticket": {k: str(v) for k, v in t.items()}})
        diff_table(recs)
        return 0

    if a.jobs:
        recs=[]
        for item in a.jobs.split(","):
            jid, _, label = item.partition("=")
            jid = int(jid.strip())
            t = ticket(c, jid)
            recs.append({"label": label.strip() or f"job {jid}", "jid": jid,
                         "ticket": {k: str(v) for k, v in t.items()}})
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / f"job{jid}.json").write_text(
                json.dumps({"jid": jid, "label": label.strip(),
                            "ticket": {k: str(v) for k, v in t.items()}}, indent=2))
        diff_table(recs)
        return 0

    if a.report:
        recs = []
        for f in sorted(outdir.glob("*.json")):
            d = json.loads(f.read_text())
            recs.append({"label": d["label"], "jid": d["jid"], "ticket": d["ticket"]})
        diff_table(recs)
        return 0

    q = queues(c).get(a.queue)
    if q is None:
        sys.exit(f"No such queue: {a.queue}")
    if q["accepting"] is False:
        print(f"\n  '{a.queue}' is not accepting jobs — your prints would be rejected, not queued.")
        print("  Enable it first:  cupsaccept " + a.queue)
        return 1
    if not q["paused"]:
        print(f"\n  REFUSING TO START: '{a.queue}' is not paused (state: {q['state']}).")
        print("  Jobs would go to the printer and use ink.\n")
        print("  Pause it first: System Settings > Printers & Scanners > "
              f"{a.queue} > Pause")
        print(f"  or:  cupsdisable {a.queue}")
        print("\n  Then run this again. I will check again before starting.")
        return 1

    print(f"\n{'='*100}")
    print(f"  WATCHING: {a.queue}   ({q['model']})")
    print(f"  The queue is PAUSED, so nothing will print and no ink will be used.")
    print(f"  state reasons: {q['reasons']}")
    print(f"{'='*100}\n")
    print("  Now print from any application, as many times as you like:")
    print("    * print once normally, the way you always do")
    print("    * print again WITHOUT touching anything  (does it stay the same?)")
    print("    * change the paper type, then set the colour option again, then print")
    print("    * open a settings pane and close it with CANCEL, then print")
    print("    * reopen the print dialog without changing anything, then print")
    print("    * use a saved preset, then print")
    print("    * quit and reopen the application, then print")
    print("\n  After each job I will ask you what you just did. Press Ctrl-C when done.\n")

    seen = set(snapshot(c, a.queue))
    records = []
    try:
        while True:
            time.sleep(1.5)
            now = snapshot(c, a.queue)
            for jid in sorted(set(now) - seen):
                seen.add(jid)
                t = ticket(c, jid)
                print(f"\n  >>> caught job {jid}")
                try:
                    label = input("      what did you just do? (short description): ").strip()
                except EOFError:
                    label = ""
                label = label or f"job {jid}"
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                (outdir / f"{stamp}-{jid}.json").write_text(
                    json.dumps({"jid": jid, "label": label,
                                "ticket": {k: str(v) for k, v in t.items()}}, indent=2))
                records.append({"label": label, "jid": jid,
                                "ticket": {k: str(v) for k, v in t.items()}})
                print(f"      recorded ({len(records)} so far)")
    except KeyboardInterrupt:
        pass

    diff_table(records)

    pend = snapshot(c, a.queue)
    if pend:
        print(f"\n  {len(pend)} job(s) are still queued on '{a.queue}'.")
        try:
            ans = input("  Cancel them all now? [Y/n]: ").strip().lower()
        except EOFError:
            ans = "y"
        if ans in ("", "y", "yes"):
            for jid in pend:
                try:
                    c.cancelJob(jid)
                except Exception as exc:
                    print(f"    could not cancel {jid}: {exc}")
            left = snapshot(c, a.queue)
            print(f"    cancelled. jobs remaining: {len(left)}")
        else:
            print("    left in place — remember they will print when you resume the queue.")
    print(f"\n  The queue is STILL PAUSED. Resume it yourself when you are ready:")
    print(f"    System Settings > Printers & Scanners > {a.queue} > Resume")
    print(f"    or:  cupsenable {a.queue}")
    print(f"\n  Tickets saved in: {outdir}")
    print(f"  Re-print this table any time:  python3 ticketwatch.py -q {a.queue} --report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
