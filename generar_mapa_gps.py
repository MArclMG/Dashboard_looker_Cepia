import os
import math
import json
import pandas as pd
import gspread
import google.auth

def calcular_azimut(lat1, lon1, lat2, lon2):
    p1_lat, p1_lon = math.radians(lat1), math.radians(lon1)
    p2_lat, p2_lon = math.radians(lat2), math.radians(lon2)
    dlon = p2_lon - p1_lon
    y = math.sin(dlon) * math.cos(p2_lat)
    x = math.cos(p1_lat) * math.sin(p2_lat) - math.sin(p1_lat) * math.cos(p2_lat) * math.cos(dlon)
    return round((math.degrees(math.atan2(y, x)) + 360) % 360, 1)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
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
    return pd.DataFrame(ws.get_all_records())

def procesar_telemetria_viajes(df):
    df['Latitud'] = pd.to_numeric(df['Latitud'], errors='coerce')
    df['Longitud'] = pd.to_numeric(df['Longitud'], errors='coerce')
    df['Velocidad'] = pd.to_numeric(df['Velocidad'], errors='coerce').fillna(0)
    df = df.dropna(subset=['Latitud', 'Longitud'])
    
    df['dt'] = pd.to_datetime(df['Fecha'].astype(str) + ' ' + df['Hora'].astype(str), errors='coerce')
    df = df.dropna(subset=['dt']).sort_values(by=['Vehículo', 'dt']).reset_index(drop=True)

    nombres_vehiculos = sorted(df['Vehículo'].unique().tolist())
    dias = sorted(df['Fecha'].unique().tolist())
    
    vehiculos_info = []
    estructura = {}

    for v in nombres_vehiculos:
        df_v = df[df['Vehículo'] == v]
        
        # Extraer conductor más frecuente o asignado
        cond_series = df_v['Conductor'].dropna().astype(str)
        cond_series = cond_series[~cond_series.isin(["", "None", "null", "Sin Asignar"])]
        conductor_vehiculo = cond_series.mode()[0] if not cond_series.empty else "Sin Asignar"
        
        placa_vehiculo = str(df_v['Placa'].dropna().iloc[0]) if 'Placa' in df_v.columns and not df_v['Placa'].dropna().empty else v

        vehiculos_info.append({
            'id': v,
            'placa': placa_vehiculo,
            'conductor': conductor_vehiculo,
            'label': f"{placa_vehiculo} — {conductor_vehiculo}"
        })

        estructura[v] = {
            'conductor': conductor_vehiculo,
            'placa': placa_vehiculo,
            'dias': {}
        }

        for dia in dias:
            sub = df_v[df_v['Fecha'] == dia].reset_index(drop=True)
            if sub.empty:
                continue

            viajes = []
            paradas = []
            puntos_viaje_actual = []
            nodo_reanudacion = None

            for i in range(len(sub)):
                fila = sub.iloc[i]
                puntos_viaje_actual.append(fila)

                if i < len(sub) - 1:
                    siguiente = sub.iloc[i + 1]
                    delta_min = (siguiente['dt'] - fila['dt']).total_seconds() / 60.0
                    
                    if delta_min >= 20.0:
                        pts_coords = [[p['Latitud'], p['Longitud']] for p in puntos_viaje_actual]
                        km_viaje = sum(haversine_km(pts_coords[k-1][0], pts_coords[k-1][1], pts_coords[k][0], pts_coords[k][1]) for k in range(1, len(pts_coords)))
                        
                        if km_viaje >= 0.3:
                            viajes.append({
                                'puntos': puntos_viaje_actual,
                                'km': round(km_viaje, 1),
                                'reanudacion': nodo_reanudacion
                            })
                        puntos_viaje_actual = []

                        paradas.append({
                            'inicio': str(fila['Hora']),
                            'fin': str(siguiente['Hora']),
                            'duracion_min': round(delta_min),
                            'lat': float(fila['Latitud']),
                            'lon': float(fila['Longitud']),
                            'direccion': str(fila.get('Direccion', 'En ruta'))
                        })
                        nodo_reanudacion = {
                            'lat': float(siguiente['Latitud']),
                            'lon': float(siguiente['Longitud']),
                            'hora': str(siguiente['Hora']),
                            'vel': float(siguiente['Velocidad'])
                        }

            if puntos_viaje_actual:
                pts_coords = [[p['Latitud'], p['Longitud']] for p in puntos_viaje_actual]
                km_viaje = sum(haversine_km(pts_coords[k-1][0], pts_coords[k-1][1], pts_coords[k][0], pts_coords[k][1]) for k in range(1, len(pts_coords)))
                if km_viaje >= 0.3:
                    viajes.append({
                        'puntos': puntos_viaje_actual,
                        'km': round(km_viaje, 1),
                        'reanudacion': nodo_reanudacion
                    })

            viajes_json = []
            for num_v, v_item in enumerate(viajes):
                pts_v = v_item['puntos']
                km_v = v_item['km']
                puntos_detallados = []
                flechas = []

                for i in range(len(pts_v)):
                    fila = pts_v[i]
                    lat, lon = float(fila['Latitud']), float(fila['Longitud'])
                    vel = float(fila['Velocidad'])
                    hora = str(fila['Hora'])

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
                            'direccion': str(fila.get('Direccion', ''))
                        })

                    puntos_detallados.append({
                        'lat': lat,
                        'lon': lon,
                        'hora': hora,
                        'vel': vel,
                        'fraccion': round(i / max(1, len(pts_v) - 1), 3)
                    })

                viajes_json.append({
                    'nombre': f"Viaje {num_v + 1}",
                    'km': km_v,
                    'hora_inicio': str(pts_v[0]['Hora']),
                    'hora_fin': str(pts_v[-1]['Hora']),
                    'inicio_coord': [float(pts_v[0]['Latitud']), float(pts_v[0]['Longitud'])],
                    'fin_coord': [float(pts_v[-1]['Latitud']), float(pts_v[-1]['Longitud'])],
                    'reanudacion': v_item['reanudacion'],
                    'puntos': puntos_detallados,
                    'flechas': flechas
                })

            estructura[v]['dias'][dia] = {
                'viajes': viajes_json,
                'paradas': paradas,
                'inicio_dia': [float(sub.iloc[0]['Latitud']), float(sub.iloc[0]['Longitud']), str(sub.iloc[0]['Hora'])],
                'fin_dia': [float(sub.iloc[-1]['Latitud']), float(sub.iloc[-1]['Longitud']), str(sub.iloc[-1]['Hora'])]
            }

    return vehiculos_info, dias, estructura

def generar_html_mapa(vehiculos_info, dias, datos):
    datos_json = json.dumps(datos)
    vehiculos_json = json.dumps(vehiculos_info)
    dias_json = json.dumps(dias)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Visor de Rutas GPS y Conductores</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    body, html {{ margin: 0; padding: 0; height: 100%; width: 100%; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
    #map {{ height: 100%; width: 100%; z-index: 1; }}

    #toggle-panel-btn {{
      position: absolute;
      top: 12px;
      right: 342px;
      z-index: 1001;
      background: #ffffff;
      border: 1px solid #cbd5e1;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      border-radius: 8px;
      width: 36px;
      height: 36px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 16px;
      font-weight: bold;
      color: #334155;
      transition: right 0.3s ease, background 0.2s;
    }}
    #toggle-panel-btn:hover {{ background: #f1f5f9; }}
    #toggle-panel-btn.collapsed {{ right: 12px; }}

    .control-panel {{
      position: absolute;
      top: 12px;
      right: 12px;
      z-index: 1000;
      background: rgba(255, 255, 255, 0.96);
      padding: 14px 16px;
      border-radius: 10px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.18);
      width: 320px;
      max-height: 94vh;
      overflow-y: auto;
      font-size: 13px;
      color: #1e293b;
      backdrop-filter: blur(5px);
      transition: transform 0.3s ease, opacity 0.3s ease;
    }}
    .control-panel.hidden {{
      transform: translateX(360px);
      opacity: 0;
      pointer-events: none;
    }}
    .control-panel h4 {{ margin: 0 0 10px 0; font-size: 15px; font-weight: 700; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }}
    .form-group {{ margin-bottom: 11px; }}
    .form-group label {{ display: block; font-weight: 600; margin-bottom: 4px; color: #475569; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
    select {{ width: 100%; padding: 6px 8px; border-radius: 6px; border: 1px solid #cbd5e1; background: #fff; font-size: 13px; font-weight: 500; outline: none; }}
    
    /* Conductor Badge */
    .conductor-card {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 4px solid #0284c7;
      padding: 8px 10px;
      border-radius: 6px;
      margin-bottom: 10px;
    }}
    .conductor-card .title {{ font-size: 10px; text-transform: uppercase; font-weight: 700; color: #64748b; }}
    .conductor-card .name {{ font-size: 14px; font-weight: 700; color: #0f172a; margin-top: 1px; }}

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

    .trips-container {{
      max-height: 120px;
      overflow-y: auto;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #f8fafc;
      padding: 6px 8px;
    }}
    .trip-item {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; font-size: 12px; cursor: pointer; }}
    .trip-item input {{ margin-right: 6px; }}

    .stops-container {{
      max-height: 110px;
      overflow-y: auto;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #fff;
      padding: 4px;
    }}
    .stop-card {{
      padding: 4px 6px;
      border-bottom: 1px solid #f1f5f9;
      cursor: pointer;
      font-size: 11px;
      border-radius: 4px;
    }}
    .stop-card:hover {{ background: #f8fafc; }}
    .stop-time {{ font-weight: 700; color: #b45309; }}

    .gradient-preview {{
      height: 8px;
      border-radius: 4px;
      background: linear-gradient(to right, #06b6d4, #2563eb, #9333ea);
      margin-top: 4px;
      margin-bottom: 2px;
    }}
    .gradient-labels {{
      display: flex;
      justify-content: space-between;
      font-size: 10px;
      color: #64748b;
      font-weight: 600;
    }}

    .arrow-icon {{ display: flex; align-items: center; justify-content: center; transform-origin: center center; }}
    
    .badge-label {{
      background: rgba(15, 23, 42, 0.85);
      color: #fff;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 10px;
      font-weight: 600;
      white-space: nowrap;
      border: 1px solid rgba(255,255,255,0.3);
      box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }}
    .badge-start {{ background: #16a34a; }}
    .badge-end {{ background: #dc2626; }}
    .badge-resume {{ background: #d97706; }}
  </style>
</head>
<body>

  <button id="toggle-panel-btn" title="Ocultar/Mostrar Panel">◀</button>
  <div id="map"></div>

  <div class="control-panel" id="main-panel">
    <h4>Control de Rutas GPS</h4>

    <!-- Selector de Capas Base de Google Maps -->
    <div class="form-group">
      <label for="select-mapa">Capa Base</label>
      <select id="select-mapa">
        <option value="satelite" selected>Google Satélite (Híbrido)</option>
        <option value="calles">Google Calles</option>
        <option value="relieve">Google Relieve</option>
        <option value="osm">OpenStreetMap</option>
      </select>
    </div>

    <!-- Filtros de Vehículo con Conductor -->
    <div class="form-group">
      <label for="select-vehiculo">Vehículo & Conductor</label>
      <select id="select-vehiculo"></select>
    </div>

    <!-- Ficha de Conductor Asignado -->
    <div class="conductor-card">
      <div class="title">Conductor Asignado</div>
      <div class="name" id="conductor-nombre">—</div>
    </div>

    <div class="form-group">
      <label for="select-dia">Día Seleccionado</label>
      <select id="select-dia"></select>
    </div>

    <!-- Indicador de Kilómetros -->
    <div class="km-badge">
      <span>Distancia de Viajes:</span>
      <span id="total-km-badge">0.0 km</span>
    </div>

    <!-- Navegación a Puntos Extremos -->
    <div class="nav-buttons">
      <button class="btn-nav" onclick="irAPunto('inicio')">📍 Inicio del Día</button>
      <button class="btn-nav" onclick="irAPunto('fin')">🏁 Fin del Día</button>
    </div>

    <!-- Selección de Viajes -->
    <div class="form-group">
      <label>Viajes Detectados</label>
      <div class="trips-container" id="trips-list"></div>
    </div>

    <!-- Gradiente Temporal -->
    <div class="form-group">
      <label>Visualización Temporal de Ruta</label>
      <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:12px; margin-bottom:4px;">
        <input type="checkbox" id="check-gradiente" checked>
        <b>Activar gradiente de hora (Temprano &rarr; Tarde)</b>
      </label>
      <div class="gradient-preview"></div>
      <div class="gradient-labels">
        <span>Mañana (#06b6d4)</span>
        <span>Mediodía (#2563eb)</span>
        <span>Tarde (#9333ea)</span>
      </div>
    </div>

    <!-- Paradas Prolongadas -->
    <div class="form-group">
      <label>Paradas Registradas (&ge; 20 min)</label>
      <div class="stops-container" id="stops-list"></div>
    </div>
  </div>

  <script>
    const datosGPS = {datos_json};
    const listaVehiculos = {vehiculos_json};
    const listaDias = {dias_json};

    // 1. Capas Google Maps sin API Key
    const capas = {{
      satelite: L.tileLayer('https://mt1.google.com/vt/lyrs=y&x={{x}}&y={{y}}&z={{z}}', {{ maxZoom: 20, attribution: '&copy; Google Satellite' }}),
      calles: L.tileLayer('https://mt1.google.com/vt/lyrs=m&x={{x}}&y={{y}}&z={{z}}', {{ maxZoom: 20, attribution: '&copy; Google Maps' }}),
      relieve: L.tileLayer('https://mt1.google.com/vt/lyrs=p&x={{x}}&y={{y}}&z={{z}}', {{ maxZoom: 20, attribution: '&copy; Google Terrain' }}),
      osm: L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19, attribution: '&copy; OpenStreetMap' }})
    }};

    const map = L.map('map', {{
      center: [-35.43, -71.66],
      zoom: 10,
      layers: [capas.satelite]
    }});

    let capaRutas = L.featureGroup().addTo(map);
    let capaHitos = L.featureGroup().addTo(map);
    let capaTiemposZoomMedio = L.featureGroup().addTo(map);
    let capaTiemposZoomCercano = L.featureGroup().addTo(map);

    document.getElementById('select-mapa').addEventListener('change', (e) => {{
      Object.values(capas).forEach(c => map.removeLayer(c));
      capas[e.target.value].addTo(map);
    }});

    // 2. Colapsar / Expandir Panel
    const toggleBtn = document.getElementById('toggle-panel-btn');
    const mainPanel = document.getElementById('main-panel');
    toggleBtn.addEventListener('click', () => {{
      const estaOculto = mainPanel.classList.toggle('hidden');
      toggleBtn.classList.toggle('collapsed', estaOculto);
      toggleBtn.textContent = estaOculto ? '▶' : '◀';
    }});

    // 3. Llenar Selectores
    const selVeh = document.getElementById('select-vehiculo');
    listaVehiculos.forEach(v => {{
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = v.label;
      selVeh.appendChild(opt);
    }});

    const selDia = document.getElementById('select-dia');
    listaDias.forEach(d => {{
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      selDia.appendChild(opt);
    }});

    function colorGradiente(t) {{
      let r, g, b;
      if (t < 0.5) {{
        const f = t / 0.5;
        r = Math.round(6 + f * (37 - 6));
        g = Math.round(182 + f * (99 - 182));
        b = Math.round(212 + f * (235 - 212));
      }} else {{
        const f = (t - 0.5) / 0.5;
        r = Math.round(37 + f * (147 - 37));
        g = Math.round(99 + f * (51 - 99));
        b = Math.round(235 + f * (234 - 235));
      }}
      return `rgb(${{r}},${{g}},${{b}})`;
    }}

    // 4. Refrescar Viajes y Paradas al cambiar selección
    function refrescarOpcionesDia() {{
      const vehId = selVeh.value;
      const dia = selDia.value;
      const tripsList = document.getElementById('trips-list');
      const stopsList = document.getElementById('stops-list');

      tripsList.innerHTML = '';
      stopsList.innerHTML = '';

      if (!datosGPS[vehId]) return;

      const infoVeh = datosGPS[vehId];
      document.getElementById('conductor-nombre').textContent = infoVeh.conductor || "Sin Asignar";

      if (!infoVeh.dias[dia]) {{
        tripsList.innerHTML = '<div style="color:#64748b; padding:4px;">Sin datos para este día.</div>';
        actualizarMapa();
        return;
      }}

      const infoDia = infoVeh.dias[dia];

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

      if (infoDia.paradas.length === 0) {{
        stopsList.innerHTML = '<div style="color:#64748b; padding:4px;">Sin paradas detectadas.</div>';
      }} else {{
        infoDia.paradas.forEach((p, pIdx) => {{
          const card = document.createElement('div');
          card.className = 'stop-card';
          const durStr = p.duracion_min >= 60 
            ? `${{Math.floor(p.duracion_min/60)}}h ${{p.duracion_min%60}}m` 
            : `${{p.duracion_min}} min`;
          card.innerHTML = `
            <div><span class="stop-time">🛑 Parada ${{pIdx + 1}} (${{durStr}}):</span> ${{p.inicio}} &rarr; ${{p.fin}}</div>
            <div style="color:#475569; font-size:10px; margin-top:2px;">${{p.direccion}}</div>
          `;
          card.onclick = () => {{
            map.flyTo([p.lat, p.lon], 16, {{ duration: 1 }});
            L.popup()
              .setLatLng([p.lat, p.lon])
              .setContent(`<b>🛑 PARADA REGISTRADA #${{pIdx + 1}}</b><br>Conductor: <b>${{infoVeh.conductor}}</b><br>Horario: ${{p.inicio}} &rarr; ${{p.fin}}<br>Duración: ${{durStr}}<br>Lugar: ${{p.direccion}}`)
              .openOn(map);
          }};
          stopsList.appendChild(card);
        }});
      }}

      tripsList.querySelectorAll('.trip-cb').forEach(cb => {{
        cb.addEventListener('change', actualizarMapa);
      }});

      actualizarMapa();
    }}

    // 5. Renderizado Principal
    function actualizarMapa() {{
      capaRutas.clearLayers();
      capaHitos.clearLayers();
      capaTiemposZoomMedio.clearLayers();
      capaTiemposZoomCercano.clearLayers();

      const vehId = selVeh.value;
      const dia = selDia.value;
      const usarGradiente = document.getElementById('check-gradiente').checked;

      if (!datosGPS[vehId] || !datosGPS[vehId].dias[dia]) {{
        document.getElementById('total-km-badge').textContent = "0.0 km";
        return;
      }}

      const infoVeh = datosGPS[vehId];
      const infoDia = infoVeh.dias[dia];
      const conductor = infoVeh.conductor;
      const placa = infoVeh.placa;

      const cbs = document.querySelectorAll('.trip-cb:checked');
      const indicesActivos = Array.from(cbs).map(cb => parseInt(cb.dataset.idx));

      let kmTotales = 0.0;
      const bounds = [];

      indicesActivos.forEach(idx => {{
        const viaje = infoDia.viajes[idx];
        if (!viaje) return;

        kmTotales += viaje.km;
        const pts = viaje.puntos;

        for (let i = 0; i < pts.length - 1; i++) {{
          const p1 = pts[i];
          const p2 = pts[i + 1];
          const colorSeg = usarGradiente ? colorGradiente(p1.fraccion) : '#06b6d4';

          const segLine = L.polyline([[p1.lat, p1.lon], [p2.lat, p2.lon]], {{
            color: colorSeg,
            weight: 5,
            opacity: 0.88,
            lineJoin: 'round'
          }}).bindTooltip(`<b>${{viaje.nombre}}</b><br>Conductor: <b>${{conductor}}</b><br>Hora: ${{p1.hora}}<br>Velocidad: ${{p1.vel}} km/h`);
          capaRutas.addLayer(segLine);
          bounds.push([p1.lat, p1.lon]);
        }}
        if (pts.length > 0) bounds.push([pts[pts.length - 1].lat, pts[pts.length - 1].lon]);

        const ini = viaje.inicio_coord;
        const fin = viaje.fin_coord;

        const iconIni = L.divIcon({{
          className: '',
          html: `<div class="badge-label badge-start">🏁 Inicio ${{viaje.nombre}} (${{viaje.hora_inicio}})</div>`,
          iconAnchor: [30, 24]
        }});
        capaHitos.addLayer(L.marker([ini[0], ini[1]], {{ icon: iconIni }}).bindPopup(`<b>🏁 INICIO DE ${{viaje.nombre.toUpperCase()}}</b><br>Vehículo: ${{placa}}<br>Conductor: <b>${{conductor}}</b><br>Hora: ${{viaje.hora_inicio}}`));

        const iconFin = L.divIcon({{
          className: '',
          html: `<div class="badge-label badge-end">⏹️ Fin ${{viaje.nombre}} (${{viaje.hora_fin}})</div>`,
          iconAnchor: [30, 24]
        }});
        capaHitos.addLayer(L.marker([fin[0], fin[1]], {{ icon: iconFin }}).bindPopup(`<b>⏹️ FIN DE ${{viaje.nombre.toUpperCase()}}</b><br>Vehículo: ${{placa}}<br>Conductor: <b>${{conductor}}</b><br>Hora: ${{viaje.hora_fin}}`));

        if (viaje.reanudacion) {{
          const r = viaje.reanudacion;
          const iconResume = L.divIcon({{
            className: '',
            html: `<div class="badge-label badge-resume">⚡ Salida tras parada: ${{r.hora}}</div>`,
            iconAnchor: [40, 24]
          }});
          capaHitos.addLayer(L.marker([r.lat, r.lon], {{ icon: iconResume }}).bindPopup(`
            <b>⚡ REANUDACIÓN DE MARCHA</b><br>
            Conductor: <b>${{conductor}}</b><br>
            Hora de arranque: ${{r.hora}}<br>
            Velocidad inicial: ${{r.vel}} km/h
          `));
        }}

        viaje.flechas.forEach(f => {{
          const esExceso = f.es_exceso;
          const colorIcono = esExceso ? '#ef4444' : '#1d4ed8';
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
                <b>Vehículo:</b> ${{placa}}<br>
                <b>Conductor:</b> <b>${{conductor}}</b><br>
                <b>Velocidad:</b> ${{f.vel}} km/h<br>
                <b>Hora:</b> ${{f.hora}}<br>
                <b>Lugar:</b> ${{f.direccion}}
              </div>
            `);
            capaHitos.addLayer(marker);
          }} else {{
            marker.bindTooltip(`${{f.hora}} | ${{f.vel}} km/h`, {{ direction: 'top', offset: [0, -6] }});
            capaRutas.addLayer(marker);
          }}
        }});

        pts.forEach((p, idxPt) => {{
          if (idxPt > 0 && idxPt < pts.length - 1 && idxPt % 25 === 0) {{
            const badgeMedio = L.marker([p.lat, p.lon], {{
              icon: L.divIcon({{
                className: '',
                html: `<div class="badge-label" style="background:rgba(30,41,59,0.75); font-size:9px;">⏱️ ${{p.hora}}</div>`,
                iconAnchor: [20, 10]
              }})
            }});
            capaTiemposZoomMedio.addLayer(badgeMedio);
          }}
          if (idxPt > 0 && idxPt < pts.length - 1 && idxPt % 6 === 0) {{
            const badgeCercano = L.circleMarker([p.lat, p.lon], {{
              radius: 4,
              color: '#3b82f6',
              fillColor: '#ffffff',
              fillOpacity: 1,
              weight: 2
            }}).bindTooltip(`<b>${{p.hora}}</b> | ${{p.vel}} km/h`, {{ permanent: false, direction: 'top' }});
            capaTiemposZoomCercano.addLayer(badgeCercano);
          }}
        }});
      }});

      document.getElementById('total-km-badge').textContent = kmTotales.toFixed(1) + " km";

      if (bounds.length > 0) {{
        map.fitBounds(bounds, {{ padding: [35, 35] }});
      }}

      controlarCapasPorZoom();
    }}

    function controlarCapasPorZoom() {{
      const z = map.getZoom();
      if (z >= 13) {{
        if (!map.hasLayer(capaTiemposZoomMedio)) map.addLayer(capaTiemposZoomMedio);
      }} else {{
        if (map.hasLayer(capaTiemposZoomMedio)) map.removeLayer(capaTiemposZoomMedio);
      }}

      if (z >= 15) {{
        if (!map.hasLayer(capaTiemposZoomCercano)) map.addLayer(capaTiemposZoomCercano);
      }} else {{
        if (map.hasLayer(capaTiemposZoomCercano)) map.removeLayer(capaTiemposZoomCercano);
      }}
    }}

    map.on('zoomend', controlarCapasPorZoom);

    function irAPunto(tipo) {{
      const vehId = selVeh.value;
      const dia = selDia.value;
      if (!datosGPS[vehId] || !datosGPS[vehId].dias[dia]) return;
      const coords = tipo === 'inicio' ? datosGPS[vehId].dias[dia].inicio_dia : datosGPS[vehId].dias[dia].fin_dia;
      map.flyTo([coords[0], coords[1]], 16, {{ duration: 1 }});
    }}

    selVeh.addEventListener('change', refrescarOpcionesDia);
    selDia.addEventListener('change', refrescarOpcionesDia);
    document.getElementById('check-gradiente').addEventListener('change', actualizarMapa);

    refrescarOpcionesDia();
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    df_raw = obtener_datos()
    vehiculos_info, dias, estructura = procesar_telemetria_viajes(df_raw)
    html_out = generar_html_mapa(vehiculos_info, dias, estructura)

    ruta = os.path.join("docs", "rutas_gps.html")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Visor GPS con Conductores generado exitosamente en: {ruta}")
