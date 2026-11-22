# Phase 2A offline hardening

New local batches use manifest schema 2 with SHA-256 checksums for normalized files, byte sizes, per-dataset counts and a canonical manifest checksum. Storage readers validate manifests, canonical paths, raw hashes, normalized file hashes and row invariants before exposing data. Raw reuse verifies the existing content-addressed object.

Sequence allocation reserves monotonically increasing identifiers before publication and considers retained manifests, reservations and run journals. Interrupted reservations leave gaps. Previously committed files survive failed publication. Legitimate version 1 source artifacts remain readable with their original, weaker integrity evidence.

SEC selection now has an explicit snapshot-aware entry point. It preserves snapshot scope, uses raw membership even for unchanged facts, excludes withdrawn candidates, supports historical observation cutoffs and explicit snapshots, and keeps original/amended filing identity. Cumulative selection remains available for historical research.

The [cloud loader contract](cloud-loader-contract.md) defines versioning, object validation, stable batch and event identifiers, upload completion markers, transactional load checkpoints, reconciliation, source memberships and exact numeric conversion.

## Verification

On November 19, 2026, the final full offline suite passed with **80 passed, 0 failed** on Python 3.11.9 and pytest 8.4.2 in 18.76 seconds. The command used a fresh ignored repository-local directory.

```powershell
$testRoot = '.local/phase2a-tests-' + [guid]::NewGuid().ToString('N')
.\.venv\Scripts\python.exe -m pytest --basetemp $testRoot --tb=short
```

`pip check` reported no broken requirements. Python compilation succeeded for ingestion and storage. Git ignore checks confirmed that the environment file and generated local artifacts remain excluded.

The Phase 2A suite includes the original 38 tests plus 42 additional regression cases. Coverage includes normalized corruption and missing files, edited manifests, schema violations, invalid/escaping/redirected paths, raw corruption on reuse, deleted highest manifests, legacy sequence bootstrap, interrupted publication and recovery, valid version 1 reading, stable reversion-event identities, SEC withdrawal/reappearance, conflicts and historical snapshot cutoffs. Synthetic mocks remain the source of API test data.

## Changed files

| Files | Purpose |
| --- | --- |
| storage/manifest.py | Manifest schemas, canonical checksums, path and raw-reference validation |
| storage/local.py | Full batch validation, normalized integrity metadata, raw reuse verification and sequence reservations |
| ingestion/sec.py | Validated snapshot replay and snapshot-scoped selection |
| tests/test_manifest_integrity.py | Storage corruption, schema, path, compatibility, sequence and transfer-identity regressions |
| tests/test_local_ingestion.py | Existing integration fixture now produces complete source-linked batches |
| tests/test_sec.py | Snapshot withdrawal, reappearance, conflicts, explicit snapshot and cutoff regressions |
| docs/cloud-loader-contract.md | Final local transfer boundary and proposed warehouse load protocol |
| docs/architecture.md, docs/data-contracts.md, docs/local-ingestion.md, docs/roadmap.md | Current implementation and compatibility guidance |
| docs/phase15-audit.md, docs/phase2a-report.md, README.md | Historical audit cross-reference, verified hardening results and concise public status |

## Readiness

The implemented interface supports Phase 2B local integration development. Phase 2B should build transfer and load ledgers against validated schema 2 batches and preserve full SEC snapshot membership. Live FRED and SEC checks, actual financial tag verification and numeric range profiling remain pending. Cloud deployment still requires explicit approval and a priced execution plan.

No live source verification or cloud deployment was performed in Phase 2A. Existing data and configuration were retained. New test artifacts use fresh ignored repository-local directories.
