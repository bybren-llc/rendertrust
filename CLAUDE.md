# CLAUDE.md

## AI Assistant Context for SAFe Multi-Agent Development

**Repository**: rendertrust
**Methodology**: SAFe (Scaled Agile Framework) Agentic Workflow
**Philosophy**: "Round Table" - Equal voice, mutual respect, shared responsibility

---

## Quick Start

This is a **SAFe multi-agent development project** with 11 specialized AI agents working collaboratively. You are part of a team where your input has equal weight with human contributors.

**Core Principles**:
- Search for existing patterns before creating new ones ("Search First, Reuse Always")
- Attach evidence to Linear tickets for all work
- You have "stop-the-line" authority for architectural/security concerns
- Follow SAFe methodology: Epic → Feature → Story → Enabler

**Key Resources**:
- [AGENTS.md](AGENTS.md) - All 11 agent roles, invocation patterns, capabilities
- [CONTRIBUTING.md](CONTRIBUTING.md) - Git workflow, commit standards, PR process
- [docs/onboarding/](docs/onboarding/) - Setup guides and daily workflows
- [docs/guides/ROUND-TABLE-PHILOSOPHY.md](docs/guides/ROUND-TABLE-PHILOSOPHY.md) - Collaboration principles
- [patterns_library/](patterns_library/) - Reusable code patterns (18+ patterns, 7 categories)

---

## Development Commands

```bash
# Development server
docker compose up              # Start development server

# Build and production
docker compose build            # Build for production
docker compose up -d            # Start production server

# Code quality
ruff check .              # Run linting
ruff check . --fix        # Auto-fix linting issues
mypy .                    # Type checking (Python)

# Testing
pytest        # Run unit tests
pytest tests/integration # Run integration tests
pytest tests/e2e         # Run end-to-end tests

# Database (if applicable)
alembic upgrade head       # Run migrations

# CI/CD validation (REQUIRED before PR)
make ci      # Run all quality checks
```

**Important**: Always run `make ci` before creating a pull request.

---

## Architecture Overview

### Technology Stack

- **Frontend**: React 18 + Electron
- **Backend**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 16
- **ORM**: SQLAlchemy 2.x + Alembic
- **Authentication**: JWT (custom)
- **Payments**: Stripe
- **Analytics**: PostHog
- **UI Components**: ShadCN UI + Tailwind

### Repository Structure

```
rendertrust/
├── CLAUDE.md                    # This file - AI assistant context
├── AGENTS.md                    # Agent team quick reference
├── CONTRIBUTING.md              # Git workflow, commit standards, licensing
├── core/                        # Core platform (FastAPI gateway, services) — Apache 2.0
├── sdk/                         # Client SDK (Python/TypeScript) — MIT
├── edgekit/                     # Edge node relay & workers
├── rollup_anchor/               # Solidity smart contracts (on-chain anchoring)
├── docs/                        # Documentation
├── specs/                       # SAFe specifications (Epic/Feature/Story)
├── patterns_library/            # Reusable code patterns (7 categories)
├── scripts/                     # Utility scripts
├── ci/                          # CI/CD pipeline configs
├── loadtest/                    # Load testing harness
├── diagrams/                    # Architecture diagrams
├── .claude/                     # Claude Code harness (hooks, commands, skills, agents)
├── agent_providers/             # Agent configurations
└── dark-factory/                # Tmux agent team layouts
```

### Deployment Stack

- **Hosting**: Coolify (self-hosted PaaS on Hetzner)
- **CDN/DNS**: Cloudflare
- **Blockchain**: Solidity smart contracts (Ethereum/L2 for render anchoring)
- **Edge Nodes**: Distributed rendering nodes with encrypted relay

---

## SAFe Workflow

All work follows the SAFe hierarchy and specs-driven development:

1. BSA creates spec in `specs/REN-XXX-feature-spec.md`
2. System Architect validates architectural approach
3. Implementation agents execute with pattern discovery
4. QAS validates against acceptance criteria
5. Evidence attached to Linear ticket before POPM review

### Metacognitive Tags

Use in specs to highlight critical decisions:
- `#PATH_DECISION` - Architectural path chosen (document alternatives)
- `#PLAN_UNCERTAINTY` - Areas requiring validation
- `#EXPORT_CRITICAL` - Security/compliance requirements

### Pattern Discovery Protocol (MANDATORY)

**Before implementing ANY feature:**

1. Search `patterns_library/` for existing patterns
2. Search `specs/` for similar specifications
3. Search codebase for similar implementations
4. Consult documentation: [CONTRIBUTING.md](CONTRIBUTING.md), [docs/database/](docs/database/), [docs/security/](docs/security/)
5. Propose to System Architect before implementation

---

## Project-Specific Implementation Notes

### Authentication

**Provider**: JWT (custom)

- Custom JWT implementation with refresh token rotation
- Environment variables: See `.env.template`
- API key authentication for edge nodes and SDK clients

### Payments

**Provider**: Stripe

- Webhook endpoint: `/api/v1/webhooks/stripe`
- Idempotency required for all payment operations
- Subscription management for render credits

### Edge Node Deployment

- Edge nodes communicate via encrypted relay (`edgekit/relay/`)
- All render payloads must be encrypted at rest and in transit
- Node registration requires cryptographic identity verification
- Health checks and heartbeat monitoring via gateway

### Blockchain Integration

- Solidity smart contracts in `rollup_anchor/`
- On-chain anchoring for render proof-of-work
- Hardhat for contract development and testing
- Never deploy contracts without security audit sign-off

### Database

**System**: PostgreSQL 16 | **ORM**: SQLAlchemy 2.x + Alembic

**Guidelines**:
- Always use SQLAlchemy models (type safety) with proper session management
- Always create proper migrations (never skip Alembic)
- Use async session patterns for FastAPI endpoints

**Migration Workflow**:
```bash
alembic revision --autogenerate -m "description"  # Create migration
alembic upgrade head                               # Apply locally
git add alembic/versions/ && git commit -m "feat(db): add migration [REN-XXX]"
```

### Licensing

RenderTrust uses a **multi-license model** — see [CONTRIBUTING.md](CONTRIBUTING.md):
- **MIT**: `sdk/`, `loadtest/`, `ci/`, `docs/`, `diagrams/`
- **Apache 2.0**: `core/`, `edgekit/relay/`, `sdk/mcp/`
- **Enterprise**: `rollup_anchor/paymaster/`, premium workers, enterprise gateway

---

## Code Quality

**Linter**: Ruff | **Config**: pyproject.toml

```bash
ruff check .          # Run linter
ruff check . --fix      # Auto-fix issues
```

Always run `ruff check .` before committing. Consult your linting configuration file for project-specific rules.

---

## CI/CD Pipeline

**MANDATORY**: Read [CONTRIBUTING.md](CONTRIBUTING.md) before any development.

### PR Workflow

1. Create feature branch: `REN-{number}-{description}`
2. Implement with proper commits: `type(scope): description [REN-XXX]`
3. Rebase: `git rebase origin/dev`
4. Validate: `make ci` (must pass)
5. Push: `git push --force-with-lease`
6. Create PR using `.github/pull_request_template.md`
7. Merge using "Rebase and merge" only

### Branch Protection

- All PRs must be up-to-date with `dev`
- All CI checks must pass
- CODEOWNERS reviewers required
- No direct pushes to `dev`

**Detailed Guides**: [docs/ci-cd/CI-CD-Pipeline-Guide.md](docs/ci-cd/CI-CD-Pipeline-Guide.md) | [docs/workflow/](docs/workflow/)
