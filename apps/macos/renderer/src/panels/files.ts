// Files panel logic: read-only bounded workspace listing through the
// Wave 2a protocol addition `GET /v1/surface/tasks/{task_id}/files`.
// Path/size/mtime only; no content.

export interface FileEntry {
  path: string;
  size: number;
  mtime: string;
}

export interface FilesFetchLike {
  (path: string, init?: { method?: string; headers?: Record<string, string> }): Promise<{
    ok: boolean;
    status: number;
    text(): Promise<string>;
  }>;
}

export async function fetchFiles(
  baseUrl: string,
  token: string,
  taskId: string,
  fetchImpl: FilesFetchLike,
): Promise<FileEntry[]> {
  const response = await fetchImpl(
    `${baseUrl}/v1/surface/tasks/${encodeURIComponent(taskId)}/files`,
    {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Agent-OS-Protocol": "1.1",
      },
    },
  );
  if (!response.ok) {
    throw new Error(`files listing failed: HTTP ${response.status}`);
  }
  const body = JSON.parse(await response.text()) as { files: FileEntry[] };
  for (const entry of body.files) {
    if (
      typeof entry.path !== "string" ||
      typeof entry.size !== "number" ||
      typeof entry.mtime !== "string"
    ) {
      throw new Error("files listing returned an invalid entry");
    }
  }
  return body.files;
}

export interface ConflictBadge {
  disposition: "REPLAN" | "CONFLICT" | "CANCEL";
  suggestedAction: "REPLAN" | "REVIEW_DIFF" | "NONE";
  reason: string;
}

const WORKSPACE_PREFIX = "file:///ws/";

/** Derive the relative path a conflict projection targets, or null. */
export function conflictPath(writeScopeUris: string[]): string | null {
  for (const uri of writeScopeUris) {
    if (uri.startsWith(WORKSPACE_PREFIX)) {
      return uri.slice(WORKSPACE_PREFIX.length);
    }
  }
  return writeScopeUris.length > 0 ? writeScopeUris[0] : null;
}

/** Build a renderer-facing conflict badge for a path, or null if no conflict. */
export function conflictBadgeForPath(
  writeScopeUris: string[],
  disposition: "REPLAN" | "CONFLICT" | "CANCEL",
  suggestedAction: "REPLAN" | "REVIEW_DIFF" | "NONE",
  reason: string,
  path: string,
): ConflictBadge | null {
  const target = conflictPath(writeScopeUris);
  if (target === null || target !== path) {
    return null;
  }
  return { disposition, suggestedAction, reason };
}
