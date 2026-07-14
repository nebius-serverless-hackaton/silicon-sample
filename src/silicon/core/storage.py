import uuid

import boto3
import duckdb

from silicon.core.config import get_settings


def s3_client():
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.nebius_s3_endpoint_url or None,
        region_name=settings.nebius_s3_region,
        aws_access_key_id=settings.nebius_s3_access_key_id or None,
        aws_secret_access_key=settings.nebius_s3_secret_access_key or None,
    )


def upload_file(local_path, key: str) -> None:
    settings = get_settings()
    s3_client().upload_file(str(local_path), settings.nebius_s3_bucket, key)


def duckdb_connection() -> duckdb.DuckDBPyConnection:
    # always read-write: DuckDB rejects same-file connections with differing
    # configs in one process, and pipeline steps overlap connections freely
    settings = get_settings()
    con = duckdb.connect(settings.duckdb_path)
    con.execute("INSTALL httpfs; LOAD httpfs;")
    if settings.nebius_s3_endpoint_url:
        # DuckDB's s3_endpoint wants host[:port] only, no scheme
        endpoint = settings.nebius_s3_endpoint_url.split("://", 1)[-1]
        con.execute(f"SET s3_endpoint='{endpoint}';")
        con.execute(f"SET s3_region='{settings.nebius_s3_region}';")
        con.execute("SET s3_url_style='path';")
        if settings.nebius_s3_access_key_id:
            con.execute(f"SET s3_access_key_id='{settings.nebius_s3_access_key_id}';")
            con.execute(
                f"SET s3_secret_access_key='{settings.nebius_s3_secret_access_key}';"
            )
    return con


def check_storage() -> str:
    settings = get_settings()
    client = s3_client()

    # MaxKeys keeps this cheap regardless of how large the bucket already is
    listing = client.list_objects_v2(Bucket=settings.nebius_s3_bucket, MaxKeys=5)
    n_listed = listing.get("KeyCount", 0)

    key = f"_healthcheck/{uuid.uuid4().hex}.txt"
    payload = b"silicon storage check"

    client.put_object(Bucket=settings.nebius_s3_bucket, Key=key, Body=payload)
    body = client.get_object(Bucket=settings.nebius_s3_bucket, Key=key)["Body"].read()
    client.delete_object(Bucket=settings.nebius_s3_bucket, Key=key)

    if body != payload:
        raise RuntimeError(f"round-trip mismatch: wrote {payload!r}, read {body!r}")

    return f"OK - listed {n_listed} object(s), round-tripped s3://{settings.nebius_s3_bucket}/{key}"
