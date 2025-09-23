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
    fields = ["Lan", "Lon", "CO2", "PM2.5", "Route", "Temperature"]
    flux = flux_select(fields, start="-30d")

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
        if 'metrics_0_fields_Route' in df.columns:
            df['route_int'] = pd.to_numeric(df['metrics_0_fields_Route'], errors='coerce')
        
        # Create a unique container for filters
        filter_container = st.container(border=True)
        with filter_container:
            
            # Define available parameters (used across columns)
            available_parameters = {
                "CO2": {
                    "column": "metrics_0_fields_CO2",
                    "label": "CO₂",
                    "unit": "ppm",
                    "default": True
                },
                "PM2.5": {
                    "column": "metrics_0_fields_PM2.5", 
                    "label": "PM2.5",
                    "unit": "μg/m³",
                    "default": True
                },
                "Temp": {
                    "column": "metrics_0_fields_Temperature",
                    "label": "Temperatura",
                    "unit": "°C",
                    "default": True
            }}
            
            # Create filter columns
            col1, col2, col3 = st.columns(3)
            
            with col1:
                # Date filter
                if '_time' in df.columns:
                    min_date = df['_time'].min().date()
                    max_date = df['_time'].max().date()
                    
                    date_range = st.date_input(
                        "Seleccionar el rango de fechas:",
                        value=(min_date, max_date),
                        min_value=min_date,
                        max_value=max_date,
                        key="table_date_filter"
                    )
                else:
                    st.info("No hay datos de fecha disponibles")
            
            with col2:
                # Route filter
                if 'route_int' in df.columns:
                    unique_routes = df['route_int'].dropna().astype(int).unique()
                    selected_routes = st.multiselect(
                        "Seleccionar las rutas:",
                        options=sorted(unique_routes),
                        default=sorted(unique_routes),
                        key="table_route_filter"
                    )
                else:
                    st.info("No hay datos de ruta disponibles")
            
            with col3:
                # Parameters filter - Multiselect
                available_param_options = []
                default_selected = []
                
                for param_key, param_info in available_parameters.items():
                    if param_info["column"] in df.columns:
                        available_param_options.append(param_key)
                        if param_info["default"]:
                            default_selected.append(param_key)
                
                selected_param_keys = st.multiselect(
                    "Columnas a Mostrar:",
                    options=available_param_options,
                    default=default_selected,
                    format_func=lambda x: available_parameters[x]["label"],
                    key="table_parameters_filter",
                    help="Selecciona las columnas de datos que deseas ver en la tabla"
                )
                
                # Convert to the expected format for compatibility
                selected_parameters = {}
                for param_key in available_parameters.keys():
                    selected_parameters[param_key] = param_key in selected_param_keys
        
        # Apply filters and show table
        with st.container():
            # Apply filters to dataframe
            filtered_df = df.copy()
            
            # Apply date filter
            if '_time' in df.columns and len(date_range) == 2:
                start_date, end_date = date_range
                filtered_df = filtered_df[
                    (filtered_df['_time'].dt.date >= start_date) & 
                    (filtered_df['_time'].dt.date <= end_date)
                ]
            
            # Apply route filter
            if 'route_int' in df.columns and selected_routes:
                filtered_df = filtered_df[filtered_df['route_int'].isin(selected_routes)]
            
            # Show filtered results
            if not filtered_df.empty:
                st.sidebar.markdown(f"Mostrando {len(filtered_df):,} registros filtrados de {len(df):,} totales")
                
                # Summary cards
                create_summary_cards(filtered_df)
                
                # Format dataframe for display
                display_df = format_dataframe_for_display(filtered_df, selected_parameters)
                
                # Add air quality category if PM2.5 is selected
                if selected_parameters.get('PM2.5', False) and 'metrics_0_fields_PM2.5' in filtered_df.columns:
                    display_df['Calidad del Aire'] = filtered_df['metrics_0_fields_PM2.5'].apply(get_air_quality_category)
                
                # Table controls
                col_controls1, col_controls2, col_controls3 = st.columns([2, 1, 1])
                
                with col_controls1:
                    st.subheader("Tabla de Datos")
                
                with col_controls2:
                    # Records per page
                    records_per_page = st.selectbox(
                        "Registros por página:",
                        options=[25, 50, 100, 200, 500],
                        index=2,
                        key="records_per_page"
                    )
                
                with col_controls3:
                    # Download button
                    csv_data = display_df.to_csv(index=False)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"datos_calidad_aire_{timestamp}.csv"
                    
                    st.download_button(
                        label="Descargar CSV",
                        data=csv_data,
                        file_name=filename,
                        mime="text/csv",
                        help="Descargar los datos filtrados en formato CSV"
                    )
                
                # Pagination
                total_records = len(display_df)
                total_pages = max(1, (total_records - 1) // records_per_page + 1)
                
                if total_pages > 1:
                    col_page1, col_page2, col_page3 = st.columns([1, 2, 1])
                    
                    with col_page2:
                        page_number = st.number_input(
                            f"Página (1-{total_pages}):",
                            min_value=1,
                            max_value=total_pages,
                            value=1,
                            key="page_number"
                        )
                    
                    # Calculate start and end indices
                    start_idx = (page_number - 1) * records_per_page
                    end_idx = min(start_idx + records_per_page, total_records)
                    
                    # Show page info
                    st.info(f"Mostrando registros {start_idx + 1} a {end_idx} de {total_records} total")
                    
                    # Display paginated data
                    paginated_df = display_df.iloc[start_idx:end_idx]
                else:
                    paginated_df = display_df
                
                # Display the table
                st.dataframe(
                    paginated_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Fecha y Hora": st.column_config.DatetimeColumn(
                            "Fecha y Hora",
                            help="Fecha y hora del registro",
                            format="DD/MM/YYYY HH:mm:ss"
                        ),
                        "CO₂ (ppm)": st.column_config.NumberColumn(
                            "CO₂ (ppm)",
                            help="Concentración de CO₂ en partes por millón",
                            format="%.2f"
                        ),
                        "PM2.5 (μg/m³)": st.column_config.NumberColumn(
                            "PM2.5 (μg/m³)",
                            help="Concentración de PM2.5 en microgramos por metro cúbico",
                            format="%.2f"
                        ),
                        "Temperatura (°C)": st.column_config.NumberColumn(
                            "Temperatura (°C)",
                            help="Temperatura en grados Celsius",
                            format="%.2f"
                        ),
                        "Latitud": st.column_config.NumberColumn(
                            "Latitud",
                            help="Coordenada de latitud",
                            format="%.6f"
                        ),
                        "Longitud": st.column_config.NumberColumn(
                            "Longitud",
                            help="Coordenada de longitud",
                            format="%.6f"
                        ),
                        "Calidad del Aire": st.column_config.TextColumn(
                            "Calidad del Aire",
                            help="Categoría de calidad del aire basada en PM2.5"
                        )
                    }
                )
                
                # Additional information
                if total_pages > 1:
                    st.caption(f"Página {page_number} de {total_pages} • Total: {total_records:,} registros")
                else:
                    st.caption(f"Total: {total_records:,} registros")
                    
            else:
                st.warning("No hay datos que coincidan con los filtros seleccionados.")


if __name__ == "__main__" or st._is_running_with_streamlit:
    main()
