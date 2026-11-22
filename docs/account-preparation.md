# Account preparation before deployment approval

For the current Snowflake account, cost basis and approval gates, see the [Phase 3A assessment](phase3a-readiness.md). The Snowflake assumptions below describe the earlier phase.

**Latest status:** Existing-project login completed in the user-confirmed **us-east-2** region with a non-root assumed role. The local credential-process bridge and account-aware Terraform plan succeeded. See [verified Ohio account plan](aws-account-plan-review.md) for evidence, permission limitations, updated estimate and approval blockers. Earlier us-east-1 targets and pending-login instructions below are historical context.

## Confirmed account choices

The user confirms a newly created AWS **Free** account, **$100** promotional credits with **182 days** remaining as reported November 20, 2026, and intended region **us-east-1**. Snowflake has **not** been created or activated. Its intended configuration is AWS Northern Virginia / Standard. Credit information is user-verified; no account identity or permissions have been verified through authenticated CLI access. Do not activate a Snowflake trial, upgrade an account or create resources during this preparation step.

New eligible AWS customers receive $100 at signup and can earn up to $100 more. The Free plan ends after six months or credit exhaustion, whichever comes first. Confirm the actual plan, signup date, available services, credit balance and expiration in Billing; do not run extra services to earn credits. Older accounts and previously eligible customers can have different terms. [AWS plan details](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html) · [Free Tier FAQ](https://aws.amazon.com/free/free-tier-faqs/)

Snowflake's documented trial lasts 30 days or until its free balance is depleted. The actual offered balance and eligibility must be checked at signup; no balance is assumed here. Trial activation starts that clock and requires separate authorization. Choose Standard / AWS / US East (Northern Virginia) if the offer supports it. Do not add a payment card or upgrade. An existing organization account may be preferable if its administrator approves the dedicated demonstration. [Trial terms](https://docs.snowflake.com/en/user-guide/admin-trial-account)

## Installed tools

AWS CLI **2.42.1** is installed for the current user at `%LOCALAPPDATA%\Programs\Amazon\AWSCLIV2\aws.exe`. The official current-user MSI had a Valid Authenticode signature from Amazon Web Services, Inc.; installer exit code was 0. Reopen PowerShell to pick up its user PATH.

Terraform **1.17.2** is a portable installation at `.local/tools/terraform-1.17.2/terraform.exe`. Its official Windows AMD64 ZIP SHA-256 is `2244b7a379ea8c4b224a2eab411b7288f41ef36316fca27ae4b51b1cf2a53024`, matching the downloaded HashiCorp checksum file over HTTPS. A separate detached-signature check was not performed. No permanent Terraform PATH or system security changes were made. Provider initialization selected HashiCorp-signed AWS **6.73.0**, recorded in the dependency lock file.

From the repository root, these session-only settings expose both tools:

```powershell
$env:PATH = "$env:LOCALAPPDATA\Programs\Amazon\AWSCLIV2;$(Get-Location)\.local\tools\terraform-1.17.2;$env:PATH"
aws --version
terraform version
```

## Secure AWS sign-in

**Current account correction:** The user confirmed the new AWS experience lacks IAM console-access creation and canceled creating fdep-operator. The supported recommendation is existing-project browser login; see the superseding findings in iam-console-setup.md. Do not apply the conventional IAM-user instructions or inspection policy below to this account. Team members receive project admin access, so an invitation does not satisfy read-only planning access. No invitations, login, account changes or permission attachments have been performed. The latest authorization is investigation only.

Enable MFA for the account root identity and reserve it for account/billing administration. Use an approved non-root human identity for this project. Have the account administrator establish its permissions; creating IAM identities or attaching policies is outside the current local-install work.

For an existing IAM Identity Center organization, use its supplied start URL and SSO region. The SSO region can differ from the deployment region:

```powershell
aws configure sso --profile fdep-demo
aws sso login --profile fdep-demo
```

For a personal account without Identity Center, the current CLI supports browser sign-in using a non-root console identity with the `SignInLocalDevelopmentAccess` permission. Use a distinct login profile and a process profile so the existing Python SDK and Terraform need no new credential-provider dependency:

```powershell
aws login --profile fdep-signin --region us-east-1
aws configure set credential_process 'aws configure export-credentials --profile fdep-signin --format process' --profile fdep-demo
aws configure set region us-east-1 --profile fdep-demo
```

This exports temporary credentials directly to the requesting tool. **Do not run export-credentials separately, enable debug logging, or paste its output.** Ensure `aws.exe` is on the session PATH. Review any existing profile before writing these named profiles; choose fresh names if they already exist. CLI tokens stay under the user's `.aws` directory. Never create root access keys or save credentials in the repository. [Browser login and process-profile compatibility](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html) · [SSO configuration](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)

Once locally signed in, inspect identity locally using `aws sts get-caller-identity --profile fdep-demo --no-cli-pager`. It creates no resources. Share only confirmation of the intended account and identity type, never session tokens. The preparation has not executed authenticated account calls.

The provisioning identity needs lifecycle and read permissions for the dedicated S3 bucket and its policy, encryption, ownership and public-access settings, plus creation/read/deletion of the generated IAM policy. The six-resource plan creates no operator identity or policy attachment. The runtime identity receives only namespace-scoped GetObject/PutObject plus ListBucket for that dedicated bucket. The separate teardown identity needs object deletion, bucket destruction and policy detachment/deletion. Exact administrative permissions must be reviewed against the real role, organizational policies and provider plan before approval; broad AdministratorAccess is not a runtime requirement.

## Billing and Snowflake preparation

In AWS Billing, record Free-plan status, credits, expiry and existing spend locally. Review Free Tier alerts and budget notification options; avoid paid budget actions or new monitoring services during preparation. Use $5 as the operating reserve and $15 as the planned ceiling. Billing notifications can lag and do not enforce a dollar cap. Do not upgrade the Free plan to overcome service restrictions without separate approval.

After separately authorized Snowflake activation, confirm Standard edition, AWS region, trial balance/expiry and account identifier in Snowsight before any warehouse operation. Use MFA for administrators. The prepared SQL creates dedicated owner/loader/auditor roles, a disabled service user, transient database, and initially suspended Generation 1 X-Small warehouse with 60-second auto-suspend. Bind only the public key; generate and protect the encrypted private key locally using the runbook. Keep its passphrase in a local prompt/environment for the process; never in SQL, command history or chat. The loader requires no AWS keys stored in Snowflake because it transfers through the local client.

## Remaining approval package

### Current account preparation evidence

The installed CLI's `configure list-profiles` returned no profiles; both the real Windows user's `.aws/config` and `.aws/credentials` were absent. In the execution sandbox, LOCALAPPDATA points to a different temporary location; use the installed CLI's real absolute path or a normal local PowerShell session. Do not reinstall the CLI to address this path difference.

Private preparation files are in `.local/aws-account-preparation-1905b090ad234b84ab13b0fc089161e0`. The candidate bucket is `<candidate-bucket>`. Its random suffix reduces collision risk, but global availability is unverified and cannot be reserved without creating it. The fresh `demo.tfvars.json` specifies that name, us-east-1 and fdep-demo without overwriting existing configuration.

For an **existing non-root** console identity, run the following in normal local PowerShell. Stop if the named profiles already exist; do not overwrite them. The browser must select the non-root identity, with MFA. If only root exists, stop: creating a console-only IAM user and granting permissions needs separate authorization under the current no-resource-creation restriction. Do not sign this workflow in as root.

```powershell
# Ensure the AWS CLI installation directory is on PATH.
aws configure list-profiles
aws login --profile fdep-signin --region us-east-1
aws configure set credential_process 'aws configure export-credentials --profile fdep-signin --format process' --profile fdep-demo
aws configure set region us-east-1 --profile fdep-demo
aws sts get-caller-identity --profile fdep-demo --no-cli-pager
```

Complete browser login locally; never send an authorization code, token or credentials through chat. Tell the assistant only that login completed, so it can inspect identity and read permissions without credential output. No login or authenticated AWS call has yet been executed by this preparation.

After identity verification, read attached/inline policies and any permissions boundary where authorized; IAM policy simulation can provide additional evidence if allowed. Simulation and successful planning cannot guarantee future create permissions, because organization controls, conditions and service validation can differ. Do not test writes to establish permissions. Bucket availability probes can themselves be service requests, so defer them under the current prohibition on chargeable S3 requests; Terraform plan does not reserve or prove availability of a new bucket.

The account-aware plan, once authenticated, uses these commands from the repository root. Its binary plan and JSON remain private, ignored local artifacts. This block has **not** been executed:

```powershell
$env:AWS_PROFILE = 'fdep-demo'
$env:AWS_REGION = 'us-east-1'
$env:AWS_EC2_METADATA_DISABLED = 'true'
$tf = (Resolve-Path '.local/tools/terraform-1.17.2/terraform.exe').Path
$evidence = (Resolve-Path '.local/aws-account-preparation-1905b090ad234b84ab13b0fc089161e0').Path
& $tf -chdir=infrastructure/terraform plan -input=false -var-file="$evidence/demo.tfvars.json" -out="$evidence/aws.tfplan"
if ($LASTEXITCODE -ne 0) { throw 'Plan failed; stop here' }
& $tf -chdir=infrastructure/terraform show -no-color "$evidence/aws.tfplan" | Set-Content "$evidence/aws-plan.txt"
& $tf -chdir=infrastructure/terraform show -json "$evidence/aws.tfplan" | Set-Content "$evidence/aws-plan.json"
Get-FileHash -Algorithm SHA256 "$evidence/aws.tfplan"
```

Review exactly six creates, zero changes/deletes, the correct region and namespace, S3 protection and the narrowly scoped transfer policy. There is no apply command. Without an existing state, planning new resources generally uses identity checks and local expression evaluation; it does not exercise bucket creation or IAM policy attachment. Inspect any existing state before planning to avoid unexpected refresh requests.

Provide non-secret confirmation of AWS credit balance/expiry, intended operator identity, unique bucket name and availability of the needed permissions. Then save and inspect an **account-aware Terraform plan**, as described in controlled-deployment.md. It must show exactly six additions and no unrelated changes; protect the binary plan/state as private local artifacts. The existing mock plan is not a substitute for account permissions or service validation.

Snowflake creation/activation remains an independent approval gate. Until its actual offered account terms are known, the $1.28 list-price model is conditional. Reconcile actual rates/credits and taxes before requesting provisioning approval. Inventory, replay/evidence procedures and teardown are in controlled-deployment.md; no apply, SQL setup, upload or load is currently authorized.
