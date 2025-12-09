import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
from data.connection import get_client_or_raise, run_query, flux_query, ConnectionNotReady
from influxdb_client import InfluxDBClient
from utils.timezone_utils import format_colombia_time

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
        display_df['Fecha y Hora'] = display_df['_time'].apply(format_colombia_time)
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
        <h1 style="padding: 0px 0px 0px 0px; font-size: clamp(1.400rem, 3.9vw, 3.0625rem); margin:10px 0px 0px 40px; text-align: center;">Tabla de datos</h1>
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
    flux = flux_query("messages", start="-100d")

    with st.spinner("Consultando datos..."):
        try:
            df = cached_query(flux)
        except Exception as e:
            st.warning(f"No fue posible obtener datos. Revisa la query Flux. Detalle: {e}")
        else:
            # Obtener ultima conexión
            try:
                last_time = df['_time'].max()
                last_time_str = format_colombia_time(last_time)
                st.caption(f"Últimos datos recibidos: {last_time_str}", width="stretch")
            except:
                st.info("No fue posible obtener la última conexión de datos.")
            
            st.sidebar.markdown("### Filtros de la tabla")
            
            # Route filter
            if 'location' in df.columns:
                available_routes = sorted(df['location'].dropna().unique())
                selected_routes = st.sidebar.multiselect(
                    "Rutas seleccionadas:",
                    options=available_routes,
                    default=available_routes,
                    key="route_filter"
                )
            else:
                selected_routes = []
            
            # Date filter
            if '_time' in df.columns:
                # Get available dates
                df['Fecha'] = df['_time'].dt.date
                available_dates = sorted(df['Fecha'].unique())
                
                if available_dates:
                    min_date = min(available_dates)
                    max_date = max(available_dates)
                    
                    # Date range selector
                    selected_date_range = st.sidebar.date_input(
                        "Rango de fechas:",
                        value=(min_date, max_date),
                        min_value=min_date,
                        max_value=max_date,
                        key="date_filter"
                    )
                    
                    # Ensure we have a range
                    if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
                        start_date, end_date = selected_date_range
                    else:
                        start_date = end_date = selected_date_range if hasattr(selected_date_range, 'year') else min_date
                else:
                    start_date = end_date = None 

    with st.container(key="table"):  

        if 'df' in locals() and not df.empty:
            # Apply filters
            filtered_df = df.copy()
            
            # Apply route filter
            if selected_routes and 'location' in filtered_df.columns:
                filtered_df = filtered_df[filtered_df['location'].isin(selected_routes)]
            
            # Apply date filter
            if start_date and end_date and '_time' in filtered_df.columns:
                filtered_df = filtered_df[
                    (filtered_df['_time'].dt.date >= start_date) & 
                    (filtered_df['_time'].dt.date <= end_date)
                ]
            
            # Show filter summary
            col1, col2, col3 = st.columns(3, gap=None)
            with col1:
                st.html("""<div class="graphtitle"> Total de registros </div>""")
                st.metric(label="Total de Registros", label_visibility="collapsed", value=f"{len(df):,}")
            with col2:
                st.html("""<div class="graphtitle"> Registros filtrados </div>""")
                st.metric(label="Registros Filtrados", label_visibility="collapsed", value=f"{len(filtered_df):,}")
            with col3:
                st.html("""<div class="graphtitle"> Porcentaje mostrado </div>""")
                if len(df) > 0:
                    percentage = (len(filtered_df) / len(df)) * 100
                    st.metric(label="Porcentaje Mostrado", label_visibility="collapsed", value=f"{percentage:.1f}%")
            
            # Check if filtered data is empty
            if filtered_df.empty:
                st.warning("No hay datos que coincidan con los filtros seleccionados.")
                return
            
            # Filter and clean the dataframe
            display_df = filtered_df.copy()
            
            # Remove complementary columns like result, table number, etc.
            columns_to_remove = [
                'result', 'table', '_start', '_stop', '_measurement', 
                'header_result', 'table_number', '_field', '_value'
            ]
            
            # Remove unwanted columns if they exist
            for col in columns_to_remove:
                if col in display_df.columns:
                    display_df = display_df.drop(columns=[col])
            
            # Format time in UTC format - separate date and time
            if '_time' in display_df.columns:
                # Separate date and time into different columns
                display_df['Hora'] = display_df['_time'].dt.time
                display_df = display_df.drop(columns=['_time'])
            
            st.dataframe(
                display_df,
                key="data",
                height=600,
                on_select="rerun",
            )

    st.html(
    """
    <div class="footer">Diego Andrés Ortega Gelvez y Jose Fredy Navarro Motta<br>SISTEMA DE INFORMACIÓN IOT PARA ANÁLISIS DE CALIDAD DEL AIRE</div>
    """) 
        

if __name__ == "__main__" or st._is_running_with_streamlit:
    main()
