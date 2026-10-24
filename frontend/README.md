# SecureEV React Dashboard

## Run locally

From the `frontend` directory:

```powershell
npm install
npm run dev
```

The dashboard expects FastAPI at `http://127.0.0.1:8000`.

Override the API location with:

```powershell
$env:VITE_API_URL = 'http://127.0.0.1:8000'
```

The dashboard uses the `/ws/live` WebSocket for live state and `/camera/mjpeg` for the CARLA RGB camera feed.
