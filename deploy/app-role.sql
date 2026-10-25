-- Run with psql as schema owner, on the intended database, AFTER migrations.
-- Supply -v app_role=...; create its LOGIN/password separately via secret tooling.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE :"DBNAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"DBNAME" TO :"app_role";
GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT SELECT ON ALL TABLES IN SCHEMA public TO :"app_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_role";
GRANT INSERT, UPDATE ON accounts_user, inventory_person, inventory_reference, inventory_movement,
 inventory_importbatch, inventory_importpreview, inventory_legacyrow TO :"app_role";
GRANT INSERT, UPDATE ON consultation_exportsource TO :"app_role";
GRANT INSERT ON inventory_document, inventory_auditevent, inventory_locationchange,
 inventory_openingbalance, inventory_movementlinesource TO :"app_role";
GRANT INSERT, UPDATE, DELETE ON accounts_loginlimit, django_session,
 inventory_location, inventory_sector, inventory_movementline TO :"app_role";
-- Existing triggers protect confirmed lines even though draft lines are removable.
-- No ownership, superuser, CREATE, CREATEDB, CREATEROLE or ledger/document DELETE.
-- Repeat grants after migrations add tables/sequences; never migrate as this role.
