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

`DATA_PATH` in `.env` points to the external data directory (see `.env-example`). All scripts resolve paths relative to this variable. The data directory is large (~350GB) and gitignored.

Python 3.13 (see `.python-version`).

## Running Scripts

All scripts are standalone — run directly with `python src/<script>.py`. There are no tests, no build system, and no CLI arguments (except `src/oc_lookup.py` which takes an OMID as argv[1]).

Lint with: `pylint src/`

## Pipeline Architecture

Scripts are meant to run sequentially. Each stage reads the output of previous stages:

1. **`build_iris_oc_pids.py`** — Replaces the former `oc_index.py` + `iris_oc_pids.py` + `extract_unique_pids.py` three-step pipeline. Three phases in a single script:
   - Phase A: Reads IRIS-in-OC-index CSVs for all 6 universities, collects the set of needed OMIDs
   - Phase B: Streams the OpenCitations Meta tar.gz dump directly (no SQLite index, no extraction to disk), extracting DOI/PMID/ISBN/pub_date only for needed OMIDs
   - Phase C: Re-reads IRIS CSVs, resolves citing/cited metadata via in-memory dict, writes per-university `iris_oc_pids.csv` files with citation direction (inbound/outbound/internal), and runs union-find deduplication to produce `unique_pids.csv`
   - Output: per-university `iris_oc_pids/` CSVs + `unique_pids.csv`

2. **`match_organizations_countries.py`** — Builds an OpenAIRE org-id to country mapping by cross-referencing the whole OpenAIRE organization dump with the whole ROR dump. Outputs `openaire_ror_countries.json`. Country resolution prefers ROR, falls back to OpenAIRE's own country field.

3. **`resolve_organizations.py`** — The heaviest script. Four phases:
   - Phase 0: Reads `unique_pids.csv`, builds DOI/PMID lookup indexes
   - Phase 1: Streams OpenAIRE publication tars, matches DOI/PMID to OpenAIRE publication IDs
   - Phase 2: Streams OpenAIRE relation tars, collects `hasAuthorInstitution` affiliation edges
   - Phase 3: Resolves org IDs using the mapping from step 2
   - Output: `omid_organizations.json` — OMID-keyed JSON with affiliated organizations per publication
   - Supports checkpoint/resume via `_checkpoint_phase1.json` and `_checkpoint_phase2.json`

4. **`count_citations.py`** — Final aggregation. Reads per-university iris_oc_pids CSVs, streams `omid_organizations.json` (via ijson), and produces per-university counts of citing/cited organizations and countries (4 CSV files per university).

Legacy scripts (`oc_index.py`, `iris_oc_pids.py`, `extract_unique_pids.py`) are kept for reference but no longer part of the active pipeline.

## Key Conventions

- Scripts skip work if output files already exist (idempotent re-runs). Delete outputs to re-run.
- Each script writes a `.metadata.json` alongside its outputs with runtime stats (elapsed time, row counts, file sizes).
- The `sample/` directory contains small representative data files for reference.
- Debug scripts (`debug_omid.py`, `debug_count_citations.py`) trace a single OMID or university/direction/country through the full pipeline for verification. Edit the constants at the top of the file before running.
- `oc_lookup.py` is a quick CLI tool: `python src/oc_lookup.py "omid:br/..."` to query the SQLite index.

## Data Flow

```
IRIS CSV dumps (per university) + OpenCitations tar.gz dump
        │
        ▼
  build_iris_oc_pids.py ──► per-university CSVs with PIDs and direction
        │                    + unique_pids.csv
        │
        ├──► match_organizations_countries.py ──► openaire_ror_countries.json
        │           │
        │           ▼
        │    resolve_organizations.py ──► omid_organizations.json
        │           │
        └───────────┤
                    ▼
           count_citations.py ──► per-university org/country counts
```
