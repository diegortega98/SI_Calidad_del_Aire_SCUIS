import streamlit as st
import plotly.express as px
import pandas as pd
import pydeck as pdk
import time
from data.connection import get_client_or_raise, run_query, flux_query, ConnectionNotReady
from influxdb_client import InfluxDBClient

if "map_controls" not in st.session_state:
    st.session_state.map_controls = True

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
def plot_map(df, selected_parameters, auto_refresh=False):
    import numpy as np
    # Definir constantes para las columnas de datos ------------------

    PM25_COLUMN = 'PM2.5'
    CO2_COLUMN = 'CO2'

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

    def get_paths(
        df: pd.DataFrame,
        time_col="_time",
        lat_col="Lat",
        lon_col="Lon",
        group_col="location",
        metric_cols=None,
    ) -> pd.DataFrame:
        """
        Genera segmentos consecutivos (i -> i+1) por cada grupo en group_col,
        con path listo para pydeck y promedios de métricas.
        """
        if group_col not in df.columns:
            raise KeyError(f"'{group_col}' no está en el DataFrame")

        def _build(g: pd.DataFrame) -> pd.DataFrame:
            g = g.sort_values(time_col).reset_index(drop=True)

            # métricas a usar (si no se pasan -> todas numéricas excepto lat/lon/time)
            if metric_cols is None:
                non_metric = {time_col, lat_col, lon_col}
                mcols = g.select_dtypes(include=[np.number]).columns.difference(list(non_metric))
            else:
                mcols = metric_cols

            out = pd.DataFrame({
                "start_time": g[time_col],
                "end_time":   g[time_col].shift(-1),
                "start_lat":  g[lat_col],
                "start_lon":  g[lon_col],
                "end_lat":    g[lat_col].shift(-1),
                "end_lon":    g[lon_col].shift(-1),
            })

            for c in mcols:
                out[f"avg_{c}"] = (g[c] + g[c].shift(-1)) / 2

            out["path"] = out.apply(
                lambda r: [[r["start_lon"], r["start_lat"]], [r["end_lon"], r["end_lat"]]],
                axis=1
            )

            return out.dropna(subset=["end_time"]).reset_index(drop=True)

        segs = (
            df.groupby(group_col, group_keys=True, dropna=False)
            .apply(_build)
            .reset_index(level=0, drop=False)
            .reset_index(drop=True)
        )

        segs["segment_index"] = segs.groupby(group_col).cumcount()
        return segs
    
    

    #------------------- Mapa principal ------------------
                
    with st.container(key="map_container"):

        if df.empty:
            st.warning("No hay datos válidos para mostrar en el mapa.")
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
                    'start_lon': current_point['Lon'],
                    'start_lat': current_point['Lat'],
                    'end_lon': next_point['Lon'],
                    'end_lat': next_point['Lat'],
                    'R': path_color[0],
                    'G': path_color[1],
                    'B': path_color[2],
                    'pm25_category': current_point.get('pm25_category', 'No disponible'),
                    'co2_value': current_point.get('co2_value', 0),
                    'pm25_value': current_point.get('pm25_value', 0),
                    'timestamp': current_point.get('_time', '').strftime('%Y-%m-%d %H:%M:%S') if pd.notna(current_point.get('_time', '')) else 'No disponible'
                }
                paths_data.append(path)
        
        # Initialize layers list
        layers = []
        
        # Add heatmap layers based on selected parameters
        if selected_parameters and isinstance(selected_parameters, dict):
            
            # CO2 Heatmap Layer
            if selected_parameters.get('CO2', False) and 'CO2' in df.columns:
                co2_data = df.dropna(subset=['CO2']).copy()
                if not co2_data.empty:
                    # Normalize CO2 values for better visualization (0-1 range)
                    co2_min = co2_data['CO2'].min()
                    co2_max = co2_data['CO2'].max()
                    if co2_max > co2_min:
                        co2_data['weight'] = (co2_data['CO2'] - co2_min) / (co2_max - co2_min)
                    else:
                        co2_data['weight'] = 0.5
                    
                    co2_heatmap = pdk.Layer(
                        'HeatmapLayer',
                        data=co2_data,
                        get_position='[Lon, Lat]',
                        get_weight='weight',
                        radius_pixels=80,
                        opacity=0.5,
                        color_range=[
                            [0, 255, 0],      # Green (low CO2)
                            [255, 255, 0],    # Yellow
                            [255, 165, 0],    # Orange
                            [255, 0, 0],      # Red (high CO2)
                            [139, 0, 0],      # Dark red
                            [75, 0, 130]      # Purple (very high)
                        ],
                        pickable=False
                    )
                    layers.append(co2_heatmap)
            
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
        
        # Add PM2.5 paths layer only if PM2.5 is selected
        if PM25_COLUMN in selected_parameters:
            # Convert to DataFrame and add LineLayer for PM2.5 paths
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
                
                layers.append(line_layer)
            else:
                # If no paths can be created, show a message only if no other layers exist
                if not layers:
                    st.info("Se necesitan al menos 2 puntos de datos para mostrar rutas.")
        
        # Check if any layers exist
        if not layers:
            st.warning("No hay capas disponibles para mostrar. Selecciona al menos un parámetro.")
            return

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
        st.pydeck_chart(r, height = 505)

        if st.session_state.map_controls:

            with st.container(key="map_controls"):
                
                #leyenda
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

                if st.button("Recargar datos", type="secondary", key="reload_data",on_click=lambda: st.rerun()):
                    st.rerun()


                st.button("Ocultar leyenda", key="toggle_map_controls",on_click=lambda: st.session_state.update(map_controls=not st.session_state.map_controls))
        else:
            # hidden controls

            with st.container(key="hidden_map_controls"):

                st.button("Leyenda", key="show_map_controls",on_click=lambda: st.session_state.update(map_controls=not st.session_state.map_controls))

@st.fragment(run_every=5)
def auto_refresh_map(date_range, selected_routes, selected_parameters):
    """Fragment that runs every 5 seconds when auto-refresh is enabled"""
    import pandas as pd
    
    # Re-query fresh data
    fields = ["Lat", "Lon", "CO2", "PM2_5", "Temperature", "location"]
    flux = flux_query("messages", start="-30d")
    
    try:
        client = get_cached_client()
        # Clear cache to get fresh data
        st.cache_data.clear()
        fresh_df = cached_query(flux)
        
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
            
            # Apply route filter
            if 'location' in fresh_df.columns and selected_routes:
                filtered_df = filtered_df[filtered_df['location'].isin(selected_routes)]

            if not filtered_df.empty:
                # Show refresh indicator
                current_time = pd.Timestamp.now().strftime("%H:%M:%S")
                st.caption(f"Última actualización: {current_time}")
                
                # Plot the refreshed map
                plot_map(filtered_df, selected_parameters, auto_refresh=True)
            else:
                st.warning("No hay datos que coincidan con los filtros para la actualización automática.")
        else:
            st.warning("No hay datos disponibles para la actualización automática.")
        
    except Exception as e:
        st.error(f"Error al actualizar mapa: {e}")

@st.fragment()
def graphs(df):
    with st.container(key="graphs"):
        with st.container(key="graph1"):
            
            st.html(
            """
            <div style="text-align: center;"> Contaminación por ruta </div>
            """)
            st.line_chart(
                df.groupby('route_int')['PM2.5'].mean().sort_values(ascending=False), use_container_width=True,
            )

        with st.container(key="graph2"):
            st.html(
            """
            <div style="text-align: center;"> Contaminación por día </div>
            """)
            
            st.bar_chart(
                df.groupby(df['_time'].dt.date)['metrics_0_fields_PM2.5'].mean().sort_values(ascending=False), use_container_width=True,
            )

def main():
    st.html("""
    <h1 style="margin: 0; font-size: 36px; text-align: center;">Mapa de rutas de contaminación</h1>
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
    flux = flux_query(bucket="messages", start="-30d")

    with st.spinner("Consultando datos..."):
        try:
            df = cached_query(flux)
            #Columns location','CO2', 'Lat', 'Lon', 'PM2_5', 'Temperature'
            print(df.columns)
        except Exception as e:
            st.warning(f"No fue posible obtener datos. Revisa la query Flux. Detalle: {e}")
        else:
            # Last Connection
            try:
                last_time = df['_time'].max()
                last_time_str = last_time.strftime("%Y-%m-%d %H:%M:%S")
                st.sidebar.markdown(f"Últimos datos recibidos: {last_time_str}",width="stretch")
            except:
                st.info("No fue posible obtener la última conexión de datos.")   
        
        with st.sidebar:
            
            # Define available parameters (used across columns)
            available_parameters = ["CO2", "PM2.5", "Temperature"]
            
            auto_refresh_enabled = st.toggle(
                "Actualizar en tiempo real ",
                value=False
            )

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
        
            # Route filter
            if 'location' in df.columns:
                unique_routes = df['location'].dropna().unique().tolist()
                selected_routes = st.multiselect(
                    "Seleccionar las rutas:",
                    options=sorted(unique_routes),
                    default=sorted(unique_routes),
                    key="route_filter"
                )
            else:
                st.info("No hay datos de ruta disponibles")
            
            # Parameters filter - Multiselect
            default_selected = ["PM2.5"]

           
            selected_params = st.multiselect(
                "Parámetros a Mostrar:",
                options=available_parameters,
                default=default_selected,
                key="parameters_filter",
                help="Selecciona los parámetros que deseas visualizar en el mapa"
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
            
        
            filtered_df = filtered_df[filtered_df['location'].isin(selected_routes)]
            
            
            
            # Show filtered results
            if not filtered_df.empty:
                st.sidebar.markdown(f"Mostrando {len(filtered_df):,} registros filtrados de {len(df):,} totales")
                # Handle auto-refresh mode
                if auto_refresh_enabled:
                    # Use the auto-refresh fragment
                    auto_refresh_map(date_range, selected_routes, selected_params)
                else:
                    # Use the normal static map
                    plot_map(filtered_df, selected_params, auto_refresh=False)
            else:
                st.warning("No hay datos que coincidan con los filtros seleccionados.")

        chartSequentialColors = ["#0FA539", "#89b83c", "#d1c958", "#ffdb83"]

        with st.container(key="graphs"):
            with st.container(key="graph1"):
                
                st.html(
                """
                <div style="text-align: center;"> Contaminación promedio por ruta </div>
                """)

                df.rename(columns={"Ruta": "location", "PM2_5": "PM2_5"},
                inplace=True)

                dfchart = df.groupby('Location')['PM2.5'].mean()

                fig = px.bar({'Location': dfchart.index,
                'Average PM2.5': dfchart.values}, x="Location", y="Average PM2.5", color=chartSequentialColors)
                fig.update_traces(showlegend=False)
                st.plotly_chart(fig, use_container_width=True, theme=None)

            with st.container(key="graph2"):
                st.html(
                """
                <div style="text-align: center;"> Contaminación promedio por hora </div>
                """)
                
                df.rename(columns={"_time": "Date-Time", "metrics_0_fields_CO2": "CO2"},
                inplace=True)

                dfchart2 = df.groupby('Date-Time')['CO2'].mean()
                
                fig2 = px.line({'Date-Time': dfchart2.index,
                'Average CO2': dfchart2.values}, x="Date-Time", y="Average CO2")
                st.plotly_chart(fig2, use_container_width=True, theme=None)

if __name__ == "__main__" or st._is_running_with_streamlit:

    main()