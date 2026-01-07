# Create virtual env and install package + dev tools (using uv - fast!)
venv:
	uv venv
	uv pip install -e ".[dev]"

# Alternative: Create venv with standard pip
venv-pip:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

# Sync dependencies from pyproject.toml (uv)
sync:
	uv pip sync pyproject.toml

# Run unit tests
test:
	pytest -q

# Lint & formatting check
lint:
	ruff check .

# Auto-fix linting issues
lint-fix:
	ruff check --fix .

# Build package distribution (wheel + sdist)
build:
	python3 -m build

# Clean build artifacts
clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.py[co]' -delete
	rm -rf dist build *.egg-info .ruff_cache .pytest_cache
