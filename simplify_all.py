import json
import os

def simp(c, p=2):
    if isinstance(c, (int, float)):
        return round(c, p)
    if isinstance(c, list):
        return [simp(x, p) for x in c]
    return c

# Simplify Regional.json to p=2
INPUT_REGIONAL = os.path.join('Mapas vectoriales', 'JSONS', 'Regional.json')
OUTPUT_REGIONAL = os.path.join('Mapas vectoriales', 'JSONS', 'Regional_simplified.json')

with open(INPUT_REGIONAL, 'r', encoding='utf-8') as f:
    raw = f.read()
txt = raw[raw.index('{'):].rstrip().rstrip(';')
data = json.loads(txt)

# Filter/clean duplicates
for feat in data['features']:
    if feat.get('geometry'):
        feat['geometry']['coordinates'] = simp(feat['geometry']['coordinates'], p=2)

out = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
with open(OUTPUT_REGIONAL, 'w', encoding='utf-8') as f:
    f.write(out)
print(f'Regional size with 2 decimals: {len(out)/1024/1024:.2f} MB')

# Simplify Rutas_DGC.json to p=4 and filter by COD
INPUT_RUTAS = os.path.join('Mapas vectoriales', 'JSONS', 'Rutas_DGC.json')
OUTPUT_RUTAS = os.path.join('Mapas vectoriales', 'JSONS', 'Rutas_simplified.json')

with open(INPUT_RUTAS, 'r', encoding='utf-8') as f:
    data_rutas = json.load(f)

# Filter by COD
filtered_rutas = [ft for ft in data_rutas['features'] if ft.get('properties') and ft['properties'].get('COD') and str(ft['properties']['COD']).strip()]
data_rutas['features'] = filtered_rutas

# Simplify coordinates to 4 decimals
for feat in data_rutas['features']:
    if feat.get('geometry'):
        feat['geometry']['coordinates'] = simp(feat['geometry']['coordinates'], p=4)

out_rutas = json.dumps(data_rutas, ensure_ascii=False, separators=(',', ':'))
with open(OUTPUT_RUTAS, 'w', encoding='utf-8') as f:
    f.write(out_rutas)
print(f'Rutas size with 4 decimals: {len(out_rutas)/1024/1024:.2f} MB')
