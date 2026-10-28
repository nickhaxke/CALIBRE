# Phase 4 — Configuration Data Model & Persistence Specification
**Document Reference:** DATA-MODEL-PHASE4-001  
**Project:** Calibre Institutional Digital Library  
**Date:** October 27, 2026  
**Author:** Principal Software Architect & Database Engineer  
**Scope:** SQLite configuration store (`institutional_config.sqlite`), entity relationship design, migrations engine, transactional guarantees, backup strategy, and environment resolution.

---

## 1. Overview & Architectural Principles

The Institutional Calibre Digital Library requires an autonomous, self-contained configuration store that decouples runtime institutional state from static code checkouts and prevents unauthorized tampering.

### Core Design Rules:
1. **Zero Duplicate Calibre Storage:** Calibre's book records (`metadata.db`) and core user accounts (`server-users.sqlite`) are never duplicated. The configuration model manages institutional metadata, library registrations, administrative settings, and audit trails.
2. **Outside Source-Tree Persistence:** Production configuration is stored in the Windows Application Data hierarchy (`%APPDATA%\CalibreInstitutional\institutional_config.sqlite`). An environment variable (`CALIBRE_INSTITUTIONAL_CONFIG_DIR`) provides clean development isolation.
3. **Transactional Guarantees:** All schema mutations, settings updates, and audit logging execute within atomic transactions.
4. **Versioned Migrations:** Tables and indexes are managed through an append-only `schema_migrations` tracking table with automatic backups prior to schema evolution.

---

## 2. Entity Relational Schema Specification (v1)

```
+----------------------------------------------------------------------------------------------------+
|                                    INSTITUTIONAL CONFIG STORE                                      |
+----------------------------------------------------------------------------------------------------+
|  institution_settings           libraries                      system_config                       |
|  --------------------           ---------                      -------------                       |
|  id (PK, =1)                    library_id (PK, text)          key (PK, text)                      |
|  institution_name               display_name                   value                               |
|  short_name                     path (UNIQUE)                  updated_at                          |
|  logo_path                      is_active (0/1)                                                    |
|  library_title                  is_default (0/1)               audit_records                       |
|  motto                          access_policy                  -------------                       |
|  contact_email                  created_at                     id (PK, autoinc)                    |
|  contact_phone                  updated_at                     timestamp                           |
|  default_language                                              actor                               |
|  primary_color                  institutional_user_profiles    action                              |
|  accent_color                   ---------------------------    details (JSON)                      |
|  accent_gold                    username (PK, text)                                                |
|  updated_at                     role                           schema_migrations                   |
|                                 display_name                   -----------------                   |
|                                 department                     version (PK, int)                   |
|                                 created_at                     applied_at                          |
|                                 updated_at                                                         |
+----------------------------------------------------------------------------------------------------+
```

### 2.1 Table Definitions

#### 1. `institution_settings`
Stores branding, visual identity, and contact information. Constrained to a single singleton record (`id = 1`).
```sql
CREATE TABLE institution_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    institution_name TEXT NOT NULL,
    short_name TEXT NOT NULL,
    logo_path TEXT,
    library_title TEXT NOT NULL,
    motto TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    default_language TEXT DEFAULT 'en',
    primary_color TEXT DEFAULT '#0f172a',
    accent_color TEXT DEFAULT '#2563eb',
    accent_gold TEXT DEFAULT '#d97706',
    updated_at TEXT NOT NULL
);
```

#### 2. `libraries`
Maintains connected Calibre library registrations, folder paths, active status, and default designation.
```sql
CREATE TABLE libraries (
    library_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    access_policy TEXT NOT NULL DEFAULT 'public',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### 3. `system_config`
Key-value configuration for runtime environment flags, ports, setup completion, and binary locations.
```sql
CREATE TABLE system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### 4. `institutional_user_profiles`
Enriches upstream Calibre user accounts with institutional identity (academic role, display name, department).
```sql
CREATE TABLE institutional_user_profiles (
    username TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    display_name TEXT NOT NULL,
    department TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### 5. `audit_records`
Immutable chronological log tracking administrative actions and configuration changes.
```sql
CREATE TABLE audit_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT
);
```

#### 6. `schema_migrations`
Tracks applied database schema versions.
```sql
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

---

## 3. Directory & Environment Resolution

`ConfigManager.get_config_directory()` resolves configuration storage using an institutional hierarchy:
1. **Explicit Environment Variable:** If `CALIBRE_INSTITUTIONAL_CONFIG_DIR` is set, use this directory.
2. **Local Development Fallback:** If `test-environment/config` exists within the workspace, use it for isolated dev testing.
3. **Production Standard:** Uses Windows `%APPDATA%\CalibreInstitutional`.

Database file: `<CONFIG_DIR>/institutional_config.sqlite`.

---

## 4. Backup & Disaster Recovery Architecture

Before any schema migration or major administrative update, `ConfigManager.backup_database()` generates a timestamped copy:
`<CONFIG_DIR>/backups/institutional_config_YYYYMMDD_HHMMSS.sqlite.bak`

Database connections enforce `PRAGMA foreign_keys = ON`, `PRAGMA journal_mode = WAL` (where appropriate), and transaction rollbacks on failure.

---

## 5. Verification & Unit Test Results

The configuration data model was validated through `tests/test_config_manager.py`:
- `test_01_schema_initialization_and_migration`: **PASS** (all 6 tables & v1 migration verified)
- `test_02_institution_settings_crud`: **PASS** (singleton updates, fields, audit trail)
- `test_03_library_configuration`: **PASS** (registration, default toggling, non-destructive removal)
- `test_04_system_config_and_setup_flag`: **PASS** (key-value storage, setup_completed state)
- `test_05_institutional_user_profiles`: **PASS** (profile mappings, fallbacks)
- `test_06_database_backup`: **PASS** (timestamped snapshot verified)

**Pass Rate:** **6/6 Tests PASSED (100%)** in 0.353 seconds.
