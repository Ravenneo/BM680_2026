import streamlit as st
import pandas as pd
import json
import os
import time
import math
import streamlit.components.v1 as components

# Configuración de página
st.set_page_config(page_title="Air Guardian", page_icon="⚙️", layout="wide")

# Estilos globales para la app
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Courier+Prime:ital,wght@0,400;0,700;1,400;1,700&family=Playfair+Display:ital,wght@0,400..900;1,400..900&display=swap');

    .stApp {
        background-color: #1a1511;
        background-image: radial-gradient(#2b221a 10%, transparent 20%),
                          radial-gradient(#2b221a 10%, transparent 20%);
        background-position: 0 0, 10px 10px;
        background-size: 20px 20px;
        color: #d4af37;
        font-family: 'Courier Prime', monospace;
    }
    
    /* Títulos y Header */
    h1, h2, h3, .stMetric label {
        font-family: 'Playfair Display', serif;
        color: #d4af37 !important;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
    }
    
    /* Sidebar Steampunk */
    [data-testid="stSidebar"] {
        background-color: #2b221a;
        border-right: 5px double #8b6508;
    }
    
    [data-testid="stSidebar"] * {
        color: #e6c27a !important;
        font-family: 'Playfair Display', serif;
    }

    /* Tarjetas de métricas */
    [data-testid="stMetric"] {
        background-color: rgba(30, 20, 15, 0.8);
        border: 2px solid #8b6508;
        border-radius: 10px;
        padding: 15px;
        box-shadow: inset 0 0 10px rgba(0,0,0,0.8);
    }
    
    .stMetric [data-testid="stMetricValue"] {
        color: #e6c27a;
    }

    /* Estilo de Gráficas (Sobreescribir colores de Streamlit si es posible) */
    .stChart {
        background-color: rgba(0,0,0,0.3);
        border-radius: 10px;
        border: 1px solid #8b6508;
        padding: 10px;
    }
</style>
""", unsafe_allow_html=True)

# Navegación en el Sidebar
st.sidebar.title("🛠️ Panel de Control")
page = st.sidebar.radio("Seleccionar Vista:", ["Real-Time", "Historial Atmosférico"])

# Auto-refresh cada 30 segundos en Real-Time
auto_refresh = st.sidebar.checkbox("Sincronización Automática (30s)", value=True)
if auto_refresh and page == "Real-Time":
    time.sleep(30)
    st.rerun()

# Rutas locales
BATCH_PATH = "air_batches_15m.jsonl"
SAMPLES_PATH = "air_samples.jsonl"

def load_jsonl(path, last_only=False):
    if not os.path.exists(path):
        return None
    
    data_list = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    data_list.append(json.loads(line))
        
        if last_only:
            return data_list[-1] if data_list else None
        return pd.DataFrame(data_list)
    except Exception as e:
        return None

# --- VISTA REAL-TIME ---
if page == "Real-Time":
    st.title("⚙️ Air Guardian Dashboard 🚂")
    
    # La vista en tiempo real ahora usa los Samples (resolución sub-segundo/2-segundos)
    latest_data = load_jsonl(SAMPLES_PATH, last_only=True)
    
    # Funciones de lógica de color importadas de led_tiles_bme680.py
    def clamp(x, a, b): return max(a, min(b, x))
    def lerp(a, b, t): return a + (b - a) * t

    def base_rgb(state, score, t_val):
        if state == "WARMUP" or state == "HEATING":
            breathe = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t_val * 0.55))
            r = 0
            g = int(lerp(18,  70, breathe))
            b = int(lerp(55, 230, breathe))
            return f"rgb({r}, {g}, {b})"

        if score is None:
            return "rgb(0, 110, 0)"

        s = float(clamp(score / 100.0, 0.0, 1.0))
        q = 1.0 - s

        if q <= 0.5:
            t2 = q / 0.5
            r = int(lerp(0,   235, t2))
            g = int(lerp(150, 235, t2))
            b = 0
        else:
            t2 = (q - 0.5) / 0.5
            r = 235
            g = int(lerp(235, 0, t2))
            b = 0
        return f"rgb({r}, {g}, {b})"

    state_class = "ok"
    temp, hum, score, heat_ratio, air_state = 0.0, 0.0, 0.0, 1.0, "UNKNOWN"
    led_color = "rgb(46, 184, 46)" # Default verde

    if latest_data is not None:
        # En air_samples.jsonl las llaves son 'temp', 'hum', 'air_score'
        temp = latest_data.get("temp", latest_data.get("temperature", 0.0))
        hum = latest_data.get("hum", latest_data.get("humidity", 0.0))
        score = latest_data.get("air_score", 0.0)
        heat_ratio = latest_data.get("heat_stable_ratio_1m", latest_data.get("heat_stable_ratio", 1.0))
        air_state = latest_data.get("state", latest_data.get("air_state_last", "OK")).upper()

        if air_state == "BAD" or (score is not None and score < 40):
            state_class = "bad"
        elif air_state == "WARMUP" or heat_ratio < 0.6:
            state_class = "heating"
            air_state = "WARMUP"
            
        t_val = time.time()
        led_color = base_rgb(air_state, score, t_val)
    else:
        st.warning("🏮 Esperando suministro de datos... Asegúrate de que data_fetcher.py esté corriendo.")

    col1, col2, col3, col4 = st.columns(4)
    # Mostramos los valores limpios al decimo
    col1.metric("Temperatura Local", f"{temp:.1f} °C" if temp is not None else "-- °C")
    col2.metric("Humedad Local", f"{hum:.1f} %" if hum is not None else "-- %")
    col3.metric("Calidad Aire (Actual)", f"{score:.1f}" if score is not None else "--")
    col4.metric("Estado Físico", str(air_state))

    # Componente HTML de Animación Mejorada con Engranajes Reales (Vectoriales) e inyección RGB real
    steampunk_html = f"""
    <div style="display:flex; justify-content:center; align-items:center; height:400px; background: transparent;">
        <style>
            @keyframes spin {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(360deg); }} }}
            @keyframes spin-rev {{ from {{ transform: rotate(0deg); }} to {{ transform: rotate(-360deg); }} }}
            @keyframes pulse {{ 0%, 100% {{ opacity: 0.5; transform: scale(1); }} 50% {{ opacity: 1; transform: scale(1.1); }} }}
            
            .container {{ position: relative; width: 300px; height: 300px; border: 12px solid #8b6508; border-radius: 50%; background: #2b221a; box-shadow: inset 0 0 50px #000, 0 0 20px rgba(0,0,0,0.5); overflow: hidden; }}
            
            /* Engranaje Victoriano con dientes */
            .gear {{
                position: absolute;
                fill: #d4af37;
                opacity: 0.8;
                filter: drop-shadow(2px 2px 2px #000);
            }}
            .g1 {{ width: 120px; height: 120px; top: 10px; left: 10px; animation: spin 15s linear infinite; }}
            .g2 {{ width: 80px; height: 80px; bottom: 20px; right: 20px; animation: spin-rev 10s linear infinite; }}
            .g3 {{ width: 60px; height: 60px; top: 100px; right: 10px; animation: spin 8s linear infinite; opacity: 0.5; }}
            
            .core {{
                position: absolute;
                top: 50%; left: 50%;
                transform: translate(-50%, -50%);
                width: 60px; height: 60px;
                border-radius: 50%;
                background: #444;
                border: 4px solid #8b6508;
                z-index: 10;
            }}

            /* Estados Dinámicos y Velocidades (Los colores reales se inyectan en style) */
            .state-ok .core {{ background: radial-gradient(circle, {led_color} 0%, rgba(0,0,0,0.8) 100%); box-shadow: 0 0 20px {led_color}; }}
            .state-ok .gear {{ fill: #8b6508; }}

            .state-heating .core {{ background: radial-gradient(circle, {led_color} 0%, rgba(0,0,0,0.8) 100%); animation: pulse 2s infinite ease-in-out; }}
            .state-heating .gear {{ fill: {led_color}; animation-duration: 5s; }}

            .state-bad .core {{ background: radial-gradient(circle, {led_color} 0%, rgba(0,0,0,0.8) 100%); animation: pulse 0.5s infinite; }}
            .state-bad .gear {{ fill: {led_color}; animation-duration: 2s; }}
        </style>
        
        <div class="container state-{state_class}">
            <!-- SVG de Engranaje Steampunk -->
            <svg class="gear g1" viewBox="0 0 100 100">
                <path d="M50 0 L55 10 L65 10 L70 0 L80 5 L75 15 L85 25 L95 20 L100 30 L90 35 L90 45 L100 50 L95 60 L85 55 L75 65 L80 75 L70 80 L65 70 L55 70 L50 80 L40 75 L45 65 L35 55 L25 60 L20 50 L30 45 L30 35 L20 30 L25 20 L35 25 L45 15 L40 5 Z M50 30 A20 20 0 1 0 50 70 A20 20 0 1 0 50 30 Z" />
            </svg>
            <svg class="gear g2" viewBox="0 0 100 100">
                <path d="M50 0 L55 10 L65 10 L70 0 L80 5 L75 15 L85 25 L95 20 L100 30 L90 35 L90 45 L100 50 L95 60 L85 55 L75 65 L80 75 L70 80 L65 70 L55 70 L50 80 L40 75 L45 65 L35 55 L25 60 L20 50 L30 45 L30 35 L20 30 L25 20 L35 25 L45 15 L40 5 Z M50 30 A20 20 0 1 0 50 70 A20 20 0 1 0 50 30 Z" />
            </svg>
            <svg class="gear g3" viewBox="0 0 100 100">
                <path d="M50 0 L55 10 L65 10 L70 0 L80 5 L75 15 L85 25 L95 20 L100 30 L90 35 L90 45 L100 50 L95 60 L85 55 L75 65 L80 75 L70 80 L65 70 L55 70 L50 80 L40 75 L45 65 L35 55 L25 60 L20 50 L30 45 L30 35 L20 30 L25 20 L35 25 L45 15 L40 5 Z M50 30 A20 20 0 1 0 50 70 A20 20 0 1 0 50 30 Z" />
            </svg>
            <div class="core"></div>
        </div>
    </div>
    """
    components.html(steampunk_html, height=420)
    
    if st.button("🔄 Forzar Sincronización"):
        st.rerun()


# --- VISTA HISTORIAL ---
elif page == "Historial Atmosférico":
    st.title("📚 Archivos de Bitácora Atmosférica")
    st.markdown("*Análisis profundo de los registros almacenados*")
    
    # Selector de archivo
    source = st.selectbox("Seleccionar Registro:", ["Muestras Granulares (Samples)", "Promedios por Batch (15m)"])
    file_path = SAMPLES_PATH if "Samples" in source else BATCH_PATH
    
    df = load_jsonl(file_path)
    
    if df is not None and not df.empty:
        # Intentar normalizar nombres de columnas
        df = df.rename(columns={
            "temperature_last": "Temperature", "temperature": "Temperature", "Temp": "Temperature",
            "humidity_last": "Humidity", "humidity": "Humidity", "Humidity": "Humidity",
            "air_score_last": "Air Quality", "air_score": "Air Quality", "score": "Air Quality"
        })
        # Mostrar Resumen estadístico estilo antiguo
        st.subheader("📊 Resumen de la Expedición")
        stats_col1, stats_col2, stats_col3 = st.columns(3)
        
        # Safe extraction
        max_temp = df['Temperature'].max() if 'Temperature' in df.columns else 0.0
        min_hum = df['Humidity'].min() if 'Humidity' in df.columns else 0.0
        avg_aq = df['Air Quality'].mean() if 'Air Quality' in df.columns else 0.0

        stats_col1.metric("Máx Temp", f"{max_temp:.1f} °C")
        stats_col2.metric("Mín Hum", f"{min_hum:.1f} %")
        stats_col3.metric("Calidad Promedio", f"{avg_aq:.1f}")

        # Gráficas
        st.subheader("📈 Gráficas de Evolución")
        
        # Gráfica de Temperatura y Humedad
        st.write("**Evolución Térmica y de Humedad**")
        available_cols = [c for c in ['Temperature', 'Humidity'] if c in df.columns]
        if available_cols:
            st.line_chart(df[available_cols])
        
        # Gráfica de Calidad de Aire
        st.subheader("🧪 Análisis de Correlación (IA)");
        st.write("**Estudio de Impacto Ambiental: Humedad vs Calidad**")
        
        if 'Humidity' in df.columns and 'Air Quality' in df.columns:
            # Análisis de correlación simple
            correlation = df['Humidity'].corr(df['Air Quality'])
            # Handle NaN from corr
            if pd.isna(correlation): correlation = 0.0
            
            col_ia1, col_ia2 = st.columns([2, 1])
            
            with col_ia1:
                # Gráfico de dispersión para ver la relación
                st.scatter_chart(df, x='Humidity', y='Air Quality', color="#8b6508")
            
        with col_ia2:
            st.markdown(f"""
            <div style="background-color: rgba(139, 101, 8, 0.1); border: 1px solid #8b6508; padding: 15px; border-radius: 10px;">
                <p style='color: #d4af37; font-size: 0.9em; margin:0;'>Coeficiente de Correlación:</p>
                <h2 style='margin:0;'>{correlation:.2f}</h2>
                <hr style='border-color: #8b6508;'>
                <p style='font-size: 0.85em; font-style: italic;'>
                    { "Alta relación positiva" if correlation > 0.7 else 
                      "Relación moderada" if correlation > 0.4 else 
                      "Baja correlación técnica" if correlation > -0.4 else 
                      "Relación inversa detectada" }
                </p>
                <p style='font-size: 0.8em;'>Este análisis indica cómo influye el vapor de agua en la conductividad del sensor de gas.</p>
            </div>
            """, unsafe_allow_html=True)
        
        # Visualizar tabla de datos
        with st.expander("📜 Ver Registros en Bruto"):

            st.dataframe(df.tail(100), use_container_width=True)
            
    else:
        st.info(f"📜 El archivo de bitácora `{file_path}` aún no ha sido sincronizado o está vacío.")
        st.image("https://www.publicdomainpictures.net/pictures/30000/velka/old-paper-texture-1.jpg", width=400)
