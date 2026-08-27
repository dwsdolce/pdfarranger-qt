"""Cost of entering read mode: the in-memory export, not the page rendering.

    tools/bench_export.py <file.pdf>

D15 has the reader showing an export of the edited page list rather than the
source, rebuilt whenever the snapshot goes stale, so entering read mode pays for
a whole document before it draws a page. tools/bench_render.py measures the
drawing; this measures getting the document.

Reports peak RSS as well as wall time: on a large file the memory is the worse
half. See PORTING-NOTES.md section 6, "Entering read mode costs more than
reading does".
"""
import os
import resource
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from pdfarranger_qt.core import DocumentSet  # noqa: E402
from pdfarranger_qt.export import get_in_memory_pdf  # noqa: E402
from pdfarranger_qt.render import MemoryDocument  # noqa: E402

app = QGuiApplication(sys.argv)
path = sys.argv[1]


def rss_mb():
    # macOS reports ru_maxrss in bytes; Linux in kilobytes.
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1024 / 1024 if sys.platform == "darwin" else r / 1024


def step(label, fn):
    before = rss_mb()
    t0 = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - t0) * 1000
    print(f"  {label:<38} {ms:9.0f} ms   peak RSS {rss_mb():7.0f} MB "
          f"(+{rss_mb() - before:.0f})")
    return result


print(f"file: {os.path.basename(path)}  ({os.path.getsize(path)/1024/1024:.0f} MB on disk)")
print(f"baseline RSS {rss_mb():.0f} MB")
print()

docs = DocumentSet()
try:
    pages = step("open (add_file, incl. working copy)", lambda: docs.add_file(path))
    print(f"  -> {len(pages)} pages")
    files = docs.files_for_export()
    names = docs.source_names()

    plain = step("export, outlines=False", 
                 lambda: get_in_memory_pdf(list(pages), files, outlines=False,
                                           source_names=names))
    print(f"  -> {len(plain)/1024/1024:.0f} MB of PDF")
    del plain

    data = step("export, outlines=True  (what read mode does)",
                lambda: get_in_memory_pdf(list(pages), files, outlines=True,
                                          source_names=names))
    print(f"  -> {len(data)/1024/1024:.0f} MB of PDF")

    doc = step("MemoryDocument (QByteArray + parse)", lambda: MemoryDocument(data))
    print(f"  -> ok={doc.ok}  pages={doc.page_count()}")
    doc.close()
finally:
    docs.cleanup()
