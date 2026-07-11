import sqlite3
import os
import json
import logging
from typing import Dict, List, Any, Optional

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
        conn = sqlite3.connect(cls.db_file)
        conn.row_factory = sqlite3.Row
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_opt_outs_identifier ON opt_outs(channel, identifier)")
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_subscriptions_account ON trade_subscriptions(account_id)")
            # Indexes for commonly filtered columns
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_source ON leads(source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_industry ON leads(industry)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leads_found_at ON leads(found_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_payments_account ON trade_payments(account_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_stripe_mappings_sub ON stripe_mappings(stripe_subscription_id)")
            conn.commit()
        logger.info("Database initialized successfully at %s", cls.db_file)

# Auto-initialize database on import
Database.initialize()
