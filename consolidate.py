import json
import os
import re

def clean_prop_keys(properties):
    """
    Clean up property keys: remove extra whitespace/newlines.
    Keep the values as they are.
    """
    cleaned = {}
    for k, v in properties.items():
        clean_k = re.sub(r'\s+', ' ', str(k)).strip()
        cleaned[clean_k] = v
    return cleaned

def load_layer_file(path):
    if not os.path.exists(path):
        print(f"Warning: File not found at {path}")
        return []
    
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        
    # Strip potential JavaScript variable wrapping (e.g. var airports = { ... };)
    idx = content.find('{')
    if idx != -1:
        content = content[idx:].rstrip(';').strip()
        
    try:
        data = json.loads(content)
    except Exception as e:
        print(f"Error parsing JSON from {path}: {e}")
        return []
        
    return data.get('features', [])

def main():
    jsons_dir = os.path.join('Mapas vectoriales', 'JSONS')
    
    # Mapping source files to their Sector label
    files_n_sectors = [
        ('Aeropuertos_de_Chile_DGC.json', 'Aeropuertos'),
        ('Hospitales_Concesionados_DGC.json', 'Hospitales'),
        ('miscelaneo_dgc.json', 'Diversos'),
        ('Rutas_DGC.json', 'Rutas')
    ]
    
    combined_features = []
    
    for filename, sector in files_n_sectors:
        path = os.path.join(jsons_dir, filename)
        features = load_layer_file(path)
        print(f"Loaded {len(features)} features from {filename} ({sector})")
        
        for feat in features:
            props = feat.get('properties', {})
            # Keep original properties but clean the property keys of formatting space garbage
            cleaned_props = clean_prop_keys(props)
            # Inject consolidated attribute
            cleaned_props['Sector_DGC'] = sector
            feat['properties'] = cleaned_props
            combined_features.append(feat)
            
    output_collection = {
        "type": "FeatureCollection",
        "features": combined_features
    }
    
    output_path = os.path.join(jsons_dir, 'DGC.json')
    with open(output_path, 'w', encoding='utf-8') as out_f:
        json.dump(output_collection, out_f, ensure_ascii=False)
        
    print(f"Successfully consolidated {len(combined_features)} features into {output_path}")

if __name__ == '__main__':
    main()
