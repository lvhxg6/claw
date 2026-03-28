---
name: remediation-skill
description: Turn inspection findings into controlled remediation guidance, prioritizing proposed actions over direct file modification.
---

# Remediation Skill

Use this skill when the current step is remediation, hardening, or follow-up action after inspection.

## Scope

- Treat this phase as controlled remediation planning by default.
- Base every proposed action on concrete inspection findings or artifacts.
- Prefer low-risk, reversible changes and explicit rationale.

## Execution Rules

- Do not silently change files unless the parent step explicitly allows direct modification.
- For each finding, propose a practical fix, expected impact, and any tradeoff.
- If a change would touch files, name the likely files and the kind of modification.
- If a finding lacks enough evidence for a safe fix, say what extra information is needed.

## Output Shape

Return a concise remediation plan with:

1. Prioritized action list.
2. For each action: target finding, proposed fix, affected files or configs, risk level, and whether approval is required.
3. Safe fallback when direct remediation is not advisable.
4. Recommended order of execution.
