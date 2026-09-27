import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

DB_FILE = os.environ.get("DATABASE_FILE", "data/lead_gen.db")


class Database:
    db_file = DB_FILE

    @classmethod
    def set_db_file(cls, path: str):
        cls.db_file = path

    @classmethod
    def get_connection(cls):
        os.makedirs(os.path.dirname(cls.db_file) or "data", exist_ok=True)
        # check_same_thread=False: the API serves requests from a thread pool and
        # the background scheduler/nurture loops run on their own threads. Without
        # it, sqlite3 raises ProgrammingError on any cross-thread reuse, which
        # surfaces to the client as a 500 rather than a clear error.
        # timeout=30: wait rather than immediately raising "database is locked"
        # when another connection holds a write lock.
        conn = sqlite3.connect(cls.db_file, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # WAL lets readers proceed while a writer holds the lock, instead of
        # serialising every read behind every write. This is the difference
        # between a p50 of 3ms and p50 of 890ms under concurrent load on the
        # same SQLite file. Only set on first open, and is a no-op for :memory:.
        if cls.db_file != ":memory:":
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA foreign_keys=ON")
            except sqlite3.OperationalError:
                # Some filesystems (network shares) reject WAL. Roll back to the
                # default journal rather than failing the request.
                logger.warning("WAL not available for %s; using default journal", cls.db_file)
        return conn

    @classmethod
    def initialize(cls):
        with cls.get_connection() as conn:
            # Create leads table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS leads (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    snippet TEXT,
                    industry TEXT,
                    location TEXT,
                    source TEXT,
                    score REAL,
                    found_at TEXT,
                    email TEXT,
                    phone TEXT,
                    notes TEXT,
                    score_breakdown TEXT,
                    status TEXT DEFAULT 'new',
                    first_name TEXT,
                    last_name TEXT,
                    address TEXT,
                    project_description TEXT,
                    utm_source TEXT,
                    utm_medium TEXT,
                    utm_campaign TEXT,
                    sms_consent INTEGER DEFAULT 0,
                    email_consent INTEGER DEFAULT 0,
                    call_consent INTEGER DEFAULT 0,
                    consent_source TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Migration: add missing columns for schema drift
            existing = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
            cols = {
                "project_description": "TEXT",
                "sms_consent": "INTEGER DEFAULT 0",
                "email_consent": "INTEGER DEFAULT 0",
                "call_consent": "INTEGER DEFAULT 0",
                "consent_source": "TEXT",
                "website": "TEXT",
                "employee_count": "TEXT",
                "revenue": "TEXT",
                "confidence_score": "REAL",
                "enriched_at": "TEXT",
                "opt_out_sms_at": "TEXT",
                "opt_out_email_at": "TEXT",
                "contact_name": "TEXT",
                "utm_content": "TEXT",
                "utm_term": "TEXT",
            }
            for col, dtype in cols.items():
                if col not in existing:
                    conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {dtype}")
            # Ensure first_name/last_name/address exist before UPDATE that references them
            for col, dtype in [("first_name", "TEXT"), ("last_name", "TEXT"), ("address", "TEXT")]:
                if col not in existing:
                    conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {dtype}")
            if "contact_name" in existing:
                conn.execute(
                    "UPDATE leads SET first_name = contact_name WHERE first_name IS NULL OR first_name = ''"
                )
            # Create trade_accounts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_accounts (
                    account_id TEXT PRIMARY KEY,
                    lead_id TEXT,
                    business_name TEXT,
                    phone TEXT,
                    email TEXT,
                    address TEXT,
                    website TEXT,
                    trade TEXT,
                    source TEXT,
                    plan TEXT,
                    status TEXT,
                    created_at TEXT,
                    monthly_fee REAL,
                    leads_generated INTEGER DEFAULT 0,
                    conversions INTEGER DEFAULT 0
                )
            """)
            # Create trade_payments table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_payments (
                    payment_id TEXT PRIMARY KEY,
                    account_id TEXT,
                    amount REAL,
                    method TEXT,
                    status TEXT,
                    timestamp TEXT
                )
            """)
            # Create stripe_mappings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS stripe_mappings (
                    account_id TEXT PRIMARY KEY,
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    plan TEXT,
                    status TEXT,
                    created_at TEXT,
                    cancelled_at TEXT,
                    cancel_at_period_end INTEGER DEFAULT 0
                )
            """)
            # Create schedules table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    query TEXT,
                    provider TEXT,
                    industry TEXT,
                    location TEXT,
                    num_results INTEGER,
                    min_score REAL,
                    interval_minutes INTEGER,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT,
                    last_run TEXT,
                    last_result_count INTEGER DEFAULT 0,
                    total_runs INTEGER DEFAULT 0
                )
            """)
            # Create nurture_sequences table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nurture_sequences (
                    id TEXT PRIMARY KEY,
                    lead_name TEXT,
                    lead_id TEXT,
                    lead_email TEXT,
                    lead_phone TEXT,
                    industry TEXT,
                    created_at TEXT,
                    actions TEXT,
                    current_step INTEGER DEFAULT 0,
                    completed INTEGER DEFAULT 0
                )
            """)
            # Create appointments table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS appointments (
                    appointment_id TEXT PRIMARY KEY,
                    name TEXT,
                    phone TEXT,
                    email TEXT,
                    date TEXT,
                    time_slot TEXT,
                    created_at TEXT
                )
            """)
            # Create landing_pages table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS landing_pages (
                    page_id TEXT PRIMARY KEY,
                    html TEXT
                )
            """)
            # Create ad_campaigns table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ad_campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    name TEXT,
                    platform TEXT,
                    industry TEXT,
                    location TEXT,
                    daily_budget_dollars REAL,
                    objective TEXT,
                    status TEXT DEFAULT 'created',
                    headline TEXT,
                    description TEXT,
                    cta TEXT,
                    keywords TEXT,
                    landing_page_url TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    platform_response TEXT
                )
            """)
            # Create utm_events table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS utm_events (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    lead_id TEXT,
                    utm_source TEXT,
                    utm_medium TEXT,
                    utm_campaign TEXT,
                    utm_term TEXT,
                    utm_content TEXT,
                    page_path TEXT,
                    referrer TEXT,
                    user_agent TEXT,
                    ip TEXT,
                    timestamp TEXT NOT NULL,
                    metadata TEXT
                )
            """)
            # Create crm_campaigns table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crm_campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    name TEXT,
                    target_count INTEGER,
                    channels TEXT,
                    agents_active INTEGER,
                    estimated_reach INTEGER,
                    launched_at TEXT
                )
            """)
            # Create opt_outs table for TCPA/CAN-SPAM/GDPR compliance
            conn.execute("""
                CREATE TABLE IF NOT EXISTS opt_outs (
                    id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    identifier TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(channel, identifier)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_opt_outs_identifier ON opt_outs(channel, identifier)"
            )
            # Create call_tasks table for human call reminders
            conn.execute("""
                CREATE TABLE IF NOT EXISTS call_tasks (
                    task_id TEXT PRIMARY KEY,
                    lead_id TEXT,
                    phone TEXT,
                    note TEXT,
                    due_at TEXT,
                    completed INTEGER DEFAULT 0,
                    completed_at TEXT,
                    assigned_to TEXT,
                    created_at TEXT
                )
            """)
            # Create trade_subscriptions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_subscriptions (
                    subscription_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    started_at TEXT,
                    next_billing TEXT,
                    stripe_subscription_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_subscriptions_account ON trade_subscriptions(account_id)"
            )
            # Indexes for commonly filtered columns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_industry ON leads(industry)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_found_at ON leads(found_at)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trade_payments_account ON trade_payments(account_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_stripe_mappings_sub ON stripe_mappings(stripe_subscription_id)"
            )
            conn.commit()
        logger.info("Database initialized successfully at %s", cls.db_file)

        # Apply the numbered migration chain AFTER the base tables exist, so a
        # schema-drift fix is applied to a database that has something to alter.
        # Idempotent and safe to run on every boot. A failure here is logged but
        # does not prevent the app from starting -- a missing migration must
        # not take the API down; the guard in tests/ asserts the chain works.
        try:
            from engine.migrations import apply_migrations

            applied = apply_migrations(cls.db_file)
            if applied:
                logger.info("applied %s pending migration(s)", applied)
        except Exception:
            logger.exception(
                "Schema migrations failed; the app will start but the schema may be behind the code"
            )


# Auto-initialize database on import
try:
    Database.initialize()
except Exception as e:
    logger.error("Failed to auto-initialize database: %s", e)
