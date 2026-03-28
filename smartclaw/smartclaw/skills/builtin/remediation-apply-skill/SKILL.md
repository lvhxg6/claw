---
name: remediation-apply-skill
description: Execute an approved remediation plan in a controlled way and report exactly what was changed.
---

# Remediation Apply Skill

Use this skill when the current step is approved remediation execution after inspection and remediation planning.

## Scope

- Execute only approved, concrete remediation actions.
- Keep changes minimal, targeted, and easy to audit.
- If the approved plan is incomplete or unsafe to apply, stop and explain why.

## Execution Rules

- Only modify files or configuration that are directly supported by findings and the remediation plan.
- State what will be changed before applying meaningful modifications when the context is ambiguous.
- Prefer reversible edits and avoid broad refactors.
- If execution cannot proceed safely, return a blocked status with the reason.

## Output Shape

Return a concise remediation execution result with:

1. Applied actions.
2. For each action: target finding, files or configs changed, and resulting status.
3. Skipped or blocked actions with reasons.
4. Residual risk after execution.
