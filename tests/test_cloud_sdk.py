import base64
import hashlib
import io

import boto3
from botocore.stub import Stubber
import snowflake.connector

from storage.local import LocalStore
from storage.transfer import S3Transfer


def test_boto3_conditional_put_parameters_and_readback_are_valid_offline(tmp_path):
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="offline-test-id",
        aws_secret_access_key="offline-test-value",
    )
    transfer = S3Transfer(LocalStore(tmp_path), client, bucket="test-bucket", namespace="portfolio")
    key, body = "portfolio/raw/test.json", b'{"synthetic":true}\n'
    checksum = base64.b64encode(hashlib.sha256(body).digest()).decode()
    with Stubber(client) as stub:
        stub.add_client_error(
            "get_object", service_error_code="NoSuchKey", http_status_code=404,
            expected_params={"Bucket": "test-bucket", "Key": key},
        )
        stub.add_response("put_object", {"ETag": '"irrelevant"'}, {
            "Bucket": "test-bucket", "Key": key, "Body": body, "IfNoneMatch": "*",
            "ChecksumSHA256": checksum, "ServerSideEncryption": "AES256",
        })
        stub.add_response("get_object", {"Body": io.BytesIO(body)}, {"Bucket": "test-bucket", "Key": key})
        assert transfer._ensure(key, body)
        stub.assert_no_pending_responses()


def test_snowflake_connector_imports_without_connecting():
    assert callable(snowflake.connector.connect)
