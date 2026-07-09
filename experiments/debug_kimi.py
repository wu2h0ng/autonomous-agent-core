"""Debug: test Kimi API call directly."""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_KEY = "KIMI_API_KEY_PLACEHOLDER"
API_URL = "https://api.kimi.com/coding/v1/chat/completions"

prompt = "Given these proteins: Raf, Mek, Plcg, PIP2, PIP3, Erk, Akt, PKA, PKC, P38, Jnk. For the edge (Raf)--(Mek), which direction is causal? Return JSON: {\"orientations\": [{\"i\": 0, \"j\": 1, \"direction\": \"0→1\", \"score\": 0.8}]}"

payload = json.dumps({
    "model": "kimi-k2.6",
    "messages": [{"role": "user", "content": "say hello"}],
}).encode("utf-8")

req = urllib.request.Request(API_URL, data=payload, headers={
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode()
        print(f"RAW RESPONSE: {raw[:500]}")
        rj = json.loads(raw)
        content = rj.get("choices",[{}])[0].get("message",{}).get("content","")
        print(f"\nCONTENT: {content[:300]}")
except Exception as e:
    print(f"ERROR: {e}")
