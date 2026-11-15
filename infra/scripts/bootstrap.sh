#!/usr/bin/env bash
# One-off: create the Terraform state storage and write infra/terraform/backend.hcl.
# Usage: infra/scripts/bootstrap.sh [location]
set -euo pipefail

LOCATION="${1:-francecentral}"
SUB_ID="$(az account show --query id -o tsv)"
SUFFIX="$(echo -n "$SUB_ID" | sha1sum | cut -c1-6)"
RG="rg-cvsearch-tfstate"
SA="stcvsearchtf${SUFFIX}"
HERE="$(cd "$(dirname "$0")" && pwd)"

az group create -n "$RG" -l "$LOCATION" -o none
az storage account create -n "$SA" -g "$RG" -l "$LOCATION" --sku Standard_LRS \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o none
az storage container create -n tfstate --account-name "$SA" --auth-mode login -o none

cat > "$HERE/../terraform/backend.hcl" <<HCL
resource_group_name  = "$RG"
storage_account_name = "$SA"
container_name       = "tfstate"
key                  = "cvsearch.tfstate"
use_azuread_auth     = true
HCL
echo "State storage ready: $SA. backend.hcl written."
