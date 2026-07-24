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
    in_degree_counter = {}  # Para contar cuántas veces recibe endosos cada nodo

    # 1. Primer pase: Recopilar datos y contar endosos por nodo
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
        height="850px", 
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
      },
      "groups": {
        "bono": {
          "color": {"background": "#A8BFA8", "border": "#7F9A7F", "highlight": {"background": "#A8BFA8", "border": "#C65A72"}},
          "shape": "dot"
        },
        "endosatario": {
          "color": {"background": "#D8A48F", "border": "#B87E67", "highlight": {"background": "#D8A48F", "border": "#C65A72"}},
          "shape": "box"
        },
        "beneficiario": {
          "color": {"background": "#F0D9A7", "border": "#D8B775", "highlight": {"background": "#F0D9A7", "border": "#C65A72"}},
          "shape": "dot"
        }
      }
    }
    """)

    # 2. Segundo pase: Construir nodos con tamaños dinámicos sutiles
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

        # Bono base size
        net.add_node(
            cepia_id, 
            label=f"Bono:\n{cepia_id}", 
            title=f"<b>Bono (N° Cepia):</b> {cepia_id}<br><b>Endosos:</b> {num_endosos_bono}<br><b>Beneficiario Final:</b> {beneficiario_id}", 
            group="bono",
            cantEndosos=num_endosos_bono,
            size=20,
            font={"size": 11, "face": "arial", "bold": True, "color": "#1C2B1C"}
        )

        if beneficiario_id:
            label_benef = acortar_texto(beneficiario_id, 12)
            net.add_node(
                beneficiario_id, 
                label=label_benef, 
                title=f"<b>Beneficiario Completo:</b><br>{beneficiario_id}", 
                group="beneficiario",
                size=14,
                font={"size": 9, "face": "arial", "color": "#3D3015"}
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
                
                # ESCALADO LEVE SUTIL: Base 12px + 2px por cada endoso recibido (Máximo tope 28px)
                endosos_recibidos = in_degree_counter.get(endosatario_id, 1)
                size_dinamico = min(12 + (endosos_recibidos * 2), 28)

                net.add_node(
                    endosatario_id, 
                    label=label_endo, 
                    title=f"<b>Endosatario:</b> {endosatario_id}<br><b>Endosos Recibidos Total:</b> {endosos_recibidos}", 
                    group="endosatario",
                    shape="box",
                    size=size_dinamico,
                    widthConstraint={"maximum": 120},
                    font={"size": 9, "face": "arial", "color": "#3B1E13"}
                )
                
                label_arista = f"E{i}: {fecha_val}" if fecha_val else f"Endoso {i}"
                
                net.add_edge(
                    nodo_actual, 
                    endosatario_id, 
                    label=label_arista, 
                    title=f"Bono: {cepia_id} | Fecha: {fecha_val}",
                    color={"color": "#B9B4AE", "highlight": "#C65A72"},
                    width=1.5,
                    bono=cepia_id,
                    cantEndosos=num_endosos_bono,
                    arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                    smooth={"type": "curvedCW", "roundness": 0.25},
                    font={"size": 8, "align": "middle", "color": "#777777"}
                )
                nodo_actual = endosatario_id
            i += 1

        if beneficiario_id:
            net.add_edge(
                nodo_actual, 
                beneficiario_id, 
                label="Asignado a", 
                title=f"Bono: {cepia_id} | Registro de Beneficiario", 
                color={"color": "#B9B4AE", "highlight": "#C65A72"}, 
                width=1.5,
                dashes=True,
                bono=cepia_id,
                cantEndosos=num_endosos_bono,
                arrows={"to": {"enabled": True, "scaleFactor": 1.0}},
                smooth={"type": "curvedCW", "roundness": 0.2},
                font={"size": 8, "align": "middle", "color": "#777777"}
            )

    os.makedirs("docs", exist_ok=True)
    output_path = os.path.join("docs", "index.html")
    net.write_html(output_path)

    inyectar_panel_filtros(output_path, bonos_set, endosatarios_set, beneficiarios_set, max_endosos_encontrados)
    print(f"✅ Grafo procesado con escalado sutil de nodos y filtros vinculados en: {output_path}")

def inyectar_panel_filtros(html_path, bonos, endosatarios, beneficiarios, max_endosos):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    meta_cache = """
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
    <meta http-equiv="Pragma" content="no-cache" />
    <meta http-equiv="Expires" content="0" />
    """
    content = content.replace("<head>", f"<head>\n{meta_cache}")

    opts_bonos = "".join([f'<option value="{b}">{b}</option>' for b in sorted(bonos)])
    opts_endosatarios = "".join([f'<option value="{e}">{e}</option>' for e in sorted(endosatarios)])
    opts_beneficiarios = "".join([f'<option value="{b}">{b}</option>' for b in sorted(beneficiarios)])

    opts_num_endosos = '<option value="0">Todos (≥ 0)</option>'
    for k in range(1, max_endosos + 1):
        opts_num_endosos += f'<option value="{k}">Al menos {k} endoso{"s" if k > 1 else ""}</option>'

    panel_html = f"""
    <style>
        #filter-panel {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            background: rgba(250, 250, 250, 0.95);
            padding: 12px 16px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            border: 1px solid #E0DAD3;
            font-family: Arial, sans-serif;
            font-size: 13px;
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
            max-width: 95%;
        }}
        #filter-panel label {{
            font-weight: bold;
            color: #333;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        #filter-panel select, #filter-panel button {{
            padding: 6px 10px;
            border-radius: 4px;
            border: 1px solid #CCC;
            background-color: #FFF;
            font-size: 12px;
        }}
        #filter-panel button {{
            background-color: #C65A72;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            margin-top: 16px;
        }}
        #filter-panel button:hover {{
            background-color: #A8455B;
        }}

        /* ESTILIZADO DE TARJETAS TAG PARA TOOLTIPS (HOVER) CON AUTO-AJUSTE */
        div.vis-tooltip {{
            position: absolute !important;
            background-color: transparent !important;
            border: none !important;
            padding: 0 !important;
            font-family: Arial, sans-serif !important;
            z-index: 9999 !important;
            pointer-events: none;
        }}
        .custom-tooltip-card {{
            background: #FFFFFF;
            border: 1px solid #E0DAD3;
            border-left: 4px solid #C65A72;
            border-radius: 6px;
            padding: 8px 12px;
            box-shadow: 0 4px 14px rgba(0,0,0,0.15);
            color: #2B2B2B;
            font-size: 12px;
            line-height: 1.4;
            
            /* PROPIEDADES DE ANCHO Y SALTO DE LÍNEA DINÁMICO */
            width: max-content;          /* Se ajusta al tamaño exacto del texto si es corto */
            min-width: 180px;            /* Tamaño mínimo estético */
            max-width: 320px;            /* Ancho máximo en pantalla */
            white-space: normal;         /* Permite saltos de línea automáticos */
            overflow-wrap: break-word;   /* Parte las palabras largas si superan el max-width */
            word-break: break-word;      /* Asegura el quiebre de texto en cualquier navegador */
        }}
        .custom-tooltip-card strong {{
            color: #1A1A1A;
        }}
    </style>

    <div id="filter-panel">
        <label>Min. Endosos:
            <select id="sel-min-endosos" onchange="filterByEndosos(this.value)">
                {opts_num_endosos}
            </select>
        </label>

        <label>Bono (N° Cepia):
            <select id="sel-bono" onchange="applyIsolationFilter(this.value, 'bono')">
                <option value="">-- Todos --</option>
                {opts_bonos}
            </select>
        </label>

        <label>Endosatario:
            <select id="sel-endosatario" onchange="applyIsolationFilter(this.value, 'endosatario')">
                <option value="">-- Todos --</option>
                {opts_endosatarios}
            </select>
        </label>

        <label>Beneficiario:
            <select id="sel-beneficiario" onchange="applyIsolationFilter(this.value, 'beneficiario')">
                <option value="">-- Todos --</option>
                {opts_beneficiarios}
            </select>
        </label>

        <button onclick="resetZoom()">Restablecer Vista</button>
    </div>

    <script>
        var originalNodes = [];
        var originalEdges = [];
        var initialPositions = {{}};
        var currentIsolatedValue = null;
        var currentIsolatedType = null;

        // PARSER DE TOOLTIP HTML PARA EVITAR MOSTRAR ETIQUETAS BR / B
        network.once("beforeDrawing", function() {{
            var allNodes = nodes.get();
            var updates = [];

            allNodes.forEach(function(node) {{
                if (node.title && typeof node.title === 'string') {{
                    var container = document.createElement('div');
                    container.className = 'custom-tooltip-card';
                    container.innerHTML = node.title;
                    updates.push({{ id: node.id, title: container }});
                }}
            }});

            if (updates.length > 0) {{
                nodes.update(updates);
            }}
        }});

        // 1. REGISTRO FÍSICO INICIAL Y COORDENADAS
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
        }});

        // RE-POBLAR SELECTORES HTML EN FUNCIÓN DEL FILTRO ACTIVO
        function updateSelectDropdowns(validNodeIds) {{
            var selBono = document.getElementById('sel-bono');
            var selEndo = document.getElementById('sel-endosatario');
            var selBene = document.getElementById('sel-beneficiario');

            var valBono = selBono.value;
            var valEndo = selEndo.value;
            var valBene = selBene.value;

            var bonosList = [];
            var endoList = [];
            var beneList = [];

            originalNodes.forEach(function(n) {{
                if (!validNodeIds || validNodeIds.has(n.id)) {{
                    if (n.group === 'bono') bonosList.push(n.id);
                    if (n.group === 'endosatario') endoList.push(n.id);
                    if (n.group === 'beneficiario') beneList.push(n.id);
                }}
            }});

            bonosList.sort(); endoList.sort(); beneList.sort();

            selBono.innerHTML = '<option value="">-- Todos --</option>' + bonosList.map(b => `<option value="${{b}}">${{b}}</option>`).join('');
            selEndo.innerHTML = '<option value="">-- Todos --</option>' + endoList.map(e => `<option value="${{e}}">${{e}}</option>`).join('');
            selBene.innerHTML = '<option value="">-- Todos --</option>' + beneList.map(b => `<option value="${{b}}">${{b}}</option>`).join('');

            selBono.value = bonosList.includes(valBono) ? valBono : "";
            selEndo.value = endoList.includes(valEndo) ? valEndo : "";
            selBene.value = beneList.includes(valBene) ? valBene : "";
        }}

        // 2. FILTRO INDEPENDIENTE Y CASCADA DE CANTIDAD DE ENDOSOS
        function filterByEndosos(minCount) {{
            minCount = parseInt(minCount, 10);
            
            currentIsolatedValue = null;
            currentIsolatedType = null;

            if (minCount === 0) {{
                nodes.update(originalNodes.map(n => ({{ id: n.id, hidden: false }})));
                edges.update(originalEdges.map(e => ({{ id: e.id, hidden: false }})));
                updateSelectDropdowns(null);
                return;
            }}

            var validEdges = originalEdges.filter(e => e.cantEndosos >= minCount);
            var validNodeIds = new Set();
            validEdges.forEach(function(e) {{
                validNodeIds.add(e.from);
                validNodeIds.add(e.to);
            }});

            edges.update(originalEdges.map(e => ({{ id: e.id, hidden: e.cantEndosos < minCount }})));
            nodes.update(originalNodes.map(n => ({{ id: n.id, hidden: !validNodeIds.has(n.id) }})));

            updateSelectDropdowns(validNodeIds);
        }}

        // 3. AISLAMIENTO EXCLUSIVO DE NODOS
        function applyIsolationFilter(selectedValue, type) {{
            if (type !== 'bono') document.getElementById('sel-bono').value = "";
            if (type !== 'endosatario') document.getElementById('sel-endosatario').value = "";
            if (type !== 'beneficiario') document.getElementById('sel-beneficiario').value = "";

            if (!selectedValue) {{
                var minCount = parseInt(document.getElementById('sel-min-endosos').value, 10);
                filterByEndosos(minCount);
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
                    if (edge.from === selectedValue || edge.to === selectedValue) {{
                        if (edge.bono) activeBonos.add(edge.bono);
                    }}
                }});
            }}

            originalEdges.forEach(function(edge) {{
                if (activeBonos.has(edge.bono)) {{
                    activeEdges.add(edge.id);
                    activeNodes.add(edge.from);
                    activeNodes.add(edge.to);
                }}
            }});

            var minCount = parseInt(document.getElementById('sel-min-endosos').value, 10);

            nodes.update(originalNodes.map(n => ({{
                id: n.id,
                hidden: !activeNodes.has(n.id)
            }})));

            edges.update(originalEdges.map(e => ({{
                id: e.id,
                hidden: !activeEdges.has(e.id) || (minCount > 0 && e.cantEndosos < minCount)
            }})));

            network.fit({{ nodes: Array.from(activeNodes), animation: {{ duration: 600 }} }});
        }}

        // 4. INTERACCIÓN AL HACER CLIC EN UN NODO O ARISTA
        network.on("click", function (params) {{
            setTimeout(function() {{ network.unselectAll(); }}, 50);

            if (params.nodes.length > 0) {{
                var selectedNodeId = params.nodes[0];
                var clickedNode = nodes.get(selectedNodeId);

                if (clickedNode) {{
                    var type = clickedNode.group;
                    if (currentIsolatedValue === selectedNodeId && currentIsolatedType === type) {{
                        applyIsolationFilter("", type);
                        return;
                    }}
                    if (type === 'bono') document.getElementById('sel-bono').value = selectedNodeId;
                    else if (type === 'endosatario') document.getElementById('sel-endosatario').value = selectedNodeId;
                    else if (type === 'beneficiario') document.getElementById('sel-beneficiario').value = selectedNodeId;

                    applyIsolationFilter(selectedNodeId, type);
                }}
            }} else if (params.edges.length > 0) {{
                var edgeId = params.edges[0];
                var clickedEdge = edges.get(edgeId);

                if (clickedEdge && clickedEdge.bono) {{
                    var bonoId = clickedEdge.bono;
                    if (currentIsolatedValue === bonoId && currentIsolatedType === 'bono') {{
                        applyIsolationFilter("", 'bono');
                        return;
                    }}
                    document.getElementById('sel-bono').value = bonoId;
                    applyIsolationFilter(bonoId, 'bono');
                }}
            }} else {{
                var minCount = parseInt(document.getElementById('sel-min-endosos').value, 10);
                filterByEndosos(minCount);
            }}
        }});

        // 5. RESTABLECER POSICIONES Y ESTADO COMPLETO
        function resetZoom() {{
            document.getElementById('sel-min-endosos').value = "0";
            currentIsolatedValue = null;
            currentIsolatedType = null;

            updateSelectDropdowns(null);

            var nodeUpdates = [];
            for (var nodeId in initialPositions) {{
                nodeUpdates.push({{
                    id: nodeId,
                    x: initialPositions[nodeId].x,
                    y: initialPositions[nodeId].y,
                    hidden: false
                }});
            }}
            nodes.update(nodeUpdates);
            edges.update(originalEdges.map(e => ({{ id: e.id, hidden: false }})));

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
