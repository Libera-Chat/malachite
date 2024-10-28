BEGIN;

CREATE TABLE mxbl (
    id SERIAL PRIMARY KEY,
    pattern TEXT NOT NULL,
    pattern_type SMALLINT NOT NULL,
    reason TEXT NOT NULL,
    status INTEGER NOT NULL,
    added TIMESTAMP WITH TIME ZONE NOT NULL,
    added_by TEXT NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    last_hit TIMESTAMP WITH TIME ZONE
);

CREATE INDEX mxbl_pattern ON mxbl(pattern);

CREATE TABLE settings (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    value TEXT
);

COMMIT;
