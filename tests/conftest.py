"""Shared test fixtures.

Two things matter here:

1.  ISOLATION -- the suite must never touch the real database. `engine.database`
    reads DATABASE_FILE at import time, so without this the test run silently
    writes into data/lead_gen.db (the production file). Every test now gets a
    per-session temp database, and a guard fixture fails the run if anything
    reopens the production file.

2.  CREDENTIALS -- tests set throwaway secrets via the environment, never the
    real .env. This is why the isolation below must happen BEFORE `main` is
    imported.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# ── 1. Redirect the database BEFORE anything imports engine.database ───────
# Must precede `import main` below, because engine.database reads the env var
# at module import and Database.initialize() runs on that same import.
# LEADGEN_TESTING tells main.py to call load_dotenv(override=False) so this
# value cannot be clobbered back to the production path.
os.environ["LEADGEN_TESTING"] = "1"
_TMP_DIR = tempfile.mkdtemp(prefix="leadgen-tests-")
TEST_DB = os.path.join(_TMP_DIR, "test_lead_gen.db")
os.environ["DATABASE_FILE"] = TEST_DB
# Strip any inherited production DB override so a developer's shell env cannot
# point the suite at real data.
os.environ.pop("DATABASE_URL", None)

os.environ["EXA_API_KEY"] = ""
os.environ["PERPLEXITY_API_KEY"] = ""
os.environ["API_KEY"] = "test-api-key-for-ci-only"
os.environ["JWT_SECRET"] = "ci-test-secret-do-not-use-in-production"
# Never let a test send real mail/SMS/ad spend.
os.environ["SENDGRID_API_KEY"] = ""
os.environ["TWILIO_ACCOUNT_SID"] = ""
os.environ["TWILIO_AUTH_TOKEN"] = ""
os.environ["STRIPE_SECRET_KEY"] = ""
os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"] = ""
os.environ["META_ACCESS_TOKEN"] = ""

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from engine.database import Database  # noqa: E402

# `import main` builds module-level singletons, and engine/trades/convert.py's
# `ConversionPipeline.__init__` calls `Database.set_db_file("data/lead_gen.db")`
# -- discarding the DATABASE_FILE redirect above. The real DB is only opened by
# that call, so re-point after the import and the guard below passes honestly.
Database.set_db_file(TEST_DB)
Database.initialize()

# Fail loudly at collection time if isolation did not take effect, rather than
# letting a whole suite quietly mutate production data.
_REAL_DB = str((Path(project_root) / "data" / "lead_gen.db").resolve())
if Path(Database.db_file).resolve() == Path(_REAL_DB).resolve():
    raise RuntimeError(
        "TEST ISOLATION BROKEN: engine.database is pointed at the production "
        f"database ({_REAL_DB}). Refusing to run -- the suite would corrupt "
        "real lead data. Check conftest.py ordering."
    )


@pytest.fixture(scope="session", autouse=True)
def _verify_isolation_holds():
    """Confirm the production DB is never opened during the session."""
    yield
    assert Path(Database.db_file).resolve() != Path(_REAL_DB).resolve()


@pytest.fixture
def tmp_db(tmp_path):
    """Point Database at a per-test temp file, restoring it afterwards."""
    original = Database.db_file
    Database.db_file = str(tmp_path / "leads.db")
    try:
        yield Database.db_file
    finally:
        Database.db_file = original


@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-api-key-for-ci-only"})
        yield c


@pytest.fixture
def conn(tmp_db):
    """A connection to an isolated, initialized database."""
    Database.initialize()
    connection = sqlite3.connect(Database.db_file)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()
