# Public portfolio publication

Version 0.16.0. Scientific source, configurations, metrics, frozen artifacts
and deployed infrastructure are preserved.

Confirmed destination: https://github.com/Everlynmartins/adaptive-predictive-maintenance-platform
on branch main.

## Data and reproduction

Source: [NASA PCoE repository](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/).
Attribution: A. Saxena and K. Goebel (2008), Turbofan Engine Degradation
Simulation Data Set, NASA Ames Prognostics Data Repository.

The [NASA resource metadata](https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data/resource/5224bcd1-ad61-490b-93b9-2817288accb8)
does not specify a license. Dataset redistribution rights are not asserted.
Raw, interim and processed dataset files remain excluded from Git.
Project-authored reports, frozen models and existing evaluation outputs remain
included; this change does not assign a software or dataset license.

The demo requires the previously validated validation.parquet and
split_manifest.json in data/processed/fd001. Restore that local snapshot before
Docker build. A fresh clone is not a self-contained dataset/demo bundle.
Do not fabricate inputs or replace split membership.

## Excluded publication inputs

- Original portfolio imports, accidental CSV, PDFs and ZIP archive.
- Dataset files, environment files, credential/key files and logs.
- Terraform state, plans, local tfvars and installed providers.
- Caches and temporary publication checks.
- Commercial standards PDFs, including IEC, ISO, RTCA and SAE.

No proprietary company data was identified in publication candidates.
Exclusion preserves local files. Standards remain conceptual references;
no commercial documents are redistributed.

## GitHub presentation

Suggested description:

> Predictive maintenance with probabilistic risk modeling, telemetry optimization,
> FastAPI, PostgreSQL, Terraform and AWS ECS/RDS.

Suggested topics: machine-learning, ml-engineering, mlops,
predictive-maintenance, reliability, time-series, fastapi, postgresql, docker,
terraform, aws, ecs, rds, cmapss.

Continuous MLOps remains future work.

## Publication checks

Review candidate and staged files for secrets/live identifiers, commercial
documents, large files and broken links. Inspect screenshots visually and
verify copied image hashes. Compare protected scientific files against the
local preparation baseline. Pattern scans support review, not a guarantee
against every possible secret.

Confirm remote, branch and visibility before push. Authentication must remain
outside the repository.

No real GIF was supplied. A future genuine recording may use
docs/assets/demo/dashboard_demo.gif; the README has no broken placeholder.

## Preparation verification — 2026-09-17

- 86 focused integration tests and 4 publication tests passed.
- All 15 operation scripts parsed on Windows PowerShell 5.1.
- Local browser preview rendered 3 Mermaid diagrams, with no broken images
  or page errors; relative documentation links passed offline checks.
- All 362 files in the protected preparation snapshot retained their hashes.
  The 345 protected files included in Git also match byte-for-byte in the
  prepared index. Git attributes prevent checkout newline conversion.
- Candidate text/binary scans found no real credential literals or live cloud
  identifiers requiring removal. Synthetic AWS fixtures and explicit local
  development credentials were distinguished from real secrets.
- All 11 supplied PNGs were reviewed; 12 images are included, counting the
  unchanged existing telemetry experiment figure. No imported CSV/PDF/ZIP
  is included.
