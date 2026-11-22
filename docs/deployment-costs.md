# Controlled demonstration cost estimate

The deployment basis is the existing AWS Ohio (`us-east-2`) S3 infrastructure and Snowflake Ohio Enterprise trial. On November 21, 2026, Snowsight showed $400 of $400 remaining, 30 days left, and no payment method on file. The trial tile and Billing pane offered an explicit upgrade. The standard self-service trial suspends at expiry or balance depletion unless upgraded. See the [Phase 3A account evidence](phase3a-readiness.md) and [Snowflake trial terms](https://docs.snowflake.com/en/user-guide/admin-trial-account).

## Itemized estimate

Snowflake Ohio Enterprise public On-Demand equivalents are $3 per credit and $23/TB-month for standard storage. The single-cluster STANDARD Generation 1 X-Small warehouse uses one credit per hour. Each start or resume bills at least 60 seconds ($0.05), then per second. Thirty charged minutes include bootstrap, test queries, reconciliation, resume minima and idle tails. [Snowflake consumption table](https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf) · [Warehouse billing](https://docs.snowflake.com/en/user-guide/warehouses-considerations)

The offline scope is 15 objects and 5,243,107 bytes across all four batches. The S3 allowances cover readback, retries and replay. Using Ohio S3 Standard rates ($0.023/GB-month, $0.005/1,000 writes or lists, $0.0004/1,000 GETs and $0.09/GB internet readback before allowances), 20 MiB for seven days, 100 writes/lists, 1,000 reads and 256 MiB of readback model about $0.024. Retain $0.05 as the AWS allowance, including verification requests. [Ohio S3 price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/us-east-2/index.json) · [Ohio transfer price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AWSDataTransfer/current/us-east-2/index.json)

| Item | Basis | Modeled USD |
| --- | --- | ---: |
| Existing S3 bucket | Storage, scoped requests and client readback allowance | $0.05 |
| Snowflake warehouse | 0.5 credit at $3 per credit | $1.50 |
| Snowflake cloud services | 0.125 credits reserved at $3 per credit | $0.375 |
| Snowflake database storage | 64 MiB for seven days at $23/TB-month | <$0.001 |
| **Rounded total before tax and credits** | Includes AWS allowance | **$1.93** |

Expected cash cost is **near $0**, contingent on Snowflake trial coverage and the remaining eligible AWS promotional credits. The $100 AWS balance was previously reported and was not refreshed in Phase 3A. Keep the **$5 working reserve** and **$15 maximum planned expenditure**. The Snowflake price is a published regional usage equivalent. Actual metering and posted credits will be reconciled after the run.

## Billing controls and risks

- Keep the warehouse initially suspended, with 60-second auto-suspend, on-demand auto-resume, query acceleration disabled and one cluster. Suspend explicitly during pauses and after verification. A continuously running Gen1 X-Small would consume 24 credits per day, or $72/day at list price.
- The one-credit resource monitor is supplementary. Its trigger can overshoot and it covers the assigned warehouse; storage and account-level or serverless consumption can sit outside its control. The cloud-services allowance is conservative. Snowflake calculates the 10% daily adjustment against warehouse usage in UTC. Other account activity can affect metering and no new serverless workloads are planned. [Resource monitors](https://docs.snowflake.com/en/user-guide/resource-monitors) · [Compute and cloud services charges](https://docs.snowflake.com/en/user-guide/cost-understanding-compute)
- Client-mediated S3 readbacks and load retries can incur request and egress costs. Snowflake storage accrues while data remains. Verify effective transient retention and prompt teardown. Avoid unrelated SQL or Snowsight features that resume the default warehouse.
- Gate execution on balance, account status, Gen1 availability and approved scope. If Gen1 is rejected, stop and reprice. Usage displays can lag. Record resume/suspend timestamps, warehouse metering, storage and S3 usage, then revisit posted usage after provider reporting delays.
