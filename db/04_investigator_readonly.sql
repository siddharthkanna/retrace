-- A login the investigator uses to read evidence. It can never change data.
CREATE ROLE investigator_ro LOGIN PASSWORD 'investigator_ro';

-- Stop any single query from running longer than five seconds.
ALTER ROLE investigator_ro SET statement_timeout = '5s';

\connect payments
GRANT SELECT ON ALL TABLES IN SCHEMA public TO investigator_ro;

\connect telemetry
GRANT SELECT ON ALL TABLES IN SCHEMA public TO investigator_ro;
