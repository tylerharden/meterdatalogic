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

# Create GitHub release (requires gh CLI)
release:
	@echo "Creating GitHub release..."
	@VERSION=$$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/'); \
	gh release create v$$VERSION --generate-notes --latest
