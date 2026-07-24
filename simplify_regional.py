import json
import os

INPUT = os.path.join('Mapas vectoriales', 'JSONS', 'Regional.json')
OUTPUT = os.path.join('Mapas vectoriales', 'JSONS', 'Regional_simplified.json')

def simp(c, p=3):
    if isinstance(c, (int, float)):
        return round(c, p)
    if isinstance(c, list):
        return [simp(x, p) for x in c]
    return c

with open(INPUT, 'r', encoding='utf-8') as f:
    raw = f.read()

txt = raw[raw.index('{'):].rstrip().rstrip(';')
data = json.loads(txt)

for feat in data['features']:
    if feat.get('geometry'):
        feat['geometry']['coordinates'] = simp(feat['geometry']['coordinates'])

out = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
with open(OUTPUT, 'w', encoding='utf-8') as f:
    f.write(out)

print(f'Output size: {len(out)/1024/1024:.1f} MB')
