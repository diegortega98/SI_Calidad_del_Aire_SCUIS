Sistema de información de calidad del aire
Smart Campus UIS

=========================================
CÓMO EJECUTAR EL PROYECTO
=========================================

REQUISITOS PREVIOS:
------------------
1. Python 3.8 o superior instalado
2. InfluxDB 2.x ejecutándose en localhost:8086
3. Token de autenticación válido para InfluxDB

INSTALACIÓN DE DEPENDENCIAS:
----------------------------
1. Abrir terminal en la carpeta del proyecto
2. Instalar las dependencias listadas en pkgs.txt:
   
   pip install streamlit pandas plotly pydeck influxdb-client python-dotenv

CONFIGURACIÓN:
--------------
1. Verificar que InfluxDB esté ejecutándose en localhost:8086
2. Asegurar que el token de autenticación sea válido
3. Verificar que la organización "smart-campus" exista
4. Verificar que el bucket "messages" contenga datos

EJECUCIÓN:
----------
1. Abrir terminal en la carpeta del proyecto
2. Ejecutar el comando:
   
   streamlit run main_app.py

3. El navegador se abrirá automáticamente en http://localhost:8501
4. Si no se abre automáticamente, navegar manualmente a esa URL

ESTRUCTURA DE LA APLICACIÓN:
----------------------------
- Dashboard principal: Monitoreo en tiempo real con mapas 3D
- Análisis estadístico: Gráficos y métricas de calidad del aire
- Visualización de datos: Tablas interactivas con filtros
- Carga de datos: Interfaz para cargar nuevos datasets

SOLUCIÓN DE PROBLEMAS:
----------------------
- Si hay error de conexión a InfluxDB, verificar que esté ejecutándose
- Si no hay datos, verificar que el bucket "messages" contenga información
- Si la página no carga, verificar que no haya otro proceso usando el puerto 8501
- Para detener la aplicación, usar Ctrl+C en la terminal

DATOS DE CALIDAD DEL AIRE:
--------------------------
- PM2.5: Partículas finas (μg/m³)
- CO2: Dióxido de carbono (ppm)
- Temperature: Temperatura ambiente (°C)
- GPS: Coordenadas de ubicación (Lat, Lon)
- Timestamps: Zona horaria colombiana (UTC-5)

=========================================
