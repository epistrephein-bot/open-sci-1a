"""Trace one organization back through the pipeline that produced it.

Answers "why does this organization show up in citation_counts — and with these
counts?" by walking the places its identity is decided, in pipeline order:

    1. ror_organizations.json   — the ROR id(s) publishing this name
    2. openaire_ror_map.json    — which OpenAIRE orgs resolved onto them
    3. organization.tar         — every OpenAIRE org carrying that ROR id, and
                                  for each, whether it resolved or was dropped
    4. omid_organizations.json  — real entries the organization ended up on

Step 3 is the interesting one. An OpenAIRE org is dropped when it has no ROR id,
or when it carries several and none is singled out by its legalName — see
resolve_ror_id() in match_organizations_countries.py. Dropped orgs contribute
nothing to the counts, so this is where missing citations go.

Reads the pipeline's existing outputs — it does not re-run resolve_pids_organizations.py.
"""

import gzip
import json
import tarfile
import time
from pathlib import Path

import ijson

# ==============================================================================
# PARAMETERS — change these before running
# ==============================================================================

# Organization legal_name to trace, as it appears in citation_counts CSVs
TARGET_NAME = "Harvard University"

# How many omid_organizations.json entries to capture before stopping
SAMPLE_SIZE = 20


# ==============================================================================
# CONSTANTS AND CONFIGURATION
# ==============================================================================

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

DUMPS_DIR = DATA_DIR / "dumps"
OPENAIRE_ORG_TAR = DUMPS_DIR / "openaire" / "organization.tar"

ROR_ORGANIZATIONS_JSON = DATA_DIR / "ror_organizations" / "ror_organizations.json"
OPENAIRE_ROR_MAP_JSON = DATA_DIR / "ror_organizations" / "openaire_ror_map.json"
OMID_ORGANIZATIONS_JSON = DATA_DIR / "iris_openaire_organizations" / "omid_organizations.json"

OUTPUT_DIR = DATA_DIR / "debug_organization"

# Progress logging
LOG_EVERY_ENTRIES = 500_000


# ==============================================================================
# METHODS
# ==============================================================================

def format_elapsed(t0):
    """Format elapsed time since t0 (monotonic) as HhMMmSSs."""
    m, s = divmod(int(time.monotonic() - t0), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def slugify(name):
    """Turn an organization name into a filename-safe slug."""
    return "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")


def iter_openaire_orgs(tar_path):
    """Yield every JSON object from a tar archive of json.gz files."""
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


def extract_ror_ids(pids):
    """Return every ROR pid value on an OpenAIRE org, in dump order."""
    return [pid["value"] for pid in (pids or []) if pid.get("scheme") == "ROR"]


# ==============================================================================
# STEP 1 — find the ROR id(s) publishing this name
# ==============================================================================

print("=" * 70)
print(f"Tracing organization: {TARGET_NAME}")
print("=" * 70)

print(f"\n--- Step 1: searching {ROR_ORGANIZATIONS_JSON.name} for the name ---")

for required in (ROR_ORGANIZATIONS_JSON, OPENAIRE_ROR_MAP_JSON):
    if not required.exists():
        raise SystemExit(f"  ❌ {required} not found — run match_organizations_countries.py")

with ROR_ORGANIZATIONS_JSON.open("r", encoding="utf-8") as fh:
    ror_organizations = json.load(fh)

target_lower = TARGET_NAME.lower()
target_rors = {
    ror_id: rec
    for ror_id, rec in ror_organizations.items()
    if rec["legal_name"].lower() == target_lower
}

print(f"  {len(ror_organizations):,} organizations in the ROR index")
print(f"  {len(target_rors)} ROR id(s) publish the name {TARGET_NAME!r}")

if not target_rors:
    raise SystemExit("  ❌ no ROR organization has this name — nothing to trace")

for ror_id, rec in target_rors.items():
    print(f"    {ror_id} -> {json.dumps(rec, ensure_ascii=False)}")


# ==============================================================================
# STEP 2 — which OpenAIRE orgs resolved onto them
# ==============================================================================

print(f"\n--- Step 2: reading {OPENAIRE_ROR_MAP_JSON.name} ---")

with OPENAIRE_ROR_MAP_JSON.open("r", encoding="utf-8") as fh:
    openaire_ror_map = json.load(fh)

resolved_ids = {
    oid: ror_id for oid, ror_id in openaire_ror_map.items() if ror_id in target_rors
}

print(f"  {len(openaire_ror_map):,} OpenAIRE orgs resolved overall")
print(f"  {len(resolved_ids)} of them resolve onto this organization")
for oid, ror_id in resolved_ids.items():
    print(f"    {oid} -> {ror_id}")


# ==============================================================================
# STEP 3 — every OpenAIRE org carrying that ROR id, resolved or dropped
# ==============================================================================

print(f"\n--- Step 3: scanning {OPENAIRE_ORG_TAR.name} for orgs carrying these ROR ids ---")

t0 = time.monotonic()
candidates = []

for org in iter_openaire_orgs(OPENAIRE_ORG_TAR):
    ror_ids = extract_ror_ids(org.get("pids"))
    if not any(rid in target_rors for rid in ror_ids):
        continue

    oid = org.get("id")
    mapped_to = openaire_ror_map.get(oid)

    if mapped_to in target_rors:
        status = "resolved onto this organization"
    elif mapped_to:
        status = f"resolved elsewhere -> {mapped_to}"
    elif len(ror_ids) > 1:
        status = "DROPPED — several ROR ids, none singled out by legalName"
    else:
        status = "DROPPED — ROR id absent from the ROR dump"

    candidates.append({
        "openaire": oid,
        "legal_name": org.get("legalName"),
        "website": org.get("websiteUrl"),
        "ror_pids": [
            {"ror": rid, "name": (ror_organizations.get(rid) or {}).get("legal_name")}
            for rid in ror_ids
        ],
        "mapped_to": mapped_to,
        "status": status,
    })

print(f"  {len(candidates)} OpenAIRE org(s) carry one of these ROR ids | {format_elapsed(t0)}")

for cand in candidates:
    print(f"\n    {cand['openaire']}")
    print(f"      legalName : {cand['legal_name']!r}")
    print(f"      website   : {cand['website']!r}")
    for pid in cand["ror_pids"]:
        mark = "  <-- resolved to this" if pid["ror"] == cand["mapped_to"] else ""
        print(f"      {pid['ror']} = {pid['name']!r}{mark}")
    flag = "✅" if cand["mapped_to"] in target_rors else "⚠️ "
    print(f"      {flag} {cand['status']}")


# ==============================================================================
# STEP 4 — sample real entries the organization landed on
# ==============================================================================

print(f"\n--- Step 4: sampling {SAMPLE_SIZE} entries from {OMID_ORGANIZATIONS_JSON.name} ---")

if not OMID_ORGANIZATIONS_JSON.exists():
    raise SystemExit(f"  ❌ {OMID_ORGANIZATIONS_JSON} not found — run resolve_pids_organizations.py")

samples = []
scanned = 0
t0 = time.monotonic()

with OMID_ORGANIZATIONS_JSON.open("rb") as fh:
    for omid, entry in ijson.kvitems(fh, ""):
        scanned += 1

        if scanned % LOG_EVERY_ENTRIES == 0:
            print(f"    ...{scanned:,} entries scanned | {len(samples)} samples | "
                  f"{format_elapsed(t0)}")

        matched = [
            org.get("ror")
            for org in entry.get("organizations") or []
            if org.get("ror") in target_rors
        ]
        if not matched:
            continue

        samples.append({"omid": omid, "matched_rors": matched, "entry": entry})

        if len(samples) >= SAMPLE_SIZE:
            print(f"    reached {SAMPLE_SIZE} samples — stopping scan")
            break

print(f"  {len(samples)} sample(s) collected from {scanned:,} entries scanned | "
      f"{format_elapsed(t0)}")


# ==============================================================================
# OUTPUT
# ==============================================================================

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
output_json = OUTPUT_DIR / f"{slugify(TARGET_NAME)}.json"

report = {
    "target_name": TARGET_NAME,
    "sample_size_requested": SAMPLE_SIZE,
    "entries_scanned": scanned,
    "ror_organizations": target_rors,
    "resolved_openaire_ids": resolved_ids,
    "openaire_candidates": candidates,
    "samples": samples,
}

with output_json.open("w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2, ensure_ascii=False)


# ==============================================================================
# SUMMARY
# ==============================================================================

dropped = [c for c in candidates if c["mapped_to"] not in target_rors]

print()
print("=" * 70)
print("Summary")
print("=" * 70)
print(f"  Organization traced: {TARGET_NAME}")
print(f"  ROR id(s):           {', '.join(target_rors) or 'none'}")
print(f"  OpenAIRE orgs feeding it: {len(resolved_ids)}")
print(f"  OpenAIRE orgs carrying the ROR id but NOT feeding it: {len(dropped)}")
for cand in dropped:
    print(f"    {cand['openaire']}  {cand['legal_name']!r}")
    print(f"      {cand['status']}")
print(f"  Entries scanned:     {scanned:,}")
print(f"  Samples captured:    {len(samples)}")
print(f"  Report written to:   {output_json.relative_to(DATA_DIR)}")
