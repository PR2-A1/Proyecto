use anyhow::Result;
use log::{error, info, warn};
use serde_json::{json, Value};
use std::{
    sync::{
        mpsc::{Receiver, sync_channel},
        Arc, Mutex,
    },
    thread,
    time::Duration,
};

use crate::{config, mqtt_manager::{MqttManager, PullSlot}, state::DemoState};

pub fn spawn_logic_task(
    mqtt:         Arc<Mutex<MqttManager<'static>>>,
    state:        Arc<Mutex<DemoState>>,
    cobot_evt_rx: Receiver<u32>,
    camera_rx:    Receiver<String>,
    pull_slot:    PullSlot,
) -> Result<thread::JoinHandle<()>> {
    let handle = thread::Builder::new()
        .name("logic-task".to_string())
        .stack_size(16 * 1024)
        .spawn(move || {
            info!("[LOGIC] Tarea unificada iniciada");
            let mut cap_counter: u32 = 1;

            loop {
                // Escenario 1 tiene prioridad: AMR llegó al cobot
                let cobot_ready = state
                    .try_lock()
                    .map(|s| s.cobot_ready && !s.cobot_in_progress)
                    .unwrap_or(false);

                if cobot_ready {
                    run_esc1_cycle(&mqtt, &state, &cobot_evt_rx, &pull_slot);
                } else {
                    run_esc2_cycle(&mqtt, &state, &camera_rx, &pull_slot, &mut cap_counter);
                }
            }
        })?;

    Ok(handle)
}

// -----------------------------------------------------------------------
// ESCENARIO 1: AMR → Cobot → DB
// -----------------------------------------------------------------------
fn run_esc1_cycle(
    mqtt:         &Arc<Mutex<MqttManager<'static>>>,
    state:        &Arc<Mutex<DemoState>>,
    cobot_evt_rx: &Receiver<u32>,
    pull_slot:    &PullSlot,
) {
    let (caja_id, color, pallet_id) = {
        let mut st = state.lock().unwrap();
        st.cobot_in_progress = true;
        st.cobot_ready       = false;
        let caja  = st.current_caja_id.clone().unwrap_or_else(|| "C0001".to_string());
        let color = st.current_color.clone().unwrap_or_else(|| "RED".to_string());
        let pid   = st.current_pallet_id;
        (caja, color, pid)
    };

    info!("[ESC1] Ordenando paletizar — caja={} color={} pallet={}", caja_id, color, pallet_id);

    let cmd = json!({
        "cmd":       "start",
        "id_pallet": pallet_id,
        "caja_id":   caja_id,
        "color":     color,
        "mode":      "pallet",
        "location":  "PALLET_1",
        "device":    "ESP32-S3",
    })
    .to_string();

    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::TOPIC_COBOT_ACTION, &cmd);
    }

    info!("[ESC1] Esperando FINISHED del cobot...");
    let finished_pallet = match cobot_evt_rx.recv_timeout(Duration::from_secs(60)) {
        Ok(pid) => {
            info!("[ESC1] Cobot FINISHED pallet_id={}", pid);
            pid
        }
        Err(_) => {
            error!("[ESC1] Timeout esperando FINISHED — abortando ciclo");
            let mut st = state.lock().unwrap();
            st.cobot_in_progress = false;
            return;
        }
    };

    let pallet_lleno = {
        let mut st = state.lock().unwrap();
        st.pallet_count += 1;
        let lleno = st.pallet_count >= config::PALLET_CAPACITY;
        if lleno {
            st.pallet_count      = 0;
            st.current_pallet_id += 1;
            info!("[ESC1] Pallet {} completo — nuevo pallet_id={}", finished_pallet, st.current_pallet_id);
        }
        lleno
    };

    let operario_id = if pallet_lleno {
        let op = query_operarios(mqtt, pull_slot);
        info!("[ESC1] Operario seleccionado: {:?}", op);
        op
    } else {
        None
    };

    publish_caja_paletizada(mqtt, &caja_id, finished_pallet, &color, pallet_lleno, operario_id);
}

// -----------------------------------------------------------------------
// ESCENARIO 2: DB (lote) → RoboDK → Cámara
// -----------------------------------------------------------------------
fn run_esc2_cycle(
    mqtt:        &Arc<Mutex<MqttManager<'static>>>,
    state:       &Arc<Mutex<DemoState>>,
    camera_rx:   &Receiver<String>,
    pull_slot:   &PullSlot,
    cap_counter: &mut u32,
) {
    let lote = match fetch_lote(mqtt, pull_slot) {
        Some(l) => l,
        None => {
            warn!("[ESC2] Sin lotes pendientes — reintentando en 60 s");
            thread::sleep(Duration::from_secs(60));
            return;
        }
    };

    info!("[ESC2] Lote obtenido: id={} color={} cantidad={}", lote.lote_id, lote.color, lote.quantity);

    let cap_id = format!("C{:04}", *cap_counter);
    *cap_counter += 1;

    {
        let mut st = state.lock().unwrap();
        st.current_caja_id = Some(cap_id.clone());
        st.current_color   = Some(lote.color.to_ascii_uppercase());
    }

    let spawn_cmd = json!({
        "cmd":     "spawn",
        "color":   lote.color,
        "cap_id":  cap_id,
        "lote_id": lote.lote_id,
        "device":  "ESP32-S3",
    })
    .to_string();

    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::TOPIC_ROBODK_ACTION, &spawn_cmd);
    }
    info!("[ESC2] Spawn enviado a RoboDK — cap_id={}", cap_id);

    let clasificada = match camera_rx.recv_timeout(Duration::from_secs(15)) {
        Ok(json_str) => {
            if let Ok(val) = serde_json::from_str::<Value>(&json_str) {
                let detected = val.get("cap_id").and_then(|v| v.as_str()).unwrap_or("?");
                let x        = val.get("x").and_then(|v| v.as_f64()).unwrap_or(0.0);
                let y        = val.get("y").and_then(|v| v.as_f64()).unwrap_or(0.0);
                let color    = val.get("color").and_then(|v| v.as_str()).unwrap_or("?");
                info!("[ESC2] Camara confirmó cap_id={} color={} pos=({:.1},{:.1})", detected, color, x, y);
                true
            } else {
                false
            }
        }
        Err(_) => {
            error!("[ESC2] Timeout esperando confirmación de cámara — continuando");
            false
        }
    };

    if clasificada {
        publish_tapa_clasificada(mqtt, &lote.lote_id, &cap_id);
    }

    thread::sleep(Duration::from_secs(3));
}

// -----------------------------------------------------------------------
// Helpers compartidos
// -----------------------------------------------------------------------

struct LoteInfo {
    lote_id:  String,
    quantity: i32,
    color:    String,
}

fn fetch_lote(mqtt: &Arc<Mutex<MqttManager<'static>>>, pull_slot: &PullSlot) -> Option<LoteInfo> {
    let (tx, rx) = sync_channel::<String>(1);
    { pull_slot.lock().unwrap().replace(tx); }

    let req = json!({"query": "lote_pendiente"}).to_string();
    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::TOPIC_DB_PULL, &req);
    }

    let result = match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(json_str) => serde_json::from_str::<Value>(&json_str).ok().and_then(|val| {
            if val.get("lote_id").and_then(|v| v.as_str()).is_none() {
                return None;
            }
            let lote_id  = val.get("lote_id")?.as_str()?.to_string();
            let quantity = val.get("quantity")?.as_i64()? as i32;
            let color    = val.get("color").and_then(|v| v.as_str()).unwrap_or("red").to_string();
            Some(LoteInfo { lote_id, quantity, color })
        }),
        Err(_) => {
            warn!("[ESC2] Timeout en db/pull/response para lote_pendiente");
            None
        }
    };

    pull_slot.lock().unwrap().take();
    result
}

fn query_operarios(mqtt: &Arc<Mutex<MqttManager<'static>>>, pull_slot: &PullSlot) -> Option<i32> {
    let (tx, rx) = sync_channel::<String>(1);
    { pull_slot.lock().unwrap().replace(tx); }

    let req = json!({"query": "operarios"}).to_string();
    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::TOPIC_DB_PULL, &req);
    }

    let result = match rx.recv_timeout(Duration::from_secs(5)) {
        Ok(json_str) => serde_json::from_str::<Value>(&json_str).ok().and_then(|val| {
            let lista = val.get("operarios")?.as_array()?;
            if lista.is_empty() {
                warn!("[ESC1] Bridge respondió sin operarios");
                return None;
            }
            let idx = (std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .subsec_nanos() as usize)
                % lista.len();
            let operario_id = lista[idx].get("operario_id").and_then(|v| v.as_i64()).map(|v| v as i32);
            let nombre = lista[idx].get("nombre").and_then(|v| v.as_str()).unwrap_or("?");
            info!("[ESC1] Elegido operario_id={:?} ({})", operario_id, nombre);
            operario_id
        }),
        Err(_) => {
            warn!("[ESC1] Timeout en db/pull/response para operarios");
            None
        }
    };

    pull_slot.lock().unwrap().take();
    result
}

fn publish_tapa_clasificada(
    mqtt:    &Arc<Mutex<MqttManager<'static>>>,
    lote_id: &str,
    cap_id:  &str,
) {
    let msg = json!({
        "event":   "tapa_clasificada",
        "lote_id": lote_id,
        "cap_id":  cap_id,
    })
    .to_string();

    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::TOPIC_DB_PUSH, &msg);
        info!("[ESC2] tapa_clasificada enviada — lote={} cap={}", lote_id, cap_id);
    }
}

fn publish_caja_paletizada(
    mqtt:        &Arc<Mutex<MqttManager<'static>>>,
    caja_id:     &str,
    pallet_id:   u32,
    color:       &str,
    estado:      bool,
    operario_id: Option<i32>,
) {
    let mut msg = json!({
        "event":        "caja_paletizada",
        "caja_id":      caja_id,
        "palet_id":     pallet_id,
        "codigo_palet": format!("PAL{:07}", pallet_id),
        "color_id":     color,
        "estado":       estado,
    });

    if let (true, Some(op_id)) = (estado, operario_id) {
        msg["operario_id"] = json!(op_id);
    }

    if let Ok(mut mg) = mqtt.try_lock() {
        mg.publish_text(config::TOPIC_DB_PUSH, &msg.to_string());
        info!("[ESC1] caja_paletizada — caja={} pallet={} estado={} operario={:?}", caja_id, pallet_id, estado, operario_id);
    }
}
