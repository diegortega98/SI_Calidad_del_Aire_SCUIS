import streamlit as st
import pandas as pd
import time
from data.connection import get_client_or_raise, run_query, flux_select, ConnectionNotReady
from influxdb_client import InfluxDBClient
import pydeck as pdk
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

@st.fragment()
def plot_map(df, selected_parameters, auto_refresh=False):
    import pandas as pd
    import pydeck as pdk

    # Filtrar datos inválidos
    df = df.dropna(subset=['header_latitude', 'header_longitude'])


    if df.empty:
        st.warning("No hay datos válidos para mostrar en el mapa.")
        return

    # Crear columna layer como la media de los valores de contaminación
    pollution_columns = ['metrics_0_fields_CO2', 'metrics_0_fields_PM2.5']
    
    # Verificar que las columnas existen y calcular la media
    available_columns = [col for col in pollution_columns if col in df.columns]
    
    if available_columns:
        # Calcular la media de las columnas de contaminación disponibles
        df = df.copy()
        df['layer'] = df[available_columns].mean(axis=1, skipna=True)
        
        # Usar PM2.5 para el tamaño si está disponible
        if 'metrics_0_fields_PM2.5' in df.columns:
            df['pm25_size'] = df['metrics_0_fields_PM2.5']
            
            # Umbrales de PM2.5 según EPA AQI
            PM25_THRESHOLDS = [
                (0.0, 12.0, 0, 50, "Buena", "#00e400"),
                (12.1, 35.4, 51, 100, "Moderada", "#ffff00"),
                (35.5, 55.4, 101, 150, "Dañina para sensibles", "#ff7e00"),
                (55.5, 150.4, 151, 200, "Dañina", "#ff0000"),
                (150.5, 250.4, 201, 300, "Muy dañina", "#8f3f97"),
                (250.5, 500.4, 301, 500, "Peligrosa", "#7e0023")
            ]
            
            def get_pm25_color_and_category(pm25_value):
                for low, high, aqi_low, aqi_high, category, color_hex in PM25_THRESHOLDS:
                    if low <= pm25_value <= high:
                        # Convertir hex a RGB con transparencia
                        r = int(color_hex[1:3], 16)
                        g = int(color_hex[3:5], 16)
                        b = int(color_hex[5:7], 16)
                        return [r, g, b, 180], category
                # Si está fuera de rango, usar el último threshold
                r = int(PM25_THRESHOLDS[-1][5][1:3], 16)
                g = int(PM25_THRESHOLDS[-1][5][3:5], 16)
                b = int(PM25_THRESHOLDS[-1][5][5:7], 16)
                return [r, g, b, 180], PM25_THRESHOLDS[-1][4]
            
            # Aplicar colores y categorías
            df[['pm25_color', 'pm25_category']] = df['metrics_0_fields_PM2.5'].apply(
                lambda x: pd.Series(get_pm25_color_and_category(x))
            )
            
            # Crear columnas para el tooltip
            df['co2_value'] = df.get('metrics_0_fields_CO2', 0).round(1)
            df['pm25_value'] = df['metrics_0_fields_PM2.5'].round(1)
        else:
            df['pm25_size'] = df['layer']  # Fallback a la media general
            df['pm25_color'] = [[255, 255, 0, 180]] * len(df)  # Color amarillo por defecto
            df['pm25_category'] = ['No disponible'] * len(df)  # Categoría por defecto
            df['co2_value'] = df.get('metrics_0_fields_CO2', 0).round(1)
            df['pm25_value'] = [0] * len(df)
    else:
        # Valores por defecto si no hay columnas de contaminación
        df['layer'] = 100
        df['pm25_size'] = 100
        df['pm25_color'] = [[255, 255, 0, 180]] * len(df)  # Color amarillo por defecto
        df['pm25_category'] = ['No disponible'] * len(df)  # Categoría por defecto
        df['co2_value'] = [0] * len(df)
        df['pm25_value'] = [0] * len(df)

    # Calculate contamination mean for height
    # Create contamination_mean column combining CO2 and PM2.5
    if 'metrics_0_fields_CO2' in df.columns and 'metrics_0_fields_PM2.5' in df.columns:
        # Normalize values to similar scales for meaningful average
        # CO2 typically ranges 400-2000 ppm, PM2.5 ranges 0-500 μg/m³
        co2_normalized = df['metrics_0_fields_CO2'] / 10  # Scale down CO2
        pm25_normalized = df['metrics_0_fields_PM2.5']    # Keep PM2.5 as is
        df['contamination_mean'] = (co2_normalized + pm25_normalized) / 2
    elif 'metrics_0_fields_PM2.5' in df.columns:
        df['contamination_mean'] = df['metrics_0_fields_PM2.5']
    elif 'metrics_0_fields_CO2' in df.columns:
        df['contamination_mean'] = df['metrics_0_fields_CO2'] / 10
    else:
        df['contamination_mean'] = 50  # Default value

    # Create paths data if there are 2 or more records
    paths_data = []
    if len(df) >= 2:
        # Sort by time to create logical path sequence
        if '_time' in df.columns:
            df_sorted = df.sort_values('_time')
        else:
            df_sorted = df.copy()
        
        # Create paths between consecutive points
        for i in range(len(df_sorted) - 1):
            current_point = df_sorted.iloc[i]
            next_point = df_sorted.iloc[i + 1]
            
            # Get PM2.5 color for the path (using current point's color)
            if 'pm25_color' in df.columns:
                color = current_point['pm25_color']
                # Ensure color is in the right format [R, G, B, A]
                if isinstance(color, list) and len(color) >= 3:
                    path_color = [color[0], color[1], color[2], 200]
                else:
                    path_color = [0, 228, 0, 200]  # Default green
            else:
                path_color = [0, 228, 0, 200]  # Default green
            
            path = {
                'start_lon': current_point['header_longitude'],
                'start_lat': current_point['header_latitude'],
                'end_lon': next_point['header_longitude'],
                'end_lat': next_point['header_latitude'],
                'R': path_color[0],
                'G': path_color[1],
                'B': path_color[2],
                'pm25_category': current_point.get('pm25_category', 'No disponible'),
                'co2_value': current_point.get('co2_value', 0),
                'pm25_value': current_point.get('pm25_value', 0),
                'timestamp': current_point.get('_time', '').strftime('%Y-%m-%d %H:%M:%S') if pd.notna(current_point.get('_time', '')) else 'No disponible'
            }
            paths_data.append(path)
    
    # Convert to DataFrame
    if paths_data:
        paths_df = pd.DataFrame(paths_data)
        
        # Define a LineLayer to display paths on the map
        line_layer = pdk.Layer(
            'LineLayer',
            data=paths_df,
            get_source_position='[start_lon, start_lat]',
            get_target_position='[end_lon, end_lat]',
            get_color='[R, G, B, 200]',
            get_width=10,
            highlight_color=[0, 0, 255],
            picking_radius=10,
            auto_highlight=True,
            pickable=True,
        )
        
        layers = [line_layer]
    else:
        # If no paths can be created, show a message
        st.info("Se necesitan al menos 2 puntos de datos para mostrar rutas.")
        layers = []

    # Set the viewport location
    view_state = pdk.ViewState(
        latitude=df['header_latitude'].mean(),
        longitude=df['header_longitude'].mean(),
        zoom=14,
        bearing=0,
        pitch=45
    )

    # Render with LineLayer
    r = pdk.Deck(
        layers=layers, 
        map_style='road',
        initial_view_state=view_state, 
        tooltip={
            "html": "<b>Ruta de Contaminación</b><br/><b>Tiempo:</b> {timestamp}<br/><b>CO₂:</b> {co2_value} ppm<br/><b>PM2.5:</b> {pm25_value} μg/m³<br/><b>Calidad:</b> {pm25_category}",
            "style": {
                "backgroundColor": "rgba(0, 0, 0, 0.8)",
                "color": "white",
                "borderRadius": "10px",
                "backdrop-filter": "blur(15.4px)",
                "-webkit-backdrop-filter": "blur(15.4px)",
                "padding": "10px",
                "fontSize": "12px"
            }
        }
    )
    
    # Mostrar en Streamlit
    st.pydeck_chart(r)


@st.fragment(run_every=5)
def auto_refresh_map(date_range, selected_routes, display_columns):
    """Fragment that runs every 5 seconds when auto-refresh is enabled"""
    import pandas as pd
    
    # Re-query fresh data
    fields = ["header_latitude", "header_longitude", "metrics_0_fields_CO2", "metrics_0_fields_PM2.5", "metrics_0_fields_Route", "header_deviceId"]
    flux = flux_select(fields, start="-30d")
    
    try:
        client = get_cached_client()
        # Clear cache to get fresh data
        st.cache_data.clear()
        fresh_df = cached_query(flux)
        
        if not fresh_df.empty:
            # Convert routes to integers for better handling
            if 'metrics_0_fields_Route' in fresh_df.columns:
                fresh_df['route_int'] = pd.to_numeric(fresh_df['metrics_0_fields_Route'], errors='coerce')
            
            # Apply the same filters as main app
            filtered_df = fresh_df.copy()
            
            # Apply date filter
            if '_time' in fresh_df.columns and len(date_range) == 2:
                start_date, end_date = date_range
                filtered_df = filtered_df[
                    (filtered_df['_time'].dt.date >= start_date) & 
                    (filtered_df['_time'].dt.date <= end_date)
                ]
            
            # Apply route filter
            if 'route_int' in fresh_df.columns and selected_routes:
                filtered_df = filtered_df[filtered_df['route_int'].isin(selected_routes)]
            
            if not filtered_df.empty:
                # Show refresh indicator
                current_time = pd.Timestamp.now().strftime("%H:%M:%S")
                st.caption(f"Última actualización: {current_time}")
                
                # Plot the refreshed map
                plot_map(filtered_df, display_columns, auto_refresh=True)
            else:
                st.warning("No hay datos que coincidan con los filtros para la actualización automática.")
        else:
            st.warning("No hay datos disponibles para la actualización automática.")
        
    except Exception as e:
        st.error(f"Error al actualizar mapa: {e}")



    
    
    # Mostrar en Streamlit
    


def main():

    #Page banner
    st.html("""

    <div class="hero-section">
        <h1 style="margin: 0; font-size: 36px;">Mapa de rutas de transporte público</h1>
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
    fields = ["header_latitude", "header_longitude", "metrics_0_fields_CO2", "metrics_0_fields_PM2.5", "metrics_0_fields_Route", "header_deviceId"]
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
                    "default": False
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
                        key="date_filter"
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
                        key="route_filter"
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
                    "Parámetros a Mostrar:",
                    options=available_param_options,
                    default=default_selected,
                    format_func=lambda x: available_parameters[x]["label"],
                    key="parameters_filter",
                    help="Selecciona los parámetros que deseas visualizar en el mapa"
                )
                
                # Convert to the expected format for compatibility
                selected_parameters = {}
                for param_key in available_parameters.keys():
                    selected_parameters[param_key] = param_key in selected_param_keys
            
            # Auto-refresh toggle - in a separate row
            st.markdown("---")
            col_refresh = st.columns([1, 3])[0]  # Use only first column for compact layout
            with col_refresh:
                auto_refresh_enabled = st.toggle(
                    "Actualizar en tiempo real (5s)",
                    value=False,
                    key="map_auto_refresh",
                    
                )
        
       
        
        # Apply filters and show filtered map
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
            
            # Filter data based on selected parameters (keep all data but note selection for display)
            # Parameters selection affects tooltip and display, not data filtering
            display_columns = []
            for param_key, is_selected in selected_parameters.items():
                if is_selected and param_key in available_parameters:
                    column_name = available_parameters[param_key]["column"]
                    if column_name in filtered_df.columns:
                        display_columns.append(column_name)
            
            # Show filtered results
            if not filtered_df.empty:
                st.sidebar.markdown(f"Mostrando {len(filtered_df):,} registros filtrados de {len(df):,} totales")

                # Handle auto-refresh mode
                if auto_refresh_enabled:
                    # Use the auto-refresh fragment
                    auto_refresh_map(date_range, selected_routes, display_columns)
                else:
                    # Use the normal static map
                    plot_map(filtered_df, display_columns, auto_refresh=False)
            else:
                st.warning("No hay datos que coincidan con los filtros seleccionados.")


if __name__ == "__main__" or st._is_running_with_streamlit:

    main()