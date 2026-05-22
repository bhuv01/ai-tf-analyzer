#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# scripts/setup.sh — ONE-TIME SETUP
# Reads config.env and generates terraform.tfvars + validates prerequisites
#
# Usage: ./scripts/setup.sh
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="$ROOT/config.env"

# ── Colors ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓${NC} $1"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $1"; }
err()  { echo -e "${RED}  ✗${NC} $1"; }
info() { echo -e "${BLUE}  →${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║      AI-Powered Terraform Analyzer — Setup               ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── 1. Load config.env ─────────────────────────────────────────────────────────
if [[ ! -f "$CONFIG" ]]; then
  err "config.env not found at $CONFIG"
  exit 1
fi
source "$CONFIG"
ok "Loaded config.env"

# ── 2. Validate config.env values ──────────────────────────────────────────────
echo ""
echo "▶ Validating config.env..."

ERRORS=0

if [[ "$ALERT_EMAIL" == "your-email@gmail.com" ]]; then
  err "ALERT_EMAIL is still the default. Edit config.env first!"; ERRORS=$((ERRORS+1))
else
  ok "ALERT_EMAIL = $ALERT_EMAIL"
fi

ok "AWS_REGION     = $AWS_REGION"
ok "BEDROCK_REGION = $BEDROCK_REGION"
ok "PROJECT_NAME   = $PROJECT_NAME"
ok "ENVIRONMENT    = $ENVIRONMENT"
ok "BEDROCK_MODEL  = $BEDROCK_MODEL_ID"

if [[ $ERRORS -gt 0 ]]; then
  echo ""; err "Fix the above errors in config.env then re-run."; exit 1
fi

# ── 3. Check prerequisites ─────────────────────────────────────────────────────
echo ""
echo "▶ Checking prerequisites..."

check_cmd() {
  if command -v "$1" &>/dev/null; then ok "$1 found: $(command -v $1)"
  else err "$1 NOT found — install it first"; ERRORS=$((ERRORS+1)); fi
}

check_cmd aws
check_cmd terraform
check_cmd python3
check_cmd pip3

# Check AWS credentials
if aws sts get-caller-identity &>/dev/null; then
  ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
  ok "AWS credentials valid — Account: $ACCOUNT"
else
  err "AWS credentials not configured. Run: aws configure"; ERRORS=$((ERRORS+1))
fi

# Check Python boto3
if python3 -c "import boto3" 2>/dev/null; then
  ok "boto3 installed"
else
  warn "boto3 not installed — installing now..."
  pip3 install boto3 --quiet
  ok "boto3 installed"
fi

if [[ $ERRORS -gt 0 ]]; then
  echo ""; err "$ERRORS prerequisite(s) missing. Fix them and re-run."; exit 1
fi

# ── 4. Check Bedrock model access ──────────────────────────────────────────────
echo ""
echo "▶ Checking Bedrock model access..."
MODEL_BASE=$(echo "$BEDROCK_MODEL_ID" | sed 's/^[a-z]*\.//')
if aws bedrock list-foundation-models --region "$BEDROCK_REGION" \
    --query "modelSummaries[?contains(modelId,'claude')].[modelId]" \
    --output text 2>/dev/null | grep -q "claude"; then
  ok "Bedrock Claude models accessible in $BEDROCK_REGION"
else
  warn "Could not verify Bedrock access — make sure you completed the FTU form"
  warn "Go to: AWS Console → Bedrock → Model catalog → Any Claude model → Request access"
fi

# ── 5. Generate terraform.tfvars ───────────────────────────────────────────────
echo ""
echo "▶ Generating terraform/terraform.tfvars..."

cat > "$ROOT/terraform/terraform.tfvars" << EOF
# Auto-generated from config.env — do not edit manually
# Edit config.env and re-run ./scripts/setup.sh

aws_region         = "$AWS_REGION"
bedrock_region     = "$BEDROCK_REGION"
project_name       = "$PROJECT_NAME"
environment        = "$ENVIRONMENT"
alert_email        = "$ALERT_EMAIL"
bedrock_model_id   = "$BEDROCK_MODEL_ID"
lambda_timeout     = $LAMBDA_TIMEOUT
lambda_memory      = $LAMBDA_MEMORY
log_retention_days = $LOG_RETENTION_DAYS
max_tokens         = $MAX_TOKENS
EOF

ok "terraform/terraform.tfvars generated"

# ── 6. Add to .gitignore ───────────────────────────────────────────────────────
GITIGNORE="$ROOT/.gitignore"
for entry in "terraform/terraform.tfvars" "terraform/.build/" "*.tfstate" "*.tfstate.backup" ".terraform/" "lambda_payload.json" "response.json"; do
  if ! grep -qF "$entry" "$GITIGNORE" 2>/dev/null; then
    echo "$entry" >> "$GITIGNORE"
  fi
done
ok ".gitignore updated"

# ── 7. Make scripts executable ─────────────────────────────────────────────────
chmod +x "$ROOT/scripts/"*.sh 2>/dev/null || true
ok "Scripts made executable"

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ✅ Setup Complete! Next steps:                          ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║                                                          ║"
echo "║  1. LOCAL TEST (no deploy needed):                       ║"
echo "║     python3 tests/test_local.py                          ║"
echo "║                                                          ║"
echo "║  2. DEPLOY to AWS:                                       ║"
echo "║     ./scripts/deploy.sh plan                             ║"
echo "║     ./scripts/deploy.sh apply                            ║"
echo "║                                                          ║"
echo "║  3. ANALYZE your Terraform project:                      ║"
echo "║     ./scripts/analyze.sh --tf-dir /path/to/your/tf       ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
