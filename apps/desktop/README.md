# Agent OS Desktop Surface

`python -m apps.desktop` is the first desktop delivery for the local Agent OS
Surface. It supervises the existing Python Runtime, waits for `/v1/health`, and
opens either the live Task Workspace or the deterministic Chinese UX preview.

This is deliberately a thin desktop shell. It does not add a second task store,
credential path, capability broker, or execution authority. A future macOS/Tauri
package can replace this launcher while keeping the same Runtime protocol.

Examples:

```bash
python -m apps.desktop --workspace /path/to/repo
python -m apps.desktop --surface preview --no-open
```
