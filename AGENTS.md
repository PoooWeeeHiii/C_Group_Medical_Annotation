# AGENTS.md

## Cursor Cloud specific instructions

### Project state (important)
This repo (`label_platform` / C 组医学影像标注与数据管理平台) is currently at the **design/contract stage**. `backend/`, `frontend/`, `ai/`, `database/` contain only `.gitkeep` placeholders — there is **no runnable application, no tests, and no frontend tooling yet**. The design contracts live in `docs/` (data flow, DB ER, API contract, UI prototype). See `README.md`.

### Python environment
- Dependencies are Python only, listed in `requirements.txt` (FastAPI/Uvicorn backend + medical-imaging/AI stack: numpy, pydicom, SimpleITK, opencv-python, pillow, torch, torchvision, monai, scikit-learn).
- Dev setup uses a virtualenv at `.venv` (gitignored). The startup update script recreates it and installs `requirements.txt`.
- Use the venv Python directly, e.g. `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/uvicorn`, or `source .venv/bin/activate`.
- `torch` installs the CPU build here (`torch.cuda.is_available()` is `False`); no GPU is present.
- Installing `python3-venv` is a system dependency handled once during environment setup (not in the update script).

### Running / testing (once code exists)
- Backend (intended): FastAPI served with `uvicorn backend.main:app --reload` on port 8000 (conventional; API prefix is `/api` per `docs/04_api_design.md`). No entrypoint exists yet.
- Tests: `pytest` (`.venv/bin/python -m pytest`). There are currently no tests, so pytest exits with code 5 ("no tests ran") — that is expected, not a failure.
- Frontend: a Vue app is planned but no `package.json`/Node tooling exists yet.
