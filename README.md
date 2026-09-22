# Pips Master Academy — rebuild

This build contains a frontend and FastAPI backend. Set the backend environment variables in Render before deployment. Do not commit real passwords or secret keys.

Backend start command:
`uvicorn backend.app:app --host 0.0.0.0 --port $PORT`

Backend build command from repository root:
`pip install -r backend/requirements.txt`

Frontend can be deployed from the `frontend` directory to Vercel/Netlify/Cloudflare Pages.
