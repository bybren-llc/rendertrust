<!-- Copyright 2026 ByBren, LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# REN-26: CI/CD Pipeline

| Field            | Value                                      |
|------------------|--------------------------------------------|
| **Linear Ticket**| [REN-26](https://linear.app/cheddarfox/issue/REN-26) |
| **SAFe Type**    | Enabler (Infrastructure)                   |
| **Status**       | COMPLETE (delivered via REN-61)            |
| **Priority**     | Urgent                                     |
| **Story Points** | 5                                          |
| **PI / Sprint**  | Phase I / Sprint 1                         |

---

## Overview

Establish automated quality gates and security scanning for the RenderTrust platform via GitHub Actions. The pipeline enforces code quality, type safety, test coverage, and security posture on every push and pull request, ensuring that the trust fabric itself is built with verifiable integrity.

## Deliverables (Completed)

### Workflow Files

- `.github/workflows/ci.yml` -- Primary quality gate (lint, type-check, test, build)
- `.github/workflows/security.yml` -- Security scanning suite
- `.github/workflows/pr-validation.yml` -- PR-specific checks and labeling

### Quality Gates (ci.yml)

| Gate            | Tool      | Threshold             |
|-----------------|-----------|-----------------------|
| Lint            | Ruff      | Zero errors           |
| Type Check      | mypy      | Strict mode, zero errors |
| Unit Tests      | pytest    | All pass, coverage reported |
| Docker Build    | docker    | Multi-stage build succeeds |

### Security Scanning (security.yml)

| Scanner         | Purpose                          |
|-----------------|----------------------------------|
| pip-audit       | Python dependency vulnerabilities |
| Semgrep         | Static analysis (OWASP rules)    |
| Gitleaks        | Secret detection in commits      |
| CodeQL          | Semantic code analysis           |

## Acceptance Criteria

- [x] `ci.yml` triggers on push to `dev` and all PR branches
- [x] `security.yml` runs on schedule (weekly) and on PR to `dev`
- [x] `pr-validation.yml` validates PR title format (`type(scope): description [REN-XX]`)
- [x] Pipeline fails fast on first quality gate failure
- [x] Security scan results available as GitHub check annotations
- [x] `make ci` locally reproduces the same checks as the CI pipeline
- [x] Branch protection rules require all checks to pass before merge

## Technical Approach

### Pipeline Architecture

```
Push / PR ──► ci.yml
              ├── ruff check .
              ├── mypy . --strict
              ├── pytest --cov=core
              └── docker build --target production .

Schedule / PR ──► security.yml
                  ├── pip-audit
                  ├── semgrep --config=p/owasp-top-ten
                  ├── gitleaks detect
                  └── codeql-analysis

PR ──► pr-validation.yml
       ├── title format check
       ├── branch name check (REN-XX-*)
       └── label assignment
```

### Key Decisions

- **#PATH_DECISION**: Ruff over flake8+isort+black (single tool, faster, compatible config)
- **#PATH_DECISION**: Semgrep with OWASP ruleset for SAST (free tier sufficient, low false-positive rate)
- **#PATH_DECISION**: Gitleaks over trufflehog (simpler config, GitHub Action available)

### Patterns Referenced

- `patterns_library/ci/github-actions-workflow.md` -- workflow structure
- `patterns_library/ci/deployment-pipeline.md` -- stage ordering
- `patterns_library/security/secrets-management.md` -- secret detection

## Dependencies

| Dependency       | Status   | Notes                          |
|------------------|----------|--------------------------------|
| REN-61 (Bootstrap)| Complete | Makefile, Dockerfile, pyproject.toml |
| GitHub repo      | Ready    | ByBren-LLC/rendertrust         |
| Branch protection| Ready    | Configured on `dev`            |

## Testing Strategy

- **Validation**: Push a failing lint commit; verify pipeline rejects it
- **Security**: Introduce a test secret in a branch; verify Gitleaks catches it
- **Regression**: `make ci` runs identical checks locally for developer pre-flight
- **Coverage**: pytest coverage report uploaded as CI artifact

## Security Considerations

- **OWASP A06 (Vulnerable Components)**: pip-audit scans on every PR and weekly
- **OWASP A05 (Security Misconfiguration)**: Semgrep OWASP ruleset catches common misconfigs
- **Secret Leakage**: Gitleaks scans full commit history on PRs
- **Supply Chain**: CodeQL semantic analysis for injection and data-flow vulnerabilities
- **#EXPORT_CRITICAL**: CI secrets (API keys, tokens) stored in GitHub Secrets, never in workflow files
- **Pipeline Security**: Workflows use pinned action versions (SHA, not tags)
