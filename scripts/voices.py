"""Voice audition (runs in GitHub Actions; stdlib only).

Lists Japanese voices from the ElevenLabs Voice Library plus the account's own voices,
then synthesizes one test line with each candidate so we can compare them on our script.
Output: data/voices/list.json, data/voices/samples/<n>_<name>.mp3
"""
import json, os, re, sys, urllib.parse, urllib.request, urllib.error

KEY = os.environ.get('ELEVENLABS_API_KEY', '').strip()
LINE = 'もしも、渋谷駅を丸ごと買収したら、いくらになるのか。答えは、およそ900億円。計算してみましょう。'
N = int(os.environ.get('N', '8'))
OUT = 'data/voices'


def get(path, params=None):
    url = 'https://api.elevenlabs.io' + path + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(url, headers={'xi-api-key': KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def tts(voice_id):
    url = f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128'
    body = json.dumps({'text': LINE, 'model_id': 'eleven_multilingual_v2', 'language_code': 'ja',
                       'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75, 'style': 0.15,
                                          'use_speaker_boost': True, 'speed': 1.1}}).encode()
    req = urllib.request.Request(url, data=body, method='POST',
                                 headers={'xi-api-key': KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def main():
    if not KEY:
        raise SystemExit('ELEVENLABS_API_KEY is not set')
    os.makedirs(OUT + '/samples', exist_ok=True)
    cands = []
    try:
        for v in get('/v1/voices').get('voices', []):
            cands.append({'source': 'mine', 'voice_id': v['voice_id'], 'name': v.get('name'),
                          'labels': v.get('labels'), 'category': v.get('category')})
    except urllib.error.HTTPError as e:
        print('my voices:', e.code, e.read()[:200])
    try:
        lib = get('/v1/shared-voices', {'language': 'ja', 'page_size': 40, 'sort': 'usage_character_count_1y'})
        for v in lib.get('voices', []):
            cands.append({'source': 'library', 'voice_id': v['voice_id'], 'name': v.get('name'),
                          'gender': v.get('gender'), 'age': v.get('age'), 'accent': v.get('accent'),
                          'use_case': v.get('use_case'), 'descriptive': v.get('descriptive'),
                          'description': (v.get('description') or '')[:160],
                          'usage_1y': v.get('usage_character_count_1y'),
                          'free_users_allowed': v.get('free_users_allowed'),
                          'preview_url': v.get('preview_url')})
    except urllib.error.HTTPError as e:
        print('library:', e.code, e.read()[:200])

    # Prefer narration-type library voices, then most used.
    def score(c):
        uc = (c.get('use_case') or '') + ' ' + (c.get('descriptive') or '')
        return (c['source'] != 'library', not re.search('narrat|informative|news|educat|documentar', uc),
                -(c.get('usage_1y') or 0))
    lib_sorted = sorted([c for c in cands if c['source'] == 'library'], key=score)[:N]

    for i, c in enumerate(lib_sorted, 1):
        safe = re.sub(r'[^0-9A-Za-z]+', '_', c.get('name') or 'voice')[:30]
        path = f'{OUT}/samples/{i:02d}_{safe}.mp3'
        try:
            open(path, 'wb').write(tts(c['voice_id']))
            c['sample'] = path
        except urllib.error.HTTPError as e:
            c['sample_error'] = f'{e.code} {e.read()[:200]!r}'
        c['rank'] = i
        print(i, c.get('name'), c.get('gender'), c.get('age'), c.get('use_case'), c.get('sample') or c.get('sample_error'))

    json.dump({'line': LINE, 'auditioned': lib_sorted, 'all': cands}, open(OUT + '/list.json', 'w'),
              ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
