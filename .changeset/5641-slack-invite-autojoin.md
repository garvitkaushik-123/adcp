---
---

fix(slack): auto-join public channels when inviting users (#5641)

When the bot was asked to invite users to a channel it wasn't a member
of, Slack returned `not_in_channel` and the invite failed — the bot only
logged a warning and filed an escalation, so the users were never added.

`inviteToChannel` now recovers from `not_in_channel` by self-joining the
channel (via `conversations.join`) and retrying the invite. This works
for public channels, which is the common case. Private channels can't be
self-joined — Slack requires an existing member to add the bot — so they
still fall through to the existing operational escalation. Any join or
retry failure (missing `channels:join` scope, archived channel) also
falls back to escalation rather than masking the problem.
