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
        "https://www.googleapis.com/auth/spreadsheets.readonly", 
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    
    credentials, _ = google.auth.default(scopes=SCOPES)
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
        bgcolor="transparent", 
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

    for _, row in df.iterrows():
        cepia_id = normalizar_texto(row.get('N° Cepia', ''))
        beneficiario_id = normalizar_texto(row.get('Beneficiario', ''))
        if not cepia_id: 
            continue

        i_temp = 1
        num_endosos_bono = 0
        while True:
            col_check = next((c for c in df.columns if c.strip().lower() == f'endosatario_{i_temp}'), None)
            if not col_check:
                break
            if normalizar_texto(row.get(col_check, '')):
                num_endosos_bono += 1
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
                font={"size": 10, "face": "Arial"}
            )

        nodo_actual = cepia_id
        i = 1
        
        while True:
            col_endosatario = next((c for c in df.columns if c.strip().lower() == f'endosatario_{i}'), None)
            col_fecha = next((c for c in df.columns if c.strip().lower() == f'endoso_fecha_{i}'), None)

            if not col_endosatario:
                break

            endosatario_id = normalizar_texto(row.get(col_endosatario, ''))
            fecha_val = str(row.get(col_fecha, '')).strip() if col_fecha else ""

            if endosatario_id:
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
                    font={"size": 10, "face": "Arial"}
                )
                
                label_arista = f"E{i}: {fecha_val}" if fecha_val else f"Endoso {i}"
                
                net.add_edge(
                    nodo_actual, 
                    endosatario_id, 
                    label=label_arista, 
                    title=f"Bono: {cepia_id} | Fecha: {fecha_val}",
                    width=1.5,
                    bono=cepia_id,
                    cantEndosos=num_endosos_bono,
                    arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                    smooth={"type": "curvedCW", "roundness": 0.25},
                    font={"size": 7, "face": "Arial", "align": "middle", "vadjust": -2}
                )
                nodo_actual = endosatario_id
            i += 1

        if beneficiario_id:
            net.add_edge(
                nodo_actual, 
                beneficiario_id, 
                label="Asignado a", 
                title=f"Bono: {cepia_id} | Beneficiario Final", 
                width=1.5,
                dashes=True,
                bono=cepia_id,
                cantEndosos=num_endosos_bono,
                arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                smooth={"type": "curvedCW", "roundness": 0.2},
                font={"size": 7, "face": "Arial", "align": "middle", "vadjust": -2}
            )

    os.makedirs("docs", exist_ok=True)
    output_path = os.path.join("docs", "index.html")
    net.write_html(output_path)

    inyectar_panel_filtros(output_path, bonos_set, endosatarios_set, beneficiarios_set, max_endosos_encontrados)
    print(f"✅ Grafo procesado con selector de 4 temas y búsqueda rápida en: {output_path}")


def inyectar_panel_filtros(html_path, bonos, endosatarios, beneficiarios, max_endosos):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    meta_cache = """
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
    <meta http-equiv="Pragma" content="no-cache" />
    <meta http-equiv="Expires" content="0" />
    """
    content = content.replace("<head>", f"<head>\n{meta_cache}", 1)

    panel_html = r"""
    <style>
        :root {
            --graph-bg: #FAFAFA;
            --panel-bg: rgba(250,250,250,0.97);
            --panel-border: #E0DAD3;
            --panel-text: #333333;
            --ctrl-bg: #FFFFFF;
            --ctrl-text: #333333;
            --ctrl-border: #CCCCCC;
            --btn-bg: #C65A72;
            --btn-hover: #A8455B;
            --tooltip-bg: #FFFFFF;
            --tooltip-text: #252525;
            --tooltip-border: #C9CDD2;
        }

        html, body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            height: 100% !important;
            overflow: hidden !important;
            background: var(--graph-bg) !important;
            font-family: Arial, sans-serif;
            transition: background-color 0.25s ease;
        }

        .card, .card-body {
            margin: 0 !important;
            padding: 0 !important;
            width: 100% !important;
            height: 100% !important;
            border: 0 !important;
            background: transparent !important;
        }

        #mynetwork {
            width: 100% !important;
            height: 100vh !important;
            border: 0 !important;
            background: var(--graph-bg) !important;
            transition: background-color 0.25s ease;
        }

        #mynetwork canvas {
            background: transparent !important;
        }

        #filter-panel {
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
            max-width: calc(100% - 40px);
            padding: 12px 16px;
            color: var(--panel-text);
            background: var(--panel-bg);
            border: 1px solid var(--panel-border);
            border-radius: 8px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.22);
            font-size: 13px;
        }

        #filter-panel label {
            display: flex;
            flex-direction: column;
            gap: 4px;
            color: var(--panel-text);
            font-weight: bold;
        }

        #filter-panel select,
        #filter-panel button {
            min-height: 30px;
            padding: 6px 10px;
            border-radius: 4px;
            font-size: 12px;
            outline: none;
        }

        #filter-panel select {
            color: var(--ctrl-text);
            background: var(--ctrl-bg);
            border: 1px solid var(--ctrl-border);
        }

        #filter-panel option {
            color: var(--ctrl-text);
            background: var(--ctrl-bg);
        }

        #filter-panel button {
            margin-top: 16px;
            color: #FFFFFF;
            background: var(--btn-bg);
            border: 0;
            cursor: pointer;
            font-weight: bold;
        }

        #filter-panel button:hover {
            background: var(--btn-hover);
        }

        /* Tooltip opaco para nodos y aristas. */
        div.vis-tooltip {
            position: absolute !important;
            z-index: 9999 !important;
            pointer-events: none !important;
            max-width: 340px !important;
            padding: 9px 12px !important;
            color: var(--tooltip-text) !important;
            background: var(--tooltip-bg) !important;
            border: 1px solid var(--tooltip-border) !important;
            border-radius: 7px !important;
            box-shadow: 0 5px 18px rgba(0,0,0,0.34) !important;
            font-family: Arial, sans-serif !important;
            font-size: 12px !important;
            line-height: 1.45 !important;
            white-space: normal !important;
            overflow-wrap: break-word !important;
            word-break: break-word !important;
        }
    </style>

    <div id="filter-panel">
        <label>Tema:
            <select id="sel-theme" onchange="changeTheme(this.value)">
                <option value="dia1">Día · Pastel original</option>
                <option value="dia2">Día · Azul Acero / Teal / Mostaza</option>
                <option value="noche1">Noche · Petróleo / Pino / Ámbar</option>
                <option value="noche2">Noche · Índigo / Turquesa / Cobre</option>
            </select>
        </label>

        <label>Min. Endosos:
            <select id="sel-min-endosos" onchange="filterByEndosos(this.value)"></select>
        </label>

        <label>Bono (N° Cepia):
            <select id="sel-bono" class="searchable-select" onchange="applyIsolationFilter(this.value, 'bono')">
                <option value="">-- Todos --</option>
            </select>
        </label>

        <label>Endosatario:
            <select id="sel-endosatario" class="searchable-select" onchange="applyIsolationFilter(this.value, 'endosatario')">
                <option value="">-- Todos --</option>
            </select>
        </label>

        <label>Beneficiario:
            <select id="sel-beneficiario" class="searchable-select" onchange="applyIsolationFilter(this.value, 'beneficiario')">
                <option value="">-- Todos --</option>
            </select>
        </label>

        <button id="btn-edge-labels" type="button" onclick="toggleEdgeLabels()">
            Ocultar texto aristas
        </button>

        <button id="btn-reset" type="button" onclick="resetZoom()">
            Restablecer vista
        </button>
    </div>

    <script>
        "use strict";

        var MAX_ENDOSOS = __MAX_ENDOSOS__;

        var THEMES = {
            dia1: {
                dark: false,
                bgGrafo: "#FAFAFA",
                panelBg: "rgba(250,250,250,0.97)",
                panelBorder: "#E0DAD3",
                textCtrl: "#333333",
                ctrlBg: "#FFFFFF",
                ctrlBorder: "#CCCCCC",
                tooltipBg: "#FFFFFF",
                tooltipText: "#252525",
                tooltipBorder: "#C9CDD2",
                btnBg: "#C65A72",
                btnHover: "#A8455B",
                bono: { bg: "#A8BFA8", border: "#7F9A7F", text: "#1C2B1C" },
                endosatario: { bg: "#D8A48F", border: "#B87E67", text: "#3B1E13" },
                beneficiario: { bg: "#F0D9A7", border: "#D8B775", text: "#3D3015" },
                edgeNormal: "#B9B4AE",
                edgeText: "#666666",
                edgeHighlight: "#C65A72"
            },
            dia2: {
                dark: false,
                bgGrafo: "#F4F7FB",
                panelBg: "rgba(255,255,255,0.97)",
                panelBorder: "#D8E0EA",
                textCtrl: "#243342",
                ctrlBg: "#FFFFFF",
                ctrlBorder: "#D8E0EA",
                tooltipBg: "#FFFFFF",
                tooltipText: "#243342",
                tooltipBorder: "#B9C5D2",
                btnBg: "#D94F70",
                btnHover: "#B83A58",
                bono: { bg: "#8FB3D9", border: "#4F7DA8", text: "#18324A" },
                endosatario: { bg: "#74C3B4", border: "#2E8F80", text: "#113B36" },
                beneficiario: { bg: "#E6C15A", border: "#B48A18", text: "#4A3710" },
                edgeNormal: "#9EA7B3",
                edgeText: "#58606B",
                edgeHighlight: "#D94F70"
            },
            noche1: {
                dark: true,
                bgGrafo: "#0D1521",
                panelBg: "rgba(24,34,48,0.98)",
                panelBorder: "#3A485A",
                textCtrl: "#E7ECF2",
                ctrlBg: "#121D2B",
                ctrlBorder: "#445368",
                tooltipBg: "#202B39",
                tooltipText: "#F2F5F8",
                tooltipBorder: "#53657A",
                btnBg: "#E35F78",
                btnHover: "#F0798E",
                bono: { bg: "#456C89", border: "#8BB4D0", text: "#F5FAFF" },
                endosatario: { bg: "#3E847A", border: "#84C7BC", text: "#F4FFFD" },
                beneficiario: { bg: "#9B752D", border: "#E2BC62", text: "#FFF8E5" },
                edgeNormal: "#6F7E91",
                edgeText: "#CBD5E1",
                edgeHighlight: "#FF7188"
            },
            noche2: {
                dark: true,
                bgGrafo: "#0B0D10",
                panelBg: "rgba(28,30,35,0.98)",
                panelBorder: "#454A53",
                textCtrl: "#F2F3F5",
                ctrlBg: "#181A1F",
                ctrlBorder: "#484E58",
                tooltipBg: "#252830",
                tooltipText: "#F7F7F8",
                tooltipBorder: "#5B626E",
                btnBg: "#FF675F",
                btnHover: "#FF827B",
                bono: { bg: "#6675DF", border: "#B3BCFF", text: "#F8F8FF" },
                endosatario: { bg: "#259D91", border: "#76DBCF", text: "#F1FFFD" },
                beneficiario: { bg: "#C77A32", border: "#F3B86F", text: "#FFF7ED" },
                edgeNormal: "#747C89",
                edgeText: "#D5DBE3",
                edgeHighlight: "#FF716A"
            }
        };

        /* Captura inmediata: el panel se inyecta después de crear nodes/edges. */
        var originalNodes = JSON.parse(JSON.stringify(nodes.get()));
        var originalEdges = JSON.parse(JSON.stringify(edges.get()));
        var initialPositions = {};
        var positionsCaptured = false;
        var currentIsolatedValue = null;
        var currentIsolatedType = null;
        var currentThemeKey = localStorage.getItem("selectedTheme") || "dia1";
        var edgeLabelsVisible = localStorage.getItem("edgeLabelsVisible") !== "false";

        if (!THEMES[currentThemeKey]) currentThemeKey = "dia1";

        function cssVar(name, value) {
            document.documentElement.style.setProperty(name, value);
        }

        function groupTheme(theme, group) {
            return theme[group] || theme.bono;
        }

        function clearEntitySelections() {
            document.getElementById("sel-bono").value = "";
            document.getElementById("sel-endosatario").value = "";
            document.getElementById("sel-beneficiario").value = "";
        }

        function replaceOptions(select, values) {
            select.replaceChildren(new Option("-- Todos --", ""));
            values.forEach(function(value) {
                select.add(new Option(value, value));
            });
        }

        function sortValues(values) {
            return values.sort(function(a, b) {
                return a.localeCompare(b, "es", { sensitivity: "base", numeric: true });
            });
        }

        function updateSelectDropdowns(validNodeIds) {
            var bonos = [];
            var endosatarios = [];
            var beneficiarios = [];

            originalNodes.forEach(function(node) {
                if (validNodeIds && !validNodeIds.has(node.id)) return;
                if (node.group === "bono") bonos.push(String(node.id));
                if (node.group === "endosatario") endosatarios.push(String(node.id));
                if (node.group === "beneficiario") beneficiarios.push(String(node.id));
            });

            replaceOptions(document.getElementById("sel-bono"), sortValues(bonos));
            replaceOptions(document.getElementById("sel-endosatario"), sortValues(endosatarios));
            replaceOptions(document.getElementById("sel-beneficiario"), sortValues(beneficiarios));
        }

        function buildMinOptions() {
            var select = document.getElementById("sel-min-endosos");
            select.replaceChildren(new Option("Todos (≥ 0)", "0"));
            for (var i = 1; i <= MAX_ENDOSOS; i++) {
                select.add(new Option("Al menos " + i + " endoso" + (i === 1 ? "" : "s"), String(i)));
            }
        }

        function applyThemeStyles(themeKey) {
            var t = THEMES[themeKey] || THEMES.dia1;
            currentThemeKey = themeKey;
            localStorage.setItem("selectedTheme", themeKey);

            cssVar("--graph-bg", t.bgGrafo);
            cssVar("--panel-bg", t.panelBg);
            cssVar("--panel-border", t.panelBorder);
            cssVar("--panel-text", t.textCtrl);
            cssVar("--ctrl-bg", t.ctrlBg);
            cssVar("--ctrl-text", t.textCtrl);
            cssVar("--ctrl-border", t.ctrlBorder);
            cssVar("--btn-bg", t.btnBg);
            cssVar("--btn-hover", t.btnHover);
            cssVar("--tooltip-bg", t.tooltipBg);
            cssVar("--tooltip-text", t.tooltipText);
            cssVar("--tooltip-border", t.tooltipBorder);

            document.documentElement.style.backgroundColor = t.bgGrafo;
            document.body.style.backgroundColor = t.bgGrafo;
            var container = document.getElementById("mynetwork");
            if (container) container.style.backgroundColor = t.bgGrafo;

            network.setOptions({
                edges: {
                    font: {
                        size: 7,
                        face: "Arial",
                        color: t.edgeText,
                        strokeWidth: t.dark ? 1.5 : 1,
                        strokeColor: t.bgGrafo,
                        align: "middle",
                        vadjust: -2
                    }
                }
            });

            nodes.update(originalNodes.map(function(node) {
                var gt = groupTheme(t, node.group);
                return {
                    id: node.id,
                    borderWidth: 1.5,
                    color: {
                        background: gt.bg,
                        border: gt.border,
                        highlight: { background: gt.bg, border: t.edgeHighlight },
                        hover: { background: gt.bg, border: t.edgeHighlight }
                    },
                    font: Object.assign({}, node.font || {}, { color: gt.text, face: "Arial" })
                };
            }));

            edges.update(originalEdges.map(function(edge) {
                return {
                    id: edge.id,
                    width: 1.5,
                    color: { color: t.edgeNormal, highlight: t.edgeHighlight, hover: t.edgeHighlight },
                    font: Object.assign({}, edge.font || {}, {
                        size: 7,
                        face: "Arial",
                        color: t.edgeText,
                        strokeWidth: t.dark ? 1.5 : 1,
                        strokeColor: t.bgGrafo,
                        align: "middle",
                        vadjust: -2
                    })
                };
            }));

            network.redraw();
        }

        function changeTheme(themeKey) {
            applyThemeStyles(themeKey);
            if (currentIsolatedValue && currentIsolatedType) {
                applyIsolationFilter(currentIsolatedValue, currentIsolatedType);
            }
            applyEdgeLabelVisibility();
        }

        function applyEdgeLabelVisibility() {
            edges.update(originalEdges.map(function(edge) {
                return { id: edge.id, label: edgeLabelsVisible ? (edge.label || "") : "" };
            }));
            document.getElementById("btn-edge-labels").textContent = edgeLabelsVisible
                ? "Ocultar texto aristas"
                : "Mostrar texto aristas";
        }

        function toggleEdgeLabels() {
            edgeLabelsVisible = !edgeLabelsVisible;
            localStorage.setItem("edgeLabelsVisible", String(edgeLabelsVisible));
            applyEdgeLabelVisibility();
        }

        function applyBaseVisibility(minCount) {
            if (minCount <= 0) {
                nodes.update(originalNodes.map(function(n) { return { id: n.id, hidden: false }; }));
                edges.update(originalEdges.map(function(e) { return { id: e.id, hidden: false }; }));
                return null;
            }

            var validEdges = originalEdges.filter(function(e) {
                return Number(e.cantEndosos || 0) >= minCount;
            });
            var validNodeIds = new Set();
            validEdges.forEach(function(e) {
                validNodeIds.add(e.from);
                validNodeIds.add(e.to);
            });

            edges.update(originalEdges.map(function(e) {
                return { id: e.id, hidden: Number(e.cantEndosos || 0) < minCount };
            }));
            nodes.update(originalNodes.map(function(n) {
                return { id: n.id, hidden: !validNodeIds.has(n.id) };
            }));
            return validNodeIds;
        }

        function fitVisible(duration) {
            var ids = nodes.get().filter(function(n) { return n.hidden !== true; }).map(function(n) { return n.id; });
            if (!ids.length) return;
            network.fit({ nodes: ids, animation: { duration: duration || 500, easingFunction: "easeInOutQuad" } });
        }

        function restoreFilteredView(fitGraph) {
            currentIsolatedValue = null;
            currentIsolatedType = null;
            clearEntitySelections();

            var minCount = parseInt(document.getElementById("sel-min-endosos").value, 10) || 0;
            var validNodeIds = applyBaseVisibility(minCount);
            updateSelectDropdowns(validNodeIds);
            applyThemeStyles(currentThemeKey);
            applyEdgeLabelVisibility();
            network.unselectAll();
            if (fitGraph !== false) fitVisible(500);
        }

        function filterByEndosos(minCount) {
            document.getElementById("sel-min-endosos").value = String(parseInt(minCount, 10) || 0);
            restoreFilteredView(true);
        }

        function clearIsolation() {
            restoreFilteredView(true);
        }

        function applyIsolationFilter(selectedValue, type) {
            if (!selectedValue) {
                clearIsolation();
                return;
            }

            var t = THEMES[currentThemeKey] || THEMES.dia1;
            if (type !== "bono") document.getElementById("sel-bono").value = "";
            if (type !== "endosatario") document.getElementById("sel-endosatario").value = "";
            if (type !== "beneficiario") document.getElementById("sel-beneficiario").value = "";

            currentIsolatedValue = selectedValue;
            currentIsolatedType = type;

            var minCount = parseInt(document.getElementById("sel-min-endosos").value, 10) || 0;
            var activeBonos = new Set();
            if (type === "bono") {
                activeBonos.add(selectedValue);
            } else {
                originalEdges.forEach(function(edge) {
                    var linked = edge.from === selectedValue || edge.to === selectedValue;
                    if (linked && Number(edge.cantEndosos || 0) >= minCount && edge.bono) {
                        activeBonos.add(edge.bono);
                    }
                });
            }

            var activeEdges = new Set();
            var activeNodes = new Set([selectedValue]);
            originalEdges.forEach(function(edge) {
                if (activeBonos.has(edge.bono) && Number(edge.cantEndosos || 0) >= minCount) {
                    activeEdges.add(edge.id);
                    activeNodes.add(edge.from);
                    activeNodes.add(edge.to);
                }
            });

            nodes.update(originalNodes.map(function(node) {
                var active = activeNodes.has(node.id);
                var gt = groupTheme(t, node.group);
                return {
                    id: node.id,
                    hidden: !active,
                    borderWidth: active ? 3 : 1.5,
                    color: {
                        background: gt.bg,
                        border: active ? t.edgeHighlight : gt.border,
                        highlight: { background: gt.bg, border: t.edgeHighlight },
                        hover: { background: gt.bg, border: t.edgeHighlight }
                    },
                    font: Object.assign({}, node.font || {}, { color: gt.text, face: "Arial" })
                };
            }));

            edges.update(originalEdges.map(function(edge) {
                var active = activeEdges.has(edge.id);
                return {
                    id: edge.id,
                    hidden: !active,
                    width: active ? 3.8 : 1.5,
                    color: { color: active ? t.edgeHighlight : t.edgeNormal, highlight: t.edgeHighlight, hover: t.edgeHighlight },
                    font: Object.assign({}, edge.font || {}, {
                        size: 7,
                        face: "Arial",
                        color: t.edgeText,
                        strokeWidth: t.dark ? 1.5 : 1,
                        strokeColor: t.bgGrafo,
                        align: "middle",
                        vadjust: -2
                    })
                };
            }));

            applyEdgeLabelVisibility();
            if (activeNodes.size) {
                network.fit({ nodes: Array.from(activeNodes), animation: { duration: 600, easingFunction: "easeInOutQuad" } });
            }
            setTimeout(function() { network.unselectAll(); }, 50);
        }

        network.on("click", function(params) {
            var hasNode = params.nodes.length > 0;
            var hasEdge = params.edges.length > 0;

            /* Clic real sobre fondo: deselecciona y vuelve al filtro base. */
            if (!hasNode && !hasEdge) {
                clearIsolation();
                return;
            }

            if (hasNode) {
                var nodeId = params.nodes[0];
                var node = nodes.get(nodeId);
                if (!node) return;

                if (currentIsolatedValue === nodeId && currentIsolatedType === node.group) {
                    clearIsolation();
                    return;
                }

                clearEntitySelections();
                if (node.group === "bono") document.getElementById("sel-bono").value = nodeId;
                if (node.group === "endosatario") document.getElementById("sel-endosatario").value = nodeId;
                if (node.group === "beneficiario") document.getElementById("sel-beneficiario").value = nodeId;
                applyIsolationFilter(nodeId, node.group);
                return;
            }

            if (hasEdge) {
                var edge = edges.get(params.edges[0]);
                if (!edge || !edge.bono) return;

                if (currentIsolatedValue === edge.bono && currentIsolatedType === "bono") {
                    clearIsolation();
                    return;
                }

                clearEntitySelections();
                document.getElementById("sel-bono").value = edge.bono;
                applyIsolationFilter(edge.bono, "bono");
            }
        });

        document.querySelectorAll(".searchable-select").forEach(function(select) {
            var search = "";
            var timer = null;
            select.addEventListener("keydown", function(event) {
                if (event.key.length !== 1) return;
                search += event.key.toLowerCase();
                clearTimeout(timer);
                timer = setTimeout(function() { search = ""; }, 1000);
                for (var i = 0; i < select.options.length; i++) {
                    if (select.options[i].text.toLowerCase().includes(search)) {
                        select.selectedIndex = i;
                        select.dispatchEvent(new Event("change"));
                        break;
                    }
                }
            });
        });

        function capturePositionsAndFreeze() {
            if (positionsCaptured) return;
            network.setOptions({ physics: { enabled: false } });
            var ids = nodes.getIds();
            var positions = network.getPositions(ids);
            ids.forEach(function(id) {
                if (positions[id]) initialPositions[id] = { x: positions[id].x, y: positions[id].y };
            });
            positionsCaptured = true;
        }

        network.once("stabilizationIterationsDone", capturePositionsAndFreeze);

        function resetZoom() {
            document.getElementById("sel-min-endosos").value = "0";
            currentIsolatedValue = null;
            currentIsolatedType = null;
            clearEntitySelections();
            updateSelectDropdowns(null);

            nodes.update(originalNodes.map(function(node) {
                var update = { id: node.id, hidden: false };
                if (initialPositions[node.id]) {
                    update.x = initialPositions[node.id].x;
                    update.y = initialPositions[node.id].y;
                }
                return update;
            }));
            edges.update(originalEdges.map(function(edge) { return { id: edge.id, hidden: false }; }));

            applyThemeStyles(currentThemeKey);
            applyEdgeLabelVisibility();
            network.unselectAll();
            network.fit({ animation: { duration: 600, easingFunction: "easeInOutQuad" } });
        }

        buildMinOptions();
        updateSelectDropdowns(null);
        document.getElementById("sel-theme").value = currentThemeKey;
        applyThemeStyles(currentThemeKey);
        applyEdgeLabelVisibility();
    </script>
    """

    panel_html = panel_html.replace("__MAX_ENDOSOS__", str(int(max_endosos)))

    if "</body>" not in content:
        raise ValueError("No se encontró la etiqueta </body> en el HTML generado por PyVis.")

    new_content = content.replace("</body>", panel_html + "\n</body>", 1)

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_content)


if __name__ == "__main__":
    main()
