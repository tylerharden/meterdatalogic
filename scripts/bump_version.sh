#!/bin/bash
# Automated version bumping script
# Usage: ./scripts/bump_version.sh [major|minor|patch]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BUMP_TYPE=${1:-patch}

if [[ ! "$BUMP_TYPE" =~ ^(major|minor|patch)$ ]]; then
    echo -e "${RED}Error: Bump type must be major, minor, or patch${NC}"
    echo "Usage: $0 [major|minor|patch]"
    exit 1
fi

# Check for uncommitted changes
if [[ -n $(git status -s) ]]; then
    echo -e "${RED}Error: You have uncommitted changes. Commit or stash them first.${NC}"
    git status -s
    exit 1
fi

# Get current version from pyproject.toml
CURRENT_VERSION=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo -e "${YELLOW}Current version: ${CURRENT_VERSION}${NC}"

# Parse version
IFS='.' read -r -a VERSION_PARTS <<< "$CURRENT_VERSION"
MAJOR="${VERSION_PARTS[0]}"
MINOR="${VERSION_PARTS[1]}"
PATCH="${VERSION_PARTS[2]}"

# Bump version
case "$BUMP_TYPE" in
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    patch)
        PATCH=$((PATCH + 1))
        ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
echo -e "${GREEN}New version: ${NEW_VERSION}${NC}"

# Confirm
read -p "Bump version from ${CURRENT_VERSION} to ${NEW_VERSION}? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Update pyproject.toml
sed -i.bak "s/^version = \".*\"/version = \"${NEW_VERSION}\"/" pyproject.toml
rm pyproject.toml.bak

echo -e "${GREEN}✓ Updated pyproject.toml${NC}"

# Create commit
git add pyproject.toml
git commit -m "chore: bump version to ${NEW_VERSION}"
echo -e "${GREEN}✓ Created commit${NC}"

# Create tag
git tag -a "v${NEW_VERSION}" -m "Release v${NEW_VERSION}"
echo -e "${GREEN}✓ Created tag v${NEW_VERSION}${NC}"

echo ""
echo -e "${GREEN}Success! Version bumped to ${NEW_VERSION}${NC}"
echo ""
echo "Next steps:"
echo "  1. Review the commit: git show"
echo "  2. Push with tags: git push && git push --tags"
echo "  3. Create GitHub release (optional): gh release create v${NEW_VERSION} --generate-notes"
