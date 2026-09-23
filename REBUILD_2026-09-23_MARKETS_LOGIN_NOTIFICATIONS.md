# PMA rebuild — 2026-09-23

Targeted fixes in this build:
- Non-Forex TradingView symbols now use canonical provider aliases for Indices, Metals and Commodities.
- TradingView chart widget symbol mapping updated for Indices, Metals and Commodities so timeframe charts are not blank because of invalid friendly symbols.
- Login/profile requests have a longer timeout and login retries; reload authentication keeps a token through transient network/server failures and only discards it on an actual 401/403.
- Notification history deletion reports the actual deleted row count and confirms the server has zero remaining notifications for that user.
- Existing community admin-only voice-note workflow is retained; an unsent recording remains client-side only and is discarded on reload without being posted.
- Existing Forex path and login credential flow were not intentionally redesigned.
