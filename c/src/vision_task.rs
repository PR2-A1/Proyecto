use anyhow::Result;
use log::{error, info};
use serde_json::Value;
use std::{
    sync::mpsc::{Receiver, SyncSender},
    thread,
};

#[derive(Clone, Debug)]
pub struct VisionSample {
    pub x: f32,
    pub y: f32,
    pub color: Option<String>,
    pub cap_id: String,
}

pub fn spawn_vision_task(
    input_rx: Receiver<String>,
    vision_tx: SyncSender<VisionSample>,
) -> Result<thread::JoinHandle<()>> {
    let handle = thread::Builder::new()
        .name("vision-task".to_string())
        .spawn(move || loop {
            let payload = match input_rx.recv() {
                Ok(payload) => payload,
                Err(_) => break,
            };

            let value = match serde_json::from_str::<Value>(&payload) {
                Ok(value) => value,
                Err(_) => {
                    error!("Vision payload invalido: {}", payload);
                    continue;
                }
            };

            let precision = value.get("precision").and_then(|v| v.as_f64()).unwrap_or(0.0);
            if precision <= 0.95 {
                info!("Vision ignorada por baja precision: {}", precision);
                continue;
            }

            let x = match value.get("x").and_then(|v| v.as_f64()) {
                Some(x) => x as f32,
                None => continue,
            };
            let y = match value.get("y").and_then(|v| v.as_f64()) {
                Some(y) => y as f32,
                None => continue,
            };
            let color = value.get("color").and_then(|v| v.as_str()).map(|s| s.to_string());
            let cap_id = value
                .get("cap_id")
                .and_then(|v| v.as_str())
                .map(|s| s.to_string())
                .unwrap_or_else(next_cap_id);

            let sample = VisionSample {
                x,
                y,
                color,
                cap_id,
            };

            let _ = vision_tx.try_send(sample);
        })?;

    Ok(handle)
}

fn next_cap_id() -> String {
    use std::sync::atomic::{AtomicU32, Ordering};
    static COUNTER: AtomicU32 = AtomicU32::new(1);
    let id = COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("cap_{}", id)
}