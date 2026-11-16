"""Model shoot-out with automatic listening test (runs in GitHub Actions).

For one tts job, synthesizes every line with several ElevenLabs models, transcribes each
with Whisper, and scores character error rate against the intended text.
Output: tts/<job>/qa/<model>/<id>.mp3, tts/<job>/qa/report.json
"""
import base64, json, os, re, sys, unicodedata, urllib.request, urllib.error

KEY = os.environ['ELEVENLABS_API_KEY'].strip()
job = sys.argv[1]
cfg = json.load(open(f'tts/{job}/lines.json', encoding='utf-8'))
voice = cfg['voice_id']
MODELS = {
    'eleven_multilingual_v2': {'stability': 0.5, 'similarity_boost': 0.75, 'style': 0.15, 'use_speaker_boost': True, 'speed': 1.1},
    'eleven_v3': {'stability': 0.5, 'similarity_boost': 0.75},
    'eleven_flash_v2_5': {'stability': 0.5, 'similarity_boost': 0.75, 'speed': 1.1},
}


def tts(text, model, settings, lang):
    body = {'text': text, 'model_id': model, 'voice_settings': settings}
    if lang:
        body['language_code'] = 'ja'
    req = urllib.request.Request(
        f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128',
        data=json.dumps(body).encode(), method='POST',
        headers={'xi-api-key': KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def norm(s):
    s = unicodedata.normalize('NFKC', s)
    return re.sub(r'[\s、。，．,.！!？?「」…・ー]', '', s)


def cer(ref, hyp):
    a, b = norm(ref), norm(hyp)
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        p, d[0] = d[0], i
        for j, cb in enumerate(b, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (ca != cb))
    return d[len(b)] / max(1, len(a))


import subprocess, numpy as np
from faster_whisper import WhisperModel


def load(path):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', '16000', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768
asr = WhisperModel('medium', device='cpu', compute_type='int8')
report = {'voice': voice, 'models': {}}
for model, st in MODELS.items():
    rows = []
    for variant, lang in (('lang', True), ('nolang', False)):
        d = f'tts/{job}/qa/{model}-{variant}'
        os.makedirs(d, exist_ok=True)
        for ln in cfg['lines']:
            path = f"{d}/{ln['id']}.mp3"
            try:
                open(path, 'wb').write(tts(ln['text'], model, st, lang))
            except urllib.error.HTTPError as e:
                rows.append({'variant': variant, 'id': ln['id'], 'error': f'{e.code} {e.read()[:200]!r}'})
                break
            segs, _ = asr.transcribe(load(path), language='ja', beam_size=5)
            heard = ''.join(s.text for s in segs)
            rows.append({'variant': variant, 'id': ln['id'], 'said': ln['text'], 'heard': heard,
                         'cer': round(cer(ln['text'], heard), 3)})
            print(model, variant, ln['id'], rows[-1]['cer'], heard, flush=True)
    report['models'][model] = rows
for model, rows in report['models'].items():
    for variant in ('lang', 'nolang'):
        c = [r['cer'] for r in rows if r.get('variant') == variant and 'cer' in r]
        print('SUMMARY', model, variant, round(sum(c) / len(c), 3) if c else 'error')
json.dump(report, open(f'tts/{job}/qa/report.json', 'w'), ensure_ascii=False, indent=1)
