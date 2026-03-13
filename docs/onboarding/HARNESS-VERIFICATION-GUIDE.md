# SAFe Agentic Workflow Harness — Verification Guide

**Purpose**: Trust-and-verify checklist for the Claude team to confirm the harness is correctly installed and functional.

**Linear Issue**: [REN-60](https://linear.app/cheddarfox/issue/REN-60)
**Harness Version**: v2.6.0 (adapted from [safe-agentic-workflow](https://github.com/bybren-llc/safe-agentic-workflow))

---

## 1. File Structure Verification

Run these checks to confirm all artifacts are in place:

```bash
# Agents (should list 11 + README = 12 files)
ls .claude/agents/*.md | wc -l  # Expected: 12

# Commands (should list 20 + README = 21 files)
ls .claude/commands/*.md | wc -l  # Expected: 21

# Skills (should list 18 directories)
ls -d .claude/skills/*/  | wc -l  # Expected: 18

# Hooks (should list 3 files)
ls .claude/hooks/*.sh | wc -l  # Expected: 3

# Top-level files
test -f CLAUDE.md && echo "CLAUDE.md: OK" || echo "CLAUDE.md: MISSING"
test -f AGENTS.md && echo "AGENTS.md: OK" || echo "AGENTS.md: MISSING"
test -f CONTRIBUTING.md && echo "CONTRIBUTING.md: OK" || echo "CONTRIBUTING.md: MISSING"

# Supporting directories
test -d patterns_library && echo "patterns_library/: OK" || echo "patterns_library/: MISSING"
test -d dark-factory && echo "dark-factory/: OK" || echo "dark-factory/: MISSING"
test -d agent_providers && echo "agent_providers/: OK" || echo "agent_providers/: MISSING"
```

## 2. Placeholder Verification

Confirm no raw template placeholders remain in critical files:

```bash
# Should return ZERO results for these files
grep -c '{{[A-Z_]*}}' CLAUDE.md AGENTS.md CONTRIBUTING.md .claude/settings.json

# Some remaining placeholders are expected in patterns_library/ and docs/
# templates — those are generic examples, not project-specific config
```

### Expected Values

| Field | Expected Value |
|-------|---------------|
| Ticket prefix | `REN` |
| Main branch | `dev` |
| Project name | `rendertrust` |
| GitHub org | `ByBren-LLC` |
| Linear MCP server | `claude_ai_Linear` |
| Confluence MCP server | `claude_ai_Atlassian` |

## 3. CLAUDE.md Content Verification

Open `CLAUDE.md` and verify these sections exist and are correct:

- [ ] **Technology Stack** lists: FastAPI, PostgreSQL 16, SQLAlchemy 2.x, React 18 + Electron
- [ ] **Repository Structure** includes: core/, sdk/, edgekit/, rollup_anchor/, dark-factory/
- [ ] **Deployment Stack** mentions: Coolify, Cloudflare, Solidity, Edge Nodes
- [ ] **Development Commands** use: `docker compose`, `ruff`, `pytest`, `alembic`, `make ci`
- [ ] **PR Workflow** references branch format `REN-{number}-{description}`
- [ ] **Commit format** is `type(scope): description [REN-XXX]`
- [ ] **Branch protection** targets `dev` (not `main`)
- [ ] **Licensing section** lists MIT / Apache 2.0 / Enterprise directories

## 4. CONTRIBUTING.md Verification

- [ ] **Licensing Guidelines** section preserved (MIT, Apache 2.0, Enterprise)
- [ ] **License headers** include correct copyright (`Words To Film By, Inc.`)
- [ ] **SAFe workflow** sections present (branch naming, commit format, agent exit states)
- [ ] **Commands** reference Python tooling (`ruff`, `pytest`, `mypy`, `alembic`) not Node.js
- [ ] **Gate Quick Reference** table lists all 5 gates with correct owners

## 5. AGENTS.md Verification

- [ ] **11 agent roles** listed in the "When to Use Which Agent" table
- [ ] **DE tools** say `SQLAlchemy, Alembic, SQL` (not Prisma)
- [ ] **QAS tools** say `pytest, Playwright` (not Jest)
- [ ] **Frontend patterns** reference `React 18, Electron, ShadCN` (not Next.js, Clerk)
- [ ] **Success Validation Commands** use Python tooling
- [ ] **POPM** set to `J. Scott Graham`

## 6. Linear MCP Integration

Test that the Linear MCP server can read REN issues:

```
# In a Claude Code session with MCP enabled:
# Ask: "List the 5 most recent REN issues from Linear"
# Expected: Should return issues like REN-60, REN-59, REN-47, etc.
```

Verify `.claude/settings.local.json` has:
```json
{
  "enableAllProjectMcpServers": true
}
```

## 7. Settings Verification

```bash
# Project settings (committed, shared)
cat .claude/settings.json
# Should show: permissions with Linear/Atlassian MCP access

# Local settings (NOT committed, user-specific)
cat .claude/settings.local.json
# Should show: enableAllProjectMcpServers: true

# Gitignore check
grep "settings.local.json" .gitignore
# Should find the exclusion rule
```

## 8. Agent Role Spot-Check

Pick 2-3 agent files and verify they contain RenderTrust-specific context:

```bash
# Check that agent files reference REN tickets and RenderTrust tools
grep -l "REN" .claude/agents/*.md
grep -l "rendertrust\|RenderTrust" .claude/agents/*.md
```

## 9. Dark Factory Verification

```bash
# Verify team layouts exist
ls dark-factory/templates/team-layouts/
# Expected: epic-team.sh, feature-team.sh, story-team.sh

# Verify scripts are executable
ls -la dark-factory/scripts/*.sh
# All should have execute permissions
```

## 10. What's NOT Yet Done

These items from the REN-60 acceptance criteria require runtime validation:

- [ ] **Commit hooks enforcement**: Needs `make ci` / pre-commit hook setup (depends on CI pipeline)
- [ ] **End-to-end workflow test**: `/start-work REN-XX` → implement → `/pre-pr` → PR → merge → `/end-work`
- [ ] **Dark Factory tmux session**: Requires remote server with tmux + Claude Code installed

These will be validated as part of the first Cycle 1 implementation work.

---

## Quick Start for New Agent Sessions

After the harness is merged, any Claude Code session in this repo will automatically have access to:

1. **CLAUDE.md** — loaded as project context
2. **Skills** — triggered by context (e.g., database work loads `rls-patterns`)
3. **Commands** — invocable via `/command-name` (e.g., `/start-work REN-123`)
4. **Agents** — spawnable via `@agent-name` or Task tool

To start working on an issue:
```
/start-work REN-123
```

Before creating a PR:
```
/pre-pr
```
