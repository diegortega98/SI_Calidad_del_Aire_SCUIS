# connection.py
import os
import time
from typing import Optional
import influxdb_client
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
import dotenv
import pandas as pd
from utils.timezone_utils import convert_to_colombia_time

# --------- Config ---------

dotenv.load_dotenv()
  # Carga variables de entorno desde .env
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "smartcampusuis-iot-auth-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "smart-campus")
DEFAULT_BUCKET = os.getenv("INFLUX_BUCKET", "messages")

# --------- Excepciones ---------
class ConnectionNotReady(Exception):
    """La conexión no está lista (aún)."""

# --------- Cliente (sin UI) ---------
def _new_client() -> InfluxDBClient:
    """
    Crea el cliente 
    """
    return influxdb_client.InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
        timeout=30_000,  
        enable_gzip=True
    )

def ping(client: InfluxDBClient) -> bool:
    """
    Verifica que el servidor responda.
    """
    
    try:
        if not client.ping():
            return False
        # Consulta para validar la conexión:
        q = 'buckets() |> limit(n:1)'
        _ = client.query_api().query(q)
        return True
    except Exception:
        return False

def wait_until_ready(
    max_wait_seconds: int = 10,
    interval_seconds: float = 1.0
) -> InfluxDBClient:
    """
    Reintentar conexión.
    """
    client = _new_client()
    deadline = time.time() + max_wait_seconds
    while time.time() < deadline:
        if ping(client):
            return client
        time.sleep(interval_seconds)
    raise ConnectionNotReady("InfluxDB no está listo aún.")

# --------- API de alto nivel para páginas ---------
def get_client_or_raise() -> InfluxDBClient:
    
    client = _new_client()
    if not ping(client):
        raise ConnectionNotReady("No fue posible validar la conexión con InfluxDB.")
    return client

def run_query(client: InfluxDBClient, flux: str):
    """
    Ejecuta una query Flux y convierte timestamps a zona horaria colombiana
    """
    df = client.query_api().query_data_frame(flux)
    # Convert timestamps to Colombian timezone
    df = convert_to_colombia_time(df)
    return df


def flux_query(bucket: Optional[str] = None, start: str = "-1h") -> str:
    """
    Construye un Flux para obtener TODAS las métricas disponibles sin ningún filtro de measurement.
    """
    bucket = bucket or DEFAULT_BUCKET
    
    return f'''
  from(bucket: "{bucket}")
  |> range(start: {start})
  |> filter(fn: (r) =>
    r._measurement == "CO2" or
    r._measurement == "PM2.5" or
    r._measurement == "Temperature" or
    r._measurement == "Lat" or
    r._measurement == "Lon"
  )
  |> aggregateWindow(every: 10s, fn: last, createEmpty: false)
  |> pivot(
      rowKey: ["_time","location"],
      columnKey: ["_measurement"],
      valueColumn: "_value"
  )
  |> keep(columns: ["_time","location","Lat","Lon","CO2","Temperature","PM2.5"])
  |> sort(columns: ["location","_time"])
  '''

if __name__ == "__main__":
    client = get_client_or_raise()
    flux = flux_query(start="-1h")
    print("Ejecutando query...")
    df = run_query(client, flux)
    print(f"Datos obtenidos: {len(df)} filas")
    print(df.head())
    df.to_csv("sample_data.csv", index=False)