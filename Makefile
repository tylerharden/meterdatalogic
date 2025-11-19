# Create virtual env and install package + dev tools
venv:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

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
