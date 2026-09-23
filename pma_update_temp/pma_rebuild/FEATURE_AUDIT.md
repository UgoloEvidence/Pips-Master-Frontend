# Pips Master Academy — Rebuild Audit

Build target: complete member/admin rebuild based on the current PMA build plus the latest community/private-messaging requirements.

## Community messaging
- Permanent community messages are the default.
- Admin can enable **Temporary Message Mode**.
- Temporary mode is fixed to **24 hours**.
- Each temporary message stores an expiry timestamp.
- Members can see a visible `time left` countdown on temporary messages.
- The community banner tells members whether messages are permanent or temporary.
- Temporary messages are removed after their own expiry; permanent messages are not auto-deleted.
- Members can react with emoji.
- Message view counts are recorded.
- Members can edit/delete their own messages; deletion leaves a deleted-message marker.
- Admin can edit/delete community messages; admin deletion is visibly marked.
- Community lock remains: members can read/react but cannot post while locked.
- Admin controls include member moderation and temporary-mode toggle.

## Member-to-member private messaging
- Members can open another member's profile from the Community member strip or Messages directory.
- A normal member must send a message request before a private conversation can start.
- The recipient must accept the request.
- A normal member cannot request, start, or send a private message to the administrator.
- The administrator can start a private conversation with any member without a request.
- Accepted conversations are stored in the backend and survive page reloads.
- Message Requests has incoming accept/decline controls and outgoing pending status.
- Private conversation history is stored server-side.

## Account/admin
- Admin email is configured as `ugoloevidence81@gmail.com`.
- The rebuild's one-time admin credential migration sets the configured admin password to the build credential and then preserves later password changes.
- Admin can manage community lock, moderation, temporary messages and private conversations.

## Existing PMA features preserved
- Scanner/day-trade redesign and no-late-entry architecture.
- Locked Entry/SL/TP after confirmation.
- Multi-timeframe context and personal scanner settings.
- Trading history and scanner history.
- Notifications and 14-day notification cleanup.
- My Progress backend integration.
- Referral leaderboard without a referral target.
- Feedback/XP flow.
- Profile editing and referral-code copy control.
- Offline access gate.
- Mature dark/light visual system and directional trade colors.

## Inspection performed
- Python syntax compilation: PASS (`backend/app.py`, `backend/market_data.py`).
- JavaScript syntax check: PASS (`frontend/app.js`, `app.js`, `frontend_embedded.js`).
- Archive contents reviewed after packaging.
- Feature strings/endpoints reviewed for temporary messaging, 24-hour expiry, request/accept flow, admin bypass, and admin-only restrictions.

## Deployment note
This archive is source/deployment-ready but has not been deployed from this environment to the user's Render/Vercel accounts. Render SQLite is still subject to its filesystem persistence limitations; durable long-term community/private-message history should use persistent storage/PostgreSQL in production.
