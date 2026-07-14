# Frontend

The frontend is a Vite React app that consumes the separate FastAPI backend.

From this directory:

```powershell
npm install
npm run dev
```

The backend URL defaults to `http://localhost:8000`. To override it:

```powershell
Copy-Item .env.example .env
```

Then edit `VITE_API_BASE_URL` in `.env`.

Validation commands:

```powershell
npm run lint
npm run build
```
