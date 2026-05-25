import csv
import json
import os
import sys
import time
from collections import Counter
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
# PARAMETERS — change these before running
# ==============================================================================

UNIVERSITY = "UNIMI"
DIRECTION = "outbound"       # "inbound" or "outbound"
COUNTRY_NAME = "Australia"

VALID_UNIVERSITIES = ("SNS", "UNIBO", "UNIMI", "UNIPD", "UNITO", "UPO")
VALID_DIRECTIONS = ("inbound", "outbound")


# ==============================================================================
# CONSTANTS AND CONFIGURATION
# ==============================================================================

DATA_DIR = Path(DATA_PATH)
IRIS_OC_PIDS_DIR = DATA_DIR / "iris_oc_pids"
OMID_ORGANIZATIONS_JSON = DATA_DIR / "openaire_organizations" / "omid_organizations.json"

INPUT_CSV = IRIS_OC_PIDS_DIR / UNIVERSITY / "iris_oc_pids.csv"

# Progress logging
LOG_EVERY_CSV = 100_000
LOG_EVERY_JSON = 1_000_000


# ==============================================================================
# METHODS
# ==============================================================================

def format_elapsed(t0):
    """Format elapsed time since t0 (monotonic) as HhMMmSSs."""
    m, s = divmod(int(time.monotonic() - t0), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


# ==============================================================================
# VALIDATION
# ==============================================================================

if UNIVERSITY not in VALID_UNIVERSITIES:
    print(f"Invalid UNIVERSITY: {UNIVERSITY}")
    print(f"Valid values: {VALID_UNIVERSITIES}")
    sys.exit(1)

if DIRECTION not in VALID_DIRECTIONS:
    print(f"Invalid DIRECTION: {DIRECTION}")
    print(f"Valid values: {VALID_DIRECTIONS}")
    sys.exit(1)

if not INPUT_CSV.exists():
    print(f"Input CSV not found: {INPUT_CSV}")
    sys.exit(1)

print("=" * 70)
print(f"Debug count_citations")
print(f"  University: {UNIVERSITY}")
print(f"  Direction:  {DIRECTION}")
print(f"  Country:    {COUNTRY_NAME}")
print("=" * 70)


# ==============================================================================
# Step 1 — scan CSV, collect omids for the requested direction
# ==============================================================================

print(f"\n--- Step 1: scanning {INPUT_CSV.relative_to(DATA_DIR)} ---")

omid_counts = Counter()
rows_read = 0
t0 = time.monotonic()

with INPUT_CSV.open("r", encoding="utf-8", newline="") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        rows_read += 1

        direction = row.get("direction", "").strip()
        citing = row.get("citing_omid", "").strip()
        cited = row.get("cited_omid", "").strip()

        if direction == DIRECTION:
            omid = citing if DIRECTION == "inbound" else cited
            omid_counts[omid] += 1
        elif direction == "internal":
            omid = cited if DIRECTION == "inbound" else citing
            omid_counts[omid] += 1

        if rows_read % LOG_EVERY_CSV == 0:
            print(f"  {rows_read:,} rows | {format_elapsed(t0)}")

print(f"  {rows_read:,} rows read")
print(f"  {len(omid_counts):,} unique omids for {DIRECTION} direction")
print(f"  {sum(omid_counts.values()):,} total {DIRECTION} citation events")


# ==============================================================================
# Step 2 — stream JSON, count only orgs matching the target country
# ==============================================================================

print(f"\n--- Step 2: streaming {OMID_ORGANIZATIONS_JSON.relative_to(DATA_DIR)} ---")

country_total = 0
org_counts = Counter()
matched_omids = 0
example_rows = []

scanned = 0
t0 = time.monotonic()

with OMID_ORGANIZATIONS_JSON.open("rb") as fh:
    for omid, entry in ijson.kvitems(fh, ""):
        scanned += 1
        if scanned % LOG_EVERY_JSON == 0:
            print(f"  ...{scanned:,} entries scanned, {matched_omids:,} matched | "
                  f"{format_elapsed(t0)}")

        if omid not in omid_counts:
            continue

        multiplier = omid_counts[omid]
        organizations = entry.get("organizations", [])
        if not organizations:
            continue

        matched_omids += 1
        omid_contributed = False

        for org in organizations:
            if org.get("country_name", "") != COUNTRY_NAME:
                continue

            omid_contributed = True
            org_key = (
                org.get("legal_name", ""),
                org.get("country_code", ""),
                org.get("ror") or "",
                org.get("openaire", ""),
            )
            org_counts[org_key] += multiplier
            country_total += multiplier

            if len(example_rows) < 10:
                example_rows.append({
                    "omid": omid,
                    "multiplier": multiplier,
                    "legal_name": org.get("legal_name", ""),
                    "country_code": org.get("country_code", ""),
                    "ror": org.get("ror") or "",
                    "openaire": org.get("openaire", ""),
                })

print(f"  {scanned:,} entries scanned, {matched_omids:,} omids matched | "
      f"{format_elapsed(t0)}")


# ==============================================================================
# Step 3 — results
# ==============================================================================

print()
print("=" * 70)
print(f"Results: {UNIVERSITY} / {DIRECTION} / {COUNTRY_NAME}")
print("=" * 70)

print(f"\n  Country total: {country_total:,}")
print(f"  Distinct organizations from {COUNTRY_NAME}: {len(org_counts):,}")

print(f"\n  Top 20 organizations:")
for i, (org_key, count) in enumerate(
    sorted(org_counts.items(), key=lambda x: -x[1])[:20]
):
    legal_name, country_code, ror, openaire = org_key
    print(f"    {i + 1:3d}. {count:>8,}  {legal_name}  ({openaire})")

if example_rows:
    print(f"\n  First {len(example_rows)} example matches:")
    for ex in example_rows:
        print(f"    {ex['omid']} (x{ex['multiplier']}) -> "
              f"{ex['legal_name']} ({ex['openaire']})")

# Compare with existing output if available
output_csv = (
    DATA_DIR / "citation_counts" / UNIVERSITY /
    f"citation_counts_countries_{DIRECTION}.csv"
)
if output_csv.exists():
    print(f"\n  Comparing with {output_csv.relative_to(DATA_DIR)} ...")
    with output_csv.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("country_name") == COUNTRY_NAME:
                csv_count = int(row["count"])
                match = "MATCH" if csv_count == country_total else "MISMATCH"
                print(f"    CSV count: {csv_count:,}  |  debug count: {country_total:,}  |  {match}")
                break
        else:
            print(f"    Country '{COUNTRY_NAME}' not found in CSV")
else:
    print(f"\n  (no existing output CSV to compare with)")
