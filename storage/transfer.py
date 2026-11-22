"""Validated, immutable S3 transfer with local pins and remote ready receipts."""

import base64
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Callable

from ingestion.models import utc_now
from storage.local import LocalStore, atomic_write, json_bytes
from storage.manifest import IntegrityError, digest, parse_json, require, safe_path, token


LOGGER = logging.getLogger(__name__)


class CloudError(Exception):
    """Sanitized cloud failure, safe for logs."""


@dataclass(frozen=True)
class PreparedBatch:
    manifest: dict
    rows: list[dict]
    artifacts: dict[str, bytes]
    receipt: dict
    batch_id: str


def prepare_batch(store: LocalStore, manifest: dict, namespace: str) -> PreparedBatch:
    token(namespace, "archive namespace")
    require(manifest.get("schema_version") == 2, "Transfer requires a v2 manifest")
    rows = store.validate_batch(manifest)
    references = [item["object_key"] for item in manifest["objects"]]
    references.extend(manifest["normalized"].values())
    references.append(manifest["manifest"])
    ordered = sorted(set(references) - {manifest["manifest"]}) + [manifest["manifest"]]
    artifacts = {key: safe_path(store.root, key).read_bytes() for key in ordered}
    # Check the exact byte buffers being transferred, not earlier reads.
    for reference in manifest["objects"]:
        require(digest(artifacts[reference["object_key"]]) == reference["sha256"], "Raw transfer checksum mismatch")
    for dataset, path in manifest["normalized"].items():
        info = manifest["normalized_files"][dataset]
        require(digest(artifacts[path]) == info["sha256"] and len(artifacts[path]) == info["byte_size"],
                "Normalized transfer checksum mismatch")
        require(len(artifacts[path].splitlines()) == info["row_count"], "Transfer row count mismatch")
    require(parse_json(artifacts[manifest["manifest"]]) == manifest, "Manifest changed during preparation")
    identity = {
        "namespace": namespace, "source": manifest["source"],
        "entity": manifest["entity"], "run_id": manifest["run_id"],
    }
    batch_id = digest(json_bytes(identity))
    receipt = {
        "schema_version": 1, "batch_id": batch_id, "identity": identity,
        "manifest": manifest["manifest"], "manifest_sha256": manifest["manifest_sha256"],
        "manifest_file_sha256": digest(artifacts[manifest["manifest"]]),
        "files": {
            key: {"sha256": digest(body), "byte_size": len(body)}
            for key, body in artifacts.items()
        },
    }
    return PreparedBatch(manifest, rows, artifacts, receipt, batch_id)


def _error_code(error: Exception) -> str:
    return str(getattr(error, "response", {}).get("Error", {}).get("Code", ""))


class S3Transfer:
    def __init__(
        self, store: LocalStore, client: Any, *, bucket: str, namespace: str,
        attempts: int = 4, sleep: Callable = time.sleep,
    ):
        token(namespace, "archive namespace")
        require(bool(bucket) and "/" not in bucket, "Invalid S3 bucket")
        require(attempts >= 1, "Invalid transfer retry count")
        self.store, self.client = store, client
        self.bucket, self.namespace = bucket, namespace
        self.attempts, self.sleep = attempts, sleep

    def key(self, relative: str) -> str:
        safe_path(self.store.root, relative)
        return f"{self.namespace}/{relative}"

    def receipt_key(self, batch_id: str) -> str:
        return f"{self.namespace}/ready/{batch_id}.json"

    def _retry(self, operation: Callable):
        for attempt in range(self.attempts):
            try:
                return operation()
            except Exception as error:
                code = _error_code(error)
                transient = code in {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable", "500", "503", "ConditionalRequestConflict"}
                transient = transient or error.__class__.__name__ in {
                    "EndpointConnectionError", "ConnectionClosedError", "ReadTimeoutError", "ConnectTimeoutError",
                }
                if not transient or attempt + 1 == self.attempts:
                    raise
                self.sleep(min(8, 2**attempt) + random.uniform(0, 0.25))

    def _get(self, key: str) -> bytes | None:
        def read():
            result = self.client.get_object(Bucket=self.bucket, Key=key)
            stream = result["Body"]
            try:
                return stream.read()
            finally:
                stream.close()

        try:
            return self._retry(read)
        except Exception as error:
            if _error_code(error) in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise

    def _ensure(self, key: str, body: bytes) -> bool:
        existing = self._get(key)
        if existing is not None:
            require(digest(existing) == digest(body) and len(existing) == len(body), "Remote object checksum mismatch")
            return False
        try:
            self._retry(lambda: self.client.put_object(
                Bucket=self.bucket, Key=key, Body=body, IfNoneMatch="*",
                ChecksumSHA256=base64.b64encode(bytes.fromhex(digest(body))).decode("ascii"),
                ServerSideEncryption="AES256",
            ))
        except Exception as error:
            if _error_code(error) not in {"PreconditionFailed", "412"}:
                raise
        verified = self._get(key)
        require(verified is not None and digest(verified) == digest(body) and len(verified) == len(body),
                "Uploaded object checksum mismatch")
        return True

    def _state_path(self, batch_id: str):
        target = digest(json_bytes({"bucket": self.bucket, "namespace": self.namespace}))
        return safe_path(self.store.root, f"metadata/transfers/{target}/{batch_id}.json")

    def _pin(self, batch: PreparedBatch) -> dict:
        path = self._state_path(batch.batch_id)
        if path.exists():
            state = parse_json(path.read_bytes())
            require(state.get("receipt") == batch.receipt, "Transfer identity was previously pinned to different bytes")
            for attempt in state["attempts"]:
                if attempt["status"] == "running":
                    attempt.update(status="interrupted", recovered_at=utc_now())
            return state
        state = {"receipt": batch.receipt, "status": "pending", "attempts": []}
        atomic_write(path, json_bytes(state))
        return state

    def transfer(self, manifest: dict) -> dict:
        with self.store.lock():
            batch = prepare_batch(self.store, manifest, self.namespace)
            state = self._pin(batch)
            attempt = {"started_at": utc_now(), "status": "running"}
            state["attempts"].append(attempt)
            state["status"] = "pending"
            atomic_write(self._state_path(batch.batch_id), json_bytes(state))
            uploaded = 0
            try:
                ready = self._get(self.receipt_key(batch.batch_id))
                if ready is not None:
                    require(ready == json_bytes(batch.receipt), "Remote ready receipt conflicts with pinned batch")
                for relative, body in batch.artifacts.items():
                    uploaded += self._ensure(self.key(relative), body)
                # Ready is published only after all dependencies were independently read back.
                self._ensure(self.receipt_key(batch.batch_id), json_bytes(batch.receipt))
            except Exception as error:
                attempt.update(status="failed", error_code="integrity" if isinstance(error, IntegrityError) else "s3_error")
                atomic_write(self._state_path(batch.batch_id), json_bytes(state))
                if isinstance(error, IntegrityError):
                    raise
                raise CloudError("S3 transfer failed. Check permissions, connectivity and the transfer journal.") from None
            attempt.update(status="success", completed_at=utc_now(), uploaded=uploaded)
            state.update(status="success", completed_at=utc_now())
            atomic_write(self._state_path(batch.batch_id), json_bytes(state))
            report = {"batch_id": batch.batch_id, "status": "success", "uploaded": uploaded,
                      "verified_files": len(batch.artifacts), "ready_key": self.receipt_key(batch.batch_id)}
            LOGGER.info(json_bytes({"event": "s3_transfer_complete", **report}).decode().strip())
            return report

    def verified_batch(self, manifest: dict) -> PreparedBatch:
        """Verify remote readiness and every object against a pinned local archive."""
        batch = prepare_batch(self.store, manifest, self.namespace)
        state = self._pin(batch)
        state["status"] = "pending"
        atomic_write(self._state_path(batch.batch_id), json_bytes(state))
        try:
            ready = self._get(self.receipt_key(batch.batch_id))
            require(ready == json_bytes(batch.receipt), "Transferred batch has no matching ready receipt")
            for relative, body in batch.artifacts.items():
                remote = self._get(self.key(relative))
                require(remote is not None and digest(remote) == digest(body) and len(remote) == len(body),
                        "Transferred batch object checksum mismatch")
        except Exception as error:
            state["verification_error"] = "integrity" if isinstance(error, IntegrityError) else "s3_error"
            atomic_write(self._state_path(batch.batch_id), json_bytes(state))
            if isinstance(error, IntegrityError):
                raise
            raise CloudError("Transferred batch verification failed. Check the transfer journal.") from None
        # Completion can be recovered if the process stopped after publishing ready.
        state.pop("verification_error", None)
        state.update(status="success", completed_at=utc_now())
        atomic_write(self._state_path(batch.batch_id), json_bytes(state))
        return batch
