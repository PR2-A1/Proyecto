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

//Función de conexión Wi-Fi, que se encarga de configurar y conexión inicial, con manejo de errores para asegurar que cualquier fallo se reporte adecuadamente y se reintente la conexión.
pub fn connect_wifi<'a>(
    //Inicialización de variables y configuración de la conexión WIFI.
    modem: Modem<'a>,
    sys_loop: EspSystemEventLoop,
    nvs: EspDefaultNvsPartition,
    ssid: &str,
    password: &str,
) -> Result<BlockingWifi<EspWifi<'a>>> {
    //Creación de instancia WIFI con el fin de poder usar una API sin que se bloqueen tareas.
    let mut wifi = BlockingWifi::wrap(
        EspWifi::new(modem, sys_loop.clone(), Some(nvs))
            .context("No se pudo crear la interfaz Wi-Fi")?,
        sys_loop,
    )
    .context("No se pudo crear el wrapper BlockingWifi")?;

    //Desconexión y parada de cualquier conexión previa para asegurar un estado limpio antes de configurar la nueva conexión.
    let _ = wifi.disconnect();
    let _ = wifi.stop();

    //Configuración de la conexión Wi-Fi con los parámetros proporcionados, con manejo de errores para asegurar que cualquier problema en la configuración se reporte adecuadamente.
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

    //Inicio de conexión WIFI, donde se arranca el driver.
    wifi.start().context("No se pudo iniciar Wi-Fi")?;
    // Evita desconexiones frecuentes por modo de ahorro de energia del modem.
    esp!(unsafe { sys::esp_wifi_set_ps(sys::wifi_ps_type_t_WIFI_PS_NONE) })
        .context("No se pudo desactivar power-save de Wi-Fi")?;
    info!("Wi-Fi iniciado. Intentando conectar...");

    //Intento de conexión con reintentos
    let retry_delay = Duration::from_secs(2);

    loop {
        info!("Intentando conectar en modo WPA2 Personal");
        //Intento de conexión, con manejo de errores para asegurar que cualquier fallo se reporte adecuadamente y se reintente después de un delay.
        match wifi.connect() {
            //Espera a que la interfaz tenga IP, si falla lo vuelver a intentar en la siuiente iteración..
            Ok(_) => match wifi.wait_netif_up() {
                Ok(_) => {
                    info!("Wi-Fi conectado: IP obtenida con exito");
                    break;
                }
                Err(e) => {
                    error!("Sin IP aun, reintentando... Error: {:?}", e);
                }
            },
            Err(e) => {
                error!("Error al iniciar conexion Wi-Fi, reintentando... {:?}", e);
            }
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


//Función de la tarea de Wi-Fi, que se encarga de mantener la conexión activa y reconectar en caso de desconexión, con un delay entre intentos para evitar consumo excesivo de recursos.
pub fn run_wifi_manager<'a>(
    //Inicialización de variables y configuración de la conexión WIFI.
    modem: Modem<'a>,
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
        //Monitoreo del estado de la conexión Wi-Fi, con manejo de errores para asegurar que cualquier fallo en la consulta del estado se reporte adecuadamente y se intente reconectar si es necesario.
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

//Función de reconexión Wi-Fi, que se encarga de intentar reconectar en caso de desconexión, con manejo de errores para asegurar que cualquier fallo se reporte adecuadamente y se reintente después de un delay.
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
