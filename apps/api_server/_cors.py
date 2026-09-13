"""CORS policy for the Tauri webview origins (never '*')."""


def _tauri_origin_cors(origin: str | None) -> dict[str, str]:
    """CORS headers for the Tauri webview origins only (never '*').

    The renderer talks to the daemon over loopback HTTP; the webview origin
    is one of the Tauri custom-scheme origins. Every other Origin gets no
    CORS headers.
    """

    if origin not in {"tauri://localhost", "http://tauri.localhost"}:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": (
            "Authorization, Content-Type, X-Agent-OS-Protocol, Last-Event-ID"
        ),
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    }
