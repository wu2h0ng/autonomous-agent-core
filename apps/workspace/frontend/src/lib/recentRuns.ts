export const RECENT_RUNS_STORAGE_KEY = 'data-agent-recent-runs';

export type RecentRun = {
  traceId: string;
  question: string;
  timestamp: number;
};

const EMPTY_RUNS: RecentRun[] = [];

let cachedRaw: string | null | undefined;
let cachedSnapshot: RecentRun[] = EMPTY_RUNS;

function parseRecentRuns(raw: string | null): RecentRun[] {
  if (!raw) return EMPTY_RUNS;
  try {
    const parsed = JSON.parse(raw) as RecentRun[];
    return Array.isArray(parsed) ? parsed : EMPTY_RUNS;
  } catch {
    return EMPTY_RUNS;
  }
}

function invalidateRecentRunsSnapshot(): void {
  cachedRaw = undefined;
}

export function getRecentRunsSnapshot(): RecentRun[] {
  if (typeof window === 'undefined') return EMPTY_RUNS;
  const raw = window.localStorage.getItem(RECENT_RUNS_STORAGE_KEY);
  if (raw === cachedRaw) return cachedSnapshot;
  cachedRaw = raw;
  cachedSnapshot = parseRecentRuns(raw);
  return cachedSnapshot;
}

export function loadRecentRuns(): RecentRun[] {
  return getRecentRunsSnapshot();
}

export function addRecentRun(traceId: string, question: string) {
  if (typeof window === 'undefined') return;
  const runs = getRecentRunsSnapshot();
  const next = [
    { traceId, question, timestamp: Date.now() },
    ...runs.filter((r) => r.traceId !== traceId),
  ].slice(0, 50);
  window.localStorage.setItem(RECENT_RUNS_STORAGE_KEY, JSON.stringify(next));
  invalidateRecentRunsSnapshot();
  window.dispatchEvent(new StorageEvent('storage'));
}

export function clearRecentRuns() {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(RECENT_RUNS_STORAGE_KEY);
  invalidateRecentRunsSnapshot();
  window.dispatchEvent(new StorageEvent('storage'));
}

export function subscribeRecentRuns(callback: () => void) {
  const handler = () => {
    invalidateRecentRunsSnapshot();
    callback();
  };
  window.addEventListener('storage', handler);
  return () => window.removeEventListener('storage', handler);
}
