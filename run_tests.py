#!/usr/bin/env python3
import sys
import shutil
from pathlib import Path

project_root = Path(__file__).parent
init_py = project_root / "__init__.py"
init_bak = project_root / "__init__.py.bak"

if init_py.exists():
    shutil.move(str(init_py), str(init_bak))
    restored = True
else:
    restored = False

try:
    import pytest
    sys.exit(pytest.main([str(project_root / "tests")] + sys.argv[1:]))
finally:
    if restored:
        shutil.move(str(init_bak), str(init_py))
