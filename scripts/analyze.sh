#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# scripts/analyze.sh — Analyze ANY Terraform project
#
# Usage:
#   ./scripts/analyze.sh --tf-dir /path/to/your/terraform   # run plan + analyze
#   ./scripts/analyze.sh --plan-file plan.json               # analyze existing JSON
#   ./scripts/analyze.sh --sample                            # use built-in test plan
#   ./scripts/analyze.sh --local --tf-dir /path/to/tf        # local test (no Lambda)
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
source "$ROOT/config.env"

# ── Parse args ─────────────────────────────────────────────────────────────────
MODE=""; SOURCE=""; LOCAL=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --tf-dir)    MODE="tfdir";  SOURCE="$2"; shift 2 ;;
    --plan-file) MODE="file";   SOURCE="$2"; shift 2 ;;
    --sample)    MODE="sample";              shift   ;;
    --local)     LOCAL=true;                 shift   ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

[[ -z "$MODE" ]] && { echo "Usage: $0 --tf-dir <path> | --plan-file <file> | --sample [--local]"; exit 1; }

# ── Build plan JSON ────────────────────────────────────────────────────────────
PAYLOAD=$(mktemp /tmp/tf-payload-XXXXXX.json)
trap "rm -f $PAYLOAD" EXIT

case "$MODE" in
  tfdir)
    echo "▶ Running terraform plan in: $SOURCE"
    PLAN_BIN=$(mktemp /tmp/tfplan-XXXXXX)
    PLAN_JSON=$(mktemp /tmp/tfplan-XXXXXX.json)
    trap "rm -f $PAYLOAD $PLAN_BIN $PLAN_JSON" EXIT
    cd "$SOURCE"
    terraform plan -out="$PLAN_BIN" -input=false > /dev/null
    terraform show -json "$PLAN_BIN" > "$PLAN_JSON"
    cd "$ROOT"
    jq --argjson plan "$(cat $PLAN_JSON)" \
       --arg env "$ENVIRONMENT" \
       --arg branch "$(git -C $SOURCE rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)" \
       --arg commit "$(git -C $SOURCE rev-parse --short HEAD 2>/dev/null || echo unknown)" \
       '{"plan_json": $plan, "metadata": {"environment": $env, "branch": $branch, "commit_id": $commit, "triggered_by": "analyze.sh"}}' \
       /dev/null > "$PAYLOAD"
    # jq with null input
    echo "{}" | jq \
      --argjson plan "$(cat $PLAN_JSON)" \
      --arg env "$ENVIRONMENT" \
      --arg branch "$(git -C $SOURCE rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)" \
      --arg commit "$(git -C $SOURCE rev-parse --short HEAD 2>/dev/null || echo unknown)" \
      '{"plan_json": $plan, "metadata": {"environment": $env, "branch": $branch, "commit_id": $commit, "triggered_by": "analyze.sh"}}' \
      > "$PAYLOAD"
    ;;
  file)
    echo "▶ Using plan file: $SOURCE"
    if jq -e '.plan_json' "$SOURCE" >/dev/null 2>&1; then
      cp "$SOURCE" "$PAYLOAD"
    else
      jq '{"plan_json": .}' "$SOURCE" > "$PAYLOAD"
    fi
    ;;
  sample)
    echo "▶ Using sample plan"
    cp "$ROOT/tests/sample_plan.json" "$PAYLOAD"
    ;;
esac

# ── Run analysis ───────────────────────────────────────────────────────────────
if $LOCAL; then
  echo "▶ Running LOCAL analysis (no Lambda)..."
  # Merge SNS_TOPIC_ARN if set
  export SNS_TOPIC_ARN="${SNS_TOPIC_ARN:-}"
  python3 "$ROOT/tests/test_local.py" --plan "$PAYLOAD"
else
  echo "▶ Invoking Lambda: $PROJECT_NAME-$ENVIRONMENT-analyzer"
  RESPONSE=$(mktemp /tmp/lambda-response-XXXXXX.json)
  trap "rm -f $PAYLOAD $RESPONSE" EXIT

  aws lambda invoke \
    --function-name "${PROJECT_NAME}-${ENVIRONMENT}-analyzer" \
    --region "$AWS_REGION" \
    --payload "$(base64 < "$PAYLOAD")" \
    --cli-binary-format base64 \
    "$RESPONSE" > /dev/null

  echo ""
  echo "══════════════════════════════════════════════════════════"
  echo "  BEDROCK AI ANALYSIS"
  echo "══════════════════════════════════════════════════════════"

  STATUS=$(jq -r '.statusCode' "$RESPONSE")
  BODY=$(jq -r '.body' "$RESPONSE")

  echo "$BODY" | python3 -m json.tool

  if [[ "$STATUS" == "200" ]]; then
    ACTION=$(echo "$BODY" | jq -r '.pipeline_action')
    RISK=$(echo "$BODY"   | jq -r '.analysis.overall_risk')
    REC=$(echo "$BODY"    | jq -r '.analysis.approval_recommendation')

    echo "══════════════════════════════════════════════════════════"
    case "$ACTION" in
      PROCEED)      echo "  ✅ PROCEED — Auto-approved. Low risk." ;;
      WAIT_APPROVAL) echo "  ⏸️  WAIT — Manual approval required. Check email." ;;
      FAIL)         echo "  ❌ FAIL — Plan rejected. Fix issues and retry." ;;
    esac
    echo "  Risk: $RISK | Recommendation: $REC"
    echo "══════════════════════════════════════════════════════════"

    [[ "$ACTION" == "FAIL" ]] && exit 1
  fi
fi
