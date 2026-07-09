-- Non-superuser application role (S1.8). RLS does not apply to superusers, so the app must NOT
-- connect as the bootstrap user. Migrations run as `alphadash` (owner); the app connects as
-- `alphadash_app` and is subject to every policy.
CREATE ROLE alphadash_app LOGIN PASSWORD 'alphadash_app_dev';
GRANT USAGE ON SCHEMA public TO alphadash_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO alphadash_app;
ALTER DEFAULT PRIVILEGES FOR ROLE alphadash IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO alphadash_app;
