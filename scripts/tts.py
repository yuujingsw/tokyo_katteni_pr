"""ElevenLabs TTS (runs in GitHub Actions; stdlib only).

Input : tts/<job>/lines.json  = {"voice_id": "...?", "model_id": "...?", "settings": {...}?, "lines": [{"id": "01", "text": "..."}, ...]}
Output: tts/<job>/out/<id>.mp3 and tts/<job>/out/<id>.json (character timestamps for subtitles)
Skips lines whose mp3 already exists unless the text changed (hash check).
"""
import base64, hashlib, json, os, sys, time, urllib.request, urllib.error

KEY = os.environ.get('ELEVENLABS_API_KEY', '').strip()
DEFAULT_VOICE = os.environ.get('ELEVENLABS_VOICE_ID', '').strip()


def tts(text, voice, model, settings):
    url = f'https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps?output_format=mp3_44100_128'
    body = json.dumps({'text': text, 'model_id': model, 'voice_settings': settings, 'language_code': 'ja'}).encode()
    req = urllib.request.Request(url, data=body, method='POST',
                                 headers={'xi-api-key': KEY, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors='replace')[:300]
            if e.code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1)); continue
            raise SystemExit(f'ElevenLabs error {e.code}: {msg}')


def run(job):
    if not KEY:
        raise SystemExit('ELEVENLABS_API_KEY is not set')
    cfg = json.load(open(f'tts/{job}/lines.json', encoding='utf-8'))
    voice = cfg.get('voice_id') or DEFAULT_VOICE
    if not voice:
        raise SystemExit('voice_id missing (lines.json or ELEVENLABS_VOICE_ID)')
    model = cfg.get('model_id', 'eleven_multilingual_v2')
    settings = cfg.get('settings', {'stability': 0.5, 'similarity_boost': 0.75, 'style': 0.15, 'use_speaker_boost': True, 'speed': 1.1})
    out = f'tts/{job}/out'; os.makedirs(out, exist_ok=True)
    chars = 0
    for ln in cfg['lines']:
        h = hashlib.sha1(json.dumps([ln['text'], voice, model, settings], ensure_ascii=False).encode()).hexdigest()[:12]
        meta_p = f"{out}/{ln['id']}.json"
        if os.path.exists(meta_p) and json.load(open(meta_p)).get('hash') == h:
            continue
        res = tts(ln['text'], voice, model, settings)
        open(f"{out}/{ln['id']}.mp3", 'wb').write(base64.b64decode(res['audio_base64']))
        json.dump({'hash': h, 'text': ln['text'], 'alignment': res.get('alignment')}, open(meta_p, 'w'), ensure_ascii=False)
        chars += len(ln['text'])
        print(f"{ln['id']}: {len(ln['text'])} chars ok")
    print(f'done: {chars} chars synthesized')


if __name__ == '__main__':
    jobs = [a for a in sys.argv[1:] if a] or sorted(d for d in os.listdir('tts') if os.path.isdir(f'tts/{d}'))
    for j in jobs:
        run(j)
