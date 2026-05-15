use anyhow::{anyhow, Context, Result};
use esp_idf_hal::{cpu::Core, modem::Modem, task::thread::ThreadSpawnConfiguration};
use esp_idf_svc::{
    eventloop::EspSystemEventLoop,
    nvs::EspDefaultNvsPartition,
    sys::{self, esp},
    wifi::{AuthMethod, BlockingWifi, ClientConfiguration, Configuration, EspWifi, ScanMethod},
};
use log::{error, info};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread,
    time::Duration,
};

use crate::config;

const WIFI_CORE: Core = Core::Core0;

pub fn spawn_wifi_manager(
    modem: Modem<'static>,
    sys_loop: EspSystemEventLoop,
    nvs: EspDefaultNvsPartition,
    wifi_ready: Arc<AtomicBool>,
) -> Result<()> {
    let mut conf = ThreadSpawnConfiguration::default();
    conf.pin_to_core = Some(WIFI_CORE);
    conf.stack_size = conf.stack_size.max(8 * 1024);
    conf.priority = conf.priority.max(5);
    conf.set()?;

    thread::Builder::new()
        .name("wifi-manager".into())
        .spawn(move || {
            if let Err(e) = run_wifi_manager(
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

pub fn wait_until_ready(wifi_ready: &AtomicBool) {
    while !wifi_ready.load(Ordering::SeqCst) {
        info!("Esperando a que Wi-Fi este operativo...");
        thread::sleep(Duration::from_millis(500));
    }
}

fn run_wifi_manager(
    modem: Modem<'_>,
    sys_loop: EspSystemEventLoop,
    nvs: EspDefaultNvsPartition,
    ssid: &str,
    password: &str,
    wifi_ready: Arc<AtomicBool>,
) -> Result<()> {
    let mut wifi = connect_wifi(modem, sys_loop, nvs, ssid, password)?;
    wifi_ready.store(true, Ordering::SeqCst);

    let monitor_delay = Duration::from_secs(3);

    loop {
        match wifi.is_connected() {
            Ok(true) => {}
            Ok(false) => {
                wifi_ready.store(false, Ordering::SeqCst);
                error!("Wi-Fi desconectado. Reintentando reconexion...");
                reconnect_wifi(&mut wifi);
                wifi_ready.store(true, Ordering::SeqCst);
            }
            Err(e) => {
                wifi_ready.store(false, Ordering::SeqCst);
                error!("No se pudo consultar estado Wi-Fi: {:?}", e);
                reconnect_wifi(&mut wifi);
                wifi_ready.store(true, Ordering::SeqCst);
            }
        }
        thread::sleep(monitor_delay);
    }
}

fn connect_wifi<'a>(
    modem: Modem<'a>,
    sys_loop: EspSystemEventLoop,
    nvs: EspDefaultNvsPartition,
    ssid: &str,
    password: &str,
) -> Result<BlockingWifi<EspWifi<'a>>> {
    let mut wifi = BlockingWifi::wrap(
        EspWifi::new(modem, sys_loop.clone(), Some(nvs))
            .context("No se pudo crear la interfaz Wi-Fi")?,
        sys_loop,
    )
    .context("No se pudo crear el wrapper BlockingWifi")?;

    let _ = wifi.disconnect();
    let _ = wifi.stop();

    wifi.set_configuration(&Configuration::Client(ClientConfiguration {
        ssid: ssid
            .try_into()
            .map_err(|_| anyhow!("SSID invalido para la configuracion Wi-Fi"))?,
        password: password
            .try_into()
            .map_err(|_| anyhow!("Password invalido para la configuracion Wi-Fi"))?,
        auth_method: AuthMethod::WPA2Personal,
        scan_method: ScanMethod::FastScan,
        ..Default::default()
    }))
    .context("No se pudo establecer la configuracion Wi-Fi")?;

    wifi.start().context("No se pudo iniciar Wi-Fi")?;
    esp!(unsafe { sys::esp_wifi_set_ps(sys::wifi_ps_type_t_WIFI_PS_NONE) })
        .context("No se pudo desactivar power-save de Wi-Fi")?;
    info!("Wi-Fi iniciado. Intentando conectar...");

    let retry_delay = Duration::from_secs(2);
    loop {
        info!("Intentando conectar en modo WPA2 Personal");
        match wifi.connect() {
            Ok(_) => match wifi.wait_netif_up() {
                Ok(_) => {
                    info!("Wi-Fi conectado: IP obtenida con exito");
                    break;
                }
                Err(e) => error!("Sin IP aun, reintentando... Error: {:?}", e),
            },
            Err(e) => error!("Error al iniciar conexion Wi-Fi, reintentando... {:?}", e),
        }
        let _ = wifi.disconnect();
        let _ = wifi.stop();
        thread::sleep(retry_delay);
        if let Err(e) = wifi.start() {
            error!("No se pudo reiniciar Wi-Fi: {:?}", e);
        }
    }

    Ok(wifi)
}

fn reconnect_wifi<'a>(wifi: &mut BlockingWifi<EspWifi<'a>>) {
    let retry_delay = Duration::from_secs(3);
    loop {
        let _ = wifi.disconnect();
        let _ = wifi.stop();
        thread::sleep(retry_delay);
        if let Err(e) = wifi.start() {
            error!("No se pudo reiniciar Wi-Fi en reconexion: {:?}", e);
            continue;
        }
        match wifi.connect() {
            Ok(_) => match wifi.wait_netif_up() {
                Ok(_) => {
                    info!("Wi-Fi reconectado y con IP");
                    break;
                }
                Err(e) => {
                    error!("Conectado sin IP valida todavia: {:?}", e);
                    thread::sleep(retry_delay);
                }
            },
            Err(e) => {
                error!("Fallo en reconexion Wi-Fi: {:?}", e);
                thread::sleep(retry_delay);
            }
        }
    }
}
