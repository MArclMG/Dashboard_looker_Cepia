import os
import re
import pandas as pd
import folium
from folium.plugins import Fullscreen, LocateControl
import gspread
import google.auth

def obtener_datos_gps():
    # Usa las credenciales generadas por google-github-actions/auth en el runner
    credentials, _ = google.auth.default(scopes=[
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ])
    gc = gspread.authorize(credentials)
    
    # ID o URL del Spreadsheet destino
    spreadsheet_id = os.environ.get("GPS_SPREADSHEET_ID", "1n-edOD5p1K99m2m78SoTlJSnXDU_rY69Vxk5yttPgHg")
    sh = gc.open_by_key(spreadsheet_id)
    worksheet = sh.worksheet("Looker_GPS")
    
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)
    return df

def crear_mapa_rutas(df):
    # Asegurar tipos numéricos y orden cronológico
    df['Latitud'] = pd.to_numeric(df['Latitud'], errors='coerce')
    df['Longitud'] = pd.to_numeric(df['Longitud'], errors='coerce')
    df['Velocidad'] = pd.to_numeric(df['Velocidad'], errors='coerce').fillna(0)
    df = df.dropna(subset=['Latitud', 'Longitud'])
    df = df.sort_values(by=['Vehículo', 'Timestamp'])

    # Centrar en el promedio de las coordenadas (Maule / O'Higgins)
    lat_centro = df['Latitud'].mean()
    lng_centro = df['Longitud'].mean()

    # Mapa base con soporte para pantalla completa y selector de capas
    m = folium.Map(
        location=[lat_centro, lng_centro],
        zoom_start=9,
        tiles="CartoDB positron",
        control_scale=True
    )

    # Agregar capas adicionales útiles
    folium.TileLayer('OpenStreetMap', name='Calles (OpenStreetMap)').add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satélite (Esri World Imagery)'
    ).add_to(m)

    colores = {
        'LHJL-14': '#2563eb', # Azul
        'PRYG-42': '#059669', # Verde
        'LHJL-13': '#7c3aed', # Morado
        'PTJP-73': '#ea580c'  # Naranja
    }

    # Agrupar por vehículo y crear una capa independiente por cada uno
    for vehiculo, grupo in df.groupby('Vehículo'):
        color = colores.get(vehiculo, '#4b5563')
        fg_vehiculo = folium.FeatureGroup(name=f"Rutas: {vehiculo}", show=True)

        coords_ruta = grupo[['Latitud', 'Longitud']].values.tolist()

        # 1. Trazado continuo de la ruta
        folium.PolyLine(
            locations=coords_ruta,
            color=color,
            weight=4,
            opacity=0.75,
            tooltip=f"Flota: {vehiculo}"
        ).add_to(fg_vehiculo)

        # 2. Marcador de Inicio y Fin de jornada
        primer_punto = grupo.iloc[0]
        ultimo_punto = grupo.iloc[-1]

        folium.CircleMarker(
            location=[primer_punto['Latitud'], primer_punto['Longitud']],
            radius=7,
            color='#16a34a',
            fill=True,
            fill_color='#22c55e',
            fill_opacity=1.0,
            popup=f"<b>INICIO</b><br>{vehiculo}<br>{primer_punto['Fecha']} {primer_punto['Hora']}"
        ).add_to(fg_vehiculo)

        folium.CircleMarker(
            location=[ultimo_punto['Latitud'], ultimo_punto['Longitud']],
            radius=7,
            color='#1e293b',
            fill=True,
            fill_color='#0f172a',
            fill_opacity=1.0,
            popup=f"<b>FIN</b><br>{vehiculo}<br>{ultimo_punto['Fecha']} {ultimo_punto['Hora']}"
        ).add_to(fg_vehiculo)

        # 3. Puntos con Exceso de Velocidad (>= 120 km/h) en Rojo
        excesos = grupo[grupo['Velocidad'] >= 120]
        for _, row in excesos.iterrows():
            folium.CircleMarker(
                location=[row['Latitud'], row['Longitud']],
                radius=5,
                color='#b91c1c',
                fill=True,
                fill_color='#ef4444',
                fill_opacity=0.9,
                tooltip=f"⚠️ {vehiculo} - {row['Velocidad']} km/h ({row['Hora']})",
                popup=f"""
                <div style='font-family:sans-serif; font-size:12px;'>
                    <b style='color:#b91c1c;'>EXCESO DE VELOCIDAD</b><br>
                    <b>Vehículo:</b> {vehiculo} ({row.get('Placa', '')})<br>
                    <b>Velocidad:</b> {row['Velocidad']} km/h<br>
                    <b>Fecha/Hora:</b> {row['Fecha']} {row['Hora']}<br>
                    <b>Sentido:</b> {row.get('Sentido_Ruta', '')}<br>
                    <b>Lugar:</b> {row.get('Direccion', '')}
                </div>
                """
            ).add_to(fg_vehiculo)

        # 4. Flechas direccionales cada 25 puntos en movimiento
        muestras_flechas = grupo[grupo['Velocidad'] > 0].iloc[::25]
        for _, row in muestras_flechas.iterrows():
            flecha_char = str(row.get('Flecha', '➤'))
            html_arrow = f"""
            <div style="font-size: 14px; font-weight: bold; color: {color}; text-shadow: 1px 1px 2px white;">
                {flecha_char}
            </div>
            """
            folium.Marker(
                location=[row['Latitud'], row['Longitud']],
                icon=folium.DivIcon(html=html_arrow, icon_size=(20, 20), icon_anchor=(10, 10)),
                tooltip=f"{row['Hora']} | {row['Velocidad']} km/h"
            ).add_to(fg_vehiculo)

        fg_vehiculo.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    Fullscreen().add_to(m)
    return m

if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    df_gps = obtener_datos_gps()
    mapa = crear_mapa_rutas(df_gps)
    salida = os.path.join("docs", "rutas_gps.html")
    mapa.save(salida)
    print(f"Mapa generado con éxito en: {salida}")
