import os
import pandas as pd
import gspread
import google.auth
from google.auth.transport.requests import Request
from pyvis.network import Network

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

    # Limpiar espacios en los nombres de las columnas
    df.columns = df.columns.str.strip()

    print("➡️ Generando grafo con PyVis (con etiquetas)...")
    net = Network(height="750px", width="100%", directed=True, notebook=False, bgcolor="#f4f4f4", font_color="black")
    net.barnes_hut()

    for _, row in df.iterrows():
        # Extraer IDs únicos de las columnas clave
        cepia_id = str(row.get('N° Cepia', '')).strip()
        beneficiario_id = str(row.get('Beneficiario', '')).strip()

        if not cepia_id: 
            continue # Omitir filas sin ID

        # --- CONFIGURAR NODOS PRINCIPALES ---
        
        # 1. Nodo CEPIA: Label visible y Título hover
        net.add_node(
            cepia_id, 
            label=f"Cepia\n{cepia_id}", 
            title=f"<b>N° Cepia:</b> {cepia_id}", 
            color="#1f77b4", 
            shape="dot", 
            size=25
        )

        # 2. Nodo BENEFICIARIO: Label visible y Título hover
        if beneficiario_id:
            net.add_node(
                beneficiario_id, 
                label=f"Beneficiario\n{beneficiario_id}", 
                title=f"<b>Destinatario Final:</b><br>{beneficiario_id}", 
                color="#2ca02c", 
                shape="square", 
                size=20
            )

        # --- CONFIGURAR ENDOSATARIOS DINÁMICOS ---
        nodo_actual = cepia_id
        i = 1
        while f'endosatario_{i}' in df.columns:
            endosatario_id = str(row.get(f'endosatario_{i}', '')).strip()
            fecha_val = str(row.get(f'endoso_fecha_{i}', '')).strip()
            
            if endosatario_id and endosatario_id.lower() != 'nan':
                # Nodo ENDOSATARIO: Label y Hover con fecha
                net.add_node(
                    endosatario_id, 
                    label=f"{endosatario_id}", 
                    title=f"<b>Endosatario {i}:</b> {endosatario_id}<br><b>Fecha:</b> {fecha_val}", 
                    color="#ff7f0e", 
                    shape="ellipse"
                )
                
                # Arista con etiqueta de Fecha visible y Hover
                label_arista = f"{fecha_val}" if fecha_val else ""
                net.add_edge(
                    nodo_actual, 
                    endosatario_id, 
                    label=label_arista, 
                    title=f"Endoso {i}: {label_arista}"
                )
                
                nodo_actual = endosatario_id
            i += 1

        # Conectar el último eslabón al Beneficiario
        if beneficiario_id:
            net.add_edge(
                nodo_actual, 
                beneficiario_id, 
                label="➡️ Beneficiario", 
                title="Destino Final", 
                color="#2ca02c", 
                weight=2
            )

    # Asegurar directorio y escribir HTML
    os.makedirs("docs", exist_ok=True)
    output_path = os.path.join("docs", "index.html")
    net.write_html(output_path)
    print(f"✅ Grafo generado con etiquetas en: {output_path}")

if __name__ == "__main__":
    main()
