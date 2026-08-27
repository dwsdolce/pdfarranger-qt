"""Per-page cold render cost across a whole document.

    tools/bench_render.py <file.pdf> [width]

Written to answer whether the reader can render on the GUI thread; kept because
the answer has to be re-checked whenever the reader's render path changes. See
PORTING-NOTES.md section 6, "Owning the reader's view".

Report the distribution, never the mean: the cost is bimodal, so the mean
describes no actual page. The median says whether it feels smooth and the tail
says whether it stutters. Render each page once, cold - rendering one page
repeatedly measures PDFium's per-page cache instead.
"""
import statistics
import sys
import time

from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions

app = QGuiApplication(sys.argv)
width = int(sys.argv[2]) if len(sys.argv) > 2 else 2000

doc = QPdfDocument(None)
if doc.load(sys.argv[1]) != QPdfDocument.Error.None_:
    sys.exit("load failed")
n = doc.pageCount()
sz = doc.pagePointSize(0)
h = round(width * sz.height() / sz.width())
size = QSize(width, h)
options = QPdfDocumentRenderOptions()
options.setScaledSize(size)

times = []
for p in range(n):
    t0 = time.perf_counter()
    doc.render(p, size, options)          # each page rendered once, cold
    times.append(((time.perf_counter() - t0) * 1000, p))

ms = sorted(t for t, _ in times)
def pct(q): return ms[min(len(ms) - 1, int(len(ms) * q))]

print(f"{n} pages at {width}x{h}")
print(f"  min      {ms[0]:6.1f}ms")
print(f"  median   {statistics.median(ms):6.1f}ms")
print(f"  p90      {pct(0.90):6.1f}ms")
print(f"  p99      {pct(0.99):6.1f}ms")
print(f"  max      {ms[-1]:6.1f}ms")
print(f"  mean     {statistics.mean(ms):6.1f}ms")
print()
print("  slowest pages:", ", ".join(f"p{p}={t:.0f}ms"
      for t, p in sorted(times, reverse=True)[:5]))
over = sum(1 for t in ms if t > 16.7)
print(f"  pages over one 60Hz frame (16.7ms): {over}/{n} ({100*over/n:.0f}%)")
doc.close()
