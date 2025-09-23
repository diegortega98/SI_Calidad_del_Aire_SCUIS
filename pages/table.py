import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from data.connection import get_client_or_raise, run_query, flux_query, ConnectionNotReady
from influxdb_client import InfluxDBClient

# Cachea el cliente
@st.cache_resource(show_time=True, show_spinner=False)
def get_cached_client() -> InfluxDBClient:
    with st.spinner("Estableciendo conexión con SmartCampus UIS..."):
        client = get_client_or_raise()
    return client

# Cachea datos (dependen de parámetros; pon TTLs cortos)
@st.cache_data(ttl=10, show_spinner=False)
def cached_query(flux: str):
    client = get_cached_client()
    return run_query(client, flux)

def format_dataframe_for_display(df, selected_parameters):
    """Formatear el dataframe para mostrar solo las columnas seleccionadas con nombres amigables"""
    if df.empty:
        return df
    
    # Crear una copia del dataframe
    display_df = df.copy()
    
    # Columnas base que siempre se muestran
    base_columns = []
    if '_time' in display_df.columns:
        display_df['Fecha y Hora'] = display_df['_time'].dt.strftime('%Y-%m-%d %H:%M:%S')
        base_columns.append('Fecha y Hora')
    
    if 'header_deviceId' in display_df.columns:
        display_df['ID Dispositivo'] = display_df['header_deviceId']
        base_columns.append('ID Dispositivo')
    
    if 'route_int' in display_df.columns:
        display_df['Ruta'] = display_df['route_int'].fillna('N/A').astype(str)
        base_columns.append('Ruta')
    
    if 'header_latitude' in display_df.columns and 'header_longitude' in display_df.columns:
        display_df['Latitud'] = display_df['header_latitude'].round(6)
        display_df['Longitud'] = display_df['header_longitude'].round(6)
        base_columns.extend(['Latitud', 'Longitud'])
    
    # Mapeo de parámetros a nombres de columnas
    param_mapping = {
        'CO2': ('metrics_0_fields_CO2', 'CO₂ (ppm)'),
        'PM2.5': ('metrics_0_fields_PM2.5', 'PM2.5 (μg/m³)'),
        'Temp': ('metrics_0_fields_Temperature', 'Temperatura (°C)')
    }
    
    # Agregar columnas de parámetros seleccionados
    selected_columns = base_columns.copy()
    
    for param_key, is_selected in selected_parameters.items():
        if is_selected and param_key in param_mapping:
            original_col, display_name = param_mapping[param_key]
            if original_col in display_df.columns:
                display_df[display_name] = display_df[original_col].round(2)
                selected_columns.append(display_name)
    
    # Retornar solo las columnas seleccionadas
    return display_df[selected_columns]

def get_air_quality_category(pm25_value):
    """Obtener categoría de calidad del aire basada en PM2.5"""
    if pd.isna(pm25_value):
        return "No disponible"
    
    if pm25_value <= 12.0:
        return "Buena"
    elif pm25_value <= 35.4:
        return "Moderada"
    elif pm25_value <= 55.4:
        return "Dañina para sensibles"
    elif pm25_value <= 150.4:
        return "Dañina"
    elif pm25_value <= 250.4:
        return "Muy dañina"
    else:
        return "Peligrosa"

def create_summary_cards(df):
    """Crear tarjetas de resumen con estadísticas clave"""
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        total_records = len(df)
        st.metric(
            label="Total de Registros",
            value=f"{total_records:,}"
        )
    
    with col2:
        if 'route_int' in df.columns:
            unique_routes = df['route_int'].nunique()
            st.metric(
                label="Rutas Únicas",
                value=f"{unique_routes}"
            )
    
    with col3:
        if 'header_deviceId' in df.columns:
            unique_devices = df['header_deviceId'].nunique()
            st.metric(
                label="Dispositivos",
                value=f"{unique_devices}"
            )
    
    with col4:
        if '_time' in df.columns:
            time_span = df['_time'].max() - df['_time'].min()
            days = time_span.days
            st.metric(
                label="Período (días)",
                value=f"{days}"
            )

def main():
    # Page banner
    st.html("""
    <div class="hero-section">
        <h1 style="margin: 0; font-size: 36px;">Datos de Calidad del Aire</h1>
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
    flux = flux_query("messages", start="-30d")

    with st.spinner("Consultando datos..."):
        try:
            df = cached_query(flux)
        except Exception as e:
            st.warning(f"No fue posible obtener datos. Revisa la query Flux. Detalle: {e}")
        else:
            # Obtener ultima conexión
            try:
                last_time = df['_time'].max()
                last_time_str = last_time.strftime("%Y-%m-%d %H:%M:%S")
                st.sidebar.markdown(f"Últimos datos recibidos: {last_time_str}", width="stretch")
            except:
                st.info("No fue posible obtener la última conexión de datos.")   

    if 'df' in locals() and not df.empty:
        # Convert routes to integers for better handling
            st.write("Esta página muestra una tabla con los datos de calidad del aire en el transporte público del AMB.")

            st.dataframe(
                df,
                key="data",
                height=700,
                on_select="rerun",
            )

if __name__ == "__main__" or st._is_running_with_streamlit:
    main()
