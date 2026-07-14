import os
os.environ["EXA_API_KEY"] = ""
os.environ["PERPLEXITY_API_KEY"] = ""
os.environ["API_KEY"] = "test-api-key-for-ci-only"
os.environ["JWT_SECRET"] = "ci-test-secret-do-not-use-in-production"

import sys
from pathlib import Path

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c
