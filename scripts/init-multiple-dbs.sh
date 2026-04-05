#!/bin/bash
# Creates multiple databases and enables pgvector extension.
# Mounted as /docker-entrypoint-initdb.d/init.sh in PostgreSQL container.

set -e

for db in verity_db pas_db; do
  echo "Creating database: $db"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE $db;
    GRANT ALL PRIVILEGES ON DATABASE $db TO $POSTGRES_USER;
EOSQL
done

# Enable pgvector extension in verity_db
echo "Enabling pgvector in verity_db..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "verity_db" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "vector";
EOSQL

echo "Database initialization complete."
