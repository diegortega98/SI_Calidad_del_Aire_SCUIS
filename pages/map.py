import streamlit as st
import pandas as pd
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

@st.fragment()
def plot_map(df):
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

    # Define a HexagonLayer to display on a map
    layer = pdk.Layer(
        "HexagonLayer",
        df,
        get_position=["header_longitude", "header_latitude"],
        get_weight="pm25_size",
        radius=25,
        elevation_scale=10,
        elevation_range=[0, 100],
        pickable=True,
        extruded=True,
        coverage=1,
        auto_highlight=True,
        get_fill_color="pm25_color",
    )

    # Set the viewport location
    view_state = pdk.ViewState(
        latitude=df['header_latitude'].mean(),
        longitude=df['header_longitude'].mean(),
        zoom=14,
        bearing=0,
        pitch=20
    )

    # Render
    r = pdk.Deck(
        layers=[layer], 
        map_style='road',
        initial_view_state=view_state, 
        tooltip={
            "text":"{co2_value}",
            "style": {
                "backgroundColor": "rgba(0, 0, 0, 0.5)",
                "color": "white",
                "borderRadius": "10px",
                "backdrop-filter": "blur(15.4px)",
                "-webkit-backdrop-filter": "blur(15.4px)"
            }
        }
    )
    
    # Mostrar en Streamlit
    st.pydeck_chart(r)


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

            except:
                st.info("No fue posible obtener la última conexión de datos.")   
    
    st.sidebar.markdown(f"Últimos datos recibidos: {last_time_str}",width="stretch")

    if 'df' in locals() and not df.empty:
        # Convert routes to integers for better handling
        if 'metrics_0_fields_Route' in df.columns:
            df['route_int'] = pd.to_numeric(df['metrics_0_fields_Route'], errors='coerce')
        
        
        # Create a unique container for filters
        filter_container = st.container(border=True)
        with filter_container:
            
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
                # Tag/Device filter
                if 'header_deviceId' in df.columns:
                    unique_devices = df['header_deviceId'].dropna().unique()
                    selected_devices = st.multiselect(
                        "Selecciona los dispositivos:",
                        options=sorted(unique_devices),
                        default=sorted(unique_devices),
                        key="device_filter"
                    )
                else:
                    st.info("No hay datos de dispositivo disponibles")
        
       
        
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
            
            # Apply device filter
            if 'header_deviceId' in df.columns and selected_devices:
                filtered_df = filtered_df[filtered_df['header_deviceId'].isin(selected_devices)]
            
            # Show filtered results
            if not filtered_df.empty:
                st.sidebar.markdown(f"Mostrando {len(filtered_df):,} registros filtrados de {len(df):,} totales")
                plot_map(filtered_df)
            else:
                st.warning("No hay datos que coincidan con los filtros seleccionados.")


if __name__ == "__main__" or st._is_running_with_streamlit:

    main()