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

def acortar_texto(texto, max_len=22):
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

    print("➡️ Procesando datos y forzando paleta Salvia / Terracota / Crema...")
    
    bonos_set = set()
    endosatarios_set = set()
    beneficiarios_set = set()
    cant_endosos_set = set()

    net = Network(
        height="750px", 
        width="100%", 
        directed=True, 
        notebook=False, 
        bgcolor="#FAFAFA", 
        font_color="#2B2B2B"
    )
    
    # 1. OPCIONES GLOBALES DE INTERACCIÓN Y GRUPOS (Corrige colores y arrastre pegajoso)
    net.set_options("""
    {
      "interaction": {
        "hover": true,
        "dragNodes": true,
        "dragView": true,
        "selectable": true,
        "multiselect": false
      },
      "physics": {
        "barnesHut": {
          "gravitationalConstant": -3000,
          "centralGravity": 0.3,
          "springLength": 140
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

    for _, row in df.iterrows():
        cepia_id = normalizar_texto(row.get('N° Cepia', ''))
        beneficiario_id = normalizar_texto(row.get('Beneficiario', ''))

        if not cepia_id: 
            continue

        bonos_set.add(cepia_id)
        if beneficiario_id:
            beneficiarios_set.add(beneficiario_id)

        # 2. NODO ORIGEN: Bono / N° Cepia (Salvia #A8BFA8)
        net.add_node(
            cepia_id, 
            label=f"Bono:\n{cepia_id}", 
            title=f"<b>Bono (N° Cepia):</b> {cepia_id}<br><b>Beneficiario Final:</b> {beneficiario_id}", 
            group="bono",
            size=26,
            font={"size": 13, "face": "arial", "bold": True, "color": "#1C2B1C"}
        )

        # 3. NODO FINAL: Beneficiario (Crema #F0D9A7 - Círculo reducido)
        if beneficiario_id:
            label_benef = acortar_texto(beneficiario_id, 20)
            net.add_node(
                beneficiario_id, 
                label=f"Benef:\n{label_benef}", 
                title=f"<b>Beneficiario Completo:</b><br>{beneficiario_id}", 
                group="beneficiario",
                size=18,
                font={"size": 10, "face": "arial", "color": "#3D3015"}
            )

        # 4. ENDOSATARIOS INTERMEDIOS (Terracota #D8A48F - Rectángulo)
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

                label_endo = acortar_texto(endosatario_id, 22)
                net.add_node(
                    endosatario_id, 
                    label=label_endo, 
                    title=f"<b>Endosatario Completo:</b><br>{endosatario_id}", 
                    group="endosatario",
                    size=16,
                    font={"size": 10, "face": "arial", "color": "#3B1E13"}
                )
                
                label_arista = f"Endoso {i}\n{fecha_val}" if fecha_val else f"Endoso {i}"
                
                net.add_edge(
                    nodo_actual, 
                    endosatario_id, 
                    label=label_arista, 
                    title=f"Bono: {cepia_id} | Fecha: {fecha_val}",
                    color={"color": "#B9B4AE", "highlight": "#C65A72"},
                    width=2,
                    bono=cepia_id,
                    arrows={"to": {"enabled": True, "scaleFactor": 1.1}},
                    smooth={"type": "curvedCW", "roundness": 0.2},
                    font={"size": 8, "align": "middle", "color": "#666666"}
                )
                
                nodo_actual = endosatario_id
            i += 1

        cant_endosos_set.add(num_endosos)

        if beneficiario_id:
            net.add_edge(
                nodo_actual, 
                beneficiario_id, 
                label="Asignado a", 
                title=f"Bono: {cepia_id} | Registro de Beneficiario", 
                color={"color": "#B9B4AE", "highlight": "#C65A72"}, 
                width=2,
                dashes=True,
                bono=cepia_id,
                arrows={"to": {"enabled": True, "scaleFactor": 1.1}},
                smooth={"type": "curvedCW", "roundness": 0.15},
                font={"size": 8, "align": "middle", "color": "#666666"}
            )

    os.makedirs("docs", exist_ok=True)
    output_path = os.path.join("docs", "index.html")
    net.write_html(output_path)

    inyectar_panel_filtros(output_path, bonos_set, endosatarios_set, beneficiarios_set, cant_endosos_set)
    print(f"✅ Grafo corregido e impreso en: {output_path}")


def inyectar_panel_filtros(html_path, bonos, endosatarios, beneficiarios, cant_endosos):
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
        var originalNodes = [];
        var originalEdges = [];

        network.once("afterDrawing", function () {{
            originalNodes = JSON.parse(JSON.stringify(nodes.get()));
            originalEdges = JSON.parse(JSON.stringify(edges.get()));
        }});

        // INTERACCIÓN DE CLIC LIMPIA (Evita retención/pegado de drag)
        network.on("click", function (params) {{
            // Deseleccionar automáticamente para evitar que el nodo quede "fijo" o enganchado al cursor
            setTimeout(function() {{ network.unselectAll(); }}, 50);

            if (params.nodes.length > 0) {{
                var selectedNodeId = params.nodes[0];
                var clickedNode = nodes.get(selectedNodeId);

                if (clickedNode && clickedNode.group === 'bono') {{
                    document.getElementById('sel-bono').value = selectedNodeId;
                    highlightPath(selectedNodeId, 'bono');
                }} else if (clickedNode && clickedNode.group === 'endosatario') {{
                    document.getElementById('sel-endosatario').value = selectedNodeId;
                    highlightPath(selectedNodeId, 'endosatario');
                }} else if (clickedNode && clickedNode.group === 'beneficiario') {{
                    document.getElementById('sel-beneficiario').value = selectedNodeId;
                    highlightPath(selectedNodeId, 'beneficiario');
                }}
            }} else if (params.edges.length > 0) {{
                var edgeId = params.edges[0];
                var clickedEdge = edges.get(edgeId);

                if (clickedEdge && clickedEdge.bono) {{
                    document.getElementById('sel-bono').value = clickedEdge.bono;
                    highlightPath(clickedEdge.bono, 'bono');
                }}
            }} else {{
                resetZoom();
            }}
        }});

        function highlightPath(selectedValue, type) {{
            if (!selectedValue) {{
                resetZoom();
                return;
            }}

            if (type !== 'bono') document.getElementById('sel-bono').value = "";
            if (type !== 'endosatario') document.getElementById('sel-endosatario').value = "";
            if (type !== 'beneficiario') document.getElementById('sel-beneficiario').value = "";

            nodes.update(originalNodes);
            edges.update(originalEdges);

            var activeBonos = new Set();
            var activeNodes = new Set();
            var activeEdges = new Set();

            if (type === 'bono') {{
                activeBonos.add(selectedValue);
            }} else {{
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

            // Resaltado de trazo con carmín #C65A72
            var updateEdges = [];
            activeEdges.forEach(function(edgeId) {{
                updateEdges.push({{
                    id: edgeId,
                    color: {{ color: '#C65A72', highlight: '#C65A72' }},
                    width: 4
                }});
            }});
            edges.update(updateEdges);

            // Borde grueso en nodos activos
            var updateNodes = [];
            activeNodes.forEach(function(nodeId) {{
                var baseNode = originalNodes.find(n => n.id === nodeId);
                if (baseNode) {{
                    updateNodes.push({{
                        id: nodeId,
                        color: {{
                            background: baseNode.color ? baseNode.color.background : undefined,
                            border: '#C65A72'
                        }},
                        borderWidth: 3
                    }});
                }}
            }});
            nodes.update(updateNodes);

            if (type === 'bono' && activeNodes.size > 0) {{
                network.fit({{
                    nodes: Array.from(activeNodes),
                    animation: {{ duration: 800, easingFunction: "easeInOutQuad" }}
                }});
            }} else {{
                network.focus(selectedValue, {{
                    scale: 1.1,
                    animation: {{ duration: 800, easingFunction: "easeInOutQuad" }}
                }});
            }}
        }}

        function resetZoom() {{
            document.getElementById('sel-bono').value = "";
            document.getElementById('sel-endosatario').value = "";
            document.getElementById('sel-beneficiario').value = "";

            if (originalNodes.length > 0 && originalEdges.length > 0) {{
                nodes.update(originalNodes);
                edges.update(originalEdges);
            }}

            network.fit({{ animation: {{ duration: 800 }} }});
            network.unselectAll();
        }}
    </script>
    """

    new_content = content.replace("</body>", f"{panel_html}\n</body>")

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(new_content)


if __name__ == "__main__":
    main()
