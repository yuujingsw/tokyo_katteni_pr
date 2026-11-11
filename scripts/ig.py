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
    try:
        me = req('GET', f'{fb}/{VER}/me', {'fields': 'id,name'})
        print('me ->', json.dumps(me)[:400])
    except RuntimeError as e:
        print('me failed:', str(e)[:200])
    probes = [
        ('me/accounts', {'fields': 'name,instagram_business_account{id,username}'}),
        ('me/businesses', {'fields': 'id,name,owned_instagram_accounts{id,username},instagram_business_accounts{id,username}'}),
        ('me/assigned_business_asset_groups', {}),
    ]
    for path, params in probes:
        try:
            res = req('GET', f'{fb}/{VER}/{path}', params)
        except RuntimeError as e:
            print(path, 'failed:', str(e)[:200])
            continue
        for p in res.get('data', []):
            iba = p.get('instagram_business_account')
            if iba:
                return fb, iba['id'], iba.get('username')
            for key in ('instagram_business_accounts', 'owned_instagram_accounts'):
                for a in (p.get(key) or {}).get('data', []):
                    print(path, key, a)
                    if key == 'instagram_business_accounts':
                        return fb, a['id'], a.get('username')
        print(path, '->', json.dumps(res)[:300])
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
    tags = [w for w in caption.split() if w.startswith('#')]
    if len(tags) > 5:
        raise RuntimeError(f'ハッシュタグは5個までです（現在{len(tags)}個）')
    size = os.path.getsize(video)
    host, uid, name = discover()
    print(f'publishing {folder} ({size/1e6:.1f} MB) to @{name}')

    base = {'media_type': 'REELS', 'caption': caption, 'share_to_feed': 'true'}
    cid = None
    try:
        c = req('POST', f'{host}/{VER}/{uid}/media', dict(base, upload_type='resumable'))
        cid = c['id']
        print('container (resumable)', cid)
        with open(video, 'rb') as f:
            blob = f.read()
        up = req('POST', f'https://rupload.facebook.com/ig-api-upload/{VER}/{cid}', data=blob,
                 headers={'Authorization': f'OAuth {TOKEN}', 'offset': '0', 'file_size': str(size),
                          'Content-Type': 'application/octet-stream'})
        print('upload', json.dumps(up))
    except RuntimeError as e:
        # fallback: let Instagram fetch the file from the public repo
        repo, sha = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GITHUB_SHA')
        if not (repo and sha):
            raise
        print('resumable upload failed, falling back to video_url:', str(e)[:200])
        url = f'https://raw.githubusercontent.com/{repo}/{sha}/{urllib.parse.quote(video)}'
        c = req('POST', f'{host}/{VER}/{uid}/media', dict(base, video_url=url))
        cid = c['id']
        print('container (video_url)', cid)

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
