//Librerias externas instaladas via Cargo
use anyhow::Result;
use core::num::NonZeroU32;
use esp_idf_hal::{
    delay::TickType,
    gpio::{Gpio10, Gpio38, Gpio39, Gpio48, InterruptType, PinDriver, Pull},
    task::notification::Notification,
};
use serde_json::json;

//Libreria estándar de Rust
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
        Mutex,
    },
};

//Modulos internos del proyecto
use crate::{config, control_state::ControlState, mqtt_manager::MqttManager};

//Mapea el source interno (botones / MQTT) a los valores admitidos por la colección NoSQL emergencias
fn map_source_to_nosql(source: &str) -> &'static str {
    match source {
        "emergency_button" | "resume_button" => "boton_fisico",
        _ => "mqtt_scada",
    }
}

//Función publica para ejecutar la tarea de emergencia, encargada de monitorear los botones, controlar el led y buzzer y notificar a través de MQTT
pub fn run_emergency_task<'a>(
    mqtt: Arc<Mutex<MqttManager<'a>>>,
    emergency_pin: Gpio38,
    resume_pin: Gpio39,
    led_pin: Gpio10,
    buzzer_pin: Gpio48,
    emergency_stop: Arc<AtomicBool>,
    control_state: Arc<Mutex<ControlState>>,
) -> Result<()> {
    //Declaración de pines y variables para el manejo de la emergencia
    let mut emergency_button = PinDriver::input(emergency_pin, Pull::Up)?;
    let mut resume_button = PinDriver::input(resume_pin, Pull::Up)?;
    let mut led = PinDriver::output(led_pin)?;
    let mut buzzer = PinDriver::output(buzzer_pin)?;
    let mut last_state = false;
    let mut pending_source: Option<&'static str> = None;

    //Configuración de interrupciones para los botones de emergencia y reanudación en flanco de bajada
    emergency_button.set_interrupt_type(InterruptType::NegEdge)?;
    resume_button.set_interrupt_type(InterruptType::NegEdge)?;

    loop {
        let notification = Notification::new();
        let emergency_waker = notification.notifier();
        let resume_waker = notification.notifier();
        let emergency_flag = Arc::new(AtomicBool::new(false));
        let resume_flag = Arc::new(AtomicBool::new(false));
        let emergency_flag_isr = Arc::clone(&emergency_flag);
        let resume_flag_isr = Arc::clone(&resume_flag);

        unsafe {
            //Suscripción a interrupción de botón de emergencia, setea la flag y notifica a la tarea para despertar al hilo que está esperando.
            emergency_button.subscribe_nonstatic(move || {
                emergency_flag_isr.store(true, Ordering::SeqCst);
                emergency_waker.notify(NonZeroU32::new(1).unwrap());
            })?;
            //Suscripción a interrupción de botón de readunación, setea la fla y notifica a la tarea para despertar al hilo que está esperando.
            resume_button.subscribe_nonstatic(move || {
                resume_flag_isr.store(true, Ordering::SeqCst);
                resume_waker.notify(NonZeroU32::new(2).unwrap());
            })?;
        }
        //Habilitación de interrupciones para ambos botones
        emergency_button.enable_interrupt()?;
        resume_button.enable_interrupt()?;

        //Espera de notificación por interrupción, con timeout para poder actualizar el estado del LED y buzzer aunque no haya cambios.
        let _ = notification.wait(TickType::new_millis(50).ticks());
        if emergency_flag.swap(false, Ordering::SeqCst) {
            emergency_stop.store(true, Ordering::SeqCst);
            pending_source = Some("emergency_button");
        } else if resume_flag.swap(false, Ordering::SeqCst) {
            emergency_stop.store(false, Ordering::SeqCst);
            pending_source = Some("resume_button");
        }
        //Actualización del estado del LED y buzzer según el estado de emergencia
        let current_state = emergency_stop.load(Ordering::SeqCst);
        if current_state != last_state {
            if current_state {
                let _ = led.set_high();
                let _ = buzzer.set_high();
            } else {
                let _ = led.set_low();
                let _ = buzzer.set_low();
            }

            let source = pending_source.unwrap_or("mqtt_action");
            let nosql_source = map_source_to_nosql(source);

            //NoSQL emergencias: registra inicio o resolución de la emergencia en el estado compartido
            if let Ok(mut state) = control_state.lock() {
                if current_state {
                    state.emergency_started_at = Some(std::time::Instant::now());
                    state.emergency_origin     = Some(nosql_source.to_string());
                } else if let (Some(started_at), Some(origin)) =
                    (state.emergency_started_at.take(), state.emergency_origin.take())
                {
                    let duracion = started_at.elapsed().as_secs();
                    state.emergency_event_pending = Some((duracion, origin, nosql_source.to_string()));
                }
            }

            if let Ok(mut mqtt_guard) = mqtt.lock() {
                let status = if current_state { "emergency_active" } else { "emergency_inactive" };
                let payload = json!({
                    "status": status,
                    "source": source,
                    "device": "ESP32-S3"
                })
                .to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_EMERGENCY_STATUS, &payload);
            }

            pending_source = None;
            last_state = current_state;
        }

    }
}