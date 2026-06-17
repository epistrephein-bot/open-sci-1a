# README

Data produced for the article "In the World of Citations, Are We Really Open(Minded), or Stuck in a Comfort Zone?"

## RQ 1a - Map of Italian Science

### citation_counts

| file | description |
|---|---|
| `<university_name>/citation_counts.metadata.json` | Metadata about the citation counts process for a specific university. |
| `<university_name>/citation_counts_countries_incoming.csv` | Incoming citation counts for countries for a specific university. |
| `<university_name>/citation_counts_countries_outgoing.csv` | Outgoing citation counts for countries for a specific university. |
| `<university_name>/citation_counts_organizations_incoming.csv` | Incoming citation counts for organizations for a specific university. |
| `<university_name>/citation_counts_organizations_outgoing.csv` | Outgoing citation counts for organizations for a specific university. |

### citation_counts_annualized

| file | description |
|---|---|
| `<university_name>/citation_counts.metadata.json` | Metadata about the annualized citation counts process for a specific university. |
| `<university_name>/<time_period>/citation_counts_countries_incoming.csv` | Incoming annualized citation counts for countries for a specific university for a specific time period. |
| `<university_name>/<time_period>/citation_counts_countries_outgoing.csv` | Outgoing annualized citation counts for countries for a specific university for a specific time period. |
| `<university_name>/<time_period>/citation_counts_organizations_incoming.csv` | Incoming annualized citation counts for organizations for a specific university for a specific time period. |
| `<university_name>/<time_period>/citation_counts_organizations_outgoing.csv` | Outgoing annualized citation counts for organizations for a specific university for a specific time period. |

### iris_oc_pids

| file | description |
|---|---|
| `<university_name>/iris_oc_pids.csv` | Mapping of IRIS publications to OpenCitations PIDs for a specific university. |
| `<university_name>/iris_oc_pids.missing.csv` | IRIS publications for which no OpenCitations PIDs were found for a specific university. |
| `<university_name>/iris_oc_pids.metadata.json` | Metadata about the IRIS to OpenCitations PIDs mapping process for a specific university. |
| `unique_pids.csv` | List of unique PIDs across all IRIS publications. |
| `unique_pids.metadata.json` | Metadata about the unique PIDs generation process across all IRIS publications. |

### iris_openaire_organizations

| file | description |
|---|---|
| `missing_no_searchable_pid.csv` | IRIS publications for which no searchable PID was found. |
| `omid_organizations.json` | Mapping of IRIS publications to OpenAIRE organizations. |
| `omid_organizations.metadata.json` | Metadata about the IRIS to OpenAIRE organizations mapping process. |

### openaire_ror_countries

| file | description |
|---|---|
| `openaire_ror_countries.json` | Mapping of OpenAIRE organizations to ROR identifiers, names and countries. |
| `openaire_ror_countries.metadata.json` | Metadata about the OpenAIRE to ROR mapping process. |

### top_cited

| file | description |
|---|---|
| `top_cited_combined.csv` | Most cited publications across all universities. |
| `top_cited_<university_name>.csv` | Most cited publications for a specific university. |
| `top_cited.metadata.json` | Metadata about the top cited calculation process. |

---

## RQ 2a - Disciplinary Flow

For each university name

| file | description |
|---|---|
| `iris_oc_citation_subjects.csv` | Final output csv of the enriched iris_in_oc_index extended with citation flow categorisation, venue data and Library of Congress subject classification. |
| `iris_oc_subject_processing.txt` | Full summary output from running each script in the disciplinary flow workflow. |
| `no_match/venues_no_match.csv` | Citation entities which could not be matched with venue data from the OC meta data dump on either the citing or cited side, or both. |
| `no_match/discipline_no_match.csv` | Citation entities which could not be matched to disciplines from the external data dumps (Scimago and DOAJ) on either the citing or cited side, or both. |
| `no_match/venues_no_issn.csv` | Citation entities with venue data but no ISSN on either the citing or cited side, or both. |
| `no_match/miss_loc_cat.csv` | Citation entities which could not be matched to one of the LOC subject classifications, on either the citing or cited side, or both. |
