use anyhow::Result;
use core::num::NonZeroU32;
use esp_idf_hal::{
    delay::TickType,
    gpio::{Gpio10, Gpio38, Gpio39, Gpio11, InterruptType, PinDriver, Pull},
    task::notification::Notification,
};
use serde_json::json;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
        Mutex,
    },
};

use crate::{config, mqtt_manager::MqttManager};

pub fn run_emergency_task<'a>(
    mqtt: Arc<Mutex<MqttManager<'a>>>,
    emergency_pin: Gpio38,
    resume_pin: Gpio39,
    led_pin: Gpio10,
    buzzer_pin: Gpio11,
    emergency_stop: Arc<AtomicBool>,
) -> Result<()> {
    //Declaración de pines y variables para el manejo de la emergencia
    let mut emergency_button = PinDriver::input(emergency_pin, Pull::Up)?;
    let mut resume_button = PinDriver::input(resume_pin, Pull::Up)?;
    let mut led = PinDriver::output(led_pin)?;
    let mut buzzer = PinDriver::output(buzzer_pin)?;
    let mut last_state = false;
    let mut pending_source: Option<&'static str> = None;

    //Configuración de interrupciones para los botones de emergencia y reanudación
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
            //Suscripción a interrupción de botón de emergencia, setea la flah y notifica a la tarea para despertar al hilo que está esperando.
            emergency_button.subscribe_nonstatic(move || {
                emergency_flag_isr.store(true, Ordering::SeqCst);
                emergency_waker.notify(NonZeroU32::new(1).unwrap());
            })?;
            //Suscripción a interrupción de botón de readunación, setea la flah y notifica a la tarea para despertar al hilo que está esperando.
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

            if let Ok(mut mqtt_guard) = mqtt.lock() {
                let source = pending_source.unwrap_or("mqtt_action");
                let status = if current_state { "active" } else { "operative" };
                let payload = json!({
                    "status": status,
                    "device": "ESP32-S3",
                    "sensor": source
                })
                .to_string();
                mqtt_guard.publish_text(config::MQTT_TOPIC_EMERGENCY_STATUS, &payload);
            }

            pending_source = None;
            last_state = current_state;
        }

    }
}