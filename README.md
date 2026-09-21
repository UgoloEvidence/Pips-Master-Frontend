# Pips Master Academy

## Folder structure
- `frontend/` — everything needed for the Netlify frontend.
- `backend/` — FastAPI API, database setup and market-data helpers.

## Netlify
Upload the contents of `frontend/` to Netlify, or connect the repository with the publish directory set to `frontend`.

The frontend supports local persistence for profile data, referral links, notifications and community media when no backend is configured. For multi-device accounts and shared community data, configure `PMA_API_BASE` in the browser/local environment or update the API base in the frontend.

## Backend
Run the FastAPI application from the backend package. The backend now includes profile persistence, community message/media storage and notification endpoints.

Never put backend secrets such as database passwords or market-data API keys in frontend code.
