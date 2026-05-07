// Wi-Fi
pub const WIFI_SSID: &str = "PCGato";
pub const WIFI_PASS: &str = "Coca12345";

// MQTT
pub const MQTT_URL: &str       = "mqtt://broker.hivemq.com:1883";
pub const MQTT_CLIENT_ID: &str = "ESP32_DEMO_INTEGRACION";
pub const MQTT_USER: &str      = "";
pub const MQTT_PASSWORD: &str  = "";

// Topics suscritos por el ESP32
pub const MQTT_SUB_TOPICS: &[&str] = &[
    "giirob/pr2-A1/devices/amr/status",
    "giirob/pr2-A1/devices/cobot/status",
    "giirob/pr2-A1/devices/camera/data",
    "giirob/pr2-A1/db/pull/response",
];

// Topics publicados por el ESP32
pub const TOPIC_COBOT_ACTION:   &str = "giirob/pr2-A1/devices/cobot/action";
pub const TOPIC_ROBODK_ACTION:  &str = "giirob/pr2-A1/devices/robodk/action";
pub const TOPIC_DB_PUSH:        &str = "giirob/pr2-A1/db/push";
pub const TOPIC_DB_PULL:        &str = "giirob/pr2-A1/db/pull";

// Localización del cobot dentro del sistema AMR
pub const AMR_COBOT_LOCATION: &str = "cobot_pick";

// Pallet ID base y capacidad maxima de cajas por pallet
pub const PALLET_ID_BASE:  u32 = 10;
pub const PALLET_CAPACITY: u32 = 2;
