# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 

### Changed
-

### Fixed
-

## [0.1.6] - 2026-02-05

### Fixed
- Fixed pandas 2.2+ compatibility with lowercase frequency strings (`"h"` instead of `"H"`)

## [0.1.5] - 2026-02-05

### Added
- MIT License file for open source distribution
- Automated test coverage reporting with pytest-cov
- GitHub Actions CI/CD workflow for automated testing across Python 3.10, 3.11, 3.12
- Codecov integration for coverage tracking
- Pre-commit hooks for automated code formatting and linting with ruff
- Automated version bump script (`scripts/bump_version.sh`)
- Comprehensive project documentation (API reference, examples, contributing guide)
- Documentation reorganization into guides/, features/, and reference/ directories
- PyPI trusted publishing support for secure, token-free releases
- Pre-release version detection in release workflow (alpha, beta, rc)
- Copilot instructions for AI-assisted development
- Enhanced validation functions for comprehensive data quality checks

### Changed
- Updated GitHub Actions release workflow with automated PyPI publishing
- Enhanced pyproject.toml with complete project metadata (authors, keywords, classifiers, URLs)
- Improved Makefile with coverage cleanup commands
- Updated .gitignore to exclude coverage reports and test artifacts
- Refactored documentation structure with dedicated guides and reference sections
- Updated README with modern release workflow and PyPI setup instructions
- Removed duplicate nemreader dependency from main dependencies (kept in nem12 extra)
- Enhanced utils module with expanded utility functions
- Improved error handling and logging throughout insights engine
- Streamlined exception handling in modules

### Fixed
- Fixed pyproject.toml structure (moved dependencies to correct location)
- Resolved build configuration errors for setuptools

## [0.1.4] - 2025-01-07

### Added
- Added uv support for 10-100x faster dependency installation
- Added error logging to insights engine for better debuggability
- Added comprehensive utility functions to eliminate code duplication
- Added `.python-version` file for consistent Python version
- Added example GitHub Actions workflow using uv

### Changed
- Updated to modern uv workflow with automatic environment management
- Consolidated duplicate code patterns into reusable utilities
- Enhanced documentation with requirements, timezone handling, and performance notes
- Improved insights configuration with detailed docstrings explaining rationale

### Fixed
- Resolved all type checking errors (pandas-stubs, NEMFile, TypedDict)
- Fixed string to int conversion type errors in transform.py
- Fixed numpy version constraint to use realistic versions

---

## How to maintain this changelog

Before releasing:
1. Move items from `[Unreleased]` to a new version section
2. Add the release date
3. Update the version links at the bottom
4. Commit the changelog with the version bump

Categories:
- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes
