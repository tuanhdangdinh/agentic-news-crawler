"""MinIO object storage client for persisting crawl results."""

from __future__ import annotations

import asyncio
import io
import json
import os
from dataclasses import dataclass

import structlog
from minio import Minio
from minio.error import S3Error

logger = structlog.get_logger(__name__)


@dataclass
class StorageSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool

    @classmethod
    def from_env(cls) -> StorageSettings:
        return cls(
            endpoint=os.environ.get("MINIO_ENDPOINT", ""),
            access_key=os.environ.get("MINIO_ACCESS_KEY", ""),
            secret_key=os.environ.get("MINIO_SECRET_KEY", ""),
            bucket=os.environ.get("MINIO_BUCKET", "crawl-results"),
            secure=os.environ.get("MINIO_SECURE", "false").lower() == "true",
        )

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)


def _make_client(settings: StorageSettings) -> Minio:
    return Minio(
        endpoint=settings.endpoint,
        access_key=settings.access_key,
        secret_key=settings.secret_key,
        secure=settings.secure,
    )


def _put_result_sync(job_id: str, payload: dict, settings: StorageSettings) -> None:
    client = _make_client(settings)
    if not client.bucket_exists(settings.bucket):
        client.make_bucket(settings.bucket)
    payload_copy = {**payload, "meta": {**payload.get("meta", {}), "job_id": job_id}}
    data = json.dumps(payload_copy, ensure_ascii=False).encode()
    client.put_object(
        bucket_name=settings.bucket,
        object_name=f"crawl-{job_id}.json",
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/json",
    )
    logger.debug("uploaded result", job_id=job_id, bucket=settings.bucket)


def _get_result_sync(job_id: str, settings: StorageSettings) -> bytes | None:
    client = _make_client(settings)
    try:
        response = client.get_object(settings.bucket, f"crawl-{job_id}.json")
        try:
            return response.read()
        finally:
            response.close()
    except S3Error as exc:
        if exc.code == "NoSuchKey":
            return None
        raise


def _list_results_sync(settings: StorageSettings) -> list[dict]:
    client = _make_client(settings)
    results = []
    for obj in client.list_objects(settings.bucket):
        name: str = obj.object_name
        if not name.startswith("crawl-") or not name.endswith(".json"):
            continue
        job_id = name[len("crawl-") : -len(".json")]
        results.append({
            "job_id": job_id,
            "size_bytes": obj.size,
            "last_modified": obj.last_modified.isoformat(),
        })
    return results


def _delete_result_sync(job_id: str, settings: StorageSettings) -> None:
    client = _make_client(settings)
    client.remove_object(settings.bucket, f"crawl-{job_id}.json")


async def put_result(job_id: str, payload: dict, settings: StorageSettings) -> None:
    """Upload result payload to MinIO as crawl-{job_id}.json, injecting job_id into meta."""
    await asyncio.to_thread(_put_result_sync, job_id, payload, settings)


async def get_result(job_id: str, settings: StorageSettings) -> bytes | None:
    """Fetch raw bytes for crawl-{job_id}.json from MinIO. Returns None if not found."""
    return await asyncio.to_thread(_get_result_sync, job_id, settings)


async def list_results(settings: StorageSettings) -> list[dict]:
    """List all stored crawl results. Returns [{job_id, size_bytes, last_modified}]."""
    return await asyncio.to_thread(_list_results_sync, settings)


async def delete_stored_result(job_id: str, settings: StorageSettings) -> None:
    """Delete crawl-{job_id}.json from MinIO."""
    await asyncio.to_thread(_delete_result_sync, job_id, settings)
