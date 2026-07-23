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

    print("➡️ Procesando datos y recolectando listas de filtros...")
    
    bonos_set = set()
    endosatarios_set = set()
    beneficiarios_set = set()
    cant_endosos_set = set()

    net = Network(
        height="750px", 
        width="100%", 
        directed=True, 
        notebook=False, 
        bgcolor="#f8f9fa", 
        font_color="#333333"
    )
    
    net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=120)

    for _, row in df.iterrows():
        cepia_id = normalizar_texto(row.get('N° Cepia', ''))
        beneficiario_id = normalizar_texto(row.get('Beneficiario', ''))

        if not cepia_id: 
            continue

        bonos_set.add(cepia_id)
        if beneficiario_id:
            beneficiarios_set.add(beneficiario_id)

        # 1. NODO PRINCIPAL: Bono / N° Cepia
        net.add_node(
            cepia_id, 
            label=f"Bono:\n{cepia_id}", 
            title=f"<b>Bono (N° Cepia):</b> {cepia_id}<br><b>Beneficiario Final:</b> {beneficiario_id}", 
            color="#005f73", 
            shape="dot", 
            size=28,
            font={"size": 14, "face": "arial", "bold": True}
        )

        # 2. NODO FINAL: Beneficiario
        if beneficiario_id:
            net.add_node(
                beneficiario_id, 
                label=f"Beneficiario:\n{beneficiario_id}", 
                title=f"<b>Beneficiario:</b> {beneficiario_id}", 
                color="#2a9d8f", 
                shape="square", 
                size=20,
                font={"size": 11, "face": "arial"}
            )

        # 3. CADENA DE ENDOSATARIOS DINÁMICOS
        nodo_actual = cepia_id
        i = 1
        num_endosos = 0
        
        while True:
            col_endosatario = next((c for c in df.columns if c.strip().lower() == f'endosatario_{i}'), None)
            col_fecha = next((c for c in df.columns if c.strip().lower() == f'endoso_fecha_{i}'), None)

            if not col_endosatario:
                break

            endosatario_id = normalizar_texto(row.get(col_endosatario, ''))
            fecha_val = str(row.get(col_fecha, '')).strip() if col_fecha else ""

            if endosatario_id:
                num_endosos += 1
                endosatarios_set.add(endosatario_id)

                net.add_node(
                    endosatario_id, 
                    label=f"{endosatario_id}", 
                    title=f"<b>Endosatario:</b> {endosatario_id}", 
                    color="#ee9b00", 
                    shape="ellipse",
                    size=18,
                    font={"size": 11, "face": "arial"}
                )
                
                label_arista = f"Endoso {i}: {fecha_val}" if fecha_val else f"Endoso {i}"
                net.add_edge(
                    nodo_actual, 
                    endosatario_id, 
                    label=label_arista, 
                    title=f"Fecha: {fecha_val}",
                    color="#ca6702",
                    font={"size": 9, "align": "top"}
                )
                
                nodo_actual = endosatario_id
            i += 1

        cant_endosos_set.add(num_endosos)

        if beneficiario_id:
            net.add_edge(
                nodo_actual, 
                beneficiario_id, 
                label="Asignado a", 
                title="Registro de Beneficiario", 
                color="#94d2bd", 
                dashes=True
            )

    os.makedirs("docs", exist_ok=True)
    output_path = os.path.join("docs", "index.html")
    net.write_html(output_path)

    inyectar_panel_filtros(output_path, bonos_set, endosatarios_set, beneficiarios_set, cant_endosos_set)
    print(f"✅ Grafo con tramado de ruta y atenuación generado en: {output_path}")


def inyectar_panel_filtros(html_path, bonos, endosatarios, beneficiarios, cant_endosos):
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()

    opts_bonos = "".join([f'<option value="{b}">{b}</option>' for b in sorted(bonos)])
    opts_endosatarios = "".join([f'<option value="{e}">{e}</option>' for e in sorted(endosatarios)])
    opts_beneficiarios = "".join([f'<option value="{b}">{b}</option>' for b in sorted(beneficiarios)])

    panel_html = f"""
    <style>
        #filter-panel {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            background: rgba(255, 255, 255, 0.95);
            padding: 12px 16px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
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
            border: 1px solid #ccc;
            background-color: #fff;
            font-size: 12px;
        }}
        #filter-panel button {{
            background-color: #005f73;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: bold;
            margin-top: 16px;
        }}
        #filter-panel button:hover {{
            background-color: #0a9396;
        }}
    </style>

    <div id="filter-panel">
        <label>Bono (N° Cepia):
            <select id="sel-bono" onchange="highlightPath(this.value, 'bono')">
                <option value="">-- Todos --</option>
                {opts_bonos}
            </select>
        </label>

        <label>Endosatario:
            <select id="sel-endosatario" onchange="highlightPath(this.value, 'endosatario')">
                <option value="">-- Todos --</option>
                {opts_endosatarios}
            </select>
        </label>

        <label>Beneficiario:
            <select id="sel-beneficiario" onchange="highlightPath(this.value, 'beneficiario')">
                <option value="">-- Todos --</option>
                {opts_beneficiarios}
            </select>
        </label>

        <button onclick="resetZoom()">Restablecer Vista</button>
    </div>

    <script>
        var allNodes = null;
        var allEdges = null;

        // Guardar estado original de los elementos una vez cargada la red
        network.once("afterDrawing", function () {{
            allNodes = nodes.get({{returnType: "Object"}});
            allEdges = edges.get({{returnType: "Object"}});
        }});

        function highlightPath(selectedNodeId, type) {{
            if (!selectedNodeId) {{
                resetZoom();
                return;
            }}

            // Sincronizar selectores
            if (type !== 'bono') document.getElementById('sel-bono').value = "";
            if (type !== 'endosatario') document.getElementById('sel-endosatario').value = "";
            if (type !== 'beneficiario') document.getElementById('sel-beneficiario').value = "";

            var connectedNodes = new Set();
            var connectedEdges = new Set();

            // Algoritmo de rastreo en ambas direcciones (origen <-> destino)
            function traceConnected(nodeId) {{
                connectedNodes.add(nodeId);
                
                // Obtener aristas conectadas al nodo
                var nodeEdges = network.getConnectedEdges(nodeId);
                nodeEdges.forEach(function(edgeId) {{
                    var edge = edges.get(edgeId);
                    connectedEdges.add(edgeId);
                    
                    if (edge.from === nodeId && !connectedNodes.has(edge.to)) {{
                        traceConnected(edge.to);
                    }}
                    if (edge.to === nodeId && !connectedNodes.has(edge.from)) {{
                        traceConnected(edge.from);
                    }}
                }});
            }}

            traceConnected(selectedNodeId);

            // Modificar opacidad de todos los nodos
            var updateNodes = [];
            for (var nodeId in allNodes) {{
                if (connectedNodes.has(nodeId)) {{
                    updateNodes.push({{ id: nodeId, opacity: 1.0, font: {{ color: '#000000' }} }});
                }} else {{
                    updateNodes.push({{ id: nodeId, opacity: 0.1, font: {{ color: 'rgba(0,0,0,0.1)' }} }});
                }}
            }}
            nodes.update(updateNodes);

            // Modificar opacidad de todas las aristas/líneas
            var updateEdges = [];
            for (var edgeId in allEdges) {{
                if (connectedEdges.has(edgeId)) {{
                    updateEdges.push({{ id: edgeId, opacity: 1.0 }});
                }} else {{
                    updateEdges.push({{ id: edgeId, opacity: 0.05 }});
                }}
            }}
            edges.update(updateEdges);

            // Enfocar la cámara en el grupo de nodos seleccionados
            network.fit({{
                nodes: Array.from(connectedNodes),
                animation: {{ duration: 1000, easingFunction: "easeInOutQuad" }}
            }});
        }}

        function resetZoom() {{
            document.getElementById('sel-bono').value = "";
            document.getElementById('sel-endosatario').value = "";
            document.getElementById('sel-beneficiario').value = "";

            if (allNodes && allEdges) {{
                var updateNodes = [];
                for (var nodeId in allNodes) {{
                    updateNodes.push({{ id: nodeId, opacity: 1.0, font: {{ color: '#333333' }} }});
                }}
                nodes.update(updateNodes);

                var updateEdges = [];
                for (var edgeId in allEdges) {{
                    updateEdges.push({{ id: edgeId, opacity: 1.0 }});
                }}
                edges.update(updateEdges);
            }}

            network.fit({{ animation: {{ duration: 1000 }} }});
            network.unselectAll();
        }}
    </script>
    """

    new_content = content.replace("</body>", f"{panel_html}\n</body>")

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_content)


if __name__ == "__main__":
    main()
