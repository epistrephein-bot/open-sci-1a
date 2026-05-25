import csv
import gzip
import json
import os
import re
import sys
import tarfile
import time
from glob import glob
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

# The OMID to debug — change this before running
OMID = "omid:br/062502139701"

# Paths and directories
DATA_DIR = Path(DATA_PATH)
DUMPS_DIR = DATA_DIR / "dumps"

# Input CSV (columns: omid, doi, pmid, isbn)
INPUT_CSV = DATA_DIR / "unique_pids.csv"

# OpenAIRE dump location
OPENAIRE_DIR = DUMPS_DIR / "openaire"
PUBLICATION_TAR_PATTERN = "publication_*.tar"
RELATION_TAR_PATTERN = "relation_*.tar"

# Organization/country mapping
ORG_COUNTRIES_JSON = DATA_DIR / "openaire_ror_countries" / "openaire_ror_countries.json"


# ==============================================================================
# METHODS — normalization (same as resolve_organizations.py)
# ==============================================================================

_DOI_PREFIX_RE = re.compile(r"^(https?://)?(dx\.)?doi\.org/", re.IGNORECASE)
_ENTITY_PREFIX_RE = re.compile(r"^\d+\|")


def normalize_doi(raw):
    """Lowercase DOI, strip resolver prefix and 'doi:' scheme prefix."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("doi:"):
        raw = raw[4:]
    raw = _DOI_PREFIX_RE.sub("", raw)
    return raw.lower().strip() or None


def normalize_pmid(raw):
    """Strip 'pmid:' scheme prefix."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("pmid:"):
        raw = raw[5:]
    return raw.strip() or None


def strip_entity_prefix(eid):
    """Remove leading 'NN|' OpenAIRE entity-type prefix if present."""
    if eid is None:
        return None
    return _ENTITY_PREFIX_RE.sub("", eid.strip())


# ==============================================================================
# METHODS — tar streaming (same as resolve_organizations.py)
# ==============================================================================

def iter_tar_records(tar_path):
    """Yield parsed JSON objects from a *.tar of *.json.gz members."""
    with tarfile.open(tar_path, "r") as tar:
        for member in tar:
            if not member.isfile():
                continue
            base = os.path.basename(member.name)
            if base.startswith("."):
                continue
            name_lower = member.name.lower()
            if not (name_lower.endswith(".gz") or name_lower.endswith(".json")):
                continue
            fobj = tar.extractfile(member)
            if fobj is None:
                continue
            stream = (
                gzip.GzipFile(fileobj=fobj)
                if name_lower.endswith(".gz")
                else fobj
            )
            try:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
            finally:
                stream.close()


def parse_relation(rel):
    """Return (src_id, src_type, tgt_id, tgt_type, rel_name)."""
    src = rel.get("source")
    tgt = rel.get("target")

    if isinstance(src, dict):
        src_id, src_type = src.get("id"), src.get("type")
    else:
        src_id, src_type = src, rel.get("sourceType")

    if isinstance(tgt, dict):
        tgt_id, tgt_type = tgt.get("id"), tgt.get("type")
    else:
        tgt_id, tgt_type = tgt, rel.get("targetType")

    rt = rel.get("relType") or rel.get("reltype") or {}
    rel_name = rt.get("name") if isinstance(rt, dict) else None

    return src_id, src_type, tgt_id, tgt_type, rel_name


def format_elapsed(t0):
    """Format elapsed time since t0 (monotonic) as HhMMmSSs."""
    m, s = divmod(int(time.monotonic() - t0), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s"


# ==============================================================================
# STEP 1 — lookup OMID in unique_pids.csv
# ==============================================================================

print("=" * 70)
print(f"Debugging OMID: {OMID}")
print("=" * 70)

print(f"\n--- Step 1: looking up {OMID} in {INPUT_CSV.name} ---")

csv_row = None
with INPUT_CSV.open("r", encoding="utf-8") as fh:
    reader = csv.DictReader(fh)
    for row in reader:
        if (row.get("omid") or "").strip() == OMID:
            csv_row = row
            break

if csv_row is None:
    print(f"  ❌ OMID not found in {INPUT_CSV.name}")
    sys.exit(1)

doi_raw = (csv_row.get("doi") or "").strip()
pmid_raw = (csv_row.get("pmid") or "").strip()
isbn_raw = (csv_row.get("isbn") or "").strip()
ndoi = normalize_doi(doi_raw)
npmid = normalize_pmid(pmid_raw)

print(f"  CSV row: {json.dumps(csv_row, ensure_ascii=False)}")
print(f"  Normalized DOI:  {ndoi}")
print(f"  Normalized PMID: {npmid}")

if not ndoi and not npmid:
    print(f"  ❌ no DOI or PMID to search for — this record would be in missing.csv")
    sys.exit(1)


# ==============================================================================
# STEP 2 — find the publication record in publication tars
# ==============================================================================

print(f"\n--- Step 2: scanning publication tars for DOI={ndoi} / PMID={npmid} ---")

tars = sorted(glob(str(OPENAIRE_DIR / PUBLICATION_TAR_PATTERN)))
print(f"  {len(tars)} publication tar(s) to scan")

pub_record = None
pub_id = None
t0 = time.monotonic()

for tar_path in tars:
    base = os.path.basename(tar_path)
    for rec in iter_tar_records(tar_path):
        pids_list = rec.get("pids") or []
        matched = False

        for p in pids_list:
            scheme = (p.get("scheme") or "").lower()
            val = p.get("value")
            if not val:
                continue

            if scheme == "doi" and ndoi and normalize_doi(val) == ndoi:
                matched = True
                break
            if scheme == "pmid" and npmid and normalize_pmid(val) == npmid:
                matched = True
                break

        if matched:
            pub_id = strip_entity_prefix(rec.get("id"))
            pub_record = rec
            print(f"  ✅ found in {base} | {format_elapsed(t0)}")
            break

    if pub_record:
        break

if pub_record is None:
    print(f"  ❌ no publication record found in any tar | {format_elapsed(t0)}")
    sys.exit(1)

print(f"  OpenAIRE publication id: {pub_id}")
print(f"  Full record:")
print(json.dumps(pub_record, indent=2, ensure_ascii=False))


# ==============================================================================
# STEP 3 — find all relation edges for this publication in relation tars
# ==============================================================================

print(f"\n--- Step 3: scanning relation tars for pub_id={pub_id} ---")

tars = sorted(glob(str(OPENAIRE_DIR / RELATION_TAR_PATTERN)))
print(f"  {len(tars)} relation tar(s) to scan")

# Collect ALL relations involving this pub_id, not just affiliations
all_relations = []
affiliation_org_ids = []
t0 = time.monotonic()

for tar_path in tars:
    base = os.path.basename(tar_path)
    found_here = 0
    pub_id_bytes = pub_id.encode("utf-8")

    with tarfile.open(tar_path, "r") as tar:
        for member in tar:
            if not member.isfile():
                continue
            name_lower = member.name.lower()
            if not (name_lower.endswith(".gz") or name_lower.endswith(".json")):
                continue
            fobj = tar.extractfile(member)
            if fobj is None:
                continue
            stream = (
                gzip.GzipFile(fileobj=fobj)
                if name_lower.endswith(".gz")
                else fobj
            )
            try:
                for raw_line in stream:
                    if pub_id_bytes not in raw_line:
                        continue

                    try:
                        rel = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    src_id, src_type, tgt_id, tgt_type, rel_name = parse_relation(rel)
                    src_id_norm = strip_entity_prefix(src_id)
                    tgt_id_norm = strip_entity_prefix(tgt_id)

                    if src_id_norm != pub_id and tgt_id_norm != pub_id:
                        continue

                    found_here += 1
                    all_relations.append(rel)

                    if rel_name and rel_name.lower() in {"hasauthorinstitution", "isauthorinstitutionof"}:
                        if (src_type or "").lower() == "organization":
                            affiliation_org_ids.append(strip_entity_prefix(src_id))
                        elif (tgt_type or "").lower() == "organization":
                            affiliation_org_ids.append(strip_entity_prefix(tgt_id))
            finally:
                stream.close()

    if found_here:
        print(f"  {base}: {found_here} relation(s) found")

print(f"\n  Total relations involving this publication: {len(all_relations)} | "
      f"{format_elapsed(t0)}")

if all_relations:
    print(f"\n  All relations (full records):")
    for i, rel in enumerate(all_relations):
        _, _, _, _, rname = parse_relation(rel)
        print(f"\n  [{i + 1}] relType.name = {rname}")
        print(json.dumps(rel, indent=2, ensure_ascii=False))

print(f"\n  Affiliation org ids ({len(affiliation_org_ids)}):")
for oid in affiliation_org_ids:
    print(f"    {oid}")


# ==============================================================================
# STEP 4 — resolve org ids in the organization/country mapping
# ==============================================================================

print(f"\n--- Step 4: looking up {len(affiliation_org_ids)} org(s) "
      f"in {ORG_COUNTRIES_JSON.name} ---")

if not ORG_COUNTRIES_JSON.exists():
    print(f"  ❌ {ORG_COUNTRIES_JSON} not found")
    sys.exit(1)

with ORG_COUNTRIES_JSON.open("r", encoding="utf-8") as fh:
    org_countries = json.load(fh)

for oid in affiliation_org_ids:
    rec = org_countries.get(oid)
    if rec:
        print(f"\n  ✅ {oid}")
        print(json.dumps(rec, indent=2, ensure_ascii=False))
    else:
        print(f"\n  ❌ {oid} — not found in mapping")


# ==============================================================================
# SUMMARY
# ==============================================================================

print()
print("=" * 70)
print("Summary")
print("=" * 70)
print(f"  OMID:             {OMID}")
print(f"  DOI:              {ndoi}")
print(f"  PMID:             {npmid}")
print(f"  OpenAIRE pub id:  {pub_id}")
print(f"  Total relations:  {len(all_relations)}")
print(f"  Affiliation orgs: {len(affiliation_org_ids)}")
for oid in affiliation_org_ids:
    rec = org_countries.get(oid, {})
    print(f"    {oid} -> {rec.get('legal_name', '???')} ({rec.get('country_code', '?')})")
