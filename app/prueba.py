import os
import re
import json
import sqlite3
import unicodedata
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'caltec.db')

if not os.path.exists(DB_PATH):
    # Try running migration automatically if DB missing
    migrator = os.path.join(BASE_DIR, 'migrate_to_sqlite.py')
    if os.path.exists(migrator):
        import subprocess
        subprocess.run(['python', migrator], check=True)

if not os.path.exists(DB_PATH):
    raise FileNotFoundError(f"No se encontró la base de datos SQLite en: {DB_PATH}")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Helper: Standardize region splitting and naming convention (Chile 16 Regions)
def parse_regions_from_row(region_str):
    if not region_str or not isinstance(region_str, str):
        return []
    
    region_str = region_str.replace('&nbsp;', ' ').replace('\xa0', ' ')
    parts = re.split(r'[;,]', region_str)
    cleaned = []
    
    for p in parts:
        p = p.strip()
        if not p:
            continue
        
        if p == 'Metropolitana':
            p = 'Metropolitana de Santiago'
        elif p in ('Araucanía', 'Araucanía '):
            p = 'La Araucanía'
            
        if p not in cleaned:
            cleaned.append(p)
            
    return cleaned

# Geographical North to South order for Chile's 16 regions
CHILE_NORTH_TO_SOUTH_ORDER = [
    'arica y parinacota', 'tarapaca', 'antofagasta', 'atacama',
    'coquimbo', 'valparaiso', 'metropolitana', 'higgins',
    'maule', 'nuble', 'biobio', 'araucania',
    'rios', 'lagos', 'aysen', 'magallanes'
]

def region_north_south_key(region_name):
    clean = unicodedata.normalize('NFD', str(region_name)).encode('ascii', 'ignore').decode('utf-8').lower()
    for idx, key in enumerate(CHILE_NORTH_TO_SOUTH_ORDER):
        if key in clean:
            return idx
    return 999

def load_filter_options():
    conn = get_db_connection()
    rows = conn.execute("SELECT DISTINCT region_geografica FROM contracts WHERE region_geografica IS NOT NULL AND region_geografica != ''").fetchall()
    all_regions = set()
    for r in rows:
        for reg in parse_regions_from_row(r['region_geografica']):
            all_regions.add(reg)
    unique_regions = sorted(list(all_regions), key=region_north_south_key)

    sec_rows = conn.execute("SELECT DISTINCT sector_proyecto FROM contracts WHERE sector_proyecto IS NOT NULL AND sector_proyecto != ''").fetchall()
    unique_sectors = sorted([r['sector_proyecto'] for r in sec_rows])
    conn.close()
    return unique_regions, unique_sectors

UNIQUE_REGIONS, UNIQUE_SECTORS = load_filter_options()

@app.route('/')
def index():
    """Renders the main platform webpage dashboard"""
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    """Retrieve filtered, sorted and paginated dataset along with KPIs summary and statistics"""
    conn = get_db_connection()

    query_conditions = []
    query_params = []

    # 1. Apply Region Filter
    region_filter = request.args.get('region', '').strip()
    if region_filter:
        selected_regions = [r.strip() for r in region_filter.split(',') if r.strip()]
        if selected_regions:
            reg_conds = []
            for sel_r in selected_regions:
                reg_conds.append("region_geografica LIKE ?")
                query_params.append(f"%{sel_r}%")
            query_conditions.append(f"({' OR '.join(reg_conds)})")

    # 2. Apply Sector Filter
    sector_filter = request.args.get('sector', '').strip()
    if sector_filter:
        selected_sectors = [s.strip() for s in sector_filter.split(',') if s.strip()]
        if selected_sectors:
            placeholders = ','.join(['?'] * len(selected_sectors))
            query_conditions.append(f"sector_proyecto IN ({placeholders})")
            query_params.extend(selected_sectors)

    # 3. Apply Text Search Filter
    search_query = request.args.get('search', '').strip()
    if search_query:
        norm_q = unicodedata.normalize('NFD', search_query)
        clean_q = ''.join(c for c in norm_q if unicodedata.category(c) != 'Mn').lower()
        query_conditions.append("search_index LIKE ?")
        query_params.append(f"%{clean_q}%")

    where_clause = " WHERE " + " AND ".join(query_conditions) if query_conditions else ""

    # Total database row count
    total_db_count = conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]

    # Filtered rows query
    all_filtered_rows = conn.execute(f"SELECT * FROM contracts {where_clause}", query_params).fetchall()
    count_filtered = len(all_filtered_rows)

    # Calculate Summaries and KPIs
    total_inv_uf = float(sum(r['inversion_estimada'] or 0.0 for r in all_filtered_rows))
    
    total_bidders = 0
    hitos_status = {
        'operación': 0,
        'construcción': 0,
        'comb_const_oper': 0,
        'finalizado': 0,
        'activos': 0
    }
    sector_stats = {}
    status_stats = {}

    map_projects = []

    for r in all_filtered_rows:
        # Bidders count
        bidders_list = json.loads(r['bidders_json']) if r['bidders_json'] else []
        total_bidders += len(bidders_list)

        # Status counts
        st = r['estado']
        if st:
            status_stats[st] = status_stats.get(st, 0) + 1
            if st == 'Operación':
                hitos_status['operación'] += 1
                hitos_status['activos'] += 1
            elif st == 'Construcción':
                hitos_status['construcción'] += 1
            elif st == 'Construcción y Operación':
                hitos_status['comb_const_oper'] += 1
                hitos_status['activos'] += 1
            elif st == 'Finalizado':
                hitos_status['finalizado'] += 1

        # Sector counts
        sec = r['sector_proyecto']
        if sec:
            sector_stats[sec] = sector_stats.get(sec, 0) + 1

        # Map project payload
        data_obj = json.loads(r['data_json'])
        map_projects.append({
            'code': r['codigo_proyecto'],
            'name': data_obj.get('Nombre de uso común') or data_obj.get('Nombre de la Concesión '),
            'common': data_obj.get('Nombre de uso común'),
            'region': data_obj.get('Región geográfica'),
            'status': data_obj.get('ESTADO'),
            'sector': data_obj.get('Sector del proyecto'),
            'shapes': json.loads(r['shapes_json']) if r['shapes_json'] else [],
            'group_timeline': json.loads(r['group_timeline_json']) if r['group_timeline_json'] else []
        })

    # Sorting
    sort_by = request.args.get('sort_by', 'Fecha inicio del contrato de concesión')
    sort_order = request.args.get('sort_order', 'asc')

    def row_sort_key(r):
        data_obj = json.loads(r['data_json'])
        val = data_obj.get(sort_by)
        if val is None:
            return 'zzzzzz'
        return str(val)

    all_filtered_rows.sort(key=row_sort_key, reverse=(sort_order == 'desc'))

    # Pagination
    page_size_param = request.args.get('page_size', '').strip()
    if page_size_param and page_size_param.isdigit() and int(page_size_param) > 0:
        page_size = int(page_size_param)
        try:
            page = int(request.args.get('page', 1))
        except ValueError:
            page = 1
        total_pages = max(1, (count_filtered + page_size - 1) // page_size)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_rows = all_filtered_rows[start_idx:end_idx]
    else:
        page = 1
        page_size = count_filtered if count_filtered > 0 else 1
        total_pages = 1
        paginated_rows = all_filtered_rows

    serialized_data = [json.loads(r['data_json']) for r in paginated_rows]

    conn.close()

    return jsonify({
        'data': serialized_data,
        'regions': UNIQUE_REGIONS,
        'sectors': UNIQUE_SECTORS,
        'stats': {
            'sectors': sector_stats,
            'status': status_stats
        },
        'summary': {
            'count_filtered': count_filtered,
            'count_total': total_db_count,
            'total_investment_uf': total_inv_uf,
            'total_bidders': total_bidders,
            'hitos': hitos_status
        },
        'pagination': {
            'page': page,
            'page_size': page_size,
            'total_records': count_filtered,
            'total_pages': total_pages
        },
        'map_projects': map_projects
    })

@app.route('/api/project/<path:code_id>')
def get_project_detail(code_id):
    """Retrieve full detail payload on-demand for a single project code"""
    clean_code = str(code_id).strip()
    conn = get_db_connection()
    row = conn.execute("SELECT data_json FROM contracts WHERE codigo_proyecto = ?", (clean_code,)).fetchone()
    conn.close()
    
    if not row:
        return jsonify({'error': 'Proyecto no encontrado'}), 404
        
    return jsonify(json.loads(row['data_json']))

# API Routes for Map GeoJSON Layering
MAPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Mapas vectoriales', 'JSONS')
if not os.path.exists(MAPS_DIR):
    MAPS_DIR = os.path.join('Mapas vectoriales', 'JSONS')

DGC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Mapas vectoriales', 'DGC')
if not os.path.exists(DGC_DIR):
    DGC_DIR = os.path.join('Mapas vectoriales', 'DGC')

def _load_layer(filename, is_js_wrapped=False):
    path = os.path.join(MAPS_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    if is_js_wrapped:
        idx = content.find('{')
        if idx != -1:
            content = content[idx:].rstrip(';').strip()
    return json.loads(content)

# Pre-load and cache consolidated DGC layer
DGC_DATA = {"type": "FeatureCollection", "features": []}
DGC_SECTORS = {
    'Aeropuertos': [],
    'Hospitales': [],
    'Rutas': [],
    'Diversos': []
}

dgc_filenames = ['DGC_point.json', 'DGC_line.json', 'DGC_polygon.json']
for fname in dgc_filenames:
    fpath = os.path.join(DGC_DIR, fname)
    if os.path.exists(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                raw_json = json.load(f)
                features = raw_json.get('features', [])
                DGC_DATA['features'].extend(features)
        except Exception as e:
            print(f"Error loading {fname} on startup: {e}")
    else:
        print(f"Warning: {fpath} does not exist")

# Populate DGC_SECTORS caches
for feat in DGC_DATA.get('features', []):
    sec = feat.get('properties', {}).get('Sector_DGC', 'Diversos')
    if sec in DGC_SECTORS:
        DGC_SECTORS[sec].append(feat)
    else:
        DGC_SECTORS['Diversos'].append(feat)

def _make_collection(features):
    return {
        "type": "FeatureCollection",
        "features": features
    }

@app.route('/api/map/regions')
def get_map_regions():
    return jsonify(_load_layer('Regional_simplified.json', is_js_wrapped=False))

@app.route('/api/map/dgc')
def get_map_dgc():
    return jsonify(DGC_DATA)

@app.route('/api/map/airports')
def get_map_airports():
    return jsonify(_make_collection(DGC_SECTORS['Aeropuertos']))

@app.route('/api/map/hospitals')
def get_map_hospitals():
    return jsonify(_make_collection(DGC_SECTORS['Hospitales']))

@app.route('/api/map/roads')
def get_map_roads():
    return jsonify(_make_collection(DGC_SECTORS['Rutas']))

@app.route('/api/map/misc')
def get_map_misc():
    return jsonify(_make_collection(DGC_SECTORS['Diversos']))

if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "True") == "True",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000))
    )