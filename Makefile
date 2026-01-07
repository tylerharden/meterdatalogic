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
	rm -rf dist build *.egg-info .ruff_cache .pytest_cache
