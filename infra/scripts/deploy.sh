#!/usr/bin/env bash
# Deploy the whole stack: infrastructure, image build in ACR, rollout.
# Prerequisites: az login, terraform, infra/terraform/terraform.tfvars (see terraform.tfvars.example).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TF="$HERE/../terraform"
TAG="${1:-$(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)}"
export ARM_SUBSCRIPTION_ID="${ARM_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"

terraform -chdir="$TF" init -input=false -backend-config=backend.hcl

# 1) Create only the registry, so an image can be pushed before the apps reference it.
#    Running apps are untouched on later deployments.
terraform -chdir="$TF" apply -input=false -auto-approve -target=azurerm_container_registry.main

# 2) Build the image remotely in ACR (no local Docker needed).
ACR="$(terraform -chdir="$TF" output -raw acr_name)"
az acr build -r "$ACR" -t "cvsearch:${TAG}" -f "$HERE/../../Dockerfile" "$HERE/../.."

# 3) Roll out the new image.
terraform -chdir="$TF" apply -input=false -auto-approve -var "image_tag=${TAG}"

echo
echo "API : $(terraform -chdir="$TF" output -raw api_url)"
echo "UI  : $(terraform -chdir="$TF" output -raw ui_url)"
echo "Credentials:"
terraform -chdir="$TF" output -json retrieve_credentials | python3 -c "import sys,json; [print('  ', v) for v in json.load(sys.stdin).values()]"
