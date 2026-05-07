use anyhow::{anyhow, Context, Result};
use esp_idf_hal::modem::Modem;
use esp_idf_svc::{
    eventloop::EspSystemEventLoop,
    nvs::EspDefaultNvsPartition,
    sys::{self, esp},
    wifi::{AuthMethod, BlockingWifi, ClientConfiguration, Configuration, EspWifi, ScanMethod},
};
use log::{error, info};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::{thread, time::Duration};

pub fn connect_wifi<'a>(
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
            .map_err(|_| anyhow!("SSID invalido"))?,
        password: password
            .try_into()
            .map_err(|_| anyhow!("Password invalido"))?,
        auth_method: AuthMethod::WPA2Personal,
        scan_method: ScanMethod::FastScan,
        ..Default::default()
    }))
    .context("No se pudo establecer la configuracion Wi-Fi")?;

    wifi.start().context("No se pudo iniciar Wi-Fi")?;
    esp!(unsafe { sys::esp_wifi_set_ps(sys::wifi_ps_type_t_WIFI_PS_NONE) })
        .context("No se pudo desactivar power-save Wi-Fi")?;

    info!("Wi-Fi iniciado. Intentando conectar...");
    let retry_delay = Duration::from_secs(2);

    loop {
        match wifi.connect() {
            Ok(_) => match wifi.wait_netif_up() {
                Ok(_) => {
                    info!("Wi-Fi conectado: IP obtenida");
                    break;
                }
                Err(e) => error!("Sin IP, reintentando... {:?}", e),
            },
            Err(e) => error!("Error Wi-Fi, reintentando... {:?}", e),
        }
        let _ = wifi.disconnect();
        let _ = wifi.stop();
        thread::sleep(retry_delay);
        let _ = wifi.start();
    }

    Ok(wifi)
}

pub fn run_wifi_manager<'a>(
    modem: Modem<'a>,
    sys_loop: EspSystemEventLoop,
    nvs: EspDefaultNvsPartition,
    ssid: &str,
    password: &str,
    wifi_ready: Arc<AtomicBool>,
) -> Result<()> {
    let mut wifi = connect_wifi(modem, sys_loop, nvs, ssid, password)?;
    wifi_ready.store(true, Ordering::SeqCst);

    loop {
        thread::sleep(Duration::from_secs(3));
        match wifi.is_connected() {
            Ok(true) => {}
            _ => {
                wifi_ready.store(false, Ordering::SeqCst);
                error!("Wi-Fi desconectado. Reconectando...");
                reconnect_wifi(&mut wifi);
                wifi_ready.store(true, Ordering::SeqCst);
            }
        }
    }
}

fn reconnect_wifi<'a>(wifi: &mut BlockingWifi<EspWifi<'a>>) {
    loop {
        let _ = wifi.disconnect();
        let _ = wifi.stop();
        thread::sleep(Duration::from_secs(3));
        if wifi.start().is_err() {
            continue;
        }
        match wifi.connect() {
            Ok(_) => match wifi.wait_netif_up() {
                Ok(_) => {
                    info!("Wi-Fi reconectado");
                    break;
                }
                Err(e) => error!("Conectado sin IP: {:?}", e),
            },
            Err(e) => error!("Fallo reconexion: {:?}", e),
        }
    }
}
