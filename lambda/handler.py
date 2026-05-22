"""
╔══════════════════════════════════════════════════════════════════╗
║         AI-Powered Terraform Plan Analyzer — Lambda Handler      ║
║         Works with ANY Terraform project                         ║
║         Powered by AWS Bedrock (Claude)                          ║
╚══════════════════════════════════════════════════════════════════╝

Environment Variables (set by Terraform automatically):
  BEDROCK_REGION    - AWS region for Bedrock API
  BEDROCK_MODEL_ID  - Inference profile ID (apac./us./eu. prefix)
  MAX_TOKENS        - Max response tokens (default 2048)
  SNS_TOPIC_ARN     - SNS topic for email alerts (optional)
  ENVIRONMENT       - dev / staging / prod
"""

import json
import boto3
import logging
import os
import datetime
from typing import Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Config (from environment variables set by Terraform) ───────────────────────
BEDROCK_REGION  = os.environ.get("BEDROCK_REGION",   "ap-south-1")
MODEL_ID        = os.environ.get("BEDROCK_MODEL_ID",  "apac.anthropic.claude-3-5-sonnet-20241022-v2:0")
MAX_TOKENS      = int(os.environ.get("MAX_TOKENS",    "2048"))
SNS_TOPIC_ARN   = os.environ.get("SNS_TOPIC_ARN",     "")
ENVIRONMENT     = os.environ.get("ENVIRONMENT",        "dev")

# ── AWS Clients ────────────────────────────────────────────────────────────────
bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
sns     = boto3.client("sns",             region_name=BEDROCK_REGION)


# ══════════════════════════════════════════════════════════════════════════════
# CORE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def extract_changes(plan: dict) -> dict:
    """
    Parse any Terraform plan JSON and classify resource changes.
    Works with any Terraform version >= 0.12 (format_version 0.1, 0.2, 1.x)
    """
    resource_changes = plan.get("resource_changes", [])
    creates, deletes, updates, replaces, no_ops, unknowns = [], [], [], [], [], []

    for rc in resource_changes:
        address = rc.get("address", rc.get("name", "unknown"))
        actions = rc.get("change", {}).get("actions", [])
        rtype   = rc.get("type", "unknown_type")

        entry = {"address": address, "type": rtype}

        if not actions or actions == ["no-op"]:
            no_ops.append(entry)
        elif actions == ["create"]:
            creates.append(entry)
        elif actions == ["delete"]:
            deletes.append(entry)
        elif actions == ["update"]:
            updates.append(entry)
        elif set(actions) == {"delete", "create"} or actions == ["create", "delete"]:
            replaces.append(entry)
        else:
            unknowns.append(entry)

    return {
        "creates":  creates,
        "deletes":  deletes,
        "updates":  updates,
        "replaces": replaces,
        "no_ops":   no_ops,
        "unknowns": unknowns,
    }


def format_resource_list(resources: list) -> str:
    """Format resource list for prompt — address + type."""
    if not resources:
        return "[]"
    lines = [f"  - {r['address']} ({r['type']})" for r in resources[:30]]  # cap at 30
    if len(resources) > 30:
        lines.append(f"  ... and {len(resources) - 30} more")
    return "\n" + "\n".join(lines)


def build_prompt(changes: dict, raw_plan_excerpt: str, metadata: dict) -> str:
    """
    Build a structured prompt for Claude.
    Includes security checklist + metadata context.
    """
    return f"""You are a senior DevOps/Security engineer reviewing a Terraform plan before production deployment.

━━━ PIPELINE CONTEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Environment  : {metadata.get('environment', 'unknown')}
Triggered by : {metadata.get('triggered_by', 'unknown')}
Branch       : {metadata.get('branch', 'unknown')}
Commit       : {metadata.get('commit_id', 'unknown')}
Timestamp    : {metadata.get('timestamp', 'unknown')}

━━━ RESOURCE CHANGES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CREATE  ({len(changes['creates'])}): {format_resource_list(changes['creates'])}
DELETE  ({len(changes['deletes'])}): {format_resource_list(changes['deletes'])}
UPDATE  ({len(changes['updates'])}): {format_resource_list(changes['updates'])}
REPLACE ({len(changes['replaces'])}): {format_resource_list(changes['replaces'])}
NO-OP   ({len(changes['no_ops'])}): {len(changes['no_ops'])} resources unchanged

━━━ SECURITY CHECKLIST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Check ALL of these in the plan:
1. IAM roles/policies with overly broad permissions (Admin, *)
2. Security groups with 0.0.0.0/0 or ::/0 ingress on sensitive ports
3. S3 buckets with public access enabled or ACLs open
4. Databases/storage being DELETED (data loss risk)
5. Resources with encryption disabled or removed
6. Resources being REPLACED (destroy + recreate = potential downtime)
7. Missing deletion protection on critical resources
8. Backup/retention settings being reduced to 0
9. Public-facing resources being created unexpectedly
10. Resources in production being touched by a non-prod branch

━━━ TERRAFORM PLAN EXCERPT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{raw_plan_excerpt[:3500]}

━━━ INSTRUCTIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Respond ONLY with a valid JSON object. No markdown. No explanation outside JSON.

{{
  "summary": "One-line executive summary of what this plan does",

  "creates": {{
    "count": <number>,
    "resources": ["address (type)", ...],
    "description": "What is being created",
    "security_notes": "Any security concerns with new resources"
  }},
  "deletes": {{
    "count": <number>,
    "resources": ["address (type)", ...],
    "description": "What is being deleted",
    "warning": "Data loss or service disruption warning",
    "data_loss_risk": true
  }},
  "updates": {{
    "count": <number>,
    "resources": ["address (type)", ...],
    "description": "What is being updated"
  }},
  "replaces": {{
    "count": <number>,
    "resources": ["address (type)", ...],
    "description": "What is being replaced",
    "downtime_risk": true,
    "warning": "Downtime or data loss from destroy+recreate"
  }},

  "security_findings": [
    {{
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "category": "IAM|Network|Data|Encryption|Availability|Cost|Compliance",
      "resource": "resource address",
      "finding": "Specific security issue found",
      "recommendation": "Exact action to remediate"
    }}
  ],

  "risks": [
    {{
      "severity": "HIGH|MEDIUM|LOW",
      "resource": "resource address or General",
      "risk": "Operational risk description",
      "recommendation": "How to mitigate"
    }}
  ],

  "overall_risk": "CRITICAL|HIGH|MEDIUM|LOW",
  "approval_recommendation": "APPROVE|REVIEW|REJECT",
  "approval_reason": "Clear reason for recommendation",
  "requires_manual_approval": true,

  "estimated_cost_impact": "Brief cost impact description",
  "rollback_complexity": "EASY|MEDIUM|HARD|IMPOSSIBLE",
  "rollback_steps": "How to rollback if something goes wrong"
}}"""


def call_bedrock(prompt: str) -> dict:
    """Invoke Bedrock Claude and parse the JSON response."""
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }

    response = bedrock.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )

    result   = json.loads(response["body"].read())
    raw_text = result["content"][0]["text"].strip()

    # Strip markdown code fences if model adds them
    if raw_text.startswith("```"):
        parts    = raw_text.split("```")
        raw_text = parts[1] if len(parts) > 1 else raw_text
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    return json.loads(raw_text.strip())


def send_sns_alert(analysis: dict, metadata: dict) -> bool:
    """
    Send email alert via SNS for HIGH or CRITICAL risk plans.
    SNS → Email (Gmail or any email) — FREE tier friendly.
    Returns True if alert was sent.
    """
    if not SNS_TOPIC_ARN:
        logger.warning("SNS_TOPIC_ARN not set — skipping email alert")
        return False

    risk = analysis.get("overall_risk", "LOW")
    rec  = analysis.get("approval_recommendation", "APPROVE")

    # Send alert on EVERY pipeline run (no filter)
    logger.info("Sending SNS alert for Risk=%s Rec=%s", risk, rec)

    # Icons
    risk_icon = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(risk, "⚪")
    rec_icon  = {"APPROVE": "✅", "REVIEW": "⚠️", "REJECT": "❌"}.get(rec, "❓")

    # Security findings section
    findings      = analysis.get("security_findings", [])
    findings_text = ""
    for f in findings[:8]:
        sev_icon = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(f.get("severity"), "⚪")
        findings_text += f"\n  {sev_icon} [{f.get('severity')}] {f.get('category')} — {f.get('resource', 'N/A')}"
        findings_text += f"\n     Issue  : {f.get('finding', '')}"
        findings_text += f"\n     Action : {f.get('recommendation', '')}\n"

    risks      = analysis.get("risks", [])
    risks_text = ""
    for r in risks[:5]:
        sev_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(r.get("severity"), "⚪")
        risks_text += f"\n  {sev_icon} {r.get('resource', 'General')}: {r.get('risk', '')}"

    message = f"""
{'=' * 62}
  TERRAFORM PLAN ALERT  {risk_icon} {risk} RISK  {rec_icon} {rec}
{'=' * 62}

PIPELINE INFO
  Environment  : {metadata.get('environment', 'N/A').upper()}
  Branch       : {metadata.get('branch', 'N/A')}
  Commit       : {metadata.get('commit_id', 'N/A')}
  Triggered by : {metadata.get('triggered_by', 'N/A')}
  Build #      : {metadata.get('build_number', 'N/A')}
  Timestamp    : {metadata.get('timestamp', 'N/A')}

ANALYSIS
  Summary      : {analysis.get('summary', 'N/A')}
  Risk Level   : {risk}
  Recommend    : {rec}
  Reason       : {analysis.get('approval_reason', 'N/A')}
  Cost Impact  : {analysis.get('estimated_cost_impact', 'N/A')}
  Rollback     : {analysis.get('rollback_complexity', 'N/A')}
  Rollback How : {analysis.get('rollback_steps', 'N/A')}

CHANGES
  ➕ Create  : {analysis.get('creates', {}).get('count', 0)}
  🗑️  Delete  : {analysis.get('deletes', {}).get('count', 0)}
  ✏️  Update  : {analysis.get('updates', {}).get('count', 0)}
  🔄 Replace : {analysis.get('replaces', {}).get('count', 0)}
{'─' * 62}
SECURITY FINDINGS ({len(findings)} total)
{findings_text if findings_text else '  None detected.'}
{'─' * 62}
OPERATIONAL RISKS ({len(risks)} total)
{risks_text if risks_text else '  None detected.'}
{'─' * 62}
{'⚠️  ACTION REQUIRED: This plan needs MANUAL APPROVAL in Jenkins.' if analysis.get('requires_manual_approval') else ''}
{'❌ REJECTED: Fix the above issues before re-running.' if rec == 'REJECT' else ''}
{'=' * 62}
"""

    subject = f"[TF-ANALYZER][{metadata.get('environment','?').upper()}] {rec} — {risk} Risk | {metadata.get('branch', 'unknown')}"

    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject[:100],
            Message=message,
        )
        logger.info("SNS alert sent. Subject: %s", subject)
        return True
    except Exception as e:
        logger.error("SNS publish failed: %s", e)
        return False


def determine_pipeline_action(analysis: dict) -> tuple:
    """
    Returns (action, message) that CI/CD pipeline should act on.

    PROCEED       → Auto-approve, run terraform apply
    WAIT_APPROVAL → Pause pipeline, wait for human input
    FAIL          → Fail build immediately, do not apply
    """
    rec  = analysis.get("approval_recommendation", "APPROVE")
    risk = analysis.get("overall_risk", "LOW")

    if rec == "REJECT":
        return (
            "FAIL",
            f"Plan REJECTED — {analysis.get('approval_reason', 'Critical issues found')}. Fix issues and re-run."
        )
    elif rec == "REVIEW" or analysis.get("requires_manual_approval") or risk in ("HIGH", "CRITICAL"):
        return (
            "WAIT_APPROVAL",
            f"Plan requires manual approval. Risk={risk}. Check your email for security details."
        )
    else:
        return (
            "PROCEED",
            f"Plan APPROVED. Risk={risk}. Proceeding with terraform apply."
        )


# ══════════════════════════════════════════════════════════════════════════════
# LAMBDA ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def lambda_handler(event: dict, context: Any) -> dict:
    """
    Universal entry point — works with any Terraform plan.

    Accepted event formats:

    Format 1 — Full plan JSON:
    {
      "plan_json": { ...terraform show -json output... },
      "metadata": {
        "environment": "dev",
        "branch": "main",
        "commit_id": "abc123",
        "triggered_by": "jenkins",
        "build_number": "42"
      }
    }

    Format 2 — Stringified plan:
    {
      "plan_json_string": "{ ...json string... }",
      "metadata": { ... }
    }

    Format 3 — Minimal (no metadata):
    {
      "plan_json": { ...terraform plan... }
    }
    """
    logger.info("Lambda invoked. Event keys: %s", list(event.keys()))
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    # ── 1. Build metadata ────────────────────────────────────────────────────
    metadata = event.get("metadata", {})
    metadata.setdefault("environment",   ENVIRONMENT)
    metadata.setdefault("triggered_by",  "unknown")
    metadata.setdefault("branch",        "unknown")
    metadata.setdefault("commit_id",     "unknown")
    metadata.setdefault("build_number",  "unknown")
    metadata["timestamp"] = timestamp
    logger.info("Metadata: %s", json.dumps(metadata))

    # ── 2. Parse plan ────────────────────────────────────────────────────────
    try:
        if "plan_json" in event:
            plan = event["plan_json"]
        elif "plan_json_string" in event:
            plan = json.loads(event["plan_json_string"])
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "Missing required field: 'plan_json' or 'plan_json_string'",
                    "hint":  "Run: terraform show -json tfplan > plan.json, then wrap in {\"plan_json\": <contents>}"
                })
            }
    except json.JSONDecodeError as e:
        return {"statusCode": 400, "body": json.dumps({"error": f"Invalid JSON: {e}"})}

    # ── 3. Extract changes ───────────────────────────────────────────────────
    try:
        changes = extract_changes(plan)
        logger.info(
            "Changes extracted — create:%d delete:%d update:%d replace:%d no-op:%d",
            len(changes["creates"]), len(changes["deletes"]),
            len(changes["updates"]), len(changes["replaces"]), len(changes["no_ops"])
        )
    except Exception as e:
        logger.error("Failed to extract changes: %s", e)
        return {"statusCode": 500, "body": json.dumps({"error": f"Plan parsing failed: {e}"})}

    # ── 4. Call Bedrock ──────────────────────────────────────────────────────
    try:
        prompt   = build_prompt(changes, json.dumps(plan, indent=2), metadata)
        analysis = call_bedrock(prompt)
        logger.info(
            "Bedrock response — Risk:%s Rec:%s",
            analysis.get("overall_risk"), analysis.get("approval_recommendation")
        )
    except Exception as e:
        logger.error("Bedrock call failed: %s", e)
        return {"statusCode": 502, "body": json.dumps({"error": f"Bedrock failed: {e}"})}

    # ── 5. Send alert ────────────────────────────────────────────────────────
    alert_sent = send_sns_alert(analysis, metadata)

    # ── 6. Determine pipeline action ─────────────────────────────────────────
    pipeline_action, pipeline_message = determine_pipeline_action(analysis)
    logger.info("Pipeline action: %s", pipeline_action)

    # ── 7. Return structured response ────────────────────────────────────────
    return {
        "statusCode": 200,
        "body": json.dumps({
            # CI/CD reads these two fields to decide what to do next
            "pipeline_action":  pipeline_action,
            "pipeline_message": pipeline_message,

            # Full AI analysis
            "analysis": analysis,

            # Quick stats
            "change_counts": {
                "creates":  len(changes["creates"]),
                "deletes":  len(changes["deletes"]),
                "updates":  len(changes["updates"]),
                "replaces": len(changes["replaces"]),
                "no_ops":   len(changes["no_ops"]),
            },

            # Audit fields
            "alert_sent": alert_sent,
            "metadata":   metadata,
            "model_used": MODEL_ID,
        }, indent=2)
    }
