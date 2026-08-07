import sys

# Absolute, not `from .app import main`. PyInstaller uses this file as the entry
# script and runs it as a top-level module with no package context, so a
# relative import fails at startup with "attempted relative import with no known
# parent package". The absolute form works both frozen and under
# `python -m pdfarranger_qt`.
from pdfarranger_qt.app import main

sys.exit(main())
