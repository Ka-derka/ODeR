# Saved-data compatibility

ODeR treats user configuration and working indexes differently, but never silently downgrades either one.

## JSON state

Settings, profiles, the download queue, favorites, package history, and per-directory crawl state use a versioned envelope:

```json
{
  "format": "oder-state",
  "kind": "settings",
  "schema_version": 1,
  "written_by": "1.1.0-alpha.1",
  "data": {}
}
```

Each state kind has an independent integer schema. ODeR upgrades older schemas step by step and writes the migrated result atomically while retaining the previous file as `.bak`. State from pre-0.20 releases is treated as schema 0. ODeR 0.21 and 1.0 upgrade the download queue to schema 2 by pinning each existing item's previous relative destination; the other state kinds remain at schema 1.

ODeR 1.1 Alpha 1 adds optional presentation metadata to each profile without changing the profiles-state schema. ODeR 1.0 preserves these unknown profile fields when loading and saving its existing data, while `.oder` packages remain at format version 1 and profile schema version 1.

If a file uses a newer schema, startup stops before the main window or background work can overwrite it. Installing a newer ODeR release is the recovery path. Syntax errors and invalid structures instead use the last-known-good backup; damaged files are preserved for diagnosis when possible.

## SQLite directory caches

Each cache records its schema in both SQLite `user_version` and ODeR metadata. Older supported schemas are upgraded in place. A newer schema is refused and is never recreated as an empty index.

Corrupt caches are derived data, so ODeR preserves the damaged database and creates a rebuildable empty cache. Full crawls and hosted `.oder` replacements first create a consistent checkpoint. The checkpoint is committed only after the complete new index and change snapshot succeed; stopping, validation failure, or a process interruption restores the last complete index.

Resume, incremental, single-folder, and grow operations remain progressive by design. Their completed folders are committed so useful work can continue after a stop.

## Compatibility policy toward 1.0

- Saved-state and `.oder` schema versions change only for incompatible representation changes.
- Unknown newer schemas are refused rather than guessed at or downgraded.
- Migrations are explicit and covered by tests using legacy and future-version fixtures.
- Release metadata, Windows builds, and canonical stable or prerelease SemVer tags are checked automatically.
- The 1.0 line will retain readers or documented migration paths for every schema published as stable before 1.0 where safe migration is possible.
