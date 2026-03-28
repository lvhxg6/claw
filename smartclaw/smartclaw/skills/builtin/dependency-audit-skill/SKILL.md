---
name: dependency-audit-skill
description: Audit dependency manifests, supply-chain exposure, and third-party package hygiene without modifying files.
---

# Dependency Audit Skill

Use this skill when the current step is dependency review, supply-chain inspection, or third-party package security analysis.

## Scope

- Inspect only local dependency manifests, lock files, package metadata, CI setup, and related configuration in the current workspace.
- Focus on third-party libraries, package managers, registries, update hygiene, integrity checks, and risky dependency patterns.
- Do not modify files in this step.

## Execution Rules

- Start from high-signal manifests and lock files such as `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `poetry.lock`, `requirements*.txt`, `pyproject.toml`, Docker and CI files.
- Look for concrete issues: missing lockfiles, overly broad version ranges, unpinned packages, suspicious install scripts, insecure registries, missing integrity controls, or weak update/scanning practices.
- Keep findings specific. Mention packages, versions, manifest paths, config keys, or observed pipeline behavior.
- Treat this as a focused audit that can run alongside general inspection work.

## Output Shape

Return a concise dependency audit result with:

1. Overall dependency security posture.
2. Key findings grouped by severity.
3. For each finding: package or config target, evidence, affected file, and risk explanation.
4. Recommended next actions for remediation planning.
