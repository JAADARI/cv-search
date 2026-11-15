# ADR 0006: Deployment blocked by PostgreSQL SKU policy mismatch

## Status
Blocked

## Context
The Terraform configuration deploys a PostgreSQL Flexible Server with SKU `B_Standard_B1ms` (Burstable tier). The subscription has a guardrail policy (`GenAI guardrails (jaadari-firas99-gmail-com)`) that only allows two SKUs for `Microsoft.DBforPostgreSQL/flexibleServers`:

- `Standard_B1ms`
- `Standard_B2s`

## Problem
These SKUs **do not exist in any Azure region for this subscription**. Verification:

1. `az postgres flexible-server list-skus` returns no Burstable SKUs in any region (tested 24 regions)
2. Direct creation attempts with `standard_b1ms`, `standard_b2ms`, `Standard_B1ms`, `Standard_B2s` all fail with `SkuNotAvailable`
3. General Purpose SKUs (e.g., `standard_d2ds_v5`) are rejected by the policy with `RequestDisallowedByPolicy`

## Root cause
The policy was authored for a different subscription/region where `Standard_B1ms`/`Standard_B2s` exist, but this subscription (a candidate sandbox) does not offer them.

## Impact
- Terraform `apply` fails at `azurerm_postgresql_flexible_server.main`
- No PostgreSQL server can be created under the current policy
- Full end-to-end deployment is blocked

## Required fix (by Equancy platform team)
One of:
1. **Add available SKUs to the policy** — e.g., allow `standard_d2ds_v5` (General Purpose) or whatever Burstable SKUs actually exist in the target region
2. **Create a policy exemption** for this resource group / subscription
3. **Use a different subscription** where the allowed SKUs exist
4. **Remove the SKU restriction** from the policy for this candidate sandbox

## Workaround (not recommended)
Replace PostgreSQL with an allowed database service (e.g., Azure Cosmos DB for PostgreSQL, Azure Database for MySQL) — requires Terraform rewrite.

## Files
- `infra/terraform/main.tf` — PostgreSQL resource definition
- `infra/terraform/variables.tf` — `postgres_sku` variable default
- Policy: `/subscriptions/7d44c18b-c242-40e7-9da6-dbf783446320/providers/Microsoft.Authorization/policyDefinitions/genai-guardrails-jaadari-firas99-gmail-com`
