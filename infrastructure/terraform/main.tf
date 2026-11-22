terraform {
  required_version = ">= 1.6, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type = string
}

variable "bucket_name" {
  type = string
}

variable "runtime_source_role_arn" {
  description = "Exact existing project role ARN allowed to assume the transfer role."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/managed/AccountFullAccessRole$", var.runtime_source_role_arn))
    error_message = "Supply the verified project AccountFullAccessRole ARN, not a session ARN or wildcard."
  }
}

variable "archive_namespace" {
  type = string
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]+$", var.archive_namespace))
    error_message = "Use the same single-component namespace as the transfer CLI."
  }
}

resource "aws_s3_bucket" "archive" {
  bucket        = var.bucket_name
  force_destroy = false
  tags = {
    Project = "financial-data-engineering-platform"
  }
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "tls_only" {
  bucket = aws_s3_bucket.archive.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "RequireTLS"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.archive.arn, "${aws_s3_bucket.archive.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# Deletion is reserved for a separate teardown/admin identity.
resource "aws_iam_policy" "transfer" {
  name_prefix = "financial-data-transfer-"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.archive.arn}/${var.archive_namespace}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.archive.arn
        Condition = {
          StringLike = { "s3:prefix" = ["${var.archive_namespace}/*"] }
        }
      }
    ]
  })
}

resource "aws_iam_role" "runtime" {
  name                 = "FdepTransferRuntime"
  path                 = "/fdep/"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { AWS = var.runtime_source_role_arn }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "runtime" {
  role       = aws_iam_role.runtime.name
  policy_arn = aws_iam_policy.transfer.arn
}

output "runtime_role_arn" {
  value = aws_iam_role.runtime.arn
}

output "bucket_name" {
  value = aws_s3_bucket.archive.id
}

output "transfer_policy_arn" {
  value = aws_iam_policy.transfer.arn
}
