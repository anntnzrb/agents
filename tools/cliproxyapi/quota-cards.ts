/**
 * Quota cards for the generic `custom` provider.
 *
 * This file is copied into the panel at build time
 * (`src/utils/quota/custom/cards.ts`) by `tools/cliproxyapi/panel.rebuild.sh`.
 * Adding a provider = adding one object to QUOTA_CARDS; no panel source edits.
 *
 * Each card declares:
 *   - `matches(file)`      → auth-file rows it serves (checked in order)
 *   - `matchesBaseUrl(url)` → optional; lets the panel synthesize rows for
 *                             API-key compatibility providers (auth_index
 *                             + baseUrl) that /auth-files does not list
 *   - `request(file)`      → upstream call via the gateway api-call proxy;
 *                             `$TOKEN$` is replaced with the selected credential
 *   - `parse(payload)`     → [{ id, label, remainingPercent, resetAtMs }]
 */

import type { AuthFileItem, CustomQuotaWindow } from '@/types';
import { parseIsoToMs } from '@/utils/quota/resetInstants';
import type { QuotaCard } from './types';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === 'object' && !Array.isArray(value);

const readString = (value: unknown): string =>
  typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim();

const clampPercent = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(0, Math.min(100, value));
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.max(0, Math.min(100, parsed));
  }
  return null;
};

const remainingFromUsed = (usedPercent: number | null): number | null =>
  usedPercent === null ? null : Math.max(0, Math.min(100, 100 - usedPercent));

const parseUnixSecondsToMs = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.floor(value * 1000);
  }
  if (typeof value === 'string' && /^\d+$/.test(value.trim())) {
    const sec = Number(value.trim());
    if (Number.isSafeInteger(sec) && sec > 0) {
      return sec * 1000;
    }
  }
  return null;
};

const parseProtoPercent = (value: unknown, resetAtMs: number | null): number | null => {
  const clamped = clampPercent(value);
  if (clamped !== null) return clamped;
  // Proto3 JSON omits zero-valued numeric fields. If reset timestamp is present, treat missing percent as 0%.
  if (resetAtMs !== null) return 0;
  return null;
};

const readBaseUrl = (file: AuthFileItem): string => {
  const record = file as unknown as Record<string, unknown>;
  for (const candidate of [record.baseUrl, record['base-url'], record.base_url, record.BaseURL]) {
    const value = readString(candidate);
    if (value) return value;
  }
  return '';
};

const matchesBaseUrl = (value: string, host: string, path: string): boolean => {
  if (!value) return false;
  try {
    const parsed = new URL(value.includes('://') ? value : `https://${value}`);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false;
    if (parsed.hostname.toLowerCase() !== host) return false;
    return (parsed.pathname.replace(/\/+$/, '') || '') === path;
  } catch {
    return false;
  }
};

/** OpenCode Go: `https://opencode.ai/zen/go` (OpenAI-compatible subscription). */
const openCodeGoCard: QuotaCard = {
  id: 'opencode-go',
  title: 'OpenCode Go',
  matchesBaseUrl: (baseUrl) => matchesBaseUrl(baseUrl, 'opencode.ai', '/zen/go'),
  matches: (file) => matchesBaseUrl(readBaseUrl(file), 'opencode.ai', '/zen/go'),
  request: () => ({
    method: 'GET',
    url: 'https://opencode.ai/zen/go/v1/usage',
    header: { Authorization: 'Bearer $TOKEN$', Accept: 'application/json' },
  }),
  parse: (payload) => {
    if (!isRecord(payload)) return null;
    const nested = isRecord(payload.usage) ? payload.usage : null;
    const window = (key: string, snake: string, short: string) => {
      const raw =
        payload[key] ?? payload[snake] ?? nested?.[key] ?? nested?.[snake] ?? nested?.[short];
      if (!isRecord(raw)) return { usedPercent: null, resetLabel: '', resetAtMs: null };
      const resetsAt = readString(raw.resetsAt ?? raw.resets_at);
      return {
        usedPercent: clampPercent(raw.percent),
        resetLabel: resetsAt,
        resetAtMs: parseIsoToMs(resetsAt),
      };
    };
    const specs = [
      { id: '5h', label: '5 Hour', ...window('rollingUsage', 'rolling_usage', 'rolling') },
      { id: 'weekly', label: 'Weekly', ...window('weeklyUsage', 'weekly_usage', 'weekly') },
      { id: 'monthly', label: 'Monthly', ...window('monthlyUsage', 'monthly_usage', 'monthly') },
    ];
    const windows: CustomQuotaWindow[] = specs.map((spec) => ({
      id: spec.id,
      label: spec.label,
      remainingPercent: remainingFromUsed(spec.usedPercent),
      resetLabel: spec.resetLabel,
      resetAtMs: spec.resetAtMs,
    }));
    return windows;
  },
};

/** ClinePass: `https://api.cline.bot/api/v1` (OpenAI-compatible subscription). */
const clinePassCard: QuotaCard = {
  id: 'cline-pass',
  title: 'ClinePass',
  matchesBaseUrl: (baseUrl) => matchesBaseUrl(baseUrl, 'api.cline.bot', '/api/v1'),
  matches: (file) => matchesBaseUrl(readBaseUrl(file), 'api.cline.bot', '/api/v1'),
  request: () => ({
    method: 'GET',
    url: 'https://api.cline.bot/api/v1/users/me/plan/usage-limits',
    header: { Authorization: 'Bearer $TOKEN$', Accept: 'application/json' },
  }),
  parse: (payload) => {
    if (!isRecord(payload)) return null;
    const data = isRecord(payload.data) ? payload.data : null;
    if (!data || !Array.isArray(data.limits)) return null;
    const byType = new Map<string, Record<string, unknown>>();
    for (const entry of data.limits) {
      if (isRecord(entry)) byType.set(readString(entry.type), entry);
    }
    const specs = [
      { id: '5h', label: '5 Hour', type: 'five_hour' },
      { id: 'weekly', label: 'Weekly', type: 'weekly' },
      { id: 'monthly', label: 'Monthly', type: 'monthly' },
    ];
    const windows: CustomQuotaWindow[] = specs.map((spec) => {
      const limit = byType.get(spec.type);
      const usedPercent = clampPercent(limit?.percentUsed ?? limit?.percent_used);
      const resetsAt = readString(limit?.resetsAt ?? limit?.resets_at);
      return {
        id: spec.id,
        label: spec.label,
        remainingPercent: remainingFromUsed(usedPercent),
        resetLabel: resetsAt,
        resetAtMs: parseIsoToMs(resetsAt),
      };
    });
    return windows;
  },
};

/** Devin: `https://server.codeium.com` (Cognition Devin Pro quota via Codeium SeatManagementService). */
const devinCard: QuotaCard = {
  id: 'devin',
  title: 'Devin',
  matches: (file) => {
    const provider = String(file.provider ?? file.type ?? '')
      .trim()
      .toLowerCase()
      .replace(/_/g, '-');
    return provider === 'devin';
  },
  request: () => ({
    method: 'POST',
    url: 'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetUserStatus',
    header: {
      Authorization: 'Basic $TOKEN$-$TOKEN$',
      'Connect-Protocol-Version': '1',
      'Content-Type': 'application/json',
    },
    data: JSON.stringify({
      metadata: {
        ideName: 'chisel',
        ideVersion: '3000.10.21',
        apiKey: '$TOKEN$',
        locale: 'en',
        os: 'linux',
        extensionVersion: '3000.10.21',
        extensionName: 'chisel',
      },
    }),
  }),
  parse: (payload) => {
    let obj = payload;
    if (typeof obj === 'string') {
      try {
        obj = JSON.parse(obj);
      } catch {
        return null;
      }
    }
    if (!isRecord(obj)) return null;
    const userStatus = isRecord(obj.userStatus) ? obj.userStatus : null;
    const planStatus = isRecord(userStatus?.planStatus)
      ? userStatus.planStatus
      : isRecord(obj.planStatus)
        ? obj.planStatus
        : null;
    if (!planStatus) return null;

    const dailyResetAtMs = parseUnixSecondsToMs(planStatus.dailyQuotaResetAtUnix);
    const dailyRemaining = parseProtoPercent(planStatus.dailyQuotaRemainingPercent, dailyResetAtMs);

    const weeklyResetAtMs = parseUnixSecondsToMs(planStatus.weeklyQuotaResetAtUnix);
    const weeklyRemaining = parseProtoPercent(planStatus.weeklyQuotaRemainingPercent, weeklyResetAtMs);

    const windows: CustomQuotaWindow[] = [
      {
        id: 'daily',
        label: 'Daily',
        remainingPercent: dailyRemaining,
        resetAtMs: dailyResetAtMs,
      },
      {
        id: 'weekly',
        label: 'Weekly',
        remainingPercent: weeklyRemaining,
        resetAtMs: weeklyResetAtMs,
      },
    ];
    return windows;
  },
};

export const QUOTA_CARDS: readonly QuotaCard[] = [openCodeGoCard, clinePassCard, devinCard];
