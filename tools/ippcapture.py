#!/usr/bin/env python3
"""Minimal IPP/1.1 server that impersonates a CUPS queue and CAPTURES what any
macOS application spools: the full job ticket + the document bytes.

No root, nothing installed, nothing printed -- there is no backend at all.
Reached by pointing ~/.cups/client.conf at it (ServerName localhost:<port>).
"""
import http.server, socketserver, struct, sys, os, time, json, pathlib

PORT = int(os.environ.get("IPP_PORT", "16631"))
CAP  = pathlib.Path(os.environ.get("IPP_CAPTURE", os.path.expanduser("~/.print-forensics/capture")))
CAP.mkdir(parents=True, exist_ok=True)
QUEUE = os.environ.get("IPP_QUEUE", "CaptureQueue")
HOST  = f"localhost:{PORT}"

# --- IPP tags ---
OP_ATTRS, JOB_ATTRS, PRN_ATTRS, END = 0x01, 0x02, 0x04, 0x03
UNSUP = 0x05
INT, BOOL, ENUM = 0x21, 0x22, 0x23
STR, DATE, RES, RANGE, COLL, TXTLANG, NAMELANG = 0x41, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36
TEXT, NAME, KEYWORD, URI, URISCHEME, CHARSET, LANG, MIME = 0x41, 0x42, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49
NOVALUE = 0x12

def enc(tag, name, val):
    if isinstance(val, str): val = val.encode()
    if isinstance(val, int): val = struct.pack(">i", val)
    n = name.encode()
    return struct.pack(">BH", tag, len(n)) + n + struct.pack(">H", len(val)) + val

def enc_more(tag, val):           # additional value of a 1setOf
    if isinstance(val, str): val = val.encode()
    if isinstance(val, int): val = struct.pack(">i", val)
    return struct.pack(">BH", tag, 0) + struct.pack(">H", len(val)) + val

def parse(data):
    """-> (version, opid, reqid, {name: [(tag,bytes)]}, doc_bytes)"""
    v1, v2, op, rid = struct.unpack(">BBHI", data[:8])
    i = 8; attrs = {}; last = None
    while i < len(data):
        tag = data[i]
        if tag == END: i += 1; break
        if tag <= 0x05: i += 1; continue                      # delimiter
        nl = struct.unpack(">H", data[i+1:i+3])[0]; i += 3
        name = data[i:i+nl].decode("utf-8", "replace"); i += nl
        vl = struct.unpack(">H", data[i:i+2])[0]; i += 2
        val = data[i:i+vl]; i += vl
        if nl == 0 and last: attrs[last].append((tag, val))
        else: attrs.setdefault(name, []).append((tag, val)); last = name
    return (v1, v2), op, rid, attrs, data[i:]

def printer_attrs():
    uri = f"ipp://{HOST}/printers/{QUEUE}"
    a  = enc(URI, "printer-uri-supported", uri)
    a += enc(KEYWORD, "uri-authentication-supported", "none")
    a += enc(KEYWORD, "uri-security-supported", "none")
    a += enc(NAME, "printer-name", QUEUE)
    a += enc(TEXT, "printer-info", "Capture queue (no output)")
    a += enc(TEXT, "printer-make-and-model", "Generic Capture Printer")
    a += enc(TEXT, "printer-location", "capture")
    a += enc(ENUM, "printer-state", 3)
    a += enc(KEYWORD, "printer-state-reasons", "none")
    a += enc(BOOL, "printer-is-accepting-jobs", b"\x01")
    a += enc(INT, "queued-job-count", 0)
    a += enc(KEYWORD, "pdl-override-supported", "attempted")
    a += enc(INT, "printer-up-time", int(time.time()))
    a += enc(CHARSET, "charset-configured", "utf-8")
    a += enc(CHARSET, "charset-supported", "utf-8")
    a += enc(LANG, "natural-language-configured", "en-us")
    a += enc(LANG, "generated-natural-language-supported", "en-us")
    a += enc(MIME, "document-format-default", "application/octet-stream")
    for m in ("application/octet-stream","application/pdf","application/postscript",
              "image/urf","image/pwg-raster","application/vnd.cups-raster",
              "image/jpeg","image/tiff","application/vnd.cups-postscript",
              "application/vnd.cups-pdf","text/plain"):
        a += enc(MIME, "document-format-supported", m) if m=="application/octet-stream" else enc_more(MIME, m)
    a += enc(ENUM, "operations-supported", 0x0002)
    for o in (0x0004,0x0005,0x0006,0x0008,0x0009,0x000A,0x000B,0x4001,0x4002,0x4003):
        a += enc_more(ENUM, o)
    a += enc(INT, "printer-type", 0x0004)
    a += enc(BOOL, "color-supported", b"\x01")
    a += enc(KEYWORD, "compression-supported", "none")
    a += enc(INT, "job-priority-supported", 100)
    a += enc(INT, "job-priority-default", 50)
    a += enc(INT, "copies-supported", 1); a += enc_more(INT, 99)
    a += enc(INT, "copies-default", 1)
    a += enc(KEYWORD, "media-supported", "iso_a4_210x297mm"); a += enc_more(KEYWORD, "na_letter_8.5x11in")
    a += enc(KEYWORD, "media-default", "iso_a4_210x297mm")
    a += enc(KEYWORD, "sides-supported", "one-sided")
    a += enc(KEYWORD, "sides-default", "one-sided")
    a += enc(ENUM, "print-quality-supported", 3); a += enc_more(ENUM,4); a += enc_more(ENUM,5)
    a += enc(ENUM, "print-quality-default", 4)
    a += enc(KEYWORD, "print-color-mode-supported", "color"); a += enc_more(KEYWORD,"monochrome")
    a += enc(KEYWORD, "print-color-mode-default", "color")
    a += enc(RES, "printer-resolution-default", struct.pack(">iiB",600,600,3))
    a += enc(RES, "printer-resolution-supported", struct.pack(">iiB",600,600,3))
    a += enc(KEYWORD, "ipp-versions-supported", "1.1"); a += enc_more(KEYWORD,"2.0")
    a += enc(URI, "device-uri", "file:///dev/null")
    a += enc(NAME, "printer-dns-sd-name", QUEUE)
    return a

JOBS = {"n": 0}

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _reply(self, rid, status, body=b""):
        head = struct.pack(">BBHI", 1, 1, status, rid)
        head += struct.pack(">B", OP_ATTRS)
        head += enc(CHARSET, "attributes-charset", "utf-8")
        head += enc(LANG, "attributes-natural-language", "en-us")
        payload = head + body + struct.pack(">B", END)
        self.send_response(200)
        self.send_header("Content-Type", "application/ipp")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(n) if n else b""
        if self.headers.get("Transfer-Encoding","").lower() == "chunked":
            data = b""
            while True:
                ln = self.rfile.readline().strip()
                sz = int(ln.split(b";")[0], 16) if ln else 0
                if sz == 0: self.rfile.readline(); break
                data += self.rfile.read(sz); self.rfile.readline()
        try:
            ver, op, rid, attrs, doc = parse(data)
        except Exception as e:
            self.send_error(400, str(e)); return

        readable = {k: [(hex(t), v.decode("utf-8","replace") if t in (0x41,0x42,0x44,0x45,0x47,0x48,0x49)
                         else (struct.unpack(">i",v)[0] if t in (0x21,0x23) and len(v)==4 else v.hex()))
                        for t, v in vs] for k, vs in attrs.items()}

        if op in (0x4002,):                                  # CUPS-Get-Printers
            self._reply(rid, 0x0000, struct.pack(">B", PRN_ATTRS) + printer_attrs()); return
        if op in (0x4001,):                                  # CUPS-Get-Default
            self._reply(rid, 0x0000, struct.pack(">B", PRN_ATTRS) + printer_attrs()); return
        if op in (0x000B,):                                  # Get-Printer-Attributes
            self._reply(rid, 0x0000, struct.pack(">B", PRN_ATTRS) + printer_attrs()); return
        if op == 0x400F:                                     # CUPS-Get-PPD
            ppd = os.environ.get("IPP_PPD", "")
            if ppd and os.path.exists(ppd):
                head = struct.pack(">BBHI", 1, 1, 0x0000, rid) + struct.pack(">B", OP_ATTRS)
                head += enc(CHARSET, "attributes-charset", "utf-8")
                head += enc(LANG, "attributes-natural-language", "en-us")
                payload = head + struct.pack(">B", END) + open(ppd, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "application/ipp")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers(); self.wfile.write(payload)
                sys.stderr.write("[ppd] CUPS-Get-PPD served\n"); sys.stderr.flush()
                return
            self._reply(rid, 0x0406); return
        if op in (0x000A,):                                  # Get-Jobs
            self._reply(rid, 0x0000); return
        if op in (0x0004,):                                  # Validate-Job
            self._reply(rid, 0x0000); return
        if op in (0x0002, 0x0005, 0x0006):                   # Print-Job / Create-Job / Send-Document
            JOBS["n"] += 1
            jid = JOBS["n"]
            stamp = time.strftime("%H%M%S")
            base = CAP / f"job{jid:03d}-{stamp}"
            with open(str(base) + ".ticket.json", "w") as f:
                json.dump({"operation": hex(op), "ipp_version": ver, "attributes": readable}, f, indent=2)
            if doc:
                open(str(base) + ".doc", "wb").write(doc)
            sys.stderr.write(f"[capture] job {jid} op={hex(op)} doc={len(doc)}B -> {base}\n")
            sys.stderr.flush()
            b  = struct.pack(">B", JOB_ATTRS)
            b += enc(URI, "job-uri", f"ipp://{HOST}/jobs/{jid}")
            b += enc(INT, "job-id", jid)
            b += enc(ENUM, "job-state", 9)                   # completed
            b += enc(KEYWORD, "job-state-reasons", "job-completed-successfully")
            self._reply(rid, 0x0000, b); return
        self._reply(rid, 0x0000)

    def do_GET(self):
        # Serve the real vendor PPD so PrintCore loads the vendor PDE for this queue.
        ppd = os.environ.get("IPP_PPD", "")
        if ppd and self.path.endswith(".ppd") and os.path.exists(ppd):
            b = open(ppd, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.cups-ppd")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b)
            sys.stderr.write(f"[ppd] served {self.path} ({len(b)}B)\n"); sys.stderr.flush()
            return
        self.send_response(200); self.send_header("Content-Length","2"); self.end_headers(); self.wfile.write(b"ok")

class S(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

if __name__ == "__main__":
    sys.stderr.write(f"IPP capture server on {HOST}, queue {QUEUE}, capture -> {CAP}\n"); sys.stderr.flush()
    S(("127.0.0.1", PORT), H).serve_forever()
