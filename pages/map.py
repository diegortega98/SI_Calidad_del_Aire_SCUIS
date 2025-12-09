import streamlit as st
import plotly.express as px
import pandas as pd
import pydeck as pdk
import time
from datetime import datetime
from data.connection import get_client_or_raise, run_query, flux_query, ConnectionNotReady
from influxdb_client import InfluxDBClient
from utils.timezone_utils import format_colombia_time

if "map_controls" not in st.session_state:
    st.session_state.map_controls = False

# Cachea el cliente de conexión.
@st.cache_resource(show_time=True,show_spinner=False)
def get_cached_client() -> InfluxDBClient:
    with st.spinner("Estableciendo conexión con SmartCampus UIS..."):
        client = get_client_or_raise()
    return client

# Cachea datos (dependen de parámetros).
@st.cache_data(ttl=10, show_spinner=False)
def cached_query(flux: str):
    client = get_cached_client()
    return run_query(client, flux)

@st.fragment()
def plot_map(df, selected_parameters, selected_aqi_categories=None, auto_refresh=False):
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
            # Ensure data is sorted by time within each subset
            if "_time" in sub.columns:
                sub = sub.sort_values("_time").copy()
            else:
                sub = sub.copy()
            
            # Filter out invalid coordinates (-1, -1) within the subset
            if 'Lat' in sub.columns and 'Lon' in sub.columns:
                sub = sub[(sub['Lat'] != -1) & (sub['Lon'] != -1)].copy()
            
            # If after filtering we have less than 2 points, return empty
            if len(sub) < 2:
                return []
            
            local_paths = []
            # Create simple paths between consecutive valid points
            for i in range(len(sub) - 1):
                current_point = sub.iloc[i]
                next_point = sub.iloc[i + 1]

                # Check time gap - don't create path if more than 3 minutes apart
                if '_time' in sub.columns:
                    current_time = current_point['_time']
                    next_time = next_point['_time']
                    
                    if pd.notna(current_time) and pd.notna(next_time):
                        try:
                            time_diff = abs((next_time - current_time).total_seconds())
                            if time_diff > 180:  # 3 minutes = 180 seconds
                                continue  # Skip this path segment due to time gap
                        except Exception:
                            # If time comparison fails, skip this segment to be safe
                            continue

                # Check distance gap - don't create path if points are too far apart
                # Calculate approximate distance in degrees (rough estimate)
                lat_diff = abs(next_point['Lat'] - current_point['Lat'])
                lon_diff = abs(next_point['Lon'] - current_point['Lon'])
                distance_degrees = (lat_diff**2 + lon_diff**2)**0.5
                
                # Skip if distance is more than ~0.01 degrees (roughly 1km)
                if distance_degrees > 0.01:
                    continue  # Skip this path segment due to large distance gap

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
                    "start_elevation": 10,  
                    "end_lon": next_point["Lon"],
                    "end_lat": next_point["Lat"],
                    "end_elevation": 10,    
                    "R": path_color[0],
                    "G": path_color[1],
                    "B": path_color[2],
                    "A": opacity,  # Store opacity separately for easier access
                    "pm25_category": current_category,
                    "co2_value": current_point.get("co2_value", 0),
                    "pm25_value": current_point.get("pm25_value", 0),
                    "temperature": current_point.get("temperature", 0),
                    "timestamp": (
                        format_colombia_time(current_point["_time"])
                        if "_time" in current_point and pd.notna(current_point["_time"])
                        else "No disponible"
                    ),
                    "location": current_point.get("location", "No disponible"),
                }
                local_paths.append(path)
            return local_paths

        if "location" in df.columns:
            # Group by location to ensure we don't connect paths between different routes
            for location, sub in df.groupby("location"):
                if len(sub) >= 2:  # Only process if we have at least 2 points
                    paths_data.extend(_build_for_subset(sub))
        else:
            if "header_deviceId" in df.columns:
                for device, sub in df.groupby("header_deviceId"):
                    if len(sub) >= 2:
                        paths_data.extend(_build_for_subset(sub))
            else:
                paths_data = _build_for_subset(df)

        return paths_data
    
    

    #------------------- Mapa principal ------------------
                
    with st.container(key="map_container"):

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
            st.pydeck_chart(r, height=380)
            return

        # Filter out invalid coordinates (-1, -1) before processing
        if 'Lat' in df.columns and 'Lon' in df.columns:
            initial_count = len(df)
            # Remove rows where Lat or Lon is -1
            df = df[(df['Lat'] != -1) & (df['Lon'] != -1)].copy()
            
            
        
        # Check if we still have data after filtering
        if df.empty:
            st.warning("No hay datos válidos para mostrar en el mapa después del filtrado de coordenadas.")
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
            st.pydeck_chart(r, height=380)
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
            
        # Initialize layers list
        layers = []
        
        # Add heatmap layers based on selected parameters
        if selected_parameters and isinstance(selected_parameters, dict):
            
            # CO2 Scatter Layer
            if selected_parameters.get('CO2', False) and 'CO2' in df.columns:
                co2_data = df.dropna(subset=['CO2']).copy()
                # Additional filtering for invalid coordinates
                if 'Lat' in co2_data.columns and 'Lon' in co2_data.columns:
                    co2_data = co2_data[(co2_data['Lat'] != -1) & (co2_data['Lon'] != -1)].copy()
                
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
                    co2_data['co2_value'] = co2_data['CO2'].round(1)
                    co2_data['timestamp'] = co2_data['_time'].apply(format_colombia_time) if '_time' in co2_data.columns else 'No disponible'
                    
                    co2_scatter = pdk.Layer(
                        'ScatterplotLayer',
                        data=co2_data,
                        get_position='[Lon, Lat]',
                        get_color='co2_color',
                        opacity=0.5,
                        pickable=False
                    )
                    layers.append(co2_scatter)
            
            # Temperature Heatmap Layer
            if selected_parameters.get('Temp', False) and 'Temperature' in df.columns:
                temp_data = df.dropna(subset=['Temperature']).copy()
                # Additional filtering for invalid coordinates
                if 'Lat' in temp_data.columns and 'Lon' in temp_data.columns:
                    temp_data = temp_data[(temp_data['Lat'] != -1) & (temp_data['Lon'] != -1)].copy()
                
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
        
        # Add PM2.5 paths layer only if PM2.5 is selected
        if PM25_COLUMN in selected_parameters:
            # Convert to DataFrame and add LineLayer for PM2.5 paths
            
            paths_df = build_paths(df, selected_aqi_categories)
            # Define a LineLayer to display paths on the map
            line_layer = pdk.Layer(
                'LineLayer',
                data=paths_df,
                get_source_position='[start_lon, start_lat, start_elevation]',
                get_target_position='[end_lon, end_lat, end_elevation]',
                get_color='[R, G, B, A]',  # Use the opacity from data
                get_width=10,
                highlight_color=[0, 0, 255],
                picking_radius=10,
                auto_highlight=True,
                pickable=True,
                wireframe=False,
                extruded=True
            )
            
            layers.append(line_layer)
        
        if CO2_COLUMN in selected_parameters:
            co2_data = df.dropna(subset=['CO2']).copy()
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
                co2_data['timestamp'] = co2_data['_time'].apply(format_colombia_time) if '_time' in co2_data.columns else 'No disponible'

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
            # Additional filtering for invalid coordinates
            if 'Lat' in temp_data.columns and 'Lon' in temp_data.columns:
                temp_data = temp_data[(temp_data['Lat'] != -1) & (temp_data['Lon'] != -1)].copy()
            
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
                temp_data['timestamp'] = temp_data['_time'].apply(format_colombia_time) if '_time' in temp_data.columns else 'No disponible'

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
                "html": "<b>CO₂:</b> {co2_value} ppm<br/><b>PM2.5:</b> {pm25_value} μg/m³<br/><b>Calidad:</b> {pm25_category}<br/><b>Temp:</b> {temperature} °C<br/><b>Tiempo:</b> {timestamp}<br/><b>Ubicación:</b> {location}",
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
        st.pydeck_chart(r, height=380)

        if st.session_state.map_controls:

            with st.container(key="map_controls"):
                
                # Legend selector
                legend_option = st.selectbox(
                    "Seleccionar leyenda:",
                    options=["PM2.5 (µg/m³)", "CO2 (ppm)", "Temperatura (°C)"],
                    index=0,
                    key="legend_selector"
                )
                
                if legend_option == "PM2.5 (µg/m³)":
                    #leyenda PM2.5
                    st.html(
                    """<div class="mydiv">
                    <table style="
                        border-spacing: 0;
                        text-align: center;
                        margin: auto;
                        box-sizing: border-box;
                        border-radius: 12px;
                        overflow: hidden;
                    ">
                        <thead>
                        <tr style="background-color: #333; color: white;">
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">PM2.5 (µg/m³)</th>
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">Categoría</th>
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">Color</th>
                        </tr>
                        </thead>
                        <tbody>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">0.0 - 12.0</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Buena</td>
                            <td style="background-color: #00e400; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">12.1 - 35.4</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Moderada</td>
                            <td style="background-color: #ffff00; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">35.5 - 55.4</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Dañina para sensibles</td>
                            <td style="background-color: #ff7e00; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">55.5 - 150.4</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Dañina</td>
                            <td style="background-color: #ff0000; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">150.5 - 250.4</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Muy dañina</td>
                            <td style="background-color: #8f3f97; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">250.5 - 500.4</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Peligrosa</td>
                            <td style="background-color: #7e0023; padding: 4px;">&nbsp;</td>
                        </tr>
                        </tbody>
                    </table>
                    </div>"""
                    )
                
                elif legend_option == "CO2 (ppm)":
                    # CO2 legend
                    st.html(
                    """<div class="mydiv">
                    <table style="
                        border-spacing: 0;
                        text-align: center;
                        margin: auto;
                        box-sizing: border-box;
                        border-radius: 12px;
                        overflow: hidden;
                    ">
                        <thead>
                        <tr style="background-color: #333; color: white;">
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">CO2 (ppm)</th>
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">Nivel</th>
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">Color</th>
                        </tr>
                        </thead>
                        <tbody>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">≤ 400</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Exterior</td>
                            <td style="background-color: #00ff00; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">401 - 600</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Aceptable</td>
                            <td style="background-color: #80ff00; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">601 - 1000</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Somnolencia</td>
                            <td style="background-color: #ffff00; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">1001 - 5000</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Límite laboral</td>
                            <td style="background-color: #ffa500; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">5001 - 10000</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Peligroso</td>
                            <td style="background-color: #ff4500; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">> 10000</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Inmediatamente peligroso</td>
                            <td style="background-color: #ff0000; padding: 4px;">&nbsp;</td>
                        </tr>
                        </tbody>
                    </table>
                    </div>"""
                    )
                
                elif legend_option == "Temperatura (°C)":
                    # Temperature legend
                    st.html(
                    """<div class="mydiv">
                    <table style="
                        border-spacing: 0;
                        text-align: center;
                        margin: auto;
                        box-sizing: border-box;
                        border-radius: 12px;
                        overflow: hidden;
                    ">
                        <thead>
                        <tr style="background-color: #333; color: white;">
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">Temperatura (°C)</th>
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">Sensación</th>
                            <th style="padding: 6px; border-bottom: 1px solid #ccc;">Color</th>
                        </tr>
                        </thead>
                        <tbody>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">≤ 10</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Muy frío</td>
                            <td style="background-color: #0000ff; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">11 - 15</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Frío</td>
                            <td style="background-color: #0080ff; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">16 - 20</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Fresco</td>
                            <td style="background-color: #00ffff; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">21 - 25</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Confortable</td>
                            <td style="background-color: #00ff00; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">26 - 30</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Cálido</td>
                            <td style="background-color: #ffff00; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">31 - 35</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Caliente</td>
                            <td style="background-color: #ffa500; padding: 4px;">&nbsp;</td>
                        </tr>
                        <tr>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">> 35</td>
                            <td style="padding: 4px; background-color: rgba(255, 255, 255, 0.6);">Muy caliente</td>
                            <td style="background-color: #ff0000; padding: 4px;">&nbsp;</td>
                        </tr>
                        </tbody>
                    </table>
                    </div>"""
                    )

                if st.button("Recargar datos", type="secondary", key="reload_data", on_click=lambda: st.rerun()):
                    st.rerun()


                st.button("Ocultar leyenda", key="toggle_map_controls", on_click=lambda: st.session_state.update(map_controls=not st.session_state.map_controls))
        else:
            # hidden controls

            with st.container(key="hidden_map_controls"):

                st.button("Mostrar leyenda", key="show_map_controls", on_click=lambda: st.session_state.update(map_controls=not st.session_state.map_controls))

@st.fragment(run_every=5)
def auto_refresh_map(date_range, selected_routes, selected_parameters, selected_aqi_categories=None, selected_hours=None):
    """Fragment that runs every 5 seconds when auto-refresh is enabled"""
    import pandas as pd
    
    # Re-query fresh data
    fields = ["Lat", "Lon", "CO2", "PM2_5", "Temperature", "location"]
    flux = flux_query("messages", start="-100d")
    
    try:
        client = get_cached_client()
        # Clear cache to get fresh data
        st.cache_data.clear()
        fresh_df = cached_query(flux)

        print(fresh_df.columns)
        
        if not fresh_df.empty:
            # Convert routes to integers for better handling
            
            
            # Apply the same filters as main app
            filtered_df = fresh_df.copy()
            
            # Apply date filter
            if '_time' in fresh_df.columns and len(date_range) == 2:
                start_date, end_date = date_range
                filtered_df = filtered_df[
                    (filtered_df['_time'].dt.date >= start_date) & 
                    (filtered_df['_time'].dt.date <= end_date)
                ]
            
            # Apply hour filter
            if '_time' in fresh_df.columns and selected_hours:
                filtered_df['hour'] = filtered_df['_time'].dt.hour
                filtered_df = filtered_df[filtered_df['hour'].isin(selected_hours)]
            
            # Apply route filter
            if 'location' in fresh_df.columns and selected_routes:
                filtered_df = filtered_df[filtered_df['location'].isin(selected_routes)]

            if not filtered_df.empty:  
                # Plot the refreshed map
                plot_map(filtered_df, selected_parameters, selected_aqi_categories, auto_refresh=True)

                # Show refresh indicator
                current_time = pd.Timestamp.now().strftime("%H:%M:%S")
                st.caption(f"Última actualización: {current_time}")
            else:
                st.warning("No hay datos que coincidan con los filtros para la actualización automática.")
        else:
            st.warning("No hay datos disponibles para la actualización automática.")
        
    except Exception as e:
        st.error(f"Error al actualizar mapa: {e}")

def main():
    st.html("""
    <h1 style="padding: 0px 0px 0px 0px; font-size: clamp(1.400rem, 3.9vw, 3.0625rem); margin:10px 0px 0px 40px; text-align: center;">Dashboard de contaminación en rutas del AMB</h1>
    """)

    # Establish connection
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

    # Query to fetch data
    flux = flux_query(bucket="messages", start="-100d")

    with st.spinner("Consultando datos..."):
        try:
            df = cached_query(flux)
            
            #Columns location','CO2', 'Lat', 'Lon', 'PM2_5', 'Temperature'
        except Exception as e:
            st.warning(f"No fue posible obtener datos. Revisa la query Flux. Detalle: {e}")
        else:
            # Last Connection
            try:
                last_time = df['_time'].max()
                last_time_str = format_colombia_time(last_time)
                st.caption(f"Últimos datos recibidos: {last_time_str}",width="stretch")
            except:
                st.info("No fue posible obtener la última conexión de datos.")   
        
        with st.sidebar:
            
            # Define available parameters (used across columns)
            available_parameters = ["CO2", "PM2.5", "Temperature"]
            
            auto_refresh_enabled = st.toggle(
                "Actualizar en tiempo real ",
                value=False
            )

            st.markdown("### Filtros del mapa")

            # Date filter
            if '_time' in df.columns:
                min_date = df['_time'].min().date()
                max_date = df['_time'].max().date()
                
                date_range = st.date_input(
                    "Rango de fechas:",
                    value=(min_date, max_date),
                    min_value=min_date,
                    max_value=max_date,
                    key="date_filter"
                )
            else:
                st.info("No hay datos de fecha disponibles")
            
            # Hour filter
            if '_time' in df.columns:
                # Extract unique hours from the data
                df['hour'] = df['_time'].dt.hour
                min_hour = int(df['hour'].min())
                max_hour = int(df['hour'].max())
                
                # Handle case when there's only one hour of data
                if min_hour == max_hour:
                    st.info(f"Solo hay datos disponibles para la hora: {min_hour}:00")
                    selected_hours = [min_hour]
                else:
                    hour_range = st.slider(
                        "Rango de horas:",
                        min_value=min_hour,
                        max_value=max_hour,
                        value=(min_hour, max_hour),
                        step=1,
                        key="hour_filter",
                        format="%d:00"
                    )
                    
                    # Convert range to list of hours for filtering
                    selected_hours = list(range(hour_range[0], hour_range[1] + 1))       
        
            # Route filter
            if 'location' in df.columns:
                unique_routes = df['location'].dropna().unique().tolist()
                selected_routes = st.multiselect(
                    "Rutas a mostrar:",
                    options=sorted(unique_routes),
                    default=sorted(unique_routes),
                    key="route_filter"
                )
            else:
                st.info("No hay datos de ruta disponibles")
            
            # Parameters filter - Multiselect
            default_selected = ["PM2.5"]

            selected_params = st.multiselect(
                "Parámetros a mostrar:",
                options=available_parameters,
                default=default_selected,
                key="parameters_filter"
            )
            
            # AQI Category Filter
            aqi_categories = ["Buena", "Moderada", "Dañina para sensibles", "Dañina", "Muy dañina", "Peligrosa"]
            
            selected_aqi_categories = st.pills(
                "Categorías de AQI basadas en PM2.5:",
                aqi_categories,
                default=aqi_categories,
                key="aqi_filter",
                selection_mode="multi"
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
            
            filtered_df['hour'] = filtered_df['_time'].dt.hour
            filtered_df = filtered_df[filtered_df['hour'].isin(selected_hours)]
            filtered_df = filtered_df[filtered_df['location'].isin(selected_routes)]
            
            # Show filtered results
            if not filtered_df.empty:
                st.sidebar.markdown(f"Mostrando {len(filtered_df):,} registros filtrados de {len(df):,} totales")
                # Handle auto-refresh mode
                if auto_refresh_enabled:
                    # Use the auto-refresh fragment
                    auto_refresh_map(date_range, selected_routes, selected_params, selected_aqi_categories, selected_hours)
                else:
                    # Use the normal static map
                    plot_map(filtered_df, selected_params, selected_aqi_categories, auto_refresh=False)
            else:
                plot_map(pd.DataFrame(), [], [], auto_refresh=False)


        with st.container(key="dailies"):
            st.html(f"""<div class="dailytitle"> Gráficos en base a los últimos 7 días </div>""")
            with st.container(key="graphs"):
                with st.container(key="graph1"):
                    st.html("""<div class="graphtitle"> Concentración de PM2.5 y CO2 por ruta </div>""")

                    df["_time"] = pd.to_datetime(df["_time"].dt.tz_localize(None))
                    dfchart1 = df[df["_time"] > (datetime.now() - pd.Timedelta(days=7))]
                    dfchart1x = dfchart1.groupby('location')['PM2.5'].mean().sort_values(ascending=True)
                    dfchart1y = dfchart1.groupby('location')['CO2'].mean().sort_values(ascending=True)

                    # Create color list based on contamination classification using the same thresholds
                    def get_route_colors(pm25_values):
                        # Define PM2.5 thresholds (same as in plot_map function)
                        thresholds = [
                            (0.0, 12.0, 0, 50, "Buena", "#00e400"),
                            (12.1, 35.4, 51, 100, "Moderada", "#ffff00"),
                            (35.5, 55.4, 101, 150, "Dañina para sensibles", "#ff7e00"),
                            (55.5, 150.4, 151, 200, "Dañina", "#ff0000"),
                            (150.5, 250.4, 201, 300, "Muy dañina", "#8f3f97"),
                            (250.5, 500.4, 301, 500, "Peligrosa", "#7e0023")
                        ]
                        
                        colors = []
                        for pm25_value in pm25_values:
                            for low, high, aqi_low, aqi_high, category, color_hex in thresholds:
                                if low <= pm25_value <= high:
                                    colors.append(color_hex)
                                    break
                            else:
                                # If outside range, use the last threshold color
                                colors.append(thresholds[-1][5])
                        return colors
                    
                    route_colors = get_route_colors(dfchart1x.values)

                    fig = px.bar({'Ruta': dfchart1x.index,
                    'Promedio PM2.5': dfchart1x.values, 'Promedio CO2': dfchart1y.values,},
                    x="Ruta",y=["Promedio CO2", "Promedio PM2.5"], barmode = 'group', labels={'value':'Concentración'},
                    color_discrete_sequence=["#0FA539","#00707c"])

                    st.plotly_chart(fig, theme=None, height="content")

                with st.container(key="graph2"):
                    st.html(
                    """
                    <div class="graphtitle"> Evolución por día del PM2.5 y CO2 </div>
                    """)

                    dfchart2 = df[df["_time"] > (datetime.now() - pd.Timedelta(days=7))]
                    
                    dfchart2x = dfchart2.groupby('_time')['PM2.5'].mean()
                    dfchart2y = dfchart2.groupby('_time')['CO2'].mean()

                    fig2 = px.line({'Fecha': dfchart2x.index,
                    'Promedio PM2.5': dfchart2x.values, 'Promedio CO2': dfchart2y.values,},
                    x="Fecha",y=["Promedio CO2", "Promedio PM2.5"], labels={'value':'Concentración'},
                    color_discrete_sequence=["#0FA539","#00707c"])
                    
                    st.plotly_chart(fig2, theme=None, height="content")

if __name__ == "__main__" or st._is_running_with_streamlit:

    main()