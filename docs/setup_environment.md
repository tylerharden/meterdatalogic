# Setting up and Developing the `meterdatalogic` Package

This guide explains how to **set up, install, and develop** the `meterdatalogic` package locally in VS Code or any IDE using a virtual environment and pytest.

---

## 1. Project Structure

Make sure your folder structure looks like this:

```
meterdatalogic/
│
├── meterlogic/              ← your package code
│   ├── __init__.py
│   ├── canon.py
│   ├── ingest.py
│   ├── validate.py
│   ├── transform.py
│   ├── summary.py
│   ├── pricing.py
│   └── ...
│
├── tests/                   ← pytest tests
│   ├── test_ingest.py
│   ├── test_validate.py
│   ├── test_transform.py
│   ├── test_summary.py
│   └── ...
│
├── pyproject.toml           ← package configuration
├── README.md
└── .venv/                   ← your virtual environment (after creation)
```

---

## 2. Create a Virtual Environment

Create an isolated Python environment to keep dependencies clean.

```bash
# Create venv in the project root
python -m venv .venv

# Activate the environment
# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\activate
```

You should now see `(.venv)` at the start of your terminal prompt.

---

## 3. Install Dependencies and Your Package

Install the package **in editable mode** (`-e`) so that changes to your code take effect immediately.

```bash
# Upgrade pip first
pip install --upgrade pip

# Install your package + optional extras + test tools
pip install -e .[nem12] pytest
```

### What this does
- `-e .` → installs your package in *editable mode* (creates a live link to your folder)
- `[nem12]` → installs optional dependencies (e.g. `nemreader`)
- `pytest` → installs the testing framework

---

## 4. Verify Installation

Run a quick import check inside your virtual environment:

```bash
python -c "import meterlogic, os; print('meterlogic loaded from:', os.path.dirname(meterlogic.__file__))"
```

You should see something like:
```
meterlogic loaded from: /Users/tyler/Developer/meterdatalogic/meterlogic
```

If you see a path inside `.venv/lib/...`, it’s still fine — it just means the editable link is registered correctly.

---

## 5. Run Tests with Pytest

From the project root (the same directory that contains `tests/`):

```bash
pytest -v
```

Example output:
```
collected 20 items
tests/test_ingest.py .........
tests/test_transform.py ......
tests/test_summary.py .....
================= 20 passed in 3.21s =================
```

You can also run a single file:
```bash
pytest tests/test_ingest.py -v
```

---

## 6. Running in VS Code

1. **Select Interpreter**  
   - Command Palette → “Python: Select Interpreter” → choose `.venv`

2. **Configure Tests**  
   - Command Palette → “Python: Configure Tests”  
   - Choose **pytest** and select the `tests/` folder

3. **(Optional)** Add VS Code settings file:

   `.vscode/settings.json`
   ```json
   {
     "python.testing.pytestEnabled": true,
     "python.testing.unittestEnabled": false,
     "python.testing.pytestArgs": ["tests"],
     "python.envFile": "${workspaceFolder}/.env"
   }
   ```

VS Code will automatically detect tests and let you run them individually.

---

## 7. Developer Workflow

Typical loop while building the package:

| Step | Command | Purpose |
|------|----------|----------|
| Activate environment | `source .venv/bin/activate` | Use your project Python env |
| Install package | `pip install -e .[nem12]` | Editable dev install |
| Run tests | `pytest -v` | Validate code changes |
| Lint/format | `ruff check .` / `black .` | Keep code consistent |
| Try in REPL | `python` → `import meterlogic as ml` | Test functions interactively |

---

## 8. Typical Troubleshooting

| Problem | Likely Cause | Fix |
|----------|--------------|-----|
| `ModuleNotFoundError: No module named 'meterlogic'` | Not installed in venv | Run `pip install -e .` |
| Tests not discovered | Wrong test folder | Run `pytest -v` from repo root |
| VS Code shows red squiggles | Wrong interpreter | Re-select `.venv` via Command Palette |
| Pandas version mismatch | Outdated dependency | `pip install -U pandas` |

---

## 9. Build & Distribute

To deploy:

```bash
pip install build
python -m build
```

Creates:
```
dist/
  meterlogic-0.1.0-py3-none-any.whl
  meterlogic-0.1.0.tar.gz
```

Can then upload to an internal PyPI or use it in other projects.

---
