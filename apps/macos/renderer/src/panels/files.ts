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
        "X-Agent-OS-Protocol": "1.0",
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
