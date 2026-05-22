#!/usr/bin/env bash
# scripts/deploy.sh — Deploy Lambda + SNS to AWS via Terraform
# Usage: ./scripts/deploy.sh [plan|apply|destroy]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/config.env"

ACTION="${1:-plan}"

echo ""
echo "▶ Installing Lambda Python dependencies..."
pip3 install -r "$ROOT/lambda/requirements.txt" \
  --target "$ROOT/lambda" --upgrade --quiet
echo "  ✓ Done"

mkdir -p "$ROOT/terraform/.build"
cd "$ROOT/terraform"

echo "▶ Terraform init..."
terraform init -upgrade -input=false

echo "▶ Terraform $ACTION..."
case "$ACTION" in
  plan)    terraform plan -out=".build/tfplan" ;;
  apply)   terraform apply -auto-approve && echo "" && terraform output next_steps ;;
  destroy) echo "⚠ Destroying in 5s... Ctrl+C to cancel" && sleep 5 && terraform destroy -auto-approve ;;
  *)       echo "Usage: $0 [plan|apply|destroy]"; exit 1 ;;
esac
