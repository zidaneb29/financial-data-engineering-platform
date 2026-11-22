# Validated batch and cloud loader contract

Phase 2A implements local validation and snapshot selection. Phase 2B implements this transfer boundary through S3Transfer and a client-mediated Snowflake RAW loader, verified offline. See [cloud integration](cloud-integration.md) for the implemented protocol, configuration and remaining live checks.

## Local manifest versions

New entity batches use schema version 2. Version 1 artifacts remain readable when their schema, locations, raw hashes, row structure, business fingerprints and aggregate counts validate. Reading older artifacts does not rewrite them. Version 1 lacks original normalized-file checksums and the manifest checksum, so its corruption detection has weaker evidence. Cloud transfer requires version 2. A future explicit migration must preserve old artifacts and record its provenance. A backfill into a fresh archive can also establish a new fully checksummed baseline.

Both versions have exactly these top-level fields.

| Field | Meaning |
| --- | --- |
| schema_version | Integer version of the manifest contract |
| source, entity | fred plus series ID, or sec plus zero-padded 10-digit CIK |
| run_id | 32 lowercase hexadecimal characters, shared across entities in one CLI run |
| started_at, completed_at | UTC timestamps in chronological order |
| start, end | Inclusive source-date scope |
| metadata | FRED snapshot date and series metadata key, or SEC forms and normalization diagnostics |
| objects | Ordered raw request references with endpoint, SHA-256, object key, safe parameters and retrieval time |
| normalized | Dataset name to relative JSON Lines path. Empty for a successful run with no new normalized rows. |
| manifest | Its canonical relative path under metadata/batches/source/entity/sequence.json |
| status | success |
| counts | Nonnegative retrieved, written, duplicates and revised counts. Retrieved equals written plus duplicates. Revised cannot exceed written. |

Version 2 adds exactly `normalized_files` and `manifest_sha256`.

- `normalized_files` maps each dataset in `normalized` to SHA-256, byte_size and row_count. Byte hashes cover the entire UTF-8 JSON Lines file, including newlines. Per-file counts sum to counts.written.
- `manifest_sha256` hashes canonical UTF-8 JSON with sorted keys, standard JSON spacing, unescaped Unicode, finite numbers and a final newline, omitting only the manifest_sha256 field itself. The canonical serializer is `storage.manifest.canonical_bytes`.
- Each normalized row adds `business_fields`, the exact sorted field inventory used to calculate its business fingerprint. All known business fields must be present. Lineage and ingestion metadata remain separate from that fingerprint.

These hashes detect content mismatch. They provide no signature or protection against an actor replacing data and recalculating every hash. Phase 2B must pin manifest identity and its expected byte hash in its independently maintained transfer and load ledgers.

## Validation entry points and paths

`LocalStore.manifests(source, entity)` discovers and validates each committed batch, all raw objects and all normalized rows before returning the batch list. `LocalStore.validate_batch(manifest)` verifies that the supplied manifest matches its committed file and returns the validated normalized changes. `LocalStore.rows(manifests)` uses the same validator per batch. `LocalStore.read_object(reference)` validates the reference and SHA-256 before returning JSON bytes. SEC `read_snapshot` validates the batch before replaying raw source data.

All references use canonical relative POSIX paths. Reject traversal, drive letters, absolute paths, backslashes, empty components, alternate data streams, unexpected source/entity/run/dataset locations and redirects through symlinks or junctions. The selected archive root is resolved once and defines the trusted storage boundary. Validation assumes no external process changes files between validation and consumption. The uploader must hash the exact bytes it transfers and recheck the pinned manifest.

| Artifact | Allowed location |
| --- | --- |
| Raw JSON | raw/source/entity/endpoint/sha256.json |
| Normalized JSON Lines | processed/source/entity/run_id/dataset.jsonl |
| Success manifest | metadata/batches/source/entity/12-digit-positive-sequence.json |
| Run journal | metadata/runs/run_id.json |
| Sequence reservation | metadata/sequences/source/entity.json |

Version 2 requires the source endpoints needed for a complete snapshot, known dataset names, source-specific request parameter schemas and metadata. It verifies normalized entity, dataset, raw membership, natural keys, business fingerprint, ingestion timestamp and decimal representation. FRED retrieval validation checks observation pagination before publication. SEC retrieval validation checks column shape, issuer identity and financial fact fields before publication. An invalid or incomplete artifact raises an OSError-compatible IntegrityError, or a filesystem error for a missing file, and cannot advance coverage or be promoted by recovery.

## Publication, sequence allocation and repair

The ingestion coordinator holds the archive writer lock across publication. The writer atomically reserves a sequence before writing normalized files. Allocation takes the maximum of retained manifest filenames, the durable last_reserved counter and matching manifest references retained in run journals, then adds one. A failed or interrupted attempt can leave a reserved gap. Removing a committed manifest does not cause a surviving identity to be reused. No committed manifest is overwritten during ordinary publication.

The success manifest is published last after full batch validation. Orphaned raw or normalized files remain outside the committed stream. Recovery recognizes only validated committed batches. If a batch is corrupt, recovery fails closed and preserves the journal for investigation. Existing raw content-addressed objects must match the incoming hash before reuse. Corrupt files remain in place for explicit repair.

Deleting manifests loses their batch associations and can remove historical coverage. Reservation metadata prevents collisions but cannot recreate deleted records. Treat source retention as immutable during normal operation. Compare discovered identities against transfer/load ledgers and journal references when reconciling a missing committed batch. A gap alone cannot distinguish a failed reservation from a deleted batch. If manifests, counters and journals are all lost, restore the archive from a known backup before relying on its historical identities.

## Stable transfer and load identity

Assign a stable archive namespace at transfer configuration time. Use namespace, source, entity and run_id as the batch identity. Include schema version, manifest path, canonical manifest checksum and the exact manifest-file byte checksum in the transfer receipt. Never use sequence alone across archives.

For each raw object, use source, entity, endpoint and SHA-256 as its identity. Preserve separate batch-request membership with the ordered object index even if multiple requests reused the same raw bytes. A normalized change event uses batch identity, dataset and row ordinal. This preserves FRED reversions even when an old fingerprint recurs. SEC history also retains fact keys and fingerprints, including conflicting values.

The cloud destination should retain source-relative paths inside the configured archive namespace. Prepare an upload receipt containing the batch identity, pinned manifest hash and expected object paths, byte hashes, sizes and normalized row counts. Validate the same file bytes being uploaded. Use SHA-256 explicitly when checking object integrity. Do not substitute a multipart ETag for the content hash.

Upload dependencies first. Reuse a destination object only after verifying its identity and checksum. Publish the verified manifest or transfer receipt last with conditional creation. An interrupted upload has no ready marker. Resume by reconciling expected objects and retrying missing or mismatched ones under the same identity. Report mismatches for repair rather than overwrite a previously committed different batch.

## Warehouse loading and reconciliation

The implemented loader consumes a fully validated ready transfer with its pinned local archive. It validates records and uses parameterized DML to commit history changes, source memberships and the successful ledger entry in one transaction. Schema DDL is a separate administrator step. Source raw-object tables deduplicate by object identity while retaining batch relationships. A pre-existing warehouse mutex serializes cooperating loader transactions.

Maintain successful batch identities as the authoritative checkpoint. A maximum sequence watermark alone is insufficient because reserved gaps, later repair, independently processed entities and out-of-order arrivals are possible. Replays of the same identity and pinned hash produce no new load events. The same identity with a different hash is an integrity failure. Preserve source order independently of warehouse arrival time.

On failure, roll back the transaction, record sanitized failure stage and error code, and retain the source identity for retry. On restart, reconcile receipts, expected object hashes, warehouse commit ledger and row counts. Treat source-ingestion success, successful upload and successful warehouse load as separate states. A partial overall ingestion run may still contain independently valid entity manifests.

## Snapshot membership and source provenance

Normalized JSON Lines contain cumulative changes. They do not enumerate every candidate present in every snapshot.

For SEC current available candidates, use `select_snapshot_candidates(store, entity, filed_through=...)`. It selects the latest validated committed snapshot for that entity and returns its manifest and start/end scope with candidate results. A narrower latest backfill therefore returns a narrower scope. Pass an explicit manifest to select a different committed snapshot.

`observed_through` selects the most recent committed snapshot completed by that UTC timestamp. `filed_through` then filters the candidates by filing date. `original=True` applies the established non-amended original-candidate rule within the selected snapshot. For an original candidate withdrawn later, query the earlier observed snapshot. The low-level `select_period_candidates` remains usable for cumulative historical research. Its optional snapshot_rows argument restricts both facts and filings to supplied snapshot membership.

The loader must store raw snapshot identity and candidate membership, including candidates unchanged from prior batches and empty snapshot membership. Replay archived Company Facts to materialize those relationships when needed. Avoid interpreting an empty normalized change file as an empty SEC snapshot.

Preserve CIK, accession, namespace, tag, original unit, source dates, fiscal labels, filed date, source row, object checksum, retrieval event and committed batch identity. Retain original and amended accessions separately. Same-day release order, issuer extensions and confirmed restatements remain bounded by the source evidence.

## Exact numeric conversion

Keep source decimal text and raw lexical bytes. Profile values before selecting physical warehouse precision and scale. Convert through exact decimal arithmetic. Reject or quarantine any overflow or conversion requiring rounding, report the affected batch and source record, and avoid publishing a successful complete analytical load until the discrepancy is resolved according to its contract. The local parser supports values beyond warehouse fixed-precision limits. Its finite-value and magnitude checks are insufficient to select warehouse types without profiling.
