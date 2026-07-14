# Backend

The backend is the `backend` Python package. Run commands from the project root.

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

Run its test suite from the project root:

```powershell
python -m pytest backend -v
```

The API listens on `http://localhost:8000` by default. `GEMINI_API_KEY` is optional; all deterministic scoring remains available without it.
