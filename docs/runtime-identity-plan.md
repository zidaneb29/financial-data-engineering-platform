# Runtime identity preparation and revised plan

For the current Snowflake account, cost basis and approval gates, see the [Phase 3A assessment](phase3a-readiness.md). The Snowflake assumptions below describe the earlier phase.

**Deployment and teardown:** The eight-resource deployment reconciled with Terraform state, and live role assumption, prefix checks, missing-object reads and replay passed. After the Phase 3B demonstration, all eight resources were destroyed and independently verified absent. The existing source role remained in place. The design and pending checks below describe the predeployment review. [AWS smoke results](aws-deployment-smoke-report.md) · [Teardown verification](phase7-publication.md#verification-record)

## Design and account evidence

The custom role FdepTransferRuntime is proposed under /fdep/, outside AWS-managed paths. Its trust names exactly the verified /managed/AccountFullAccessRole IAM role ARN, not an STS session, wildcard principal or account root. It allows only sts:AssumeRole, with a maximum one-hour chained session. No MFA condition was invented: AWS project browser login handles source authentication, and propagation of IAM-user MFA context has not been established. AWS-managed project roles are unchanged.

The runtime receives one dedicated managed policy through one Terraform attachment: GetObject/PutObject under the dedicated bucket's fdep-demo/* prefix, and ListBucket conditioned on s3:prefix matching fdep-demo/*. No deletion, IAM administration, customer-key KMS, resource creation or administrative access is granted. Prefix-scoped listing is narrower than the previous six-resource policy.

**Missing-object limitation:** the uploader first GETs potentially absent objects and treats only NoSuchKey/404/NotFound as absence. AWS documents that missing-object status depends on ListBucket authorization. The effect of a prefix-conditioned ListBucket grant on these unlisted GET requests has not been tested live. A 403 must fail closed; do not convert AccessDenied to absence or silently broaden listing permissions. The first separately authorized smoke test must verify an absent key inside the prefix, successful upload/readback, and denial outside the prefix. Stop if authorization is incompatible; obtain approval for any policy/selection change. [S3 GetObject behavior](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)

The expired source session was refreshed using aws login. New STS identity, GetRole, attached-policy and inline-policy reads succeeded. The source remains a non-root managed project role with AdministratorAccess, no inline policies and no reported permissions boundary. IAM SimulatePrincipalPolicy now executed successfully: CreateRole, AttachRolePolicy, CreatePolicy and AssumeRole were all **allowed**, with AllowedByOrganizations=true and no missing context for the hypothetical role/policy resources. Private responses are retained under .local/runtime-identity-review. The simulation tests source authorization; it does not test a nonexistent target's trust, all creation parameters, permissions propagation, S3 authorization or actual role assumption. No role was created or assumed. Effective organization restrictions were not independently enumerated in full.

## Actual plan and verification

Terraform 1.17.2, signed AWS provider 6.73.0, region us-east-2. The actual account-aware plan is **8 additions, 0 changes, 0 deletions**:

1. Dedicated S3 bucket.
2. Public-access block (all four enabled).
3. BucketOwnerEnforced ownership.
4. AES256 SSE-S3 encryption.
5. TLS-only bucket policy.
6. Namespace-scoped transfer managed policy.
7. /fdep/FdepTransferRuntime role.
8. Runtime policy attachment.

The bucket remains <dedicated-demo-bucket>; global availability is not reserved or proven. No existing state or resources were changed. Earlier six-resource binary plans remain preserved but are superseded for this design.

Evidence: .local/runtime-identity-review/runtime.tfplan, plan.json, plan-output.txt and simulation.json. Plan SHA-256: **5e33e3a6321eb240aa0cdacf01d159257742c7dd68daaede20460502d24bbf78**. Local JSON inspection verified all eight actions are create-only and the trust principal exactly matches the configured verified source role.

Formatting was applied; recursive fmt -check passed. validate returned valid=true, zero errors/warnings. Terraform mock plan: **1 passed, 0 failed**, asserting source trust, custom path, bounded session, namespace policy, private access, ownership and encryption. An initial test encountered unknown bucket ARN during planning; a mock-only plan-time ARN override corrected it. Relevant Python tests on 3.11.9: **17 passed in 7.08s** (cloud CLI, SDK and transfer). No Python ingestion/loader implementation changed. The prior full suite result remains 128 passing; it was not rerun in this narrowly scoped change.

## Authentication after separately approved provisioning

No live AWS profile was overwritten for the proposed role. A private ready-to-review example exists at .local/runtime-identity-review/runtime-profile.example. After the role exists, review existing config before adding a fresh profile to the real user's .aws/config:

```ini
[profile fdep-transfer]
role_arn = <runtime_role_arn Terraform output>
source_profile = fdep-project-terraform
role_session_name = fdep-transfer-demo
duration_seconds = 3600
region = us-east-2
```

The source profile already bridges AWS CLI temporary browser credentials through credential_process, using the working forward-slash executable path. boto3's standard assume-role provider supports role_arn/source_profile and refreshes temporary credentials; no CLI code change or long-lived key is needed. Set AWS_PROFILE=fdep-transfer and AWS_REGION=us-east-2 for both transfer and load. Clear unrelated AWS credential environment overrides in that session. After authorization, verify STS reports assumed-role/FdepTransferRuntime, inspect attached policies/boundary, and test allowed/denied S3 operations deliberately. Do not claim success from the source login or simulated permission alone.

## Costs, deployment gates and teardown

AWS Ohio and prospective Snowflake AWS / US East (Ohio) / Standard remain the targets. IAM role/policy setup introduces no compute service. Using retained public regional rates, the planned demonstration remains approximately **$1.30 before tax/credits**, $5 operating reserve and **$15 maximum planned expenditure**. This includes $0.05 AWS allowance, 30 charged Generation 1 X-Small Snowflake minutes at $2/credit and cloud-service/storage reserves. Snowflake trial terms, balance and Generation 1 availability remain unverified; no trial is activated. Refresh billing/credit balances before execution; credits, alerts and suspension monitors are not hard dollar caps.

Recommendation: **conditional go for requesting approval of a controlled eight-resource AWS provisioning and scoped smoke test**, not a claim of verified runtime operation. No-go for unattended deployment or full warehouse loading until real assumption, prefix/missing-key behavior, readback and replay pass. Re-plan if configuration or account inputs change. Snowflake activation/setup requires separate approval.

After future authorized work: stop writers; preserve reconciliation evidence; disable/suspend and remove dedicated Snowflake objects if created; empty only this dedicated S3 bucket with the administrator identity; review Terraform destroy using the same state and variables. Terraform removes the policy attachment before deleting its role/policy. Do not manually detach Terraform-managed attachments before destruction. Confirm role, attachment, policy and bucket absence; preserve local archives; reconcile delayed billing; end temporary source sessions. force_destroy=false intentionally prevents implicit bucket-content removal. No teardown is needed now because no cloud resource exists from this work.
