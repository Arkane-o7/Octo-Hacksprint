# New-member join onboarding

## Cause

The deployed bridge forwarded only `message`, while the app's normalizer ignored
all group events. The numbered menu opened on a greeting or `menu`, so joining a
group alone could not start onboarding.

## Fix

- Compose subscribes to `message,group.v2.participants` with the existing HMAC key.
- The signed webhook routes only participant `type: join` events to a dedicated
  durable queue. It does not turn system events into user messages or facts.
- Before welcoming someone, the worker fetches current configured-group members,
  resolves verified phone/LID aliases and checks their role and current scope.
- Eligible new members get one private welcome followed by the main numbered menu
  in the same message. They can select an option immediately. Existing English,
  Hindi and Tamil menu copy is used; a new unconfigured member keeps the current
  roster fallback language. The welcome contains no private school facts.
- The bot and configured teachers are excluded from parent onboarding. Promotions,
  leaves, join requests, the bot's own group-join event, unrelated groups/sessions,
  events older than 24 hours and events over five minutes ahead are ignored.
- Phone/LID events and webhook retries converge on one welcome per member/group.
  The outbox, current scope and menu state are committed atomically. Delivery
  rechecks authorization. Uncertain sends are never automatically repeated.
- Membership lookup failures or API lag receive at most five bounded checks.
  Failure produces no message. People with an existing private menu are not
  interrupted by a delayed join notification.
- There is no startup roster broadcast or historical-member backfill. A member
  who joined before the fix can open the same flow by sending `menu` in a DM.

## Checks

25 dedicated offline checks exercise signed webhooks, current membership, active
numbered choices, encrypted restart recovery, departed members, lookup failures,
alias duplicates, unrelated/stale/self events, uncertain delivery, transactional
rollback and preserving an existing conversation. Full offline suite: 391 tests.
No test sends a message to a real recipient or adds/removes group members.

After deploying, `/health` reports `join_onboarding_enabled: true`. Recreate the
WAHA container from the updated Compose manifest to load the new global event
subscription; retain the existing session and media volumes. Do not re-pair or
reset the session. Handset acceptance remains a genuine new member joining the
configured group and receiving the private welcome once.

Official contracts:
- [WAHA participant events](https://waha.devlike.pro/docs/how-to/events/#groupv2participants)
- [WAHA webhook configuration](https://waha.devlike.pro/docs/how-to/events/#global-webhooks)
