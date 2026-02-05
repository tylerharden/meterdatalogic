# Release Process

This document describes how to release a new version of meterdatalogic.

## Prerequisites

- Ensure all tests pass: `make test`
- Ensure linting passes: `make lint`
- All changes are committed and pushed to master

## Release Workflow

### Option 1: Automated

```bash
# 1. Bump version (creates commit + tag automatically)
make bump-patch   # for bug fixes (0.1.4 → 0.1.5)
make bump-minor   # for new features (0.1.4 → 0.2.0)
make bump-major   # for breaking changes (0.1.4 → 1.0.0)

# 2. Review the changes
git show
git log --oneline -3

# 3. Push to GitHub
git push && git push --tags

# 4. Create GitHub release (optional, with gh CLI)
make release
```

### Option 2: Manual

```bash
# 1. Update version in pyproject.toml
# Edit: version = "0.1.5"

# 2. Update CHANGELOG.md
# Move items from [Unreleased] to new version section

# 3. Commit and tag
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 0.1.5"
git tag -a v0.1.5 -m "Release v0.1.5"

# 4. Push
git push && git push --tags

# 5. Create GitHub release manually at:
# https://github.com/tylerharden/meterdatalogic/releases/new
```

## Publishing to PyPI

```bash
# 1. Build the package
make build

# 2. Check the built package
ls -lh dist/

# 3. Publish to PyPI (requires credentials)
make publish
# Or manually:
# uv run twine upload dist/*
```

## Version Numbering (Semantic Versioning)

- **MAJOR** (1.0.0): Breaking changes to the API
- **MINOR** (0.2.0): New features, backward compatible
- **PATCH** (0.1.5): Bug fixes, backward compatible

Examples:
- Bug fix: `0.1.4 → 0.1.5`
- New feature (no breaking changes): `0.1.5 → 0.2.0`
- Breaking API change: `0.2.0 → 1.0.0`

## Checklist

Before releasing, ensure:

- [ ] All tests pass (`make test`)
- [ ] Linting passes (`make lint`)
- [ ] CHANGELOG.md is updated
- [ ] Version number follows semantic versioning
- [ ] README.md is up to date
- [ ] All PRs/issues for this release are closed
- [ ] Documentation is updated if needed

## Rollback

If you need to rollback a release:

```bash
# Delete the tag locally and remotely
git tag -d v0.1.5
git push origin :refs/tags/v0.1.5

# Revert the version commit
git revert HEAD
git push
```
