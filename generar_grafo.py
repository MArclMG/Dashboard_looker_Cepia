import os
import pandas as pd
import gspread
import google.auth
from google.auth.transport.requests import Request
from pyvis.network import Network

def main():
    print("➡️ Autenticando en GCP mediante Workload Identity Federation...")
    
    # Definir los scopes requeridos para Google Sheets y Drive
    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    # Obtener credenciales explícitamente con scopes
    credentials, project = google.auth.default(scopes=SCOPES)
    
    # Forzar el refresco de token si es necesario
    if not credentials.valid:
        credentials.refresh(Request())

    gc = gspread.authorize(credentials)

    spreadsheet_url = os.environ.get("SPREADSHEET_URL")
    print("➡️ Conectando a Google Sheets...")
    sh = gc.open_by_url(spreadsheet_url)
    
    # ... resto del código sin cambios ...
    
    # Toma la primera hoja de trabajo
    sheet = sh.sheet1 
    data = sheet.get_all_records()
    df = pd.DataFrame(data)

    # Limpiar espacios en los nombres de las columnas por seguridad
    df.columns = df.columns.str.strip()
    print("Columnas detectadas:", df.columns.tolist())

    print("➡️ Generando grafo con PyVis...")
    net = Network(height="750px", width="100%", directed=True, notebook=False)
    net.barnes_hut()

    for _, row in df.iterrows():
        cepia = str(row.get('N° Cepia', '')).strip()
        beneficiario = str(row.get('Beneficiario', '')).strip()

        if not cepia:
            continue  # Omitir filas vacías

        # Agregar nodo inicial (Cepia) y nodo final (Beneficiario)
        net.add_node(cepia, label=f"Cepia: {cepia}", color="#1f77b4", shape="dot")
        if beneficiario:
            net.add_node(beneficiario, label=f"Beneficiario: {beneficiario}", color="#2ca02c", shape="square")

        # Detectar dinámicamente las columnas de endosatarios
        endosatarios = []
        i = 1
        while f'endosatario_{i}' in df.columns:
            endosatario_val = str(row.get(f'endosatario_{i}', '')).strip()
            fecha_val = str(row.get(f'endoso_fecha_{i}', '')).strip()
            
            # Solo consideramos si el endosatario tiene valor no vacío
            if endosatario_val and endosatario_val.lower() != 'nan':
                endosatarios.append({'nombre': endosatario_val, 'fecha': fecha_val})
            i += 1

        # Construir aristas (conexiones)
        nodo_actual = cepia

        for idx, endoso in enumerate(endosatarios):
            siguiente_nodo = endoso['nombre']
            label_fecha = f"Fecha: {endoso['fecha']}" if endoso['fecha'] else ""
            
            # Nodo intermedio (Endosatario)
            net.add_node(siguiente_nodo, label=f"Endosatario: {siguiente_nodo}", color="#ff7f0e", shape="ellipse")
            
            # Conexión
            net.add_edge(nodo_actual, siguiente_nodo, title=label_fecha, label=label_fecha)
            nodo_actual = siguiente_nodo

        # Conectar el último endosatario (o la Cepia directamente si no hay endosos) al Beneficiario
        if beneficiario:
            net.add_edge(nodo_actual, beneficiario, title="Destino Final", label="Beneficiario")

    # Asegurar directorio de salida para GH Pages
    os.makedirs("docs", exist_ok=True)
    output_path = os.path.join("docs", "index.html")
    
    net.write_html(output_path)
    print(f"✅ Grafo generado exitosamente en: {output_path}")

if __name__ == "__main__":
    main()
