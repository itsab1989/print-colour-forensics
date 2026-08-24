#!/usr/bin/env python3
"""Scan a tree for material that must never reach the public repository.

Run before every push:

    python3 tools/scrub_scan.py .            # this repo
    python3 tools/scrub_scan.py ~/other-repo # anything else about to be published

Exit status is the number of findings, so it drops straight into a pre-push hook.

WHY EACH PATTERN IS HERE.  Every one of these has actually leaked, or nearly leaked,
during this investigation -- the list is a record of mistakes, not a guess at what might
matter.  Device URIs are the newest entry: a queue's device URI carries a HARDWARE
IDENTIFIER (a UUID, or a .local. name derived from the device), and they appear in the
ordinary output of `lpstat -v`, so they arrive in a paste without anyone deciding to
include them.
"""
from __future__ import annotations
import argparse, pathlib, re, sys

# (name, regex, note)
PATTERNS: list[tuple[str, str, str]] = [
    # A REDACTED uri -- ipps://<id>.local./... , ipps://<redacted>, dnssd://<host>/... -- is
    # the correct way to write one of these down, so it must not be flagged: a scanner that
    # cries wolf over the fix teaches people to ignore it. The `<` in the character class
    # already stops the match at a placeholder; this negative lookahead stops a URI whose
    # identifier part IS the placeholder from matching on a later ".local." instead.
    ("device URI with a hardware identifier",
     r"(?:ipps?|dnssd|mdns)://(?!<)[^\s\"'<>)\]]*(?:uuid=|\.local\.)[^\s\"'<>)\]]*",
     "a queue's device URI identifies the physical device; show the scheme only"),
    ("bare UUID",
     r"\buuid=[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
     "printer/device UUIDs are hardware identifiers"),
    ("email address",
     r"\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
     "the noreply address is the only one permitted"),
    ("home directory path",
     r"/Users/(?!you\b|<)[A-Za-z0-9._-]+/",
     "a home path names the account holder; use ~ or a placeholder"),
    ("machine hostname",
     r"(?<![<\w.-])[A-Za-z0-9-]+\.local\.?(?::\d+)?\b",
     "mDNS names are derived from the machine or device name"),
    ("serial number field",
     r"\b(?:serial(?:[ _-]?(?:no|number))?|SN)\s*[:=]\s*[A-Za-z0-9-]{6,}",
     "device serials"),
]

# Names -- of people, customers, accounts and private products -- are NOT listed in this
# file, and that is deliberate: a scanner that carries the words it is looking for publishes
# them itself. (The first version of this script did exactly that, and its own pattern list
# was the only thing it flagged.)
#
# They live OUTSIDE any repository, one per line, in:
#
#     ~/.print-colour-forensics-names        (or $SCRUB_NAMES_FILE)
#
# Lines starting with # are comments. If the file is absent the name check is reported as
# NOT RUN -- never as clean, because "no findings" and "did not look" must not print the
# same way.
NAMES_FILE_DEFAULT = "~/.print-colour-forensics-names"


def name_patterns() -> tuple[list[tuple[str, str, str]], str]:
    """-> (patterns, status).  status is 'loaded: N names' or a reason it did not run."""
    import os
    path = pathlib.Path(os.environ.get("SCRUB_NAMES_FILE", NAMES_FILE_DEFAULT)).expanduser()
    if not path.exists():
        return [], f"NOT RUN -- no name list at {path}"
    words = [w.strip() for w in path.read_text().splitlines()
             if w.strip() and not w.startswith("#")]
    if not words:
        return [], f"NOT RUN -- {path} is empty"
    pat = r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b"
    return ([("name or private product name from the local list", pat,
              "no customer, colleague, account or private-product names -- including in "
              "commit messages")],
            f"loaded: {len(words)} entries from {path}")

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "spool", "caught"}
SKIP_SUFFIX = {".pyc", ".so", ".o", ".png", ".jpg", ".pdf", ".tif", ".tiff",
               ".icc", ".gz", ".zip", ".prn", ".doc", ".ti1", ".ti2", ".ti3"}


def scan(root: pathlib.Path, allow: list[str], patterns) -> int:
    allow_re = [re.compile(a) for a in allow]
    findings = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix in SKIP_SUFFIX:
            continue
        if SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pat, note in patterns:
                for m in re.finditer(pat, line):
                    hit = m.group(0)
                    if any(a.search(line) for a in allow_re):
                        continue
                    findings += 1
                    print(f"{path.relative_to(root)}:{lineno}: {name}: {hit!r}\n"
                          f"    -> {note}")
    return findings


def self_test() -> int:
    """Prove every pattern actually rejects something.

    A guard that has never been shown to reject anything is not a guard -- an earlier check
    in this project passed for weeks because its subject was silently never present. The
    bait is GENERATED here rather than stored in a file, so the repository never contains the
    strings the scanner is hunting for.
    """
    import tempfile
    extra, status = name_patterns()
    names = []
    if extra:
        # recover the words from the compiled alternation, so the bait needs no second copy
        names = [re.sub(r"\\(.)", r"\1", w)
                 for w in re.findall(r"\(\?:(.*?)\)", extra[0][1])[0].split("|")]
    # The bait is ASSEMBLED FROM FRAGMENTS so the literals never appear in this file. If it
    # were written out plainly the scanner would flag its own self-test -- and the tempting
    # fix for that is an exemption, which is how the next leak gets waved through.
    AT, DOT, SL = chr(64), chr(46), chr(47)
    _local = "local"
    bait = [
        ("device URI with a hardware identifier",
         f"ipps:{SL}{SL}EXAMPLEID{DOT}{_local}{DOT}:631{SL}ipp{SL}print"),
        ("bare UUID", "uuid=" + "-".join(["0" * n for n in (8, 4, 4, 4, 12)])),
        ("email address", f"somebody{AT}example{DOT}invalid"),
        ("home directory path", f"{SL}Users{SL}someaccount{SL}work"),
        ("machine hostname", f"some-machine{DOT}{_local}"),
        ("serial number field", "serial" + "-no: ABC123456"),
    ] + ([("name or private product name from the local list", names[0])] if names else [])

    ok = True
    print("scrub_scan self-test — every pattern must reject its bait")
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        for i, (label, text) in enumerate(bait):
            (root / f"b{i}.txt").write_text(text + "\n")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            scan(root, [], PATTERNS + extra)
        out = buf.getvalue()
        for label, _ in bait:
            hit = label in out
            print(f"  {'PASS' if hit else 'FAIL'}  {label}")
            ok &= hit
    # and the one thing that must NOT be flagged
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        AT, DOT = chr(64), chr(46)
        (root / "ok.txt").write_text(
            f"someone{AT}users{DOT}noreply{DOT}github{DOT}com\n")
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            n = scan(root, [], [p for p in PATTERNS if p[0] == "email address"])
        clean = (n == 0)
        print(f"  {'PASS' if clean else 'FAIL'}  the noreply address is NOT flagged")
        ok &= clean
    if not extra:
        print("  WARN  name check not loaded, so its bait was skipped")
    print("ALL PASS" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


def git_check(root: pathlib.Path) -> int:
    """Check the repository's HISTORY, not just its working tree.

    The working tree can be spotless while a commit, a tag or a leftover backup ref still
    carries an identity that must not be published. `git filter-branch` in particular leaves
    the entire pre-rewrite history under `refs/original/`, so a rewrite that removed an
    address from every commit can leave a complete copy of the old commits one
    `git push --mirror` away from being published again.
    """
    import subprocess
    PERMITTED = "users.noreply.github.com"

    def git(*args) -> str:
        try:
            return subprocess.run(["git", "-C", str(root), *args],
                                  capture_output=True, timeout=30).stdout.decode(
                                      "utf-8", "replace")
        except Exception:
            return ""

    if not (root / ".git").exists():
        print(f"git check: NOT RUN — {root} is not a git repository")
        return 1

    problems = 0
    refs = [l.strip() for l in git("for-each-ref", "--format=%(refname)").splitlines()
            if l.strip()]
    print("git check — every commit reachable from every ref")
    for ref in refs:
        bad = sorted({a for a in git("log", "--format=%ae%n%ce", ref).split()
                      if a and not a.endswith(PERMITTED)})
        kind = ("BACKUP REF (git filter-branch leftover)"
                if ref.startswith("refs/original/") else "ref")
        if bad:
            problems += 1
            print(f"  FAIL  {ref}  [{kind}]")
            for a in bad:
                print(f"          author/committer: {a}")
        else:
            print(f"  PASS  {ref}")

    if problems:
        print("\nA ref carrying a non-permitted identity is one `git push --mirror` or "
              "`git push --all` away from publishing it again.")
        print("For filter-branch leftovers, once you are satisfied the rewrite is correct:")
        print("    git for-each-ref --format='%(refname)' refs/original | "
              "xargs -n1 git update-ref -d")
        print("    git reflog expire --expire=now --all && git gc --prune=now --aggressive")
        print("That is a DELETION of the pre-rewrite history. It is the owner's call, not "
              "the tool's — this check reports it and stops.")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".", help="tree to scan")
    ap.add_argument("--allow", action="append", default=[],
                    help="regex; a LINE matching it is exempt. Use sparingly and never for "
                         "a real identifier -- an exemption is how the next leak happens.")
    ap.add_argument("--self-test", action="store_true",
                    help="prove each pattern rejects generated bait, then exit")
    ap.add_argument("--git", action="store_true",
                    help="also check every commit reachable from every ref, including "
                         "filter-branch backup refs, for a non-permitted identity")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    root = pathlib.Path(a.root).resolve()
    extra, status = name_patterns()
    n = scan(root, a.allow, PATTERNS + extra)
    if a.git:
        n += git_check(root)
    print(f"\nname check: {status}")
    print(f"{n} finding(s) in {root}")
    if not extra:
        print("⚠ The name check DID NOT RUN. Treat this scan as incomplete: it cannot have "
              "found a name it was never given.")
    if n:
        print("Nothing may be pushed until every one is resolved or explicitly exempted.")
    return min(n, 125) or (0 if extra else 1)


if __name__ == "__main__":
    sys.exit(main())
