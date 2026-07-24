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

    net = Network(
        height="850px", 
        width="100%", 
        directed=True, 
        notebook=False, 
        bgcolor="#FAFAFA", 
        font_color="#2B2B2B"
    )
    
    # CONFIGURACIÓN DE FÍSICA ESTABILIZADA Y CONGELADA
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
            val_endo = normalizar_texto(row.get(col_check, ''))
            if val_endo:
                num_endosos_bono += 1
            i_temp += 1

        if num_endosos_bono > max_endosos_encontrados:
            max_endosos_encontrados = num_endosos_bono

        bonos_set.add(cepia_id)
        if beneficiario_id:
            beneficiarios_set.add(beneficiario_id)

        net.add_node(
            cepia_id, 
            label=f"Bono:\n{cepia_id}", 
            title=f"<b>Bono (N° Cepia):</b> {cepia_id}<br><b>Endosos:</b> {num_endosos_bono}<br><b>Beneficiario Final:</b> {beneficiario_id}", 
            group="bono",
            cantEndosos=num_endosos_bono,
            size=22,
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
                endosatarios_set.add(endosatario_id)

                label_endo = acortar_texto(endosatario_id, 14)
                net.add_node(
                    endosatario_id, 
                    label=label_endo, 
                    title=f"<b>Endosatario Completo:</b><br>{endosatario_id}", 
                    group="endosatario",
                    shape="box",
                    widthConstraint={"maximum": 110},
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
    print(f"✅ Grafo procesado con función Toggle de resaltado en: {output_path}")


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
    </style>

    <div id="filter-panel">
        <label>Min. Endosos:
            <select id="sel-min-endosos" onchange="filterByEndosos(this.value)">
                {opts_num_endosos}
            </select>
        </label>

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
        var currentHighlightedValue = null;
        var currentHighlightedType = null;

        network.once("stabilizationIterationsDone", function() {{
            network.setOptions({{ physics: {{ enabled: false }} }});
        }});

        network.once("afterDrawing", function () {{
            originalNodes = JSON.parse(JSON.stringify(nodes.get()));
            originalEdges = JSON.parse(JSON.stringify(edges.get()));
        }});

        function filterByEndosos(minCount) {{
            minCount = parseInt(minCount, 10);

            clearHighlightState();

            document.getElementById('sel-bono').value = "";
            document.getElementById('sel-endosatario').value = "";
            document.getElementById('sel-beneficiario').value = "";

            if (minCount === 0) {{
                nodes.update(originalNodes.map(n => ({{ id: n.id, hidden: false }})));
                edges.update(originalEdges.map(e => ({{ id: e.id, hidden: false }})));
                return;
            }}

            var validEdges = originalEdges.filter(function(edge) {{
                return edge.cantEndosos >= minCount;
            }});

            var validNodeIds = new Set();
            validEdges.forEach(function(edge) {{
                validNodeIds.add(edge.from);
                validNodeIds.add(edge.to);
            }});

            var edgeUpdates = originalEdges.map(function(edge) {{
                return {{
                    id: edge.id,
                    hidden: edge.cantEndosos < minCount
                }};
            }});
            edges.update(edgeUpdates);

            var nodeUpdates = originalNodes.map(function(node) {{
                return {{
                    id: node.id,
                    hidden: !validNodeIds.has(node.id)
                }};
            }});
            nodes.update(nodeUpdates);
        }}

        network.on("click", function (params) {{
            setTimeout(function() {{ network.unselectAll(); }}, 50);

            if (params.nodes.length > 0) {{
                var selectedNodeId = params.nodes[0];
                var clickedNode = nodes.get(selectedNodeId);

                if (clickedNode) {{
                    var type = clickedNode.group;
                    
                    // TOGGLE: Si se vuelve a presionar el mismo nodo, se deselecciona
                    if (currentHighlightedValue === selectedNodeId && currentHighlightedType === type) {{
                        clearHighlightState();
                        return;
                    }}

                    if (type === 'bono') document.getElementById('sel-bono').value = selectedNodeId;
                    else if (type === 'endosatario') document.getElementById('sel-endosatario').value = selectedNodeId;
                    else if (type === 'beneficiario') document.getElementById('sel-beneficiario').value = selectedNodeId;

                    highlightPath(selectedNodeId, type);
                }}
            }} else if (params.edges.length > 0) {{
                var edgeId = params.edges[0];
                var clickedEdge = edges.get(edgeId);

                if (clickedEdge && clickedEdge.bono) {{
                    var bonoId = clickedEdge.bono;

                    // TOGGLE PARA ARISTAS
                    if (currentHighlightedValue === bonoId && currentHighlightedType === 'bono') {{
                        clearHighlightState();
                        return;
                    }}

                    document.getElementById('sel-bono').value = bonoId;
                    highlightPath(bonoId, 'bono');
                }}
            }} else {{
                // Clic en el fondo deselecciona
                clearHighlightState();
            }}
        }});

        function clearHighlightState() {{
            currentHighlightedValue = null;
            currentHighlightedType = null;

            document.getElementById('sel-bono').value = "";
            document.getElementById('sel-endosatario').value = "";
            document.getElementById('sel-beneficiario').value = "";

            var minCount = parseInt(document.getElementById('sel-min-endosos').value, 10);

            // Restaurar bordes y colores base respetando el filtro de endosos activo
            var updateEdges = originalEdges.map(function(edge) {{
                return {{
                    id: edge.id,
                    color: {{ color: '#B9B4AE', highlight: '#C65A72' }},
                    width: 1.5,
                    hidden: minCount > 0 ? edge.cantEndosos < minCount : false
                }};
            }});
            edges.update(updateEdges);

            var validNodeIds = new Set();
            if (minCount > 0) {{
                originalEdges.filter(e => e.cantEndosos >= minCount).forEach(e => {{
                    validNodeIds.add(e.from);
                    validNodeIds.add(e.to);
                }});
            }}

            var updateNodes = originalNodes.map(function(node) {{
                return {{
                    id: node.id,
                    color: node.color,
                    borderWidth: 1,
                    hidden: minCount > 0 ? !validNodeIds.has(node.id) : false
                }};
            }});
            nodes.update(updateNodes);
        }}

        function highlightPath(selectedValue, type) {{
            if (!selectedValue) {{
                clearHighlightState();
                return;
            }}

            // Limpiar estado anterior para evitar superposición de resaltados
            clearHighlightState();

            currentHighlightedValue = selectedValue;
            currentHighlightedType = type;

            if (type === 'bono') document.getElementById('sel-bono').value = selectedValue;
            if (type === 'endosatario') document.getElementById('sel-endosatario').value = selectedValue;
            if (type === 'beneficiario') document.getElementById('sel-beneficiario').value = selectedValue;

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

            var updateEdges = [];
            activeEdges.forEach(function(edgeId) {{
                updateEdges.push({{
                    id: edgeId,
                    color: {{ color: '#C65A72', highlight: '#C65A72' }},
                    width: 4
                }});
            }});
            edges.update(updateEdges);

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
        }}

        function resetZoom() {{
            document.getElementById('sel-min-endosos').value = "0";
            clearHighlightState();
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
