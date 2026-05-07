use anyhow::Result;
use esp_idf_hal::{cpu::Core, modem::Modem, task::thread::ThreadSpawnConfiguration};
use esp_idf_svc::{eventloop::EspSystemEventLoop, nvs::EspDefaultNvsPartition};
use log::{error, info};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::Duration,
};

use crate::{config, wifi_connection};

const WIFI_CORE: Core = Core::Core0;

pub fn spawn_wifi_manager(
    modem: Modem<'static>,
    sys_loop: EspSystemEventLoop,
    nvs: EspDefaultNvsPartition,
    wifi_ready: Arc<AtomicBool>,
) -> Result<()> {
    //Configuración del hilo para ejecutar la tarea del WIFI, con stack y prioridad adecuados para evitar problemas de estabilidad.
    let mut conf = ThreadSpawnConfiguration::default();
    conf.pin_to_core = Some(WIFI_CORE);
    conf.stack_size = conf.stack_size.max(8 * 1024);
    conf.priority = conf.priority.max(5);
    conf.set()?;

    //Creación del hilo para manejar la conexión Wi-Fi, con manejo de errores para asegurar que cualquier fallo se maneje adecuadamente.
    thread::Builder::new()
        .name("wifi-manager".into())
        .spawn(move || {
            if let Err(e) = wifi_connection::run_wifi_manager(
                modem,
                sys_loop,
                nvs,
                config::WIFI_SSID,
                config::WIFI_PASS,
                wifi_ready,
            ) {
                error!("La tarea de Wi-Fi termino con error: {:?}", e);
            }
        })?;

    ThreadSpawnConfiguration::default().set()?;
    Ok(())
}

//Funcion de espera activa para asegurar que el Wi-Fi esté operativo antes de continuar con las tareas dependientes, con un pequeño delay para evitar consumo excesivo de CPU.
pub fn wait_until_ready(wifi_ready: &AtomicBool) {
    while !wifi_ready.load(Ordering::SeqCst) {
        info!("Esperando a que Wi-Fi este operativo...");
        thread::sleep(Duration::from_millis(500));
    }
}
