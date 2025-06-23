#!/bin/bash

# RenderTrust Planning Agent Starter Script
# This script initializes a planning agent to analyze Confluence documentation
# and create properly structured Linear issues following SAFe methodology.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [CONFLUENCE_PAGE_URL] [PLANNING_TITLE]"
    echo ""
    echo "Arguments:"
    echo "  CONFLUENCE_PAGE_URL  URL of the Confluence page to analyze"
    echo "  PLANNING_TITLE       Title for the planning document (kebab-case)"
    echo ""
    echo "Example:"
    echo "  $0 'https://cheddarfox.atlassian.net/wiki/spaces/WA/pages/252477442' 'core-foundation-implementation'"
    echo ""
    echo "This script will:"
    echo "  1. Create a new planning document from the template"
    echo "  2. Place it in the specs/todo/ directory"
    echo "  3. Provide instructions for the planning agent"
    exit 1
}

# Check arguments
if [ $# -ne 2 ]; then
    print_error "Invalid number of arguments"
    show_usage
fi

CONFLUENCE_URL="$1"
PLANNING_TITLE="$2"

# Validate inputs
if [[ ! "$CONFLUENCE_URL" =~ ^https://.*atlassian\.net/wiki/spaces/.* ]]; then
    print_error "Invalid Confluence URL format"
    print_warning "Expected format: https://[domain].atlassian.net/wiki/spaces/[SPACE]/pages/[ID]"
    exit 1
fi

if [[ ! "$PLANNING_TITLE" =~ ^[a-z0-9-]+$ ]]; then
    print_error "Invalid planning title format"
    print_warning "Use kebab-case (lowercase letters, numbers, and hyphens only)"
    exit 1
fi

# Set up paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATE_PATH="$PROJECT_ROOT/specs/templates/planning_template.md"
TODO_DIR="$PROJECT_ROOT/specs/todo"
PLANNING_FILE="$TODO_DIR/${PLANNING_TITLE}-planning.md"

# Check if template exists
if [ ! -f "$TEMPLATE_PATH" ]; then
    print_error "Planning template not found at: $TEMPLATE_PATH"
    exit 1
fi

# Create todo directory if it doesn't exist
mkdir -p "$TODO_DIR"

# Check if planning document already exists
if [ -f "$PLANNING_FILE" ]; then
    print_error "Planning document already exists: $PLANNING_FILE"
    print_warning "Remove the existing file or choose a different title"
    exit 1
fi

# Copy template to todo directory
print_status "Creating planning document: $PLANNING_FILE"
cp "$TEMPLATE_PATH" "$PLANNING_FILE"

# Update the template with basic information
print_status "Updating planning document with initial information"
sed -i.bak "s|\[Title\](URL)|$PLANNING_TITLE|g" "$PLANNING_FILE"
sed -i.bak "s|(URL)|($CONFLUENCE_URL)|g" "$PLANNING_FILE"
rm "$PLANNING_FILE.bak"

print_success "Planning document created successfully!"
echo ""
print_status "Next steps:"
echo "1. Open the planning document: $PLANNING_FILE"
echo "2. Fill out all sections based on the Confluence documentation"
echo "3. Move to specs/doing/ when actively working on it"
echo "4. Move to specs/done/ when ready to create Linear issues"
echo ""
print_status "Planning Agent Instructions:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "You are a planning agent for the RenderTrust project. Your task is to:"
echo ""
echo "1. ANALYZE the Confluence documentation at: $CONFLUENCE_URL"
echo "2. FILL OUT the planning document at: $PLANNING_FILE"
echo "3. FOLLOW the SAFe methodology for work breakdown"
echo "4. CREATE comprehensive Linear issues based on the completed planning"
echo ""
echo "Key Requirements:"
echo "• Break down work into Epics → Features → User Stories/Technical Enablers"
echo "• Include detailed acceptance criteria for all work items"
echo "• Consider non-functional requirements (performance, security, scalability)"
echo "• Plan comprehensive testing strategy"
echo "• Document architectural impact and technical debt considerations"
echo ""
echo "When complete, the planning document should provide everything needed"
echo "to create well-structured Linear issues that align with the RenderTrust"
echo "architectural assessment and implementation roadmap."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
print_status "Planning document ready for agent processing!"
