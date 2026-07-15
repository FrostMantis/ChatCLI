# Followups

Non-urgent items noted during development, to revisit later.

## Scheduled cleanup of stale rows
Unverified accounts, and expired/revoked session/refresh/email/reset tokens, are
never purged. Consequences today:

- An abandoned unverified account permanently reserves its username (registration
  no longer overwrites an existing unverified user, by design).
- Dead token rows accumulate.

Deferred on purpose: at current scale this costs nothing, and a cleanup job means
either a background thread or an external scheduled task — complexity not worth it
yet. Revisit if the user base or table sizes grow. A single periodic job could
handle all of the above (delete unverified users older than ~24h; delete tokens
past `expires_at` or with `revoked = TRUE`).

## Message edit — participant re-check
`websockets/services.py post_msg` (edit path) verifies message ownership and that
the message belongs to the claimed chat, but not that the editor is still a
participant of that chat. Low severity (you can only edit your own messages).
Consider adding a participant check for consistency with the new-message path.
