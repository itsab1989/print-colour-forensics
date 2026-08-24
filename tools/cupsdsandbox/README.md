# A CUPS scheduler you control

Vendor print filters generally cannot be run by hand — they expect a real CUPS
environment and will crash or block without one. The system scheduler is root-only
(`-r-x------ root:wheel` on macOS), so you cannot borrow it. Build your own.

No root. Nothing installed system-wide. Nothing printed: the backend is a capture program.

## 1. Build

```bash
curl -LO https://github.com/OpenPrinting/cups/releases/download/v2.4.19/cups-2.4.19-source.tar.gz
tar xzf cups-2.4.19-source.tar.gz && cd cups-2.4.19
./configure --prefix="$SANDBOX" --with-cups-user="$(id -un)" --with-cups-group="$(id -gn)" \
            --disable-libusb --disable-gssapi
make -j8
make install            # the launchd step fails: it targets a read-only system path.
                        # That failure is expected and harmless.
cd scheduler && make install-exec     # installs cupsd itself
```

## 2. Configure

Use `cupsd.conf` and `cups-files.conf` from this directory, replacing `@SANDBOX@` with your
prefix. Key points: high port, `FileDevice Yes`, `ServerBin` in your prefix, and
`DefaultAuthType None` so `lpadmin` needs no password.

Then make the OS filters and mime rules visible to your scheduler:

```bash
for f in /usr/libexec/cups/filter/*; do ln -sf "$f" "$SANDBOX/libexec/cups/filter/$(basename "$f")"; done
cp /usr/share/cups/mime/*.convs /usr/share/cups/mime/*.types "$SANDBOX/share/cups/mime/"
mkdir -p "$SANDBOX/var/cache/cups" "$SANDBOX/var/spool/cups/tmp"
```

## 3. The three obstacles

**`cups-exec` exits 101.** That is `errno + 100` = `EPERM`: a non-root scheduler cannot
`setuid`/`setgid`. Build `cupsexec.c` from this directory over
`$SANDBOX/libexec/cups/daemon/cups-exec` — it skips the sandbox profile and the uid/gid
change and execs the program.

The real argument layout is **not** what the header comment suggests:

```
cups-exec  -g GID  -n NICE  -u UID  /path/to/profile  /path/to/program  argv0 argv1 …
```

The profile path comes *after* the options, so scan for the first existing executable path
rather than counting arguments.

**Backends are sandboxed.** Write captures to `$TMPDIR`, which the generated profile
allows. `capback.c` does this.

**The vendor filter may want a plausible `DEVICE_URI`.** With none it may crash; with an
unreachable one it may report a communication error and poll for ever. Because the
scheduler is yours, give the queue the URI scheme the vendor expects and replace *that
scheme's backend* with the capture program:

```bash
cc -O2 -o "$SANDBOX/libexec/cups/backend/<scheme>" capback.c
```

## 4. Add the queue and run

```bash
"$SANDBOX/sbin/cupsd" -c "$SANDBOX/etc/cups/cupsd.conf" -f &
./systemv/lpadmin -h localhost:16632 -p Probe -v '<scheme>:/probe' -P /etc/cups/ppd/<queue>.ppd -E
lp -h localhost:16632 -d Probe test.pdf
ls "$SANDBOX/var/spool/cups/tmp/"*.prn      # the vendor's stream
```

A successful run logs, in `$SANDBOX/var/log/cups/error_log`:

```
<vendor filter> ... exited with no errors.
captured NNNNN bytes to .../cap-<job>-<time>.prn
```

## 5. Compare runs — and control first

Vendor streams contain nonces (job GUIDs, timestamps). Run the **same** configuration at
least twice and normalise until the repeats are byte-identical (`../canon_stream.py`)
before comparing different configurations. Without this you will invent differences that
are only the clock — see `../../docs/TRAPS.md` T5.

## 6. Teardown

```bash
cancel -h localhost:16632 -a -x Probe
pkill -f "$SANDBOX/sbin/cupsd"
rm -rf "$SANDBOX"
```

Then verify the system is untouched: `lpstat -p` shows your original queues, `lpstat -o`
is empty, and `/usr/sbin/cupsd` is unchanged.
