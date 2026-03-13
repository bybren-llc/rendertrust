# RenderTrust Planning Specifications

This directory contains planning specifications and templates for the RenderTrust project, following the WTFB Linear Agents methodology.

## Directory Structure

```
specs/
├── README.md                    # This file
├── templates/                   # Planning templates
│   └── planning_template.md     # SAFe methodology planning template
├── wip/                        # Work In Progress planning documents
├── todo/                       # Planning documents to be processed
├── doing/                      # Currently active planning documents
└── done/                       # Completed planning documents
```

## Workflow

### 1. Planning Document Creation
When creating a new planning document:
1. Copy `templates/planning_template.md` to `todo/`
2. Name the file: `[component-name]-planning.md`
3. Fill out all sections with appropriate detail
4. Move to `doing/` when actively working on it
5. Move to `done/` when Linear issues are created

### 2. Linear Issue Creation
Use completed planning documents to create properly structured Linear issues following SAFe methodology:
- **Epics**: High-level business capabilities
- **Features**: Specific functionality within epics
- **User Stories**: User-focused requirements
- **Technical Enablers**: Infrastructure/architecture work
- **Spikes**: Research and investigation tasks

## Available Templates

### planning_template.md
Comprehensive template for analyzing Confluence documentation and creating structured Linear issues.

#### Usage
1. Copy template to appropriate folder (todo/doing/done)
2. Name following convention: `feature-name-planning.md`
3. Fill out all sections with appropriate detail
4. Use completed document to create Linear issues

## Template Maintenance

When updating templates:
1. Consider impact on existing workflows
2. Ensure backward compatibility where possible
3. Update related scripts in `/scripts` directory
4. Update this README with change information
5. Document changes in Confluence

## Contact

For questions about planning specifications or templates:
- **Project**: RenderTrust
- **Team**: REN
- **Documentation**: [Confluence WA Space](https://cheddarfox.atlassian.net/wiki/spaces/WA/)
