"""Trend radar (read-only, stdlib only).

Collects:
  1. Google Trends — Japan daily trending searches (public RSS)
  2. Instagram hashtag top posts (Graph API ig_hashtag_search; limit: 30 unique hashtags per 7 days)

Usage: python scripts/trends.py [extra hashtags, comma separated]
Writes data/trends/latest.json and data/trends/YYYY-MM-DD.json
"""
import json, os, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET

VER = 'v23.0'
TOKEN = os.environ.get('IG_ACCESS_TOKEN', '').strip()
UID = os.environ.get('IG_USER_ID', '17841435576448672').strip()
WATCH = ['東京新店', '新店オープン', '東京グルメ', '東京カフェ', '東京ホテル', '東京観光', '東京駅グルメ', '神保町']
UA = {'User-Agent': 'Mozilla/5.0 (trend-radar; +https://github.com/yuujingsw/tokyo_katteni_pr)'}


def get(url, params=None, headers=None):
    full = url + ('?' + urllib.parse.urlencode(params) if params else '')
    req = urllib.request.Request(full, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


NEWS_QUERIES = ['東京 初上陸', '東京 新店 オープン', '東京 閉店', '東京 再開発 取り壊し', '東京 開業 ホテル', '東京 行列 話題']


def google_news(q):
    out = []
    try:
        raw = get('https://news.google.com/rss/search', {'q': q + ' when:3d', 'hl': 'ja', 'gl': 'JP', 'ceid': 'JP:ja'}, UA)
        for it in ET.fromstring(raw).iter('item'):
            out.append({'title': it.findtext('title', ''), 'source': it.findtext('source', ''), 'pubDate': it.findtext('pubDate', ''),
                        'url': it.findtext('link', '')})
    except Exception as e:
        out = [{'error': f'{type(e).__name__}: {str(e)[:300]}'}]
    return out[:15]


def google_trends(geo='JP'):
    out = []
    try:
        raw = get('https://trends.google.co.jp/trending/rss', {'geo': geo}, UA)
        root = ET.fromstring(raw)
        ns = {'ht': 'https://trends.google.com/trending/rss'}
        for it in root.iter('item'):
            news = [{'title': n.findtext('ht:news_item_title', '', ns), 'source': n.findtext('ht:news_item_source', '', ns),
                     'url': n.findtext('ht:news_item_url', '', ns)} for n in it.findall('ht:news_item', ns)]
            out.append({'title': it.findtext('title', ''), 'traffic': it.findtext('ht:approx_traffic', '', ns),
                        'pubDate': it.findtext('pubDate', ''), 'news': news[:3]})
    except Exception as e:  # keep the run alive; record the failure
        out = [{'error': f'{type(e).__name__}: {str(e)[:300]}'}]
    return out


def ig(path, params):
    p = dict(params, access_token=TOKEN)
    try:
        return json.loads(get(f'https://graph.facebook.com/{VER}/{path}', p))
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors='replace').replace(TOKEN, '***')
        return {'error': msg[:400]}


def hashtags(tags):
    res = {}
    if not TOKEN:
        return {'_error': 'IG_ACCESS_TOKEN not set'}
    for tag in tags:
        h = ig('ig_hashtag_search', {'user_id': UID, 'q': tag})
        if 'error' in h or not h.get('data'):
            res[tag] = {'error': h.get('error', 'not found')}
            continue
        hid = h['data'][0]['id']
        top = ig(f'{hid}/top_media', {'user_id': UID, 'limit': 25,
                                     'fields': 'id,media_type,media_product_type,like_count,comments_count,timestamp,permalink,caption'})
        if 'error' in top:
            res[tag] = {'id': hid, 'error': top['error']}
            continue
        items = []
        for m in top.get('data', []):
            items.append({k: m.get(k) for k in ('media_product_type', 'like_count', 'comments_count', 'timestamp', 'permalink')}
                         | {'caption': (m.get('caption') or '')[:160]})
        items.sort(key=lambda m: (m.get('like_count') or 0) + 3 * (m.get('comments_count') or 0), reverse=True)
        res[tag] = {'id': hid, 'top': items[:10]}
        time.sleep(1)
    return res


if __name__ == '__main__':
    extra = [t.strip().lstrip('#') for t in (sys.argv[1] if len(sys.argv) > 1 else '').split(',') if t.strip()]
    tags = list(dict.fromkeys(WATCH + extra))[:15]
    use_ig = os.environ.get('IG_HASHTAGS', '') == '1'   # needs Meta app review (Instagram Public Content Access)
    data = {'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'google_trends_jp': google_trends('JP'), 'google_trends_tokyo': google_trends('JP-13'),
            'google_news': {q: google_news(q) for q in NEWS_QUERIES},
            'ig_hashtags': hashtags(tags) if use_ig else {'_skipped': 'Instagram Public Content Access not approved yet'}}
    os.makedirs('data/trends', exist_ok=True)
    for p in ('data/trends/latest.json', f"data/trends/{time.strftime('%Y-%m-%d')}.json"):
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    g = data['google_trends_jp']
    print('google trends:', len(g), 'items;', ', '.join(x.get('title', x.get('error', '')) for x in g[:10]))
    t2 = data['google_trends_tokyo']
    print('google trends tokyo:', len(t2), 'items;', ', '.join(x.get('title', x.get('error', '')) for x in t2[:10]))
    for q, items in data['google_news'].items():
        print('news[' + q + ']:', len(items), '|', ' / '.join(i.get('title', i.get('error', ''))[:40] for i in items[:4]))
    for t, v in data['ig_hashtags'].items():
        print('#' + t, 'ERROR ' + str(v.get('error'))[:200] if isinstance(v, dict) and 'error' in v else f"{len(v.get('top', []))} top posts" if isinstance(v, dict) else v)
