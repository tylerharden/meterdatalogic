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

## [0.4.0] - 2026-05-20

### Fixed
- **Battery scenario**: rewrote dispatch to a net-metering model (`net = import − export + EV − PV`) — prevents simultaneous import and export in the same interval, which was inflating self-consumption figures
- **EV charging with wrap-around windows** (e.g. 18:00–07:00): positions were sorted by calendar time (midnight first) so charging began at 00:00 instead of the window start; positions are now re-sorted from `window_start`
- **`scenario.run()`**: used a non-unique `DatetimeIndex` for baseline import/export series when multi-flow data had duplicate timestamps, causing incorrect totals — fixed with `.unique()`
- **`data_completeness` insight**: coverage percentage was computed against a raw (potentially duplicated) index; now uses `idx.unique()` for accurate interval counts
- **`seasonal_variation` insight**: flow column selection now prefers columns containing `"import"` before falling back to all non-reserved columns, avoiding accidental inclusion of export or metadata columns

### Changed
- `peak_demand_characteristics` and `step_change_baseload` insight evaluators now delegate time-window filtering and kWh→kW conversion to `transform.aggregate`, removing inline duplication
- `core/utils.py`: consolidated time-parsing, window-filtering, and kW-conversion helpers
- Docstrings condensed throughout for brevity; ruff formatting applied across the codebase

### Tests
- Added `tests/test_insights.py` with evaluator unit tests across basic, intermediate, and advanced insights
- Expanded `tests/test_scenarios.py` with 700+ lines of regression tests covering EV wrap-around windows, battery net-metering, and multi-flow edge cases
- Expanded `tests/test_summary.py`, `tests/test_pricing.py`, and `tests/test_transform.py`

## [0.3.0] - 2026-02-07

### Added
- **Seasonal aggregation**: `summarise()` now returns a `seasonal` breakdown in its output
- `transform.aggregate` supports `groupby="season"` with a `hemisphere` parameter (`"southern"` / `"northern"`) for season-aware grouping

## [0.2.1] - 2026-02-07

### Changed
- Public API in `__init__.py` streamlined for backwards compatibility — top-level imports re-exported to match pre-refactor usage patterns
- Updated README and `docs/api-reference.md` with revised usage examples

### Fixed
- Tests updated to use the new domain-structured imports

## [0.2.0] - 2026-02-07

### Changed
- **Major refactor**: flat module structure reorganised into domain packages — `analytics/` (insights, pricing, scenario, summary), `core/` (transform, utils, types), `io/` (ingest, validate, formats)
- Shared types split into `analytics/types.py`, `core/types.py`, and `io/types.py`
- Added `py.typed` marker for PEP 561 type-checking support
- Added type annotations for `LogicalDay` and `LogicalSeries`

## [0.3.0] - 2026-02-07

### Added
- Seasonal aggregation support in `summarise()` — results now include a `seasonal` breakdown (Summer/Autumn/Winter/Spring) in addition to monthly and daily profiles
- `transform.aggregate()` extended to support `groupby="season"` with hemisphere-aware season mapping
- `analytics/types.py` updated with seasonal summary types

## [0.2.1] - 2026-02-07

### Changed
- Updated public API in `__init__.py` for backwards compatibility after the v0.2.0 domain restructure
- Updated README and `docs/api-reference.md` with corrected import paths and usage examples

## [0.2.0] - 2026-02-07

### Added
- `py.typed` marker — package now ships type information for downstream type checkers
- Type annotations for `LogicalDay` and `LogicalSeries` in `core/types.py`
- New `analytics/types.py` with return-type models for summary, pricing, and scenario outputs
- New `io/types.py` with ingestion and validation types

### Changed
- **Breaking**: restructured from flat layout to domain packages — `analytics/` (insights, pricing, scenario, summary), `core/` (transform, utils, types), `io/` (ingest, validate, formats). Update imports accordingly.
- `meterdatalogic/types.py` consolidated; domain-specific types moved to their respective packages

## [0.1.7] - 2026-02-06

### Added
- `compute_billables()` now accepts optional parameters `include_controlled_load` and `include_total_import`
- When `include_controlled_load=True`, adds `controlled_load_kwh` column with controlled load import totals
- When `include_total_import=True`, adds `total_import_kwh` column with all import flows summed
- Both parameters work in both `monthly` and `cycles` modes
- Added comprehensive test coverage for new optional flow parameters
- Change from dataclasses to pydantic

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
