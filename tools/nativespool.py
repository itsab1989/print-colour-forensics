#!/usr/bin/env python3
"""nativespool -- spool a REAL job through PrintCore/NSPrintOperation (no dialog).

macOS-specific. Builds an NSBitmapImageRep the way a Cocoa application does and
prints it to a chosen queue, so you can capture what PrintCore ACTUALLY spools
(pair with ippcapture.py + CUPS_SERVER).

WHAT IT PROVES: the bytes and the job ticket a Cocoa print path puts on the wire.
WHAT IT CANNOT PROVE: what the vendor filter or firmware then does.
POSITIVE CONTROL: pass "foreign" as the third argument -- it retags the same
pixels with a different ICC profile; the spooled document MUST change. If it does
not, your capture is not seeing the real spool.

    CUPS_SERVER=localhost:16631 python3 nativespool.py chart.tif "<queue>" [device|foreign]
"""
import signal, sys, os
signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(SystemExit("TIMEOUT")))
signal.alarm(int(os.environ.get("PROBE_TIMEOUT", "120")))
import numpy as np, AppKit, Foundation, objc
from PIL import Image

TIF, QUEUE = sys.argv[1], sys.argv[2]
MODE = sys.argv[3] if len(sys.argv) > 3 else "device"

print("NSPrinter.printerNames:", list(AppKit.NSPrinter.printerNames())[:12])
pr = AppKit.NSPrinter.printerWithName_(QUEUE)
print(f"printerWithName_({QUEUE}) -> {pr}")
if pr is None:
    raise SystemExit("QUEUE NOT VISIBLE TO PrintCore")

with Image.open(TIF) as im:
    rgb = im.convert("RGB"); w, h = rgb.size
    dpi = rgb.info.get("dpi") or (300.0, 300.0)
    raw = rgb.tobytes()
rep = AppKit.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
    None, w, h, 8, 3, False, False, AppKit.NSDeviceRGBColorSpace, w*3, 24)
rep.bitmapData()[:len(raw)] = raw
if MODE == "foreign":
    p = AppKit.NSColorSpace.alloc().initWithICCProfileData_(
        Foundation.NSData.dataWithContentsOfFile_("/System/Library/ColorSync/Profiles/AdobeRGB1998.icc"))
    rep = rep.bitmapImageRepByRetaggingWithColorSpace_(p)
    print("CONTROL: retagged", rep.colorSpace().localizedName())

pts = (w*72.0/float(dpi[0] or 300), h*72.0/float(dpi[1] or 300))

class V(AppKit.NSView):
    def drawRect_(self, r):
        rep.drawInRect_(Foundation.NSMakeRect(0, 0, pts[0], pts[1]))
    def knowsPageRange_(self, rp): return True, Foundation.NSMakeRange(1, 1)
    def rectForPage_(self, p): return Foundation.NSMakeRect(0, 0, pts[0], pts[1])

v = V.alloc().initWithFrame_(Foundation.NSMakeRect(0, 0, pts[0], pts[1]))
pi = AppKit.NSPrintInfo.sharedPrintInfo().copy()
pi.setPrinter_(pr)
pi.setPaperSize_(Foundation.NSMakeSize(pts[0], pts[1]))
for s in ("setLeftMargin_","setRightMargin_","setTopMargin_","setBottomMargin_"):
    getattr(pi, s)(0.0)
pi.setHorizontalPagination_(AppKit.NSClipPagination)
pi.setVerticalPagination_(AppKit.NSClipPagination)
d = pi.dictionary()
d.setObject_forKey_("AP_ApplicationColorMatching", "AP_ColorMatchingMode")
d.setObject_forKey_("1001", "CNIJIntent2")
op = AppKit.NSPrintOperation.printOperationWithView_printInfo_(v, pi)
op.setShowsPrintPanel_(False)
op.setShowsProgressPanel_(False)
print("running print operation ->", QUEUE)
ok = op.runOperation()
print("runOperation ->", ok)
