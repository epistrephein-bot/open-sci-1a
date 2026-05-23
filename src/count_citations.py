import csv
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv


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
OUTPUT_ORG_CSV_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts_organizations.csv"
OUTPUT_COUNTRY_CSV_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts_countries.csv"
OUTPUT_METADATA_TEMPLATE = OUTPUT_DIR / "{university}" / "citation_counts.metadata.json"

# Universities to process
UNIVERSITIES = ("SNS", "UNIBO", "UNIMI", "UNIPD", "UNITO", "UPO")

# Progress logging
LOG_EVERY = 100_000


# ==============================================================================
# METHODS
# ==============================================================================

def load_omid_organizations(path):
    """Load the omid -> organizations mapping from JSON."""
    print(f"Loading {path.relative_to(DATA_DIR)} ...")
    t0 = time.monotonic()
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    elapsed = time.monotonic() - t0
    print(f"  {len(data):,} entries loaded in {elapsed:.1f}s")
    return data


def get_omids_for_row(direction, citing_omid, cited_omid):
    """Return the list of omids to look up based on citation direction."""
    if direction == "inbound":
        return [citing_omid]
    elif direction == "outbound":
        return [cited_omid]
    elif direction == "internal":
        return [citing_omid, cited_omid]
    return []


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

# Load the omid -> organizations mapping (shared across all universities)
omid_orgs = load_omid_organizations(OMID_ORGANIZATIONS_JSON)

# Process each university
for university in UNIVERSITIES:
    input_csv = Path(str(INPUT_CSV_TEMPLATE).format(university=university))
    output_org_csv = Path(str(OUTPUT_ORG_CSV_TEMPLATE).format(university=university))
    output_country_csv = Path(str(OUTPUT_COUNTRY_CSV_TEMPLATE).format(university=university))
    metadata_json = Path(str(OUTPUT_METADATA_TEMPLATE).format(university=university))

    # Create university-specific output directory
    output_org_csv.parent.mkdir(parents=True, exist_ok=True)

    # Skip if output already exists
    if output_org_csv.exists():
        print(f"! output already exists for {university}, skipping: "
              f"{output_org_csv.relative_to(OUTPUT_DIR)}")
        continue

    if not input_csv.exists():
        print(f"! input CSV not found for {university}, skipping: {input_csv}")
        continue

    print(f"\nProcessing {university}")
    print(f"  Input: {input_csv.relative_to(DATA_DIR)}")

    started_at = time.monotonic()

    # (direction, org_key) -> count
    org_counts = Counter()
    # (direction, country_key) -> count
    country_counts = Counter()

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

            omids = get_omids_for_row(direction, citing_omid, cited_omid)

            for omid in omids:
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
                    org_counts[(direction, org_key)] += 1

                    country_key = (
                        org.get("country_name", ""),
                        org.get("country_code", ""),
                    )
                    country_counts[(direction, country_key)] += 1

            if rows_read % LOG_EVERY == 0:
                print(f"  [{format_elapsed(started_at)}] {rows_read:,} rows processed")

    # Write organization counts CSV (sorted by count descending within each direction)
    org_fieldnames = ["direction", "legal_name", "country_name", "country_code",
                      "ror", "openaire", "count"]
    org_rows = []
    for (direction, org_key), count in sorted(
        org_counts.items(), key=lambda x: (x[0][0], -x[1])
    ):
        legal_name, country_name, country_code, ror, openaire = org_key
        org_rows.append({
            "direction": direction,
            "legal_name": legal_name,
            "country_name": country_name,
            "country_code": country_code,
            "ror": ror,
            "openaire": openaire,
            "count": count,
        })

    with output_org_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=org_fieldnames)
        writer.writeheader()
        writer.writerows(org_rows)

    # Write country counts CSV (sorted by count descending within each direction)
    country_fieldnames = ["direction", "country_name", "country_code", "count"]
    country_rows = []
    for (direction, country_key), count in sorted(
        country_counts.items(), key=lambda x: (x[0][0], -x[1])
    ):
        country_name, country_code = country_key
        country_rows.append({
            "direction": direction,
            "country_name": country_name,
            "country_code": country_code,
            "count": count,
        })

    with output_country_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=country_fieldnames)
        writer.writeheader()
        writer.writerows(country_rows)

    # Metadata
    ended_at = datetime.now(timezone.utc)
    elapsed_seconds = round(time.monotonic() - started_at, 2)
    org_csv_size = output_org_csv.stat().st_size if output_org_csv.exists() else 0
    country_csv_size = output_country_csv.stat().st_size if output_country_csv.exists() else 0

    metadata = {
        "university": university,
        "elapsed_seconds": elapsed_seconds,
        "ended_at": ended_at.isoformat(),
        "rows_read": rows_read,
        "omids_looked_up": omids_looked_up,
        "omids_found": omids_found,
        "omids_not_mapped": omids_not_mapped,
        "unique_organizations": len(set(k for (_, k) in org_counts)),
        "unique_countries": len(set(k for (_, k) in country_counts)),
        "output_org_csv_size_bytes": org_csv_size,
        "output_org_csv_size_mb": round(org_csv_size / 1024 / 1024, 2),
        "output_country_csv_size_bytes": country_csv_size,
        "output_country_csv_size_mb": round(country_csv_size / 1024 / 1024, 2),
    }

    with metadata_json.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"  {rows_read:,} rows, {omids_found:,} omids found, "
          f"{omids_not_mapped:,} not mapped")
    print(f"  {len(org_rows):,} organization entries -> "
          f"{output_org_csv.relative_to(OUTPUT_DIR)}")
    print(f"  {len(country_rows):,} country entries -> "
          f"{output_country_csv.relative_to(OUTPUT_DIR)}")
    print(f"  Elapsed: {elapsed_seconds}s")
    print(f"  Metadata: {metadata_json.relative_to(OUTPUT_DIR)}")
