"""Pre-flight check: which organizations would a re-run silently drop?

Compares a previous citation_counts run against the current openaire_ror_map, and
reports every organization that used to be counted but no longer resolves. Run it
after match_organizations_countries.py and BEFORE the ~6h resolve_pids_organizations.py,
so a mapping regression costs seconds instead of a night.

Two real regressions this catches:
  - University of Padua dropped because OpenAIRE lists its ROR pid twice and the
    duplicate was read as two competing identities
  - Karolinska Institutet, Oregon, New Mexico and 99 others dropped because their
    legalName only matched a ROR alias, or tied with a withdrawn ROR record

Organizations with no ROR id at all are excluded by design and are reported
separately — those are expected, not regressions.
"""

import csv
import json
from pathlib import Path

# ==============================================================================
# PARAMETERS — change these before running
# ==============================================================================

# A previous citation_counts run to compare against. Must still have the
# `openaire` column, i.e. a run from before the ROR-authority change.
BASELINE_DIR = "bloom_data/map_of_italian_science/citation_counts"

# How many rows per CSV to check. The long tail is mostly noise.
TOP_N = 500

# Report an excluded organization only if it held at least this many citations
MIN_COUNT = 1_000


# ==============================================================================
# CONSTANTS AND CONFIGURATION
# ==============================================================================

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

BASELINE_PATH = DATA_DIR / BASELINE_DIR
ROR_ORGANIZATIONS_JSON = DATA_DIR / "openaire_ror_countries" / "ror_organizations.json"
OPENAIRE_ROR_MAP_JSON = DATA_DIR / "openaire_ror_countries" / "openaire_ror_map.json"

UNIVERSITIES = ("SNS", "UNIBO", "UNIMI", "UNIPD", "UNITO", "UPO")
DIRECTIONS = ("incoming", "outgoing")

# Organizations the project is about — these must always resolve
TARGET_UNIVERSITIES = {
    "SNS": "https://ror.org/03aydme10",
    "UNIBO": "https://ror.org/01111rn36",
    "UNIMI": "https://ror.org/00wjc7c48",
    "UNIPD": "https://ror.org/00240q980",
    "UNITO": "https://ror.org/048tbm396",
    "UPO": "https://ror.org/04387x656",
}


# ==============================================================================
# RUNTIME
# ==============================================================================

for required in (ROR_ORGANIZATIONS_JSON, OPENAIRE_ROR_MAP_JSON):
    if not required.exists():
        raise SystemExit(f"❌ {required} not found — run match_organizations_countries.py")

with ROR_ORGANIZATIONS_JSON.open("r", encoding="utf-8") as fh:
    ror_organizations = json.load(fh)
with OPENAIRE_ROR_MAP_JSON.open("r", encoding="utf-8") as fh:
    openaire_ror_map = json.load(fh)

mapped_rors = set(openaire_ror_map.values())

print("=" * 70)
print("Organization coverage check")
print("=" * 70)
print(f"  {len(ror_organizations):,} ROR organizations, "
      f"{len(openaire_ror_map):,} OpenAIRE ids mapped onto {len(mapped_rors):,} of them")

# ------------------------------------------------------------------
# The six target universities must always be present
# ------------------------------------------------------------------

print("\n--- target universities ---")
missing_targets = []
for university, ror_id in TARGET_UNIVERSITIES.items():
    record = ror_organizations.get(ror_id)
    resolves = ror_id in mapped_rors
    if not resolves:
        missing_targets.append(university)
    flag = "✅" if resolves else "❌"
    name = record["legal_name"] if record else "NOT IN ROR INDEX"
    print(f"  {flag} {university:6} {name[:50]:50} {ror_id}")

# ------------------------------------------------------------------
# Compare against the baseline run
# ------------------------------------------------------------------

if not BASELINE_PATH.exists():
    print(f"\n! baseline not found: {BASELINE_PATH.relative_to(DATA_DIR)} — skipping comparison")
    raise SystemExit(1 if missing_targets else 0)

print(f"\n--- comparing against {BASELINE_PATH.relative_to(DATA_DIR)} (top {TOP_N} rows) ---")

# openaire_id -> (legal_name, highest count seen)
baseline = {}
for university in UNIVERSITIES:
    for direction in DIRECTIONS:
        path = BASELINE_PATH / university / f"citation_counts_organizations_{direction}.csv"
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for index, row in enumerate(csv.DictReader(fh)):
                if index >= TOP_N:
                    break
                openaire_id = row.get("openaire", "")
                if not openaire_id:
                    continue
                count = int(row["count"])
                name, best = baseline.get(openaire_id, (row["legal_name"], 0))
                baseline[openaire_id] = (name, max(best, count))

if not baseline:
    print("  ! baseline CSVs have no `openaire` column — cannot compare")
    raise SystemExit(1 if missing_targets else 0)

# Split the dropped organizations by cause
no_ror = []
regressions = []
for openaire_id, (name, count) in baseline.items():
    if openaire_id in openaire_ror_map or count < MIN_COUNT:
        continue
    # pending_org_ records are overwhelmingly the intended no-ROR exclusion
    (no_ror if openaire_id.startswith("pending_org_") else regressions).append(
        (count, name, openaire_id)
    )

resolved = sum(1 for oid in baseline if oid in openaire_ror_map)
print(f"  {len(baseline):,} distinct organizations in the baseline")
print(f"  {resolved:,} still resolve")
print(f"  {len(no_ror):,} excluded for having no ROR id (expected by design)")
print(f"  {len(regressions):,} excluded for other reasons (investigate these)")

if regressions:
    print("\n  ⚠️  excluded despite being curated OpenAIRE organizations:")
    for count, name, openaire_id in sorted(regressions, reverse=True):
        print(f"    {count:>9,}  {name[:52]:52} {openaire_id}")

# ------------------------------------------------------------------
# Renames — expected, but worth eyeballing before a long run
# ------------------------------------------------------------------

renamed = []
for openaire_id, (name, count) in baseline.items():
    ror_id = openaire_ror_map.get(openaire_id)
    if not ror_id or count < MIN_COUNT:
        continue
    new_name = ror_organizations[ror_id]["legal_name"]
    if new_name != name:
        renamed.append((count, name, new_name))

print(f"\n--- {len(renamed):,} organizations renamed by ROR resolution (top 15) ---")
for count, old_name, new_name in sorted(renamed, reverse=True)[:15]:
    print(f"  {count:>9,}  {old_name[:40]:40} -> {new_name[:40]!r}")

# ------------------------------------------------------------------
# Verdict
# ------------------------------------------------------------------

print()
print("=" * 70)
if missing_targets:
    print(f"❌ FAIL — target universities missing: {', '.join(missing_targets)}")
elif regressions:
    print(f"⚠️  {len(regressions)} curated organization(s) dropped — check before re-running")
else:
    print("✅ PASS — no curated organization lost; safe to run resolve_pids_organizations.py")
print("=" * 70)

raise SystemExit(1 if (missing_targets or regressions) else 0)
