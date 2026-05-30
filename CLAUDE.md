# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project maps Italian scientific citation networks. It answers: "What are the institutions and countries that either cite or are cited by the IRIS publications included in OpenCitations of 6 given Italian institutions (SNS, UNIBO, UNIMI, UNIPD, UNITO, UPO)?"

The pipeline processes ~350GB of data across multiple stages, linking IRIS institutional repositories to OpenCitations metadata, then resolving citing/cited works to their affiliated organizations and countries via OpenAIRE and ROR dumps.

## Environment Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

All scripts resolve data paths relative to `data/` inside the repo root (hardcoded as `ROOT_DIR / "data"`). The data directory is large (~350GB) and gitignored.

Python 3.13 (see `.python-version`).

## Running Scripts

All scripts are standalone — run directly with `python src/<script>.py`. There are no tests, no build system, and no CLI arguments. The `utilities/` directory contains debug and helper scripts (e.g. `debug_omid.py` for tracing a single OMID through the full pipeline).

Lint with: `pylint src/`

## Pipeline Architecture

Scripts are meant to run sequentially. Each stage reads the output of previous stages:

1. **`build_iris_oc_pids.py`** — Replaces the former `oc_index.py` + `iris_oc_pids.py` + `extract_unique_pids.py` three-step pipeline. Three phases in a single script:
   - Phase 1: Reads IRIS-in-OC-index CSVs for all 6 universities, collects the set of needed OMIDs
   - Phase 2: Streams the OpenCitations Meta tar.gz dump directly (no SQLite index, no extraction to disk), extracting DOI/PMID/ISBN/pub_date only for needed OMIDs
   - Phase 3: Re-reads IRIS CSVs, resolves citing/cited metadata via in-memory dict, writes per-university `iris_oc_pids.csv` files with citation direction (incoming/outgoing/internal), and runs union-find deduplication to produce `unique_pids.csv`
   - Output: `iris_oc_pids/{university}/iris_oc_pids.csv` + `iris_oc_pids/unique_pids.csv`

2. **`match_organizations_countries.py`** — Builds an OpenAIRE org-id to country mapping by cross-referencing the whole OpenAIRE organization dump with the whole ROR dump. Country resolution prefers ROR, falls back to OpenAIRE's own country field.
   - Output: `openaire_ror_countries/openaire_ror_countries.json`

3. **`resolve_pids_organizations.py`** — The heaviest script. Four phases:
   - Phase 0: Reads `unique_pids.csv`, builds DOI/PMID lookup indexes
   - Phase 1: Streams OpenAIRE publication tars, matches DOI/PMID to OpenAIRE publication IDs
   - Phase 2: Streams OpenAIRE relation tars, collects `hasAuthorInstitution` affiliation edges
   - Phase 3: Resolves org IDs using the mapping from step 2
   - Output: `iris_openaire_organizations/omid_organizations.json` — OMID-keyed JSON with affiliated organizations per publication
   - Supports checkpoint/resume via `_checkpoint_phase1.json` and `_checkpoint_phase2.json`

4. **`count_citations.py`** — Final aggregation. Reads per-university iris_oc_pids CSVs, streams `omid_organizations.json` (via ijson), and produces per-university counts of citing/cited organizations and countries.
   - Output: `citation_counts/{university}/` with 4 CSVs per university (org incoming, org outgoing, country incoming, country outgoing)

## Key Conventions

- Scripts skip work if output files already exist (idempotent re-runs). Delete outputs to re-run.
- Each script writes a `.metadata.json` alongside its outputs with runtime stats (elapsed time, row counts, file sizes).
- The `sample/` directory contains small representative data files for reference.

## Data Flow

```
IRIS CSV dumps (per university) + OpenCitations tar.gz dump
        │
        ▼
  build_iris_oc_pids.py ──► per-university CSVs with PIDs and direction
        │                    + unique_pids.csv
        │
        ├──► match_organizations_countries.py ──► openaire_ror_countries/
        │           │
        │           ▼
        │    resolve_pids_organizations.py ──► iris_openaire_organizations/
        │           │
        └───────────┤
                    ▼
           count_citations.py ──► citation_counts/{university}/
```
