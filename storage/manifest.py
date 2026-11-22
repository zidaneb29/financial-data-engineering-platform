"""Strict local batch schemas and portable archive path validation."""

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


class IntegrityError(OSError):
    """A batch cannot be trusted or safely read."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def manifest_digest(manifest: dict) -> str:
    return digest(canonical_bytes({key: value for key, value in manifest.items() if key != "manifest_sha256"}))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrityError(message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON object field")
        result[key] = value
    return result


def parse_json(body: bytes) -> Any:
    def invalid_constant(_value):
        raise ValueError

    try:
        return json.loads(body, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError):
        raise IntegrityError("Malformed stored JSON") from None


def token(value: Any, label: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None,
            f"Invalid {label}")
    return value


def identity(source: Any, entity: Any, run_id: Any = None) -> None:
    require(source in ("fred", "sec"), "Unsupported source")
    token(entity, "entity")
    if source == "sec":
        require(re.fullmatch(r"[0-9]{10}", entity) is not None, "Invalid SEC entity")
    if run_id is not None:
        require(isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{32}", run_id) is not None,
                "Invalid run identifier")


def safe_path(root: Path, reference: Any) -> Path:
    require(isinstance(reference, str) and bool(reference), "Invalid archive path")
    parts = reference.split("/")
    require(all(re.fullmatch(r"\.?[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", part) for part in parts),
            "Archive paths must use canonical relative POSIX components")
    target = root.joinpath(*parts)
    # Reject internal redirects as well as external symlinks and junctions.
    require(target.resolve() == root.resolve().joinpath(*parts), "Archive path contains a redirected location")
    return target


def timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed),
                "Expected UTC timestamp")
        return parsed
    except (ValueError, TypeError):
        raise IntegrityError("Invalid manifest timestamp") from None


def day(value: Any) -> date:
    try:
        parsed = date.fromisoformat(value)
        require(parsed.isoformat() == value, "Noncanonical manifest date")
        return parsed
    except (ValueError, TypeError):
        raise IntegrityError("Invalid manifest date") from None


def checksum(value: Any) -> None:
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
            "Invalid SHA-256 checksum")


def raw_reference(root: Path, reference: Any, source: str | None = None, entity: str | None = None) -> Path:
    require(isinstance(reference, dict) and set(reference) == {
        "endpoint", "sha256", "object_key", "params", "retrieved_at",
    }, "Invalid raw object reference schema")
    checksum(reference["sha256"])
    endpoint = token(reference["endpoint"], "endpoint")
    path = safe_path(root, reference["object_key"])
    parts = reference["object_key"].split("/")
    require(len(parts) == 5 and parts[0] == "raw", "Unexpected raw object location")
    identity(parts[1], parts[2])
    require(source is None or source == parts[1], "Raw source mismatch")
    require(entity is None or entity == parts[2], "Raw entity mismatch")
    require(parts[3] == endpoint and parts[4] == reference["sha256"] + ".json",
            "Raw object identity does not match its checksum")
    allowed = {"fred": {"series", "observations"},
               "sec": {"submissions", "submissions_history", "companyfacts"}}
    require(endpoint in allowed[parts[1]], "Unexpected raw endpoint")
    require(isinstance(reference["params"], dict), "Invalid raw request parameters")
    parameter_names = {
        "series": {"series_id", "file_type", "realtime_start", "realtime_end"},
        "observations": {
            "series_id", "file_type", "realtime_start", "realtime_end", "observation_start",
            "observation_end", "units", "order_by", "sort_order", "limit", "offset",
        },
        "submissions": {"file"}, "submissions_history": {"file"}, "companyfacts": {"file"},
    }
    require(set(reference["params"]) == parameter_names[endpoint], "Unexpected raw request parameters")
    if parts[1] == "fred":
        params = reference["params"]
        require(params["series_id"] == parts[2] and params["file_type"] == "json",
                "FRED raw request identity mismatch")
        require(day(params["realtime_start"]) == day(params["realtime_end"]), "Invalid FRED snapshot bounds")
        if endpoint == "observations":
            require(day(params["observation_start"]) <= day(params["observation_end"]),
                    "Invalid FRED observation window")
            require(params["units"] == "lin" and params["order_by"] == "observation_date"
                    and params["sort_order"] == "asc", "Unexpected FRED observation transformation")
            require(type(params["limit"]) is int and 1 <= params["limit"] <= 100000
                    and type(params["offset"]) is int and params["offset"] >= 0, "Invalid FRED page parameters")
    else:
        filename = reference["params"]["file"]
        pattern = rf"CIK{parts[2]}-submissions-[0-9]+\.json" if endpoint == "submissions_history" else rf"CIK{parts[2]}\.json"
        require(isinstance(filename, str) and re.fullmatch(pattern, filename) is not None,
                "SEC raw request identity mismatch")
    timestamp(reference["retrieved_at"])
    return path


COMMON_FIELDS = {
    "schema_version", "run_id", "source", "entity", "started_at", "completed_at",
    "start", "end", "metadata", "objects", "normalized", "manifest", "status", "counts",
}


def validate_schema(root: Path, manifest: Any) -> None:
    try:
        _validate_schema(root, manifest)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise IntegrityError("Malformed manifest schema") from None


def _validate_schema(root: Path, manifest: Any) -> None:
    require(isinstance(manifest, dict), "Manifest must be an object")
    version = manifest.get("schema_version")
    require(type(version) is int and version in (1, 2), "Unsupported manifest schema version")
    extra = {"normalized_files", "manifest_sha256"} if version == 2 else set()
    require(set(manifest) == COMMON_FIELDS | extra, "Invalid manifest fields")
    identity(manifest["source"], manifest["entity"], manifest["run_id"])
    require(manifest["status"] == "success", "Manifest is not successfully committed")
    require(day(manifest["start"]) <= day(manifest["end"]), "Reversed manifest date window")
    require(timestamp(manifest["started_at"]) <= timestamp(manifest["completed_at"]),
            "Reversed manifest timestamps")
    require(isinstance(manifest["metadata"], dict), "Invalid source metadata")
    path = safe_path(root, manifest["manifest"])
    expected_parent = root / "metadata" / "batches" / manifest["source"] / manifest["entity"]
    require(path.parent == expected_parent and re.fullmatch(r"[0-9]{12}\.json", path.name) is not None
            and int(path.stem) > 0, "Unexpected manifest location")
    counts = manifest["counts"]
    require(isinstance(counts, dict) and set(counts) == {"retrieved", "written", "duplicates", "revised"},
            "Invalid manifest counts")
    require(all(type(value) is int and value >= 0 for value in counts.values()), "Invalid record count")
    require(counts["retrieved"] == counts["written"] + counts["duplicates"]
            and counts["revised"] <= counts["written"], "Inconsistent manifest counts")
    require(isinstance(manifest["objects"], list), "Invalid raw object list")
    for reference in manifest["objects"]:
        raw_reference(root, reference, manifest["source"], manifest["entity"])
    endpoints = [item["endpoint"] for item in manifest["objects"]]
    required_endpoints = {"series", "observations"} if manifest["source"] == "fred" else {"submissions", "companyfacts"}
    require(required_endpoints <= set(endpoints), "Incomplete source snapshot")
    for endpoint in required_endpoints - {"observations"}:
        require(endpoints.count(endpoint) == 1, "Repeated source snapshot endpoint")
    if version == 2:
        if manifest["source"] == "fred":
            metadata = manifest["metadata"]
            require(set(metadata) == {"snapshot_date", "series_metadata_key"}, "Invalid FRED metadata fields")
            snapshot = day(metadata["snapshot_date"])
            series_reference = next(item for item in manifest["objects"] if item["endpoint"] == "series")
            require(metadata["series_metadata_key"] == series_reference["object_key"],
                    "FRED metadata object mismatch")
            for item in manifest["objects"]:
                params = item["params"]
                require(day(params["realtime_start"]) == snapshot, "FRED request snapshot mismatch")
                if item["endpoint"] == "observations":
                    require(params["observation_start"] == manifest["start"]
                            and params["observation_end"] == manifest["end"], "FRED request window mismatch")
        else:
            metadata = manifest["metadata"]
            require(set(metadata) == {"forms", "missing_mapped_metrics", "conflicting_fact_keys", "unmatched_fact_rows"},
                    "Invalid SEC metadata fields")
            require(isinstance(metadata["forms"], list) and bool(metadata["forms"])
                    and all(form in {"10-K", "10-K/A", "10-Q", "10-Q/A"} for form in metadata["forms"]),
                    "Invalid SEC snapshot forms")
            require(isinstance(metadata["missing_mapped_metrics"], list)
                    and all(isinstance(item, str) for item in metadata["missing_mapped_metrics"]),
                    "Invalid SEC missing-metric diagnostics")
            require(all(type(metadata[name]) is int and metadata[name] >= 0
                        for name in ("conflicting_fact_keys", "unmatched_fact_rows")), "Invalid SEC diagnostics")
    normalized = manifest["normalized"]
    require(isinstance(normalized, dict), "Invalid normalized file mapping")
    datasets = {"fred": {"observations"}, "sec": {"filings", "facts"}}
    require(set(normalized) <= datasets[manifest["source"]], "Unexpected normalized dataset")
    for dataset, reference in normalized.items():
        safe_path(root, reference)
        expected = f"processed/{manifest['source']}/{manifest['entity']}/{manifest['run_id']}/{dataset}.jsonl"
        require(reference == expected, "Unexpected normalized file location")
    if version == 2:
        checksum(manifest["manifest_sha256"])
        require(manifest_digest(manifest) == manifest["manifest_sha256"], "Manifest checksum mismatch")
        files = manifest["normalized_files"]
        require(isinstance(files, dict) and set(files) == set(normalized), "Normalized integrity mapping mismatch")
        for dataset, item in files.items():
            require(isinstance(item, dict) and set(item) == {"sha256", "byte_size", "row_count"},
                    "Invalid normalized integrity schema")
            checksum(item["sha256"])
            require(all(type(item[name]) is int and item[name] > 0 for name in ("byte_size", "row_count")),
                    "Invalid normalized file size or count")
        require(sum(item["row_count"] for item in files.values()) == counts["written"],
                "Normalized row counts do not match manifest")
