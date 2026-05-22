# Install dependencies (uv automatically manages .venv)
install:
	uv sync --all-extras
	uv run pre-commit install

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

# Help command
help:
	@echo "Meterdatalogic Makefile Commands:"
	@echo ""
	@echo "Development:"
	@echo "  make install              - Install dependencies and pre-commit hooks"
	@echo "  make test                 - Run unit tests"
	@echo "  make lint                 - Check code with ruff"
	@echo "  make lint-fix             - Auto-fix linting issues"
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
