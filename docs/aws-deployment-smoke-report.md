# Controlled AWS deployment and runtime smoke test

For the current Snowflake account, cost basis and approval gates, see the [Phase 3A assessment](phase3a-readiness.md). The Snowflake assumptions below describe the earlier phase.

## Authorized scope and preflight

The user explicitly approved the eight reviewed resources and bounded disposable-object tests in us-east-2, with a $5 reserve and $15 planned ceiling. STS verified the expected account and non-root managed source role. Full account/session identifiers remain private local evidence. A fresh account-aware preapply plan was compared programmatically with the reviewed plan: configuration, variables and resource_changes matched exactly; all eight actions were create-only. The original reviewed plan SHA-256 was rechecked as 5e33e3a6321eb240aa0cdacf01d159257742c7dd68daaede20460502d24bbf78.

The verified preapply plan was applied: **8 added, 0 changed, 0 destroyed**. No additional resources, policy broadening or source changes were required. The private evidence directory is `.local/runtime-identity-review`; Terraform state stays under the ignored Terraform state path. Preserve state and lock files for teardown.

## Live resource verification

All eight resources were read and checked through administrator APIs after creation:

- Dedicated bucket `<dedicated-demo-bucket>` reports us-east-2.
- All four public-access blocks are enabled.
- Ownership is BucketOwnerEnforced.
- Default encryption is AES256 SSE-S3.
- The TLS-only bucket policy's nonsecure-transport Deny is present. No plaintext credential-bearing request was sent to test it.
- The transfer policy allows only GetObject/PutObject under fdep-demo/* and ListBucket with the reviewed prefix condition.
- FdepTransferRuntime has path /fdep/, one-hour maximum sessions, exactly the reviewed source-role trust and no permissions boundary.
- Exactly the expected transfer policy is attached; no inline runtime policies are present.

A postapply Terraform plan refreshed all eight resources and returned **No changes**, exit code 0. This independently reconciles the live resources with the approved configuration.

## Actual runtime results

The local fdep-transfer profile uses role_arn, source_profile=fdep-project-terraform, a named session and 3600-second duration. STS returned **assumed-role/FdepTransferRuntime**, in the same account as the source. Temporary credentials were handled by the SDK; no long-lived keys or exported credential values were printed or saved.

| Check | Actual result |
| --- | --- |
| Prefix-scoped ListObjectsV2 | HTTP 200 |
| Missing object within namespace through uploader _get | Recognized as absent (NoSuchKey/404 behavior), no unexpected 403 |
| Conditional PUT with AES256 and SHA-256 | HTTP 200 |
| GET, exact bytes, returned SHA-256 and encryption | HTTP 200; all matched |
| Existing-object uploader replay | _ensure returned False; verified bytes reused |
| Repeated conditional PUT | HTTP 412 PreconditionFailed |
| GET outside namespace | HTTP 403 AccessDenied |
| PUT outside namespace | HTTP 403 AccessDenied |
| Listing outside namespace | HTTP 403 AccessDenied |
| Runtime DeleteObject | HTTP 403 AccessDenied |
| Explicit uploader _get outside namespace | 403 exception propagated: fail closed |
| Fresh uploader _ensure path followed by replay | First write True, repeated call False |
| Administrator disposable-object cleanup | HTTP 204; final bucket listing empty |

The second uploader-path check confirms actual first-write behavior, not just direct SDK PUT behavior. Evidence is `smoke-results.json` (HTTP statuses, request identifiers, digest and sanitized identity), `final-smoke.json`, `apply-output.txt`, `preapply.json`, `preapply-output.txt` and `postapply-output.txt`. Local smoke scripts and fresh local working directories are ignored artifacts; no financial source archive was modified. No complete dataset was transferred.

## Costs and retention recommendation

Only a few dozen requests and two tiny disposable bodies were used. At the retained Ohio request prices, the expected S3 request charge is below $0.01 before applicable allowances/credits. The previous $0.05 AWS smoke allowance remains adequate. Actual posted billing, tax and credit application were not queried or verified; billing can lag. No unexpected service charges were observed in API responses, but that is not a billing reconciliation. No paid Cost Explorer queries, new monitoring resources or account upgrades were introduced.

The bucket is now empty and unversioned; no compute, warehouse or continuously running service exists from this deployment. The IAM roles/policies and empty bucket can be retained temporarily for the upcoming separately authorized Snowflake demonstration without a planned standing compute charge. **Recommend temporary retention**, with teardown if that demonstration is deferred or abandoned. There are still administration/security responsibilities, and future requests or data retention can incur charges. The full prospective demonstration estimate remains approximately $1.30 before tax/credits, with $5 reserve and $15 ceiling; actual Snowflake trial offer, balance and generation availability remain unverified.

Snowflake has not been activated. No financial warehouse load, commit or publication occurred. No runtime source code changed, so regression tests were not repeated for this operational-only step; the prior 17 relevant Python and Terraform mock tests remain the latest automated checks. The live checks above add deployment evidence rather than replace regression tests.

## Next steps and teardown

AWS runtime smoke verification is complete. Obtain separate approval for Snowflake AWS / US East (Ohio) / Standard trial activation and setup, followed by the already documented staged financial-data demonstration. Keep runtime calls on fdep-transfer, provisioning/cleanup on the separate approved administrator identity. Review credentials and budget before the next run; never transfer with administrator credentials merely to avoid a failure.

No cloud cleanup beyond disposable-object removal was executed. If teardown is selected: stop writers, confirm this dedicated bucket is empty, generate/review a destroy plan with the same state and `.local/runtime-identity-review/demo.tfvars.json`, and obtain/confirm authorization for destruction. Terraform handles the managed attachment/role/policy dependency ordering. Verify all eight resources are absent afterwards and reconcile billing after its reporting delay. Preserve local source data and historical evidence; do not remove the project account or its AWS-managed roles. End temporary sessions when no longer needed. No unneeded billable compute is running.
