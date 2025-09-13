# connection.py
import os
import time
from typing import Optional
import influxdb_client
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError

# --------- Config ---------
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "smartcampusuis-iot-auth-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "uis")
DEFAULT_BUCKET = os.getenv("INFLUX_BUCKET", "iotuis")

# --------- Excepciones ---------
class ConnectionNotReady(Exception):
    """La conexión no está lista (aún)."""

# --------- Cliente (sin UI) ---------
def _new_client() -> InfluxDBClient:
    """
    Crea el cliente sin efectos secundarios de UI.
    """
    return influxdb_client.InfluxDBClient(
        url=INFLUX_URL,
        token=INFLUX_TOKEN,
        org=INFLUX_ORG,
        timeout=30_000,  # ms
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
    Ejecuta una query Flux
    """
    return client.query_api().query_data_frame(flux)

def flux_select(fields: list[str], bucket: Optional[str] = None, start: str = "-1h") -> str:
    """
    Construye un Flux básico de ejemplo (ajústalo a tu estilo).
    """
    bucket = bucket or DEFAULT_BUCKET
    fields_filter = " or ".join([f'r["_field"] == "{f}"' for f in fields])
    return f'''
    from(bucket: "{bucket}")
    |> range(start: {start})
    |> filter(fn: (r) => {fields_filter})
    |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
    '''
