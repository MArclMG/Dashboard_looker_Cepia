import os
import pandas as pd
import gspread
from google.auth import default
from pyvis.network import Network

def main():
    print("➡️ Autenticando en GCP mediante Workload Identity Federation...")
    # Obtiene credenciales automáticamente del entorno OIDC de GitHub Actions
    credentials, project = default(scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'])
    gc = gspread.authorize(credentials)

    # ------------------------------------------------------------------
    # 1. LECTURA DE DATOS (Pestaña específica )
    # ------------------------------------------------------------------
    spreadsheet_url = os.environ.get("SPREADSHEET_URL")
    
    if not spreadsheet_url:
        raise ValueError("❌ ERROR: La variable de entorno 'SPREADSHEET_URL' no está configurada.")

    print("➡️ Conectando a Google Sheets...")
    sh = gc.open_by_url(spreadsheet_url)
    
    # Se selecciona la pestaña directamente por su nombre
    worksheet = sh.worksheet("Resumen") 
    
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)

    # ------------------------------------------------------------------
    # 2. CONSTRUCCIÓN DEL GRAFO CON PYVIS
    # ------------------------------------------------------------------
    print("➡️ Generando grafo con PyVis...")
    net = Network(height="750px", width="100%", bgcolor="#ffffff", font_color="black", directed=True)
    
    # Opciones físicas para un renderizado dinámico fluido
    net.force_atlas_2based()

    # Asumiendo columnas origen/destino en tu hoja (Ajusta los nombres según tu Sheet)
    # Ejemplo: 'Empresa_Origen' -> 'Empresa_Destino'
    for _, row in df.iterrows():
        origen = str(row['Origen'])
        destino = str(row['Destino'])
        monto = str(row.get('Monto', ''))

        # Añadir nodos sin duplicar
        net.add_node(origen, label=origen, title=origen, color="#2B7CE9")
        net.add_node(destino, label=destino, title=destino, color="#5A9E32")
        
        # Añadir arista/conexión
        net.add_edge(origen, destino, title=f"Endoso: {monto}")

    # ------------------------------------------------------------------
    # 3. GUARDAR EL ARCHIVO HTML
    # ------------------------------------------------------------------
    os.makedirs("docs", exist_ok=True)
    output_path = "docs/index.html"
    
    net.write_html(output_path)
    print(f"✅ Grafo generado exitosamente en: {output_path}")

if __name__ == "__main__":
    main()
