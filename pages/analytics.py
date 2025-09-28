import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import pydeck as pdk
import numpy as np
import time
from data.connection import get_client_or_raise, run_query, flux_query, ConnectionNotReady
from influxdb_client import InfluxDBClient
from utils.timezone_utils import format_colombia_time

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
def plot_map2(df, selected_parameters, selected_aqi_categories=None, auto_refresh=False):
    import numpy as np
    # Definir constantes para las columnas de datos ------------------

    PM25_COLUMN = 'PM2.5'
    CO2_COLUMN = 'CO2'
    TEMP_COLUMN = 'Temperature'

    PM25_THRESHOLDS = [
                    (0.0, 12.0, 0, 50, "Buena", "#00e400"),
                    (12.1, 35.4, 51, 100, "Moderada", "#ffff00"),
                    (35.5, 55.4, 101, 150, "Dañina para sensibles", "#ff7e00"),
                    (55.5, 150.4, 151, 200, "Dañina", "#ff0000"),
                    (150.5, 250.4, 201, 300, "Muy dañina", "#8f3f97"),
                    (250.5, 500.4, 301, 500, "Peligrosa", "#7e0023")
                ]
    
    # Functions ------------------------------------------------
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

    def build_paths(df: pd.DataFrame, selected_aqi_categories=None) -> list[dict]:
        
        paths_data = []
        if len(df) < 2:
            return paths_data

        def _build_for_subset(sub: pd.DataFrame) -> list[dict]:
            sub = sub.sort_values("_time") if "_time" in sub.columns else sub.copy()
            local_paths = []
            for i in range(len(sub) - 1):
                current_point = sub.iloc[i]
                next_point = sub.iloc[i + 1]

                # Get current point's PM2.5 category
                current_category = current_point.get("pm25_category", "No disponible")
                
                # Determine opacity based on AQI filter selection
                if selected_aqi_categories is None or current_category in selected_aqi_categories:
                    opacity = 200  # Full opacity for selected categories
                else:
                    opacity = 60   # Reduced opacity for non-selected categories

                # Color
                if "pm25_color" in sub.columns:
                    color = current_point["pm25_color"]
                    if isinstance(color, list) and len(color) >= 3:
                        path_color = [color[0], color[1], color[2], opacity]
                    else:
                        path_color = [0, 228, 0, opacity]
                else:
                    path_color = [0, 228, 0, opacity]

                path = {
                    "start_lon": current_point["Lon"],
                    "start_lat": current_point["Lat"],
                    "start_elevation": 50,  # Add elevation to start point
                    "end_lon": next_point["Lon"],
                    "end_lat": next_point["Lat"],
                    "end_elevation": 50,    # Add elevation to end point
                    "R": path_color[0],
                    "G": path_color[1],
                    "B": path_color[2],
                    "A": opacity,  # Store opacity separately for easier access
                    "pm25_category": current_category,
                    "co2_value": current_point.get("co2_value", 0),
                    "pm25_value": current_point.get("pm25_value", 0),
                    "temperature": current_point.get("temperature", 0),
                    "timestamp": (
                        current_point["_time"].strftime("%Y-%m-%d %H:%M:%S")
                        if "_time" in current_point and pd.notna(current_point["_time"])
                        else "No disponible"
                    ),
                    "location": current_point.get("location", "No disponible"),
                }
                local_paths.append(path)
            return local_paths

        if "location" in df.columns:
            for _, sub in df.groupby("location"):
                paths_data.extend(_build_for_subset(sub))
        else:
            paths_data = _build_for_subset(df)

        return paths_data


    #Show empty map if no data

    if df.empty:
        st.info("No hay datos disponibles para mostrar en el mapa.")
        r = pdk.Deck(
        layers=[], 
        map_style='road',
        initial_view_state=pdk.ViewState(
        latitude=7.1333,
        longitude=-73.1333,
        zoom=14,
        bearing=0,
        pitch=45
    )         
        )
        st.pydeck_chart(r, height = 400)
        return

    # Crear columna layer como la media de los valores de contaminación
    pollution_columns = [CO2_COLUMN, PM25_COLUMN]
    
    # Verificar que las columnas existen y calcular la media
    available_columns = [col for col in pollution_columns if col in df.columns]
    
    if available_columns:
        # Calcular la media de las columnas de contaminación disponibles
        df = df.copy()
        df['layer'] = df[available_columns].mean(axis=1, skipna=True)            
            
        # Aplicar colores y categorías
        df[['pm25_color', 'pm25_category']] = df[PM25_COLUMN].apply(
            lambda x: pd.Series(get_pm25_color_and_category(x))
        )
        
        # Crear columnas para el tooltip
        df['co2_value'] = df.get(CO2_COLUMN, 0).round(1)
        df['pm25_value'] = df[PM25_COLUMN].round(1)
        df['temperature'] = df.get(TEMP_COLUMN, 0).round(1)
        
    # Create paths data if there are 2 or more records
    

    
    
    # Initialize layers list
    layers = []
    
    # Add heatmap layers based on selected parameters
    if selected_parameters and isinstance(selected_parameters, dict):
        
        # Temperature Heatmap Layer
        if selected_parameters.get('Temp', False) and 'Temperature' in df.columns:
            temp_data = df.dropna(subset=['Temperature']).copy()
            if not temp_data.empty:
                # Normalize temperature values for better visualization (0-1 range)
                temp_min = temp_data['Temperature'].min()
                temp_max = temp_data['Temperature'].max()
                if temp_max > temp_min:
                    temp_data['weight'] = (temp_data['Temperature'] - temp_min) / (temp_max - temp_min)
                else:
                    temp_data['weight'] = 0.5
                
                temp_heatmap = pdk.Layer(
                    'HeatmapLayer',
                    data=temp_data,
                    get_position='[Lon, Lat]',
                    get_weight='weight',
                    radius_pixels=60,
                    opacity=0.6,
                    color_range=[
                        [0, 0, 255],      # Blue (cold)
                        [0, 255, 255],    # Cyan 
                        [0, 255, 0],      # Green
                        [255, 255, 0],    # Yellow
                        [255, 165, 0],    # Orange
                        [255, 0, 0]       # Red (hot)
                    ],
                    pickable=False
                )
                layers.append(temp_heatmap)
    
    # Add PM2.5 scatter plot if PM2.5 is selected
    if PM25_COLUMN in selected_parameters:
        # Create PM2.5 scatter plot using individual data points
        pm25_data = df.dropna(subset=['PM2.5']).copy()
        if not pm25_data.empty:
            # Get min and max PM2.5 values for size scaling
            pm25_min = pm25_data['PM2.5'].min()
            pm25_max = pm25_data['PM2.5'].max()
            
            # Apply colors and categories using existing function
            pm25_data[['pm25_color', 'pm25_category']] = pm25_data['PM2.5'].apply(
                lambda x: pd.Series(get_pm25_color_and_category(x))
            )
            
            # Ensure pm25_color is properly formatted as list
            pm25_data['pm25_color'] = pm25_data['pm25_color'].apply(
                lambda x: list(x) if hasattr(x, '__iter__') and not isinstance(x, str) else [0, 255, 0, 180]
            )
            
            # Calculate size based on PM2.5 value (higher values = larger circles)
            if pm25_max > pm25_min:
                pm25_data['pm25_size'] = ((pm25_data['PM2.5'] - pm25_min) / (pm25_max - pm25_min) * 40 + 15).astype(float)
            else:
                pm25_data['pm25_size'] = 25.0
                
            pm25_data['pm25_value'] = pm25_data['PM2.5'].round(1).astype(float)
            pm25_data['timestamp'] = pm25_data['_time'].apply(format_colombia_time) if '_time' in pm25_data.columns else 'No disponible'
            
            # Convert coordinates to float to ensure serialization
            pm25_data['Lat'] = pm25_data['Lat'].astype(float)
            pm25_data['Lon'] = pm25_data['Lon'].astype(float)
            
            # Convert all data to native Python types for JSON serialization
            pm25_data_clean = pd.DataFrame()
            pm25_data_clean['Lat'] = pm25_data['Lat'].astype(float).tolist()
            pm25_data_clean['Lon'] = pm25_data['Lon'].astype(float).tolist()
            pm25_data_clean['pm25_color'] = pm25_data['pm25_color'].tolist()
            pm25_data_clean['pm25_size'] = pm25_data['pm25_size'].astype(float).tolist()
            pm25_data_clean['pm25_value'] = pm25_data['pm25_value'].astype(float).tolist()
            pm25_data_clean['pm25_category'] = pm25_data['pm25_category'].astype(str).tolist()
            pm25_data_clean['timestamp'] = pm25_data['timestamp'].astype(str).tolist()
            pm25_data_clean['location'] = pm25_data.get('location', 'No disponible').astype(str).tolist() if 'location' in pm25_data.columns else ['No disponible'] * len(pm25_data)
            
            # Create ScatterplotLayer for PM2.5 data
            pm25_scatter = pdk.Layer(
                'ScatterplotLayer',
                data=pm25_data_clean,
                get_position='[Lon, Lat]',
                get_color='pm25_color',
                get_radius='pm25_size',
                radius_scale=1,
                radius_min_pixels=8,
                radius_max_pixels=50,
                pickable=True,
                auto_highlight=True,
                opacity=0.8
            )
            
            layers.append(pm25_scatter)
    
    if CO2_COLUMN in selected_parameters:
        co2_data = df.dropna(subset=['CO2']).copy()
        co2_data = co2_data[co2_data['CO2'] != -1]
        # Sort by CO2 values (highest to lowest) and take first 10
        co2_data = co2_data.nlargest(10, 'CO2')
        if not co2_data.empty:
            # Get min and max CO2 values for color scaling
            co2_min = co2_data['CO2'].min()
            co2_max = co2_data['CO2'].max()
            
            # Create color based on CO2 value using standard thresholds
            def get_co2_color(co2_value):
                # Standard CO2 thresholds (ppm)
                if co2_value <= 400:
                    return [0, 255, 0, 180]    # Green - Outdoor level
                elif co2_value <= 600:
                    return [128, 255, 0, 180]  # Light green - Acceptable
                elif co2_value <= 1000:
                    return [255, 255, 0, 180]  # Yellow - Drowsiness may begin
                elif co2_value <= 5000:
                    return [255, 165, 0, 180]  # Orange - Workplace exposure limit
                elif co2_value <= 10000:
                    return [255, 69, 0, 180]   # Red orange - Drowsiness
                else:
                    return [255, 0, 0, 180]    # Red - Immediately dangerous
            
            # Apply colors to data
            co2_data['co2_color'] = co2_data['CO2'].apply(get_co2_color)
            co2_data['co2_size'] = ((co2_data['CO2'] - co2_min) / (co2_max - co2_min) * 50 + 10) if co2_max > co2_min else 30
            co2_data['co2_value'] = co2_data['CO2'].round(1)
            co2_data['timestamp'] = co2_data['_time'].dt.strftime('%Y-%m-%d %H:%M:%S') if '_time' in co2_data.columns else 'No disponible'

            co2_scatter = pdk.Layer(
                'ScatterplotLayer',
                data=co2_data,
                get_position='[Lon, Lat]',
                get_color='co2_color',
                get_radius='co2_size',
                radius_scale=1,
                radius_min_pixels=5,
                radius_max_pixels=60,
                pickable=False,
                auto_highlight=False,
                opacity=0.8
            )

            layers.append(co2_scatter)

    if TEMP_COLUMN in selected_parameters:
        temp_data = df.dropna(subset=['Temperature']).copy()
        if not temp_data.empty:
            # Get min and max temperature values for color scaling
            temp_min = temp_data['Temperature'].min()
            temp_max = temp_data['Temperature'].max()
            
            # Create color based on temperature value using standard thresholds
            def get_temp_color(temp_value):
                # Standard temperature thresholds (°C)
                if temp_value <= 10:
                    return [0, 0, 255, 180]     # Blue - Very cold
                elif temp_value <= 15:
                    return [0, 128, 255, 180]   # Light blue - Cold
                elif temp_value <= 20:
                    return [0, 255, 255, 180]   # Cyan - Cool
                elif temp_value <= 25:
                    return [0, 255, 0, 180]     # Green - Comfortable
                elif temp_value <= 30:
                    return [255, 255, 0, 180]   # Yellow - Warm
                elif temp_value <= 35:
                    return [255, 165, 0, 180]   # Orange - Hot
                else:
                    return [255, 0, 0, 180]     # Red - Very hot
            
            # Apply colors and size to data
            temp_data['temp_color'] = temp_data['Temperature'].apply(get_temp_color)
            temp_data['temp_size'] = ((temp_data['Temperature'] - temp_min) / (temp_max - temp_min) * 40 + 15) if temp_max > temp_min else 25
            temp_data['temp_value'] = temp_data['Temperature'].round(1)
            temp_data['timestamp'] = temp_data['_time'].dt.strftime('%Y-%m-%d %H:%M:%S') if '_time' in temp_data.columns else 'No disponible'

            # Use ColumnLayer for temperature (rectangular columns)
            temp_columns = pdk.Layer(
                'ColumnLayer',
                data=temp_data,
                get_position='[Lon, Lat]',
                get_fill_color='temp_color',
                get_elevation='temp_size',
                elevation_scale=2,
                radius=15,
                pickable=False,
                auto_highlight=False,
                opacity=0.7
            )

            layers.append(temp_columns)

    # Check if any layers exist
    

    # Set the viewport location
    view_state = pdk.ViewState(
        latitude=df['Lat'].mean(),
        longitude=df['Lon'].mean(),
        zoom=10,
        bearing=0,
        pitch=45
    )

    # Render with LineLayer
    r = pdk.Deck(
        layers=layers, 
        map_style='road',
        initial_view_state=view_state,
        tooltip={
            "html": "<b>PM2.5:</b> {pm25_value} μg/m³<br/><b>Ubicación:</b> {location}",
            "style": {
                "backgroundColor": "rgba(0, 0, 0, 0.8)",
                "color": "white",
                "borderRadius": "5px",
                "padding": "10px",
                "fontSize": "12px"
            }
        }
    )
    
    # Mostrar en Streamlit
    st.pydeck_chart(r, height = 450)

@st.fragment()
def plot_map(df, selected_parameters, selected_aqi_categories=None, auto_refresh=False):
    # Definir constantes para las columnas de datos ------------------

    PM25_COLUMN = 'PM2.5'
    CO2_COLUMN = 'CO2'
    TEMP_COLUMN = 'Temperature'

    PM25_THRESHOLDS = [
                    (0.0, 12.0, 0, 50, "Buena", "#00e400"),
                    (12.1, 35.4, 51, 100, "Moderada", "#ffff00"),
                    (35.5, 55.4, 101, 150, "Dañina para sensibles", "#ff7e00"),
                    (55.5, 150.4, 151, 200, "Dañina", "#ff0000"),
                    (150.5, 250.4, 201, 300, "Muy dañina", "#8f3f97"),
                    (250.5, 500.4, 301, 500, "Peligrosa", "#7e0023")
                ]
    
    # Filter out invalid data (-1 values in key columns)
    df = df[
        (df.get('CO2', 0) != -1) & 
        (df.get('PM2.5', 0) != -1) & 
        (df.get('Lat', 0) != -1) & 
        (df.get('Lon', 0) != -1)
    ].copy()
    
    if df.empty:
        st.warning("No hay datos válidos para mostrar después del filtrado.")
        return
    
    # Functions ------------------------------------------------
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
    
     
    #------------------- Mapa principal ------------------
                
    if df.empty:
        st.info("No hay datos disponibles para mostrar en el mapa.")
        r = pdk.Deck(
        layers=[], 
        map_style='road',
        initial_view_state=pdk.ViewState(
        latitude=7.1333,
        longitude=-73.1333,
        zoom=14,
        bearing=0,
        pitch=45
    )         
        )
        st.pydeck_chart(r, height = 400)
        return

    # Crear columna layer como la media de los valores de contaminación
    pollution_columns = [CO2_COLUMN, PM25_COLUMN]
    
    # Verificar que las columnas existen y calcular la media
    available_columns = [col for col in pollution_columns if col in df.columns]
    
    if available_columns:
        # Calcular la media de las columnas de contaminación disponibles
        df = df.copy()
        df['layer'] = df[available_columns].mean(axis=1, skipna=True)            
            
        # Aplicar colores y categorías
        df[['pm25_color', 'pm25_category']] = df[PM25_COLUMN].apply(
            lambda x: pd.Series(get_pm25_color_and_category(x))
        )
        
        # Crear columnas para el tooltip
        df['co2_value'] = df.get(CO2_COLUMN, 0).round(1)
        df['pm25_value'] = df[PM25_COLUMN].round(1)
        df['temperature'] = df.get(TEMP_COLUMN, 0).round(1)
        
    # Create paths data if there are 2 or more records
    
    
    # Initialize layers list
    layers = []

    co2_data = df.dropna(subset=['CO2']).copy()
    co2_data = co2_data[co2_data['CO2'] != -1]
    # Sort by CO2 values (highest to lowest) and take first 10
    co2_data = co2_data.nlargest(15, 'CO2')
    if not co2_data.empty:
        # Get min and max CO2 values for color scaling
        co2_min = co2_data['CO2'].min()
        co2_max = co2_data['CO2'].max()
        
        # Create color based on CO2 value using standard thresholds
        def get_co2_color(co2_value):
            # Standard CO2 thresholds (ppm)
            if co2_value <= 400:
                return [0, 255, 0, 180]    # Green - Outdoor level
            elif co2_value <= 600:
                return [128, 255, 0, 180]  # Light green - Acceptable
            elif co2_value <= 1000:
                return [255, 255, 0, 180]  # Yellow - Drowsiness may begin
            elif co2_value <= 5000:
                return [255, 165, 0, 180]  # Orange - Workplace exposure limit
            elif co2_value <= 10000:
                return [255, 69, 0, 180]   # Red orange - Drowsiness
            else:
                return [255, 0, 0, 180]    # Red - Immediately dangerous
        
        # Apply colors to data
        co2_data['co2_color'] = co2_data['CO2'].apply(get_co2_color)
        co2_data['co2_size'] = ((co2_data['CO2'] - co2_min) / (co2_max - co2_min) * 50 + 10) if co2_max > co2_min else 30
        co2_data['co2_value'] = co2_data['CO2'].round(1)
        co2_data['timestamp'] = co2_data['_time'].dt.strftime('%Y-%m-%d %H:%M:%S') if '_time' in co2_data.columns else 'No disponible'
        co2_data['location'] = co2_data['location'] if 'location' in co2_data.columns else 'No disponible'

        co2_scatter = pdk.Layer(
            'ScatterplotLayer',
            data=co2_data,
            get_position='[Lon, Lat]',
            get_color='co2_color',
            get_radius='co2_size',
            radius_scale=1,
            radius_min_pixels=5,
            radius_max_pixels=60,
            pickable=True,
            auto_highlight=False,
            opacity=0.8
        )

        layers.append(co2_scatter)

    # Set the viewport location
    view_state = pdk.ViewState(
        latitude=df['Lat'].mean(),
        longitude=df['Lon'].mean(),
        zoom=10,
        bearing=0,
        pitch=45
    )

    r = pdk.Deck(
        layers=layers, 
        map_style='road',
        initial_view_state=view_state,
        tooltip={
            "html": "<b>CO₂:</b> {co2_value} ppm<br/><b>Ruta:</b> {location}",
            "style": {
                "backgroundColor": "rgba(0, 0, 0, 0.8)",
                "color": "white",
                "borderRadius": "5px",
                "padding": "10px",
                "fontSize": "12px"
            }
        }
    )
        
    # Mostrar en Streamlit
    st.pydeck_chart(r, height=450)

def main():

    #Page banner
    st.html("""

    <div class="hero-section">
        <h1 style="margin: 0; font-size: 36px; text-align: center;">Análisis estadístico</h1>
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
                last_time_str = format_colombia_time(last_time)
                st.caption(f"Últimos datos recibidos: {last_time_str}",width="stretch")
            except:
                st.info("No fue posible obtener la última conexión de datos.")   


        # Convert routes to integers for better handling

        st.write("Total de registros analizados: " + str(len(df)))
        
        # Calculate key metrics
        try:
            # PM2.5 thresholds for AQI classification
            PM25_THRESHOLDS = [
                (0.0, 12.0, 0, 50, "Buena", "#00e400"),
                (12.1, 35.4, 51, 100, "Moderada", "#ffff00"),
                (35.5, 55.4, 101, 150, "Dañina para sensibles", "#ff7e00"),
                (55.5, 150.4, 151, 200, "Dañina", "#ff0000"),
                (150.5, 250.4, 201, 300, "Muy dañina", "#8f3f97"),
                (250.5, 500.4, 301, 500, "Peligrosa", "#7e0023")
            ]
            
            def get_pm25_category(pm25_value):
                for low, high, aqi_low, aqi_high, category, color_hex in PM25_THRESHOLDS:
                    if low <= pm25_value <= high:
                        return category
                return PM25_THRESHOLDS[-1][4]  # Return "Peligrosa" if out of range
            
            # Most dangerous hour (highest average PM2.5)
            df['hour'] = df['_time'].dt.hour
            hourly_pm25 = df.groupby('hour')['PM2.5'].mean()
            most_dangerous_hour = hourly_pm25.idxmax()
            max_pm25_value = hourly_pm25.max()
            
            # Most contaminated route (highest average PM2.5)
            route_pm25 = df.groupby('location')['PM2.5'].mean()
            most_contaminated_route = route_pm25.idxmax()
            max_route_pm25 = route_pm25.max()
            
            # Least contaminated route (lowest average PM2.5)
            least_contaminated_route = route_pm25.idxmin()
            min_route_pm25 = route_pm25.min()
            
            # Most common air quality category
            df['pm25_category'] = df['PM2.5'].apply(get_pm25_category)
            most_common_category = df['pm25_category'].mode().iloc[0] if not df['pm25_category'].mode().empty else "No disponible"
            category_count = df['pm25_category'].value_counts().iloc[0] if not df['pm25_category'].value_counts().empty else 0
            category_percentage = (category_count / len(df) * 100) if len(df) > 0 else 0
            
            with st.container(key="info"):
                with st.container(key="col1"):
                    st.html("""<div class="graphtitle"> Hora Más Peligrosa </div>""")
                    st.metric(
                        label="Hora Más Peligrosa",
                        label_visibility="collapsed",
                        value=f"{most_dangerous_hour}:00",
                        delta=f"{max_pm25_value:.1f} μg/m³"
                    )
                
                with st.container(key="col2"):
                    st.html("""<div class="graphtitle"> Ruta Más Contaminada </div>""")
                    st.metric(
                        label="Ruta Más Contaminada",
                        label_visibility="collapsed",
                        value=most_contaminated_route,
                        delta=f"{max_route_pm25:.1f} μg/m³"
                    )
                
                with st.container(key="col3"):
                    st.html("""<div class="graphtitle"> Ruta Menos Contaminada </div>""")
                    st.metric(
                        label="Ruta Menos Contaminada",
                        label_visibility="collapsed", 
                        value=least_contaminated_route,
                        delta=f"{min_route_pm25:.1f} μg/m³"
                    )
                
                with st.container(key="col4"):
                    st.html("""<div class="graphtitle"> Categoría Más Común </div>""")
                    st.metric(
                        label="Categoría Más Común",
                        label_visibility="collapsed",
                        value=most_common_category,
                        delta=f"{category_percentage:.1f}% de mediciones"
                    )
                
        except Exception as e:
            st.warning(f"No se pudieron calcular los indicadores clave: {e}")

        # Define available parameters (used across columns)
        available_parameters = ["CO2"]
            
        # Apply filters to dataframe
        filtered_df = df.copy()
        
        
        with st.container(key="main"):
            with st.container(key="pie"):
                try:
                    st.html(
                    """
                    <div class="graphtitle"> Distribución de Categorías de AQI </div>
                    """)
                    
                    # Calculate category distribution
                    category_counts = df['pm25_category'].value_counts()
                    
                    # Create pie chart
                    fig_pie = px.pie(
                        values=category_counts.values,
                        names=category_counts.index,
                        title="",
                        color=category_counts.index,
                        color_discrete_map={'Buena':'#00e400',
                                 "Moderada":"#ffff00",
                                 "Dañina para sensibles":"#ff7e00",
                                 'Dañina':'#ff0000',
                                 "Muy dañina":"#8f3f97",
                                 "Peligrosa":"#7e0023"})
                    
                    # Update layout for better appearance in column
                    fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                    fig_pie.update_layout(
                        showlegend=True,
                        margin=dict(t=20, b=20, l=20, r=20)
                    )
                    
                    st.plotly_chart(fig_pie, use_container_width=True, theme=None, key="pie_categories")
                    
                except Exception as e:
                    st.warning(f"No se pudo generar el gráfico de categorías: {e}")
            
            with st.container(key="daily"):
                try:
                    st.html(
                    """
                    <div class="graphtitle"> Estadísticas Diarias </div>
                    """)
                    
                    # Calculate daily statistics
                    df['date'] = df['_time'].dt.date
                    daily_stats = df.groupby('date').agg({
                        'PM2.5': ['mean', 'max', 'min', 'count'],
                        'CO2': ['mean', 'max', 'min'],
                        'Temperature': ['mean', 'max', 'min']
                    }).round(2)
                    
                    # Flatten column names
                    daily_stats.columns = ['_'.join(col).strip() for col in daily_stats.columns]
                    
                    # Date selector
                    available_dates = sorted(daily_stats.index.tolist(), reverse=True)
                    if available_dates:
                        selected_date = st.selectbox(
                            "Seleccionar fecha:",
                            options=available_dates,
                            index=0,  # Default to most recent date
                            key="date_selector"
                        )
                        
                        # Display stats for selected date
                        if selected_date in daily_stats.index:
                            selected_stats = daily_stats.loc[selected_date]
                            
                            st.markdown(f"**Estadísticas para {selected_date}**")
                            
                            col_pm, col_co2, col_temp = st.columns(3)
                            
                            with col_pm:
                                st.metric(
                                    "PM2.5 Promedio",
                                    f"{selected_stats['PM2.5_mean']:.1f}",
                                    delta=f"Max: {selected_stats['PM2.5_max']:.1f}"
                                )
                            
                            with col_co2:
                                st.metric(
                                    "CO2 Promedio", 
                                    f"{selected_stats['CO2_mean']:.1f}",
                                    delta=f"Max: {selected_stats['CO2_max']:.1f}"
                                )
                            
                            with col_temp:
                                st.metric(
                                    "Temp Promedio",
                                    f"{selected_stats['Temperature_mean']:.1f}°C",
                                    delta=f"Max: {selected_stats['Temperature_max']:.1f}°C"
                                )
                            
                            # Show additional details for selected date
                            st.markdown("**Detalles del día:**")
                            
                            # Create a more compact table format
                            details_data = {
                                "Métrica": ["PM2.5", "CO2", "Temperatura"],
                                "Mínimo": [
                                    f"{selected_stats['PM2.5_min']:.1f} μg/m³",
                                    f"{selected_stats['CO2_min']:.1f} ppm",
                                    f"{selected_stats['Temperature_min']:.1f}°C"
                                ],
                                "Máximo": [
                                    f"{selected_stats['PM2.5_max']:.1f} μg/m³",
                                    f"{selected_stats['CO2_max']:.1f} ppm",
                                    f"{selected_stats['Temperature_max']:.1f}°C"
                                ]
                            }
                            
                            details_df = pd.DataFrame(details_data)
                            st.dataframe(details_df, hide_index=True, height=140)
                        
                except Exception as e:
                    st.warning(f"No se pudieron calcular las estadísticas diarias: {e}")

        with st.container(key="graphsy"):
            with st.container(key="graph1"):
                st.html(
                """
                <div class="graphtitle"> Puntos con concentración de PM2.5 más alta</div>
                """)
                
                # Parameters filter - Multiselect
                default_selected = ["PM2.5"]

                # AQI Category Filter
                aqi_categories = ["Buena", "Moderada", "Dañina para sensibles", "Dañina", "Muy dañina", "Peligrosa"]
                    
                # Apply filters to dataframe
                dfchart4 = df.nlargest(15, 'PM2.5', keep='first')
                
                # Show filtered results
                if not dfchart4.empty:
                    plot_map2(dfchart4, default_selected, aqi_categories, auto_refresh=False)
                else:
                    plot_map2(pd.DataFrame(), [], [], auto_refresh=False)

            with st.container(key="graph2"):

                st.html(
                """
                <div class="graphtitle"> Concentración de C02 en el mapa </div>
                """)
                # Show filtered results
                if not filtered_df.empty:
                    plot_map(filtered_df, available_parameters, auto_refresh=False)
                else:
                    plot_map(pd.DataFrame(), [], [], auto_refresh=False)

        with st.container(key="graphsx"):
            with st.container(key="graphx1"):
                
                st.html(
                """
                <div class="graphtitle"> Concentración de PM2.5 y C02 por ruta </div>
                """)

                dfchart5 = df.groupby('location')['PM2.5'].mean()
                dfchart5x = df.groupby('location')['CO2'].mean()

                fig5 = px.bar({'Ruta': dfchart5.index,
                'Promedio PM2.5': dfchart5.values, 'Promedio CO2': dfchart5x.values,},
                x="Ruta",y=["Promedio CO2", "Promedio PM2.5"], barmode = 'group', labels={'value':'Concentración'},
                    color_discrete_sequence=["#0FA539","#00707c"])

                st.plotly_chart(fig5, use_container_width=True, theme=None, key="fig5")

            with st.container(key="graphx2"):
                st.html(
                """
                <div class="graphtitle"> Evolución por día del PM2.5 y C02 </div>
                """)
                
                dfchart6 = df.groupby('_time')['PM2.5'].mean()
                dfchart6x = df.groupby('_time')['CO2'].mean()

                fig6 = px.line({'Fecha': dfchart6.index,
                'Promedio PM2.5': dfchart6.values, 'Promedio CO2': dfchart6x.values,},
                x="Fecha",y=["Promedio CO2", "Promedio PM2.5"], labels={'value':'Concentración'},
                    color_discrete_sequence=["#0FA539","#00707c"])

                st.plotly_chart(fig6, use_container_width=True, theme=None, key="fig6")

if __name__ == "__main__" or st._is_running_with_streamlit:

    main()