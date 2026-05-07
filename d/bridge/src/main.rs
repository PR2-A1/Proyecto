use anyhow::{Context, Result};
use dotenvy::dotenv;
use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS};
use serde_json::Value;
use std::{env, time::Duration};
use tokio_postgres::NoTls;
use tracing::{error, info, warn};

const TOPIC_DB_PUSH:      &str = "giirob/pr2-A1/db/push";
const TOPIC_DB_PULL:      &str = "giirob/pr2-A1/db/pull";
const TOPIC_PULL_RESP:    &str = "giirob/pr2-A1/db/pull/response";

// -----------------------------------------------------------------------
// Estructuras de datos para los eventos del ESP32
// -----------------------------------------------------------------------

#[derive(Debug)]
struct CajaPaletizadaEvent {
    caja_id:     String,
    palet_id:    i32,
    codigo_palet: String,
    color_id:    String,
    estado:      bool,
    operario_id: Option<i32>,
}

// -----------------------------------------------------------------------
// Parsers
// -----------------------------------------------------------------------

fn parse_caja_paletizada(v: &Value) -> Option<CajaPaletizadaEvent> {
    let caja_id      = v.get("caja_id").and_then(|x| x.as_str()).filter(|s| !s.is_empty())?;
    let palet_id     = v.get("palet_id").and_then(|x| x.as_i64())? as i32;
    let codigo_palet = v.get("codigo_palet").and_then(|x| x.as_str()).filter(|s| !s.is_empty())?;
    let color_id     = v.get("color_id").and_then(|x| x.as_str()).filter(|s| !s.is_empty())?;
    let estado       = v.get("estado").and_then(|x| x.as_bool()).unwrap_or(false);
    let operario_id  = if estado {
        v.get("operario_id").and_then(|x| x.as_i64()).map(|x| x as i32)
    } else {
        None
    };

    if palet_id <= 0 { return None; }

    Some(CajaPaletizadaEvent {
        caja_id:      caja_id.to_string(),
        palet_id,
        codigo_palet: codigo_palet.to_string(),
        color_id:     color_id.to_string(),
        estado,
        operario_id,
    })
}

// -----------------------------------------------------------------------
// Punto de entrada
// -----------------------------------------------------------------------

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    // Busca .env junto al ejecutable y luego en el directorio actual
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            let _ = dotenvy::from_path(exe_dir.join(".env"));
        }
    }
    let _ = dotenv();

    let mqtt_host      = env::var("MQTT_HOST").unwrap_or_else(|_| "broker.hivemq.com".into());
    let mqtt_port: u16 = env::var("MQTT_PORT").unwrap_or_else(|_| "1883".into()).parse()?;
    let mqtt_client_id = env::var("MQTT_CLIENT_ID").unwrap_or_else(|_| "mqtt-db-bridge-demo".into());
    let database_url   = env::var("DATABASE_URL").context("DATABASE_URL requerida en .env")?;

    // ----------------------------------------------------------------
    // MQTT
    // ----------------------------------------------------------------
    info!("Conectando a MQTT {}:{}", mqtt_host, mqtt_port);
    let mut opts = MqttOptions::new(mqtt_client_id, mqtt_host, mqtt_port);
    opts.set_keep_alive(Duration::from_secs(30));

    let (mqtt, mut eventloop) = AsyncClient::new(opts, 10);
    mqtt.subscribe(TOPIC_DB_PUSH, QoS::AtLeastOnce).await?;
    mqtt.subscribe(TOPIC_DB_PULL, QoS::AtLeastOnce).await?;
    info!("Suscrito a {} y {}", TOPIC_DB_PUSH, TOPIC_DB_PULL);

    // ----------------------------------------------------------------
    // PostgreSQL
    // ----------------------------------------------------------------
    info!("Conectando a PostgreSQL...");
    let (pg, conn) = tokio_postgres::connect(&database_url, NoTls).await?;
    tokio::spawn(async move {
        if let Err(e) = conn.await { error!("PostgreSQL connection error: {e}"); }
    });
    info!("PostgreSQL conectado");

    // Preparar sentencias SQL reutilizables
    let upsert_palet = pg.prepare(
        "INSERT INTO palet (palet_id, codigo_palet, color_id, estado)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (palet_id) DO UPDATE SET estado = EXCLUDED.estado",
    ).await?;

    let link_caja_palet = pg.prepare(
        "UPDATE caja SET palet_id = $1 WHERE caja_id = $2",
    ).await?;

    let set_operario_cierre = pg.prepare(
        "UPDATE palet SET operario_cierre_id = $1 WHERE palet_id = $2",
    ).await?;

    let query_operarios_stmt = pg.prepare(
        "SELECT operario_id, nombre, apellido FROM operario",
    ).await?;

    let query_lote_pendiente = pg.prepare(
        "SELECT lote_id, total_tapas_entrada - total_tapas_clasificadas AS pendientes
         FROM material_no_clasificado
         WHERE total_tapas_clasificadas < total_tapas_entrada
         ORDER BY fecha_inicio ASC
         LIMIT 1",
    ).await?;

    let inc_tapas_clasificadas = pg.prepare(
        "UPDATE material_no_clasificado
         SET total_tapas_clasificadas = total_tapas_clasificadas + 1
         WHERE lote_id = $1
           AND total_tapas_clasificadas < total_tapas_entrada",
    ).await?;

    info!("Bridge listo — esperando mensajes MQTT...");

    // ----------------------------------------------------------------
    // Bucle principal de eventos
    // ----------------------------------------------------------------
    loop {
        match eventloop.poll().await {
            Ok(Event::Incoming(Packet::Publish(pub_msg))) => {
                let topic   = pub_msg.topic.as_str();
                let payload = String::from_utf8_lossy(&pub_msg.payload).to_string();
                info!("Mensaje en [{}]: {}", topic, payload);

                match topic {
                    TOPIC_DB_PUSH => handle_db_push(
                        &pg,
                        &payload,
                        &upsert_palet,
                        &link_caja_palet,
                        &set_operario_cierre,
                        &inc_tapas_clasificadas,
                    ).await,

                    TOPIC_DB_PULL => handle_db_pull(
                        &pg,
                        &mqtt,
                        &payload,
                        &query_operarios_stmt,
                        &query_lote_pendiente,
                    ).await,

                    _ => {}
                }
            }
            Err(e) => {
                error!("Error en eventloop MQTT: {:?} — reintentando en 5 s", e);
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
            _ => {}
        }
    }
}

// -----------------------------------------------------------------------
// Handler: db/push
// Procesa el evento caja_paletizada publicado por el ESP32 tras recibir
// FINISHED del cobot.
// -----------------------------------------------------------------------
async fn handle_db_push(
    pg:                      &tokio_postgres::Client,
    payload:                 &str,
    upsert_palet:            &tokio_postgres::Statement,
    link_caja_palet:         &tokio_postgres::Statement,
    set_op_cierre:           &tokio_postgres::Statement,
    inc_tapas_clasificadas:  &tokio_postgres::Statement,
) {
    let Ok(val) = serde_json::from_str::<Value>(payload) else {
        error!("JSON invalido en db/push: {}", payload);
        return;
    };

    let event = val.get("event").and_then(|v| v.as_str()).unwrap_or("");

    if event.eq_ignore_ascii_case("caja_paletizada") {
        let Some(ev) = parse_caja_paletizada(&val) else {
            warn!("caja_paletizada con campos faltantes: {}", payload);
            return;
        };

        info!(
            "Paletizando: caja={} palet={} estado={}",
            ev.caja_id, ev.palet_id, ev.estado
        );

        // 1. UPSERT del palet (crea o actualiza estado)
        match pg.execute(upsert_palet, &[&ev.palet_id, &ev.codigo_palet, &ev.color_id, &ev.estado]).await {
            Ok(_)  => info!("Palet {} upserted", ev.palet_id),
            Err(e) => { error!("Error upsertando palet: {:?}", e); return; }
        }

        // 2. Vincular caja al palet
        match pg.execute(link_caja_palet, &[&ev.palet_id, &ev.caja_id]).await {
            Ok(n)  => info!("Caja {} vinculada a palet {} ({} filas)", ev.caja_id, ev.palet_id, n),
            Err(e) => error!("Error vinculando caja a palet: {:?}", e),
        }

        // 3. Asignar operario de cierre si el palet queda cerrado
        if ev.estado {
            if let Some(op_id) = ev.operario_id {
                match pg.execute(set_op_cierre, &[&op_id, &ev.palet_id]).await {
                    Ok(_)  => info!("Operario {} asignado como cierre del palet {}", op_id, ev.palet_id),
                    Err(e) => error!("Error asignando operario_cierre: {:?}", e),
                }
            } else {
                warn!("Palet {} cerrado sin operario_id", ev.palet_id);
            }
        }
    } else if event.eq_ignore_ascii_case("tapa_clasificada") {
        let lote_id = val.get("lote_id").and_then(|v| v.as_str()).unwrap_or("");
        if lote_id.is_empty() {
            warn!("tapa_clasificada sin lote_id: {}", payload);
            return;
        }
        match pg.execute(inc_tapas_clasificadas, &[&lote_id]).await {
            Ok(n) if n > 0 => info!("Tapa clasificada en lote {} ({} filas)", lote_id, n),
            Ok(_)          => warn!("Lote {} no encontrado o ya completo", lote_id),
            Err(e)         => error!("Error incrementando clasificadas en {}: {:?}", lote_id, e),
        }
    } else {
        warn!("Evento desconocido en db/push: {}", event);
    }
}

// -----------------------------------------------------------------------
// Handler: db/pull
// Atiende dos tipos de consulta:
//   "operarios"      — lista de operarios activos (escenario 1)
//   "lote_pendiente" — primer lote sin clasificar (escenario 2)
// -----------------------------------------------------------------------
async fn handle_db_pull(
    pg:               &tokio_postgres::Client,
    mqtt:             &AsyncClient,
    payload:          &str,
    q_operarios:      &tokio_postgres::Statement,
    q_lote_pendiente: &tokio_postgres::Statement,
) {
    let Ok(val) = serde_json::from_str::<Value>(payload) else {
        error!("JSON invalido en db/pull: {}", payload);
        return;
    };

    let query = val.get("query").and_then(|v| v.as_str()).unwrap_or("");

    match query {
        // ------------------------------------------------------------
        // Escenario 1: devuelve la lista de operarios activos.
        // El ESP32 elegirá uno al azar para asignarlo como operario
        // de cierre del pallet.
        // ------------------------------------------------------------
        q if q.eq_ignore_ascii_case("operarios") => {
            match pg.query(q_operarios, &[]).await {
                Ok(rows) => {
                    let lista: Vec<serde_json::Value> = rows.iter().map(|r| {
                        let id:       i32  = r.get(0);
                        let nombre:   &str = r.get(1);
                        let apellido: &str = r.get(2);
                        serde_json::json!({
                            "operario_id": id,
                            "nombre":      nombre,
                            "apellido":    apellido,
                        })
                    }).collect();

                    let resp = serde_json::json!({ "operarios": lista }).to_string();
                    publish_response(mqtt, &resp).await;
                    info!("Operarios enviados: {} registros", rows.len());
                }
                Err(e) => error!("Error consultando operarios: {:?}", e),
            }
        }

        // ------------------------------------------------------------
        // Escenario 2: devuelve el primer lote con tapas pendientes.
        // El ESP32 usará el lote para generar la tapa en RoboDK.
        // ------------------------------------------------------------
        q if q.eq_ignore_ascii_case("lote_pendiente") => {
            match pg.query_opt(q_lote_pendiente, &[]).await {
                Ok(Some(row)) => {
                    let lote_id:    &str = row.get(0);
                    let pendientes: i32  = row.get(1);
                    let resp = serde_json::json!({
                        "lote_id":  lote_id,
                        "quantity": pendientes,
                        "color":    "red",   // el color lo decide el sistema al clasificar
                    })
                    .to_string();
                    publish_response(mqtt, &resp).await;
                    info!("Lote pendiente enviado: {} ({} tapas)", lote_id, pendientes);
                }
                Ok(None) => {
                    // Demo en bucle: resetear todos los lotes y devolver null.
                    // El ESP32 duerme 10 s y en la siguiente consulta ya tendrá lotes.
                    match pg.execute(
                        "UPDATE material_no_clasificado SET total_tapas_clasificadas = 0",
                        &[],
                    ).await {
                        Ok(n)  => info!("Demo reset: {} lotes reiniciados a clasificadas=0", n),
                        Err(e) => error!("Error reseteando lotes: {:?}", e),
                    }
                    let resp = serde_json::json!({ "lote_id": null }).to_string();
                    publish_response(mqtt, &resp).await;
                    warn!("Todos los lotes completados — demo reiniciado automáticamente");
                }
                Err(e) => error!("Error consultando lote_pendiente: {:?}", e),
            }
        }

        other => warn!("db/pull query desconocida: {}", other),
    }
}

async fn publish_response(mqtt: &AsyncClient, payload: &str) {
    if let Err(e) = mqtt.publish(TOPIC_PULL_RESP, QoS::AtLeastOnce, false, payload.as_bytes()).await {
        error!("Error publicando en db/pull/response: {:?}", e);
    }
}
