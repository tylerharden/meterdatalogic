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
