# Copilot Instructions for meterdatalogic

## Project Overview

meterdatalogic is a lightweight Python package for meter interval data transformation, validation, and analytics. It provides a canonical data shape (CanonFrame) and a suite of modules for ingesting, validating, transforming, summarizing, pricing, and modeling meter data. The package is designed to be framework-agnostic and optimized for energy data use cases.

## Core Architecture

### Module Structure

The package follows a composable, pipeline-style architecture with these core modules:

- `ingest` — Load raw meter data (NEM12, CSV, JSON)
- `canon` — Normalize to canonical schema (CanonFrame)
- `validate` — Schema validation, tz-awareness, duplicate checks
- `transform` — Aggregation, filtering, time-of-use binning
- `summary` — Daily/monthly rollups, profiles, peaks
- `pricing` — Tariff calculations, demand windows, billables
- `scenario` — Solar/battery modeling, what-if analysis
- `insights` — Advanced pattern detection and evaluators
- `formats` — Conversion between CanonFrame and LogicalCanon (JSON-ready)

### Data Flow

```
Raw Data → ingest → CanonFrame → validate → transform/summary/pricing → Output
```

## Coding Standards

### Type Safety

- **Always use type hints** for function signatures
- Use `CanonFrame` instead of `pd.DataFrame` for canonical data
- Prefer TypedDict classes for structured dictionaries (see `types.py`)
- Import from `__future__ import annotations` for forward references
- Use `Optional[T]` or `T | None` for nullable types

### DataFrame Conventions

- **Index naming**: DatetimeIndex must be named `'t_start'` and be tz-aware
- **Required columns**: `['nmi', 'channel', 'flow', 'kwh', 'cadence_min']`
- **Flow types**: Use the `Flow` literal: `'grid_import' | 'controlled_load_import' | 'grid_export_solar'`
- **Always validate** with `validate.assert_canon(df)` after creating/modifying CanonFrame
- Prefer `.loc` and `.iloc` for DataFrame indexing to avoid chained assignment

### Error Handling

- Use `CanonError` from `exceptions.py` for schema violations
- Use standard Python exceptions for other errors (`ValueError`, `TypeError`, `KeyError`)
- Provide descriptive error messages that guide users to fixes

### Code Style

- **Line length**: 100 characters (enforced by ruff)
- **Linting**: Run `uv run ruff check .` before commits
- **Formatting**: Run `uv run ruff format .` or use pre-commit hooks
- **Testing**: Run `uv run pytest` — all tests must pass
- **Docstrings**: Use concise docstrings with clear parameter descriptions
- **Private functions**: Prefix with `_` and keep internal to modules
- **Pure functions**: Prefer stateless transformations; avoid side effects

### Dependencies

- **Core**: pandas >= 2.0.0, numpy >= 1.24.0
- **NEM12 support**: nemreader >= 0.9.2 (optional extra)
- **No heavy dependencies**: Keep the package lightweight and fast
- Use `uv` for package management (much faster than pip)

## Common Patterns

### Creating a CanonFrame

```python
from meterdatalogic import canon, validate

df = canon.from_nem12("path/to/file.csv")
validate.assert_canon(df)  # Always validate after creation
```

### Aggregation with transform

```python
from meterdatalogic import transform

# Daily aggregation with power calculation
daily = transform.aggregate(
    df,
    freq="1D",
    how="sum",
    add_power=True,
    power_col="kw"
)
```

### Pricing calculations

```python
from meterdatalogic import pricing

billables = pricing.compute_billables(
    df,
    plan={
        "demand_window": "30D",
        "demand_method": "rolling_avg",
        "billing_cycle": "monthly"
    }
)
```

### Converting to JSON-ready format

```python
from meterdatalogic import formats

logical = formats.to_logical(df)
# Returns LogicalCanon dict with timezone-naive ISO strings
```

## Testing Guidelines

- **File location**: All tests in `tests/` directory
- **Naming**: Test files must be named `test_*.py`
- **Coverage**: Aim for comprehensive coverage of edge cases
- **Fixtures**: Use pytest fixtures in `conftest.py` for shared data
- **Assertions**: Use descriptive assertion messages
- **Test data**: Store sample files in `examples/data/`

### Test Structure

```python
def test_feature_with_valid_input():
    """Test description with expected behavior."""
    # Arrange
    df = create_test_canon_frame()
    
    # Act
    result = module.function(df)
    
    # Assert
    assert result is not None
    assert len(result) > 0
```

## Pre-commit Hooks

The project uses pre-commit hooks for code quality:

- **ruff**: Linting (checks for unused variables, imports, etc.)
- **ruff-format**: Code formatting

Run manually: `uv run pre-commit run --all-files`

## Development Workflow

1. **Setup**: `make install` or `uv sync --all-extras`
2. **Make changes**: Edit code with type safety in mind
3. **Test**: `make test` or `uv run pytest`
4. **Lint**: `make lint` or `uv run ruff check .`
5. **Format**: `uv run ruff format .`
6. **Pre-commit**: `uv run pre-commit run --all-files`

## Important Notes

- **Timezone awareness**: All timestamps must be tz-aware (use `.tz_localize()` or `.tz_convert()`)
- **No mutation**: Return new DataFrames; avoid in-place modifications
- **Performance**: Vectorize operations; avoid loops over DataFrame rows
- **Documentation**: Keep README.md and docstrings up to date
- **Breaking changes**: Follow semantic versioning (current: 0.1.4)

## File Naming Conventions

- **Modules**: Snake case (e.g., `transform.py`, `time_of_use.py`)
- **Classes**: PascalCase (e.g., `CanonFrame`, `LogicalDay`)
- **Functions**: Snake case (e.g., `compute_billables`, `period_breakdown`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `DEFAULT_TZ`, `MAX_CADENCE`)

## When Adding New Features

1. **Check existing patterns**: Review similar functions in the module
2. **Add types**: Include full type annotations
3. **Validate inputs**: Raise appropriate exceptions with clear messages
4. **Write tests**: Create corresponding test cases
5. **Update docs**: Add docstrings and update README if public API
6. **Run full suite**: `make test && make lint`

## Insights Module

The `insights/` submodule provides advanced pattern detection:

- **evaluators_basic.py**: Simple threshold-based evaluators
- **evaluators_intermediate.py**: Time-of-use and statistical patterns
- **evaluators_advanced.py**: Complex multi-condition evaluators
- **engine.py**: Evaluation orchestration
- **config.py**: Default evaluator configurations

When adding evaluators:
- Return boolean or confidence score (0-1)
- Include clear `description` and `category` in config
- Handle missing/incomplete data gracefully