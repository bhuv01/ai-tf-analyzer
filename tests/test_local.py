#!/usr/bin/env python3
"""
Local test — runs handler.py directly using your AWS credentials.
No Lambda deployment needed. Only Bedrock is called.

Usage:
    python3 tests/test_local.py
    python3 tests/test_local.py --plan tests/sample_plan.json
    python3 tests/test_local.py --plan /path/to/your/plan.json
"""
import json, sys, argparse, os

# ── Path setup: works whether run from root or tests/ folder ──────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambda"))   # lambda/handler.py
sys.path.insert(0, ROOT)                            # handler.py if flat structure

# Load config.env if present
config_path = os.path.join(ROOT, "config.env")
if os.path.exists(config_path):
    with open(config_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.split("#")[0].strip())

from handler import lambda_handler

RISK_ICON = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
REC_ICON  = {"APPROVE": "✅", "REVIEW": "⚠️",  "REJECT": "❌"}
SEV_ICON  = {"CRITICAL": "🚨", "HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}


def main():
    parser = argparse.ArgumentParser(description="Local Terraform Plan Analyzer Test")
    parser.add_argument("--plan", default=None, help="Path to plan JSON file")
    args = parser.parse_args()

    # Find plan file
    if args.plan:
        plan_path = args.plan
    else:
        # Try common locations
        candidates = [
            os.path.join(ROOT, "tests", "sample_plan.json"),
            os.path.join(ROOT, "tests", "enterprise_sample_plan.json"),
            os.path.join(os.path.dirname(__file__), "sample_plan.json"),
            os.path.join(os.path.dirname(__file__), "enterprise_sample_plan.json"),
        ]
        plan_path = next((p for p in candidates if os.path.exists(p)), None)
        if not plan_path:
            print("❌ No plan file found. Use: python3 tests/test_local.py --plan <file>")
            sys.exit(1)

    print(f"\n{'='*65}")
    print(f"  AI TERRAFORM ANALYZER — LOCAL TEST")
    print(f"  Plan: {plan_path}")
    print(f"{'='*65}\n")

    with open(plan_path) as f:
        event = json.load(f)

    # Add metadata if missing
    event.setdefault("metadata", {
        "environment":  os.environ.get("ENVIRONMENT", "dev"),
        "branch":       "local-test",
        "commit_id":    "local",
        "triggered_by": "test_local.py",
        "build_number": "0",
    })

    print("⏳ Calling Bedrock Claude... (takes 10-30 seconds)\n")
    response = lambda_handler(event, context=None)
    body     = json.loads(response["body"])

    if response["statusCode"] != 200:
        print(f"❌ Error: {body}")
        sys.exit(1)

    a       = body.get("analysis", {})
    counts  = body.get("change_counts", {})
    risk    = a.get("overall_risk", "?")
    rec     = a.get("approval_recommendation", "?")
    action  = body.get("pipeline_action", "?")

    print(f"""╔{'═'*63}╗
║  📋 {a.get('summary', 'N/A')[:58]:<58} ║
╠{'═'*63}╣
║  {RISK_ICON.get(risk,'⚪')} Overall Risk     : {risk:<43} ║
║  {REC_ICON.get(rec,'❓')} Recommendation  : {rec:<43} ║
║  💬 Reason          : {a.get('approval_reason','N/A')[:43]:<43} ║
║  💸 Cost Impact     : {a.get('estimated_cost_impact','N/A')[:43]:<43} ║
║  🔄 Rollback        : {a.get('rollback_complexity','N/A'):<43} ║
║  🔒 Manual Approval : {str(a.get('requires_manual_approval','N/A')):<43} ║
║  🤖 Model Used      : {body.get('model_used','N/A')[:43]:<43} ║
╠{'═'*63}╣
║  📊 CHANGES                                                   ║
║     ➕ Create : {counts.get('creates',0):<3}  🗑️  Delete : {counts.get('deletes',0):<3}  ✏️  Update : {counts.get('updates',0):<3}  🔄 Replace : {counts.get('replaces',0):<3} ║
╚{'═'*63}╝""")

    # Security findings
    findings = a.get("security_findings", [])
    if findings:
        print(f"\n🔐 Security Findings ({len(findings)}):")
        print("─" * 65)
        for f in findings:
            icon = SEV_ICON.get(f.get("severity"), "⚪")
            print(f"  {icon} [{f.get('severity')}] {f.get('category')} — {f.get('resource','N/A')}")
            print(f"     Issue  : {f.get('finding','')}")
            print(f"     Action : {f.get('recommendation','')}")
            print()

    # Operational risks
    risks = a.get("risks", [])
    if risks:
        print(f"⚠️  Operational Risks ({len(risks)}):")
        print("─" * 65)
        for r in risks:
            icon = SEV_ICON.get(r.get("severity"), "⚪")
            print(f"  {icon} {r.get('resource','General')}: {r.get('risk','')}")
            print(f"     Fix: {r.get('recommendation','')}")
            print()

    # Rollback info
    if a.get("rollback_steps"):
        print(f"🔄 Rollback Plan:\n  {a.get('rollback_steps')}\n")

    print("─" * 65)
    print(f"\n🎯 PIPELINE WOULD: ", end="")
    if action == "PROCEED":
        print("✅ AUTO-APPROVE and run terraform apply")
    elif action == "WAIT_APPROVAL":
        print("⏸️  PAUSE and wait for manual approval (email sent)")
    elif action == "FAIL":
        print("❌ FAIL BUILD immediately — do not apply")

    print(f"\n{'='*65}\n")

    sys.exit(1 if action == "FAIL" else 0)


if __name__ == "__main__":
    main()
