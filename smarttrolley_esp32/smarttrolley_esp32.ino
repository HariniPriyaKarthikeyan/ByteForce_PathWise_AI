/*
 * SmartTrolley AI - STAGE 2: WI-FI MOTOR CONTROL
 * ----------------------------------------------
 * ESP32 makes its own hotspot and answers simple web commands.
 *
 *   Network : SmartTrolley
 *   Password: Trolley123
 *   ESP32 IP: 192.168.4.1
 *
 *   http://192.168.4.1/forward
 *   http://192.168.4.1/backward
 *   http://192.168.4.1/left
 *   http://192.168.4.1/right
 *   http://192.168.4.1/stop
 *   http://192.168.4.1/status      (last command + time since)
 *
 * SAFETY: if no command arrives for 1000 ms the motors stop.
 * This is the same timeout the Python app relies on.
 *
 * Board: ESP32 DevKit V1 | Core 2.0.17 | Tools > Board "ESP32 Dev Module"
 * Serial Monitor: 115200 baud
 */

#include <WiFi.h>
#include <WebServer.h>

const char* AP_SSID = "SmartTrolley";
const char* AP_PASS = "Trolley123";

const int IN1 = 23;
const int IN2 = 22;
const int IN3 = 14;
const int IN4 = 13;

const unsigned long COMMAND_TIMEOUT_MS = 1000;

WebServer server(80);

String lastCommand = "none";
unsigned long lastCommandAt = 0;
bool moving = false;

void allStop() {
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW);
  digitalWrite(IN4, LOW);
  moving = false;
}

void drive(const String& cmd) {
  if (cmd == "forward") {
    digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
    digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
    moving = true;
  } else if (cmd == "backward") {
    digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH);
    digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH);
    moving = true;
  } else if (cmd == "left") {
    digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH);
    digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
    moving = true;
  } else if (cmd == "right") {
    digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
    digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH);
    moving = true;
  } else {  // "stop" or anything unknown
    allStop();
  }
  lastCommand = cmd;
  lastCommandAt = millis();
}

void handleCommand(const String& cmd) {
  drive(cmd);
  Serial.print("HTTP /");
  Serial.print(cmd);
  Serial.print("  from ");
  Serial.println(server.client().remoteIP());

  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "text/plain", "OK " + cmd);
}

void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  allStop();                 // never boot with motors running

  Serial.println();
  Serial.println("=== SmartTrolley STAGE 2 Wi-Fi control ===");

  WiFi.mode(WIFI_AP);
  bool ok = WiFi.softAP(AP_SSID, AP_PASS);
  Serial.println(ok ? "Hotspot created" : "Hotspot FAILED");
  Serial.print("Network : "); Serial.println(AP_SSID);
  Serial.print("Password: "); Serial.println(AP_PASS);
  Serial.print("Open in browser: http://");
  Serial.println(WiFi.softAPIP());

  server.on("/", []() {
    server.send(200, "text/html",
      "<h2>SmartTrolley</h2>"
      "<p><a href='/forward'>forward</a> | <a href='/backward'>backward</a> | "
      "<a href='/left'>left</a> | <a href='/right'>right</a> | "
      "<a href='/stop'>stop</a> | <a href='/status'>status</a></p>");
  });

  server.on("/forward",  []() { handleCommand("forward");  });
  server.on("/backward", []() { handleCommand("backward"); });
  server.on("/left",     []() { handleCommand("left");     });
  server.on("/right",    []() { handleCommand("right");    });
  server.on("/stop",     []() { handleCommand("stop");     });

  server.on("/status", []() {
    String s = "last=" + lastCommand +
               " ago_ms=" + String(millis() - lastCommandAt) +
               " moving=" + String(moving ? "yes" : "no") +
               " clients=" + String(WiFi.softAPgetStationNum());
    server.send(200, "text/plain", s);
  });

  server.onNotFound([]() {
    server.send(404, "text/plain", "unknown command");
  });

  server.begin();
  Serial.println("Server started. Waiting for commands...");
}

void loop() {
  server.handleClient();

  // Dead-man switch: stop if commands stop arriving
  if (moving && millis() - lastCommandAt > COMMAND_TIMEOUT_MS) {
    allStop();
    Serial.println("Timeout - motors stopped");
  }
}
