import json
import gzip
import sys
import time
import tarfile
from datetime import datetime, timezone
from pathlib import Path

# ==============================================================================
# CONSTANTS AND CONFIGURATION
# ==============================================================================

# Paths and directories
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

DUMPS_DIR = DATA_DIR / "dumps"
OPENAIRE_TAR = DUMPS_DIR / "openaire" / "organization.tar"
ROR_JSON = DUMPS_DIR / "ror" / "v2.7-2026-05-12-ror-data.json"

OUTPUT_DIR = DATA_DIR / "ror_organizations"
OUTPUT_ORGANIZATIONS = OUTPUT_DIR / "ror_organizations.json"
OUTPUT_OPENAIRE_MAP = OUTPUT_DIR / "openaire_ror_map.json"
OUTPUT_METADATA = OUTPUT_DIR / "ror_organizations.metadata.json"

# Progress logging
LOG_EVERY = 50_000


# ==============================================================================
# METHODS
# ==============================================================================

def ror_display_name(names):
    """Return the ror_display name from a ROR names list, or None."""
    for name in names:
        if "ror_display" in (name.get("types") or []):
            return name.get("value")
    return None


def build_ror_organizations(ror_path):
    """Read ror.json and return {ror_id: {legal_name, country_name, country_code}}.

    This is the authority file: every organization name, id and country published
    downstream comes from here and nowhere else.
    """
    with open(ror_path, "r", encoding="utf-8") as path:
        ror_data = json.load(path)

    organizations = {}
    for record in ror_data:
        record_ror_id = record.get("id", "")
        display_name = ror_display_name(record.get("names", []))
        locations = record.get("locations", [])

        # An organization with no name or no location cannot be reported on
        if not record_ror_id or not display_name or not locations:
            continue

        geo = locations[0].get("geonames_details", {})
        organizations[record_ror_id] = {
            "legal_name": display_name,
            "country_name": geo.get("country_name", ""),
            "country_code": geo.get("country_code", ""),
        }

    return organizations


def iter_openaire_orgs(tar_path):
    """Yield every JSON object from a tar archive of json.gz files.
    Each .gz member contains one JSON-Lines document (one record per line).
    """
    with tarfile.open(tar_path, "r") as tar:
        for member in tar:
            if not member.name.endswith(".gz"):
                continue

            gz_file = tar.extractfile(member)
            if gz_file is None:
                continue

            with gzip.open(gz_file, "rt", encoding="utf-8") as lines:
                for line in lines:
                    line = line.strip()
                    if line:
                        yield json.loads(line)


def extract_ror_ids(pids, known_ror_ids):
    """Return every ROR id on an OpenAIRE organization that resolves in the ROR dump."""
    return [
        pid["value"] for pid in pids
        if pid.get("scheme") == "ROR" and pid.get("value") in known_ror_ids
    ]


def resolve_ror_id(ror_ids, legal_name, organizations):
    """Pick the single ROR id that identifies an OpenAIRE organization, or None.

    OpenAIRE frequently attaches several ROR ids to one organization record — its
    own uncertainty about which entity the record is, not a list of affiliations.
    Harvard University carries both `Harvard University` and `Harvard University
    Press`; one bucket carries 32 ROR ids including the US Air Force and Dell.
    Taking the first one silently renames the organization, so:

        - exactly one ROR id     -> use it
        - several ROR ids        -> use the one whose ROR name is OpenAIRE's own
                                    legalName, if exactly one qualifies
        - otherwise              -> ambiguous, drop the organization

    legalName is only ever a disambiguator here. Every value published downstream
    still comes from the ROR record.
    """
    if not ror_ids:
        return None

    if len(ror_ids) == 1:
        return ror_ids[0]

    wanted = (legal_name or "").strip().lower()
    if not wanted:
        return None

    matches = [
        ror_id for ror_id in ror_ids
        if organizations[ror_id]["legal_name"].lower() == wanted
    ]

    return matches[0] if len(matches) == 1 else None


# ==============================================================================
# RUNTIME
# ==============================================================================

# Create output directory if it doesn't exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Skip if output JSON already exists
if OUTPUT_ORGANIZATIONS.exists():
    print(f"! output JSON already exists, skipping: {OUTPUT_ORGANIZATIONS.relative_to(DATA_DIR)}")
    sys.exit(0)

print("Building ROR organization index…")
ror_organizations = build_ror_organizations(ROR_JSON)
known_ror_ids = set(ror_organizations)
print(f"  {len(ror_organizations):,} ROR entries loaded from {ROR_JSON.relative_to(DATA_DIR)}")

print(f"Scanning OpenAIRE organizations from {OPENAIRE_TAR.relative_to(DATA_DIR)}…")

# Start monotonic timer
started_at = time.monotonic()

# Initialize counters
openaire_ror_map = {}
rows_read = 0
rows_single_ror = 0
rows_resolved_by_name = 0
rows_ambiguous_ror = 0
rows_no_ror = 0

for org in iter_openaire_orgs(OPENAIRE_TAR):
    rows_read += 1

    ror_ids = extract_ror_ids(org.get("pids") or [], known_ror_ids)

    if not ror_ids:
        # No usable ROR id: the organization cannot be identified authoritatively
        rows_no_ror += 1
    else:
        ror_id = resolve_ror_id(ror_ids, org.get("legalName"), ror_organizations)

        if ror_id is None:
            rows_ambiguous_ror += 1
        else:
            openaire_ror_map[org["id"]] = ror_id
            if len(ror_ids) == 1:
                rows_single_ror += 1
            else:
                rows_resolved_by_name += 1

    if rows_read % LOG_EVERY == 0:
        print(f"  …{rows_read:,} organizations read, {len(openaire_ror_map):,} resolved so far")

# Write output JSON files
with open(OUTPUT_ORGANIZATIONS, "w", encoding="utf-8") as output_path:
    json.dump(ror_organizations, output_path, indent=2, ensure_ascii=False)

with open(OUTPUT_OPENAIRE_MAP, "w", encoding="utf-8") as output_path:
    json.dump(openaire_ror_map, output_path, indent=2, ensure_ascii=False)

# Record end time and calculate elapsed time
ended_at = datetime.now(timezone.utc)
elapsed_seconds = round(time.monotonic() - started_at, 2)
organizations_size_bytes = OUTPUT_ORGANIZATIONS.stat().st_size
openaire_map_size_bytes = OUTPUT_OPENAIRE_MAP.stat().st_size

# How many distinct organizations the resolved OpenAIRE ids collapse onto
distinct_ror_ids = len(set(openaire_ror_map.values()))

# Compile metadata about the processing run
metadata = {
    "elapsed_seconds": elapsed_seconds,
    "ended_at": ended_at.isoformat(),
    "ror_organizations": len(ror_organizations),
    "rows_read": rows_read,
    "rows_resolved": len(openaire_ror_map),
    "rows_single_ror": rows_single_ror,
    "rows_resolved_by_name": rows_resolved_by_name,
    "rows_ambiguous_ror": rows_ambiguous_ror,
    "rows_no_ror": rows_no_ror,
    "distinct_ror_ids_mapped": distinct_ror_ids,
    "openaire_ids_collapsed": len(openaire_ror_map) - distinct_ror_ids,
    "organizations_json_size_bytes": organizations_size_bytes,
    "organizations_json_size_mb": round(organizations_size_bytes / 1024 / 1024, 2),
    "openaire_map_json_size_bytes": openaire_map_size_bytes,
    "openaire_map_json_size_mb": round(openaire_map_size_bytes / 1024 / 1024, 2),
}

# Write metadata to JSON file
with OUTPUT_METADATA.open("w", encoding="utf-8") as metadata_path:
    json.dump(metadata, metadata_path, indent=2)

print(
    f"\n✔ ROR organizations written: {len(ror_organizations):,} records -> "
    f"{OUTPUT_ORGANIZATIONS.relative_to(DATA_DIR)}"
)
print(
    f"✔ OpenAIRE map written: {len(openaire_ror_map):,} records -> "
    f"{OUTPUT_OPENAIRE_MAP.relative_to(DATA_DIR)}"
)

print(f"  {rows_single_ror:,} resolved from a single ROR id")
print(f"  {rows_resolved_by_name:,} had several ROR ids, resolved via legalName")
print(f"  {rows_ambiguous_ror:,} had several ROR ids and stayed ambiguous (dropped)")
print(f"  {rows_no_ror:,} had no ROR id in the ROR dump (dropped)")
print(f"  {len(openaire_ror_map) - distinct_ror_ids:,} OpenAIRE ids collapsed onto a shared ROR id")
print(f"Elapsed time: {elapsed_seconds} seconds")
print(f"Metadata written to: {OUTPUT_METADATA.relative_to(DATA_DIR)}")
