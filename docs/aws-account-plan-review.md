# AWS Ohio account-aware plan review

For the current Snowflake account, cost basis and approval gates, see the [Phase 3A assessment](phase3a-readiness.md). The Snowflake assumptions below describe the earlier phase.

## Verified execution

The user confirmed the existing project's assigned region is **us-east-2 (Ohio)**. AWS CLI 2.42.1 browser login completed with temporary credentials for the existing project's **AccountFullAccessRole** assumed-role identity. STS GetCallerIdentity succeeded; the principal is non-root. Full account/session identifiers are intentionally omitted from this public-facing document. Local profiles are fdep-project-signin and fdep-project-terraform. No access keys were created.

The role is under /managed/, has AWS-managed AdministratorAccess, no inline role policies and no permissions boundary reported by GetRole. GetPolicyVersion confirmed its Allow */* statement. These are broad credentials, not an enforced read-only identity. Operations were limited to approved read APIs and local planning. Organizations ListParents returned AccessDeniedException, so complete effective organization controls remain unverified. AWS-managed project SCPs/RCPs can still restrict administrator actions. No permissions were changed.

The initial login failed because the noninteractive executor had no Windows console and no saved profile region. Saving the confirmed region and retrying with a terminal succeeded. The first credential-process path using Windows backslashes/quotes failed in Terraform although direct credential export worked. Setting its executable path to the resolved absolute path to the local AWS CLI executable corrected the bridge. Credential JSON was checked only for required field presence; its contents were not printed or saved. Tokens remain in the standard user AWS cache.

## Saved plan

Private evidence directory: `.local/aws-ohio-preparation-efa4ad458fa34e72b8be9a5d50f1a6a4`.

Terraform 1.17.2 / AWS provider 6.73.0 generated aws.tfplan using fdep-project-terraform, the fresh demo.tfvars.json and the existing configuration. aws-plan.json was exported locally and checked programmatically: exactly six resource changes, all create-only, region us-east-2. Plan hash SHA-256: `ddf450b985d0144ba2473eb8a79ca6d3e9ffcf868b90cd2b40ec43adc3902053`.

| Resource | Reviewed intention |
| --- | --- |
| aws_s3_bucket.archive | <dedicated-demo-bucket>; force_destroy=false |
| aws_s3_bucket_public_access_block.archive | All four public-access protections true |
| aws_s3_bucket_ownership_controls.archive | BucketOwnerEnforced |
| aws_s3_bucket_server_side_encryption_configuration.archive | AES256 S3-managed encryption |
| aws_s3_bucket_policy.tls_only | Deny non-TLS access; final ARN-dependent JSON resolves at apply |
| aws_iam_policy.transfer | GetObject/PutObject under fdep-demo namespace and ListBucket on dedicated bucket; attachment excluded |

Plan: **6 add, 0 change, 0 destroy**. Bucket availability is not reserved or proven. Some provider-computed defaults and ARN-dependent policies remain unknown until creation; source expressions were reviewed. A successful new-resource plan does not test create permissions or prove deployment compatibility. The managed /managed/ role is protected by AWS project controls; do not assume the planned transfer policy can be attached to it. A separate approved least-privilege runtime identity design remains required before transfer. No role attachment or alternative identity was created.

## Cost and remaining prerequisites

The user reports AWS Free credits of **$100 with 182 days remaining**; no upgrade was performed. Ohio S3 public pricing was fetched without account credentials and saved as s3-ohio-pricing.json: $0.023/GB-month, $0.005/1,000 tier-1 requests and $0.0004/1,000 tier-2 requests. For the previous demonstration allowances, S3 storage/requests are below $0.01; retain a conservative **$0.05 AWS reserve** including readback/transfer pending exact allowance reconciliation. No S3 service requests or object transfers were executed.

Snowflake is uncreated and unactivated. Its published Ohio Standard rate is $2/credit and ordinary storage $23/TB-month; a hypothetical Generation 1 X-Small 30-minute demonstration plus prior reserves gives approximately **$1.30 total before taxes/credits**, rounded conservatively from the prior $1.28 model. This is not a Snowflake account quote or verified trial offer. Retain a $5 operating reserve and $15 maximum planned expenditure. [Snowflake current consumption table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf) · [Ohio S3 price evidence](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/us-east-2/index.json)

Before deployment: separately approve cloud creation; verify the effective project restrictions and an allowed scoped runtime identity/policy attachment; approve the bucket and plan inventory; refresh authentication and re-plan if inputs/provider/configuration change; resolve Snowflake account activation/region/edition separately. Snowflake Ohio is a supported region, but account creation terms and Generation 1 availability remain unverified. Existing deployment-costs.md Northern Virginia assumptions are superseded for AWS by this Ohio review. No AWS/Snowflake resources were created, Terraform apply run, IAM permissions changed, commits made or artifacts published.

Teardown remains the controlled-deployment.md procedure: stop writers, capture reconciliation evidence, suspend/drop the dedicated Snowflake resources if later authorized, remove only dedicated S3 objects, detach any separately approved transfer policy, review a destroy plan, destroy dedicated Terraform resources, verify absence and later reconcile billing. No teardown actions are authorized or needed for this planning-only session. Local credentials may be ended with `aws logout --profile fdep-project-signin`; do not print/export credentials for evidence.

Only local configuration and documentation changed, so Python ingestion was not modified and its 128-test suite was not repeated for this authentication session. The actual account-aware plan and its JSON action checks are the relevant new validation.
