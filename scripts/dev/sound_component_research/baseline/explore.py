import json, collections, os
t = json.load(open('tmp/library-analysis/tracks.json', encoding='utf-8'))
loc = [r for r in t if not str(r.get('path', '')).startswith(('soundcloud:', 'spotify:'))]
ok = [r for r in loc if 180 <= (r.get('TotalTime') or 0) <= 420]
def folder(p):
    parts = p.replace(chr(92), '/').split('/')
    return '/'.join(parts[-3:-1])
fo = collections.Counter(folder(r['path']) for r in ok if not (r.get('Genre') or '').strip())
for k, v in fo.most_common(60):
    print(v, k)
print('----2000s / pashanim')
for r in ok:
    pl = r['path'].lower()
    if '2000s' in pl or 'pashanim' in pl:
        print(r['ID'], r['Artist'], '-', r['Title'], '|', r['Genre'], r['BPM'], r['TotalTime'], os.path.splitext(r['path'])[1])
