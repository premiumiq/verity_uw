#!/bin/bash
# Creates multiple databases and enables required extensions.
# Mounted as /docker-entrypoint-initdb.d/init.sh in PostgreSQL container.
#
# Reads database names from POSTGRES_MULTIPLE_DATABASES environment variable.
# Set in docker-compose.yml: POSTGRES_MULTIPLE_DATABASES: verity_db,uw_db,edms_db

set -e

# Read database names from environment variable (comma-separated)
IFS=',' read -ra DATABASES <<< "$POSTGRES_MULTIPLE_DATABASES"

for db in "${DATABASES[@]}"; do
  db=$(echo "$db" | xargs)  # trim whitespace
  echo "Creating database: $db"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE $db;
    GRANT ALL PRIVILEGES ON DATABASE $db TO $POSTGRES_USER;
EOSQL
done

# Enable extensions in verity_db (pgvector for embeddings, uuid-ossp for UUIDs)
echo "Enabling extensions in verity_db..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "verity_db" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "vector";
EOSQL

# Enable uuid-ossp in uw_db (needed for gen_random_uuid in submission tables)
echo "Enabling extensions in uw_db..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "uw_db" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOSQL

# Enable uuid-ossp in edms_db (needed for uuid_generate_v4 in document tables)
echo "Enabling extensions in edms_db..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "edms_db" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOSQL

echo "Database initialization complete: ${DATABASES[*]}"
