CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS route_plan (
  id SERIAL PRIMARY KEY,
  date DATE NOT NULL,
  direction VARCHAR(2) NOT NULL CHECK (direction IN ('AM','PM')),
  vehicle_id INTEGER NOT NULL,
  student_sequence INTEGER[] NOT NULL,
  eta_sequence TIMESTAMP[],
  version INTEGER DEFAULT 1,
  created_at TIMESTAMP DEFAULT NOW(),
  is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS stop_events (
  id SERIAL PRIMARY KEY,
  event_id UUID DEFAULT uuid_generate_v4(),
  ts TIMESTAMP NOT NULL,
  trip_id VARCHAR(50) NOT NULL,
  vehicle_id INTEGER NOT NULL,
  student_id INTEGER NOT NULL,
  event_type VARCHAR(20) NOT NULL CHECK (event_type IN ('ARRIVE','PICKED_UP','DEPART','MANUAL_SKIP')),
  lat DOUBLE PRECISION,
  lon DOUBLE PRECISION,
  seq_no INTEGER NOT NULL,
  processed BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  key VARCHAR(100) PRIMARY KEY,
  created_at TIMESTAMP DEFAULT NOW(),
  expires_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stop_events_trip ON stop_events(trip_id, vehicle_id, student_id);
CREATE INDEX IF NOT EXISTS idx_stop_events_ts ON stop_events(ts);
CREATE INDEX IF NOT EXISTS idx_route_plan_date ON route_plan(date, direction);

