use anyhow::Result;
use embedded_svc::mqtt::client::QoS;
use esp_idf_svc::nvs::EspDefaultNvsPartition;
use esp_idf_svc::mqtt::client::{EspMqttClient, EventPayload, MqttClientConfiguration};
use log::{error, info};
use serde_json::Value;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::SyncSender,
        Arc, Mutex,
    },
    thread,
    time::Duration,
};

use crate::{
    config,
    control_state::{ControlState, Mode, ExpectedTapa},
};

//Estructura que almacena al cliente MQTT
pub struct MqttManager<'a> {
    client: EspMqttClient<'a>,
}

//Definicion de métodos y funciones para la gestión del cliente MQTT
impl<'a> MqttManager<'a> {
    //Función de conexión y suscripción a tópicos MQTT, con manejo de eventos para procesar los mensajes recibidos y actualizar el estado de control o activar la parada de emergencia según corresponda.
    pub fn connect_and_subscribe_with_state(
        control_state: Arc<Mutex<ControlState>>,
        emergency_stop: Arc<AtomicBool>,
        vision_tx: SyncSender<String>,
        nvs: EspDefaultNvsPartition,
    ) -> Result<Self> {

        //Configuración de creedenciales MQTT.
        let mqtt_user = if config::MQTT_USER.is_empty() {
            None
        } else {
            Some(config::MQTT_USER)
        };
        let mqtt_password = if config::MQTT_PASSWORD.is_empty() {
            None
        } else {
            Some(config::MQTT_PASSWORD)
        };

        //Configuración de cliente MQTT.
        let cfg = MqttClientConfiguration {
            client_id: Some(config::MQTT_CLIENT_ID),
            username: mqtt_user,
            password: mqtt_password,
            ..Default::default()
        };
        
        //Creación de cliente MQTT con callback para manejo de eventos.
        let nvs = Arc::new(nvs);
        let mut client = EspMqttClient::new_cb(config::MQTT_URL, &cfg, move |event| match event.payload() {
            //Log de eventos relevantes.
            EventPayload::Connected(_) => info!("MQTT conectado al servidor"),
            EventPayload::Subscribed(id) => info!("Suscrito con ID: {}", id),
            
            //Log de mensajes recibidos con procesamiento de mensaje según topico y mensaje
            EventPayload::Received { topic, data, .. } => {
                let mensaje = std::str::from_utf8(data).unwrap_or("");
                let topic_recibido = topic.unwrap_or("");

                match topic_recibido {
                    config::MQTT_TOPIC_SCADA_STATUS => {
                        handle_scada_status_message(mensaje, &control_state, &nvs);
                    }
                    config::MQTT_TOPIC_SCADA_ACTION => {
                        if emergency_stop.load(Ordering::SeqCst) {
                            info!("Sistema en emergencia, ignorando comando SCADA");
                            return;
                        }
                        
                        info!("SCADA ordena: {}", mensaje);
                        
                        if let Ok(value) = serde_json::from_str::<Value>(mensaje) {
                            let cmd = value.get("cmd").and_then(|v| v.as_str()).unwrap_or("");

                            if cmd.eq_ignore_ascii_case("status") {
                                if let Ok(mut state) = control_state.try_lock() {
                                    state.status_requested = true;
                                } else {
                                    error!("No se pudo lockear control_state para status");
                                }
                                return;
                            }

                            if cmd.eq_ignore_ascii_case("set_mode") {
                                let mode_str = value.get("mode")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("");

                                if let Ok(mut state) = control_state.try_lock() {
                                    if mode_str.eq_ignore_ascii_case("AUTO") {
                                        info!("Activando modo AUTO");
                                        state.mode = Mode::Auto;
                                    } else if mode_str.eq_ignore_ascii_case("MANUAL") {
                                        info!("Activando modo MANUAL");
                                        state.mode = Mode::Manual;
                                    }
                                } else {
                                    error!("No se pudo lockear control_state para set_mode");
                                }
                                return;
                            }

                            if cmd.eq_ignore_ascii_case("gen") {
                                let quantity = value.get("quantity")
                                    .and_then(|v| v.as_u64())
                                    .unwrap_or(0) as u32;
                                let lote_id = value
                                    .get("lote_id")
                                    .and_then(|v| v.as_str())
                                    .or_else(|| value.get("lote").and_then(|v| v.as_str()))
                                    .unwrap_or("");

                                if let Ok(mut state) = control_state.try_lock() {
                                    let lote_value = if lote_id.is_empty() {
                                        None
                                    } else {
                                        Some(lote_id.to_string())
                                    };

                                    if state.mode == Mode::Auto {
                                        info!("Generando lote AUTO de {} tapas", quantity);
                                        state.auto_target = quantity;
                                        state.auto_spawned = 0;
                                        state.auto_validated = 0;
                                        state.lote_id = lote_value;
                                        state.expected_tapa = None;
                                    } else if state.mode == Mode::Manual {
                                        let color_str = value.get("color")
                                            .and_then(|v| v.as_str())
                                            .unwrap_or("red");

                                        if !config::VALID_COLORS.contains(&color_str) {
                                            error!("Color inválido recibido: {}", color_str);
                                            return;
                                        }

                                        info!("Generando MANUAL: color={}, cantidad=1", color_str);
                                        state.manual_remaining = 1;
                                        state.manual_color = color_str.to_string();
                                        state.manual_spawn_pending = true;
                                        state.lote_id = lote_value;
                                        state.expected_tapa = Some(ExpectedTapa {
                                            color: color_str.to_string(),
                                            validated: false,
                                        });
                                    }
                                } else {
                                    error!("No se pudo lockear control_state para gen");
                                }
                                return;
                            }

                            if cmd.eq_ignore_ascii_case("reset") {
                                info!("SCADA ordenó reset de tolvas");
                                if let Ok(mut state) = control_state.try_lock() {
                                    state.reset_tolva_counts();
                                    state.pending_tolva_counts = [0; 6];
                                    state.pending_tapas.clear();
                                    state.amr_pending_tolva = None;
                                    state.amr_arrived_tolva = None;
                                    state.amr_arrived_at = None;
                                    state.amr_caja_id = None;
                                    state.amr_caja_tolva = None;
                                    state.cobot_ready = false;
                                    state.cobot_in_progress = false;
                                    state.auto_target = 0;
                                    state.auto_spawned = 0;
                                    state.auto_validated = 0;
                                    state.lote_id = None;

                                    if let Err(err) = state.save_tolva_counts(&nvs) {
                                        error!("No se pudo guardar tolvas en NVS tras reset: {:?}", err);
                                    } else {
                                        info!("Tolvas reseteadas y guardadas en NVS");
                                    }
                                } else {
                                    error!("No se pudo lockear control_state para reset tolvas");
                                }
                                return;
                            }
                        }
                    }
                    
                    config::MQTT_TOPIC_CAMERA_DATA => {
                        // Cámara virtual detectó una tapa
                        info!("Cámara virtual detectó tapa: {}", mensaje);
                        let _ = vision_tx.try_send(mensaje.to_string());
                    }


                    
                    config::MQTT_TOPIC_EMERGENCY_ACTION => {
                        // ¡PARADA INMEDIATA!
                        error!("EMERGENCIA RECIBIDA POR MQTT");
                        if let Ok(value) = serde_json::from_str::<Value>(mensaje) {
                            let cmd = value.get("cmd").and_then(|v| v.as_str()).unwrap_or("");
                            if cmd.eq_ignore_ascii_case("estop") {
                                emergency_stop.store(true, Ordering::SeqCst);
                            } else if cmd.eq_ignore_ascii_case("resume") {
                                emergency_stop.store(false, Ordering::SeqCst);
                            }
                        } else {
                            error!("EMERGENCIA action sin JSON valido: {}", mensaje);
                        }
                    }
                    config::MQTT_TOPIC_AMR_STATUS => {
                        handle_amr_status_message(mensaje, &control_state);
                    }
                    config::MQTT_TOPIC_COBOT_STATUS => {
                        handle_cobot_status_message(mensaje, &control_state);
                    }
                    
                    _ => info!("Mensaje en topic no gestionado: {}", topic_recibido),
                }
            }
            _ => {}
        })?;

        info!("Esperando conexion al broker...");
        thread::sleep(Duration::from_secs(5));

        subscribe_all_topics(&mut client, config::MQTT_SUB_TOPICS);

        Ok(Self { client })
    }

    pub fn publish_text(&mut self, topic: &str, payload: &str) {
        if let Err(e) = self.client.publish(topic, QoS::AtLeastOnce, false, payload.as_bytes()) {
            error!("Error al publicar en {}: {:?}", topic, e);
        } else {
            info!("Publicado en {}: {}", topic, payload);
        }
    }
}

fn subscribe_all_topics(client: &mut EspMqttClient<'_>, topics: &[&str]) {
    for &topic in topics {
        loop {
            match client.subscribe(topic, QoS::AtLeastOnce) {
                Ok(_) => {
                    info!("Suscrito a {}", topic);
                    break;
                }
                Err(e) => {
                    error!("Error al suscribirse a {}: {:?}. Reintentando...", topic, e);
                    thread::sleep(Duration::from_secs(2));
                }
            }
        }
    }
}

fn handle_scada_status_message(
    mensaje: &str,
    control_state: &Arc<Mutex<ControlState>>,
    nvs: &EspDefaultNvsPartition,
) {
    // Espera un mensaje con "cmd" == "done" y un campo "tolva": "TOLVA_#"
    if let Ok(value) = serde_json::from_str::<Value>(mensaje) {
        let cmd = value.get("cmd").and_then(|v| v.as_str()).unwrap_or("");
        if !cmd.eq_ignore_ascii_case("done") && !cmd.eq_ignore_ascii_case("completed") {
            return;
        }

        let cap_id = value.get("cap_id").and_then(|v| v.as_str()).unwrap_or("");
        if cap_id.is_empty() {
            error!("SCADA_STATUS sin cap_id: {}", mensaje);
            return;
        }

        let tolva = value.get("tolva").and_then(|v| v.as_str()).unwrap_or("");
        if let Some(index) = parse_tolva_index(tolva) {
            if let Ok(mut state) = control_state.try_lock() {
                match state.pending_tapas.remove(cap_id) {
                    Some(expected_index) if expected_index == index => {
                        if state.pending_tolva_counts[index] > 0 {
                            state.pending_tolva_counts[index] -= 1;
                            state.tolva_counts[index] += 1;

                            if let Err(err) = state.save_tolva_counts(nvs) {
                                error!("No se pudo guardar tolvas en NVS: {:?}", err);
                            }
                        } else {
                            error!("Confirmacion sin pendientes para {}", tolva);
                        }
                    }
                    Some(expected_index) => {
                        error!(
                            "cap_id {} esperaba TOLVA_{}, pero llego {}",
                            cap_id,
                            expected_index + 1,
                            tolva
                        );
                        state.pending_tapas.insert(cap_id.to_string(), expected_index);
                    }
                    None => {
                        error!("cap_id {} no encontrado en pendientes", cap_id);
                    }
                }
            } else {
                error!("No se pudo lockear control_state para actualizar tolva");
            }
        } else {
            error!("Tolva inválida en SCADA_STATUS: {}", tolva);
        }
    } else if mensaje.to_ascii_lowercase().contains("cmd") {
        error!("SCADA_STATUS sin JSON válido: {}", mensaje);
    }
}

fn parse_tolva_index(tolva: &str) -> Option<usize> {
    let trimmed = tolva.trim();
    let num_str = trimmed.strip_prefix("TOLVA_")?;
    let num = num_str.parse::<usize>().ok()?;
    if (1..=6).contains(&num) {
        Some(num - 1)
    } else {
        None
    }
}



fn handle_amr_status_message(mensaje: &str, control_state: &Arc<Mutex<ControlState>>) {
    if let Ok(value) = serde_json::from_str::<Value>(mensaje) {
        let status = value.get("status").and_then(|v| v.as_str()).unwrap_or("");
        if !status.eq_ignore_ascii_case("ARRIVED") {
            return;
        }

        let location = value.get("location").and_then(|v| v.as_str()).unwrap_or("");
        if location.eq_ignore_ascii_case(config::AMR_WAREHOUSE_LOCATION) {
            if let Ok(mut state) = control_state.try_lock() {
                state.cobot_ready = true;
            } else {
                error!("No se pudo lockear control_state para AMR cobot_pick");
            }
            return;
        }
        if let Some(index) = parse_amr_location_index(location) {
            if let Ok(mut state) = control_state.try_lock() {
                let caja_id = value.get("caja_id").and_then(|v| v.as_str()).unwrap_or("");
                match state.amr_pending_tolva {
                    Some(pending_index) if pending_index == index => {
                        state.amr_arrived_tolva = Some(index);
                        state.amr_arrived_at = Some(std::time::Instant::now());
                        if !caja_id.is_empty() {
                            state.amr_caja_id = Some(caja_id.to_string());
                            state.amr_caja_tolva = Some(index);
                        }
                    }
                    Some(pending_index) => {
                        error!(
                            "AMR llego a {}, pero se esperaba tolva {}",
                            location,
                            pending_index + 1
                        );
                    }
                    None => {
                        error!("AMR llego a {} sin tolva pendiente", location);
                    }
                }
            } else {
                error!("No se pudo lockear control_state para AMR status");
            }
        } else {
            error!("Location AMR invalida: {}", location);
        }
    } else {
        error!("AMR status sin JSON valido: {}", mensaje);
    }
}

fn parse_amr_location_index(location: &str) -> Option<usize> {
    let normalized = location.trim().to_ascii_lowercase();
    let num_str = normalized.strip_prefix("tolva_")?;
    let num = num_str.parse::<usize>().ok()?;
    if (1..=6).contains(&num) {
        Some(num - 1)
    } else {
        None
    }
}

fn handle_cobot_status_message(mensaje: &str, control_state: &Arc<Mutex<ControlState>>) {
    if let Ok(value) = serde_json::from_str::<Value>(mensaje) {
        let status = value.get("status").and_then(|v| v.as_str()).unwrap_or("");
        if !status.eq_ignore_ascii_case("FINISHED") {
            return;
        }

        let id_pallet = value.get("id_pallet").and_then(|v| v.as_u64());
        if let Some(id) = id_pallet {
            let index = id as i64 - config::COBOT_PALLET_ID_BASE as i64;
            if index >= 0 && (index as usize) < config::COBOT_PALLET_COUNT {
                if let Ok(mut state) = control_state.try_lock() {
                    state.pallet_counts[index as usize] += 1;
                    state.cobot_in_progress = false;
                } else {
                    error!("No se pudo lockear control_state para cobot status");
                }
            } else {
                error!("id_pallet fuera de rango: {}", id);
            }
        } else {
            error!("cobot status sin id_pallet: {}", mensaje);
        }
    } else {
        error!("cobot status sin JSON valido: {}", mensaje);
    }
}
