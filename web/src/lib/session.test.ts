import { beforeEach, describe, expect, it } from 'vitest';
import { loadSession, saveSession } from './session';

describe('session storage', () => {
  beforeEach(() => window.localStorage.clear());

  it('keeps only a token and the open circle, and reads it back', () => {
    saveSession({ circle: 'c-1', person: 'asha', keys: { me: 'cs_abc' }, as: 'me', account: { provider: 'local' } });
    const raw = window.localStorage.getItem('cc-session-v3') ?? '';
    expect(raw).toContain('cs_abc');
    expect(raw).not.toMatch(/metformin|password|email/i);          // no record data, no password, no address
    expect(loadSession()?.keys.me).toBe('cs_abc');
  });

  it('forgets everything on sign-out and ignores damaged or empty values', () => {
    saveSession({ circle: 'c-1', person: 'asha', keys: { me: 'cs_abc' }, as: 'me' });
    saveSession(null);
    expect(loadSession()).toBeNull();
    window.localStorage.setItem('cc-session-v3', '{not json');
    expect(loadSession()).toBeNull();
    window.localStorage.setItem('cc-session-v3', JSON.stringify({ circle: 'x', keys: {} }));
    expect(loadSession()).toBeNull();
  });

  it('drops the previous version of the stored session', () => {
    window.localStorage.setItem('cc-session-v2', '{"old":true}');
    saveSession({ circle: '', person: '', keys: { me: 'cs_x' }, as: 'me' });
    expect(window.localStorage.getItem('cc-session-v2')).toBeNull();
  });
});
