import os
import math
import json
import html as html_lib
import tempfile
import pandas as pd
import gspread
import google.auth


UMBRAL_CORTE_VIAJE_MIN = float(os.environ.get("GPS_UMBRAL_CORTE_MIN", "25"))
UMBRAL_DETECCION_PARADA_MIN = float(os.environ.get("GPS_UMBRAL_PARADA_MIN", "3"))
RADIO_PARADA_M = float(os.environ.get("GPS_RADIO_PARADA_M", "45"))
VELOCIDAD_PARADA_KMH = float(os.environ.get("GPS_VELOCIDAD_PARADA_KMH", "5"))
VELOCIDAD_IMPLICITA_MAX_KMH = float(os.environ.get("GPS_VELOCIDAD_IMPLICITA_MAX_KMH", "220"))
ZONA_HORARIA = os.environ.get("GPS_TIMEZONE", "America/Santiago")
FORMATO_FECHA_HORA = os.environ.get("GPS_DATETIME_FORMAT", "").strip() or None

COLUMNAS_OBLIGATORIAS = {"Vehículo", "Fecha", "Hora", "Latitud", "Longitud", "Velocidad"}
DEFAULT_SPREADSHEET_ID = "1n-edOD5p1K99m2m78SoTlJSnXDU_rY69Vxk5yttPgHg"

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
        "https://www.googleapis.com/auth/spreadsheets.readonly"
    ])
    gc = gspread.authorize(credentials)
    # Se mantiene el ID anterior para no romper el workflow existente.
    # GPS_SPREADSHEET_ID permite reemplazarlo sin modificar el código.
    spreadsheet_id = os.environ.get("GPS_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID)
    sh = gc.open_by_key(spreadsheet_id)
    ws = sh.worksheet("Looker_GPS")
    return pd.DataFrame(ws.get_all_records())


def texto_limpio(valor, default=""):
    if pd.isna(valor):
        return default
    # La fuente trae algunas direcciones con entidades como O&#039;Higgins.
    # Se decodifican aquí y se vuelven a escapar al renderizar el HTML.
    texto = html_lib.unescape(str(valor).strip())
    return texto if texto and texto.lower() not in {"none", "null", "nan"} else default


def evento_motor_off(valor):
    texto = texto_limpio(valor).upper()
    return any(token in texto for token in (
        "MOTOR OFF", "IGNITION OFF", "IGNICIÓN OFF", "IGNICION OFF", "ENCENDIDO OFF", "APAGADO"
    ))


def calcular_km_segmento(filas):
    """Usa el odómetro de la fuente cuando es consistente; Haversine queda como respaldo."""
    km_haversine = sum(
        haversine_km(
            filas[k-1]['Latitud'], filas[k-1]['Longitud'],
            filas[k]['Latitud'], filas[k]['Longitud']
        ) for k in range(1, len(filas))
    )
    if 'Odometro' not in filas[0].index:
        return km_haversine, "GPS"

    odometros = pd.to_numeric(pd.Series([p.get('Odometro') for p in filas]), errors='coerce').dropna()
    if len(odometros) < 2:
        return km_haversine, "GPS"
    deltas = odometros.diff().dropna()
    km_odometro = float(odometros.iloc[-1] - odometros.iloc[0])
    if km_odometro >= 0 and not (deltas < -0.05).any():
        return km_odometro, "Odómetro"
    return km_haversine, "GPS"


def validar_y_normalizar(df):
    faltantes = sorted(COLUMNAS_OBLIGATORIAS - set(df.columns))
    if faltantes:
        raise ValueError(f"Faltan columnas obligatorias: {', '.join(faltantes)}")
    if df.empty:
        raise ValueError("La hoja Looker_GPS no contiene registros")

    df = df.copy()
    df["Vehículo"] = df["Vehículo"].map(texto_limpio)
    df["Latitud"] = pd.to_numeric(df["Latitud"], errors="coerce")
    df["Longitud"] = pd.to_numeric(df["Longitud"], errors="coerce")
    df["Velocidad"] = pd.to_numeric(df["Velocidad"], errors="coerce").fillna(0).clip(lower=0)

    opciones = {"errors": "coerce"}
    if FORMATO_FECHA_HORA:
        opciones["format"] = FORMATO_FECHA_HORA
    else:
        opciones["dayfirst"] = True

    if "Timestamp" in df.columns:
        df["dt"] = pd.to_datetime(df["Timestamp"], **opciones)
    else:
        df["dt"] = pd.NaT

    # Respaldo para filas sin Timestamp y para fuentes antiguas.
    fecha_base = pd.to_datetime(df["Fecha"], errors="coerce", dayfirst=True)
    texto_fecha = fecha_base.dt.strftime("%Y-%m-%d")
    texto_dt = texto_fecha + " " + df["Hora"].astype(str).str.strip()
    dt_respaldo = pd.to_datetime(texto_dt, **opciones)
    df["dt"] = df["dt"].fillna(dt_respaldo)

    validas = (
        df["Vehículo"].ne("")
        & df["dt"].notna()
        & df["Latitud"].between(-90, 90)
        & df["Longitud"].between(-180, 180)
    )
    descartadas = int((~validas).sum())
    df = df.loc[validas].copy()
    if df.empty:
        raise ValueError("No quedaron registros válidos después de validar fecha, vehículo y coordenadas")

    # La fuente representa horas locales. Localizarlas evita ambigüedad en cambios de hora.
    if df["dt"].dt.tz is None:
        df["dt"] = df["dt"].dt.tz_localize(
            ZONA_HORARIA, ambiguous="NaT", nonexistent="shift_forward"
        )
        antes = len(df)
        df = df.dropna(subset=["dt"])
        descartadas += antes - len(df)

    df = (
        df.sort_values(["Vehículo", "dt"])
        .drop_duplicates(subset=["Vehículo", "dt"], keep="last")
        .reset_index(drop=True)
    )
    df["dia"] = df["dt"].dt.strftime("%Y-%m-%d")
    df["hora_normalizada"] = df["dt"].dt.strftime("%H:%M:%S")

    # Descarta puntos que exigirían una velocidad físicamente inverosímil.
    conservar = []
    saltos = 0
    for _, grupo in df.groupby("Vehículo", sort=False):
        ultimo_idx = None
        for idx, fila in grupo.iterrows():
            if ultimo_idx is None:
                conservar.append(idx)
                ultimo_idx = idx
                continue
            anterior = df.loc[ultimo_idx]
            horas = (fila["dt"] - anterior["dt"]).total_seconds() / 3600.0
            distancia = haversine_km(
                anterior["Latitud"], anterior["Longitud"], fila["Latitud"], fila["Longitud"]
            )
            velocidad_implicita = distancia / horas if horas > 0 else float("inf")
            if velocidad_implicita <= VELOCIDAD_IMPLICITA_MAX_KMH:
                conservar.append(idx)
                ultimo_idx = idx
            else:
                saltos += 1

    df = df.loc[conservar].reset_index(drop=True)
    if df.empty:
        raise ValueError("Todos los registros fueron descartados como saltos GPS inválidos")
    print(f"Registros válidos: {len(df)}; inválidos: {descartadas}; saltos GPS: {saltos}")
    return df


def fusionar_paradas_cercanas(paradas, max_dist_m=RADIO_PARADA_M):
    """
    Fusiona paradas consecutivas en el mismo sitio físico (< 45 m)
    evitando fragmentación por pings periódicos del GPS.
    """
    if not paradas:
        return []
    
    fused = [paradas[0]]
    for p in paradas[1:]:
        prev = fused[-1]
        dist_m = haversine_km(prev['lat'], prev['lon'], p['lat'], p['lon']) * 1000.0
        
        separacion_min = (p["_inicio_dt"] - prev["_fin_dt"]).total_seconds() / 60.0
        mismo_viaje = p.get("viaje_idx") == prev.get("viaje_idx")
        # Solo fusionar eventos realmente contiguos del mismo viaje.
        if dist_m <= max_dist_m and mismo_viaje and 0 <= separacion_min <= 1.5:
            prev['fin'] = p['fin']
            prev['_fin_dt'] = p['_fin_dt']
            prev['duracion_min'] = round(
                (prev['_fin_dt'] - prev['_inicio_dt']).total_seconds() / 60.0, 1
            )
            if p.get('tipo') == 'Motor Apagado' or prev.get('tipo') == 'Motor Apagado':
                prev['tipo'] = 'Motor Apagado'
        else:
            fused.append(p)
            
    return fused

def procesar_telemetria_viajes(df):
    df = validar_y_normalizar(df)

    conductores_default = {
        "lhjl 13": "Michele Castro", "lhjl-13": "Michele Castro",
        "lhjl 14": "Administracion", "lhjl-14": "Administracion",
        "pryg 42": "Topografos",     "pryg-42": "Topografos",
        "ptjp 73": "Maximiliano Vera", "ptjp-73": "Maximiliano Vera",
        "ldyw 29": "Felipe Acevedo", "ldyw-29": "Felipe Acevedo"
    }

    nombres_vehiculos = sorted(df['Vehículo'].unique().tolist())
    dias = sorted(df['dia'].unique().tolist())
    
    vehiculos_info = []
    estructura = {}

    for v in nombres_vehiculos:
        df_v = df[df['Vehículo'] == v]
        
        placa_vehiculo = str(df_v['Placa'].dropna().iloc[0]) if ('Placa' in df_v.columns and not df_v['Placa'].dropna().empty) else str(v)
        
        conductor_vehiculo = "Sin Asignar"
        if 'Conductor' in df_v.columns:
            cond_series = df_v['Conductor'].dropna().astype(str)
            cond_series = cond_series[~cond_series.isin(["", "None", "null", "Sin Asignar"])]
            if not cond_series.empty:
                conductor_vehiculo = cond_series.mode()[0]

        if conductor_vehiculo in ["Sin Asignar", "", "None", "null"]:
            clave_placa = placa_vehiculo.lower().strip()
            clave_v = str(v).lower().strip()
            conductor_vehiculo = conductores_default.get(clave_placa, conductores_default.get(clave_v, "Sin Asignar"))

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
            sub = df_v[df_v['dia'] == dia].reset_index(drop=True)
            if sub.empty:
                continue

            viajes = []
            paradas_candidatas = []
            intervalos_sin_telemetria = []
            cortes = []  # (último punto del tramo anterior, primer punto del siguiente)

            # Detectar permanencia real dentro de un radio, incluso con pings frecuentes.
            inicio_cluster = None
            cluster_motor_off = False
            for i in range(len(sub) - 1):
                actual, siguiente = sub.iloc[i], sub.iloc[i + 1]
                delta_min = (siguiente['dt'] - actual['dt']).total_seconds() / 60.0
                dist_m = haversine_km(
                    actual['Latitud'], actual['Longitud'], siguiente['Latitud'], siguiente['Longitud']
                ) * 1000.0
                off = evento_motor_off(actual.get('Evento')) or evento_motor_off(siguiente.get('Evento'))
                estado_detenido = (
                    texto_limpio(actual.get('Estado')).casefold() == 'detenido'
                    or texto_limpio(siguiente.get('Estado')).casefold() == 'detenido'
                )
                quieto = dist_m <= RADIO_PARADA_M and (
                    off or estado_detenido
                    or max(float(actual['Velocidad']), float(siguiente['Velocidad'])) <= VELOCIDAD_PARADA_KMH
                )

                # Un hueco grande es falta de telemetría, salvo evidencia espacial de permanencia.
                if delta_min >= UMBRAL_DETECCION_PARADA_MIN and not quieto:
                    intervalos_sin_telemetria.append({
                        'inicio': actual['hora_normalizada'],
                        'fin': siguiente['hora_normalizada'],
                        'duracion_min': round(delta_min, 1),
                        'lat_inicio': float(actual['Latitud']),
                        'lon_inicio': float(actual['Longitud']),
                        'lat_fin': float(siguiente['Latitud']),
                        'lon_fin': float(siguiente['Longitud'])
                    })
                    if delta_min >= UMBRAL_CORTE_VIAJE_MIN:
                        cortes.append((i, i + 1))

                if quieto:
                    if inicio_cluster is None:
                        inicio_cluster = i
                        cluster_motor_off = off
                    else:
                        cluster_motor_off = cluster_motor_off or off
                elif inicio_cluster is not None:
                    fin_cluster = i
                    duracion = (sub.iloc[fin_cluster]['dt'] - sub.iloc[inicio_cluster]['dt']).total_seconds() / 60.0
                    if duracion >= UMBRAL_DETECCION_PARADA_MIN:
                        paradas_candidatas.append((inicio_cluster, fin_cluster, duracion, cluster_motor_off))
                        if duracion >= UMBRAL_CORTE_VIAJE_MIN:
                            cortes.append((inicio_cluster, fin_cluster))
                    inicio_cluster = None
                    cluster_motor_off = False

            if inicio_cluster is not None:
                fin_cluster = len(sub) - 1
                duracion = (sub.iloc[fin_cluster]['dt'] - sub.iloc[inicio_cluster]['dt']).total_seconds() / 60.0
                if duracion >= UMBRAL_DETECCION_PARADA_MIN:
                    paradas_candidatas.append((inicio_cluster, fin_cluster, duracion, cluster_motor_off))
                    if duracion >= UMBRAL_CORTE_VIAJE_MIN:
                        cortes.append((inicio_cluster, fin_cluster))

            # Construir viajes sin insertar puntos del tramo previo ni contar huecos.
            cortes = sorted(set(cortes))
            segmentos = []
            inicio = 0
            for izquierda, derecha in cortes:
                if izquierda >= inicio:
                    segmentos.append(sub.iloc[inicio:izquierda + 1])
                inicio = max(inicio, derecha)
            if inicio < len(sub):
                segmentos.append(sub.iloc[inicio:])

            for segmento in segmentos:
                if len(segmento) < 2:
                    continue
                filas = [fila for _, fila in segmento.iterrows()]
                km_viaje, metodo_km = calcular_km_segmento(filas)
                if km_viaje >= 0.3:
                    viajes.append({
                        'puntos': filas, 'km_raw': km_viaje,
                        'metodo_km': metodo_km, 'reanudacion': None
                    })

            # Conductor específico del día, no el más frecuente de todo el período.
            conductor_dia = conductor_vehiculo
            if 'Conductor' in sub.columns:
                candidatos = sub['Conductor'].map(texto_limpio)
                candidatos = candidatos[candidatos.ne('')]
                if not candidatos.empty:
                    conductor_dia = candidatos.mode().iloc[0]

            # Relacionar cada parada con el viaje inmediatamente anterior o posterior.
            paradas_normalizadas = []
            for inicio_p, fin_p, duracion, motor_off in paradas_candidatas:
                fila_ini, fila_fin = sub.iloc[inicio_p], sub.iloc[fin_p]
                viaje_idx = 0
                for idx_v, item in enumerate(viajes):
                    if item['puntos'][0]['dt'] <= fila_ini['dt']:
                        viaje_idx = idx_v
                paradas_normalizadas.append({
                    'viaje_idx': viaje_idx,
                    'inicio': fila_ini['hora_normalizada'],
                    'fin': fila_fin['hora_normalizada'],
                    'duracion_min': round(duracion, 1),
                    'tipo': 'Motor Apagado' if motor_off else 'Detención confirmada',
                    'lat': float(fila_ini['Latitud']),
                    'lon': float(fila_ini['Longitud']),
                    'direccion': texto_limpio(fila_ini.get('Direccion'), 'Sin dirección'),
                    '_inicio_dt': fila_ini['dt'],
                    '_fin_dt': fila_fin['dt']
                })

            paradas_candidatas = paradas_normalizadas

            # FUSIONAR PARADAS CONTIGUAS (< 45 metros)
            paradas_fusionadas = fusionar_paradas_cercanas(paradas_candidatas)

            viajes_json = []
            for num_v, v_item in enumerate(viajes):
                pts_v = v_item['puntos']
                km_v = v_item['km_raw']
                puntos_detallados = []
                flechas = []

                for i in range(len(pts_v)):
                    fila = pts_v[i]
                    lat, lon = float(fila['Latitud']), float(fila['Longitud'])
                    vel = float(fila['Velocidad'])
                    hora = fila['hora_normalizada']

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
                    'km': round(km_v, 1),
                    'km_raw': round(km_v, 4),
                    'metodo_km': v_item['metodo_km'],
                    'hora_inicio': pts_v[0]['hora_normalizada'],
                    'hora_fin': pts_v[-1]['hora_normalizada'],
                    'inicio_coord': [float(pts_v[0]['Latitud']), float(pts_v[0]['Longitud'])],
                    'fin_coord': [float(pts_v[-1]['Latitud']), float(pts_v[-1]['Longitud'])],
                    'reanudacion': v_item['reanudacion'],
                    'puntos': puntos_detallados,
                    'flechas': flechas
                })

            for parada in paradas_fusionadas:
                parada.pop('_inicio_dt', None)
                parada.pop('_fin_dt', None)

            estructura[v]['dias'][dia] = {
                'conductor': conductor_dia,
                'viajes': viajes_json,
                'paradas': paradas_fusionadas,
                'intervalos_sin_telemetria': intervalos_sin_telemetria,
                'inicio_dia': [float(sub.iloc[0]['Latitud']), float(sub.iloc[0]['Longitud']), sub.iloc[0]['hora_normalizada']],
                'fin_dia': [float(sub.iloc[-1]['Latitud']), float(sub.iloc[-1]['Longitud']), sub.iloc[-1]['hora_normalizada']]
            }

    return vehiculos_info, dias, estructura

def generar_html_mapa(vehiculos_info, dias, datos):
    def json_seguro_para_script(valor):
        return (
            json.dumps(valor, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

    datos_json = json_seguro_para_script(datos)
    vehiculos_json = json_seguro_para_script(vehiculos_info)
    dias_json = json_seguro_para_script(dias)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Visor de Rutas GPS y Auditoría de Flota</title>
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

    .stops-box {{
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: 6px;
      padding: 8px 10px;
      margin-bottom: 10px;
    }}
    .stops-box label {{ color: #92400e; }}
    .stops-suboptions {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-top: 6px;
      font-size: 11px;
      color: #78350f;
    }}
    .stops-suboptions label {{ display: flex; align-items: center; gap: 5px; cursor: pointer; text-transform: none; font-weight: 500; }}

    .stops-container {{
      max-height: 120px;
      overflow-y: auto;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #fff;
      padding: 4px;
    }}
    .telemetry-box {{
      background: #fef2f2;
      border: 1px solid #fecaca;
      border-radius: 6px;
      padding: 8px 10px;
      margin-bottom: 10px;
      color: #991b1b;
      font-size: 11px;
    }}
    .telemetry-item {{
      padding: 4px 0;
      border-bottom: 1px solid #fee2e2;
    }}
    .stop-card {{
      padding: 5px 6px;
      border-bottom: 1px solid #f1f5f9;
      cursor: pointer;
      font-size: 11px;
      border-radius: 4px;
    }}
    .stop-card:hover {{ background: #fef3c7; }}
    .stop-badge-off {{ color: #b45309; font-weight: 700; }}
    .stop-badge-idle {{ color: #7c3aed; font-weight: 700; }}

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

    <div class="form-group">
      <label for="select-mapa">Capa Base</label>
      <select id="select-mapa">
        <option value="satelite" selected>Google Satélite (Híbrido)</option>
        <option value="calles">Google Calles</option>
        <option value="relieve">Google Relieve</option>
        <option value="osm">OpenStreetMap</option>
      </select>
    </div>

    <div class="form-group">
      <label for="select-vehiculo">Vehículo & Conductor</label>
      <select id="select-vehiculo"></select>
    </div>

    <div class="conductor-card">
      <div class="title">Conductor Asignado</div>
      <div class="name" id="conductor-nombre">—</div>
    </div>

    <div class="form-group">
      <label for="select-dia">Día Seleccionado</label>
      <select id="select-dia"></select>
    </div>

    <div class="km-badge">
      <span>Distancia de Viajes:</span>
      <span id="total-km-badge">0.0 km</span>
    </div>

    <div class="nav-buttons">
      <button class="btn-nav" onclick="irAPunto('inicio')">📍 Inicio del Día</button>
      <button class="btn-nav" onclick="irAPunto('fin')">🏁 Fin del Día</button>
    </div>

    <div class="form-group">
      <label>Viajes Detectados</label>
      <div class="trips-container" id="trips-list"></div>
    </div>

    <div class="stops-box">
      <label for="select-umbral-parada">Filtro de Detención Mínima</label>
      <select id="select-umbral-parada">
        <option value="3">Mayor a 3 minutos</option>
        <option value="5">Mayor a 5 minutos</option>
        <option value="10">Mayor a 10 minutos</option>
        <option value="15">Mayor a 15 minutos</option>
        <option value="20" selected>Mayor a 20 minutos (Estándar)</option>
        <option value="30">Mayor a 30 minutos (Faena)</option>
        <option value="60">Mayor a 1 hora (Prolongada)</option>
      </select>
      
      <div class="stops-suboptions">
        <label>
          <input type="checkbox" id="check-mostrar-paradas" checked>
          <span>Mostrar marcadores de detención en mapa</span>
        </label>
        <label>
          <input type="checkbox" id="check-tamano-proporcional" checked>
          <span>Aumentar tamaño según duración</span>
        </label>
      </div>
    </div>

    <div class="form-group">
      <label id="label-conteo-paradas">Paradas Filtradas</label>
      <div class="stops-container" id="stops-list"></div>
    </div>

    <div class="telemetry-box">
      <b id="label-telemetria">Intervalos sin telemetría: 0</b>
      <div id="telemetry-list"></div>
    </div>

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
  </div>

  <script>
    const datosGPS = {datos_json};
    const listaVehiculos = {vehiculos_json};
    const listaDias = {dias_json};

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
    let capaParadas = L.featureGroup().addTo(map);
    let capaTelemetria = L.featureGroup().addTo(map);
    let capaTiemposZoomMedio = L.featureGroup().addTo(map);
    let capaTiemposZoomCercano = L.featureGroup().addTo(map);

    document.getElementById('select-mapa').addEventListener('change', (e) => {{
      Object.values(capas).forEach(c => map.removeLayer(c));
      capas[e.target.value].addTo(map);
    }});

    const toggleBtn = document.getElementById('toggle-panel-btn');
    const mainPanel = document.getElementById('main-panel');
    toggleBtn.addEventListener('click', () => {{
      const estaOculto = mainPanel.classList.toggle('hidden');
      toggleBtn.classList.toggle('collapsed', estaOculto);
      toggleBtn.textContent = estaOculto ? '▶' : '◀';
    }});

    const selVeh = document.getElementById('select-vehiculo');
    listaVehiculos.forEach(v => {{
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = v.label;
      selVeh.appendChild(opt);
    }});

    const selDia = document.getElementById('select-dia');

    function esc(valor) {{
      return String(valor ?? '').replace(/[&<>"']/g, caracter => ({{
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }})[caracter]);
    }}

    function cargarDiasDelVehiculo(conservarSeleccion = true) {{
      const seleccionAnterior = conservarSeleccion ? selDia.value : '';
      const diasVehiculo = Object.keys(datosGPS[selVeh.value]?.dias || {{}}).sort();
      selDia.replaceChildren();
      diasVehiculo.forEach(d => {{
        const opt = document.createElement('option');
        opt.value = d;
        opt.textContent = d;
        selDia.appendChild(opt);
      }});
      if (diasVehiculo.includes(seleccionAnterior)) selDia.value = seleccionAnterior;
    }}

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

    function refrescarOpcionesDia() {{
      const vehId = selVeh.value;
      const dia = selDia.value;
      const tripsList = document.getElementById('trips-list');

      tripsList.innerHTML = '';

      if (!datosGPS[vehId]) return;

      const infoVeh = datosGPS[vehId];
      const infoDia = infoVeh.dias[dia];
      document.getElementById('conductor-nombre').textContent = infoDia?.conductor || infoVeh.conductor || "Sin Asignar";

      if (!infoDia) {{
        tripsList.innerHTML = '<div style="color:#64748b; padding:4px;">Sin datos para este día.</div>';
        actualizarMapa();
        return;
      }}

      infoDia.viajes.forEach((v, idx) => {{
        const row = document.createElement('div');
        row.className = 'trip-item';
        row.innerHTML = `
          <label style="display:flex; align-items:center; cursor:pointer;">
            <input type="checkbox" class="trip-cb" data-idx="${{idx}}" checked>
            <b>${{esc(v.nombre)}}</b> (${{esc(v.hora_inicio)}} - ${{esc(v.hora_fin)}})
          </label>
          <span style="color:#0284c7; font-weight:700;">${{v.km}} km</span>
        `;
        tripsList.appendChild(row);
      }});

      tripsList.querySelectorAll('.trip-cb').forEach(cb => {{
        cb.addEventListener('change', actualizarMapa);
      }});

      actualizarMapa();
    }}

    function renderizarParadas(paradas, conductor, indicesActivos = []) {{
      capaParadas.clearLayers();
      const stopsList = document.getElementById('stops-list');
      stopsList.innerHTML = '';

      const umbralMin = parseFloat(document.getElementById('select-umbral-parada').value);
      const mostrarEnMapa = document.getElementById('check-mostrar-paradas').checked;
      const tamanoProporcional = document.getElementById('check-tamano-proporcional').checked;

      // Filtrar paradas de rutas activas y >= umbral
      const paradasFiltradas = paradas.filter(p => {{
        const perteneceARutaActiva = indicesActivos.includes(p.viaje_idx);
        return perteneceARutaActiva && (p.duracion_min >= umbralMin);
      }});

      document.getElementById('label-conteo-paradas').textContent = `Paradas (&ge; ${{umbralMin}} min): ${{paradasFiltradas.length}}`;

      if (paradasFiltradas.length === 0) {{
        stopsList.innerHTML = `<div style="color:#64748b; padding:4px; font-size:11px;">Sin paradas en las rutas seleccionadas.</div>`;
        return;
      }}

      paradasFiltradas.forEach((p, pIdx) => {{
        const durStr = p.duracion_min >= 60 
          ? `${{Math.floor(p.duracion_min/60)}}h ${{Math.round(p.duracion_min%60)}}m` 
          : `${{Math.round(p.duracion_min)}} min`;

        const esMotorOff = p.tipo === "Motor Apagado";
        const badgeClass = esMotorOff ? "stop-badge-off" : "stop-badge-idle";
        const iconPrefix = esMotorOff ? "🛑 Motor apagado" : "📍 Detención confirmada";

        const card = document.createElement('div');
        card.className = 'stop-card';
        card.innerHTML = `
          <div><span class="${{badgeClass}}">${{iconPrefix}} #${{pIdx + 1}} (${{durStr}}):</span> ${{esc(p.inicio)}} &rarr; ${{esc(p.fin)}}</div>
          <div style="color:#475569; font-size:10px; margin-top:2px;">${{esc(p.direccion)}}</div>
        `;
        card.onclick = () => {{
          map.flyTo([p.lat, p.lon], 16, {{ duration: 1 }});
          L.popup()
            .setLatLng([p.lat, p.lon])
            .setContent(`<b>${{iconPrefix.toUpperCase()}} #${{pIdx + 1}}</b><br>Conductor: <b>${{esc(conductor)}}</b><br>Horario: ${{esc(p.inicio)}} &rarr; ${{esc(p.fin)}}<br>Duración: ${{durStr}}<br>Clasificación: <b>${{esc(p.tipo)}}</b><br>Lugar: ${{esc(p.direccion)}}`)
            .openOn(map);
        }};
        stopsList.appendChild(card);

        if (mostrarEnMapa) {{
          const radioCirculo = tamanoProporcional 
            ? Math.min(32, Math.round(7 + Math.sqrt(p.duracion_min) * 1.5))
            : 7;

          const colorBorde = esMotorOff ? '#b45309' : '#6d28d9';
          const colorRelleno = esMotorOff ? '#f59e0b' : '#8b5cf6';

          const circle = L.circleMarker([p.lat, p.lon], {{
            radius: radioCirculo,
            color: colorBorde,
            weight: 2,
            fillColor: colorRelleno,
            fillOpacity: tamanoProporcional ? 0.38 : 0.85
          }}).bindPopup(`
            <div style="font-size:12px; line-height:1.4;">
              <b style="color:${{colorBorde}}; font-size:13px;">${{iconPrefix.toUpperCase()}}</b><br>
              <b>Conductor:</b> ${{esc(conductor)}}<br>
              <b>Duración:</b> ${{durStr}}<br>
              <b>Horario:</b> ${{esc(p.inicio)}} &rarr; ${{esc(p.fin)}}<br>
              <b>Condición:</b> ${{esc(p.tipo)}}<br>
              <b>Lugar:</b> ${{esc(p.direccion)}}
            </div>
          `);

          circle.bindTooltip(`${{esMotorOff ? '🛑' : '⏳'}} ${{durStr}} (${{p.inicio}})`, {{ direction: 'top', offset: [0, -radioCirculo] }});
          capaParadas.addLayer(circle);
        }}
      }});
    }}

    function renderizarIntervalosSinTelemetria(intervalos) {{
      capaTelemetria.clearLayers();
      const lista = document.getElementById('telemetry-list');
      lista.replaceChildren();
      document.getElementById('label-telemetria').textContent =
        `Intervalos sin telemetría: ${{intervalos.length}}`;

      intervalos.forEach((item, idx) => {{
        const fila = document.createElement('div');
        fila.className = 'telemetry-item';
        fila.textContent = `⚠ ${{item.inicio}} → ${{item.fin}} (${{item.duracion_min}} min)`;
        lista.appendChild(fila);

        const linea = L.polyline(
          [[item.lat_inicio, item.lon_inicio], [item.lat_fin, item.lon_fin]],
          {{ color: '#dc2626', weight: 2, opacity: 0.65, dashArray: '7 7' }}
        ).bindTooltip(
          `<b>Sin telemetría</b><br>${{esc(item.inicio)}} → ${{esc(item.fin)}}<br>${{item.duracion_min}} min<br>Este tramo no se suma a la distancia.`
        );
        capaTelemetria.addLayer(linea);
      }});
    }}

    function actualizarMapa() {{
      capaRutas.clearLayers();
      capaHitos.clearLayers();
      capaTelemetria.clearLayers();
      capaTiemposZoomMedio.clearLayers();
      capaTiemposZoomCercano.clearLayers();

      const vehId = selVeh.value;
      const dia = selDia.value;
      const usarGradiente = document.getElementById('check-gradiente').checked;

      const cbs = document.querySelectorAll('.trip-cb:checked');
      const indicesActivos = Array.from(cbs).map(cb => parseInt(cb.dataset.idx));

      if (!datosGPS[vehId] || !datosGPS[vehId].dias[dia]) {{
        document.getElementById('total-km-badge').textContent = "0.0 km";
        renderizarParadas([], "", []);
        renderizarIntervalosSinTelemetria([]);
        return;
      }}

      const infoVeh = datosGPS[vehId];
      const infoDia = infoVeh.dias[dia];
      const conductor = infoDia.conductor || infoVeh.conductor;
      const placa = infoVeh.placa;

      renderizarParadas(infoDia.paradas, conductor, indicesActivos);
      renderizarIntervalosSinTelemetria(infoDia.intervalos_sin_telemetria || []);

      let kmTotales = 0.0;
      const bounds = [];

      indicesActivos.forEach(idx => {{
        const viaje = infoDia.viajes[idx];
        if (!viaje) return;

        kmTotales += viaje.km_raw ?? viaje.km;
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
          }}).bindTooltip(`<b>${{esc(viaje.nombre)}}</b><br>Conductor: <b>${{esc(conductor)}}</b><br>Hora: ${{esc(p1.hora)}}<br>Velocidad: ${{p1.vel}} km/h`);
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
        capaHitos.addLayer(L.marker([ini[0], ini[1]], {{ icon: iconIni }}).bindPopup(`<b>🏁 INICIO DE ${{esc(viaje.nombre.toUpperCase())}}</b><br>Vehículo: ${{esc(placa)}}<br>Conductor: <b>${{esc(conductor)}}</b><br>Hora: ${{esc(viaje.hora_inicio)}}`));

        const iconFin = L.divIcon({{
          className: '',
          html: `<div class="badge-label badge-end">⏹️ Fin ${{viaje.nombre}} (${{viaje.hora_fin}})</div>`,
          iconAnchor: [30, 24]
        }});
        capaHitos.addLayer(L.marker([fin[0], fin[1]], {{ icon: iconFin }}).bindPopup(`<b>⏹️ FIN DE ${{esc(viaje.nombre.toUpperCase())}}</b><br>Vehículo: ${{esc(placa)}}<br>Conductor: <b>${{esc(conductor)}}</b><br>Hora: ${{esc(viaje.hora_fin)}}`));

        if (viaje.reanudacion) {{
          const r = viaje.reanudacion;
          const iconResume = L.divIcon({{
            className: '',
            html: `<div class="badge-label badge-resume">⚡ Salida tras parada: ${{r.hora}}</div>`,
            iconAnchor: [40, 24]
          }});
          capaHitos.addLayer(L.marker([r.lat, r.lon], {{ icon: iconResume }}).bindPopup(`
            <b>⚡ REANUDACIÓN DE MARCHA</b><br>
            Conductor: <b>${{esc(conductor)}}</b><br>
            Hora de arranque: ${{esc(r.hora)}}<br>
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
                <b>Vehículo:</b> ${{esc(placa)}}<br>
                <b>Conductor:</b> <b>${{esc(conductor)}}</b><br>
                <b>Velocidad:</b> ${{f.vel}} km/h<br>
                <b>Hora:</b> ${{esc(f.hora)}}<br>
                <b>Lugar:</b> ${{esc(f.direccion)}}
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

    function refrescarFiltroParadas() {{
      const vehId = selVeh.value;
      const dia = selDia.value;
      if (datosGPS[vehId] && datosGPS[vehId].dias[dia]) {{
        const cbs = document.querySelectorAll('.trip-cb:checked');
        const indicesActivos = Array.from(cbs).map(cb => parseInt(cb.dataset.idx));
        const infoDia = datosGPS[vehId].dias[dia];
        renderizarParadas(infoDia.paradas, infoDia.conductor || datosGPS[vehId].conductor, indicesActivos);
      }}
    }}

    selVeh.addEventListener('change', () => {{
      cargarDiasDelVehiculo(false);
      refrescarOpcionesDia();
    }});
    selDia.addEventListener('change', refrescarOpcionesDia);
    document.getElementById('check-gradiente').addEventListener('change', actualizarMapa);

    document.getElementById('select-umbral-parada').addEventListener('change', refrescarFiltroParadas);
    document.getElementById('check-mostrar-paradas').addEventListener('change', refrescarFiltroParadas);
    document.getElementById('check-tamano-proporcional').addEventListener('change', refrescarFiltroParadas);

    cargarDiasDelVehiculo(false);
    refrescarOpcionesDia();
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    os.makedirs("docs", exist_ok=True)
    df_raw = obtener_datos()
    vehiculos_info, dias, estructura = procesar_telemetria_viajes(df_raw)
    if not vehiculos_info or not any(info['dias'] for info in estructura.values()):
        raise RuntimeError("La actualización no produjo vehículos/días válidos; se conserva el HTML anterior")
    html_out = generar_html_mapa(vehiculos_info, dias, estructura)

    ruta = os.path.join("docs", "rutas_gps.html")
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir="docs", prefix="rutas_gps_", suffix=".tmp", delete=False
        ) as f:
            temporal = f.name
            f.write(html_out)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)
    print(f"Visor GPS actualizado de forma atómica: {ruta}")
