# 🌍 Sistema de Información de Calidad del Aire
**Smart Campus UIS**

---

## 🚀 Cómo Ejecutar el Proyecto

### 📋 Requisitos Previos

- **Python 3.8+** instalado en el sistema
- **InfluxDB 2.x** ejecutándose en `localhost:8086`
- **Token de autenticación** válido para InfluxDB
- Navegador web moderno

### 📦 Instalación de Dependencias

1. Abrir terminal en la carpeta del proyecto
2. Instalar las dependencias listadas en `pkgs.txt`:

```bash
pip install streamlit pandas plotly pydeck influxdb-client python-dotenv
```

### ⚙️ Configuración

1. ✅ Verificar que **InfluxDB** esté ejecutándose en `localhost:8086`
2. ✅ Asegurar que el **token de autenticación** sea válido
3. ✅ Verificar que la organización `"smart-campus"` exista
4. ✅ Verificar que el bucket `"messages"` contenga datos

### 🎯 Ejecución

1. Abrir terminal en la carpeta del proyecto
2. Ejecutar el comando principal:

```bash
streamlit run main_app.py
```

3. El navegador se abrirá automáticamente en `http://localhost:8501`
4. Si no se abre automáticamente, navegar manualmente a esa URL

---

## 📊 Estructura de la Aplicación

| Módulo | Descripción |
|--------|-------------|
| **🗺️ Dashboard Principal** | Monitoreo en tiempo real con mapas 3D interactivos |
| **📈 Análisis Estadístico** | Gráficos y métricas de calidad del aire |
| **📋 Visualización de Datos** | Tablas interactivas con filtros avanzados |
| **📤 Carga de Datos** | Interfaz para cargar nuevos datasets |

---

## 🔧 Solución de Problemas

| Problema | Solución |
|----------|----------|
| ❌ Error de conexión a InfluxDB | Verificar que esté ejecutándose en puerto 8086 |
| ❌ No hay datos en el mapa | Verificar que el bucket `"messages"` contenga información |
| ❌ La página no carga | Verificar que no haya otro proceso usando el puerto 8501 |
| ❌ Aplicación no responde | Usar `Ctrl+C` en la terminal para detener |

---

## 📡 Datos de Calidad del Aire

### Sensores Monitoreados

| Sensor | Descripción | Unidad | Rango Típico |
|--------|-------------|--------|--------------|
| **PM2.5** | Partículas finas | μg/m³ | 0-500 |
| **CO2** | Dióxido de carbono | ppm | 300-5000 |
| **Temperature** | Temperatura ambiente | °C | 15-40 |
| **GPS** | Coordenadas de ubicación | Lat, Lon | Bucaramanga, Colombia |

### 🕐 Zona Horaria
Todos los timestamps están en **zona horaria colombiana (UTC-5)**

---

## 🎨 Características Técnicas

- ✅ **Mapas 3D interactivos** con PyDeck
- ✅ **Tiempo real** con auto-refresh cada 5 segundos
- ✅ **Filtros avanzados** por fecha, hora, ruta y calidad del aire
- ✅ **Visualizaciones EPA** con categorías estándar de contaminación
- ✅ **Tooltips informativos** con datos completos de sensores
- ✅ **Rutas de contaminación** conectando puntos temporalmente
- ✅ **Análisis estadístico** con gráficos interactivos

---

## 🌟 Desarrollado por
**Universidad Industrial de Santander - Smart Campus Initiative**
