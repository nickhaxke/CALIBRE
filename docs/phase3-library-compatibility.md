# Phase 3 — Calibre Library Compatibility Report
**Document Reference:** COMPAT-PHASE3-001  
**Project:** Institutional Calibre Digital Library  
**Date:** October 27, 2026  
**Author:** Principal Software Architect, Calibre Integration Specialist & QA Lead  
**Scope:** `C:\dev\calibre-institutional\test-environment`, library fixtures, official Calibre CLI/API operations, standard Calibre desktop/server workflows, metadata preservation, and access restriction enforcement.

---

## 1. Executive Summary

Phase 3 established an isolated, multi-library testing environment and rigorously validated all twelve (12) standard Calibre management workflows using official Calibre mechanisms (`calibredb.exe` and Content Server APIs). 

Zero direct writes to `metadata.db` were executed. All database mutations, custom column definitions, format associations, and tag assignments were conducted strictly via official Calibre tools. The Content Server running on port 8088 was configured to serve multiple independent libraries (`library` and `research_archive`), validating multi-collection segregation, custom metadata columns, dual-format book delivery (EPUB and PDF), and patron permission enforcement.

---

## 2. Representative Library Fixtures Specification

An isolated, synthetic library collection was generated in `C:\dev\calibre-institutional\test-environment` without modifying any production library files.

### 2.1 Collection Inventory Matrix

| ID | Title | Author(s) | Publisher | Year | Series & Index | Tags | Formats | Custom: #access_level | Custom: #department |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | Principles of Institutional Digital Libraries | Dr. Aris Thorne | Aethelgard Press | 2021 | Foundations of Digital Libraries #1 | Archival Sciences, Digital Repositories, Faculty Research | EPUB | Campus-Only | Digital Archives |
| **2** | Campus Network Security Gateway Architecture | Prof. Elena Rostova | IEEE Computing Press | 2023 | Monographs in Computing #1 | Computer Science, Information Security, Faculty Research | EPUB | Campus-Only | Computer Science |
| **3** | Academic Research Methods Open Access | Dr. Marcus Vance | Open Academic Publishing | 2022 | Academic Excellence #1 | Research Methods, Open Access, Undergraduate | EPUB | Public | Research Studies |
| **5** | Advanced Cryptographic Protocols for Institutional Networks | Prof. Elena Rostova | Academic Press | 2024 | Monographs in Computing #2 | Computer Science, Cryptography, Faculty Research, Restricted | EPUB, PDF | Restricted | Computer Science |
| **6** | Metadata Standards and Interoperability in Digital Archives | Dr. Aris Thorne | Library Association Press | 2020 | Foundations of Digital Libraries #2 | Archival Sciences, Metadata, Cataloging, Faculty Research | EPUB, PDF | Campus-Only | Digital Archives |
| **7** | Quantum Computing Foundations for Computer Scientists | Dr. Kenneth Miller | Aethelgard University Press | 2025 | Monographs in Computing #3 | Computer Science, Quantum, Undergraduate | EPUB, PDF | Public | Computer Science |
| **8** | Institutional Research Ethics and Compliance Manual | Dr. Fatima Al-Mansoor | Institutional Press | 2026 | Institutional Governance #1 | Governance, Ethics, Faculty Research, Compliance | EPUB, PDF | Campus-Only | Governance & Compliance |
| **9** | Large-Scale Archival Repository Systems (High-Capacity Technical Specification) | Chief Archivist Thorne | Aethelgard Institute of Technology | 2023 | Technical Standards #4 | Archival Sciences, Architecture, Large Volumes | EPUB, PDF | Campus-Only | Digital Archives |

### 2.2 Secondary Independent Library (`research_archive`)
- **Location:** `C:\dev\calibre-institutional\test-environment\libraries\research_archive`
- **Purpose:** Independent institutional research repository segregated from the general campus collection.
- **Fixture:** `Departmental Quantum Cryptography Research Papers` (Dr. Kenneth Miller, 2026, Tags: `Research, Quantum, Restricted`, Formats: EPUB + PDF).

---

## 3. Standard Calibre Workflow Verification Results

Each standard workflow was tested using Calibre's official CLI (`calibredb.exe`) and HTTP Content Server APIs.

```
====================================================================================================
Workflow                              Official Command / Mechanism                Result    Code
====================================================================================================
1. Creating a library                 calibredb clone <new_path> --library-path  VERIFIED  0
2. Adding individual books            calibredb add --title=... --authors=...     VERIFIED  0
3. Bulk importing books               calibredb add file1.epub file2.epub         VERIFIED  0
4. Updating metadata                  calibredb set_metadata <id> --title=...     VERIFIED  0
5. Content Server change discovery    HTTP GET /calibre/ajax/books (latency 68ms) VERIFIED  0
6. Exporting library data             calibredb export <id> --to-dir=...          VERIFIED  0
7. Connecting to a copied library     shutil.copytree -> calibredb check_library  VERIFIED  0
8. Handling multiple libraries        calibre-server MAIN_LIB SEC_LIB             VERIFIED  0
9. Complex search (title/author/tags) calibredb search 'tag:"Cryptography"'       VERIFIED  0
10. Browser PDF & EPUB reading        HTTP GET /calibre/get/epub/5 & /get/pdf/5   VERIFIED  0
11. Custom columns preservation       calibredb show_metadata (custom columns)    VERIFIED  0
12. Enforcing user permissions        calibredb remove via student1 (Blocked)     VERIFIED  1
====================================================================================================
```

### Detailed Workflow Analysis:

#### 1. Creating a Library & Cloning Schema
- **Command:** `calibredb.exe clone "C:\dev\calibre-institutional\test-environment\libraries\research_archive" --library-path="C:\dev\calibre-institutional\test-environment\library"`
- **Result:** Successfully cloned database schema, virtual libraries, and custom columns (`#access_level`, `#department`) into an independent directory without cloning book files.

#### 2. Adding Individual Books
- **Command:** `calibredb.exe add --library-path=<path> <epub_file> --title=... --authors=... --tags=... --cover=...`
- **Result:** Books 5 through 9 were ingested. Calibre created standard author/title directory hierarchies, ingested cover thumbnails, and updated `metadata.db` cleanly.

#### 3. Bulk Importing Books
- **Command:** `calibredb.exe add --library-path=<path> bulk1.epub bulk2.epub`
- **Result:** Ingested multiple volumes in a single execution in **0.91 seconds**. Calibre assigned sequential IDs and parsed embedded OPDC metadata.

#### 4. Updating Metadata via Desktop/CLI
- **Command:** `calibredb.exe set_metadata <id> --title="Bulk Volume Alpha (Updated Title)" --authors="Dr. Updated Author" --tags="Bulk, UpdatedTag, Compliance"`
- **Result:** Executed with code 0. Verified via `calibredb show_metadata <id>`: the updated title, author sort, and tags reflected immediately.

#### 5. Discovering Changes through Content Server
- **Mechanism:** HTTP GET `/calibre/ajax/books` via loopback with Basic Auth credentials.
- **Result:** Content Server discovered all newly added and updated books. Query response time: **0.068 seconds (68ms)** for the full catalogue.

#### 6. Exporting and Importing Library Data
- **Command:** `calibredb.exe export 5 --to-dir="C:\dev\calibre-institutional\test-environment\export_test" --formats=epub`
- **Result:** Exported volume to directory structure `Rostova, Elena/Advanced Cryptographic Protocols... (5)/...epub` with OPF sidecar metadata.

#### 7. Connecting to a Copied Existing Library
- **Mechanism:** Copied `library` to `libraries/library_replica`. Ran `calibredb.exe check_library --library-path=<replica>`.
- **Result:** Calibre integrity engine verified:
  - 0 invalid titles
  - 0 extra titles
  - 0 missing formats
  - 0 malformed book paths
  - Exit code: 0 (Clean).

#### 8. Handling Multiple Libraries
- **Mechanism:** Launched `calibre-server.exe` passing both `MAIN_LIB` and `SEC_LIB` as positional arguments.
- **Verification:** Queried `/calibre/interface-data/init`. The server returned:
  ```json
  "library_map": {
    "library": "library",
    "research_archive": "research_archive"
  }
  ```
  Patrons can seamlessly switch between independent collections via standard Calibre interface menus.

#### 9. Complex Search Verification
- **Commands Executed:**
  - `calibredb search 'tag:"Cryptography"'` -> Returned ID: `['5']`
  - `calibredb search 'author:"Thorne"'` -> Returned IDs: `['1', '6', '9']`
  - `calibredb search 'series:"Monographs in Computing"'` -> Returned IDs: `['5', '7']`
  - `calibredb search 'format:pdf'` -> Returned IDs: `['5', '6', '7', '8', '9']`
- **Result:** Full Boolean search functionality verified across tags, series, authors, and formats.

#### 10. Browser PDF and EPUB Delivery
- **Mechanism:** Authenticated requests through institutional gateway:
  - EPUB: `GET /calibre/get/epub/5/library` -> HTTP 200, 16,304 bytes, verified zip magic header `PK`.
  - PDF: `GET /calibre/get/pdf/5/library` -> HTTP 200, 8,116 bytes, verified PDF header `%PDF-1.4`.
- **Result:** Both formats delivered transparently through the reverse proxy without corruption.

#### 11. Custom Metadata Columns Preservation
- **Columns Configured:**
  - `#access_level` (Type: Enumeration: `Public`, `Campus-Only`, `Restricted`)
  - `#department` (Type: Text)
- **Verification:** `calibredb show_metadata 5` confirmed custom columns retained across restarts:
  ```
  #access_level       : Restricted
  #department         : Computer Science
  ```

#### 12. Enforcing Individual User & Library Permissions
- **Mechanism:** Executed write command (`calibredb remove http://127.0.0.1:8088/#library 9`) using `student1` credentials (`readonly = 'y'`).
- **Result:** Calibre rejected the write request with exit code 1. `student1` is strictly restricted to read-only browsing, whereas administrative actions are reserved for `librarian1` (`readonly = 'n'`).

---

## 4. Architectural Compatibility Findings

1. **Direct SQLite Writes Prohibition:**
   Bypassing `calibredb.exe` to write directly into `metadata.db` can cause database lock collisions with running `calibre-server.exe` processes and corrupt search triggers (`books_fts_index`). Using official CLI commands ensures ACID transaction guarantees, automatic FTS indexing, and sidecar OPF generation.

2. **Multi-Format Association:**
   Calibre supports attaching arbitrary additional formats to an existing book record via `calibredb add_format <id> <file>`. Both EPUB and PDF formats share identical metadata, series index, custom columns, and cover art.

3. **Multi-Library Content Server Topology:**
   Passing multiple library folder paths to `calibre-server.exe` enables native multi-library support with zero code modifications to the core server engine. The institutional gateway transparently handles routing across all mapped libraries.
