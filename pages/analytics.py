import streamlit as st
import plotly.express as px
import pandas as pd
import pydeck as pdk
import time
from data.connection import get_client_or_raise, run_query, flux_query, ConnectionNotReady
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
        <h1 style="margin: 0; font-size: 36px; text-align: center;">Análisis</h1>
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
    flux = flux_query(bucket="messages", start="-30d")

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
            st.write("Esta página contiene una variedad de información para la calidad del aire y otros parametros.")

    with st.container(key="graphs"):
        with st.container(key="graph1"):
            
            st.html(
            """
            <div style="text-align: center;"> Coordenadas con concentraciones más altas </div>
            """)


            dfchart3 = df.groupby('location')['PM2.5'].mean()

            fig3 = px.bar({'location': dfchart3.index,
            'Average PM2.5': dfchart3.values}, x="location",y="Average PM2.5")
            st.plotly_chart(fig3, use_container_width=True, theme=None, key="fig3")

        with st.container(key="graph2"):
            st.html(
            """
            <div style="text-align: center;"> Contaminación por día </div>
            """)
            
            

            dfchart4 = df.groupby('_time')['CO2'].mean()
            
            fig4 = px.line({'_time': dfchart4.index,
            'Average CO2': dfchart4.values}, x="_time",y="Average CO2")
            st.plotly_chart(fig4, use_container_width=True, theme=None, key="fig4")

    with st.container(key="graphsx"):
        with st.container(key="graphx1"):
            
            st.html(
            """
            <div style="text-align: center;"> Coordenadas con concentraciones más altas </div>
            """)

           
            dfchart5 = df.groupby('location')['PM2.5'].mean()

            fig5 = px.bar({'location': dfchart5.index,
            'Average PM2.5': dfchart5.values}, x="location",y="Average PM2.5")
            st.plotly_chart(fig5, use_container_width=True, theme=None, key="fig5")

        with st.container(key="graphx2"):
            st.html(
            """
            <div style="text-align: center;"> Contaminación por día </div>
            """)
            
            dfchart6 = df.groupby('_time')['CO2'].mean()
            
            fig6 = px.line({'_time': dfchart6.index,
            'Average CO2': dfchart6.values}, x="_time",y="Average CO2")
            st.plotly_chart(fig6, use_container_width=True, theme=None, key="fig6")

if __name__ == "__main__" or st._is_running_with_streamlit:

    main()
