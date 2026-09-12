CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE IF NOT EXISTS maritime_observations (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    position GEOGRAPHY(POINT,4326),
    payload JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS observations_position_idx ON maritime_observations USING GIST(position);
CREATE TABLE IF NOT EXISTS marine_boundaries (
    id TEXT PRIMARY KEY,
    name TEXT,
    source TEXT,
    geometry GEOMETRY(MULTIPOLYGON,4326),
    properties JSONB
);
CREATE INDEX IF NOT EXISTS marine_boundaries_geometry_idx ON marine_boundaries USING GIST(geometry);
