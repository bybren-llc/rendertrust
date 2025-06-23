# RenderTrust Planning Scripts

This directory contains scripts for the RenderTrust project planning workflow.

## Available Scripts

### start-planning-agent.sh
This script initializes a planning agent with instructions to analyze Confluence documentation and create properly structured Linear issues following SAFe methodology.

#### Usage
```bash
./start-planning-agent.sh [CONFLUENCE_PAGE_URL] [PLANNING_TITLE]
```

#### Example
```bash
./start-planning-agent.sh "https://cheddarfox.atlassian.net/wiki/spaces/WA/pages/252477442" "Core Foundation Implementation"
```

### create-linear-issues.sh
Script to create Linear issues from completed planning documents.

#### Usage
```bash
./create-linear-issues.sh [PLANNING_DOCUMENT_PATH]
```

#### Example
```bash
./create-linear-issues.sh "specs/done/core-foundation-planning.md"
```

## Workflow Scripts

### move-planning-doc.sh
Utility script to move planning documents between workflow stages.

#### Usage
```bash
./move-planning-doc.sh [DOCUMENT_NAME] [FROM_STAGE] [TO_STAGE]
```

#### Example
```bash
./move-planning-doc.sh "core-foundation-planning.md" "todo" "doing"
```

## Adding New Scripts

When adding new scripts to this directory, please:
1. Follow the naming convention: `[action]-[purpose].sh`
2. Include detailed comments and usage instructions
3. Update this README with information about the new script
4. Ensure the script checks for required dependencies
5. Make scripts executable: `chmod +x script-name.sh`

## Dependencies

Scripts in this directory may require:
- Linear CLI (for Linear integration)
- curl (for API calls)
- jq (for JSON processing)
- git (for repository operations)

## Contact

For questions about planning scripts:
- **Project**: RenderTrust
- **Team**: REN
- **Repository**: https://github.com/cheddarfox/rendertrust
