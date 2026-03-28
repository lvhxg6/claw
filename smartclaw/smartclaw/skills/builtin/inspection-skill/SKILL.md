---
name: inspection-skill
description: Inspect the local workspace for security and configuration risks, produce structured findings, and avoid making file changes.
---

# Inspection Skill

Use this skill when the current step is an inspection, audit, or baseline review of the local workspace.

## Scope

- Inspect only the current workspace, local files, and directly accessible configuration.
- Prefer repository code, config files, manifests, scripts, and documentation that can explain security posture.
- Do not claim to have scanned remote systems unless the task explicitly provides remote access and tools.

## Execution Rules

- Read before acting. Start from high-signal files such as `.env*`, CI config, container config, dependency manifests, auth/config modules, and deployment scripts.
- Look for concrete issues: secret exposure, unsafe defaults, overbroad permissions, missing validation, risky shell usage, weak dependency hygiene, and insecure network settings.
- Keep evidence specific. Mention file paths, config keys, code locations, or observed behavior.
- Do not modify files in this step.

## Output Shape

Return a concise inspection result with:

1. Overall summary.
2. Findings grouped by severity.
3. For each finding: title, severity, evidence, affected path, risk explanation.
4. Suggested next action for remediation.

If no concrete issue is found, say so explicitly and note residual blind spots.
