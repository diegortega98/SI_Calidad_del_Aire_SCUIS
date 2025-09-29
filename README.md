# Sistema de información basado en IoT para el análisis de la calidad del aire en rutas del transporte público del Área Metropolitana de Bucaramanga
---

## Cómo Ejecutar el Proyecto

### Requisitos Previos

- **Python 3.8+** instalado en el sistema
- **InfluxDB 2.x** ejecutándose en `localhost:8086`
- **Token de autenticación** válido para InfluxDB
- Navegador web moderno
- Desplegar SmartCampus UIS https://github.com/UIS-IoT-Smart-Campus/smart_campus_core_images

### Instalación de Dependencias

1. Abrir terminal en la carpeta del proyecto
2. Instalar las dependencias listadas en `pkgs.txt`:


### Configuración

1. ✅ Verificar que **InfluxDB** esté ejecutándose en `localhost:8086`
2. ✅ Asegurar que el **token de autenticación** sea válido
3. ✅ Verificar que la organización `"smart-campus"` exista
4. ✅ Verificar que el bucket `"messages"` contenga datos

### Ejecución

1. Abrir terminal en la carpeta del proyecto
2. Ejecutar el comando principal:

```bash
streamlit run main_app.py
```

3. El navegador se abrirá automáticamente en `http://localhost:8501`
4. Si no se abre automáticamente, navegar manualmente a esa URL

---

## Estructura de la Aplicación

| Módulo | Descripción |
|--------|-------------|
| **Dashboard Principal** | Monitoreo en tiempo real con mapas 3D interactivos |
| **Análisis Estadístico** | Gráficos y métricas de calidad del aire |
| **Visualización de Datos** | Tablas interactivas con filtros avanzados |

---



## Datos de Calidad del Aire

### Sensores Monitoreados

| Sensor | Descripción | Unidad | Rango Típico |
|--------|-------------|--------|--------------|
| **PM2.5** | Partículas finas | μg/m³ | 0-500 |
| **CO2** | Dióxido de carbono | ppm | 300-5000 |
| **Temperature** | Temperatura ambiente | °C | 15-40 |
| **GPS** | Coordenadas de ubicación | Lat, Lon | Bucaramanga, Colombia |



## Desarrollado por
Diego Andrés Ortega Gelvez -2170079
Jose Fredy Navarro Motta - 2190044
**Universidad Industrial de Santander - SmartCampus UIS**


