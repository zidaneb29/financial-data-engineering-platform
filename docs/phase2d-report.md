# Phase 2D deployment preparation

**Later deployment and teardown:** Eight approved Ohio resources were created and the restricted transfer role passed the live smoke tests. After the subsequent Snowflake demonstration, all eight resources were destroyed and independently verified absent. The preparation findings below predate that deployment. [AWS smoke report](aws-deployment-smoke-report.md) · [Teardown verification](phase7-publication.md#verification-record)

**Latest account-aware verification:** see [AWS Ohio plan review](aws-account-plan-review.md). The actual project is us-east-2, temporary non-root browser authentication and Terraform credential-process bridging succeeded, and the saved account-aware plan contains six additions with no changes/deletions. Earlier missing-authentication and us-east-1 assumptions below are superseded by that review. No provisioning occurred.

The first controlled demonstration is prepared for review. No provisioning, trial activation, account connection, Terraform apply or billable service call was performed. Public pricing documents were fetched without account credentials.

## Readiness

| Area | Verified preparation status |
| --- | --- |
| Live archive | All 19 files match the previous independent audit. Four v2 batches validate with 91 changes and zero numeric quarantine. |
| Local plan | Generated .local/deployment-preparation-5c04b733af214d7585c2d6334551e9e6/plan.json with source hashes, exact run IDs, command argument lists and expected counts |
| S3 footprint | Existing six-resource Terraform configuration reviewed. All four batches produce 15 objects totaling 5,243,107 bytes. |
| Python | 3.11.9, boto3 1.44.6, Snowflake connector 4.8.1 and cryptography 50.0.2 available |
| Windows CLI tools | AWS CLI 2.42.1 installed for current user (signed official MSI, exit 0); Terraform 1.17.2 installed portably with verified published SHA-256. Snowflake CLI/SnowSQL remain optional and uninstalled. |
| Official Terraform validation | fmt -check passed; init -backend=false selected signed AWS provider 6.73.0; validate returned valid=true, zero errors/warnings. Mock-only Terraform plan test passed: six additions, zero changes/deletions. Account-aware plan pending local authentication. |
| Snowflake SQL | Dedicated resource, budget, grant, reconciliation, evidence and teardown scripts prepared and split with the installed connector's parser. Server validation remains pending. |
| Authentication | Encrypted RSA key helper tested locally. User creation is disabled until public-key binding. Real user keys were not generated. |
| Account configuration | User confirms new AWS Free account targeting us-east-1; credit balance unverified. Snowflake uncreated/unactivated, intended AWS Northern Virginia / Standard. Local authenticated identity remains pending; see account-preparation.md. |

## Prepared artifacts

- docs/controlled-deployment.md specifies installation steps, account setup, exact order of operations, source commands, expected counts, failure handling, evidence and teardown.
- docs/deployment-costs.md records current public list rates, allowances, calculation and billing risks.
- warehouse/sql/010_demo_resources.sql creates dedicated roles, disabled service user, transient database and suspended Generation 1 X-Small warehouse.
- warehouse/sql/011_demo_budget.sql prepares a one-credit suspension monitor.
- warehouse/sql/020_demo_grants.sql grants only the loader and auditor privileges required by the existing implementation.
- warehouse/sql/040_demo_reconcile.sql checks batch counts, source hashes and duplicate identities.
- warehouse/sql/050_demo_evidence.sql captures grants, settings and public authentication metadata.
- warehouse/sql/090_demo_teardown.sql removes the dedicated project resources after evidence capture.
- scripts/generate_demo_key.py generates encrypted PKCS#8 RSA keys into a fresh protected directory and renders public-key binding SQL.
- scripts/prepare_demo.py revalidates saved artifacts and produces a local execution plan without accessing cloud services.

## Verification

The complete offline suite passed again with **128 passed, 0 failed in 34.51 seconds** on Python 3.11.9 using a fresh repository-local --basetemp. A first sandbox-default temporary-directory run encountered WinError 5 on atomic rename; the repository-local rerun passed without implementation changes. The new regression checks encrypted private-key loading, public-key binding and refusal to overwrite an existing directory. No live cloud service was used by tests.

Python compilation succeeded and pip check found no broken requirements. Ignore rules exclude generated credentials, pricing evidence and saved plans. SQL scripts were read by the connector statement splitter, which establishes statement separation rather than Snowflake syntax acceptance. Official Terraform validation and a mock-provider plan now pass. The sandbox blocked local provider communication; running the same local checks outside that sandbox succeeded. No account credentials or AWS endpoints were used by the mock plan. Evidence: .local/tools/terraform-mock-plan.txt. The new infrastructure/terraform/tests/demo.tftest.hcl asserts public-access blocking, ownership enforcement, encryption and deliberate teardown protection. The provider lock file pins the selected dependency.

## Estimate and approvals

The proposed price basis is us-east-1 / Snowflake Standard / Standard Generation 1 X-Small. Thirty charged warehouse minutes, verification traffic and storage allowances model approximately **$1.28 before tax and credits**. Use a $5 working reserve and the existing $15 planned ceiling. A one-credit resource monitor and billing notifications are supplementary controls with reporting/response limits.

Windows tool installation was explicitly authorized and completed. Actual cloud provisioning and Snowflake activation remain unauthorized. Confirm the AWS account/profile/operator role/bucket name and Snowflake account/region/edition before final plan review. This estimate does not establish actual account eligibility for credits or trial allowances.

The authorized deployment scope should name the dedicated S3 infrastructure, FDEP_DEMO Snowflake resources, two initial source batches, replay verification, optional second snapshots, evidence capture and teardown. Official Terraform validation and the account-aware plan review must precede provisioning.

## Account follow-up and fresh archive verification

See account-preparation.md for secure browser/SSO profile setup and account eligibility checks. The fresh local preparation artifact .local/deployment-preparation-37de7a5f60074c93a0ef8ff204febf4e/plan.json revalidated the archive with 91 changes, 136 SEC snapshot members, zero quarantine and 15 destination objects totaling 5,243,107 bytes. No source archive files were modified. pip check passed. No AWS account operations, uploads, Snowflake activation or provisioning occurred. The list-price estimate remains conditional on the uncreated Snowflake account and actual credit eligibility; an account-specific signed-off plan cannot yet be claimed.
