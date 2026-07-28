import os
import re
import json
import sqlite3
import unicodedata
import numpy as np
import pandas as pd

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXCEL_PATH = os.path.join(BASE_DIR, '..', 'CALTEC.xlsx')
if not os.path.exists(EXCEL_PATH):
    EXCEL_PATH = os.path.join(BASE_DIR, 'CALTEC.xlsx')

DB_PATH = os.path.join(BASE_DIR, 'caltec.db')

def _normalize_col(s):
    s = str(s).lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def sanitize_value(v):
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

def parse_shapes_list(val):
    if pd.isna(val):
        return []
    if isinstance(val, (int, np.integer)):
        return [str(val)]
    if isinstance(val, (float, np.floating)):
        if val.is_integer():
            return [str(int(val))]
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

def migrate():
    print(f"Leyendo Excel desde: {EXCEL_PATH}")
    if not os.path.exists(EXCEL_PATH):
        raise FileNotFoundError(f"No se encontró el archivo {EXCEL_PATH}")

    df_contracts = pd.read_excel(EXCEL_PATH, sheet_name='BD')
    
    # Oferentes
    BIDDERS_BY_PROJECT = {}
    try:
        df_of = pd.read_excel(EXCEL_PATH, sheet_name='OF')
        col_proj = col_cod_of = col_nom_of = col_adj = None
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
        print(f"Advertencia al leer hoja OF: {e}")

    # Build Search Index
    def _build_row_search_index(row):
        proj_code = str(row.get('Código proyecto') or '')
        bidders = BIDDERS_BY_PROJECT.get(proj_code.strip(), [])
        bidders_text = ' '.join([f"{b.get('name', '')} {b.get('code', '')}" for b in bidders])
        fields = [
            proj_code,
            str(row.get('Nombre de la Concesión ') or ''),
            str(row.get('Nombre de uso común') or ''),
            str(row.get('Descripción ') or ''),
            str(row.get('Nombre sociedad concesionaria') or ''),
            str(row.get('Región geográfica') or ''),
            str(row.get('Sector del proyecto') or ''),
            bidders_text
        ]
        combined = ' '.join(fields)
        norm = unicodedata.normalize('NFD', combined)
        return ''.join(c for c in norm if unicodedata.category(c) != 'Mn').lower()

    df_contracts['_search_index'] = df_contracts.apply(_build_row_search_index, axis=1)

    # Base Groups
    BASE_GROUPS = {}
    for idx, row in df_contracts.iterrows():
        code = str(row['Código proyecto'])
        m = re.search(r'^\d+_(.+)(\d)$', code)
        if m:
            base_code = m.group(1)
            seq = int(m.group(2))
        else:
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
            'name': sanitize_value(row.get('Nombre de la Concesión ')) or sanitize_value(row.get('Nombre de uso común')),
            'concession_name': sanitize_value(row.get('Nombre de la Concesión ')),
            'common_name': sanitize_value(row.get('Nombre de uso común')),
            'status': sanitize_value(row['ESTADO']),
            'resolution_date': sanitize_value(row['Fecha resolución declaración interes público']),
            'adjudication_date': sanitize_value(row['Fecha decreto adjudicación']),
            'start_date': sanitize_value(row['Fecha inicio del contrato de concesión']),
            'end_date': sanitize_value(row['Fecha término de la concesión']),
            'investment': sanitize_value(row['Inversión Materializada estimada']),
            'progress': sanitize_value(row['% Avance obras físicas'])
        })

    for base_code in BASE_GROUPS:
        BASE_GROUPS[base_code] = sorted(BASE_GROUPS[base_code], key=lambda x: x['seq'])

    # Connect to SQLite
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create Tables
    cursor.execute('''
    CREATE TABLE contracts (
        codigo_proyecto TEXT PRIMARY KEY,
        base_code TEXT,
        search_index TEXT,
        region_geografica TEXT,
        sector_proyecto TEXT,
        estado TEXT,
        inversion_estimada REAL,
        fecha_inicio TEXT,
        shapes_json TEXT,
        bidders_json TEXT,
        group_timeline_json TEXT,
        data_json TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE bidders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_proyecto TEXT,
        code TEXT,
        name TEXT,
        adjudicado INTEGER,
        adjudicado_raw TEXT
    )
    ''')

    # Indexes for fast filtering
    cursor.execute('CREATE INDEX idx_region ON contracts(region_geografica)')
    cursor.execute('CREATE INDEX idx_sector ON contracts(sector_proyecto)')
    cursor.execute('CREATE INDEX idx_estado ON contracts(estado)')
    cursor.execute('CREATE INDEX idx_search ON contracts(search_index)')
    cursor.execute('CREATE INDEX idx_base ON contracts(base_code)')
    cursor.execute('CREATE INDEX idx_bidders_proj ON bidders(codigo_proyecto)')

    # Insert Data
    for _, row in df_contracts.iterrows():
        row_dict = row.to_dict()
        sanitized = {k: sanitize_value(v) for k, v in row_dict.items()}
        code = str(sanitized['Código proyecto'])

        m = re.search(r'^\d+_(.+)(\d)$', code)
        if m:
            base_code = m.group(1)
        else:
            m_simple = re.search(r'^(.+)(\d)$', code)
            base_code = m_simple.group(1) if m_simple else code

        shapes = parse_shapes_list(get_row_shapes_val(row_dict))
        bidders = BIDDERS_BY_PROJECT.get(code, [])
        timeline = BASE_GROUPS.get(base_code, [])

        sanitized['group_timeline'] = timeline
        sanitized['shapes'] = shapes
        sanitized['bidders'] = bidders

        search_idx = row.get('_search_index', '')
        region = str(sanitized.get('Región geográfica') or '')
        sector = str(sanitized.get('Sector del proyecto') or '')
        estado = str(sanitized.get('ESTADO') or '')
        inv = sanitized.get('Inversión Materializada estimada')
        inv_val = float(inv) if inv is not None and isinstance(inv, (int, float)) else 0.0
        fecha_ini = str(sanitized.get('Fecha inicio del contrato de concesión') or '')

        cursor.execute('''
        INSERT INTO contracts (
            codigo_proyecto, base_code, search_index, region_geografica,
            sector_proyecto, estado, inversion_estimada, fecha_inicio,
            shapes_json, bidders_json, group_timeline_json, data_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            code, base_code, search_idx, region,
            sector, estado, inv_val, fecha_ini,
            json.dumps(shapes), json.dumps(bidders), json.dumps(timeline), json.dumps(sanitized)
        ))

        # Insert Bidders
        for b in bidders:
            cursor.execute('''
            INSERT INTO bidders (codigo_proyecto, code, name, adjudicado, adjudicado_raw)
            VALUES (?, ?, ?, ?, ?)
            ''', (code, b.get('code', ''), b.get('name', ''), 1 if b.get('adjudicado') else 0, b.get('adjudicado_raw', '')))

    conn.commit()
    conn.close()
    print(f"¡Migración exitosa! Base de datos SQLite creada en: {DB_PATH}")

if __name__ == '__main__':
    migrate()
