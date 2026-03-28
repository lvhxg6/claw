---
name: reporting-skill
description: Synthesize inspection findings, remediation plans, and remediation execution outcomes into a stable security report for the current workspace.
---

# Reporting Skill

Use this skill when the current step is report generation, audit summary, or final delivery after inspection, remediation planning, and remediation execution.

## Scope

- Summarize only what was actually inspected or proposed.
- Distinguish clearly between confirmed findings, proposed remediation plans, approved remediation execution, and skipped remediation.
- Keep the report decision-friendly for a human reviewer.

## Execution Rules

- Lead with the overall risk picture.
- Preserve important evidence, but compress raw details into short summaries.
- Call out blocked items, approvals, skipped remediation, and residual risk.
- Do not invent completion if remediation was only planned, skipped, or blocked.

## Output Shape

Return a concise report with:

1. Executive summary.
2. Key findings.
3. Remediation status: planned, completed, skipped, or blocked.
4. Residual risks and recommended next steps.
5. Optional appendix with affected files or artifacts if relevant.
