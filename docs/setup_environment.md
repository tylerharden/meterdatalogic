# Setting up and Developing the `meterdatalogic` Package

This guide explains how to **set up, install, and develop** the `meterdatalogic` package locally in VS Code or any IDE using a virtual environment and pytest.

---

## 1. Project Structure

Make sure your folder structure looks like this:

```
repo-root/
├── meterdatalogic/
│   ├── meterdatalogic/      ← package code
│   │   ├── __init__.py
│   │   ├── canon.py
│   │   ├── ingest.py
│   │   ├── validate.py
│   │   ├── transform.py
│   │   ├── summary.py
│   │   ├── pricing.py
│   │   └── ...
│   ├── tests/               ← pytest tests
│   ├── pyproject.toml       ← package configuration
│   └── README.md
(optional)
└── .venv/                   ← virtual environment (after creation)
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

# Option A: Install just the library (from repo root)
pip install -e ./meterdatalogic[dev]

# Option B: Work inside the library folder
cd meterdatalogic
pip install -e .[dev]
```

### What this does
- `-e .` → installs your package in *editable mode* (creates a live link to your folder)
- `[dev]` → installs test tools (pytest, ruff, etc.)
- `nemreader` is included for NEM12 ingest.

---

## 4. Verify Installation

Run a quick import check inside your virtual environment:

```bash
python -c "import meterdatalogic, os; print('meterdatalogic loaded from:', os.path.dirname(meterdatalogic.__file__))"
```

If you see a path inside `.venv/lib/...`, it’s still fine — it just means the editable link is registered correctly.

---

## 5. Run Tests with Pytest

From the library folder (`meterdatalogic/`) or repo root if installed with Option A:

```bash
pytest -q
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
   - Choose **pytest** and select the `meterdatalogic/tests/` folder

3. **(Optional)** Add VS Code settings file:

   `.vscode/settings.json`
   ```json
   {
     "python.testing.pytestEnabled": true,
     "python.testing.unittestEnabled": false,
   "python.testing.pytestArgs": ["meterdatalogic/tests"],
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
| Install package | `pip install -e ./meterdatalogic[dev]` | Editable dev install |
| Run tests | `pytest -v` | Validate code changes |
| Lint/format | `ruff check .` / `black .` | Keep code consistent |
| Try in REPL | `python` → `import meterdatalogic as ml` | Test functions interactively |

---

## 8. Typical Troubleshooting

| Problem | Likely Cause | Fix |
|----------|--------------|-----|
| `ModuleNotFoundError: No module named 'meterdatalogic'` | Not installed in venv | Run `pip install -e ./meterdatalogic` |
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
   meterdatalogic-<ver>-py3-none-any.whl
   meterdatalogic-<ver>.tar.gz
```

Can then upload to an internal PyPI or use it in other projects.

---
