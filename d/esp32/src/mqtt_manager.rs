use anyhow::Result;
use embedded_svc::mqtt::client::QoS;
use esp_idf_svc::mqtt::client::{EspMqttClient, EventPayload, MqttClientConfiguration};
use log::{error, info};
use serde_json::Value;
use std::{
    sync::{mpsc::SyncSender, Arc, Mutex},
    thread,
    time::Duration,
};

use crate::{config, state::DemoState};

// Slot compartido: el escenario activo registra aquí su sender antes de
// publicar un db/pull; el callback lo usa para reenviar la respuesta.
pub type PullSlot = Arc<Mutex<Option<SyncSender<String>>>>;

pub struct MqttManager<'a> {
    client: EspMqttClient<'a>,
}

impl<'a> MqttManager<'a> {
    /// Conecta al broker y suscribe todos los topics del demo.
    ///
    /// - `demo_state`   — estado compartido entre escenarios
    /// - `cobot_evt_tx` — canal para notificar FINISHED del cobot (envia pallet_id)
    /// - `camera_tx`    — canal para reenviar detecciones de camara (JSON crudo)
    /// - `pull_slot`    — slot para recibir respuestas de db/pull/response
    #[allow(unused_variables)]
    pub fn connect_and_subscribe(
        demo_state:   Arc<Mutex<DemoState>>,
        cobot_evt_tx: SyncSender<u32>,
        camera_tx:    SyncSender<String>,
        pull_slot:    PullSlot,
    ) -> Result<Self> {
        let mqtt_user = if config::MQTT_USER.is_empty() { None } else { Some(config::MQTT_USER) };
        let mqtt_pass = if config::MQTT_PASSWORD.is_empty() { None } else { Some(config::MQTT_PASSWORD) };

        let cfg = MqttClientConfiguration {
            client_id: Some(config::MQTT_CLIENT_ID),
            username:  mqtt_user,
            password:  mqtt_pass,
            ..Default::default()
        };

        let mut client = EspMqttClient::new_cb(config::MQTT_URL, &cfg, move |event| {
            match event.payload() {
                EventPayload::Connected(_) => info!("MQTT conectado"),
                EventPayload::Subscribed(id) => info!("Suscrito id={}", id),

                EventPayload::Received { topic, data, .. } => {
                    let topic   = topic.unwrap_or("");
                    let mensaje = std::str::from_utf8(data).unwrap_or("");

                    match topic {
                        // Escenario 1 — AMR llegó
                        "giirob/pr2-A1/devices/amr/status" => {
                            handle_amr_status(mensaje, &demo_state);
                        }
                        // Escenario 1 — Cobot terminó de paletizar
                        "giirob/pr2-A1/devices/cobot/status" => {
                            handle_cobot_status(mensaje, &demo_state, &cobot_evt_tx);
                        }
                        // Escenario 2 — Cámara detectó tapa
                        "giirob/pr2-A1/devices/camera/data" => {
                            info!("Camara detectó tapa: {}", mensaje);
                            let _ = camera_tx.try_send(mensaje.to_string());
                        }
                        // Ambos escenarios — Respuesta a db/pull
                        "giirob/pr2-A1/db/pull/response" => {
                            info!("db/pull/response: {}", mensaje);
                            if let Ok(slot) = pull_slot.try_lock() {
                                if let Some(tx) = slot.as_ref() {
                                    let _ = tx.try_send(mensaje.to_string());
                                }
                            }
                        }
                        other => info!("Topic no gestionado: {}", other),
                    }
                }
                _ => {}
            }
        })?;

        info!("Esperando conexion MQTT...");
        thread::sleep(Duration::from_secs(5));
        subscribe_topics(&mut client, config::MQTT_SUB_TOPICS);

        Ok(Self { client })
    }

    pub fn publish_text(&mut self, topic: &str, payload: &str) {
        if let Err(e) = self.client.publish(topic, QoS::AtLeastOnce, false, payload.as_bytes()) {
            error!("Error al publicar en {}: {:?}", topic, e);
        } else {
            info!("Publicado en [{}]: {}", topic, payload);
        }
    }
}

fn subscribe_topics(client: &mut EspMqttClient<'_>, topics: &[&str]) {
    for &topic in topics {
        loop {
            match client.subscribe(topic, QoS::AtLeastOnce) {
                Ok(_) => { info!("Suscrito a {}", topic); break; }
                Err(e) => {
                    error!("Error suscribiendose a {}: {:?}. Reintentando...", topic, e);
                    thread::sleep(Duration::from_secs(2));
                }
            }
        }
    }
}

// -----------------------------------------------------------------------
// Handlers internos
// -----------------------------------------------------------------------

fn handle_amr_status(mensaje: &str, state: &Arc<Mutex<DemoState>>) {
    let Ok(val) = serde_json::from_str::<Value>(mensaje) else {
        error!("amr/status JSON invalido: {}", mensaje);
        return;
    };

    let status   = val.get("status").and_then(|v| v.as_str()).unwrap_or("");
    let location = val.get("location").and_then(|v| v.as_str()).unwrap_or("");

    if !status.eq_ignore_ascii_case("ARRIVED") {
        return;
    }

    if location.eq_ignore_ascii_case(config::AMR_COBOT_LOCATION) {
        if let Ok(mut st) = state.try_lock() {
            st.cobot_ready = true;
            info!("AMR llegó a cobot_pick — cobot_ready=true");
        }
    }
}

fn handle_cobot_status(
    mensaje:      &str,
    state:        &Arc<Mutex<DemoState>>,
    cobot_evt_tx: &SyncSender<u32>,
) {
    let Ok(val) = serde_json::from_str::<Value>(mensaje) else {
        error!("cobot/status JSON invalido: {}", mensaje);
        return;
    };

    let status    = val.get("status").and_then(|v| v.as_str()).unwrap_or("");
    let pallet_id = val.get("id_pallet").and_then(|v| v.as_u64()).unwrap_or(0) as u32;

    if !status.eq_ignore_ascii_case("COMPLETED") {
        return;
    }

    if let Ok(mut st) = state.try_lock() {
        st.cobot_in_progress = false;
        info!("Cobot COMPLETED pallet_id={}", pallet_id);
    }

    // Notificar al hilo de escenario 1
    let _ = cobot_evt_tx.try_send(pallet_id);
}
