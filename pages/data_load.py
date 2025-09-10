import time
import streamlit as st
from contextlib import suppress
from influxdb_client import InfluxDBClient

# ---------- Configuración ----------
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "YOUR_TOKEN"
INFLUX_ORG = "YOUR_ORG"
BUCKET = "air_quality_raw"

# ---------- Utilidades ----------
def retry(op, attempts=3, delay=1.0, factor=2.0):
    last = None
    for i in range(attempts):
        with suppress(Exception):
            return op()
        last = f"Intento {i+1} falló"
        time.sleep(delay)
        delay *= factor
    raise RuntimeError(last or "Error")

def check_influx():
    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG, timeout=3000) as c:
        return c.health().status == "pass"

@st.cache_data(ttl=180)
def load_initial_data():
    # Aquí harías tu query de prueba, ej. últimos 10 datos
    with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as c:
        query = f'''
        from(bucket:"{BUCKET}")
          |> range(start: -1h)
          |> limit(n:10)
        '''
        tables = c.query_api().query(query)
        return len(tables)

# ---------- Pantalla de salud / carga ----------
st.title("Inicializando datos…")

if not st.session_state.get("ready", False):
    with st.status("Preparando el entorno…", expanded=True) as status:
        try:
            st.write("🔌 Chequeando conexión a InfluxDB…")
            ok_influx = retry(check_influx, attempts=3, delay=0.8)
            st.write("✅ InfluxDB OK" if ok_influx else "❌ InfluxDB falló")

            st.write("📦 Precargando datos…")
            count = retry(load_initial_data, attempts=2, delay=0.8)
            st.write(f"✅ Datos precargados ({count} filas)")

            st.session_state["ready"] = True
            status.update(label="Listo ✔", state="complete")
            st.switch_page("pages/map.py")

        except Exception as e:
            status.update(label="Problemas de conexión", state="error")
            st.error(f"Hubo un error al preparar la app: {e}")
            if st.button("🔁 Reintentar"):
                st.rerun()
else:
    st.switch_page("pages/map.py")