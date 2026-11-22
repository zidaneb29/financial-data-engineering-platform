mock_provider "aws" {}

override_resource {
  target          = aws_s3_bucket.archive
  override_during = plan
  values = {
    arn = "arn:aws:s3:::fdep-offline-example-not-a-real-target"
    id  = "fdep-offline-example-not-a-real-target"
  }
}

variables {
  region                  = "us-east-1"
  bucket_name             = "fdep-offline-example-not-a-real-target"
  archive_namespace       = "fdep-demo"
  runtime_source_role_arn = "arn:aws:iam::123456789012:role/managed/AccountFullAccessRole"
}

run "controlled_demo_plan" {
  command = plan

  assert {
    condition     = jsondecode(aws_iam_role.runtime.assume_role_policy).Statement[0].Principal.AWS == var.runtime_source_role_arn && aws_iam_role.runtime.path == "/fdep/" && aws_iam_role.runtime.max_session_duration == 3600
    error_message = "Runtime trust must name only the verified source role and use bounded sessions outside managed paths."
  }
  assert {
    condition     = jsondecode(aws_iam_policy.transfer.policy).Statement[1].Condition.StringLike["s3:prefix"][0] == "fdep-demo/*" && toset(jsondecode(aws_iam_policy.transfer.policy).Statement[0].Action) == toset(["s3:GetObject", "s3:PutObject"])
    error_message = "Runtime permissions must be restricted to namespace reads/writes and prefix-scoped listing."
  }

  assert {
    condition     = aws_s3_bucket.archive.force_destroy == false
    error_message = "Teardown must require explicit object removal."
  }
  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.archive.block_public_acls,
      aws_s3_bucket_public_access_block.archive.block_public_policy,
      aws_s3_bucket_public_access_block.archive.ignore_public_acls,
      aws_s3_bucket_public_access_block.archive.restrict_public_buckets,
    ])
    error_message = "All public access protections must remain enabled."
  }
  assert {
    condition     = one(aws_s3_bucket_ownership_controls.archive.rule).object_ownership == "BucketOwnerEnforced"
    error_message = "Object ACLs must be disabled."
  }
  assert {
    condition     = one(one(aws_s3_bucket_server_side_encryption_configuration.archive.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    error_message = "The demonstration must use S3-managed encryption."
  }
}
