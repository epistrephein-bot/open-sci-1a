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

All scripts are standalone — run directly with `python src/<script>.py`. There are no tests, no build system, and no CLI arguments. The `utilities/` directory holds throwaway debug and sampling scripts; treat them as scratch, not as part of the pipeline.

Lint with: `pylint src/`

## Pipeline Architecture

Scripts are meant to run sequentially. Each stage reads the output of previous stages:

1. **`build_iris_oc_pids.py`** — Replaces the former `oc_index.py` + `iris_oc_pids.py` + `extract_unique_pids.py` three-step pipeline. Three phases in a single script:
   - Phase 1: Reads IRIS-in-OC-index CSVs for all 6 universities, collects the set of needed OMIDs
   - Phase 2: Streams the OpenCitations Meta tar.gz dump directly (no SQLite index, no extraction to disk), extracting DOI/PMID/ISBN/pub_date only for needed OMIDs
   - Phase 3: Re-reads IRIS CSVs, resolves citing/cited metadata via in-memory dict, writes per-university `iris_oc_pids.csv` files with citation direction (incoming/outgoing/internal), and runs union-find deduplication to produce `unique_pids.csv`
   - Output: `iris_oc_pids/{university}/iris_oc_pids.csv` + `iris_oc_pids/unique_pids.csv`

2. **`match_organizations_countries.py`** — Establishes ROR as the sole authority on organization identity. Emits two files:
   - `openaire_ror_countries/ror_organizations.json` — `ror_id -> {legal_name, country_name, country_code}`, the ROR dump flattened. Every organization name and country published downstream comes from here.
   - `openaire_ror_countries/openaire_ror_map.json` — `openaire_org_id -> ror_id`, needed only because affiliation edges reference OpenAIRE org ids.
   - The `openaire_ror_countries/` folder name is retained from the previous pipeline layout for continuity, though the contents are now keyed on ROR ids.
   - An OpenAIRE org is dropped unless it resolves to exactly one ROR id. With several ROR pids, OpenAIRE's `legalName` and country are used *only* as disambiguators to pick among them — matching ROR's display name, then any name ROR knows, then ignoring a leading article, with ties broken toward ROR's active record and then OpenAIRE's country. If nothing singles one out, the org is dropped as ambiguous. See `resolve_ror_id()`.
   - Organizations without a ROR id are excluded entirely (~325k of 448k rows, but only ~6-9% of citation counts — the excluded mass is long-tail `pending_org_::` noise).

3. **`resolve_pids_organizations.py`** — The heaviest script. Four phases:
   - Phase 0: Reads `unique_pids.csv`, builds DOI/PMID lookup indexes
   - Phase 1: Streams OpenAIRE publication tars, matches DOI/PMID to OpenAIRE publication IDs
   - Phase 2: Streams OpenAIRE relation tars, collects `hasAuthorInstitution` affiliation edges
   - Phase 3: Two-hop resolution of org IDs — OpenAIRE org id → ROR id → ROR record. Unresolvable orgs are dropped; organizations are deduplicated on ROR id.
   - Output: `iris_openaire_organizations/omid_organizations.json` — OMID-keyed JSON with affiliated organizations per publication
   - Supports checkpoint/resume via `_checkpoint_phase1.json` and `_checkpoint_phase2.json`

4. **`count_citations.py`** — Final aggregation. Reads per-university iris_oc_pids CSVs, streams `omid_organizations.json` (via ijson), and produces per-university counts of citing/cited organizations and countries. Organizations are keyed on ROR id throughout, so no name-based merging is needed.
   - Output: `citation_counts/{university}/` with 4 CSVs per university (org incoming, org outgoing, country incoming, country outgoing)
   - Organization CSV columns: `legal_name,country_name,country_code,ror,count`. There is no `openaire` column — OpenAIRE ids are not an organization's identity and are never published.

### Additional scripts

Not part of the four-stage flow, but they read its outputs and must be re-run alongside `count_citations.py`:

- **`count_citations_annualized.py`** — same aggregation split into year blocks. Shares `dedup_org_list()` and `write_org_csv()` with `count_citations.py`; keep the two in sync. Output: `citation_counts_annualized/{university}/{block}/`
- **`top_cited.py`** — ranks the most-cited OMIDs per university. Reads only `iris_oc_pids/`, so it is unaffected by organization-resolution changes. Output: `top_cited/`

## Key Conventions

- Scripts skip work if output files already exist (idempotent re-runs). Delete outputs to re-run.
- Each script writes a `.metadata.json` alongside its outputs with runtime stats (elapsed time, row counts, file sizes).
- The `sample/` directory contains small representative data files for reference.

### ROR is the sole authority on organization identity

This invariant was violated once and produced the `Harvard University Press` bug, where every Harvard affiliation was published under its publishing house. Preserve it:

- `legal_name`, `country_name`, `country_code` and `ror` must originate **only** from `ror_organizations.json`. There is exactly one assignment, in `build_ror_organizations()`. Never add an `or org.get("legalName")` style fallback — that was the original defect.
- OpenAIRE's `legalName` and `country` may be read **only** inside `resolve_ror_id()`, to choose between competing ROR candidates. They must never reach an output field.
- Organizations are identified and deduplicated by ROR id, never by name. Name-based merging conflates distinct entities that share a display name — roughly 1,000 ROR records do.
- An organization that cannot be resolved to exactly one ROR id is dropped entirely, never emitted with a partial or fallback name.
- Errors already present in OpenAIRE are inherited, not corrected. The pipeline's job is to carry OpenAIRE's assertions faithfully onto ROR identities, not to second-guess them.

## Data Flow

```
IRIS CSV dumps (per university) + OpenCitations tar.gz dump
        │
        ▼
  build_iris_oc_pids.py ──► per-university CSVs with PIDs and direction
        │                    + unique_pids.csv
        │
        ├──► match_organizations_countries.py ──► openaire_ror_countries/
        │           │                              ror_organizations.json
        │           │                              openaire_ror_map.json
        │           ▼
        │    resolve_pids_organizations.py ──► iris_openaire_organizations/
        │           │
        └───────────┤
                    ├──► count_citations.py ──────────► citation_counts/{university}/
                    └──► count_citations_annualized.py ► citation_counts_annualized/{university}/{block}/
```

`top_cited.py` runs off `iris_oc_pids/` alone and is not part of this chain.
