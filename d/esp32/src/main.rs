use esp_idf_hal::peripherals::Peripherals;
use esp_idf_svc::{eventloop::EspSystemEventLoop, nvs::EspDefaultNvsPartition};
use std::{
    sync::{atomic::AtomicBool, mpsc::sync_channel, Arc, Mutex},
    thread,
    time::Duration,
};

mod config;
mod state;
mod wifi_connection;
mod wifi_manager;
mod mqtt_manager;
mod logic_task;

fn main() -> anyhow::Result<()> {
    esp_idf_svc::sys::link_patches();
    esp_idf_svc::log::EspLogger::initialize_default();

    let peripherals = Peripherals::take().unwrap();
    let sys_loop    = EspSystemEventLoop::take().unwrap();
    let nvs         = EspDefaultNvsPartition::take().unwrap();

    // Wi-Fi
    let wifi_ready = Arc::new(AtomicBool::new(false));
    wifi_manager::spawn_wifi_manager(
        peripherals.modem,
        sys_loop,
        nvs,
        Arc::clone(&wifi_ready),
    )?;
    wifi_manager::wait_until_ready(&wifi_ready);

    // Estado compartido
    let demo_state = Arc::new(Mutex::new(state::DemoState::default()));

    // Canales MQTT → tarea lógica
    let (cobot_evt_tx, cobot_evt_rx) = sync_channel::<u32>(4);
    let (camera_tx,    camera_rx)    = sync_channel::<String>(16);
    let pull_slot = Arc::new(Mutex::new(None::<std::sync::mpsc::SyncSender<String>>));

    // Gestor MQTT
    let mqtt = Arc::new(Mutex::new(
        mqtt_manager::MqttManager::connect_and_subscribe(
            Arc::clone(&demo_state),
            cobot_evt_tx,
            camera_tx,
            Arc::clone(&pull_slot),
        )?,
    ));

    // Tarea lógica unificada (escenario 1 + escenario 2)
    let _logic_handle = logic_task::spawn_logic_task(
        Arc::clone(&mqtt),
        Arc::clone(&demo_state),
        cobot_evt_rx,
        camera_rx,
        pull_slot,
    )?;

    loop {
        thread::sleep(Duration::from_secs(60));
    }
}
