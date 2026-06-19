import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// The slack client reads ADDIE_BOT_TOKEN / SLACK_BOT_TOKEN at module
// load — set a fake value BEFORE the import resolves (vi.hoisted runs
// before import statements) so slackPostRequest doesn't throw.
vi.hoisted(() => {
  process.env.ADDIE_BOT_TOKEN = 'xoxb-test-fake';
});

import {
  inviteToChannel,
  __resetChannelCacheForTests,
} from '../../src/slack/client.js';

/**
 * #5641 — the bot used to fail to invite users to a channel it wasn't a
 * member of (Slack returns `not_in_channel`) and only escalate. For a
 * *public* channel the bot can self-join, so `inviteToChannel` now
 * recovers by joining and retrying the invite. Private channels can't be
 * self-joined and must still fall through to the {ok:false} escalation
 * path.
 *
 * We stub `globalThis.fetch` so the real slackPostRequest / slackRequest /
 * getChannelInfo all run end-to-end, routing by Slack method. The
 * module-level channel cache is reset per test so `is_private` lookups
 * don't leak between cases.
 */

type FetchCall = { method: string; body: Record<string, unknown> };
const calls: FetchCall[] = [];
// First invite per channel returns not_in_channel; later invites succeed,
// modelling "bot wasn't a member, then joined".
const channelInfo = new Map<string, { is_private: boolean } | null>();
const inviteAttempts = new Map<string, number>();

const originalFetch = globalThis.fetch;

beforeEach(() => {
  calls.length = 0;
  channelInfo.clear();
  inviteAttempts.clear();
  __resetChannelCacheForTests();

  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const urlStr = typeof input === 'string' ? input : input.toString();
    const parsed = new URL(urlStr);
    const json = (payload: unknown) =>
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });

    // conversations.info — GET with query params
    if (parsed.pathname.endsWith('/conversations.info')) {
      const channelId = parsed.searchParams.get('channel') ?? '';
      const info = channelInfo.get(channelId);
      if (!info) {
        return json({ ok: false, error: 'channel_not_found' });
      }
      return json({ ok: true, channel: { id: channelId, ...info } });
    }

    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {};

    if (parsed.pathname.endsWith('/conversations.join')) {
      calls.push({ method: 'conversations.join', body });
      return json({ ok: true, channel: { id: body.channel } });
    }

    if (parsed.pathname.endsWith('/conversations.invite')) {
      calls.push({ method: 'conversations.invite', body });
      const channelId = String(body.channel);
      const n = (inviteAttempts.get(channelId) ?? 0) + 1;
      inviteAttempts.set(channelId, n);
      // First attempt fails as if the bot isn't a member; a retry (after
      // joining) succeeds.
      if (n === 1) {
        return json({ ok: false, error: 'not_in_channel' });
      }
      return json({ ok: true });
    }

    throw new Error(`Unexpected fetch URL: ${urlStr}`);
  }) as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe('inviteToChannel not_in_channel recovery (#5641)', () => {
  it('self-joins a public channel and retries the invite on not_in_channel', async () => {
    channelInfo.set('C_public', { is_private: false });

    const result = await inviteToChannel('C_public', ['U_member']);

    expect(result.ok).toBe(true);
    // Order: invite (fails) → join → invite (succeeds).
    expect(calls.map((c) => c.method)).toEqual([
      'conversations.invite',
      'conversations.join',
      'conversations.invite',
    ]);
  });

  it('does not attempt to self-join a private channel and reports failure', async () => {
    channelInfo.set('C_private', { is_private: true });

    const result = await inviteToChannel('C_private', ['U_member']);

    expect(result.ok).toBe(false);
    expect(result.error).toContain('not_in_channel');
    // Only the original invite was attempted — no join for a private channel.
    expect(calls.some((c) => c.method === 'conversations.join')).toBe(false);
  });

  it('returns ok without any API call when there are no users to invite', async () => {
    const result = await inviteToChannel('C_public', []);
    expect(result.ok).toBe(true);
    expect(calls).toHaveLength(0);
  });
});
