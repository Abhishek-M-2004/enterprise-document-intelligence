-- ============================================================================
-- Production PostgreSQL Privilege & Role Initialization Script
-- ============================================================================
-- Executed on database container bootstrap by PostgreSQL superuser.
-- Establishes least-privilege boundary between schema migrations and application runtime.

\connect doc_intelligence;

-- 1. Create Dedicated Non-Superuser Application Role with NOBYPASSRLS
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'docintel_app') THEN
        CREATE ROLE docintel_app WITH 
            LOGIN 
            PASSWORD 'docintel_secure_pass_2026'
            NOSUPERUSER 
            NOCREATEDB 
            NOCREATEROLE 
            NOBYPASSRLS;
        RAISE NOTICE 'Role docintel_app created with NOBYPASSRLS.';
    ELSE
        ALTER ROLE docintel_app WITH 
            NOSUPERUSER 
            NOCREATEDB 
            NOCREATEROLE 
            NOBYPASSRLS;
        RAISE NOTICE 'Role docintel_app privileges verified.';
    END IF;
END $$;

-- 2. Schema and Database Access Permissions
GRANT CONNECT ON DATABASE doc_intelligence TO docintel_app;
GRANT USAGE ON SCHEMA public TO docintel_app;

-- 3. Grant Explicit CRUD on Existing Tables & Sequences
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO docintel_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO docintel_app;

-- 4. Automatically Grant Privileges on Future Tables Created by Migrations
ALTER DEFAULT PRIVILEGES IN SCHEMA public 
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO docintel_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public 
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO docintel_app;

-- 5. Revoke Administrative / Dangerous Functions
REVOKE CREATE ON SCHEMA public FROM docintel_app;

RAISE NOTICE 'PostgreSQL production security initialization complete.';
