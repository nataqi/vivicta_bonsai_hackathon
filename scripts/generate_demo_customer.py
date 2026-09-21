"""One-off: synthesize the fictional demo customer's lines with ElevenLabs.

Reads frontend/src/lib/demo/anna.json and writes frontend/public/demo/anna/*.mp3.
Run from the repo root with the backend venv (it already has httpx and python-dotenv):

    backend/.venv/Scripts/python scripts/generate_demo_customer.py          # Windows
    backend/.venv/bin/python scripts/generate_demo_customer.py              # macOS/Linux

Needs ELEVENLABS_API_KEY in .env. The generated MP3s are committed, so this only needs
re-running when the script or voice changes.
"""
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "frontend" / "src" / "lib" / "demo" / "anna.json"
PUBLIC = ROOT / "frontend" / "public"
MODEL = "eleven_multilingual_v2"
# Lower stability and some style make the delivery more emotional and less announcer-like.
VOICE_SETTINGS = {"stability": 0.35, "similarity_boost": 0.75, "style": 0.45, "use_speaker_boost": True}


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        print("ELEVENLABS_API_KEY is not set in .env", file=sys.stderr)
        return 1

    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    for line in script["lines"]:
        target = PUBLIC / line["file"].lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        response = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{script['voiceId']}",
            headers={"xi-api-key": api_key},
            params={"output_format": "mp3_44100_128"},
            json={"text": line["text"], "model_id": MODEL, "voice_settings": VOICE_SETTINGS},
            timeout=60,
        )
        if response.status_code != 200:
            print(f"Line {line['id']} failed: HTTP {response.status_code} {response.text[:200]}", file=sys.stderr)
            return 1
        target.write_bytes(response.content)
        print(f"{line['id']}: {len(response.content) / 1024:.0f} KB -> {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
