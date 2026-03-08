# Contributing to RenderTrust

Welcome to RenderTrust! This guide covers everything you need to know to contribute effectively, whether you're a human developer, Claude Code, or an AI remote agent.

## Quick Start

**For Human Developers**: Follow the complete setup process below
**For AI Agents**: Focus on [AI Agent Guidelines](#ai-agent-guidelines) and [Workflow Process](#workflow-process)

## Table of Contents

- [Prerequisites & Setup](#prerequisites--setup)
- [Licensing Guidelines](#licensing-guidelines)
- [AI Agent Guidelines](#ai-agent-guidelines)
- [Branch Naming Conventions](#branch-naming-conventions)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Workflow Process](#workflow-process)
- [Create Pull Request](#5-create-pull-request)
- [CI/CD Pipeline](#cicd-pipeline)
- [Local Development](#local-development)
- [Troubleshooting](#troubleshooting)

## Prerequisites & Setup

### For Human Developers

1. **Install Dependencies**:

   ```bash
   # Python 3.11+ required
   python --version  # Should be 3.11+

   # Docker & Docker Compose
   docker --version
   docker compose version
   ```

2. **Clone and Setup**:

   ```bash
   git clone https://github.com/ByBren-LLC/rendertrust.git
   cd rendertrust
   pip install -r requirements.txt  # or use poetry/uv
   ```

3. **Environment Setup**:

   ```bash
   cp .env.template .env
   # Fill in your environment variables
   ```

4. **Database Setup**:

   ```bash
   docker compose up -d          # Start PostgreSQL
   alembic upgrade head          # Run migrations
   ```

### For AI Agents

AI agents (Claude Code, Augment agents) should:

1. **Read this entire document** before starting work
2. **Follow all workflow processes** exactly as human developers
3. **Use the PR template** at `.github/pull_request_template.md`
4. **Run local validation** with `make ci` before pushing
5. **Reference Linear tickets** in all commits and PRs

---

## Licensing Guidelines

RenderTrust uses a **multi-license model**. When contributing new code, follow these guidelines to ensure your contribution uses the appropriate license.

### MIT License

Apply the MIT License to code in these directories:

- `sdk/` (except `sdk/mcp/`)
- `loadtest/`
- `ci/`
- `docs/`
- `diagrams/`

Add the following header to your source files:

```
// Copyright (c) 2025 Words To Film By, Inc.
// Licensed under the MIT License. See LICENSE-MIT for details.
```

### Apache License 2.0

Apply the Apache License 2.0 to code in these directories:

- `core/`
- `edgekit/relay/`
- `sdk/mcp/`

Add the following header to your source files:

```
// Copyright 2025 Words To Film By, Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
```

### Enterprise License

The following directories contain proprietary code and are subject to the Enterprise License:

- `rollup_anchor/paymaster/`
- `edgekit/workers/premium_voice/`
- `edgekit/workers/studio_llm/`
- `core/gateway/web/enterprise/`

Do not contribute to these directories without explicit permission from the RenderTrust team.

Add the following header to source files in these directories:

```
// Copyright (c) 2025 Words To Film By, Inc.
// Proprietary and confidential.
// Licensed under the RenderTrust Enterprise License.
```

---

## AI Agent Guidelines

### Required Behavior for AI Agents

**MUST DO**:

- Follow the exact branch naming convention: `REN-{number}-{description}`
- Use SAFe commit message format with Linear ticket references
- Run `make ci` before pushing any code
- Use the comprehensive PR template completely
- Follow rebase-first workflow (never create merge commits)
- Reference the Linear ticket in all commits and PR title
- Respect the multi-license model (use correct license headers)

**NEVER DO**:

- Skip the CI/CD validation steps
- Create branches without Linear ticket numbers
- Use merge commits (always rebase)
- Push without running local validation
- Ignore failing CI checks
- Contribute to Enterprise-licensed directories without permission

### AI Agent Workflow Example

```bash
# 1. Start work (always from latest dev)
git checkout dev && git pull origin dev
git checkout -b REN-123-implement-feature

# 2. Make changes and commit with SAFe format
git commit -m "feat(scope): implement feature [REN-123]"

# 3. Before pushing - ALWAYS validate locally
make ci

# 4. Rebase and push
git fetch origin && git rebase origin/dev
git push --force-with-lease origin REN-123-implement-feature

# 5. Create PR using template at .github/pull_request_template.md
```

---

## Branch Naming Conventions

**REQUIRED FORMAT**: `REN-{number}-{short-description}`

### Correct Examples

- `REN-42-add-user-authentication`
- `REN-57-fix-render-queue`
- `REN-123-implement-stripe-checkout`

### Branch Naming Rules

1. **MUST** start with `REN-{number}` (Linear ticket reference)
2. Use lowercase letters and hyphens for description
3. Keep description short but descriptive (max 50 chars total)
4. Never include personal names or dates

---

## Commit Message Guidelines

**REQUIRED FORMAT**: SAFe methodology with Linear ticket reference

```
type(scope): description [REN-XXX]
```

### Types (Required)

- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation changes
- `style` - Code formatting (no logic changes)
- `refactor` - Code restructuring (no feature/bug changes)
- `test` - Adding or updating tests
- `chore` - Maintenance tasks, dependencies
- `ci` - CI/CD pipeline changes

### Scope (Optional)

- `gateway` - API gateway changes
- `auth` - Authentication features
- `edge` - Edge node / edgekit
- `render` - Render pipeline
- `anchor` - Blockchain anchoring
- `sdk` - SDK changes
- `db` - Database changes
- `ui` - User interface (Electron app)
- `payments` - Stripe/payment changes

### Examples

Correct:

```
feat(gateway): add render job queue endpoint [REN-42]
fix(edge): resolve relay connection timeout [REN-57]
docs: update API documentation [REN-123]
```

---

## Workflow Process

**CRITICAL**: This project uses a **rebase-first workflow**.

### 1. Starting Work

```bash
# ALWAYS start from latest dev
git checkout dev
git pull origin dev

# Create feature branch with Linear ticket number
git checkout -b REN-{number}-{description}
```

### 2. During Development

```bash
# Make changes and commit with SAFe format
git add .
git commit -m "feat(scope): description [REN-XXX]"

# Keep branch updated (rebase, never merge)
git fetch origin
git rebase origin/dev
```

### 3. Before Creating PR

```bash
# REQUIRED: Run local validation
make ci

# This runs:
# - ruff check . (linting)
# - mypy . (type checking)
# - pytest (unit tests)

# Fix any issues before proceeding
```

### 4. Push Changes

```bash
# ALWAYS use force-with-lease after rebase
git push --force-with-lease origin REN-{number}-{description}
```

### 5. Create Pull Request

- **Use the template** at `.github/pull_request_template.md`
- **Fill out ALL sections** completely
- **Reference Linear ticket** in title: `feat(scope): description [REN-XXX]`
- **Request appropriate reviewers** (auto-assigned via CODEOWNERS)

### 6. Merge Process

- **ONLY use "Rebase and merge"** (maintains linear history)
- **NEVER use "Squash and merge"** or "Create merge commit"

---

## Agent Exit States (vNext Contract)

Each agent role has explicit exit states that define handoff points in the workflow:

```
+-----------------+-------------------------------------------+
| Role            | Exit State                                |
+-----------------+-------------------------------------------+
| BE-Developer    | "Ready for QAS"                           |
| FE-Developer    | "Ready for QAS"                           |
| Data-Engineer   | "Ready for QAS"                           |
| QAS             | "Approved for RTE"                        |
| RTE             | "Ready for HITL Review"                   |
| System Architect| "Stage 1 Approved - Ready for ARCHitect"  |
| HITL            | MERGED                                    |
+-----------------+-------------------------------------------+
```

### Gate Quick Reference

```
+-----------------+-----------------+-------------------------+
| Gate            | Owner           | Blocking?               |
+-----------------+-----------------+-------------------------+
| Stop-the-Line   | Implementer     | YES - no AC = no work   |
| QAS Gate        | QAS             | YES - no approval = stop|
| Stage 1 Review  | System Architect| YES - pattern check     |
| Stage 2 Review  | ARCHitect-CLI   | YES - architecture check|
| HITL Merge      | J. Scott Graham | YES - final authority   |
+-----------------+-----------------+-------------------------+
```

### Role Collapsing

- **RTE**: Collapsible (PR creation can be done by implementer)
- **QAS**: NOT collapsible (independence gate - spawn subagent)
- **SecEng**: NOT collapsible (security audit requires independence)

See [Agent Workflow SOP](./docs/sop/AGENT_WORKFLOW_SOP.md) for complete details.

---

## CI/CD Pipeline

### Local Validation Commands

```bash
# Run all quality checks (REQUIRED before pushing)
make ci

# Individual checks
ruff check .              # Linting
ruff check . --fix        # Auto-fix lint issues
mypy .                    # Type checking
pytest                    # Unit tests
pytest tests/integration  # Integration tests
```

---

## Local Development

### Environment Setup

```bash
# Database (PostgreSQL via Docker)
docker compose up -d

# Environment variables
cp .env.template .env
# Edit .env with your values

# Database migrations
alembic upgrade head
```

### Development Commands

```bash
# Start development server
docker compose up

# Database management
alembic revision --autogenerate -m "description"  # Create migration
alembic upgrade head                               # Run migrations
alembic downgrade -1                               # Rollback one migration

# Testing
pytest                     # Unit tests
pytest tests/integration   # Integration tests
pytest tests/e2e           # E2E tests

# Code quality
ruff check .               # Lint
ruff check . --fix         # Auto-fix lint
mypy .                     # Type checking
```

---

## Troubleshooting

### Common CI/CD Issues

**Branch Name Rejected**:

```bash
# Rename branch to correct format
git branch -m REN-{number}-{description}
git push origin -u REN-{number}-{description}
git push origin --delete old-branch-name
```

**Rebase Required**:

```bash
git fetch origin
git rebase origin/dev
# Resolve any conflicts
git push --force-with-lease origin your-branch
```

**Commit Message Format Error**:

```bash
# Amend last commit message
git commit --amend -m "feat(scope): description [REN-XXX]"
git push --force-with-lease origin your-branch
```

---

## Questions?

If you have any questions about contributing or licensing, please contact us at <contributors@rendertrust.com>.

---

**Last Updated**: 2026-03-07
**Version**: 2.1 (SAFe Agentic Workflow Harness v2.6.0)
**Maintained by**: RenderTrust Development Team + ARCHitect-in-the-IDE
