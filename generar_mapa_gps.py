import os
import math
import pandas as pd
import folium
from folium.plugins import Fullscreen
import gspread
import google.auth

def calcular_azimut(lat1, lon1, lat2, lon2):
    """Calcula el ángulo de rumbo (azimut) en grados de 0 a 360."""
    p1_lat = math.radians(lat1)
    p1_lon = math.radians(lon1)
    p2_lat = math.radians(lat2)
    p2_lon = math.radians(lon2)
    
    dlon = p2_lon - p1_lon
    y = math.sin(dlon) * math.cos(p2_lat)
    x = math.cos(p1_lat) * math.sin(p2_lat) - math.sin(p1_lat) * math.cos(p2_lat) * math.cos(dlon)
    rumbo = math.degrees(math.atan2(y, x))
    return (rumbo + 360) % 360

def obtener_datos():
    credentials, _ = google.auth.default(scopes=[
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly"
    ])
    gc = gspread.authorize(credentials)
    spreadsheet_id = os.environ.get("GPS_SPREADSHEET_ID", "1n-edOD5p1K99m2m78SoTlJSnXDU_rY69Vxk5yttPgHg")
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet("Looker_GPS")
    records = ws.get_all_records()
    return pd.DataFrame(records)

def generar_mapa():
    df = obtener_datos()

    # 1. Asegurar tipos y conversión estricta a Datetime
    df['Latitud'] = pd.to_numeric(df['Latitud'], errors='coerce')
    df['Longitud'] = pd.to_numeric(df['Longitud'], errors='coerce')
    df['Velocidad'] = pd.to_numeric(df['Velocidad'], errors='coerce').fillna(0)
    df = df.dropna(subset=['Latitud', 'Longitud'])

    # Parseo explícito de fecha y hora para garantizar orden cronológico estricto
    df['dt'] = pd.to_datetime(df['Fecha'].astype(str) + ' ' + df['Hora'].astype(str), errors='coerce')
    df = df.dropna(subset=['dt']).sort_values(by=['Vehículo', 'dt']).reset_index(drop=True)

    # Coordenadas iniciales (centro del mapa)
    lat_c = df['Latitud'].mean()
    lon_c = df['Longitud'].mean()

    m = folium.Map(
        location=[lat_c, lon_c],
        zoom_start=10,
        tiles="CartoDB positron",
        control_scale=True
    )

    folium.TileLayer('OpenStreetMap', name='Calles (OpenStreetMap)').add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satélite (Esri)'
    ).add_to(m)

    colores = {
        'LHJL-14': '#2563eb', # Azul
        'PRYG-42': '#059669', # Verde
        'LHJL-13': '#7c3aed', # Morado
        'PTJP-73': '#ea580c'  # Naranja
    }

    # 2. Agrupar por Vehículo Y por Día (Evita que se unan días diferentes)
    dias_disponibles = sorted(df['Fecha'].unique())
    vehiculos = sorted(df['Vehículo'].unique())

    for vehiculo in vehiculos:
        df_veh = df[df['Vehículo'] == vehiculo]
        color = colores.get(vehiculo, '#333333')

        for fecha in dias_disponibles:
            sub = df_veh[df_veh['Fecha'] == fecha]
            if sub.empty:
                continue

            # Capa individual por cada Día y Vehículo
            nombre_capa = f"{vehiculo} | {fecha}"
            fg = folium.FeatureGroup(name=nombre_capa, show=False)

            puntos = sub[['Latitud', 'Longitud']].values.tolist()
            velocidades = sub['Velocidad'].values.tolist()
            horas = sub['Hora'].values.tolist()
            dts = sub['dt'].values

            # Trazar segmentos de línea (rompe la línea si hay más de 30 min de diferencia entre puntos)
            tramo_actual = []
            for i in range(len(puntos)):
                tramo_actual.append(puntos[i])
                
                # Si el siguiente punto está a más de 30 min o es el final, pintar tramo
                es_ultimo = (i == len(puntos) - 1)
                if not es_ultimo:
                    delta_min = (pd.to_datetime(dts[i+1]) - pd.to_datetime(dts[i])).total_seconds() / 60.0
                    if delta_min > 30.0:
                        if len(tramo_actual) > 1:
                            folium.PolyLine(tramo_actual, color=color, weight=4, opacity=0.8).add_to(fg)
                        tramo_actual = []
                else:
                    if len(tramo_actual) > 1:
                        folium.PolyLine(tramo_actual, color=color, weight=4, opacity=0.8).add_to(fg)

            # Punto de Inicio del día
            folium.CircleMarker(
                location=puntos[0],
                radius=6,
                color='#16a34a',
                fill=True,
                fill_color='#22c55e',
                fill_opacity=1.0,
                popup=f"<b>INICIO {vehiculo}</b><br>{fecha} {horas[0]}"
            ).add_to(fg)

            # Punto de Fin del día
            folium.CircleMarker(
                location=puntos[-1],
                radius=6,
                color='#0f172a',
                fill=True,
                fill_color='#0f172a',
                fill_opacity=1.0,
                popup=f"<b>FIN {vehiculo}</b><br>{fecha} {horas[-1]}"
            ).add_to(fg)

            # Excesos de velocidad (>= 120 km/h) en Rojo
            for i in range(len(puntos)):
                if velocidades[i] >= 120:
                    folium.CircleMarker(
                        location=puntos[i],
                        radius=5,
                        color='#b91c1c',
                        fill=True,
                        fill_color='#ef4444',
                        fill_opacity=0.9,
                        tooltip=f"⚠️ {vehiculo} - {velocidades[i]} km/h ({horas[i]})"
                    ).add_to(fg)

            # Flechas con rotación exacta en grados (cada 15 muestras en movimiento)
            for i in range(0, len(puntos) - 1, 15):
                if velocidades[i] > 10:
                    lat1, lon1 = puntos[i]
                    lat2, lon2 = puntos[i+1]
                    
                    if lat1 != lat2 or lon1 != lon2:
                        angulo = calcular_azimut(lat1, lon1, lat2, lon2)
                        # Símbolo vectorial que rota con el ángulo exacto hacia donde avanza
                        html_flecha = f"""
                        <div style="
                            transform: rotate({angulo}deg);
                            transform-origin: center center;
                            font-size: 14px;
                            color: {color};
                            line-height: 1;
                            text-shadow: 0 0 2px white;
                            width: 16px;
                            height: 16px;
                            text-align: center;">
                            ▲
                        </div>
                        """
                        folium.Marker(
                            location=[lat1, lon1],
                            icon=folium.DivIcon(html=html_flecha, icon_size=(16, 16), icon_anchor=(8, 8)),
                            tooltip=f"{horas[i]} | {velocidades[i]} km/h"
                        ).add_to(fg)

            fg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    Fullscreen().add_to(m)
    return m

if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    mapa = generar_mapa()
    salida = os.path.join("docs", "rutas_gps.html")
    mapa.save(salida)
    print(f"Mapa generado con éxito en: {salida}")
