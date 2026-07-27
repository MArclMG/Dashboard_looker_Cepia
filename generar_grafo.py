import os
import re
import unicodedata
import pandas as pd
import gspread
import google.auth
from google.auth.transport.requests import Request
from pyvis.network import Network

def normalizar_texto(val):
    if pd.isna(val) or val is None:
        return ""
    texto = str(val).strip()
    if texto.lower() == "nan" or not texto:
        return ""
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn').upper()
    texto = re.sub(r'\b(LIMITADA\.|LIMITADA|LTDA\.|LTDA)\b', 'LTDA', texto)
    texto = re.sub(r'\b(S\.A\.|S\.A)\b', 'SA', texto)
    texto = re.sub(r'\b(S\.P\.A\.|S\.P\.A|SPA\.)\b', 'SPA', texto)
    texto = re.sub(r'\.', '', texto)
    return " ".join(texto.split())

def acortar_texto(texto, max_len=14):
    if len(texto) > max_len:
        return texto[:max_len] + "..."
    return texto

def main():
    print("➡️ Autenticando en GCP mediante Workload Identity Federation...")
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets", 
        "https://www.googleapis.com/auth/drive"
    ]
    
    credentials, project = google.auth.default(scopes=SCOPES)
    if not credentials.valid: 
        credentials.refresh(Request())
        
    gc = gspread.authorize(credentials)

    spreadsheet_url = os.environ.get("SPREADSHEET_URL")
    print("➡️ Conectando a Google Sheets...")
    sh = gc.open_by_url(spreadsheet_url)
    sheet = sh.sheet1 
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    print("➡️ Procesando datos e indexando número de endosos por bono...")
    
    bonos_set = set()
    endosatarios_set = set()
    beneficiarios_set = set()
    max_endosos_encontrados = 0
    in_degree_counter = {}

    for _, row in df.iterrows():
        cepia_id = normalizar_texto(row.get('N° Cepia', ''))
        beneficiario_id = normalizar_texto(row.get('Beneficiario', ''))
        if not cepia_id: 
            continue

        bonos_set.add(cepia_id)
        if beneficiario_id:
            beneficiarios_set.add(beneficiario_id)

        i_temp = 1
        num_endosos_bono = 0
        while True:
            col_check = next((c for c in df.columns if c.strip().lower() == f'endosatario_{i_temp}'), None)
            if not col_check:
                break
            val_endo = normalizar_texto(row.get(col_check, ''))
            if val_endo:
                num_endosos_bono += 1
                endosatarios_set.add(val_endo)
                in_degree_counter[val_endo] = in_degree_counter.get(val_endo, 0) + 1
            i_temp += 1

        if num_endosos_bono > max_endosos_encontrados:
            max_endosos_encontrados = num_endosos_bono

    net = Network(
        height="100vh", 
        width="100%", 
        directed=True, 
        notebook=False, 
        bgcolor="#FAFAFA", 
        font_color="#2B2B2B"
    )
    
    net.set_options("""
    {
      "interaction": {
        "hover": true,
        "dragNodes": true,
        "dragView": true,
        "selectable": true,
        "multiselect": false,
        "zoomView": true
      },
      "physics": {
        "enabled": true,
        "barnesHut": {
          "gravitationalConstant": -8000,
          "centralGravity": 0.05,
          "springLength": 220,
          "springConstant": 0.04,
          "damping": 0.2,
          "avoidOverlap": 1
        },
        "maxVelocity": 50,
        "minVelocity": 0.5,
        "solver": "barnesHut",
        "stabilization": {
          "enabled": true,
          "iterations": 1000,
          "updateInterval": 25,
          "onlyDynamicEdges": false,
          "fit": true
        }
      }
    }
    """)

    for idx, row in df.iterrows():
        cepia_id = normalizar_texto(row.get('N° Cepia', ''))
        beneficiario_id = normalizar_texto(row.get('Beneficiario', ''))
        if not cepia_id: 
            continue

        i_temp = 1
        num_endosos_bono = 0
        list_endosatarios = []
        list_fechas = []

        while True:
            col_endosatario = next((c for c in df.columns if c.strip().lower() == f'endosatario_{i_temp}'), None)
            col_fecha = next((c for c in df.columns if c.strip().lower() == f'endoso_fecha_{i_temp}'), None)

            if not col_endosatario:
                break

            val_endo = normalizar_texto(row.get(col_endosatario, ''))
            fecha_val = str(row.get(col_fecha, '')).strip() if col_fecha else ""

            if val_endo:
                num_endosos_bono += 1
                list_endosatarios.append(val_endo)
                list_fechas.append(fecha_val)
            i_temp += 1

        title_bono = f"<b>BONO (N° CEPIA):</b> {cepia_id}<br><b>Endosos Total:</b> {num_endosos_bono}<br><b>Beneficiario Final:</b> {beneficiario_id}"

        net.add_node(
            cepia_id, 
            label=f"Bono:\n{cepia_id}", 
            title=title_bono, 
            group="bono",
            shape="dot",
            cantEndosos=num_endosos_bono,
            size=20,
            font={"size": 11, "face": "Arial", "bold": True}
        )

        if beneficiario_id:
            label_benef = acortar_texto(beneficiario_id, 12)
            title_benef = f"<b>BENEFICIARIO COMPLETO:</b><br>{beneficiario_id}"
            net.add_node(
                beneficiario_id, 
                label=label_benef, 
                title=title_benef, 
                group="beneficiario",
                shape="dot",
                size=14,
                font={"size": 9, "face": "Arial"}
            )

        for endosatario_id in list_endosatarios:
            label_endo = acortar_texto(endosatario_id, 14)
            endosos_recibidos = in_degree_counter.get(endosatario_id, 1)
            size_dinamico = min(12 + (endosos_recibidos * 2), 26)
            title_endo = f"<b>ENDOSATARIO:</b> {endosatario_id}<br><b>Endosos Recibidos:</b> {endosos_recibidos}"

            net.add_node(
                endosatario_id, 
                label=label_endo, 
                title=title_endo, 
                group="endosatario",
                shape="box",
                size=size_dinamico,
                widthConstraint={"maximum": 120},
                font={"size": 9, "face": "Arial"}
            )

        # --- ESTRUCTURA 1: CRONOLÓGICA (Bono -> Endosatarios -> Beneficiario) ---
        nodo_actual_c = cepia_id
        for i, endosatario_id in enumerate(list_endosatarios, 1):
            fecha_val = list_fechas[i-1]
            label_arista = f"E{i}: {fecha_val}" if fecha_val else f"Endoso {i}"
            
            net.add_edge(
                nodo_actual_c, 
                endosatario_id, 
                label=label_arista, 
                title=f"Bono: {cepia_id} | Fecha: {fecha_val}",
                width=1.5,
                bono=cepia_id,
                cantEndosos=num_endosos_bono,
                flowMode="cronologico",
                arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                smooth={"type": "curvedCW", "roundness": 0.25},
                font={"size": 8, "align": "middle", "color": "#777777"}
            )
            nodo_actual_c = endosatario_id

        if beneficiario_id:
            net.add_edge(
                nodo_actual_c, 
                beneficiario_id, 
                label="Asignado a", 
                title=f"Bono: {cepia_id} | Beneficiario Final", 
                width=1.5,
                dashes=True,
                bono=cepia_id,
                cantEndosos=num_endosos_bono,
                flowMode="cronologico",
                arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                smooth={"type": "curvedCW", "roundness": 0.2},
                font={"size": 8, "align": "middle", "color": "#777777"}
            )

        # --- ESTRUCTURA 2: SEGÚN TABLA (Bono -> Beneficiario -> Endosatarios) ---
        if beneficiario_id:
            net.add_edge(
                cepia_id, 
                beneficiario_id, 
                label="Adjudicado a", 
                title=f"Bono: {cepia_id} | Titular Beneficiario", 
                width=1.5,
                dashes=True,
                bono=cepia_id,
                cantEndosos=num_endosos_bono,
                flowMode="tabla",
                arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                smooth={"type": "curvedCW", "roundness": 0.2},
                font={"size": 8, "align": "middle", "color": "#777777"}
            )
            nodo_actual_t = beneficiario_id
        else:
            nodo_actual_t = cepia_id

        for i, endosatario_id in enumerate(list_endosatarios, 1):
            fecha_val = list_fechas[i-1]
            label_arista = f"E{i}: {fecha_val}" if fecha_val else f"Endoso {i}"
            
            net.add_edge(
                nodo_actual_t, 
                endosatario_id, 
                label=label_arista, 
                title=f"Bono: {cepia_id} | Fecha: {fecha_val}",
                width=1.5,
                bono=cepia_id,
                cantEndosos=num_endosos_bono,
                flowMode="tabla",
                arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                smooth={"type": "curvedCW", "roundness": 0.25},
                font={"size": 8, "align": "middle", "color": "#777777"}
            )
            nodo_actual_t = endosatario_id

    os.makedirs("docs", exist_ok=True)
    output_path = os.path.join("docs", "index.html")
    net.write_html(output_path)

    inyectar_panel_filtros(output_path, bonos_set, endosatarios_set, beneficiarios_set, max_endosos_encontrados)
    print(f"✅ Grafo actualizado exitosamente en: {output_path}")


def inyectar_panel_filtros(html_path, bonos, endosatarios, beneficiarios, max_endosos):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    meta_cache = """
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
    <meta http-equiv="Pragma" content="no-cache" />
    <meta http-equiv="Expires" content="0" />
    """
    content = content.replace("<head>", f"<head>\n{meta_cache}")

    opts_num_endosos = '<option value="ALL">Todos</option>'
    for k in range(0, max_endosos + 1):
        opts_num_endosos += f'<option value="{k}">{k} endoso{"s" if k != 1 else ""}</option>'

    panel_html = f"""
    <style>
        body, html {{
            margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden;
            font-family: Arial, sans-serif;
        }}
        #mynetwork {{
            width: 100%;
            height: 100vh;
        }}
        #filter-panel {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            padding: 10px 14px;
            border-radius: 8px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.25);
            font-size: 13px;
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
            max-width: 95%;
            transition: all 0.3s ease;
        }}
        #filter-panel label {{
            font-weight: bold;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        
        .filter-group-box {{
            border: 1px solid rgba(150, 150, 150, 0.4);
            border-radius: 6px;
            padding: 4px 8px 6px 8px;
            margin: 0;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .filter-group-box legend {{
            font-size: 11px;
            font-weight: bold;
            padding: 0 4px;
            opacity: 0.85;
        }}

        .header-sort-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .sort-btn-group {{
            display: flex;
            gap: 2px;
            background: rgba(0,0,0,0.1);
            padding: 2px;
            border-radius: 4px;
        }}
        .sort-btn {{
            font-size: 10px !important;
            padding: 2px 5px !important;
            border: none !important;
            background: transparent !important;
            cursor: pointer;
            opacity: 0.6;
            border-radius: 3px;
            margin-top: 0 !important;
        }}
        .sort-btn.active {{
            opacity: 1.0;
            font-weight: bold;
            background: rgba(255,255,255,0.2) !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }}
        #filter-panel select, #filter-panel button {{
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 12px;
            outline: none;
            transition: all 0.2s ease;
        }}
        #filter-panel button {{
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            margin-top: 14px;
        }}

        div.vis-tooltip {{
            position: absolute !important;
            background-color: transparent !important;
            border: none !important;
            padding: 0 !important;
            z-index: 99999 !important;
            pointer-events: none;
        }}
        .custom-tooltip-card {{
            border-radius: 6px;
            padding: 10px 14px;
            box-shadow: 0 6px 20px rgba(0,0,0,0.4);
            font-size: 12px;
            line-height: 1.4;
            width: max-content;
            min-width: 190px;
            max-width: 330px;
            white-space: normal;
            overflow-wrap: break-word;
            word-break: break-word;
            opacity: 1.0 !important;
            background-color: var(--tooltip-bg, #FFFFFF) !important;
            color: var(--tooltip-text, #2B2B2B) !important;
            border: 1px solid var(--tooltip-border, #E0DAD3) !important;
            border-left: 4px solid var(--tooltip-highlight, #C65A72) !important;
        }}
    </style>

    <div id="filter-panel">
        <label>Estructura de Flujo:
            <select id="sel-flow-mode" onchange="switchFlowMode(this.value)">
                <option value="cronologico">Trazabilidad Financiera (Bono ➔ Endosos ➔ Beneficiario)</option>
                <option value="tabla">Jerarquía Administrativa (Bono ➔ Beneficiario ➔ Endosos)</option>
            </select>
        </label>

        <label>Tema:
            <select id="sel-theme" onchange="changeTheme(this.value)">
                <option value="dia1">Día · Salvia / Terracota / Crema (Pastel)</option>
                <option value="dia2">Día · Azul Acero / Teal Vivo / Mostaza</option>
                <option value="noche1">Noche · Petróleo / Pino / Ámbar</option>
                <option value="noche2">Noche · Grafito / Índigo / Cobre Vivo</option>
            </select>
        </label>

        <fieldset class="filter-group-box">
            <legend>N° Endosos</legend>
            <div style="display: flex; gap: 4px;">
                <select id="sel-op-endosos" onchange="filterByEndosos()">
                    <option value="gte">≥</option>
                    <option value="eq">=</option>
                    <option value="lte">≤</option>
                </select>
                <select id="sel-val-endosos" onchange="filterByEndosos()">
                    {opts_num_endosos}
                </select>
            </div>
        </fieldset>

        <label>
            <div class="header-sort-row">
                <span>Endosatario:</span>
                <div class="sort-btn-group">
                    <button type="button" id="btn-sort-endo-alpha" class="sort-btn active" onclick="setSortMode('endosatario', 'alpha')">A-Z</button>
                    <button type="button" id="btn-sort-endo-count" class="sort-btn" onclick="setSortMode('endosatario', 'count')">N°</button>
                </div>
            </div>
            <select id="sel-endosatario" class="searchable-select" onchange="applyIsolationFilter(this.value, 'endosatario')">
                <option value="">-- Todos --</option>
            </select>
        </label>

        <label>
            <div class="header-sort-row">
                <span>Beneficiario:</span>
                <div class="sort-btn-group">
                    <button type="button" id="btn-sort-bene-alpha" class="sort-btn active" onclick="setSortMode('beneficiario', 'alpha')">A-Z</button>
                    <button type="button" id="btn-sort-bene-count" class="sort-btn" onclick="setSortMode('beneficiario', 'count')">N°</button>
                </div>
            </div>
            <select id="sel-beneficiario" class="searchable-select" onchange="applyIsolationFilter(this.value, 'beneficiario')">
                <option value="">-- Todos --</option>
            </select>
        </label>

        <label>Bono (N° Cepia):
            <select id="sel-bono" class="searchable-select" onchange="applyIsolationFilter(this.value, 'bono')">
                <option value="">-- Todos --</option>
            </select>
        </label>

        <button type="button" id="btn-toggle-labels" style="background-color: #555555;" onclick="toggleEdgeLabels()">Ocultar Fechas</button>
        <button type="button" id="btn-reset" onclick="resetZoom()">Restablecer Vista</button>
    </div>

    <script>
        var THEMES = {{
            dia1: {{
                bgGrafo: "#FAFAFA", panelBg: "#FAFAFA", panelBorder: "#E0DAD3",
                textGen: "#2B2B2B", textCtrl: "#333333", ctrlBg: "#FFFFFF", ctrlBorder: "#CCCCCC",
                btnBg: "#C65A72",
                tooltipBg: "#FFFFFF", tooltipText: "#2B2B2B", tooltipBorder: "#E0DAD3",
                bono: {{ bg: "#A8BFA8", border: "#7F9A7F", text: "#1C2B1C" }},
                empresa: {{ bg: "#D8A48F", border: "#B87E67", text: "#3B1E13" }},
                beneficiario: {{ bg: "#F0D9A7", border: "#D8B775", text: "#3D3015" }},
                edgeNormal: "#B9B4AE", edgeText: "#777777", edgeHighlight: "#C65A72"
            }},
            dia2: {{
                bgGrafo: "#F4F7FB", panelBg: "#FFFFFF", panelBorder: "#D8E0EA",
                textGen: "#243342", textCtrl: "#243342", ctrlBg: "#FFFFFF", ctrlBorder: "#D8E0EA",
                btnBg: "#D94F70",
                tooltipBg: "#FFFFFF", tooltipText: "#243342", tooltipBorder: "#D8E0EA",
                bono: {{ bg: "#8FB3D9", border: "#4F7DA8", text: "#18324A" }},
                empresa: {{ bg: "#74C3B4", border: "#2E8F80", text: "#113B36" }},
                beneficiario: {{ bg: "#E6C15A", border: "#B48A18", text: "#4A3710" }},
                edgeNormal: "#9EA7B3", edgeText: "#58606B", edgeHighlight: "#D94F70"
            }},
            noche1: {{
                bgGrafo: "#111827", panelBg: "#1F2937", panelBorder: "#374151",
                textGen: "#E5E7EB", textCtrl: "#E5E7EB", ctrlBg: "#111827", ctrlBorder: "#374151",
                btnBg: "#FF6B81",
                tooltipBg: "#1F2937", tooltipText: "#F3F4F6", tooltipBorder: "#4B5563",
                bono: {{ bg: "#3C5A73", border: "#7FA3BF", text: "#F5FAFF" }},
                empresa: {{ bg: "#3D746D", border: "#79B7AE", text: "#F4FFFD" }},
                beneficiario: {{ bg: "#8A6A2F", border: "#D6B15E", text: "#FFF8E5" }},
                edgeNormal: "#64748B", edgeText: "#CBD5E1", edgeHighlight: "#FF6B81"
            }},
            noche2: {{
                bgGrafo: "#15171B", panelBg: "#22262C", panelBorder: "#3A4048",
                textGen: "#F3F4F6", textCtrl: "#F3F4F6", ctrlBg: "#1A1D22", ctrlBorder: "#3A4048",
                btnBg: "#FF6E67",
                tooltipBg: "#22262C", tooltipText: "#F3F4F6", tooltipBorder: "#4B5563",
                bono: {{ bg: "#6E7EE6", border: "#AAB4FF", text: "#F5F7FF" }},
                empresa: {{ bg: "#2FA394", border: "#72D6C7", text: "#F1FFFC" }},
                beneficiario: {{ bg: "#C9853E", border: "#F1BA72", text: "#FFF6E8" }},
                edgeNormal: "#6E7682", edgeText: "#D5DBE3", edgeHighlight: "#FF6E67"
            }}
        }};

        var currentThemeKey = localStorage.getItem('selectedTheme') || 'dia1';
        var currentFlowMode = 'cronologico';
        var originalNodes = [];
        var originalEdges = [];
        var initialPositions = {{}};
        var currentIsolatedValue = null;
        var currentIsolatedType = null;
        var showEdgeLabels = true;
        
        var sortModeEndo = 'alpha';
        var sortModeBene = 'alpha';

        var navigationHistory = [];
        var isNavigatingBack = false;

        function switchFlowMode(newMode) {{
            currentFlowMode = newMode;
            if (currentIsolatedValue) {{
                applyIsolationFilter(currentIsolatedValue, currentIsolatedType, true);
            }} else {{
                filterByEndosos();
            }}
        }}

        function pushNavigationState() {{
            if (isNavigatingBack) return;
            var currentState = {{
                val: currentIsolatedValue,
                type: currentIsolatedType
            }};
            
            var lastState = navigationHistory[navigationHistory.length - 1];
            if (!lastState || lastState.val !== currentState.val || lastState.type !== currentState.type) {{
                navigationHistory.push(currentState);
                if (navigationHistory.length > 25) navigationHistory.shift();
            }}
        }}

        function setSortMode(type, mode) {{
            var selectId = (type === 'endosatario') ? 'sel-endosatario' : 'sel-beneficiario';
            var selectElem = document.getElementById(selectId);
            if (!selectElem) return;

            if (type === 'endosatario') {{
                sortModeEndo = mode;
                document.getElementById('btn-sort-endo-alpha').classList.toggle('active', mode === 'alpha');
                document.getElementById('btn-sort-endo-count').classList.toggle('active', mode === 'count');
            }} else {{
                sortModeBene = mode;
                document.getElementById('btn-sort-bene-alpha').classList.toggle('active', mode === 'alpha');
                document.getElementById('btn-sort-bene-count').classList.toggle('active', mode === 'count');
            }}

            var currentVal = selectElem.value;
            var options = Array.from(selectElem.options).filter(opt => opt.value !== "");

            options.sort(function(a, b) {{
                if (mode === 'count') {{
                    var countA = parseInt((a.text.match(/\((\d+)\s+/)||[])[1] || 0, 10);
                    var countB = parseInt((b.text.match(/\((\d+)\s+/)||[])[1] || 0, 10);
                    var diff = countB - countA;
                    return diff !== 0 ? diff : a.text.localeCompare(b.text);
                }} else {{
                    return a.text.localeCompare(b.text);
                }}
            }});

            selectElem.innerHTML = '<option value="">-- Todos --</option>';
            options.forEach(opt => selectElem.appendChild(opt));
            selectElem.value = currentVal;
        }}

        function getStyledNodes(nodeList, validNodeIds) {{
            var t = THEMES[currentThemeKey] || THEMES.dia1;
            return nodeList.map(function(n) {{
                var groupTheme = t[n.group] || t.bono;
                var isExactlySelected = (currentIsolatedValue && n.id === currentIsolatedValue);
                
                // Si se pasa validNodeIds, el nodo es visible SOLO si pertenece al conjunto
                var isVisible = validNodeIds ? validNodeIds.has(n.id) : (n.hidden !== undefined ? !n.hidden : true);

                var styledNode = {{
                    id: n.id,
                    hidden: !isVisible,
                    borderWidth: isExactlySelected ? 3 : 1.5,
                    color: {{
                        background: groupTheme.bg,
                        border: isExactlySelected ? t.edgeHighlight : groupTheme.border,
                        highlight: {{ background: groupTheme.bg, border: t.edgeHighlight }}
                    }},
                    font: {{ color: groupTheme.text, face: 'Arial' }}
                }};
                if (n.x !== undefined) styledNode.x = n.x;
                if (n.y !== undefined) styledNode.y = n.y;
                return styledNode;
            }});
        }}

        function applyThemeStyles(themeKey) {{
            var t = THEMES[themeKey] || THEMES.dia1;
            currentThemeKey = themeKey;
            localStorage.setItem('selectedTheme', themeKey);

            document.body.style.backgroundColor = t.bgGrafo;
            var netContainer = document.getElementById('mynetwork');
            if (netContainer) netContainer.style.backgroundColor = t.bgGrafo;

            var panel = document.getElementById('filter-panel');
            panel.style.backgroundColor = t.panelBg;
            panel.style.borderColor = t.panelBorder;
            panel.style.color = t.textCtrl;

            var selects = panel.querySelectorAll('select');
            selects.forEach(function(s) {{
                s.style.backgroundColor = t.ctrlBg;
                s.style.color = t.textCtrl;
                s.style.borderColor = t.ctrlBorder;
            }});

            var sortBtns = panel.querySelectorAll('.sort-btn');
            sortBtns.forEach(function(b) {{
                b.style.color = t.textCtrl;
            }});

            var btn = document.getElementById('btn-reset');
            btn.style.backgroundColor = t.btnBg;

            document.documentElement.style.setProperty('--tooltip-bg', t.tooltipBg);
            document.documentElement.style.setProperty('--tooltip-text', t.tooltipText);
            document.documentElement.style.setProperty('--tooltip-border', t.tooltipBorder);
            document.documentElement.style.setProperty('--tooltip-highlight', t.edgeHighlight);
        }}

        function changeTheme(themeKey) {{
            applyThemeStyles(themeKey);
            if (currentIsolatedValue) {{
                applyIsolationFilter(currentIsolatedValue, currentIsolatedType, true);
            }} else {{
                filterByEndosos();
            }}
        }}

        function toggleEdgeLabels() {{
            showEdgeLabels = !showEdgeLabels;
            var btn = document.getElementById('btn-toggle-labels');
            btn.innerText = showEdgeLabels ? "Ocultar Fechas" : "Mostrar Fechas";

            var t = THEMES[currentThemeKey] || THEMES.dia1;

            var edgeUpdates = originalEdges.map(function(e) {{
                return {{
                    id: e.id,
                    label: showEdgeLabels ? e.label : "",
                    font: {{
                        color: t.edgeText,
                        size: showEdgeLabels ? 8 : 0,
                        strokeWidth: showEdgeLabels ? 3 : 0,
                        strokeColor: t.bgGrafo
                    }}
                }};
            }});
            edges.update(edgeUpdates);
        }}

        network.once("beforeDrawing", function() {{
            var allNodes = nodes.get();
            var nodeUpdates = [];
            allNodes.forEach(function(node) {{
                if (node.title && typeof node.title === 'string') {{
                    var container = document.createElement('div');
                    container.className = 'custom-tooltip-card';
                    container.innerHTML = node.title;
                    nodeUpdates.push({{ id: node.id, title: container }});
                }}
            }});
            if (nodeUpdates.length > 0) {{ nodes.update(nodeUpdates); }}

            var allEdges = edges.get();
            var edgeUpdates = [];
            allEdges.forEach(function(edge) {{
                if (edge.title && typeof edge.title === 'string') {{
                    var container = document.createElement('div');
                    container.className = 'custom-tooltip-card';
                    container.innerHTML = edge.title;
                    edgeUpdates.push({{ id: edge.id, title: container }});
                }}
            }});
            if (edgeUpdates.length > 0) {{ edges.update(edgeUpdates); }}
        }});

        network.once("stabilizationIterationsDone", function() {{
            network.setOptions({{ physics: {{ enabled: false }} }});
            var allIds = nodes.getIds();
            var pos = network.getPositions(allIds);
            allIds.forEach(function(id) {{
                initialPositions[id] = {{ x: pos[id].x, y: pos[id].y }};
            }});
        }});

        network.once("afterDrawing", function () {{
            originalNodes = JSON.parse(JSON.stringify(nodes.get()));
            originalEdges = JSON.parse(JSON.stringify(edges.get()));
            
            document.getElementById('sel-theme').value = currentThemeKey;
            applyThemeStyles(currentThemeKey);
            filterByEndosos();
        }});

        document.querySelectorAll('.searchable-select').forEach(function(select) {{
            var searchStr = "";
            var searchTimeout;
            select.addEventListener('keydown', function(e) {{
                if (e.key.length === 1) {{
                    searchStr += e.key.toLowerCase();
                    clearTimeout(searchTimeout);
                    searchTimeout = setTimeout(function() {{ searchStr = ""; }}, 1000);

                    for (var i = 0; i < select.options.length; i++) {{
                        if (select.options[i].text.toLowerCase().includes(searchStr)) {{
                            select.selectedIndex = i;
                            select.dispatchEvent(new Event('change'));
                            break;
                        }}
                    }}
                }}
            }});
        }});

        function updateSelectDropdowns(validNodeIds) {{
            var selBono = document.getElementById('sel-bono');
            var selEndo = document.getElementById('sel-endosatario');
            var selBene = document.getElementById('sel-beneficiario');

            var valBono = selBono.value;
            var valEndo = selEndo.value;
            var valBene = selBene.value;

            var bonosList = []; 
            var endoMap = {{}}; 
            var beneMap = {{}};

            var activeEdges = originalEdges.filter(e => e.flowMode === currentFlowMode && (!validNodeIds || (validNodeIds.has(e.from) && validNodeIds.has(e.to))));

            originalNodes.forEach(function(n) {{
                if (!validNodeIds || validNodeIds.has(n.id)) {{
                    if (n.group === 'bono') {{
                        bonosList.push(n.id);
                    }}
                }}
            }});

            activeEdges.forEach(function(e) {{
                var toNode = originalNodes.find(n => n.id === e.to);
                if (toNode && toNode.group === 'endosatario' && (!validNodeIds || validNodeIds.has(toNode.id))) {{
                    endoMap[toNode.id] = (endoMap[toNode.id] || 0) + 1;
                }}
            }});

            originalNodes.forEach(function(n) {{
                if (n.group === 'endosatario' && (!validNodeIds || validNodeIds.has(n.id))) {{
                    if (!(n.id in endoMap)) endoMap[n.id] = 0;
                }}
            }});

            activeEdges.forEach(function(e) {{
                var toNode = originalNodes.find(n => n.id === e.to);
                if (toNode && toNode.group === 'beneficiario' && (!validNodeIds || validNodeIds.has(toNode.id))) {{
                    if (!beneMap[toNode.id]) beneMap[toNode.id] = new Set();
                    if (e.bono) beneMap[toNode.id].add(e.bono);
                }}
            }});

            originalNodes.forEach(function(n) {{
                if (n.group === 'beneficiario' && (!validNodeIds || validNodeIds.has(n.id))) {{
                    if (!(n.id in beneMap)) beneMap[n.id] = new Set();
                }}
            }});

            bonosList.sort();

            var sortedEndos = Object.keys(endoMap);
            if (sortModeEndo === 'count') {{
                sortedEndos.sort(function(a, b) {{
                    var diff = endoMap[b] - endoMap[a];
                    return diff !== 0 ? diff : a.localeCompare(b);
                }});
            }} else {{
                sortedEndos.sort();
            }}

            var sortedBenes = Object.keys(beneMap);
            if (sortModeBene === 'count') {{
                sortedBenes.sort(function(a, b) {{
                    var diff = beneMap[b].size - beneMap[a].size;
                    return diff !== 0 ? diff : a.localeCompare(b);
                }});
            }} else {{
                sortedBenes.sort();
            }}

            selBono.innerHTML = '<option value="">-- Todos --</option>' + 
                bonosList.map(b => `<option value="${{b}}">${{b}}</option>`).join('');

            selEndo.innerHTML = '<option value="">-- Todos --</option>' + 
                sortedEndos.map(e => {{
                    var cant = endoMap[e];
                    var labelText = `${{e}} (${{cant}} endoso${{cant !== 1 ? 's' : ''}})`;
                    return `<option value="${{e}}">${{labelText}}</option>`;
                }}).join('');

            selBene.innerHTML = '<option value="">-- Todos --</option>' + 
                sortedBenes.map(b => {{
                    var cant = beneMap[b].size;
                    var labelText = `${{b}} (${{cant}} bono${{cant !== 1 ? 's' : ''}})`;
                    return `<option value="${{b}}">${{labelText}}</option>`;
                }}).join('');

            selBono.value = bonosList.includes(valBono) ? valBono : "";
            selEndo.value = sortedEndos.includes(valEndo) ? valEndo : "";
            selBene.value = sortedBenes.includes(valBene) ? valBene : "";
        }}

        function checkEndososCondition(val, op, targetVal) {{
            if (targetVal === "ALL") return true;
            var target = parseInt(targetVal, 10);
            var count = parseInt(val, 10) || 0;

            if (op === 'eq') return count === target;
            if (op === 'lte') return count <= target;
            return count >= target;
        }}

        function filterByEndosos() {{
            var op = document.getElementById('sel-op-endosos').value;
            var val = document.getElementById('sel-val-endosos').value;

            currentIsolatedValue = null;
            currentIsolatedType = null;

            var validEdges = originalEdges.filter(e => e.flowMode === currentFlowMode && checkEndososCondition(e.cantEndosos, op, val));
            var validNodeIds = new Set();
            validEdges.forEach(function(e) {{
                validNodeIds.add(e.from);
                validNodeIds.add(e.to);
            }});

            var t = THEMES[currentThemeKey] || THEMES.dia1;
            edges.update(originalEdges.map(e => ({{
                id: e.id,
                hidden: !(e.flowMode === currentFlowMode && checkEndososCondition(e.cantEndosos, op, val)),
                label: showEdgeLabels ? e.label : "",
                font: {{ size: showEdgeLabels ? 8 : 0, color: t.edgeText, strokeWidth: showEdgeLabels ? 3 : 0, strokeColor: t.bgGrafo }}
            }})));

            nodes.update(getStyledNodes(originalNodes, validNodeIds));
            updateSelectDropdowns(validNodeIds);
        }}

        function applyIsolationFilter(selectedValue, type, skipHistory) {{
            if (!skipHistory) {{
                pushNavigationState();
            }}

            var t = THEMES[currentThemeKey] || THEMES.dia1;

            if (type !== 'bono') document.getElementById('sel-bono').value = "";
            if (type !== 'endosatario') document.getElementById('sel-endosatario').value = "";
            if (type !== 'beneficiario') document.getElementById('sel-beneficiario').value = "";

            if (type === 'bono') document.getElementById('sel-bono').value = selectedValue || "";
            if (type === 'endosatario') document.getElementById('sel-endosatario').value = selectedValue || "";
            if (type === 'beneficiario') document.getElementById('sel-beneficiario').value = selectedValue || "";

            if (!selectedValue) {{
                filterByEndosos();
                return;
            }}

            currentIsolatedValue = selectedValue;
            currentIsolatedType = type;

            var activeBonos = new Set();
            var activeNodes = new Set();
            var activeEdges = new Set();

            if (type === 'bono') {{
                activeBonos.add(selectedValue);
                activeNodes.add(selectedValue);
            }} else {{
                activeNodes.add(selectedValue);
                originalEdges.forEach(function(edge) {{
                    if (edge.flowMode === currentFlowMode && (edge.from === selectedValue || edge.to === selectedValue)) {{
                        if (edge.bono) activeBonos.add(edge.bono);
                    }}
                }});
            }}

            originalEdges.forEach(function(edge) {{
                if (edge.flowMode === currentFlowMode && activeBonos.has(edge.bono)) {{
                    activeEdges.add(edge.id);
                    activeNodes.add(edge.from);
                    activeNodes.add(edge.to);
                }}
            }});

            var op = document.getElementById('sel-op-endosos').value;
            var val = document.getElementById('sel-val-endosos').value;

            var visibleNodeIds = new Set();

            var edgeUpdates = originalEdges.map(function(e) {{
                var isCorrectMode = (e.flowMode === currentFlowMode);
                var isActive = activeEdges.has(e.id);
                var passesEndosos = checkEndososCondition(e.cantEndosos, op, val);
                var isVisible = isCorrectMode && isActive && passesEndosos;

                if (isVisible) {{
                    visibleNodeIds.add(e.from);
                    visibleNodeIds.add(e.to);
                }}

                return {{
                    id: e.id,
                    hidden: !isVisible,
                    label: showEdgeLabels ? e.label : "",
                    width: isActive ? 3.5 : 1.5,
                    color: {{ color: isActive ? t.edgeHighlight : t.edgeNormal }},
                    font: {{ 
                        color: t.edgeText, 
                        size: showEdgeLabels ? 8 : 0, 
                        strokeWidth: showEdgeLabels ? 3 : 0, 
                        strokeColor: t.bgGrafo 
                    }}
                }};
            }});

            if (selectedValue) {{
                visibleNodeIds.add(selectedValue);
            }}

            nodes.update(getStyledNodes(originalNodes, visibleNodeIds));
            edges.update(edgeUpdates);

            updateSelectDropdowns(visibleNodeIds);

            var nodesToFit = Array.from(visibleNodeIds);
            if (nodesToFit.length === 0 && selectedValue) {{
                nodesToFit = [selectedValue];
            }}

            network.fit({{ nodes: nodesToFit, animation: {{ duration: 600 }} }});
        }}

        network.on("click", function (params) {{
            setTimeout(function() {{ network.unselectAll(); }}, 50);

            if (params.nodes.length > 0) {{
                var selectedNodeId = params.nodes[0];
                var clickedNode = nodes.get(selectedNodeId);

                if (clickedNode) {{
                    var type = clickedNode.group;
                    applyIsolationFilter(selectedNodeId, type);
                }}
            }} else if (params.edges.length > 0) {{
                var edgeId = params.edges[0];
                var clickedEdge = edges.get(edgeId);

                if (clickedEdge && clickedEdge.bono) {{
                    var bonoId = clickedEdge.bono;
                    applyIsolationFilter(bonoId, 'bono');
                }}
            }} else {{
                if (navigationHistory.length > 0) {{
                    var previousState = navigationHistory.pop();
                    isNavigatingBack = true;
                    
                    if (previousState.val) {{
                        applyIsolationFilter(previousState.val, previousState.type, true);
                    }} else {{
                        currentIsolatedValue = null;
                        currentIsolatedType = null;
                        document.getElementById('sel-bono').value = "";
                        document.getElementById('sel-endosatario').value = "";
                        document.getElementById('sel-beneficiario').value = "";
                        filterByEndosos();
                    }}
                    isNavigatingBack = false;
                }} else {{
                    currentIsolatedValue = null;
                    currentIsolatedType = null;
                    document.getElementById('sel-bono').value = "";
                    document.getElementById('sel-endosatario').value = "";
                    document.getElementById('sel-beneficiario').value = "";
                    filterByEndosos();
                }}
            }}
        }});

        function resetZoom() {{
            document.getElementById('sel-op-endosos').value = "gte";
            document.getElementById('sel-val-endosos').value = "ALL";
            document.getElementById('sel-bono').value = "";
            document.getElementById('sel-endosatario').value = "";
            document.getElementById('sel-beneficiario').value = "";
            
            currentIsolatedValue = null;
            currentIsolatedType = null;
            navigationHistory = [];

            Object.keys(initialPositions).forEach(function(nodeId) {{
                if (initialPositions[nodeId]) {{
                    network.moveNode(nodeId, initialPositions[nodeId].x, initialPositions[nodeId].y);
                }}
            }});

            filterByEndosos();
            applyThemeStyles(currentThemeKey);
            network.fit({{ animation: {{ duration: 600 }} }});
            network.unselectAll();
        }}
    </script>
    """

    new_content = content.replace("</body>", f"{panel_html}\n</body>")

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_content)


if __name__ == "__main__":
    main()
