---
name: remediation-plan-skill
description: Turn inspection findings into a concrete remediation plan without making direct file changes.
---

# Remediation Plan Skill

Use this skill when the current step is remediation planning, hardening proposal generation, or post-inspection action design.

## Scope

- Treat this phase as planning only.
- Base every proposed action on concrete inspection findings or artifacts.
- Prefer low-risk, reversible changes and explicit rationale.

## Execution Rules

- Do not modify files in this step.
- For each finding, propose a practical fix, expected impact, and any tradeoff.
- If a change would touch files, name the likely files and the kind of modification.
- If a finding lacks enough evidence for a safe fix, say what extra information is needed.

## Output Shape

Return a concise remediation plan with:

1. Prioritized action list.
2. For each action: target finding, proposed fix, affected files or configs, risk level, and whether approval would be required for execution.
3. Safe fallback when direct remediation is not advisable.
4. Recommended order of execution.
