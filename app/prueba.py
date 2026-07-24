import os
import re
import datetime
import json
import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

# Locate Excel file in workspace directory
EXCEL_PATH = 'CALTEC.xlsx'
if not os.path.exists(EXCEL_PATH):
    # Try locating it relative to script's directory (app/../CALTEC.xlsx)
    EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'CALTEC.xlsx')

if not os.path.exists(EXCEL_PATH):
    raise FileNotFoundError(f"No se encontró el archivo de datos en: {EXCEL_PATH}")

# Load Excel worksheet into memory
# Since the layout of excel.ipynb uses sheet_name='BD', we load that sheet
df_contracts = pd.read_excel(EXCEL_PATH, sheet_name='BD')

import unicodedata

def _normalize_col(s):
    s = str(s).lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

# Load bidders sheet 'OF' and organize bidders by project code
BIDDERS_BY_PROJECT = {}
try:
    df_of = pd.read_excel(EXCEL_PATH, sheet_name='OF')
    
    col_proj = None
    col_cod_of = None
    col_nom_of = None
    col_adj = None
    
    for col in df_of.columns:
        c_norm = _normalize_col(col)
        if 'codigo' in c_norm and 'proyecto' in c_norm:
            col_proj = col
        elif 'codigo' in c_norm and 'oferente' in c_norm:
            col_cod_of = col
        elif 'nombre' in c_norm and 'oferente' in c_norm:
            col_nom_of = col
        elif 'adjudicad' in c_norm:
            col_adj = col
            
    if col_proj:
        for _, row in df_of.iterrows():
            p_code = str(row[col_proj]).strip() if pd.notna(row[col_proj]) else ''
            if not p_code:
                continue
            
            b_code = str(row[col_cod_of]).strip() if col_cod_of and pd.notna(row[col_cod_of]) else ''
            b_name = str(row[col_nom_of]).strip() if col_nom_of and pd.notna(row[col_nom_of]) else ''
            adj_val = str(row[col_adj]).strip() if col_adj and pd.notna(row[col_adj]) else ''
            is_adj = adj_val.upper() in ['SI', 'SÍ', 'YES', 'TRUE', '1']
            
            BIDDERS_BY_PROJECT.setdefault(p_code, []).append({
                'code': b_code,
                'name': b_name,
                'adjudicado': is_adj,
                'adjudicado_raw': adj_val
            })
except Exception as e:
    print(f"Error cargando hoja 'OF' de oferentes: {e}")


# Helper: Standardize region splitting and naming convention (Chile 16 Regions)
def parse_regions_from_row(region_str):
    if pd.isna(region_str) or not isinstance(region_str, str):
        return []
    
    # Replace non-breaking HTML space and double spaces
    region_str = region_str.replace('&nbsp;', ' ').replace('\xa0', ' ')
    
    # Split by semicolon or comma
    parts = re.split(r'[;,]', region_str)
    cleaned = []
    
    for p in parts:
        p = p.strip()
        if not p:
            continue
        
        # Standardize region naming duplicates
        if p == 'Metropolitana':
            p = 'Metropolitana de Santiago'
        elif p in ('Araucanía', 'Araucanía '):
            p = 'La Araucanía'
            
        if p not in cleaned:
            cleaned.append(p)
            
    return cleaned

def parse_shapes_list(val):
    if pd.isna(val):
        return []
    if isinstance(val, (int, np.integer)):
        return [str(val)]
    if isinstance(val, (float, np.floating)):
        if val.is_integer():
            return [str(int(val))]
        # split by decimal point
        val_str = str(val)
        return [p for p in val_str.split('.') if p.strip()]
    if isinstance(val, str):
        cleaned_str = val.replace(';', ',').replace('.', ',')
        return [p.strip() for p in cleaned_str.split(',') if p.strip()]
    return []

def get_row_shapes_val(row_dict):
    for k, v in row_dict.items():
        if k.strip().lower() == 'shapes':
            return v
    return None

def get_row_tender_date(row_dict):
    for k, v in row_dict.items():
        if 'llamado' in k.lower() and 'licita' in k.lower():
            return sanitize_value(v)
    return None

# Pre-calculate listing filters options
ALL_REGIONS = set()
for cell in df_contracts['Región geográfica'].dropna():
    for region_name in parse_regions_from_row(cell):
        ALL_REGIONS.add(region_name)

# Geographical North to South order for Chile's 16 regions
CHILE_NORTH_TO_SOUTH_ORDER = [
    'arica y parinacota', 'tarapaca', 'antofagasta', 'atacama',
    'coquimbo', 'valparaiso', 'metropolitana', 'higgins',
    'maule', 'nuble', 'biobio', 'araucania',
    'rios', 'lagos', 'aysen', 'magallanes'
]

import unicodedata
def region_north_south_key(region_name):
    clean = unicodedata.normalize('NFD', str(region_name)).encode('ascii', 'ignore').decode('utf-8').lower()
    for idx, key in enumerate(CHILE_NORTH_TO_SOUTH_ORDER):
        if key in clean:
            return idx
    return 999

UNIQUE_REGIONS = sorted(list(ALL_REGIONS), key=region_north_south_key)
UNIQUE_SECTORS = sorted([str(s) for s in df_contracts['Sector del proyecto'].dropna().unique().tolist()])

# El mapeo de coordenadas fijas fue eliminado para ser reemplazado por capas GeoJSON dinámicas.



def sanitize_value(v):
    """Sanitizes raw values (handles NaN, Infinite values, NaT and datetime objects for json outputs)"""
    if pd.isna(v):
        return None
    if hasattr(v, 'strftime'):
        return v.strftime('%Y-%m-%d')
    if isinstance(v, (np.integer, np.floating)):
        if np.isnan(v) or np.isinf(v):
            return None
        return v.item()
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return v

# Pre-calculate Concession Grouping Timelines for easy frontend rendering
BASE_GROUPS = {}
for idx, row in df_contracts.iterrows():
    code = str(row['Código proyecto'])
    # Matches prefix + base + sequence: e.g. 067_CHCO1 (base CHCO, seq 1) or 115_CHCO2 (base CHCO, seq 2)
    m = re.search(r'^\d+_(.+)(\d)$', code)
    if m:
        base_code = m.group(1)
        seq = int(m.group(2))
    else:
        # Fallback for codes without standard numeric prefix
        m_simple = re.search(r'^(.+)(\d)$', code)
        if m_simple:
            base_code = m_simple.group(1)
            seq = int(m_simple.group(2))
        else:
            base_code = code
            seq = 1

    BASE_GROUPS.setdefault(base_code, []).append({
        'code': code,
        'seq': seq,
        'name': sanitize_value(row.get('Nombre de uso común')) or sanitize_value(row.get('Nombre de la Concesión ')),
        'status': sanitize_value(row['ESTADO']),
        'resolution_date': sanitize_value(row['Fecha resolución declaración interes público']),
        'adjudication_date': sanitize_value(row['Fecha decreto adjudicación']),
        'start_date': sanitize_value(row['Fecha inicio del contrato de concesión']),
        'end_date': sanitize_value(row['Fecha término de la concesión']),
        'investment': sanitize_value(row['Inversión Materializada estimada']),
        'progress': sanitize_value(row['% Avance obras físicas'])
    })

# Arrange concessions in chronological order by sequence ID
for base_code in BASE_GROUPS:
    BASE_GROUPS[base_code] = sorted(BASE_GROUPS[base_code], key=lambda x: x['seq'])


@app.route('/')
def index():
    """Renders the main platform webpage dashboard"""
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    """Retrieve filtered, sorted and paginated dataset along with KPIs summary and statistics"""
    filtered_df = df_contracts.copy()

    # 1. Apply Region Filter (supports single or multiple comma-separated regions)
    region_filter = request.args.get('region', '').strip()
    if region_filter:
        selected_regions = [r.strip() for r in region_filter.split(',') if r.strip()]
        if selected_regions:
            mask = filtered_df['Región geográfica'].apply(
                lambda x: any(sel_r in parse_regions_from_row(x) for sel_r in selected_regions)
            )
            filtered_df = filtered_df[mask]

    # 2. Apply Sector Filter (supports single or multiple comma-separated sectors)
    sector_filter = request.args.get('sector', '').strip()
    if sector_filter:
        selected_sectors = [s.strip() for s in sector_filter.split(',') if s.strip()]
        if selected_sectors:
            filtered_df = filtered_df[filtered_df['Sector del proyecto'].isin(selected_sectors)]

    # 3. Apply Full Text Search
    search_query = request.args.get('search', '').strip().lower()
    if search_query:
        def matches_search(row):
            proj_code = str(row['Código proyecto'] or '')
            bidders = BIDDERS_BY_PROJECT.get(proj_code, [])
            bidders_text = ' '.join([f"{b['name']} {b['code']}" for b in bidders])
            search_fields = [
                proj_code,
                str(row['Nombre de la Concesión '] or ''),
                str(row['Nombre de uso común'] or ''),
                str(row['Descripción '] or ''),
                str(row['Nombre sociedad concesionaria'] or ''),
                bidders_text
            ]
            return any(search_query in field.lower() for field in search_fields)
        
        mask = filtered_df.apply(matches_search, axis=1)
        filtered_df = filtered_df[mask]

    # 4. Save Filtered Stats before paging
    count_filtered = len(filtered_df)
    total_inv_uf = float(filtered_df['Inversión Materializada estimada'].dropna().sum())
    total_bidders = int(sum(len(BIDDERS_BY_PROJECT.get(str(row['Código proyecto'] or '').strip(), [])) for _, row in filtered_df.iterrows()))
    
    # Calculate Hitos counters
    hitos_status = {
        'operación': int((filtered_df['ESTADO'] == 'Operación').sum()),
        'construcción': int((filtered_df['ESTADO'] == 'Construcción').sum()),
        'comb_const_oper': int((filtered_df['ESTADO'] == 'Construcción y Operación').sum()),
        'finalizado': int((filtered_df['ESTADO'] == 'Finalizado').sum()),
        'activos': int(((filtered_df['ESTADO'] == 'Operación') | (filtered_df['ESTADO'] == 'Construcción y Operación')).sum())
    }

    # Format chart aggregates counts
    sector_stats = filtered_df['Sector del proyecto'].value_counts().to_dict()
    status_stats = filtered_df['ESTADO'].value_counts().to_dict()

    # 5. Apply Sorter Order
    sort_by = request.args.get('sort_by', 'Código proyecto')
    sort_order = request.args.get('sort_order', 'asc')
    
    if sort_by in filtered_df.columns:
        ascending = (sort_order == 'asc')
        filtered_df = filtered_df.sort_values(by=sort_by, ascending=ascending, na_position='last')

    # 6. Apply Paging limits
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
        paginated_df = filtered_df.iloc[start_idx:end_idx]
    else:
        page = 1
        page_size = count_filtered if count_filtered > 0 else 1
        total_pages = 1
        paginated_df = filtered_df

    # 7. Convert paginated results to sanitized dicts
    serialized_data = []
    for _, row in paginated_df.iterrows():
        row_dict = row.to_dict()
        sanitized = {k: sanitize_value(v) for k, v in row_dict.items()}
        
        # Inject grouped timeline concessions
        code = sanitized['Código proyecto']
        m = re.search(r'^\d+_(.+)(\d)$', code)
        if m:
            base_code = m.group(1)
        else:
            m_simple = re.search(r'^(.+)(\d)$', code)
            base_code = m_simple.group(1) if m_simple else code
            
        sanitized['group_timeline'] = BASE_GROUPS.get(base_code, [])
        sanitized['shapes'] = parse_shapes_list(get_row_shapes_val(row_dict))
        sanitized['bidders'] = BIDDERS_BY_PROJECT.get(code, [])
        serialized_data.append(sanitized)

    # 7.1 Extract map projects (filtered active matching concessions)
    map_projects = []
    for _, row in filtered_df.iterrows():
        row_dict = row.to_dict()
        sanitized = {k: sanitize_value(v) for k, v in row_dict.items()}
        p_code = sanitized['Código proyecto']
        map_projects.append({
            'code': p_code,
            'name': sanitized.get('Nombre de uso común') or sanitized.get('Nombre de la Concesión '),
            'common': sanitized.get('Nombre de uso común'),
            'region': sanitized['Región geográfica'],
            'status': sanitized['ESTADO'],
            'investment': sanitized['Inversión Materializada estimada'],
            'sector': sanitized['Sector del proyecto'],
            'shapes': parse_shapes_list(get_row_shapes_val(row_dict)),
            'tender_date': get_row_tender_date(row_dict),
            'bidders': BIDDERS_BY_PROJECT.get(p_code, [])
        })

    # 8. Shape final JSON structure response
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
            'count_total': len(df_contracts),
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