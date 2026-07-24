import json
import os
import re

jsons_dir = os.path.join('Mapas vectoriales', 'JSONS')
files = ['Aeropuertos_de_Chile_DGC.json', 'Hospitales_Concesionados_DGC.json', 'miscelaneo_dgc.json', 'Rutas_DGC.json']

output_lines = []

for f in files:
    path = os.path.join(jsons_dir, f)
    if not os.path.exists(path):
        output_lines.append(f"{f} does not exist")
        continue
    with open(path, 'r', encoding='utf-8') as file:
        content = file.read().strip()
    idx = content.find('{')
    if idx != -1:
        content = content[idx:].rstrip(';').strip()
    data = json.loads(content)
    features = data.get('features', [])
    if features:
        seen_keys = set()
        for feat in features:
            props = feat.get('properties', {})
            for k in props.keys():
                clean_k = re.sub(r'\s+', ' ', str(k)).strip()
                seen_keys.add(clean_k)
        output_lines.append(f"{f}: {len(features)} features. Keys: {sorted(list(seen_keys))}")
    else:
        output_lines.append(f"{f}: 0 features")

log_path = os.path.join('app', 'log_props.txt')
with open(log_path, 'w', encoding='utf-8') as f_out:
    f_out.write('\n'.join(output_lines))
print("Done writing props to file")
