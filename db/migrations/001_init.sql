-- Spielfeld Bundesliga forecast schema

CREATE TABLE IF NOT EXISTS teams (
  slug text PRIMARY KEY,
  name text NOT NULL,
  short_name text,
  ol_team_id integer,
  icon_url text,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS matches (
  match_uid text PRIMARY KEY,
  ol_match_id integer UNIQUE,
  season_year integer NOT NULL,
  season_label text,
  matchday integer,
  kickoff timestamptz NOT NULL,
  home_slug text NOT NULL REFERENCES teams(slug),
  away_slug text NOT NULL REFERENCES teams(slug),
  home_goals integer,
  away_goals integer,
  result text CHECK (result IN ('H', 'D', 'A')),
  finished boolean NOT NULL DEFAULT false,
  payload jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS matches_kickoff_idx ON matches (kickoff);
CREATE INDEX IF NOT EXISTS matches_season_matchday_idx ON matches (season_year, matchday);

CREATE TABLE IF NOT EXISTS forecasts (
  match_uid text PRIMARY KEY,
  ol_match_id integer,
  season_year integer,
  matchday integer,
  kickoff timestamptz,
  home_slug text,
  away_slug text,
  home_name text,
  away_name text,
  p_home double precision,
  p_draw double precision,
  p_away double precision,
  pick text,
  drivers jsonb,
  is_current_matchday boolean DEFAULT false,
  payload jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_runs (
  id bigserial PRIMARY KEY,
  kind text NOT NULL,
  metrics jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings_log (
  id bigserial PRIMARY KEY,
  title text NOT NULL,
  body jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS player_impacts (
  id bigserial PRIMARY KEY,
  match_uid text NOT NULL,
  player_id integer NOT NULL,
  player_name text,
  team_slug text,
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS player_impacts_match_idx ON player_impacts (match_uid);
CREATE INDEX IF NOT EXISTS player_impacts_player_idx ON player_impacts (player_id);

CREATE TABLE IF NOT EXISTS track_record_snapshots (
  id bigserial PRIMARY KEY,
  summary jsonb NOT NULL,
  matches jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS players (
  player_id integer PRIMARY KEY,
  player_name text NOT NULL,
  team_slug text,
  goals integer,
  goals_120d integer,
  payload jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
