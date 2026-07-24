import json
import os

INPUT_REGIONAL = os.path.join('Mapas vectoriales', 'JSONS', 'Regional.json')
OUTPUT_REGIONAL = os.path.join('Mapas vectoriales', 'JSONS', 'Regional_simplified.json')

def decimate_coords(coords, step=15):
    """
    Decimates coordinate lists.
    A coordinate list can be a deep nested structure depending on geometry type:
    - Polygon: list of rings (list of [lng, lat])
    - MultiPolygon: list of Polygons (list of list of rings)
    """
    if not isinstance(coords, list):
        return coords
    
    # Check if this is a list of [lng, lat] (i.e. number coordinates)
    if len(coords) > 0 and isinstance(coords[0], (int, float)):
        return coords
        
    # Check if this is a list of points (i.e. list of [lng, lat])
    if len(coords) > 0 and isinstance(coords[0], list) and len(coords[0]) == 2 and isinstance(coords[0][0], (int, float)):
        # Decimate the ring points, keeping the first and last points intact to close the polygon
        if len(coords) <= 4:
            return coords
        new_coords = [coords[0]]
        for i in range(1, len(coords) - 1, step):
            # Round to 3 decimals to save space
            pt = [round(coords[i][0], 3), round(coords[i][1], 3)]
            new_coords.append(pt)
        new_coords.append([round(coords[-1][0], 3), round(coords[-1][1], 3)])
        return new_coords
        
    # Recursive decimation for nested lists
    return [decimate_coords(x, step) for x in coords]

def main():
    with open(INPUT_REGIONAL, 'r', encoding='utf-8') as f:
        raw = f.read()
    txt = raw[raw.index('{'):].rstrip().rstrip(';')
    data = json.loads(txt)
    
    # Decimate geometry points
    for feat in data['features']:
        if feat.get('geometry') and feat['geometry'].get('coordinates'):
            feat['geometry']['coordinates'] = decimate_coords(feat['geometry']['coordinates'], step=15)
            
    out = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    with open(OUTPUT_REGIONAL, 'w', encoding='utf-8') as f:
        f.write(out)
    print(f'Decimated Regional size: {len(out)/1024/1024:.2f} MB')

if __name__ == '__main__':
    main()
