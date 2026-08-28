# E9 local restore evidence

Date: 2026-08-27 (America/New_York)

Scope: isolated local staging data under `.runtime`; no customer or external production data.

## PostgreSQL

- Source: PostgreSQL 18.6 at `127.0.0.1:55432`, database `mosaic`.
- Current Alembic head before accepted backup: `20260826_0013`.
- Backup: custom-format `mosaic-e10-v2.dump`.
- Backup SHA-256: `94755f4f674727f2867b966cdd296e73884ae74ece466a6945e792172113387b`.
- Restore target: explicit isolated database `mosaic_restore_e10`.
- `pg_restore --list`, clean single-transaction restore, and restored `alembic_version` check passed.

An earlier backup taken while the source database was still at `0012` was rejected by `verify-restore.ps1` because the repository head was already `0013`. The source was migrated and a new immutable backup name was used; the rejected backup was not overwritten.

## MinIO

- Server: checksum-verified official Windows MinIO binary.
- Client: checksum-verified official Windows `mc` binary.
- Source bucket: `mosaic-artifacts`.
- Restore bucket: `mosaic-artifacts-restore-e10`.
- Mirrored files: 2.
- Restored objects: 2.
- Mirror manifest count and restored recursive object count matched.

## Accepted verifier result

```json
{"minio_object_count":2,"status":"ok","postgres_migration_head":"20260826_0013","mirror_file_count":2,"backup_sha256":"94755f4f674727f2867b966cdd296e73884ae74ece466a6945e792172113387b"}
```

This evidence proves the local logical backup/restore path and object mirror/restore path. It does not prove remote disaster-recovery latency, multi-region failover, or container image execution.
