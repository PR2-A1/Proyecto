use anyhow::Result;
use log::{error, info};
use serde_json::{json, Value};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        mpsc::{Receiver, RecvTimeoutError},
        Arc,
        Mutex,
    },
    thread,
    time::Duration,
};

use crate::{
    config,
    mqtt_manager::{MqttManager, PullSlot},
    control_state::{ControlState, Mode},
};

#[derive(Clone, Debug)]
pub struct VisionSample {
    pub x: f32,
    pub y: f32,
    pub color: Option<String>,
    pub id_cap: String,
}

pub fn next_id_cap() -> String {
    use std::sync::atomic::{AtomicU32, Ordering};
    static COUNTER: AtomicU32 = AtomicU32::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("C{:04}", id)
}

pub fn spawn_logic_task<'a: 'static>(
    mqtt: Arc<Mutex<MqttManager<'a>>>,
    signal_rx: Receiver<String>,
    emergency_stop: Arc<AtomicBool>,
    control_state: Arc<Mutex<ControlState>>,
    pull_slot: PullSlot,
) -> Result<thread::JoinHandle<()>> {
    let handle = thread::Builder::new()
        .name("logic-task".to_string())
        .spawn(move || {
            loop {
                if emergency_stop.load(Ordering::SeqCst) {
                    thread::sleep(Duration::from_millis(100));
                    continue;
                }

                try_spawn_caps(&mqtt, &control_state, &emergency_stop);
                handle_cobot_completed(&mqtt, &control_state, &pull_slot);

                match signal_rx.recv_timeout(Duration::from_millis(500)) {
                    Ok(payload) => {
                        if let Some(sample) = parse_vision_sample(&payload) {
                            process_vision_sample(&mqtt, &control_state, &sample, &emergency_stop);
                        }
                        publish_status(&mqtt, &control_state);
                    }
                    Err(RecvTimeoutError::Timeout) => {
                        publish_status(&mqtt, &control_state);
                    }
                    Err(RecvTimeoutError::Disconnected) => break,
                }
            }
        })?;

    Ok(handle)
}

fn parse_vision_sample(payload: &str) -> Option<VisionSample> {
    let value = match serde_json::from_str::<Value>(payload) {
        Ok(v) => v,
        Err(_) => {
            error!("Vision payload invalido: {}", payload);
            return None;
        }
    };

    let precision = value.get("precision").and_then(|v| v.as_f64()).unwrap_or(0.0);
    if precision <= 0.95 {
        info!("Vision ignorada por baja precision: {}", precision);
        return None;
    }

    let x = value.get("x").and_then(|v| v.as_f64())? as f32;
    let y = value.get("y").and_then(|v| v.as_f64())? as f32;
    let color = value.get("color").and_then(|v| v.as_str()).map(|s| s.to_string());
    let id_cap = value
        .get("id_cap")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(next_id_cap);

    Some(VisionSample { x, y, color, id_cap })
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
            if let Ok(mut mqtt_guard) = mqtt.try_lock() {
                let id_cap = next_id_cap();
                let spawn_msg = json!({
                    "cmd": "spawn",
                    "id_cap": id_cap,
                    "color": color,
                    "device": "ESP32-S3",
                    "sensor": "robodk",
                    "unit": "command"
                }).to_string();

                mqtt_guard.publish_text(config::MQTT_TOPIC_ROBODK_ACTION, &spawn_msg);
                state.auto_spawned += 1;
            }
        } else if state.mode == Mode::Manual && state.manual_spawn_pending {
            let color = state.manual_color.clone();
            if let Ok(mut mqtt_guard) = mqtt.try_lock() {
                let id_cap = next_id_cap();
                let spawn_msg = json!({
                    "cmd": "spawn",
                    "id_cap": id_cap,
                    "color": color,
                    "device": "ESP32-S3",
                    "sensor": "robodk",
                    "unit": "command"
                }).to_string();

                mqtt_guard.publish_text(config::MQTT_TOPIC_ROBODK_ACTION, &spawn_msg);
                state.manual_spawn_pending = false;
            }
        }
    }
}

fn process_vision_sample<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    control_state: &Arc<Mutex<ControlState>>,
    sample: &VisionSample,
    emergency_stop: &Arc<AtomicBool>,
) {
    if emergency_stop.load(Ordering::SeqCst) {
        return;
    }

    let mut should_pick = false;
    let mut pick_reason = String::new();
    let mut selected_tolva: Option<usize> = None;
    let id_cap = sample.id_cap.clone();

    if let Ok(mut state) = control_state.lock() {
        let detected_color = sample.color.as_deref().unwrap_or("unknown");

        match state.mode {
            Mode::Manual => {
                if let Some(expected) = &state.expected_tapa {
                    if !expected.validated && detected_color.eq_ignore_ascii_case(&expected.color) {
                        selected_tolva = map_color_to_tolva(detected_color);
                        if let Some(idx) = selected_tolva {
                            let ocupacion = state.tolva_counts[idx] + state.pending_tolva_counts[idx];
                            if ocupacion >= config::AMR_TOLVA_THRESHOLD {
                                pick_reason = format!(
                                    "Manual: tolva {} llena ({} tapas), tapa rechazada",
                                    idx + 1, ocupacion
                                );
                                selected_tolva = None;
                            } else {
                                should_pick = true;
                                pick_reason = format!(
                                    "Manual: color {} coincide con esperado {}",
                                    detected_color, expected.color
                                );
                                state.expected_tapa.as_mut().unwrap().validated = true;
                                if state.manual_remaining > 0 {
                                    state.manual_remaining -= 1;
                                }
                                state.total_processed += 1;
                            }
                        } else {
                            pick_reason = format!("Manual: color {} sin tolva asignada", detected_color);
                        }
                    } else {
                        pick_reason = format!(
                            "Manual: color {} NO coincide con esperado {}",
                            detected_color, expected.color
                        );
                    }
                }
            }
            Mode::Auto => {
                if state.auto_validated < state.auto_target {
                    selected_tolva = map_color_to_tolva(detected_color);
                    if let Some(idx) = selected_tolva {
                        let ocupacion = state.tolva_counts[idx] + state.pending_tolva_counts[idx];
                        if ocupacion >= config::AMR_TOLVA_THRESHOLD {
                            pick_reason = format!(
                                "Auto: tolva {} llena ({} tapas), tapa rechazada",
                                idx + 1, ocupacion
                            );
                            selected_tolva = None;
                        } else {
                            should_pick = true;
                            pick_reason = format!(
                                "Auto: aceptando tapa color {} ({}/{})",
                                detected_color, state.auto_validated + 1, state.auto_target
                            );
                            state.auto_validated += 1;
                            state.total_processed += 1;

                            if state.auto_validated >= state.auto_target {
                                if let Ok(mut mqtt_guard) = mqtt.try_lock() {
                                    let complete_msg = json!({
                                        "event": "batch_complete",
                                        "message": "Lote de producción completado",
                                        "total": state.auto_target,
                                        "device": "ESP32-S3",
                                        "sensor": "scada",
                                        "unit": "event"
                                    }).to_string();
                                    mqtt_guard.publish_text(config::MQTT_TOPIC_SCADA_STATUS, &complete_msg);
                                }
                            }
                        }
                    } else {
                        pick_reason = format!("Auto: color {} sin tolva asignada", detected_color);
                    }
                }
            }
        }
    }

    if should_pick {
        if let Some(tolva_index) = selected_tolva {
            if let Ok(mut state) = control_state.lock() {
                state.pending_tolva_counts[tolva_index] += 1;
                state.pending_tapas.insert(id_cap.clone(), tolva_index);
            }
        }

        if let Ok(mut mqtt_guard) = mqtt.lock() {
            let tolva_label = selected_tolva
                .map(|idx| format!("TOLVA_{}", idx + 1))
                .unwrap_or_else(|| "TOLVA_UNKNOWN".to_string());
            let pick_msg = json!({
                "cmd": "pick",
                "x": sample.x,
                "y": sample.y,
                "color": sample.color.as_deref().unwrap_or("unknown"),
                "reason": pick_reason,
                "tolva": tolva_label,
                "id_cap": id_cap,
                "device": "ESP32-S3",
                "sensor": "delta",
                "unit": "command"
            }).to_string();
            mqtt_guard.publish_text(config::MQTT_TOPIC_DELTA_ACTION, &pick_msg);
        }
    }
}

fn publish_status<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    control_state: &Arc<Mutex<ControlState>>,
) {
    let mut amr_target: Option<(usize, String)> = None;
    let mut send_warehouse = false;
    let mut caja_payload: Option<(String, String, String, bool)> = None;
    let mut cobot_start: Option<(String, String, u64)> = None;
    let mut should_publish_status = false;

    if let Ok(mut state) = control_state.lock() {
        if state.status_requested {
            should_publish_status = true;
            state.status_requested = false;
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
                }
                state.amr_pending_tolva = None;
                state.amr_arrived_tolva = None;
                state.amr_arrived_at    = None;
                send_warehouse = true;
            }
        } else if state.amr_pending_tolva.is_none() {
            for (index, count) in state.tolva_counts.iter().enumerate() {
                if *count >= config::AMR_TOLVA_THRESHOLD {
                    let id_caja = next_id_caja();
                    state.amr_id_caja      = Some(id_caja.clone());
                    state.amr_caja_tolva   = Some(index);
                    state.amr_pending_tolva = Some(index);
                    amr_target = Some((index, id_caja));
                    break;
                }
            }
        }

        if state.cobot_ready && !state.cobot_in_progress {
            let id_pallet     = format!("P{:04}", state.cobot_next_pallet);
            let boxes_stacked = state.pallet_counts.get(&id_pallet).copied().unwrap_or(0);
            let color         = state.cobot_pending_color.take().unwrap_or_else(|| "red".to_string());
            state.cobot_active_color = Some(color.clone());
            state.cobot_ready        = false;
            state.cobot_in_progress  = true;
            cobot_start = Some((id_pallet, color, boxes_stacked));
        }

        if let Ok(mut mqtt_guard) = mqtt.lock() {
            if should_publish_status {
                let status_msg = json!({
                    "mode": match state.mode {
                        Mode::Manual => "Manual",
                        Mode::Auto   => "Auto",
                    },
                    "id_lote": state.id_lote.as_deref().unwrap_or(""),
                    "total_processed": state.total_processed,
                    "auto_target": state.auto_target,
                    "auto_spawned": state.auto_spawned,
                    "auto_validated": state.auto_validated,
                    "manual_remaining": state.manual_remaining,
                    "expected_color": state.expected_tapa.as_ref()
                        .map(|t| t.color.as_str())
                        .unwrap_or("none"),
                    "amr_pending_tolva": pending_label,
                    "amr_arrived_tolva": arrived_label,
                    "amr_wait_seconds": amr_wait_seconds,
                    "current_pallet": format!("P{:04}", state.cobot_next_pallet),
                    "boxes_stacked": state.pallet_counts
                        .get(&format!("P{:04}", state.cobot_next_pallet))
                        .copied()
                        .unwrap_or(0),
                    "tolvas": {
                        "TOLVA_1": state.tolva_counts[0],
                        "TOLVA_2": state.tolva_counts[1],
                        "TOLVA_3": state.tolva_counts[2],
                        "TOLVA_4": state.tolva_counts[3],
                        "TOLVA_5": state.tolva_counts[4],
                        "TOLVA_6": state.tolva_counts[5]
                    },
                    "device": "ESP32-S3",
                    "sensor": "scada",
                    "unit": "state"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_SCADA_STATUS, &status_msg);
            }

            if let Some((tolva_index, _id_caja)) = amr_target {
                let cmd_msg = json!({
                    "cmd": "goto",
                    "location": format!("TOLVA_{}", tolva_index + 1),
                    "device": "ESP32-S3",
                    "sensor": "amr",
                    "unit": "command"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_AMR_ACTION, &cmd_msg);
            }

            if send_warehouse {
                let mut cmd_msg = json!({
                    "cmd": "goto",
                    "location": config::AMR_WAREHOUSE_LOCATION,
                    "device": "ESP32-S3",
                    "sensor": "amr",
                    "unit": "command"
                });
                if let Some((caja_id, color, etiqueta, estado)) = caja_payload.clone() {
                    if let Some(obj) = cmd_msg.as_object_mut() {
                        obj.insert("id_caja".to_string(),          json!(caja_id));
                        obj.insert("color".to_string(),            json!(color));
                        obj.insert("codigo_etiqueta".to_string(),  json!(etiqueta));
                        obj.insert("estado".to_string(),           json!(estado));
                    }
                    let lotes = state.id_lote.as_ref()
                        .map(|id| vec![id.clone()])
                        .unwrap_or_default();
                    let db_msg = json!({
                        "event": "box_completed",
                        "id_caja": caja_id,
                        "color": color,
                        "codigo_etiqueta": etiqueta,
                        "estado": estado,
                        "lotes": lotes
                    }).to_string();
                    mqtt_guard.publish_text(config::MQTT_TOPIC_DB_PUSH, &db_msg);
                }
                mqtt_guard.publish_text(config::MQTT_TOPIC_AMR_ACTION, &cmd_msg.to_string());
            }

            if let Some((id_pallet, color, boxes_stacked)) = cobot_start {
                let cmd_msg = json!({
                    "cmd": "start",
                    "id_pallet": id_pallet,
                    "color": color,
                    "boxes_stacked": boxes_stacked,
                    "device": "ESP32-S3",
                    "sensor": "cobot",
                    "unit": "command"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_COBOT_ACTION, &cmd_msg);
            }
        }
    }
}

fn get_random_color() -> &'static str {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    let idx = COUNTER.fetch_add(1, Ordering::Relaxed);
    config::VALID_COLORS[idx % config::VALID_COLORS.len()]
}

fn map_color_to_tolva(color: &str) -> Option<usize> {
    match color.to_ascii_lowercase().as_str() {
        "red"    => Some(0),
        "yellow" => Some(1),
        "green"  => Some(2),
        "white"  => Some(3),
        "orange" => Some(4),
        "blue"   => Some(5),
        _        => None,
    }
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

fn next_id_caja() -> String {
    use std::sync::atomic::{AtomicU32, Ordering};
    static COUNTER: AtomicU32 = AtomicU32::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("B{:04}", id)
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

    let id_pallet = match event {
        Some(id) => id,
        None => return,
    };

    let (id_caja, id_color, pallet_full) = {
        if let Ok(mut state) = control_state.try_lock() {
            let id_caja   = state.cobot_pending_caja.take().unwrap_or_default();
            let id_color  = state.cobot_active_color.take().unwrap_or_else(|| "red".to_string());
            let count     = state.pallet_counts.get(&id_pallet).copied().unwrap_or(0);
            let full      = count >= config::PALLET_CAPACITY;
            (id_caja, id_color, full)
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
            let msg = serde_json::json!({
                "event":    "pallet_full",
                "id_palet": id_pallet,
                "device":   "ESP32-S3",
                "sensor":   "scada",
                "unit":     "event"
            }).to_string();
            mqtt_guard.publish_text(config::MQTT_TOPIC_SCADA_STATUS, &msg);
        }
        info!("Pallet {} cerrado y notificado al SCADA", id_pallet);
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
        let req = serde_json::json!({"query": "operarios"}).to_string();
        mg.publish_text(config::MQTT_TOPIC_DB_PULL, &req);
    }

    let result = match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(json_str) => serde_json::from_str::<serde_json::Value>(&json_str).ok().and_then(|val| {
            let lista = val.get("operarios")?.as_array()?;
            if lista.is_empty() {
                return None;
            }
            let idx = (std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .subsec_nanos() as usize)
                % lista.len();
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
    let mut msg = serde_json::json!({
        "event":    "caja_paletizada",
        "id_caja":  id_caja,
        "id_palet": id_palet,
        "id_color": id_color.to_ascii_uppercase(),
        "estado":   estado,
    });

    if let (true, Some(op)) = (estado, id_operario) {
        msg["id_operario"] = serde_json::json!(op);
    }

    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::MQTT_TOPIC_DB_PUSH, &msg.to_string());
        info!("caja_paletizada — caja={} palet={} estado={} operario={:?}", id_caja, id_palet, estado, id_operario);
    }
}

fn next_etiqueta() -> String {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static COUNTER: AtomicUsize = AtomicUsize::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("ETQ{:07}", id)
}
