
//Creedenciales para la red 
pub const WIFI_SSID: &str = "PCGato";
pub const WIFI_PASS: &str = "Coca12345";

//Credenciales para el MQTT
pub const MQTT_URL: &str = "mqtt://broker.hivemq.com:1883";
pub const MQTT_CLIENT_ID: &str = "ESP32_PR2A1";
pub const MQTT_USER: &str = "";
pub const MQTT_PASSWORD: &str = "";

//Topics para suscribirse en el MQTT
pub const MQTT_SUB_TOPICS: &[&str] = &[
	"giirob/pr2-A1/devices/camera/data",
	"giirob/pr2-A1/devices/scada/action",
	"giirob/pr2-A1/devices/scada/status",
	"giirob/pr2-A1/devices/amr/status",
	"giirob/pr2-A1/devices/cobot/status",
	"giirob/pr2-A1/system/emergency/action",
	"giirob/pr2-A1/db/pull/response",
];

//Topics para publicar en el MQTT
pub const MQTT_TOPIC_SCADA_STATUS: &str = "giirob/pr2-A1/devices/scada/status";
pub const MQTT_TOPIC_DELTA_ACTION: &str = "giirob/pr2-A1/devices/delta/action";
pub const MQTT_TOPIC_ROBODK_ACTION: &str = "giirob/pr2-A1/devices/robodk/action";
pub const MQTT_TOPIC_AMR_ACTION: &str = "giirob/pr2-A1/devices/amr/action";
pub const MQTT_TOPIC_COBOT_ACTION: &str = "giirob/pr2-A1/devices/cobot/action";
pub const MQTT_TOPIC_DB_PUSH: &str = "giirob/pr2-A1/db/push";
pub const MQTT_TOPIC_DB_PULL: &str = "giirob/pr2-A1/db/pull";
pub const MQTT_SUB_TOPIC_DB_PULL_RESPONSE: &str = "giirob/pr2-A1/db/pull/response";

//Topics para recibir
pub const MQTT_TOPIC_SCADA_ACTION: &str = "giirob/pr2-A1/devices/scada/action";
pub const MQTT_TOPIC_CAMERA_DATA: &str = "giirob/pr2-A1/devices/camera/data";
pub const MQTT_TOPIC_EMERGENCY_ACTION: &str = "giirob/pr2-A1/system/emergency/action";
pub const MQTT_TOPIC_EMERGENCY_STATUS: &str = "giirob/pr2-A1/system/emergency/status";
pub const MQTT_TOPIC_AMR_STATUS: &str = "giirob/pr2-A1/devices/amr/status";
pub const MQTT_TOPIC_COBOT_STATUS: &str = "giirob/pr2-A1/devices/cobot/status";

//Colores válidos
pub const VALID_COLORS: &[&str] = &["red", "green", "yellow", "blue", "white", "orange"];

pub const AMR_TOLVA_THRESHOLD: u64 = 2;
pub const AMR_ARRIVAL_DELAY_SECS: u64 = 10;
pub const AMR_WAREHOUSE_LOCATION: &str = "cobot_pick";

pub const COBOT_PALLET_ID_BASE: u32 = 10;
pub const COBOT_PALLET_COUNT: usize = 6;


//pub const MQTT_PUBLISH_INTERVAL_SECS: u64 = 5;
