-- ============================================================
-- DATA CONNECTOR QUERIES
-- One row per registered integration (e.g. "edms"). The consuming app
-- wires a ConnectorProvider callable under the connector's `name` at
-- startup — Verity stores the identity and non-secret config only.
-- ============================================================

-- name: insert_data_connector
INSERT INTO data_connector (name, connector_type, display_name, description, config, owner_name)
VALUES (%(name)s, %(connector_type)s, %(display_name)s, %(description)s, %(config)s, %(owner_name)s)
RETURNING id, created_at;


-- name: upsert_data_connector
-- Convenience for idempotent registration at app startup.
INSERT INTO data_connector (name, connector_type, display_name, description, config, owner_name)
VALUES (%(name)s, %(connector_type)s, %(display_name)s, %(description)s, %(config)s, %(owner_name)s)
ON CONFLICT (name) DO UPDATE
    SET connector_type = EXCLUDED.connector_type,
        display_name   = EXCLUDED.display_name,
        description    = EXCLUDED.description,
        config         = EXCLUDED.config,
        owner_name     = EXCLUDED.owner_name
RETURNING id, created_at;


-- name: get_data_connector_by_name
SELECT * FROM data_connector WHERE name = %(name)s;


-- name: get_data_connector_by_id
SELECT * FROM data_connector WHERE id = %(id)s;


-- name: list_data_connectors
SELECT * FROM data_connector ORDER BY name;


-- name: delete_data_connector
DELETE FROM data_connector WHERE id = %(id)s RETURNING id;
