-- Anonymized telemetry records from opt-in axor clients.
-- No PII. Raw inputs never stored. Payload is a JSON blob
-- matching AnonymizedTraceRecord schema.

CREATE TABLE IF NOT EXISTS records (
    id             BIGSERIAL PRIMARY KEY,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    client_ip_hash TEXT,                       -- sha256(ip)[:16], rate-limit bucket only
    axor_version   TEXT,
    schema_version INT NOT NULL DEFAULT 1,
    payload        JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_records_received_at ON records(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_records_signal
    ON records((payload->>'signal_chosen'));
CREATE INDEX IF NOT EXISTS idx_records_adjusted
    ON records(((payload->>'policy_adjusted')::boolean))
    WHERE (payload->>'policy_adjusted')::boolean = true;
