CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aiva_app') THEN
        CREATE ROLE aiva_app LOGIN PASSWORD 'aiva_app_dev_only';
    END IF;
END
$$;
GRANT CONNECT ON DATABASE aiva TO aiva_app;
