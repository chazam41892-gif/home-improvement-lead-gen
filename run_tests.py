#!/usr/bin/env python3
import sys
from pathlib import Path

project_root = Path(__file__).parent
import pytest
sys.exit(pytest.main([str(project_root / "tests")] + sys.argv[1:]))
