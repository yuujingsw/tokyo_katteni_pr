"""Instagram Reels publisher (stdlib only).

Usage:
  python scripts/ig.py check                 # verify token, print account (no posting)
  python scripts/ig.py publish queue/<slug>  # publish video.mp4 + caption.txt as a Reel

Env:
  IG_ACCESS_TOKEN  (required, GitHub secret — never printed)
  IG_USER_ID       (optional override; otherwise discovered from the token)
"""
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

VER = 'v23.0'
TOKEN = os.environ.get('IG_ACCESS_TOKEN', '').strip()
if not TOKEN:
    sys.exit('IG_ACCESS_TOKEN is not set')


def req(method, url, params=None, data=None, headers=None):
    params = dict(params or {})
    if 'rupload' not in url:
        params['access_token'] = TOKEN
    full = url + ('?' + urllib.parse.urlencode(params) if params and method == 'GET' else '')
    body = data
    if method == 'POST' and data is None:
        body = urllib.parse.urlencode(params).encode()
    r = urllib.request.Request(full, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            return json.loads(resp.read().decode() or '{}')
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors='replace').replace(TOKEN, '***')
        raise RuntimeError(f'{method} {url.split("?")[0]} -> {e.code}: {msg}') from None


def discover():
    """Return (host, ig_user_id, username)."""
    uid = os.environ.get('IG_USER_ID', '').strip()
    # 1) Instagram-login token
    try:
        me = req('GET', f'https://graph.instagram.com/{VER}/me', {'fields': 'user_id,username'})
        return 'https://graph.instagram.com', uid or me['user_id'], me.get('username')
    except RuntimeError as e:
        print('graph.instagram.com not usable:', str(e)[:160])
    # 2) Facebook-graph token (system user / page)
    fb = 'https://graph.facebook.com'
    if uid:
        info = req('GET', f'{fb}/{VER}/{uid}', {'fields': 'id,username'})
        return fb, info['id'], info.get('username')
    pages = req('GET', f'{fb}/{VER}/me/accounts', {'fields': 'name,instagram_business_account{id,username}'})
    for p in pages.get('data', []):
        iba = p.get('instagram_business_account')
        if iba:
            return fb, iba['id'], iba.get('username')
    raise RuntimeError('Could not find the Instagram account for this token. Set IG_USER_ID as a repo variable.')


def check():
    host, uid, name = discover()
    print(f'OK  host={host}  ig_user_id={uid}  username=@{name}')
    try:
        lim = req('GET', f'{host}/{VER}/{uid}/content_publishing_limit', {'fields': 'quota_usage,config'})
        print('publishing limit:', json.dumps(lim.get('data', lim)))
    except RuntimeError as e:
        print('limit check skipped:', str(e)[:160])


def publish(folder):
    video = os.path.join(folder, 'video.mp4')
    caption = open(os.path.join(folder, 'caption.txt'), encoding='utf-8').read().strip()
    size = os.path.getsize(video)
    host, uid, name = discover()
    print(f'publishing {folder} ({size/1e6:.1f} MB) to @{name}')

    c = req('POST', f'{host}/{VER}/{uid}/media',
            {'media_type': 'REELS', 'upload_type': 'resumable', 'caption': caption, 'share_to_feed': 'true'})
    cid = c['id']
    print('container', cid)

    with open(video, 'rb') as f:
        blob = f.read()
    up = req('POST', f'https://rupload.facebook.com/ig-api-upload/{VER}/{cid}', data=blob,
             headers={'Authorization': f'OAuth {TOKEN}', 'offset': '0', 'file_size': str(size)})
    print('upload', json.dumps(up))

    for i in range(60):
        st = req('GET', f'{host}/{VER}/{cid}', {'fields': 'status_code,status'})
        code = st.get('status_code')
        print(f'  status[{i}]', code)
        if code == 'FINISHED':
            break
        if code in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'container failed: {json.dumps(st)}')
        time.sleep(10)
    else:
        raise RuntimeError('timed out waiting for video processing')

    pub = req('POST', f'{host}/{VER}/{uid}/media_publish', {'creation_id': cid})
    mid = pub['id']
    link = req('GET', f'{host}/{VER}/{mid}', {'fields': 'permalink'}).get('permalink')
    print('PUBLISHED', mid, link)
    result = {'media_id': mid, 'permalink': link, 'published_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
    with open(os.path.join(folder, 'result.json'), 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    summ = os.environ.get('GITHUB_STEP_SUMMARY')
    if summ:
        with open(summ, 'a', encoding='utf-8') as f:
            f.write(f'### 投稿しました\n{link}\n')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'check':
        check()
    elif cmd == 'publish':
        publish(sys.argv[2].rstrip('/'))
    else:
        sys.exit(__doc__)
