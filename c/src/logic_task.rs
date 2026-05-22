use anyhow::Result;
use log::{error, info};
use serde_json::json;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::Receiver,
        Arc,
        Mutex,
    },
    thread,
    time::Duration,
};

use esp_idf_svc::nvs::EspDefaultNvsPartition;

use crate::{
    config,
    mqtt_manager::{MqttManager, PullSlot},
    control_state::{ControlState, Mode, RobotEvent},
};

pub fn next_id_cap() -> String {
    use std::sync::atomic::{AtomicU32, Ordering};
    static COUNTER: AtomicU32 = AtomicU32::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("C{:04}", id)
}

pub fn spawn_logic_task<'a: 'static>(
    mqtt: Arc<Mutex<MqttManager<'a>>>,
    emergency_stop: Arc<AtomicBool>,
    control_state: Arc<Mutex<ControlState>>,
    pull_slot: PullSlot,
    nvs: EspDefaultNvsPartition,
    event_rx: Receiver<RobotEvent>,
) -> Result<thread::JoinHandle<()>> {
    let handle = thread::Builder::new()
        .name("logic-task".to_string())
        .spawn(move || {
            loop {
                if emergency_stop.load(Ordering::SeqCst) {
                    thread::sleep(Duration::from_millis(100));
                    continue;
                }

                while let Ok(event) = event_rx.try_recv() {
                    process_robot_event(event, &control_state, &nvs);
                }

                try_spawn_caps(&mqtt, &control_state, &emergency_stop);
                handle_cobot_completed(&mqtt, &control_state, &pull_slot);
                publish_status(&mqtt, &control_state, &nvs);

                thread::sleep(Duration::from_millis(500));
            }
        })?;

    Ok(handle)
}

fn process_robot_event(
    event: RobotEvent,
    control_state: &Arc<Mutex<ControlState>>,
    nvs: &EspDefaultNvsPartition,
) {
    match event {
        RobotEvent::DeltaCompleted { color, id_cap } => {
            let tolva_index = match color.to_ascii_lowercase().as_str() {
                "red"    => 0,
                "yellow" => 1,
                "green"  => 2,
                "white"  => 3,
                "orange" => 4,
                "blue"   => 5,
                _ => { error!("Delta completed con color desconocido: {}", color); return; }
            };
            if let Ok(mut state) = control_state.lock() {
                state.tolva_counts[tolva_index] += 1;
                state.total_processed += 1;
                if state.id_lote.is_some() {
                    state.tapas_clasificadas_pending += 1;
                }
                if state.mode == Mode::Auto {
                    if state.auto_validated < state.auto_target {
                        state.auto_validated += 1;
                        if state.auto_validated >= state.auto_target {
                            state.batch_complete_pending = true;
                        }
                    }
                } else {
                    if state.manual_remaining > 0 {
                        state.manual_remaining -= 1;
                    }
                    state.expected_tapa = None;
                }
                info!("Delta depositó {} en TOLVA_{} (total: {})", id_cap, tolva_index + 1, state.tolva_counts[tolva_index]);
                if let Err(e) = state.save_tolva_counts(nvs) {
                    error!("No se pudo guardar tolvas en NVS: {:?}", e);
                }
            }
        }

        RobotEvent::AmrArrived { location } => {
            if location.eq_ignore_ascii_case(config::AMR_WAREHOUSE_LOCATION) {
                if let Ok(mut state) = control_state.lock() {
                    state.cobot_ready = true;
                }
                return;
            }
            if let Some(index) = parse_amr_location_index(&location) {
                if let Ok(mut state) = control_state.lock() {
                    match state.amr_pending_tolva {
                        Some(pending) if pending == index => {
                            state.amr_arrived_tolva = Some(index);
                            state.amr_arrived_at    = Some(std::time::Instant::now());
                        }
                        Some(pending) => error!("AMR llegó a {}, esperaba tolva {}", location, pending + 1),
                        None          => error!("AMR llegó a {} sin tolva pendiente", location),
                    }
                }
            } else {
                error!("Location AMR inválida: {}", location);
            }
        }

        RobotEvent::CobotCompleted { id_pallet } => {
            if let Ok(mut state) = control_state.lock() {
                info!("Cobot completó operación en pallet {}", id_pallet);
                state.cobot_completed_event = Some(id_pallet);
                state.cobot_in_progress     = false;
            }
        }
    }
}

fn parse_amr_location_index(location: &str) -> Option<usize> {
    let normalized = location.trim().to_ascii_lowercase();
    let num_str    = normalized.strip_prefix("tolva_")?;
    let num        = num_str.parse::<usize>().ok()?;
    if (1..=6).contains(&num) { Some(num - 1) } else { None }
}

fn try_spawn_caps<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    control_state: &Arc<Mutex<ControlState>>,
    emergency_stop: &Arc<AtomicBool>,
) {
    if emergency_stop.load(Ordering::SeqCst) {
        return;
    }

    if let Ok(mut state) = control_state.try_lock() {
        if state.mode == Mode::Auto && state.auto_spawned < state.auto_target {
            let color = get_random_color();
            let ci = color_to_index(color);
            if state.tolva_counts[ci] < config::AMR_TOLVA_THRESHOLD {
                if let Ok(mut mqtt_guard) = mqtt.try_lock() {
                    let id_cap = next_id_cap();
                    let spawn_msg = json!({
                        "cmd": "spawn",
                        "id_cap": id_cap,
                        "color": color,
                        "device": "ESP32-S3",
                        "sensor": "robodk"
                    }).to_string();
                    mqtt_guard.publish_text(config::MQTT_TOPIC_ROBODK_ACTION, &spawn_msg);
                    state.auto_spawned += 1;
                }
            }
        } else if state.mode == Mode::Manual && state.manual_spawn_pending {
            let color = state.manual_color.clone();
            let ci = color_to_index(&color);
            if state.tolva_counts[ci] < config::AMR_TOLVA_THRESHOLD {
                if let Ok(mut mqtt_guard) = mqtt.try_lock() {
                    let id_cap = next_id_cap();
                    let spawn_msg = json!({
                        "cmd": "spawn",
                        "id_cap": id_cap,
                        "color": color,
                        "device": "ESP32-S3",
                        "sensor": "robodk"
                    }).to_string();
                    mqtt_guard.publish_text(config::MQTT_TOPIC_ROBODK_ACTION, &spawn_msg);
                    state.manual_spawn_pending = false;
                }
            } else {
                info!("Tolva {} llena, spawn manual {} en espera", ci + 1, color);
            }
        }
    }
}

fn publish_status<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    control_state: &Arc<Mutex<ControlState>>,
    nvs: &EspDefaultNvsPartition,
) {
    let mut amr_target: Option<(usize, String)> = None;
    let mut send_warehouse = false;
    let mut caja_payload: Option<(String, String, String, bool)> = None;
    let mut cobot_start: Option<(String, String, u64)> = None;
    let mut should_publish_status = false;
    let mut batch_complete = false;
    let mut reset_db = false;
    let mut tapas_lote: Option<(String, u32)> = None;

    if let Ok(mut state) = control_state.lock() {
        if state.status_requested {
            should_publish_status = true;
            state.status_requested = false;
        }

        if state.batch_complete_pending {
            batch_complete = true;
            state.batch_complete_pending = false;
        }

        if state.reset_db_pending {
            reset_db = true;
            state.reset_db_pending = false;
        }

        if state.tapas_clasificadas_pending > 0 {
            if let Some(lote) = &state.id_lote {
                tapas_lote = Some((lote.clone(), state.tapas_clasificadas_pending));
                state.tapas_clasificadas_pending = 0;
            }
        }

        let pending_label = state.amr_pending_tolva.map(|idx| format!("TOLVA_{}", idx + 1));
        let arrived_label = state.amr_arrived_tolva.map(|idx| format!("TOLVA_{}", idx + 1));
        let amr_wait_seconds = state
            .amr_arrived_at
            .map(|arrived_at| {
                let elapsed = arrived_at.elapsed().as_secs();
                if elapsed >= config::AMR_ARRIVAL_DELAY_SECS {
                    0
                } else {
                    config::AMR_ARRIVAL_DELAY_SECS - elapsed
                }
            })
            .unwrap_or(0);

        if state.amr_pending_tolva.is_some() && state.amr_arrived_tolva.is_none() {
            if let Some(dispatched) = state.amr_dispatched_at {
                if dispatched.elapsed().as_secs() >= config::AMR_TIMEOUT_SECS {
                    error!("Timeout AMR — reseteando amr_pending_tolva");
                    state.amr_pending_tolva = None;
                    state.amr_dispatched_at = None;
                    state.amr_id_caja       = None;
                    state.amr_caja_tolva    = None;
                }
            }
        }

        if let Some(arrived_at) = state.amr_arrived_at {
            if arrived_at.elapsed() >= Duration::from_secs(config::AMR_ARRIVAL_DELAY_SECS) {
                let caja_id    = state.amr_id_caja.take();
                let caja_tolva = state.amr_caja_tolva.take();
                let caja_color = caja_tolva.and_then(tolva_index_to_color).map(|c| c.to_string());
                if let (Some(id), Some(color)) = (caja_id, caja_color) {
                    let etiqueta = next_etiqueta();
                    state.cobot_pending_color = Some(color.clone());
                    state.cobot_pending_caja  = Some(id.clone());
                    caja_payload = Some((id, color, etiqueta, true));
                }

                if let Some(tolva_index) = state.amr_arrived_tolva.or(state.amr_pending_tolva) {
                    state.tolva_counts[tolva_index] = 0;
                    if let Err(e) = state.save_tolva_counts(nvs) {
                        error!("No se pudo guardar tolvas en NVS tras recogida AMR: {:?}", e);
                    }
                }
                state.amr_pending_tolva = None;
                state.amr_arrived_tolva = None;
                state.amr_arrived_at    = None;
                state.amr_dispatched_at = None;
                send_warehouse = true;
            }
        } else if state.amr_pending_tolva.is_none() {
            for (index, count) in state.tolva_counts.iter().enumerate() {
                if *count >= config::AMR_TOLVA_THRESHOLD {
                    let id_caja = next_id_caja();
                    state.amr_id_caja       = Some(id_caja.clone());
                    state.amr_caja_tolva    = Some(index);
                    state.amr_pending_tolva = Some(index);
                    state.amr_dispatched_at = Some(std::time::Instant::now());
                    amr_target = Some((index, id_caja));
                    break;
                }
            }
        }

        if state.cobot_in_progress {
            if let Some(started) = state.cobot_started_at {
                if started.elapsed().as_secs() >= config::COBOT_TIMEOUT_SECS {
                    error!("Timeout cobot — reseteando cobot_in_progress");
                    state.cobot_in_progress = false;
                    state.cobot_started_at  = None;
                    state.cobot_active_color = None;
                    state.cobot_pending_caja = None;
                }
            }
        }

        if state.cobot_ready && !state.cobot_in_progress {
            let color = state.cobot_pending_color.take().unwrap_or_else(|| "red".to_string());
            let ci = color_to_index(&color);
            let id_pallet     = format!("P{:04}", state.cobot_next_pallet[ci]);
            let boxes_stacked = state.pallet_counts[ci];
            state.cobot_active_color = Some(color.clone());
            state.cobot_ready        = false;
            state.cobot_in_progress  = true;
            state.cobot_started_at   = Some(std::time::Instant::now());
            cobot_start = Some((id_pallet, color, boxes_stacked));
        }

        if let Ok(mut mqtt_guard) = mqtt.lock() {
            if let Some((lote_id, cantidad)) = tapas_lote {
                let msg = json!({
                    "event":    "tapa_clasificada",
                    "id_lote":  lote_id,
                    "cantidad": cantidad
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_DB_PUSH, &msg);
            }

            if reset_db {
                let msg = json!({
                    "event":  "reset",
                    "device": "ESP32-S3"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_DB_PUSH, &msg);
                info!("Reset de producción enviado a DB");
            }

            if batch_complete {
                let msg = json!({
                    "event":   "batch_complete",
                    "message": "Lote de producción completado",
                    "total":   state.auto_target,
                    "device":  "ESP32-S3",
                    "sensor":  "scada"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_SCADA_STATUS, &msg);
            }

            if should_publish_status {
                let status_msg = json!({
                    "mode": match state.mode {
                        Mode::Manual => "Manual",
                        Mode::Auto   => "Auto",
                    },
                    "id_lote":        state.id_lote.as_deref().unwrap_or(""),
                    "total_processed": state.total_processed,
                    "auto_target":    state.auto_target,
                    "auto_spawned":   state.auto_spawned,
                    "auto_validated": state.auto_validated,
                    "manual_remaining": state.manual_remaining,
                    "expected_color": state.expected_tapa.as_ref()
                        .map(|t| t.color.as_str())
                        .unwrap_or("none"),
                    "amr_pending_tolva": pending_label,
                    "amr_arrived_tolva": arrived_label,
                    "amr_wait_seconds":  amr_wait_seconds,
                    "pallets": {
                        "PALLET_1": state.pallet_counts[0],
                        "PALLET_2": state.pallet_counts[1],
                        "PALLET_3": state.pallet_counts[2],
                        "PALLET_4": state.pallet_counts[3],
                        "PALLET_5": state.pallet_counts[4],
                        "PALLET_6": state.pallet_counts[5],
                    },
                    "tolvas": {
                        "TOLVA_1": state.tolva_counts[0],
                        "TOLVA_2": state.tolva_counts[1],
                        "TOLVA_3": state.tolva_counts[2],
                        "TOLVA_4": state.tolva_counts[3],
                        "TOLVA_5": state.tolva_counts[4],
                        "TOLVA_6": state.tolva_counts[5]
                    },
                    "device": "ESP32-S3",
                    "sensor": "scada"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_SCADA_STATUS, &status_msg);
            }

            if let Some((tolva_index, _id_caja)) = amr_target {
                let cmd_msg = json!({
                    "cmd":      "goto",
                    "location": format!("TOLVA_{}", tolva_index + 1),
                    "device":   "ESP32-S3",
                    "sensor":   "amr",
                    "unit":     "command"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_AMR_ACTION, &cmd_msg);
            }

            if send_warehouse {
                let mut cmd_msg = json!({
                    "cmd":      "goto",
                    "location": config::AMR_WAREHOUSE_LOCATION,
                    "device":   "ESP32-S3",
                    "sensor":   "amr",
                    "unit":     "command"
                });
                if let Some((caja_id, color, etiqueta, estado)) = caja_payload.clone() {
                    if let Some(obj) = cmd_msg.as_object_mut() {
                        obj.insert("id_caja".to_string(),         json!(caja_id));
                        obj.insert("color".to_string(),           json!(color));
                        obj.insert("codigo_etiqueta".to_string(), json!(etiqueta));
                        obj.insert("estado".to_string(),          json!(estado));
                    }
                    let lotes = state.id_lote.as_ref()
                        .map(|id| vec![id.clone()])
                        .unwrap_or_default();
                    let db_msg = json!({
                        "event":            "box_completed",
                        "id_caja":          caja_id,
                        "color":            color,
                        "codigo_etiqueta":  etiqueta,
                        "estado":           estado,
                        "lotes":            lotes
                    }).to_string();
                    mqtt_guard.publish_text(config::MQTT_TOPIC_DB_PUSH, &db_msg);
                }
                mqtt_guard.publish_text(config::MQTT_TOPIC_AMR_ACTION, &cmd_msg.to_string());
            }

            if let Some((id_pallet, color, boxes_stacked)) = cobot_start {
                let cmd_msg = json!({
                    "cmd":          "start",
                    "id_pallet":    id_pallet,
                    "color":        color,
                    "boxes_stacked": boxes_stacked,
                    "device":       "ESP32-S3",
                    "sensor":       "cobot",
                    "unit":         "command"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_COBOT_ACTION, &cmd_msg);
            }
        }
    }
}

fn handle_cobot_completed<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    control_state: &Arc<Mutex<ControlState>>,
    pull_slot: &PullSlot,
) {
    let event = {
        if let Ok(mut state) = control_state.try_lock() {
            state.cobot_completed_event.take()
        } else {
            return;
        }
    };

    let _event_pallet = match event {
        Some(id) => id,
        None => return,
    };

    let (id_caja, id_color, id_pallet, pallet_full) = {
        if let Ok(mut state) = control_state.try_lock() {
            let id_caja  = state.cobot_pending_caja.take().unwrap_or_default();
            let id_color = state.cobot_active_color.take().unwrap_or_else(|| "red".to_string());
            state.cobot_started_at = None;
            let ci = color_to_index(&id_color);
            state.pallet_counts[ci] += 1;
            let count = state.pallet_counts[ci];
            let id_pallet = format!("P{:04}", state.cobot_next_pallet[ci]);
            let full = count >= config::PALLET_CAPACITY;
            if full {
                info!("Pallet {} ({}) lleno ({} cajas) — iniciando siguiente", id_pallet, id_color, count);
                state.cobot_next_pallet[ci] += 6;
                state.pallet_counts[ci] = 0;
            }
            (id_caja, id_color, id_pallet, full)
        } else {
            return;
        }
    };

    let id_operario = if pallet_full {
        query_operarios(mqtt, pull_slot)
    } else {
        None
    };

    publish_caja_paletizada(mqtt, &id_caja, &id_pallet, &id_color, pallet_full, id_operario.as_deref());

    if pallet_full {
        if let Ok(mut mqtt_guard) = mqtt.try_lock() {
            let msg = json!({
                "event":    "pallet_full",
                "id_palet": id_pallet,
                "color":    id_color,
                "device":   "ESP32-S3",
                "sensor":   "scada"
            }).to_string();
            mqtt_guard.publish_text(config::MQTT_TOPIC_SCADA_STATUS, &msg);
        }
        info!("Pallet {} ({}) cerrado y notificado al SCADA", id_pallet, id_color);
    }
}

fn query_operarios<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    pull_slot: &PullSlot,
) -> Option<String> {
    use std::sync::mpsc::sync_channel;

    let (tx, rx) = sync_channel::<String>(1);
    { pull_slot.lock().unwrap().replace(tx); }

    if let Ok(mut mg) = mqtt.try_lock() {
        let req = json!({"query": "operarios"}).to_string();
        mg.publish_text(config::MQTT_TOPIC_DB_PULL, &req);
    }

    let result = match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(json_str) => serde_json::from_str::<serde_json::Value>(&json_str).ok().and_then(|val| {
            let lista = val.get("operarios")?.as_array()?;
            if lista.is_empty() { return None; }
            let idx = (std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .subsec_nanos() as usize) % lista.len();
            let id_operario = lista[idx].get("id_operario").and_then(|v| v.as_str()).map(|v| v.to_string());
            let nombre = lista[idx].get("nombre").and_then(|v| v.as_str()).unwrap_or("?");
            info!("Operario elegido: {:?} ({})", id_operario, nombre);
            id_operario
        }),
        Err(_) => {
            error!("Timeout esperando db/pull/response para operarios");
            None
        }
    };

    pull_slot.lock().unwrap().take();
    result
}

fn publish_caja_paletizada<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    id_caja: &str,
    id_palet: &str,
    id_color: &str,
    estado: bool,
    id_operario: Option<&str>,
) {
    let mut msg = json!({
        "event":    "caja_paletizada",
        "id_caja":  id_caja,
        "id_palet": id_palet,
        "id_color": id_color.to_ascii_uppercase(),
        "estado":   estado,
    });

    if let (true, Some(op)) = (estado, id_operario) {
        msg["id_operario"] = json!(op);
    }

    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::MQTT_TOPIC_DB_PUSH, &msg.to_string());
        info!("caja_paletizada — caja={} palet={} estado={} operario={:?}", id_caja, id_palet, estado, id_operario);
    }
}

fn get_random_color() -> &'static str {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    let idx = COUNTER.fetch_add(1, Ordering::Relaxed);
    config::VALID_COLORS[idx % config::VALID_COLORS.len()]
}

fn tolva_index_to_color(index: usize) -> Option<&'static str> {
    match index {
        0 => Some("red"),
        1 => Some("yellow"),
        2 => Some("green"),
        3 => Some("white"),
        4 => Some("orange"),
        5 => Some("blue"),
        _ => None,
    }
}

fn color_to_index(color: &str) -> usize {
    match color.to_ascii_lowercase().as_str() {
        "red"    => 0,
        "yellow" => 1,
        "green"  => 2,
        "white"  => 3,
        "orange" => 4,
        "blue"   => 5,
        _        => 0,
    }
}

fn next_id_caja() -> String {
    use std::sync::atomic::{AtomicU32, Ordering};
    static COUNTER: AtomicU32 = AtomicU32::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("B{:04}", id)
}

fn next_etiqueta() -> String {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static COUNTER: AtomicUsize = AtomicUsize::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("ETQ{:07}", id)
}
