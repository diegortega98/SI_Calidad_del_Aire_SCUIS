import streamlit as st
import pathlib

st.set_page_config(page_title="Calidad del Aire de Transporte Público del AMB", page_icon=":material/edit:", layout="wide")

def load_css(file_path):
    with open(file_path) as f:
        st.html(f"<style>{f.read()}</style>")

css_path = pathlib.Path("assets/styles.css")
load_css(css_path)

about_page = st.Page("pages/home.py", title="Acerca de", icon=":material/quick_reference:")
dashboard_page = st.Page("pages/map.py", title="Mapa", icon=":material/map:")
analytics_page = st.Page("pages/analytics.py", title="Análisis", icon=":material/analytics:")
data_table_page = st.Page("pages/table.py", title="Datos", icon=":material/table_view:")


pg = st.navigation([about_page, dashboard_page, analytics_page, data_table_page])
pg.run()
