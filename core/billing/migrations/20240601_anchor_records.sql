-- Migration: Add blockchain anchoring tables
-- Story: REN-131 — Blockchain Anchoring Service
-- Parent: 20240501_usage_events.sql

BEGIN;

-- 1. Create the anchor_records table
CREATE TABLE IF NOT EXISTS anchor_records (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merkle_root     VARCHAR(66)    NOT NULL,
    tx_hash         VARCHAR(66)    NOT NULL UNIQUE,
    block_number    INTEGER        NOT NULL,
    entry_count     INTEGER        NOT NULL,
    anchored_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anchor_records_merkle_root
    ON anchor_records (merkle_root);

CREATE INDEX IF NOT EXISTS idx_anchor_records_anchored_at
    ON anchor_records (anchored_at);

-- 2. Add anchor_id FK column to ledger_entries
ALTER TABLE ledger_entries
    ADD COLUMN IF NOT EXISTS anchor_id UUID
        REFERENCES anchor_records(id);

CREATE INDEX IF NOT EXISTS idx_ledger_entries_anchor_id
    ON ledger_entries (anchor_id);

COMMIT;
