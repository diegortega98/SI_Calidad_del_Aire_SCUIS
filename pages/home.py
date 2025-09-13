import streamlit as st

st.set_page_config(layout="wide")

st.html("""

<div class="hero-section">
    <h1 style="margin: 0; font-size: 36px;">Dashboard de Calidad del Aire</h1>
    <h2 style="margin: 10px 0 0 0; font-size: 20px; opacity: 1;"> Sistema de información basado en IoT para el análisis de la calidad del aire en rutas del transporte público del Área Metropolitana de Bucaramanga
</h2>
</div>
""")

col1, col2, col3 = st.columns(3)

with col1:
    if st.button("Visualización geográfica", use_container_width=True):
        st.switch_page("pages/map.py")

with col2:
    if st.button("Análisis estadístico", use_container_width=True):
        st.switch_page("pages/analytics.py")

with col3:
    if st.button("Tabla de datos", use_container_width=True):
        st.switch_page("pages/table.py")

