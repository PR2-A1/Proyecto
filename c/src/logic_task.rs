use anyhow::Result;
use serde_json::json;
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
    mqtt_manager::MqttManager,
    vision_task::VisionSample,
    control_state::{ControlState, Mode},
};

pub fn spawn_logic_task<'a: 'static>(
    mqtt: Arc<Mutex<MqttManager<'a>>>,
    signal_rx: Receiver<VisionSample>,
    emergency_stop: Arc<AtomicBool>,
    control_state: Arc<Mutex<ControlState>>,
) -> Result<thread::JoinHandle<()>> {
    let handle = thread::Builder::new()
        .name("logic-task".to_string())
        .spawn(move || {
            loop {
                if emergency_stop.load(Ordering::SeqCst) {
                    thread::sleep(Duration::from_millis(100));
                    continue;
                }

                // Generar tapas si es necesario en modo Auto
                try_spawn_caps(&mqtt, &control_state, &emergency_stop);

                // Procesar detecciones de cámara
                match signal_rx.recv_timeout(Duration::from_millis(500)) {
                    Ok(sample) => {
                        process_vision_sample(&mqtt, &control_state, &sample, &emergency_stop);
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

/// Intenta generar (spawn) tapas en RoboDK si estamos en modo Auto y quedan pendientes
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
            // Generar color aleatorio
            let color = get_random_color();
            
            // Publicar orden a RoboDK para spawnear tapa
            if let Ok(mut mqtt_guard) = mqtt.try_lock() {
                let spawn_msg = json!({
                    "cmd": "spawn",
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
                let spawn_msg = json!({
                    "cmd": "spawn",
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

/// Procesa una muestra de visión y decide si enviar PICK al Delta
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
    let cap_id = sample.cap_id.clone();

    // Validar según el modo
    if let Ok(mut state) = control_state.lock() {
        let detected_color = sample.color.as_deref().unwrap_or("unknown");

        match state.mode {
            Mode::Manual => {
                // En modo manual, validar que el color coincida
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
                            pick_reason = format!(
                                "Manual: color {} sin tolva asignada",
                                detected_color
                            );
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
                // En modo automático, aceptar cualquier tapa detectada si aún quedan validaciones pendientes
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

                            // Verificar si completamos el lote
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
                        pick_reason = format!(
                            "Auto: color {} sin tolva asignada",
                            detected_color
                        );
                    }
                }
            }
        }
    }

    // Publicar PICK al Delta si corresponde
    if should_pick {
        if let Some(tolva_index) = selected_tolva {
            if let Ok(mut state) = control_state.lock() {
                state.pending_tolva_counts[tolva_index] += 1;
                state.pending_tapas.insert(cap_id.clone(), tolva_index);
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
                "cap_id": cap_id,
                "device": "ESP32-S3",
                "sensor": "delta",
                "unit": "command"
            }).to_string();
            
            mqtt_guard.publish_text(config::MQTT_TOPIC_DELTA_ACTION, &pick_msg);
        }
    }
}

/// Publica el estado actual del sistema
fn publish_status<'a>(
    mqtt: &Arc<Mutex<MqttManager<'a>>>,
    control_state: &Arc<Mutex<ControlState>>,
) {
    let mut amr_target: Option<usize> = None;
    let mut send_warehouse = false;
    let mut caja_payload: Option<(String, String, String, bool)> = None;
    let mut cobot_start: Option<(u32, String)> = None;
    let mut should_publish_status = false;

    if let Ok(mut state) = control_state.lock() {
        if state.status_requested {
            should_publish_status = true;
            state.status_requested = false;
        }

        let pending_label = state
            .amr_pending_tolva
            .map(|idx| format!("TOLVA_{}", idx + 1));
        let arrived_label = state
            .amr_arrived_tolva
            .map(|idx| format!("TOLVA_{}", idx + 1));
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
                let caja_id = state.amr_caja_id.take();
                let caja_tolva = state.amr_caja_tolva.take();
                let caja_color = caja_tolva.and_then(tolva_index_to_color).map(|c| c.to_string());
                if let (Some(id), Some(color)) = (caja_id, caja_color) {
                    let etiqueta = next_etiqueta();
                    caja_payload = Some((id, color, etiqueta, true));
                }

                if let Some(tolva_index) = state.amr_arrived_tolva.or(state.amr_pending_tolva) {
                    state.tolva_counts[tolva_index] = 0;
                }
                state.amr_pending_tolva = None;
                state.amr_arrived_tolva = None;
                state.amr_arrived_at = None;
                send_warehouse = true;
            }
        } else if state.amr_pending_tolva.is_none() {
            for (index, count) in state.tolva_counts.iter().enumerate() {
                if *count >= config::AMR_TOLVA_THRESHOLD {
                    state.amr_pending_tolva = Some(index);
                    amr_target = Some(index);
                    break;
                }
            }
        }

        if state.cobot_ready && !state.cobot_in_progress {
            let pallet_index = state.cobot_next_pallet % config::COBOT_PALLET_COUNT;
            let id_pallet = config::COBOT_PALLET_ID_BASE + pallet_index as u32;
            let pos = format!("pallet{}", pallet_index + 1);

            state.cobot_ready = false;
            state.cobot_in_progress = true;
            state.cobot_next_pallet = (pallet_index + 1) % config::COBOT_PALLET_COUNT;

            cobot_start = Some((id_pallet, pos));
        }

        if let Ok(mut mqtt_guard) = mqtt.lock() {
            if should_publish_status {
                let status_msg = json!({
                    "mode": match state.mode {
                        Mode::Manual => "Manual",
                        Mode::Auto => "Auto",
                    },
                    "lote_id": state.lote_id.as_deref().unwrap_or(""),
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
                    "pallets": {
                        "PALLET_1": state.pallet_counts[0],
                        "PALLET_2": state.pallet_counts[1],
                        "PALLET_3": state.pallet_counts[2],
                        "PALLET_4": state.pallet_counts[3],
                        "PALLET_5": state.pallet_counts[4],
                        "PALLET_6": state.pallet_counts[5]
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
                    "sensor": "scada",
                    "unit": "state"
                }).to_string();
                
                mqtt_guard.publish_text(config::MQTT_TOPIC_SCADA_STATUS, &status_msg);
            }

            if let Some(tolva_index) = amr_target {
                let cmd_msg = json!({
                    "cmd": "goto",
                    "location": format!("tolva_{}", tolva_index + 1),
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
                        obj.insert("caja_id".to_string(), json!(caja_id));
                        obj.insert("color".to_string(), json!(color));
                        obj.insert("codigo_etiqueta".to_string(), json!(etiqueta));
                        obj.insert("estado".to_string(), json!(estado));
                    }
                    let lotes = state.lote_id.as_ref()
                        .map(|id| vec![id.clone()])
                        .unwrap_or_default();
                    let db_msg = json!({
                        "event": "box_completed",
                        "caja_id": caja_id,
                        "color": color,
                        "codigo_etiqueta": etiqueta,
                        "estado": estado,
                        "lotes": lotes
                    })
                    .to_string();
                    mqtt_guard.publish_text(config::MQTT_TOPIC_DB_PUSH, &db_msg);
                }
                let cmd_msg = cmd_msg.to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_AMR_ACTION, &cmd_msg);
            }

            if let Some((id_pallet, pos)) = cobot_start {
                let cmd_msg = json!({
                    "cmd": "start",
                    "id_pallet": id_pallet,
                    "mode": "pallet",
                    "pos": pos,
                    "device": "ESP32-S3",
                    "sensor": "cobot",
                    "unit": "command"
                }).to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_COBOT_ACTION, &cmd_msg);
            }
        }
    }
}

/// Genera un color aleatorio del conjunto válido
fn get_random_color() -> &'static str {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static COUNTER: AtomicUsize = AtomicUsize::new(0);
    
    let idx = COUNTER.fetch_add(1, Ordering::Relaxed);
    config::VALID_COLORS[idx % config::VALID_COLORS.len()]
}

fn map_color_to_tolva(color: &str) -> Option<usize> {
    match color.to_ascii_lowercase().as_str() {
        "red" => Some(0),
        "yellow" => Some(1),
        "green" => Some(2),
        "white" => Some(3),
        "orange" => Some(4),
        "blue" => Some(5),
        _ => None,
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

fn next_etiqueta() -> String {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static COUNTER: AtomicUsize = AtomicUsize::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("ETQ{:07}", id)
}
