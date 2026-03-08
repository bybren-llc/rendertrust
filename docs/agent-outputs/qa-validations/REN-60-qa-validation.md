# QA Validation Report - REN-60: SAFe Agentic Workflow Harness Installation

**Date**: 2026-03-08
**Validator**: QAS Agent (Claude Opus 4.6)
**Scope**: Template variable replacement, file completeness, cross-reference integrity, tech stack consistency
**Verdict**: **BLOCKED** - Issues found requiring remediation

---

## 1. Critical .claude Files - Template Variable Verification

### .claude/README.md - FAIL

| Check                               | Result   | Notes                                                                                                   |
| ----------------------------------- | -------- | ------------------------------------------------------------------------------------------------------- |
| `REN` ticket prefix                 | PASS     | Correctly replaced throughout                                                                           |
| `RenderTrust` project name          | PASS     | Used in title and body                                                                                  |
| `J. Scott Graham` author            | PASS     | HITL correctly set                                                                                      |
| `claude_ai_Linear` MCP              | N/A      | Not referenced in this file                                                                             |
| `{{DEV_CONTAINER}}` placeholder     | **FAIL** | Line 154: still reads `{{DEV_CONTAINER}}`                                                               |
| `{{STAGING_CONTAINER}}` placeholder | **FAIL** | Line 155: still reads `{{STAGING_CONTAINER}}`                                                           |
| Next.js reference                   | **FAIL** | Line 21: "frontend-patterns (Clerk, shadcn, Next.js App Router)" - should reference React 18 + Electron |

### .claude/hooks-config.json - FAIL

| Check                  | Result   | Notes                                                                                    |
| ---------------------- | -------- | ---------------------------------------------------------------------------------------- |
| Branch protection      | **FAIL** | Line 9: checks `$BRANCH = 'main'` - should be `'dev'` (RenderTrust main branch is `dev`) |
| Push blocker           | **FAIL** | Line 31: blocks push to `'main'` - should block `'dev'`                                  |
| Behind warning         | **FAIL** | Line 41: references `origin/main` three times - should be `origin/dev`                   |
| Commit format reminder | PASS     | Generic, no project-specific values needed                                               |

### .claude/AGENT_OUTPUT_GUIDE.md - PASS

| Check                 | Result | Notes                                 |
| --------------------- | ------ | ------------------------------------- |
| `REN` ticket prefix   | PASS   | Used throughout in naming conventions |
| Output directories    | PASS   | Correctly structured                  |
| No template variables | PASS   | No `{{...}}` placeholders found       |

### .claude/team-config.json - FAIL (Multiple unreplaced placeholders)

| Check                                | Result   | Notes                                                                           |
| ------------------------------------ | -------- | ------------------------------------------------------------------------------- |
| `project.name` = "RenderTrust"       | PASS     | Correctly set                                                                   |
| `project.short_name` = "REN"         | PASS     | Correctly set                                                                   |
| `project.repo`                       | **FAIL** | Still reads `{{PROJECT_REPO}}`                                                  |
| `project.domain`                     | **FAIL** | Still reads `{{PROJECT_DOMAIN}}`                                                |
| `project.github_org`                 | **FAIL** | Still reads `{{GITHUB_ORG}}`                                                    |
| `project.company`                    | **FAIL** | Still reads `{{COMPANY_NAME}}`                                                  |
| `workflow.ticket_prefix` = "REN"     | PASS     | Correctly set                                                                   |
| `workflow.ticket_prefix_lower`       | **FAIL** | Still reads `{{TICKET_PREFIX_LOWER}}`                                           |
| `workflow.main_branch`               | **FAIL** | Still reads `{{MAIN_BRANCH}}` - should be `dev`                                 |
| `workflow.linear_workspace`          | **FAIL** | Still reads `{{LINEAR_WORKSPACE}}` - should be `cheddarfox`                     |
| `mcp_servers.linear`                 | PASS     | Correctly set to `claude_ai_Linear`                                             |
| `mcp_servers.confluence`             | PASS     | Correctly set to `claude_ai_Atlassian`                                          |
| `review_stages.stage_2.reviewer`     | **FAIL** | Still reads `{{ARCHITECT_GITHUB_HANDLE}}`                                       |
| `review_stages.stage_3.reviewer`     | **FAIL** | Still reads `{{AUTHOR_HANDLE}}` - should be `cheddarfox`                        |
| `gates.hitl_merge.owner`             | **FAIL** | Still reads `{{AUTHOR_HANDLE}}`                                                 |
| Quality gate commands (7 commands)   | **FAIL** | All still template placeholders (e.g., `{{LINT_COMMAND}}`, `{{BUILD_COMMAND}}`) |
| Agent validation commands (4 agents) | **FAIL** | All still template placeholders                                                 |

---

## 2. Gemini Files Verification

### .gemini/GEMINI.md - FAIL

| Check                         | Result   | Notes                                                                                                           |
| ----------------------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| `REN` ticket prefix           | PASS     | Used in branch/commit examples                                                                                  |
| Project description           | **FAIL** | Line 3: "REN (Words to Film By)" - should say "REN (RenderTrust)"                                               |
| Linear tip                    | **FAIL** | Line 154: references `[WOR-123]` - should use `[REN-123]`                                                       |
| Next.js/Clerk/Prisma patterns | **FAIL** | RLS section (lines 131-145) uses TypeScript/Prisma code examples with Clerk - should reflect FastAPI/SQLAlchemy |

### .gemini/README.md - FAIL

| Check                        | Result   | Notes                                                               |
| ---------------------------- | -------- | ------------------------------------------------------------------- |
| `TICKET_PREFIX=WOR`          | **FAIL** | Line 219: environment variable example says `WOR` - should be `REN` |
| `MAIN_BRANCH=main`           | **FAIL** | Line 225: should be `dev`                                           |
| `frontend-patterns: Next.js` | **FAIL** | Line 76: should reference React 18 + Electron                       |
| Copyright attribution        | PASS     | Correctly shows J. Scott Graham / ByBren, LLC                       |

### .gemini/settings.json - PASS (with note)

| Check                          | Result          | Notes                                                              |
| ------------------------------ | --------------- | ------------------------------------------------------------------ |
| JSON structure                 | PASS            | Valid JSON                                                         |
| `{{GEMINI_MODEL}}` placeholder | PASS (expected) | This is intentionally left as a placeholder for user configuration |
| Context patterns               | PASS            | Include/exclude patterns reasonable                                |

---

## 3. Key Documentation Verification

### docs/guides/GETTING-STARTED.md - FAIL

| Check                           | Result   | Notes                                        |
| ------------------------------- | -------- | -------------------------------------------- |
| `REN` ticket prefix             | PASS     | Used in examples                             |
| `RenderTrust` project name      | PASS     | Line 76 table correctly shows replaced value |
| `{{GITHUB_ORG}}` placeholders   | **FAIL** | Lines 27, 44: unreplaced                     |
| `{{PROJECT_REPO}}` placeholders | **FAIL** | Lines 27, 44: unreplaced                     |
| `{{MAIN_BRANCH}}` placeholder   | **FAIL** | Lines 48, 79: unreplaced                     |
| `{{AUTHOR_HANDLE}}` placeholder | **FAIL** | Line 81: unreplaced                          |

**Note**: Some of these are in "adoption guide" context where they demonstrate the setup process. Lines 27/44 may be intentionally templated for users copying the harness. Lines 76-81 in the table mix replaced and unreplaced values, which is inconsistent.

### docs/guides/ROUND-TABLE-PHILOSOPHY.md - FAIL

| Check                     | Result   | Notes                                              |
| ------------------------- | -------- | -------------------------------------------------- |
| Content quality           | PASS     | Excellent, comprehensive document                  |
| `{{CI_VALIDATE_COMMAND}}` | **FAIL** | Line 167: unreplaced                               |
| `{{POPM_NAME}}`           | **FAIL** | Line 178: unreplaced - should be "J. Scott Graham" |
| `{{GITHUB_REPO_URL}}`     | **FAIL** | Line 323: unreplaced                               |
| `{{AUTHOR_EMAIL}}`        | **FAIL** | Line 324: unreplaced                               |

### docs/team/PLANNING-AGENT-META-PROMPT.md - FAIL (Tech Stack Mismatch)

| Check                         | Result   | Notes                                                                                                                      |
| ----------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------- |
| Content quality               | PASS     | Thorough SAFe planning methodology                                                                                         |
| Technology Stack section      | **FAIL** | Lines 534-541: Lists Next.js 15, Prisma ORM, Clerk auth. Should be FastAPI, SQLAlchemy 2.x + Alembic, custom JWT           |
| Repository Structure          | **FAIL** | Lines 546-562: Shows `/app` (Next.js App Router), `/components`, `/lib/prisma.ts`. Should show `core/`, `sdk/`, `edgekit/` |
| Code examples                 | **FAIL** | Lines 567-607: All TypeScript with Prisma/Clerk imports. Should be Python/FastAPI examples                                 |
| `yarn ci:validate` references | **FAIL** | Lines 442, 179: Should be `make ci` per CLAUDE.md                                                                          |

### docs/security/SECURITY_FIRST_ARCHITECTURE.md - FAIL

| Check                         | Result   | Notes                                                                                        |
| ----------------------------- | -------- | -------------------------------------------------------------------------------------------- |
| Title includes "RenderTrust"  | PASS     | Correctly named                                                                              |
| `{{ARCHITECT_GITHUB_HANDLE}}` | **FAIL** | Lines 5, 170: Confluence URLs use unreplaced placeholder                                     |
| TypeScript code examples      | **FAIL** | Lines 28-61: Uses TypeScript with Prisma/Clerk patterns. Should be Python/FastAPI/SQLAlchemy |

---

## 4. Systematic Issues Found

### 4.1 Branch Name: `main` vs `dev` (CRITICAL)

RenderTrust's main branch is `dev`, not `main`. The following files incorrectly reference `main`:

- `.claude/hooks-config.json` - Lines 9, 31, 41 (push blocker and warning hooks)
- `.claude/team-config.json` - `workflow.main_branch` still `{{MAIN_BRANCH}}`
- `.gemini/README.md` - Line 225: `MAIN_BRANCH=main`
- `.gemini/skills/safe-workflow/SKILL.md` - Lines 57, 66: `git checkout {{MAIN_BRANCH}}`
- `.gemini/skills/release-patterns/SKILL.md` - Line 25: `origin/{{MAIN_BRANCH}}`
- `.gemini/commands/workflow/release.toml` - Lines 20, 43: `{{MAIN_BRANCH}}`

### 4.2 Tech Stack Mismatch: Next.js/Prisma/Clerk vs FastAPI/SQLAlchemy/JWT (CRITICAL)

The harness was imported from a Next.js project. RenderTrust uses FastAPI + React/Electron. The following files contain incorrect tech stack references:

**Claude skills/agents with wrong tech stack:**

- `.claude/skills/frontend-patterns/` - Entire skill is Next.js App Router + Clerk focused
- `.claude/skills/api-patterns/SKILL.md` - Uses Next.js API routes + Clerk auth
- `.claude/skills/rls-patterns/SKILL.md` - Prisma-based RLS (should be SQLAlchemy)
- `.claude/skills/testing-patterns/SKILL.md` - Jest-based (should be pytest)
- `.claude/skills/migration-patterns/SKILL.md` - Prisma migration (should be Alembic)
- `.claude/agents/be-developer.md` - `yarn` commands, Clerk/Prisma imports
- `.claude/agents/fe-developer.md` - Next.js App Router, Clerk auth
- `.claude/agents/qas.md` - Jest/yarn test commands (should be pytest)
- `.claude/agents/system-architect.md` - Clerk/Prisma code examples
- `.claude/agents/bsa.md` - References Next.js/Prisma/Clerk
- `.claude/agents/data-engineer.md` - Prisma migration commands
- `.claude/agents/rte.md` - `yarn ci:validate` commands
- `.claude/agents/tdm.md` - `yarn ci:validate` commands

**Gemini equivalents have the same issues.**

**Affected docs:**

- `docs/team/PLANNING-AGENT-META-PROMPT.md` - Full tech stack section is wrong
- `docs/security/SECURITY_FIRST_ARCHITECTURE.md` - TypeScript code examples

### 4.3 Unreplaced Template Placeholders (Across repo, excluding intentional template files)

**In `.claude/` directory** (27+ occurrences in team-config.json alone):

- `{{PROJECT_REPO}}`, `{{PROJECT_DOMAIN}}`, `{{GITHUB_ORG}}`, `{{COMPANY_NAME}}`
- `{{TICKET_PREFIX_LOWER}}`, `{{MAIN_BRANCH}}`, `{{LINEAR_WORKSPACE}}`
- `{{AUTHOR_HANDLE}}`, `{{ARCHITECT_GITHUB_HANDLE}}`
- `{{LINT_COMMAND}}`, `{{TYPE_CHECK_COMMAND}}`, `{{BUILD_COMMAND}}`, `{{TEST_UNIT_COMMAND}}`, `{{TEST_INTEGRATION_COMMAND}}`, `{{TEST_E2E_COMMAND}}`, `{{SECURITY_SCAN_COMMAND}}`, `{{CI_VALIDATE_COMMAND}}`, `{{DB_MIGRATE_COMMAND}}`, `{{LINT_MD_COMMAND}}`
- `{{DEV_CONTAINER}}`, `{{STAGING_CONTAINER}}`
- `{{SSH_KEY_PATH}}`, `{{REMOTE_USER}}`, `{{REMOTE_HOST}}`, `{{PROJECT_PATH}}`

**In `.gemini/` directory** (50+ occurrences):

- `{{HARNESS_VERSION}}` in 17 skill README files
- `{{MAIN_BRANCH}}`, `{{CI_VALIDATE_COMMAND}}` in skills
- `{{PROJECT}}`, `{{ORG_NAME}}`, `{{REPO_NAME}}`, `{{PROJECT_TEAM_NAME}}` in linear-sop skill
- `{{GEMINI_MODEL}}` in settings.json (likely intentional)

**In `docs/` directory** (80+ occurrences):

- Spread across onboarding, whitepapers, guides
- `{{GITHUB_REPO_URL}}`, `{{AUTHOR_EMAIL}}`, `{{POPM_NAME}}`
- Various command placeholders

### 4.4 `{{DEV_MACHINE}}` Placeholder (Intentionally Left)

The `{{DEV_MACHINE}}` placeholder appears in 5 deprecated command files:

- `.claude/commands/deploy-dev.md`
- `.claude/commands/dev-logs.md`
- `.claude/commands/dev-health.md`
- `.claude/commands/check-docker-status.md`
- `.claude/commands/rollback-dev.md`

This was intentionally left per the task description.

### 4.5 "Words to Film By" References (Should be RenderTrust)

- `.gemini/GEMINI.md` line 3: "REN (Words to Film By)" - should be "REN (RenderTrust)"
- `.gemini/GEMINI.md` line 154: "[WOR-123]" example
- `docs/whitepapers/HARNESS-v2.5.0-KT.md`: Multiple WOR-XXX ticket references
- `.gemini/README.md` line 219: `TICKET_PREFIX=WOR`

---

## 5. Missing Cross-Referenced Files

The following files are referenced in the harness but do not exist in the repository:

| Missing File                                                                  | Referenced By                            |
| ----------------------------------------------------------------------------- | ---------------------------------------- |
| `docs/sop/AGENT_WORKFLOW_SOP.md`                                              | AGENTS.md, ROUND-TABLE-PHILOSOPHY.md     |
| `docs/workflow/ARCHITECT_IN_CLI_ROLE.md`                                      | AGENTS.md, .claude/README.md             |
| `docs/ci-cd/CI-CD-Pipeline-Guide.md`                                          | AGENTS.md, PLANNING-AGENT-META-PROMPT.md |
| `docs/database/DATA_DICTIONARY.md`                                            | AGENT_OUTPUT_GUIDE.md, multiple agents   |
| `docs/database/RLS_DATABASE_MIGRATION_SOP.md`                                 | AGENTS.md, multiple agents               |
| `docs/database/RLS_IMPLEMENTATION_GUIDE.md`                                   | AGENT_OUTPUT_GUIDE.md, multiple skills   |
| `docs/database/RLS_POLICY_CATALOG.md`                                         | AGENT_OUTPUT_GUIDE.md                    |
| `docs/guides/RLS_TROUBLESHOOTING.md`                                          | AGENT_OUTPUT_GUIDE.md                    |
| `docs/HARNESS_SYNC_GUIDE.md`                                                  | GETTING-STARTED.md                       |
| `TEMPLATE_SETUP.md`                                                           | GETTING-STARTED.md                       |
| `.github/pull_request_template.md`                                            | CONTRIBUTING.md                          |
| `specs/planning_template.md`                                                  | PLANNING-AGENT-META-PROMPT.md            |
| `specs/spec_template.md`                                                      | PLANNING-AGENT-META-PROMPT.md            |
| `docs/security/AUTHENTICATION.md`                                             | SECURITY_FIRST_ARCHITECTURE.md           |
| `docs/security/RLS_TROUBLESHOOTING.md`                                        | SECURITY_FIRST_ARCHITECTURE.md           |
| `docs/security/ENVIRONMENT_VARIABLES.md`                                      | SECURITY_FIRST_ARCHITECTURE.md           |
| `docs/agent-outputs/workflow-analysis/HARNESS_AND_SKILLS_AUDIT_2025-12-18.md` | .claude/README.md                        |
| `docs/quality-reports/.markdownlint-cli2.jsonc`                               | AGENT_OUTPUT_GUIDE.md                    |
| `.cursor/rules/06-team-culture.mdc`                                           | .claude/README.md                        |
| `docs/sop/AGENT_CONFIGURATION_SOP.md`                                         | AGENTS.md                                |
| `docs/whitepapers/CLAUDE-CODE-HARNESS-MODERNIZATION-REN-444.md`               | AGENTS.md                                |
| `docs/whitepapers/CLAUDE-CODE-HARNESS-AGENT-PERSPECTIVE.md`                   | AGENTS.md                                |

---

## 6. File Completeness Verification

### .claude/ Directory

| Item                   | Expected       | Actual                      | Status |
| ---------------------- | -------------- | --------------------------- | ------ |
| Agent configs          | 11 + README    | 12 files                    | PASS   |
| Commands               | 20+            | 25 files                    | PASS   |
| Skills                 | 18 directories | 19 (18 + team-coordination) | PASS   |
| Hook scripts           | 3              | 3                           | PASS   |
| README.md              | 1              | 1                           | PASS   |
| hooks-config.json      | 1              | 1                           | PASS   |
| team-config.json       | 1              | 1                           | PASS   |
| AGENT_OUTPUT_GUIDE.md  | 1              | 1                           | PASS   |
| SETUP.md               | 1              | 1                           | PASS   |
| TROUBLESHOOTING.md     | 1              | 1                           | PASS   |
| settings.json          | 1              | 1                           | PASS   |
| settings.local.json    | 1              | 1                           | PASS   |
| settings.template.json | 1              | 1                           | PASS   |

### .gemini/ Directory

| Item          | Expected                                 | Actual         | Status |
| ------------- | ---------------------------------------- | -------------- | ------ |
| GEMINI.md     | 1                                        | 1              | PASS   |
| README.md     | 1                                        | 1              | PASS   |
| settings.json | 1                                        | 1              | PASS   |
| Skills        | 17+                                      | 18 directories | PASS   |
| Commands      | Workflow + Local + Remote + Media + Root | All present    | PASS   |

### Correctly Replaced Values (Working)

| Value                                                | Status | Notes                                                            |
| ---------------------------------------------------- | ------ | ---------------------------------------------------------------- |
| `{{TICKET_PREFIX}}` -> `REN`                         | PASS   | Replaced in CLAUDE.md, AGENTS.md, CONTRIBUTING.md, agent configs |
| `{{PROJECT_NAME}}` -> `RenderTrust`                  | PASS   | Replaced in key top-level files                                  |
| `{{PROJECT_SHORT}}` -> `REN`                         | PASS   | Used in branch format, commit format                             |
| `{{AUTHOR_NAME}}` -> `J. Scott Graham`               | PASS   | Set in AGENTS.md, CONTRIBUTING.md                                |
| `{{MCP_LINEAR_SERVER}}` -> `claude_ai_Linear`        | PASS   | Correct in team-config.json                                      |
| `{{MCP_CONFLUENCE_SERVER}}` -> `claude_ai_Atlassian` | PASS   | Correct in team-config.json                                      |

---

## 7. AGENTS.md Spot Check

AGENTS.md has been correctly customized:

- DE tools: "SQLAlchemy, Alembic, SQL" - PASS
- QAS tools: "pytest, Playwright, Linear MCP" - PASS
- No Next.js/Clerk/Prisma/Jest references - PASS
- `ruff check .` used for linting - PASS
- `pytest` used for testing - PASS

AGENTS.md is one of the best-customized files in the harness.

---

## 8. CONTRIBUTING.md Spot Check

CONTRIBUTING.md has been correctly customized:

- Python 3.11+ prerequisites - PASS
- `pip install`, `alembic`, `docker compose` commands - PASS
- No Next.js/Prisma/Clerk/Jest references - PASS
- Multi-license model documented - PASS
- `make ci` as validation command - PASS

CONTRIBUTING.md is well-customized for RenderTrust.

---

## Summary

### Severity Classification

| Severity | Count | Description                                                                                                 |
| -------- | ----- | ----------------------------------------------------------------------------------------------------------- |
| CRITICAL | 2     | Branch name `main` vs `dev` in hooks; Tech stack mismatch (Next.js vs FastAPI)                              |
| HIGH     | 3     | team-config.json unreplaced placeholders; GEMINI.md "Words to Film By"; Missing cross-referenced files (22) |
| MEDIUM   | 2     | docs/ unreplaced placeholders (80+); .gemini/ unreplaced placeholders (50+)                                 |
| LOW      | 1     | `{{DEV_MACHINE}}` intentionally left (acceptable)                                                           |

### Verdict: BLOCKED

The harness installation is **structurally complete** -- all expected directories, files, agents, skills, and commands are present. The core files (CLAUDE.md, AGENTS.md, CONTRIBUTING.md) have been well-customized for RenderTrust's actual tech stack (FastAPI, SQLAlchemy, Python).

However, the **inner harness files** (skills, agent configs, docs) still carry the source project's tech stack (Next.js, Prisma, Clerk, Jest, yarn). This creates a significant inconsistency: CLAUDE.md tells agents to use `pytest` and `ruff`, but the skills and agent configs show `yarn test:unit` and `import { auth } from "@clerk/nextjs/server"`.

### Recommended Remediation Priority

1. **P0 (Before merge)**: Fix hooks-config.json branch references (`main` -> `dev`)
2. **P0 (Before merge)**: Replace remaining critical placeholders in team-config.json (`{{MAIN_BRANCH}}` -> `dev`, `{{LINEAR_WORKSPACE}}` -> `cheddarfox`, `{{AUTHOR_HANDLE}}` -> `cheddarfox`, etc.)
3. **P1 (Next sprint)**: Rewrite skills/agents for FastAPI/SQLAlchemy/pytest stack (large effort -- create REN-XX epic)
4. **P1 (Next sprint)**: Fix GEMINI.md "Words to Film By" and WOR- references
5. **P2 (Backlog)**: Replace remaining template placeholders in docs/
6. **P2 (Backlog)**: Create missing cross-referenced files or remove broken links

### Decision for HITL

Given that this is a harness installation (not production code), I recommend:

- **Merge with known issues** if P0 items are fixed
- Track P1/P2 as separate Linear tickets
- The CLAUDE.md and AGENTS.md files (the primary context sources for agents) are correctly customized, which means agents will get the RIGHT instructions even if the inner skill files have wrong examples

---

_QAS validation performed by Claude Opus 4.6 on 2026-03-08_
_Linear Issue: REN-60_
