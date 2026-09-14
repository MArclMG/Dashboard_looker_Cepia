import os
import math
import json
import pandas as pd
import gspread
import google.auth

def calcular_azimut(lat1, lon1, lat2, lon2):
    """Calcula el rumbo geográfico (azimut) en grados de 0 a 360."""
    p1_lat = math.radians(lat1)
    p1_lon = math.radians(lon1)
    p2_lat = math.radians(lat2)
    p2_lon = math.radians(lon2)
    
    dlon = p2_lon - p1_lon
    y = math.sin(dlon) * math.cos(p2_lat)
    x = math.cos(p1_lat) * math.sin(p2_lat) - math.sin(p1_lat) * math.cos(p2_lat) * math.cos(dlon)
    rumbo = math.degrees(math.atan2(y, x))
    return round((rumbo + 360) % 360, 1)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

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

def procesar_telemetria_viajes(df):
    df['Latitud'] = pd.to_numeric(df['Latitud'], errors='coerce')
    df['Longitud'] = pd.to_numeric(df['Longitud'], errors='coerce')
    df['Velocidad'] = pd.to_numeric(df['Velocidad'], errors='coerce').fillna(0)
    df = df.dropna(subset=['Latitud', 'Longitud'])
    
    df['dt'] = pd.to_datetime(df['Fecha'].astype(str) + ' ' + df['Hora'].astype(str), errors='coerce')
    df = df.dropna(subset=['dt']).sort_values(by=['Vehículo', 'dt']).reset_index(drop=True)

    vehiculos = sorted(df['Vehículo'].unique().tolist())
    dias = sorted(df['Fecha'].unique().tolist())

    estructura = {}

    for v in vehiculos:
        df_v = df[df['Vehículo'] == v]
        estructura[v] = {}

        for dia in dias:
            sub = df_v[df_v['Fecha'] == dia].reset_index(drop=True)
            if sub.empty:
                continue

            # 1. Segmentar en viajes por paradas prolongadas (>= 20 minutos detenidos o sin transmisión)
            viajes = []
            paradas = []
            
            puntos_viaje_actual = []
            idx_inicio_viaje = 0

            for i in range(len(sub)):
                fila = sub.iloc[i]
                puntos_viaje_actual.append(fila)

                if i < len(sub) - 1:
                    siguiente = sub.iloc[i + 1]
                    delta_min = (siguiente['dt'] - fila['dt']).total_seconds() / 60.0
                    
                    if delta_min >= 20.0:
                        # Evaluar si el viaje actual tuvo desplazamiento real (> 300 metros)
                        pts_coords = [[p['Latitud'], p['Longitud']] for p in puntos_viaje_actual]
                        km_viaje = 0.0
                        for k in range(1, len(pts_coords)):
                            km_viaje += haversine_km(pts_coords[k-1][0], pts_coords[k-1][1], pts_coords[k][0], pts_coords[k][1])
                        
                        if km_viaje >= 0.3:
                            viajes.append((puntos_viaje_actual, round(km_viaje, 1)))
                        puntos_viaje_actual = []

                        # Registrar parada intermedia
                        paradas.append({
                            'inicio': str(fila['Hora']),
                            'fin': str(siguiente['Hora']),
                            'duracion_min': round(delta_min),
                            'lat': float(fila['Latitud']),
                            'lon': float(fila['Longitud']),
                            'direccion': str(fila.get('Direccion', 'En ruta'))
                        })

            if puntos_viaje_actual:
                pts_coords = [[p['Latitud'], p['Longitud']] for p in puntos_viaje_actual]
                km_viaje = 0.0
                for k in range(1, len(pts_coords)):
                    km_viaje += haversine_km(pts_coords[k-1][0], pts_coords[k-1][1], pts_coords[k][0], pts_coords[k][1])
                if km_viaje >= 0.3:
                    viajes.append((puntos_viaje_actual, round(km_viaje, 1)))

            # Procesar cada viaje estructurado
            viajes_json = []
            for num_v, (pts_v, km_v) in enumerate(viajes):
                segmentos = []
                seg_actual = []
                flechas = []

                for i in range(len(pts_v)):
                    fila = pts_v[i]
                    lat = float(fila['Latitud'])
                    lon = float(fila['Longitud'])
                    vel = float(fila['Velocidad'])
                    hora = str(fila['Hora'])
                    direccion = str(fila.get('Direccion', ''))

                    seg_actual.append([lat, lon])

                    # Calcular ángulo de rumbo
                    angulo = 0
                    if i < len(pts_v) - 1:
                        sig = pts_v[i + 1]
                        if sig['Latitud'] != lat or sig['Longitud'] != lon:
                            angulo = calcular_azimut(lat, lon, float(sig['Latitud']), float(sig['Longitud']))
                    elif i > 0 and len(flechas) > 0:
                        angulo = flechas[-1]['angulo']

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

                if seg_actual:
                    segmentos.append(seg_actual)

                viajes_json.append({
                    'nombre': f"Viaje {num_v + 1}",
                    'km': km_v,
                    'hora_inicio': str(pts_v[0]['Hora']),
                    'hora_fin': str(pts_v[-1]['Hora']),
                    'inicio_coord': [float(pts_v[0]['Latitud']), float(pts_v[0]['Longitud'])],
                    'fin_coord': [float(pts_v[-1]['Latitud']), float(pts_v[-1]['Longitud'])],
                    'segmentos': segmentos,
                    'flechas': flechas
                })

            # Si no hubo viajes diferenciados por parada, empaquetar el día completo como 1 viaje
            if not viajes_json and len(sub) > 1:
                pts_coords = [[float(r['Latitud']), float(r['Longitud'])] for _, r in sub.iterrows()]
                km_total = sum(haversine_km(pts_coords[k-1][0], pts_coords[k-1][1], pts_coords[k][0], pts_coords[k][1]) for k in range(1, len(pts_coords)))
                viajes_json.append({
                    'nombre': "Viaje Único",
                    'km': round(km_total, 1),
                    'hora_inicio': str(sub.iloc[0]['Hora']),
                    'hora_fin': str(sub.iloc[-1]['Hora']),
                    'inicio_coord': [float(sub.iloc[0]['Latitud']), float(sub.iloc[0]['Longitud'])],
                    'fin_coord': [float(sub.iloc[-1]['Latitud']), float(sub.iloc[-1]['Longitud'])],
                    'segmentos': [pts_coords],
                    'flechas': []
                })

            estructura[v][dia] = {
                'viajes': viajes_json,
                'paradas': paradas,
                'inicio_dia': [float(sub.iloc[0]['Latitud']), float(sub.iloc[0]['Longitud']), str(sub.iloc[0]['Hora'])],
                'fin_dia': [float(sub.iloc[-1]['Latitud']), float(sub.iloc[-1]['Longitud']), str(sub.iloc[-1]['Hora'])]
            }

    return vehiculos, dias, estructura

def generar_html_mapa(vehiculos, dias, datos):
    datos_json = json.dumps(datos)
    vehiculos_json = json.dumps(vehiculos)
    dias_json = json.dumps(dias)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Visor de Rutas GPS y Viajes</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body, html {{ margin: 0; padding: 0; height: 100%; width: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
    #map {{ height: 100%; width: 100%; z-index: 1; }}

    /* Panel de Control Lateral */
    .control-panel {{
      position: absolute;
      top: 10px;
      right: 10px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.96);
      padding: 14px 16px;
      border-radius: 10px;
      box-shadow: 0 4px 18px rgba(0,0,0,0.18);
      width: 320px;
      max-height: 94vh;
      overflow-y: auto;
      font-size: 13px;
      color: #1e293b;
      backdrop-filter: blur(5px);
    }}
    .control-panel h4 {{ margin: 0 0 10px 0; font-size: 15px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }}
    .form-group {{ margin-bottom: 12px; }}
    .form-group label {{ display: block; font-weight: 600; margin-bottom: 4px; color: #475569; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
    select {{ width: 100%; padding: 6px 8px; border-radius: 6px; border: 1px solid #cbd5e1; background: #fff; font-size: 13px; font-weight: 500; outline: none; }}
    
    /* Contador de KM */
    .km-badge {{
      background: #ecfeff;
      border: 1px solid #a5f3fc;
      color: #0e7490;
      padding: 6px 10px;
      border-radius: 6px;
      font-weight: 700;
      font-size: 13px;
      display: flex;
      justify-content: space-between;
      margin-bottom: 10px;
    }}

    /* Botones de navegación */
    .nav-buttons {{ display: flex; gap: 6px; margin-bottom: 10px; }}
    .btn-nav {{
      flex: 1;
      padding: 5px 8px;
      font-size: 11px;
      font-weight: 600;
      border: 1px solid #cbd5e1;
      background: #f8fafc;
      border-radius: 5px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      color: #1e293b;
    }}
    .btn-nav:hover {{ background: #e2e8f0; }}

    /* Lista de Viajes */
    .trips-container {{
      max-height: 130px;
      overflow-y: auto;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #f8fafc;
      padding: 6px 8px;
    }}
    .trip-item {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; font-size: 12px; cursor: pointer; }}
    .trip-item input {{ margin-right: 6px; }}

    /* Lista de Paradas */
    .stops-container {{
      max-height: 120px;
      overflow-y: auto;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #fff;
      padding: 4px;
    }}
    .stop-card {{
      padding: 5px 6px;
      border-bottom: 1px solid #f1f5f9;
      cursor: pointer;
      font-size: 11px;
      border-radius: 4px;
    }}
    .stop-card:hover {{ background: #f1f5f9; }}
    .stop-card:last-child {{ border-bottom: none; }}
    .stop-time {{ font-weight: 700; color: #b45309; }}

    /* Selector de color */
    .color-row {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
    .color-row input[type="color"] {{
      border: none;
      width: 26px;
      height: 26px;
      border-radius: 50%;
      cursor: pointer;
      background: none;
      padding: 0;
    }}

    .arrow-icon {{ display: flex; align-items: center; justify-content: center; transform-origin: center center; }}
  </style>
</head>
<body>

  <div id="map"></div>

  <div class="control-panel">
    <h4>Control de Rutas GPS</h4>

    <!-- Selector de Capa de Fondo (Google Maps) -->
    <div class="form-group">
      <label for="select-mapa">Capa de Mapa</label>
      <select id="select-mapa">
        <option value="calles">Google Calles</option>
        <option value="satelite" selected>Google Satélite (Híbrido)</option>
        <option value="relieve">Google Relieve / Terreno</option>
        <option value="osm">OpenStreetMap</option>
      </select>
    </div>

    <!-- Selector de Vehículo y Día -->
    <div class="form-group">
      <label for="select-vehiculo">Vehículo / Patente</label>
      <select id="select-vehiculo"></select>
    </div>

    <div class="form-group">
      <label for="select-dia">Día Seleccionado</label>
      <select id="select-dia"></select>
    </div>

    <!-- Distancia total acumulada -->
    <div class="km-badge">
      <span>Distancia Seleccionada:</span>
      <span id="total-km-badge">0.0 km</span>
    </div>

    <!-- Navegación a puntos Inicio / Fin -->
    <div class="nav-buttons">
      <button class="btn-nav" onclick="irAPunto('inicio')">📍 Ir a Inicio</button>
      <button class="btn-nav" onclick="irAPunto('fin')">🏁 Ir a Término</button>
    </div>

    <!-- Viajes del día -->
    <div class="form-group">
      <label>Viajes del Día (Ida / Obra / Vuelta)</label>
      <div class="trips-container" id="trips-list"></div>
    </div>

    <!-- Paradas registradas -->
    <div class="form-group">
      <label>Paradas del Día (&ge; 20 min)</label>
      <div class="stops-container" id="stops-list"></div>
    </div>

    <!-- Color de la Ruta -->
    <div class="form-group">
      <label>Color de la Ruta</label>
      <div class="color-row">
        <input type="color" id="route-color" value="#06b6d4">
        <span id="route-hex" style="font-size:12px; font-weight:600; color:#06b6d4;">Turquesa (#06b6d4)</span>
      </div>
    </div>
  </div>

  <script>
    const datosGPS = {datos_json};
    const listaVehiculos = {vehiculos_json};
    const listaDias = {dias_json};

    // 1. Capas Google Maps sin API Key
    const capas = {{
      calles: L.tileLayer('https://mt1.google.com/vt/lyrs=m&x={{x}}&y={{y}}&z={{z}}', {{ maxZoom: 20, attribution: '&copy; Google Maps' }}),
      satelite: L.tileLayer('https://mt1.google.com/vt/lyrs=y&x={{x}}&y={{y}}&z={{z}}', {{ maxZoom: 20, attribution: '&copy; Google Satellite' }}),
      relieve: L.tileLayer('https://mt1.google.com/vt/lyrs=p&x={{x}}&y={{y}}&z={{z}}', {{ maxZoom: 20, attribution: '&copy; Google Terrain' }}),
      osm: L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19, attribution: '&copy; OpenStreetMap' }})
    }};

    const map = L.map('map', {{
      center: [-35.43, -71.66],
      zoom: 10,
      layers: [capas.satelite]
    }});

    let capaRutas = L.featureGroup().addTo(map);

    // Cambiar capa base desde el select
    document.getElementById('select-mapa').addEventListener('change', (e) => {{
      Object.values(capas).forEach(c => map.removeLayer(c));
      capas[e.target.value].addTo(map);
    }});

    // 2. Llenar Selectores
    const selVeh = document.getElementById('select-vehiculo');
    listaVehiculos.forEach(v => {{
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      selVeh.appendChild(opt);
    }});

    const selDia = document.getElementById('select-dia');
    listaDias.forEach(d => {{
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      selDia.appendChild(opt);
    }});

    // 3. Renderizar Viajes y Paradas en el menú lateral al cambiar de Vehículo o Día
    function refrescarOpcionesDia() {{
      const veh = selVeh.value;
      const dia = selDia.value;
      const tripsList = document.getElementById('trips-list');
      const stopsList = document.getElementById('stops-list');

      tripsList.innerHTML = '';
      stopsList.innerHTML = '';

      if (!datosGPS[veh] || !datosGPS[veh][dia]) {{
        tripsList.innerHTML = '<div style="color:#64748b; padding:4px;">No hay registros para este día.</div>';
        actualizarMapa();
        return;
      }}

      const infoDia = datosGPS[veh][dia];

      // Construir checkboxes de viajes
      infoDia.viajes.forEach((v, idx) => {{
        const row = document.createElement('div');
        row.className = 'trip-item';
        row.innerHTML = `
          <label style="display:flex; align-items:center; cursor:pointer;">
            <input type="checkbox" class="trip-cb" data-idx="${{idx}}" checked>
            <b>${{v.nombre}}</b> (${{v.hora_inicio}} - ${{v.hora_fin}})
          </label>
          <span style="color:#0284c7; font-weight:700;">${{v.km}} km</span>
        `;
        tripsList.appendChild(row);
      }});

      // Construir listado de paradas
      if (infoDia.paradas.length === 0) {{
        stopsList.innerHTML = '<div style="color:#64748b; padding:4px;">Sin paradas prolongadas.</div>';
      }} else {{
        infoDia.paradas.forEach(p => {{
          const card = document.createElement('div');
          card.className = 'stop-card';
          const durStr = p.duracion_min >= 60 
            ? `${{Math.floor(p.duracion_min/60)}}h ${{p.duracion_min%60}}m` 
            : `${{p.duracion_min}} min`;
          card.innerHTML = `
            <div><span class="stop-time">🛑 Parada (${{durStr}}):</span> ${{p.inicio}} &rarr; ${{p.fin}}</div>
            <div style="color:#475569; font-size:10px; margin-top:2px;">${{p.direccion}}</div>
          `;
          card.onclick = () => {{
            map.flyTo([p.lat, p.lon], 16, {{ duration: 1 }});
            L.popup()
              .setLatLng([p.lat, p.lon])
              .setContent(`<b>🛑 PARADA REGISTRADA</b><br>Hora: ${{p.inicio}} a ${{p.fin}}<br>Duración: ${{durStr}}<br>Lugar: ${{p.direccion}}`)
              .openOn(map);
          }};
          stopsList.appendChild(card);
        }});
      }}

      // Escuchar cambios en los checkboxes de viajes
      tripsList.querySelectorAll('.trip-cb').forEach(cb => {{
        cb.addEventListener('change', actualizarMapa);
      }});

      actualizarMapa();
    }}

    // 4. Renderizar rutas en el mapa y calcular KM totales seleccionados
    function actualizarMapa() {{
      capaRutas.clearLayers();

      const veh = selVeh.value;
      const dia = selDia.value;
      const colorRuta = document.getElementById('route-color').value;
      const colorFlecha = '#1d4ed8'; // Azul

      if (!datosGPS[veh] || !datosGPS[veh][dia]) {{
        document.getElementById('total-km-badge').textContent = "0.0 km";
        return;
      }}

      const infoDia = datosGPS[veh][dia];
      const cbs = document.querySelectorAll('.trip-cb:checked');
      const indicesActivos = Array.from(cbs).map(cb => parseInt(cb.dataset.idx));

      let kmTotales = 0.0;
      const bounds = [];

      indicesActivos.forEach(idx => {{
        const viaje = infoDia.viajes[idx];
        if (!viaje) return;

        kmTotales += viaje.km;

        // Trazar línea de ruta
        viaje.segmentos.forEach(seg => {{
          const poly = L.polyline(seg, {{
            color: colorRuta,
            weight: 5,
            opacity: 0.9,
            lineJoin: 'round'
          }}).bindTooltip(`${{viaje.nombre}}: ${{viaje.km}} km`);
          capaRutas.addLayer(poly);
          seg.forEach(pt => bounds.push(pt));
        }});

        // Flechas direccionales
        viaje.flechas.forEach(f => {{
          const esExceso = f.es_exceso;
          const colorIcono = esExceso ? '#ef4444' : colorFlecha;
          const tamano = esExceso ? 18 : 13;

          const svg = `
            <div class="arrow-icon" style="transform: rotate(${{f.angulo}}deg); width:${{tamano}}px; height:${{tamano}}px;">
              <svg viewBox="0 0 24 24" width="${{tamano}}" height="${{tamano}}">
                <path d="M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z" fill="${{colorIcono}}" stroke="#ffffff" stroke-width="${{esExceso ? 2 : 1}}"/>
              </svg>
            </div>
          `;

          const marker = L.marker([f.lat, f.lon], {{
            icon: L.divIcon({{ html: svg, iconSize: [tamano, tamano], iconAnchor: [tamano/2, tamano/2] }})
          }});

          if (esExceso) {{
            marker.bindPopup(`
              <div style="font-size:12px; line-height:1.4;">
                <b style="color:#b91c1c; font-size:13px;">⚠️ EXCESO DE VELOCIDAD</b><br>
                <b>Vehículo:</b> ${{veh}}<br>
                <b>Velocidad:</b> ${{f.vel}} km/h<br>
                <b>Hora:</b> ${{f.hora}}<br>
                <b>Lugar:</b> ${{f.direccion}}
              </div>
            `);
          }} else {{
            marker.bindTooltip(`${{f.hora}} | ${{f.vel}} km/h`, {{ direction: 'top', offset: [0, -6] }});
          }}
          capaRutas.addLayer(marker);
        }});
      }});

      // Actualizar marcador de Inicio y Fin general del día
      if (indicesActivos.length > 0) {{
        const ptIni = infoDia.inicio_dia;
        const ptFin = infoDia.fin_dia;

        capaRutas.addLayer(L.circleMarker([ptIni[0], ptIni[1]], {{
          radius: 7, color: '#15803d', fillColor: '#22c55e', fillOpacity: 1, weight: 2
        }}).bindPopup(`<b>PUNTO INICIO DEL DÍA</b><br>${{veh}}<br>Hora: ${{ptIni[2]}}`));

        capaRutas.addLayer(L.circleMarker([ptFin[0], ptFin[1]], {{
          radius: 7, color: '#0f172a', fillColor: '#0f172a', fillOpacity: 1, weight: 2
        }}).bindPopup(`<b>PUNTO TÉRMINO DEL DÍA</b><br>${{veh}}<br>Hora: ${{ptFin[2]}}`));
      }}

      // Actualizar indicador de KM en el panel
      document.getElementById('total-km-badge').textContent = kmTotales.toFixed(1) + " km";

      if (bounds.length > 0) {{
        map.fitBounds(bounds, {{ padding: [30, 30] }});
      }}
    }}

    // Navegación rápida
    function irAPunto(tipo) {{
      const veh = selVeh.value;
      const dia = selDia.value;
      if (!datosGPS[veh] || !datosGPS[veh][dia]) return;
      const infoDia = datosGPS[veh][dia];
      const coords = tipo === 'inicio' ? infoDia.inicio_dia : infoDia.fin_dia;
      map.flyTo([coords[0], coords[1]], 16, {{ duration: 1 }});
    }}

    // Eventos
    selVeh.addEventListener('change', refrescarOpcionesDia);
    selDia.addEventListener('change', refrescarOpcionesDia);

    document.getElementById('route-color').addEventListener('input', (e) => {{
      document.getElementById('route-hex').textContent = e.target.value;
      document.getElementById('route-hex').style.color = e.target.value;
      actualizarMapa();
    }});

    // Inicio automático
    refrescarOpcionesDia();
  </script>
</body>
</html>
"""
    return html

if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    df_raw = obtener_datos()
    vehiculos, dias, estructura = procesar_telemetria_viajes(df_raw)
    html_out = generar_html_mapa(vehiculos, dias, estructura)

    ruta = os.path.join("docs", "rutas_gps.html")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Mapa interactivo con viajes generado exitosamente en: {ruta}")
