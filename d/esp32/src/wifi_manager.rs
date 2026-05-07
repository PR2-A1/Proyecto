use anyhow::Result;
use esp_idf_svc::{eventloop::EspSystemEventLoop, nvs::EspDefaultNvsPartition};
use log::error;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::Duration,
};

use crate::{config, wifi_connection};

pub fn spawn_wifi_manager(
    modem: esp_idf_hal::modem::Modem<'static>,
    sys_loop: EspSystemEventLoop,
    nvs: EspDefaultNvsPartition,
    wifi_ready: Arc<AtomicBool>,
) -> Result<()> {
    thread::Builder::new()
        .name("wifi-manager".into())
        .stack_size(8 * 1024)
        .spawn(move || {
            if let Err(e) = wifi_connection::run_wifi_manager(
                modem,
                sys_loop,
                nvs,
                config::WIFI_SSID,
                config::WIFI_PASS,
                wifi_ready,
            ) {
                error!("Tarea Wi-Fi terminó con error: {:?}", e);
            }
        })?;

    Ok(())
}

pub fn wait_until_ready(wifi_ready: &AtomicBool) {
    while !wifi_ready.load(Ordering::SeqCst) {
        log::info!("Esperando Wi-Fi...");
        thread::sleep(Duration::from_millis(500));
    }
}
