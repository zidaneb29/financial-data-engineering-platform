-- Metadata evidence, as the authorized owner/security administrator.
SHOW WAREHOUSES LIKE 'FDEP_DEMO_WH';
SHOW DATABASES LIKE 'FDEP_DEMO_DB';
SHOW GRANTS TO ROLE FDEP_DEMO_LOADER;
SHOW GRANTS TO ROLE FDEP_DEMO_AUDITOR;
SHOW GRANTS TO USER FDEP_DEMO_INGEST;
DESC USER FDEP_DEMO_INGEST;
-- ACCOUNTADMIN can additionally inspect monitor usage and account billing.
-- Its monitoring privileges are not granted to the service user.
SHOW RESOURCE MONITORS LIKE 'FDEP_DEMO_MONITOR';
