import streamlit as st
import pandas as pd
import pydeck as pdk
import time
from data.connection import get_client_or_raise, run_query, flux_select, ConnectionNotReady
from influxdb_client import InfluxDBClient

# Cachea el cliente .
@st.cache_resource(show_time=True,show_spinner=False)
def get_cached_client() -> InfluxDBClient:
    with st.spinner("Estableciendo conexión con SmartCampus UIS..."):
        client = get_client_or_raise()
    return client

# Cachea datos (dependen de parámetros; pon TTLs cortos).
@st.cache_data(ttl=10, show_spinner=False)
def cached_query(flux: str):
    client = get_cached_client()
    return run_query(client, flux)

def main():

    #Page banner
    st.html("""

    <div class="hero-section">
        <h1 style="margin: 0; font-size: 36px; text-align: center;">Datos</h1>
    </h2>
    </div>
    """)

    try:
        client = get_cached_client()
    except ConnectionNotReady as e:
        st.error(
            "No se pudo establecer la conexión. \n"
            "Verifica que SmartCampus UIS esté disponible.\n\n"
            f"Detalle: {e}"
        )
        st.stop()
    except Exception as e:
        st.error(f"Error inesperado estableciendo conexión: {e}")
        st.stop()

    # Query
    fields = ["header_latitude", "header_longitude", "metrics_0_fields_CO2", "metrics_0_fields_PM2.5", "metrics_0_fields_Route","metrics_0_fields_Temperature", "header_deviceId"]
    flux = flux_select(fields, start="-30d")

    with st.spinner("Consultando datos..."):
        try:
            df = cached_query(flux)
        except Exception as e:
            st.warning(f"No fue posible obtener datos. Revisa la query Flux. Detalle: {e}")
        else:
            #Obtener ultima conexión
            try:
                last_time = df['_time'].max()
                last_time_str = last_time.strftime("%Y-%m-%d %H:%M:%S")
                st.sidebar.markdown(f"Últimos datos recibidos: {last_time_str}",width="stretch")
            except:
                st.info("No fue posible obtener la última conexión de datos.")   
    
    

    if 'df' in locals() and not df.empty:
        # Convert routes to integers for better handling
            st.write("Esta página muestra una tabla con los datos de calidad del aire en el transporte público del AMB.")

            event = st.dataframe(
                df,
                key="data",
                height=600,
                on_select="rerun",
            )
            event.selection


if __name__ == "__main__" or st._is_running_with_streamlit:

    main()