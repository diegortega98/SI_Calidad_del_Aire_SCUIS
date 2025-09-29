/*
 * ESP8266 (NodeMCU) -> EMQX (MQTT)
 * Sensores: GPS NEO-M8N, MH-Z19B (CO2), SDS011 (PM2.5), DS18B20 (Temp)
 *
 * Wiring (NodeMCU):
 *  - GPS NEO-M8N: TX->D5(GPIO14), RX->D6(GPIO12), VCC->3V3, GND->GND (9600)
 *  - MH-Z19B: Vin->5V, GND->GND, TX(verde)->D7(GPIO13), RX(azul)->D8(GPIO15) (9600)
 *  - SDS011: TX->D1(GPIO5), RX->D2(GPIO4), VCC->5V, GND->GND (9600)
 *  - DS18B20: VDD->3V3, GND->GND, DQ->D3(GPIO0) con pull-up 4.7k a 3V3
 *  - GND común para TODO. No unir dos 5V de distintas fuentes; solo comparte GND.
 *
 * Publica JSON en topic MQTT: device/messages
 *  header: userUUID, deviceId, timeStamp (UTC ISO-8601), topic, location, shouldRequeue
 *  metrics: CO2, PM2.5, Temperature, Lat, Lon (Lat/Lon = -1 si no hay fix)
 */

#include <ESP8266WiFi.h>
#define MQTT_MAX_PACKET_SIZE 1024
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <SoftwareSerial.h>
#include <time.h>
#include <sys/time.h>

// ===== GPS =====
#include <TinyGPSPlus.h>
SoftwareSerial gpsSerial(D5, D6);   // RX=D5(GPIO14), TX=D6(GPIO12)
TinyGPSPlus gps;

// ===== MH-Z19B (CO2) =====
#include <MHZ19.h>
SoftwareSerial mhzSerial(D7, D8);   // RX=D7(GPIO13), TX=D8(GPIO15)
MHZ19 mhz;

// ===== SDS011 (PM2.5) =====
#include <SdsDustSensor.h>
SoftwareSerial sdsSerial(D1, D2);   // RX=D1(GPIO5), TX=D2(GPIO4)
SdsDustSensor sds(sdsSerial);

// ===== DS18B20 =====
#include <OneWire.h>
#include <DallasTemperature.h>
#define ONE_WIRE_BUS D3              // si molesta al boot, usa D2 y ajusta aquí
OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature dallas(&oneWire);

// ===== Web + EEPROM (Location) =====
#include <ESP8266WebServer.h>
#include <EEPROM.h>
ESP8266WebServer server(80);
const size_t EEPROM_SIZE  = 128;
const size_t LOCATION_MAX = 32;
const int    EEPROM_ADDR_LOC = 0;

// ===== WiFi / MQTT =====
const char* WIFI_SSID   = "redmi123";
const char* WIFI_PASS   = "12345678+";

const char* MQTT_HOST   = "0.tcp.ngrok.io"; // IP/host EMQX
const int   MQTT_PORT   = 11573;             // 1883 sin TLS
const char* MQTT_USER   = "user";          // "" si no usas auth
const char* MQTT_PASSWD = "password";      // "" si no usas auth
const char* MQTT_CLIENT = "esp8266-airclient"; // ID único

const char* MQTT_TOPIC_UP     = "device/messages";
const char* MQTT_TOPIC_STATUS = "device/status"; // LWT + birth

const char* USER_UUID = "1";         // si tu backend lo espera
String LOCATION = "Device test";     // editable por web y persistente

WiFiClient   net;
PubSubClient mqtt(net);

// ===== Utilidades =====
const long TZ_OFFSET_SEC = -5L * 3600;
const char* TZ_OFFSET_STR = "-05:00";
String iso8601LocalNow() {
  struct timeval tv; 
  gettimeofday(&tv, nullptr);
  time_t local = tv.tv_sec + TZ_OFFSET_SEC;
  struct tm* tmp = gmtime(&local);
  struct tm tm_loc;
  if (tmp) tm_loc = *tmp; else memset(&tm_loc, 0, sizeof(tm_loc));

  char buf[40];
  snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%06ld%s",
           tm_loc.tm_year + 1900, tm_loc.tm_mon + 1, tm_loc.tm_mday,
           tm_loc.tm_hour, tm_loc.tm_min, tm_loc.tm_sec, (long)tv.tv_usec,
           TZ_OFFSET_STR);
  return String(buf);
}

void waitForNtp(uint32_t max_ms = 10000) {
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  uint32_t t0 = millis();
  while (millis() - t0 < max_ms) {
    if (time(nullptr) > 1700000000UL) break; // ya hay hora válida
    delay(200);
  }
}

void wifiConnect() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.printf("Conectando WiFi a \"%s\"", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.printf("WiFi OK: %s", WiFi.localIP().toString().c_str());
}

void mqttConnect() {
  mqtt.setServer(MQTT_HOST, MQTT_PORT);

  // LWT JSON (offline)
  StaticJsonDocument<160> will; will["device"] = MQTT_CLIENT; will["status"] = "offline";
  char willBuf[160]; size_t willLen = serializeJson(will, willBuf);
  if (willLen >= sizeof(willBuf)) willLen = sizeof(willBuf) - 1; willBuf[willLen] = ' ';

  while (!mqtt.connected()) {
    Serial.print("MQTT conectando...");
    bool ok = mqtt.connect(
      MQTT_CLIENT,
      MQTT_USER, MQTT_PASSWD,
      MQTT_TOPIC_STATUS,  // LWT topic
      0, true,            // QoS0, retained
      willBuf
    );
    if (ok) {
      Serial.println("OK");
      StaticJsonDocument<160> birth; birth["device"] = MQTT_CLIENT; birth["status"] = "online";
      char birthBuf[160]; size_t n = serializeJson(birth, birthBuf);
      mqtt.publish(MQTT_TOPIC_STATUS, (const uint8_t*)birthBuf, n, true);
    } else {
      Serial.printf("fail rc=%d, retry 5s", mqtt.state());
      delay(5000);
    }
  }
}

// ===== Web/EEPROM (LOCATION) =====
void saveLocationToEEPROM(const String& loc) {
  char buf[LOCATION_MAX]; memset(buf, 0, sizeof(buf));
  loc.substring(0, LOCATION_MAX - 1).toCharArray(buf, LOCATION_MAX);
  EEPROM.put(EEPROM_ADDR_LOC, buf);
  EEPROM.commit();
}

void loadLocationFromEEPROM() {
  char buf[LOCATION_MAX]; EEPROM.get(EEPROM_ADDR_LOC, buf);
  buf[LOCATION_MAX - 1] = ' ';
  if ((uint8_t)buf[0] == 0xFF) buf[0] = ' ';
  if (buf[0] != ' ') LOCATION = String(buf);
}

String htmlIndex() {
  String s;
  s  = F("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>");
  s += F("<title>Device Config</title><style>body{font-family:sans-serif;max-width:520px;margin:24px auto;padding:0 12px}input,button{font-size:16px;padding:8px;border-radius:8px;border:1px solid #999}form{display:grid;gap:8px}</style></head><body>");
  s += F("<h2>Ubicación (LOCATION)</h2><p><b>Actual:</b> ");
  s += (LOCATION.length() ? LOCATION : String("(no definida)"));
  s += F("</p><form method='POST' action='/set'>");
  s += F("<label>Location:<br><input name='location' required value='");
  String esc = LOCATION; esc.replace("\"","&quot;"); s += esc;
  s += F("'></label><button type='submit'>Guardar</button></form><p>IP del ESP: ");
  s += WiFi.localIP().toString();
  s += F("</p></body></html>");
  return s;
}

void handleRoot(){ server.send(200, "text/html", htmlIndex()); }
void handleSet(){
  String loc = server.hasArg("location")? server.arg("location") : server.arg("loc");
  loc.trim(); if (loc.length() > 0) { LOCATION = loc; saveLocationToEEPROM(LOCATION); }
  server.send(200, "text/html", "<html><body style='font-family:sans-serif'><h3>Guardado</h3><a href='/'>&laquo; Volver</a></body></html>");
}

// ===== Lecturas =====
// GPS (no bloqueante)
bool readGPS(double &lat, double &lon) {
  if (gps.location.isValid() && gps.location.age() < 3000) {
    lat = gps.location.lat();
    lon = gps.location.lng();
    return true;
  }
  return false;
}

// CO2 (MH-Z19B)
int readCO2() {
  mhzSerial.listen();
  int co2 = mhz.getCO2();
  return (co2 > 0 && co2 < 10000) ? co2 : -1;
}

// PM2.5 (SDS011)
float readPM25() {
  sdsSerial.listen();
  float pm25 = NAN;
  for (int i = 0; i < 4 && !isfinite(pm25); ++i) {
    auto pm = sds.readPm();
    if (pm.isOk()) pm25 = pm.pm25;
    delay(200);
  }
  if (!isfinite(pm25)) {
    sds.wakeup(); delay(800);
    sds.setActiveReportingMode();
    sds.setContinuousWorkingPeriod();
    auto pm = sds.readPm(); if (pm.isOk()) pm25 = pm.pm25;
  }
  return isfinite(pm25) ? pm25 : -1.0f;
}

// Temp (DS18B20)
float readTemperatureC() {
  dallas.setResolution(12);
  dallas.setWaitForConversion(true);
  const int N = 3; float acc = 0; int ok = 0;
  for (int i = 0; i < N; ++i) {
    dallas.requestTemperatures();
    float t = dallas.getTempCByIndex(0);
    if (t > -55 && t < 125) { acc += t; ok++; }
  }
  if (ok == 0) return -127.0f;
  return acc / ok;
}

// ===== Publicación JSON =====
void publishJson() {
  if (!mqtt.connected()) mqttConnect();

  double lat = -1, lon = -1; bool haveGPS = readGPS(lat, lon);
  int   co2  = readCO2();
  float pm25 = readPM25();
  float temp = readTemperatureC();

  StaticJsonDocument<900> doc;
  JsonObject h = doc.createNestedObject("header");
  h["userUUID"]   = USER_UUID;
  h["deviceId"]   = MQTT_CLIENT;
  h["timeStamp"]  = iso8601LocalNow();
  h["topic"]      = MQTT_TOPIC_UP;
  h["location"]   = LOCATION;
  h["shouldRequeue"] = true;

  JsonArray metrics = doc.createNestedArray("metrics");
  { JsonObject m = metrics.createNestedObject(); m["measurement"] = "CO2";         m["value"] = co2; }
  { JsonObject m = metrics.createNestedObject(); m["measurement"] = "PM2.5";       m["value"] = pm25; }
  { JsonObject m = metrics.createNestedObject(); m["measurement"] = "Temperature"; m["value"] = temp; }
  { JsonObject m = metrics.createNestedObject(); m["measurement"] = "Lat";         m["value"] = haveGPS ? lat : -1; }
  { JsonObject m = metrics.createNestedObject(); m["measurement"] = "Lon";         m["value"] = haveGPS ? lon : -1; }

  char buf[900]; size_t n = serializeJson(doc, buf);
  bool ok = mqtt.publish(MQTT_TOPIC_UP, (const uint8_t*)buf, n, false);

  Serial.println(F("----- MQTT PUBLISH -----"));
  Serial.println(buf);
  Serial.println(ok ? F("[STATUS] Published OK") : F("[STATUS] Publish FAILED"));
}

// ===== Setup / Loop =====
void setup() {
  Serial.begin(115200); delay(150);
  Serial.println("== ESP8266 + GPS + MH-Z19B + SDS011 + DS18B20 -> EMQX ==");

  // Inicializa sensores
  gpsSerial.begin(9600);

  mhzSerial.begin(9600);
  mhz.begin(mhzSerial);
  mhz.autoCalibration(false);

  sdsSerial.begin(9600);
  sds.begin(); sds.wakeup(); delay(1200);
  sds.setActiveReportingMode();
  sds.setContinuousWorkingPeriod();

  dallas.begin();

  // WiFi + Tiempo + MQTT
  wifiConnect();
  waitForNtp(10000);
  mqtt.setBufferSize(1024);
  mqtt.setKeepAlive(30);
  mqtt.setSocketTimeout(5);
  mqttConnect();

  // Web UI Location
  EEPROM.begin(EEPROM_SIZE);
  loadLocationFromEEPROM();
  server.on("/", handleRoot);
  server.on("/set", HTTP_POST, handleSet);
  server.begin();
  Serial.println(String("[WEB] Abre: http://") + WiFi.localIP().toString() + "/");
}

void loop() {
  server.handleClient();

  if (!mqtt.connected()) mqttConnect();
  mqtt.loop();

  // Alimenta el parser de GPS continuamente
  if (!gpsSerial.isListening()) gpsSerial.listen();
  while (gpsSerial.available()) gps.encode(gpsSerial.read());

  static unsigned long t0 = 0;
  if (millis() - t0 > 10000UL) { // cada 10 s
    publishJson();
    t0 = millis();
  }
}
