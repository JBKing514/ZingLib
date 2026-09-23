# Database migrations

`../run_migrations.sh` applies these files on every container start. Runtime
schema checks use the same migration engine, so PostgreSQL is the only source
of migration state.

## Initial release

`0001_baseline.sql` is the complete ZingLib 1.0 schema, including Web UI
accounts and sessions. It is intentionally the only migration in the initial
public history. Once 1.0 has shipped, do not edit it.

## Adding a migration

1. Add the next gapless file, beginning with `0002_lower_snake.sql`.
2. Keep one bounded, transactional change per file.
3. Never edit a migration that may already have been applied.

Filenames must match `NNNN_lower_snake.sql`. `CREATE INDEX CONCURRENTLY` is not
supported because each migration and its `schema_version` row are committed in
one transaction. The runner takes an advisory lock, refuses databases ahead of
the image, and compares normalized SHA-256 checksums to detect drift.

Before upgrading, application tables are snapshotted under
`/app/runtime/backups/`. `DB_INIT_BACKUP_KEEP` defaults to 3;
`DB_INIT_REQUIRE_BACKUP=1` makes snapshot failure abort the migration.

Useful controls: `DB_INIT_ON_START`, `DB_INIT_FAIL_HARD`,
`DB_INIT_MIGRATIONS_DIR`, `DB_INIT_BACKUP`, `DB_INIT_BACKUP_DIR`,
`DB_INIT_BACKUP_KEEP`, `DB_INIT_REQUIRE_BACKUP`, `DB_INIT_ALLOW_DOWNGRADE`, and
`DB_INIT_DRY_RUN`.
