"""Debug: test Kimi Sachs orientation prompt directly."""
import json, os, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_KEY = "KIMI_API_KEY_PLACEHOLDER"
API_URL = "https://api.kimi.com/coding/v1/chat/completions"
PROTEINS = ["Raf","Mek","Plcg","PIP2","PIP3","Erk","Akt","PKA","PKC","P38","Jnk"]

edges = [(0,1)]  # just Raf-Mek
ed_str = "  (0:Raf) -- (1:Mek)"

prompt = f"""Proteins: {', '.join(f'{i}:{p}' for i,p in enumerate(PROTEINS))}
Undirected edges:
{ed_str}
For each edge, return the causal direction based on known biology.
Return ONLY JSON: {{"orientations": [{{"i": 0, "j": 1, "direction": "0→1", "score": 0.8}}]}}"""

prompt = f"""Proteins: {', '.join(f'{i}:{p}' for i,p in enumerate(PROTEINS))}
Undirected edges:
{ed_str}
For each edge, return the causal direction based on known biology.
Return ONLY JSON: {{"orientations": [{{"i": 0, "j": 1, "direction": "0→1", "score": 0.8}}, ...]}}"""

payload = json.dumps({
    "model": "kimi-k2.6",
    "messages": [
        {"role": "system", "content": "You are a molecular biology causal discovery expert. Return ONLY valid JSON."},
        {"role": "user", "content": prompt},
    ],
}).encode("utf-8")

req = urllib.request.Request(API_URL, data=payload, headers={
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
})
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        rj = json.loads(resp.read().decode())
        content = rj.get("choices",[{}])[0].get("message",{}).get("content","")
        print(f"RAW CONTENT:\n{content[:2000]}")
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"): content = content[4:]
        parsed = json.loads(content)
        print(f"\nPARSED: {len(parsed.get('orientations',[]))} orientations")
except Exception as e:
    print(f"ERROR: {e}")
