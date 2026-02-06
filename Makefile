# Install dependencies (uv automatically manages .venv)
install:
	uv sync --all-extras

# Alternative: Install in development mode with pip
install-pip:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

# Run with uv (no activation needed!)
run:
	uv run pytest -q

# Run unit tests (uv handles the environment automatically)
test:
	uv run pytest -q

# Lint & formatting check
lint:
	uv run ruff check .

# Auto-fix linting issues
lint-fix:
	uv run ruff check --fix .

# Build package distribution (wheel + sdist)
build:
	uv run python -m build

# Clean build artifacts
clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.py[co]' -delete
	rm -rf dist build *.egg-info .ruff_cache .pytest_cache .mypy_cache
	rm -rf htmlcov .coverage .coverage.* coverage.xml

# Version bumping (creates commit + tag)
bump-patch:
	./scripts/bump_version.sh patch

bump-minor:
	./scripts/bump_version.sh minor

bump-major:
	./scripts/bump_version.sh major

# Build and publish to PyPI (requires PyPI token)
publish: clean build
	@echo "Publishing to PyPI..."
	uv run twine upload dist/*

# Install this package into parent FastAPI project (editable mode)
install-parent:
	@echo "Installing meterdatalogic into parent project in editable mode..."
	cd .. && uv pip install -e ./meterdatalogic

# Build and install wheel into parent project (non-editable)
install-parent-wheel: build
	@echo "Installing meterdatalogic wheel into parent project..."
	cd .. && uv pip install --force-reinstall ./meterdatalogic/dist/*.whl

# Quick test: install locally and run parent project tests
quick-test: install-parent
	@echo "Running parent project tests..."
	cd .. && uv run pytest tests/test_analyzer_integration.py -v

# Help command
help:
	@echo "Meterdatalogic Makefile Commands:"
	@echo ""
	@echo "Development:"
	@echo "  make install              - Install dependencies with uv"
	@echo "  make test                 - Run unit tests"
	@echo "  make lint                 - Check code with ruff"
	@echo "  make lint-fix             - Auto-fix linting issues"
	@echo ""
	@echo "Local Installation (for FastAPI project):"
	@echo "  make install-parent       - Install in editable mode to parent project (recommended)"
	@echo "  make install-parent-wheel - Build wheel and install to parent project"
	@echo "  make quick-test           - Install locally and run parent tests"
	@echo ""
	@echo "Building & Publishing:"
	@echo "  make build                - Build wheel and sdist"
	@echo "  make publish              - Build and publish to PyPI"
	@echo "  make bump-patch/minor/major - Bump version"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean                - Remove build artifacts"

.PHONY: install test lint lint-fix build clean publish install-parent install-parent-wheel quick-test help


# Create GitHub release (requires gh CLI)
release:
	@echo "Creating GitHub release..."
	@VERSION=$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	gh release create v$$VERSION --generate-notes --latest
