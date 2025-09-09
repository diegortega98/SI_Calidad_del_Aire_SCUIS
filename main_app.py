import streamlit as st

st.set_page_config(page_title="Calidad del Aire de Transporte Público del AMB", page_icon=":material/edit:", layout="wide")

about_page = st.Page("pages/home.py", title="Acerca de", icon=":material/quick_reference:")
dashboard_page = st.Page("pages/map.py", title="Mapa", icon=":material/map:")
analytics_page = st.Page("pages/analytics.py", title="Análisis", icon=":material/analytics:")
data_table_page = st.Page("pages/table.py", title="Datos", icon=":material/table_view:")

pg = st.navigation([dashboard_page, analytics_page, data_table_page, about_page])
pg.run()
