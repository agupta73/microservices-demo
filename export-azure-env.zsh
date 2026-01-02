#!/bin/zsh

set -euo pipefail

echo "This script will export ARM templates and summaries for selected Azure resource groups."
echo

# 1) Ask for resource groups (space-separated)
print -n "Enter resource group names to export (space-separated, e.g. 'rg-c1-eastus rg-c2-westus'): "
read RG_INPUT

if [[ -z "$RG_INPUT" ]]; then
  echo "No resource groups provided. Exiting."
  exit 1
fi

# 2) Create output directory
TS=$(date +"%Y%m%d-%H%M%S")
BASE_DIR="azure-export-${TS}"
mkdir -p "$BASE_DIR"
echo "Exporting to: $BASE_DIR"
echo

# 3) Loop over each RG
for RG in $RG_INPUT; do
  echo "=== Exporting resource group: ${RG} ==="

  RG_DIR="${BASE_DIR}/${RG}"
  mkdir -p "$RG_DIR"

  # 3a) Export full ARM template for the RG
  echo " - Exporting ARM template..."
  az group export --name "$RG" > "${RG_DIR}/${RG}-template.json"

  # 3b) Save raw resource list
  echo " - Listing all resources..."
  az resource list -g "$RG" -o json > "${RG_DIR}/${RG}-resources.json"

  # 3c) Useful filtered exports
  echo " - Exporting AKS clusters (if any)..."
  az aks list -g "$RG" -o json > "${RG_DIR}/${RG}-aks.json"

  echo " - Exporting Network Security Groups (if any)..."
  az network nsg list -g "$RG" -o json > "${RG_DIR}/${RG}-nsgs.json"

  echo " - Exporting Virtual Networks (if any)..."
  az network vnet list -g "$RG" -o json > "${RG_DIR}/${RG}-vnets.json"

  echo " - Exporting Load Balancers (if any)..."
  az network lb list -g "$RG" -o json > "${RG_DIR}/${RG}-lbs.json"

  echo " - Exporting Public IPs (if any)..."
  az network public-ip list -g "$RG" -o json > "${RG_DIR}/${RG}-public-ips.json"

  echo " - Exporting Managed Disks (if any)..."
  az disk list -g "$RG" -o json > "${RG_DIR}/${RG}-disks.json"

  echo " - Exporting Storage Accounts (if any)..."
  az storage account list -g "$RG" -o json > "${RG_DIR}/${RG}-storage-accounts.json"

  echo "Done with ${RG}."
  echo
done

echo "All exports complete."
echo "Folder structure:"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-template.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-resources.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-aks.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-nsgs.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-vnets.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-lbs.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-public-ips.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-disks.json"
echo "  ${BASE_DIR}/<resource-group>/<resource-group>-storage-accounts.json"
echo
echo "To recreate a resource group later:"
echo "  az group create -n <rg-name> -l <location>"
echo "  az deployment group create --resource-group <rg-name> --template-file ${BASE_DIR}/<rg-name>/<rg-name>-template.json"
