import csv
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import ijson


# ==============================================================================
# ENVIRONMENT
# ==============================================================================

ROOT_DIR = Path(__file__).resolve().parent.parent

load_dotenv(ROOT_DIR / ".env")
DATA_PATH = os.environ.get("DATA_PATH")

if not DATA_PATH:
    raise RuntimeError("Missing DATA_PATH environment variable")


# ==============================================================================
# CONSTANTS AND CONFIGURATION
# ==============================================================================

# Paths and directories
DATA_DIR = Path(DATA_PATH)
IRIS_OC_PIDS_DIR = DATA_DIR / "iris_oc_pids"
OMID_ORGANIZATIONS_JSON = DATA_DIR / "openaire_organizations" / "omid_organizations.json"
OUTPUT_DIR = DATA_DIR / "citation_counts"

# File templates
INPUT_CSV_TEMPLATE = IRIS_OC_PIDS_DIR / "{university}" / "iris_oc_pids.csv"
OUTPUT_ORG_INBOUND_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts_organizations_inbound.csv"
OUTPUT_ORG_OUTBOUND_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts_organizations_outbound.csv"
OUTPUT_COUNTRY_INBOUND_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts_countries_inbound.csv"
OUTPUT_COUNTRY_OUTBOUND_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts_countries_outbound.csv"
OUTPUT_METADATA_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts.metadata.json"

# Universities to process
UNIVERSITIES = ("SNS", "UNIBO", "UNIMI", "UNIPD", "UNITO", "UPO")

# Progress logging
LOG_EVERY = 100_000


# ==============================================================================
# METHODS
# ==============================================================================

def collect_needed_omids(universities):
    """Scan all iris_oc_pids CSVs and return the set of omids we need to look up."""
    needed = set()
    for university in universities:
        input_csv = Path(str(INPUT_CSV_TEMPLATE).format(university=university))
        output_check = Path(str(OUTPUT_ORG_INBOUND_TEMPLATE).format(university=university))
        if output_check.exists() or not input_csv.exists():
            continue
        print(f"  Scanning {input_csv.relative_to(DATA_DIR)} ...")
        with input_csv.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                direction = row.get("direction", "").strip()
                citing = row.get("citing_omid", "").strip()
                cited = row.get("cited_omid", "").strip()
                if direction == "inbound":
                    needed.add(citing)
                elif direction == "outbound":
                    needed.add(cited)
                elif direction == "internal":
                    needed.add(citing)
                    needed.add(cited)
    return needed


def load_omid_organizations(path, needed_omids):
    """Stream omid_organizations.json with ijson, keeping only needed entries."""
    print(f"Streaming {path.relative_to(DATA_DIR)} (filtering {len(needed_omids):,} omids) ...")
    t0 = time.monotonic()
    data = {}
    scanned = 0
    with path.open("rb") as fh:
        for omid, entry in ijson.kvitems(fh, ""):
            scanned += 1
            if scanned % 1_000_000 == 0:
                print(f"  ...{scanned:,} entries scanned, {len(data):,} kept | "
                      f"{format_elapsed(t0)}")
            if omid in needed_omids:
                data[omid] = entry
    elapsed = time.monotonic() - t0
    print(f"  {scanned:,} entries scanned, {len(data):,} kept in {format_elapsed(t0)}")
    return data


def get_omids_by_direction(direction, citing_omid, cited_omid):
    """Return (inbound_omids, outbound_omids) to look up based on citation direction.

    For internal citations: cited omid goes to inbound, citing omid goes to outbound.
    """
    if direction == "inbound":
        return [citing_omid], []
    elif direction == "outbound":
        return [], [cited_omid]
    elif direction == "internal":
        return [cited_omid], [citing_omid]
    return [], []


def format_elapsed(t0):
    """Format elapsed time since t0 (monotonic) as HhMMmSSs."""
    m, s = divmod(int(time.monotonic() - t0), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


# ==============================================================================
# RUNTIME
# ==============================================================================

# Create output directory
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Phase 1: collect the set of omids we actually need across all universities
print("=" * 70)
print("Phase 1 -- collecting needed omids from all CSVs")
print("=" * 70)
needed_omids = collect_needed_omids(UNIVERSITIES)
print(f"  {len(needed_omids):,} unique omids to look up")

if not needed_omids:
    print("  Nothing to do.")
    raise SystemExit(0)

# Phase 2: stream the large JSON, keeping only needed entries
print()
print("=" * 70)
print("Phase 2 -- streaming omid_organizations.json")
print("=" * 70)
omid_orgs = load_omid_organizations(OMID_ORGANIZATIONS_JSON, needed_omids)

# Phase 3: count citations per university
print()
print("=" * 70)
print("Phase 3 -- counting citations")
print("=" * 70)

# Process each university
for university in UNIVERSITIES:
    input_csv = Path(str(INPUT_CSV_TEMPLATE).format(university=university))
    output_org_inbound = Path(str(OUTPUT_ORG_INBOUND_TEMPLATE).format(university=university))
    output_org_outbound = Path(str(OUTPUT_ORG_OUTBOUND_TEMPLATE).format(university=university))
    output_country_inbound = Path(str(OUTPUT_COUNTRY_INBOUND_TEMPLATE).format(university=university))
    output_country_outbound = Path(str(OUTPUT_COUNTRY_OUTBOUND_TEMPLATE).format(university=university))
    metadata_json = Path(str(OUTPUT_METADATA_TEMPLATE).format(university=university))

    # Create university-specific output directory
    output_org_inbound.parent.mkdir(parents=True, exist_ok=True)

    # Skip if output already exists
    if output_org_inbound.exists():
        print(f"! output already exists for {university}, skipping: "
              f"{output_org_inbound.relative_to(OUTPUT_DIR)}")
        continue

    if not input_csv.exists():
        print(f"! input CSV not found for {university}, skipping: {input_csv}")
        continue

    print(f"\nProcessing {university}")
    print(f"  Input: {input_csv.relative_to(DATA_DIR)}")

    started_at = time.monotonic()

    # org_key -> count, separate counters for inbound and outbound
    org_inbound = Counter()
    org_outbound = Counter()
    country_inbound = Counter()
    country_outbound = Counter()

    rows_read = 0
    omids_looked_up = 0
    omids_found = 0
    omids_not_mapped = 0

    with input_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        for row in reader:
            rows_read += 1

            direction = row.get("direction", "").strip()
            citing_omid = row.get("citing_omid", "").strip()
            cited_omid = row.get("cited_omid", "").strip()

            inbound_omids, outbound_omids = get_omids_by_direction(
                direction, citing_omid, cited_omid
            )

            for omid_list, org_counter, country_counter in (
                (inbound_omids, org_inbound, country_inbound),
                (outbound_omids, org_outbound, country_outbound),
            ):
                for omid in omid_list:
                    omids_looked_up += 1

                    entry = omid_orgs.get(omid)
                    if entry is None:
                        omids_not_mapped += 1
                        continue

                    organizations = entry.get("organizations", [])
                    if not organizations:
                        omids_not_mapped += 1
                        continue

                    omids_found += 1

                    for org in organizations:
                        org_key = (
                            org.get("legal_name", ""),
                            org.get("country_name", ""),
                            org.get("country_code", ""),
                            org.get("ror") or "",
                            org.get("openaire", ""),
                        )
                        org_counter[org_key] += 1

                        country_key = (
                            org.get("country_name", ""),
                            org.get("country_code", ""),
                        )
                        country_counter[country_key] += 1

            if rows_read % LOG_EVERY == 0:
                print(f"  [{format_elapsed(started_at)}] {rows_read:,} rows processed")

    # Write organization and country CSVs
    org_fieldnames = ["legal_name", "country_name", "country_code",
                      "ror", "openaire", "count"]
    country_fieldnames = ["country_name", "country_code", "count"]

    for counter, path, fieldnames, unpack in (
        (org_inbound, output_org_inbound, org_fieldnames, True),
        (org_outbound, output_org_outbound, org_fieldnames, True),
        (country_inbound, output_country_inbound, country_fieldnames, False),
        (country_outbound, output_country_outbound, country_fieldnames, False),
    ):
        rows = []
        for key, count in sorted(counter.items(), key=lambda x: -x[1]):
            if unpack:
                legal_name, country_name, country_code, ror, openaire = key
                rows.append({
                    "legal_name": legal_name,
                    "country_name": country_name,
                    "country_code": country_code,
                    "ror": ror,
                    "openaire": openaire,
                    "count": count,
                })
            else:
                country_name, country_code = key
                rows.append({
                    "country_name": country_name,
                    "country_code": country_code,
                    "count": count,
                })

        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    # Metadata
    ended_at = datetime.now(timezone.utc)
    elapsed_seconds = round(time.monotonic() - started_at, 2)

    def file_size(p):
        return p.stat().st_size if p.exists() else 0

    metadata = {
        "university": university,
        "elapsed_seconds": elapsed_seconds,
        "ended_at": ended_at.isoformat(),
        "rows_read": rows_read,
        "omids_looked_up": omids_looked_up,
        "omids_found": omids_found,
        "omids_not_mapped": omids_not_mapped,
        "unique_organizations_inbound": len(org_inbound),
        "unique_organizations_outbound": len(org_outbound),
        "unique_countries_inbound": len(country_inbound),
        "unique_countries_outbound": len(country_outbound),
        "output_org_inbound_csv_size_bytes": file_size(output_org_inbound),
        "output_org_outbound_csv_size_bytes": file_size(output_org_outbound),
        "output_country_inbound_csv_size_bytes": file_size(output_country_inbound),
        "output_country_outbound_csv_size_bytes": file_size(output_country_outbound),
    }

    with metadata_json.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"  {rows_read:,} rows, {omids_found:,} omids found, "
          f"{omids_not_mapped:,} not mapped")
    print(f"  Inbound:  {len(org_inbound):,} orgs, {len(country_inbound):,} countries")
    print(f"  Outbound: {len(org_outbound):,} orgs, {len(country_outbound):,} countries")
    print(f"  Elapsed: {elapsed_seconds}s")
