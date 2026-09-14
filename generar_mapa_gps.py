import os
import math
import json
import pandas as pd
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
    return round((rumbo + 360) % 360, 1)

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

def procesar_datos_a_json(df):
    df['Latitud'] = pd.to_numeric(df['Latitud'], errors='coerce')
    df['Longitud'] = pd.to_numeric(df['Longitud'], errors='coerce')
    df['Velocidad'] = pd.to_numeric(df['Velocidad'], errors='coerce').fillna(0)
    df = df.dropna(subset=['Latitud', 'Longitud'])
    
    # Parseo estricto de fecha y hora
    df['dt'] = pd.to_datetime(df['Fecha'].astype(str) + ' ' + df['Hora'].astype(str), errors='coerce')
    df = df.dropna(subset=['dt']).sort_values(by=['Vehículo', 'dt']).reset_index(drop=True)

    vehiculos = sorted(df['Vehículo'].unique().tolist())
    dias = sorted(df['Fecha'].unique().tolist())

    estructura_datos = {}

    for vehiculo in vehiculos:
        df_veh = df[df['Vehículo'] == vehiculo]
        estructura_datos[vehiculo] = {}

        for dia in dias:
            sub = df_veh[df_veh['Fecha'] == dia].reset_index(drop=True)
            if sub.empty:
                continue

            segmentos = []
            segmento_actual = []
            flechas = []

            for i in range(len(sub)):
                fila = sub.iloc[i]
                lat = float(fila['Latitud'])
                lon = float(fila['Longitud'])
                vel = float(fila['Velocidad'])
                hora = str(fila['Hora'])
                direccion = str(fila.get('Direccion', ''))

                segmento_actual.append([lat, lon])

                # Calcular rumbo hacia el siguiente punto válido
                angulo = 0
                if i < len(sub) - 1:
                    siguiente = sub.iloc[i + 1]
                    if siguiente['Latitud'] != lat or siguiente['Longitud'] != lon:
                        angulo = calcular_azimut(lat, lon, float(siguiente['Latitud']), float(siguiente['Longitud']))
                elif i > 0 and len(flechas) > 0:
                    angulo = flechas[-1]['angulo']

                # Marcar flecha si es exceso de velocidad (>= 120) o periódica en marcha (cada 15 muestras)
                es_exceso = vel >= 120
                if es_exceso or (vel > 15 and i % 15 == 0):
                    flechas.append({
                        'lat': lat,
                        'lon': lon,
                        'angulo': angulo,
                        'vel': vel,
                        'hora': hora,
                        'es_exceso': es_exceso,
                        'direccion': direccion
                    })

                # Romper la polilínea si la pausa entre muestras supera 30 min (evita cruzar cerros)
                if i < len(sub) - 1:
                    delta_min = (sub.iloc[i + 1]['dt'] - fila['dt']).total_seconds() / 60.0
                    if delta_min > 30.0:
                        if len(segmento_actual) > 1:
                            segmentos.append(segmento_actual)
                        segmento_actual = []
                else:
                    if len(segmento_actual) > 1:
                        segmentos.append(segmento_actual)

            estructura_datos[vehiculo][dia] = {
                'segmentos': segmentos,
                'flechas': flechas,
                'inicio': [float(sub.iloc[0]['Latitud']), float(sub.iloc[0]['Longitud']), str(sub.iloc[0]['Hora'])],
                'fin': [float(sub.iloc[-1]['Latitud']), float(sub.iloc[-1]['Longitud']), str(sub.iloc[-1]['Hora'])]
            }

    return vehiculos, dias, estructura_datos

def construir_html(vehiculos, dias, datos):
    datos_json = json.dumps(datos)
    vehiculos_json = json.dumps(vehiculos)
    dias_json = json.dumps(dias)

    html_template = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Visor de Rutas GPS y Control de Velocidad</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- Leaflet CSS & JS -->
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body, html {{ margin: 0; padding: 0; height: 100%; width: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
    #map {{ height: 100%; width: 100%; z-index: 1; }}

    /* Panel de Control Flotante */
    .control-panel {{
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.96);
      padding: 14px 16px;
      border-radius: 10px;
      box-shadow: 0 4px 14px rgba(0,0,0,0.18);
      max-width: 290px;
      font-size: 13px;
      color: #1e293b;
      backdrop-filter: blur(4px);
    }}
    .control-panel h4 {{ margin: 0 0 10px 0; font-size: 14px; font-weight: 700; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
    .form-group {{ margin-bottom: 10px; }}
    .form-group label {{ display: block; font-weight: 600; margin-bottom: 4px; color: #475569; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
    select {{ width: 100%; padding: 6px 8px; border-radius: 6px; border: 1px solid #cbd5e1; background: #fff; font-size: 13px; font-weight: 500; outline: none; }}
    
    /* Selector de días */
    .days-container {{
      max-height: 125px;
      overflow-y: auto;
      border: 1px solid #e2e8f0;
      padding: 6px 8px;
      border-radius: 6px;
      background: #f8fafc;
    }}
    .day-checkbox {{ display: flex; align-items: center; margin-bottom: 4px; cursor: pointer; }}
    .day-checkbox input {{ margin-right: 6px; cursor: pointer; }}
    .day-actions {{ display: flex; gap: 8px; margin-top: 4px; margin-bottom: 6px; }}
    .day-actions button {{
      flex: 1;
      padding: 3px 6px;
      font-size: 11px;
      background: #f1f5f9;
      border: 1px solid #cbd5e1;
      border-radius: 4px;
      cursor: pointer;
      color: #334155;
    }}
    .day-actions button:hover {{ background: #e2e8f0; }}

    /* Selectores de color */
    .color-row {{ display: flex; gap: 10px; }}
    .color-col {{ flex: 1; }}
    .color-picker-wrap {{ display: flex; align-items: center; gap: 6px; }}
    .color-picker-wrap input[type="color"] {{
      border: none;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      cursor: pointer;
      background: none;
      padding: 0;
    }}

    /* Leyenda */
    .legend {{ margin-top: 10px; padding-top: 8px; border-top: 1px solid #e2e8f0; font-size: 11px; }}
    .legend-item {{ display: flex; align-items: center; gap: 6px; margin-bottom: 3px; }}
    .legend-box {{ width: 12px; height: 12px; border-radius: 2px; }}

    /* Flechas SVG en el mapa */
    .arrow-icon {{
      display: flex;
      align-items: center;
      justify-content: center;
      transform-origin: center center;
    }}
  </style>
</head>
<body>

  <div id="map"></div>

  <div class="control-panel">
    <h4>Control de Rutas GPS</h4>

    <!-- Selector de Patente -->
    <div class="form-group">
      <label for="select-vehiculo">Vehículo / Patente</label>
      <select id="select-vehiculo"></select>
    </div>

    <!-- Selector de Días -->
    <div class="form-group">
      <label>Días de la semana</label>
      <div class="day-actions">
        <button onclick="seleccionarTodosDias(true)">Todos</button>
        <button onclick="seleccionarTodosDias(false)">Ninguno</button>
      </div>
      <div class="days-container" id="days-checkboxes"></div>
    </div>

    <!-- Selectores de Colores -->
    <div class="form-group">
      <div class="color-row">
        <div class="color-col">
          <label>Color Ruta</label>
          <div class="color-picker-wrap">
            <input type="color" id="route-color" value="#06b6d4">
            <span id="route-hex" style="font-size:11px; font-weight:600; color:#06b6d4;">Turquesa</span>
          </div>
        </div>
        <div class="color-col">
          <label>Color Flechas</label>
          <div class="color-picker-wrap">
            <input type="color" id="arrow-color" value="#1d4ed8">
            <span id="arrow-hex" style="font-size:11px; font-weight:600; color:#1d4ed8;">Azul</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Leyenda -->
    <div class="legend">
      <div class="legend-item">
        <span style="color:#ef4444; font-size:13px; font-weight:bold;">▲</span>
        <span><b>Exceso de velocidad</b> (&ge; 120 km/h)</span>
      </div>
      <div class="legend-item">
        <span style="display:inline-block; width:8px; height:8px; background:#22c55e; border-radius:50%;"></span>
        <span>Punto Inicio / </span>
        <span style="display:inline-block; width:8px; height:8px; background:#0f172a; border-radius:50%;"></span>
        <span>Punto Término</span>
      </div>
    </div>
  </div>

  <script>
    const datosGPS = {datos_json};
    const listaVehiculos = {vehiculos_json};
    const listaDias = {dias_json};

    // 1. Inicializar Mapa con soporte de capas base
    const capaCalles = L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
      attribution: '&copy; CartoDB &copy; OpenStreetMap',
      subdomains: 'abcd',
      maxZoom: 19
    }});

    const capaSatelite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
      attribution: 'Esri',
      maxZoom: 19
    }});

    const map = L.map('map', {{
      center: [-35.43, -71.66],
      zoom: 10,
      layers: [capaCalles]
    }});

    L.control.layers({{ "Mapa Calles": capaCalles, "Satélite": capaSatelite }}, null, {{ position: 'topleft' }}).addTo(map);

    let capaActiva = L.featureGroup().addTo(map);

    // 2. Poblar selector de vehículos
    const selectVehiculo = document.getElementById('select-vehiculo');
    listaVehiculos.forEach(v => {{
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      selectVehiculo.appendChild(opt);
    }});

    // 3. Poblar checkboxes de días
    const daysContainer = document.getElementById('days-checkboxes');
    listaDias.forEach(dia => {{
      const label = document.createElement('label');
      label.className = 'day-checkbox';
      label.innerHTML = `<input type="checkbox" value="${{dia}}" checked> ${{dia}}`;
      daysContainer.appendChild(label);
    }});

    function seleccionarTodosDias(estado) {{
      const cbs = daysContainer.querySelectorAll('input[type="checkbox"]');
      cbs.forEach(cb => cb.checked = estado);
      actualizarMapa();
    }}

    // 4. Función de renderizado dinámico
    function actualizarMapa() {{
      capaActiva.clearLayers();

      const vehiculoSel = selectVehiculo.value;
      const colorRuta = document.getElementById('route-color').value;
      const colorFlecha = document.getElementById('arrow-color').value;

      // Obtener días seleccionados
      const cbs = daysContainer.querySelectorAll('input[type="checkbox"]:checked');
      const diasSel = Array.from(cbs).map(cb => cb.value);

      if (!datosGPS[vehiculoSel]) return;

      const bounds = [];

      diasSel.forEach(dia => {{
        const jornada = datosGPS[vehiculoSel][dia];
        if (!jornada) return;

        // Trazar segmentos de polilínea
        jornada.segmentos.forEach(seg => {{
          const poly = L.polyline(seg, {{
            color: colorRuta,
            weight: 4.5,
            opacity: 0.85,
            lineJoin: 'round'
          }}).bindTooltip(`${{vehiculoSel}} - ${{dia}}`);
          capaActiva.addLayer(poly);
          seg.forEach(pt => bounds.push(pt));
        }});

        // Marcadores de Inicio (Verde) y Fin (Negro)
        const inicioMarker = L.circleMarker([jornada.inicio[0], jornada.inicio[1]], {{
          radius: 6,
          color: '#15803d',
          fillColor: '#22c55e',
          fillOpacity: 1,
          weight: 2
        }}).bindPopup(`<b>INICIO DE RUTA</b><br>${{vehiculoSel}}<br>Fecha: ${{dia}}<br>Hora: ${{jornada.inicio[2]}}`);
        capaActiva.addLayer(inicioMarker);

        const finMarker = L.circleMarker([jornada.fin[0], jornada.fin[1]], {{
          radius: 6,
          color: '#0f172a',
          fillColor: '#0f172a',
          fillOpacity: 1,
          weight: 2
        }}).bindPopup(`<b>FIN DE RUTA</b><br>${{vehiculoSel}}<br>Fecha: ${{dia}}<br>Hora: ${{jornada.fin[2]}}`);
        capaActiva.addLayer(finMarker);

        // Flechas direccionales
        jornada.flechas.forEach(f => {{
          const esExceso = f.es_exceso;
          const colorIcono = esExceso ? '#ef4444' : colorFlecha;
          const tamano = esExceso ? 18 : 14;

          const svgArrow = `
            <div class="arrow-icon" style="transform: rotate(${{f.angulo}}deg); width:${{tamano}}px; height:${{tamano}}px;">
              <svg viewBox="0 0 24 24" width="${{tamano}}" height="${{tamano}}">
                <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z" fill="${{colorIcono}}" stroke="#ffffff" stroke-width="${{esExceso ? 2 : 1}}"/>
              </svg>
            </div>
          `;

          const icon = L.divIcon({{
            html: svgArrow,
            className: '',
            iconSize: [tamano, tamano],
            iconAnchor: [tamano / 2, tamano / 2]
          }});

          const marker = L.marker([f.lat, f.lon], {{ icon: icon }});

          if (esExceso) {{
            marker.bindPopup(`
              <div style="font-size:12px; line-height:1.4;">
                <b style="color:#b91c1c; font-size:13px;">⚠️ EXCESO DE VELOCIDAD</b><br>
                <b>Vehículo:</b> ${{vehiculoSel}}<br>
                <b>Velocidad:</b> ${{f.vel}} km/h<br>
                <b>Fecha:</b> ${{dia}} ${{f.hora}}<br>
                <b>Rumbo:</b> ${{f.angulo}}°<br>
                <b>Lugar:</b> ${{f.direccion}}
              </div>
            `);
          }} else {{
            marker.bindTooltip(`${{f.hora}} | ${{f.vel}} km/h`, {{ direction: 'top', offset: [0, -8] }});
          }}

          capaActiva.addLayer(marker);
        }});
      }});

      // Auto-ajustar zoom al recorrido filtrado
      if (bounds.length > 0) {{
        map.fitBounds(bounds, {{ padding: [30, 30] }});
      }}
    }}

    // Eventos interactivos
    selectVehiculo.addEventListener('change', actualizarMapa);
    daysContainer.addEventListener('change', actualizarMapa);

    document.getElementById('route-color').addEventListener('input', (e) => {{
      document.getElementById('route-hex').textContent = e.target.value;
      document.getElementById('route-hex').style.color = e.target.value;
      actualizarMapa();
    }});

    document.getElementById('arrow-color').addEventListener('input', (e) => {{
      document.getElementById('arrow-hex').textContent = e.target.value;
      document.getElementById('arrow-hex').style.color = e.target.value;
      actualizarMapa();
    }});

    // Render inicial
    actualizarMapa();
  </script>
</body>
</html>
"""
    return html_template

if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    df_raw = obtener_datos()
    vehiculos, dias, datos = procesar_datos_a_json(df_raw)
    html_content = construir_html(vehiculos, dias, datos)

    ruta_salida = os.path.join("docs", "rutas_gps.html")
    with open(ruta_salida, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Visor GPS interactivo generado exitosamente en: {ruta_salida}")
