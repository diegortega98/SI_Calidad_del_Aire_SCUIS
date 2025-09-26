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
    client = get_cached_client( )
    return run_query(client, flux)

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
                last_time_str = last_time.strftime("%Y-%m-%d %H:%M:%S")
                st.sidebar.markdown(f"Últimos datos recibidos: {last_time_str}",width="stretch")
            except:
                st.info("No fue posible obtener la última conexión de datos.")   

    if 'df' in locals() and not df.empty:
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
            
            # Display cards in columns
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric(
                    label="Hora Más Peligrosa",
                    value=f"{most_dangerous_hour}:00",
                    delta=f"{max_pm25_value:.1f} μg/m³"
                )
            
            with col2:
                st.metric(
                    label="Ruta Más Contaminada",
                    value=most_contaminated_route,
                    delta=f"{max_route_pm25:.1f} μg/m³"
                )
            
            with col3:
                st.metric(
                    label="Ruta Menos Contaminada", 
                    value=least_contaminated_route,
                    delta=f"{min_route_pm25:.1f} μg/m³"
                )
            
            with col4:
                st.metric(
                    label="Categoría Más Común",
                    value=most_common_category,
                    delta=f"{category_percentage:.1f}% de mediciones"
                )
                
        except Exception as e:
            st.warning(f"No se pudieron calcular los indicadores clave: {e}")
        
        st.markdown("---")
        
        # Two-column layout for pie chart and daily stats
        col_pie, col_daily = st.columns(2)
        
        with col_pie:
            try:
                st.markdown("#### Distribución de Categorías")

                # Calculate category distribution
                category_counts = df['pm25_category'].value_counts()

                dfchart = df.groupby('location')['PM2.5'].mean().sort_values(ascending=True)

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
                
                route_colors = get_route_colors(dfchart.values)
                
                # Create pie chart
                fig_pie = px.pie(
                    values=category_counts.values,
                    names=category_counts.index,
                    title="", 
                    color_discrete_sequence=route_colors
                )
                
                # Update layout for better appearance in column
                fig_pie.update_traces(textposition='inside', textinfo='percent+label')
                fig_pie.update_layout(
                    showlegend=True,
                    height=400,
                    margin=dict(t=20, b=20, l=20, r=20)
                )
                
                st.plotly_chart(fig_pie, use_container_width=True, theme=None, key="pie_categories")
                
            except Exception as e:
                st.warning(f"No se pudo generar el gráfico de categorías: {e}")
        
        with col_daily:
            try:
                st.markdown("#### Estadísticas Diarias")
                
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

    with st.container(key="graphs"):
        with st.container(key="graph1"):
            
            st.html(
            """
            <div style="text-align: center;"> Coordenadas con concentraciones más altas </div>
            """)


            dfchart3 = df.groupby('location')['PM2.5'].mean()

            fig3 = px.bar({'Ubicación': dfchart3.index,
            'Promedio PM2.5': dfchart3.values}, x="Ubicación",y="Promedio PM2.5")
            st.plotly_chart(fig3, use_container_width=True, theme=None, key="fig3")

        with st.container(key="graph2"):
            st.html(
            """
            <div style="text-align: center;"> Contaminación por día </div>
            """)

            dfchart4 = df.groupby('_time')['CO2'].mean()
            
            fig4 = px.line({'Tiempo': dfchart4.index,
            'Promedio CO2': dfchart4.values}, x="Tiempo",y="Promedio CO2")
            st.plotly_chart(fig4, use_container_width=True, theme=None, key="fig4")

    with st.container(key="graphsx"):
        with st.container(key="graphx1"):
            
            st.html(
            """
            <div style="text-align: center;"> Coordenadas con concentraciones más altas </div>
            """)

           
            dfchart5 = df.groupby('location')['PM2.5'].mean()

            fig5 = px.bar({'Ubicación': dfchart5.index,
            'Promedio PM2.5': dfchart5.values}, x="Ubicación",y="Promedio PM2.5")
            st.plotly_chart(fig5, use_container_width=True, theme=None, key="fig5")

        with st.container(key="graphx2"):
            st.html(
            """
            <div style="text-align: center;"> Contaminación por día </div>
            """)
            
            dfchart6 = df.groupby('_time')['CO2'].mean()
            
            fig6 = px.line({'Tiempo': dfchart6.index,
            'Promedio CO2': dfchart6.values}, x="Tiempo",y="Promedio CO2")
            st.plotly_chart(fig6, use_container_width=True, theme=None, key="fig6")

if __name__ == "__main__" or st._is_running_with_streamlit:

    main()
