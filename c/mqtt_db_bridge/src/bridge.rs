use anyhow::{Context, Result};
use dotenvy::dotenv;
use rumqttc::{AsyncClient, Event, MqttOptions, Packet, QoS};
use serde_json::Value;
use std::time::Duration;
use std::{env, fs, path::Path};
use tokio_postgres::NoTls;
use tracing::{error, info, warn};

#[derive(Debug, PartialEq, Eq)]
struct BoxCompletedEvent {
    id_caja: String,
    color_db: String,
    etiqueta: String,
    estado: bool,
    lotes: Vec<String>,
}

#[derive(Debug, PartialEq, Eq)]
struct GenCommand {
    proveedor: Option<String>,
    id_lote: String,
    quantity: i32,
}

#[derive(Debug, PartialEq, Eq)]
struct CajaPaletizadaEvent {
    id_caja:     String,
    id_palet:    String,
    id_color:    String,
    estado:      bool,
    id_operario: Option<String>,
}

fn env_or_default(key: &str, default: &str) -> String {
    env::var(key).unwrap_or_else(|_| default.to_string())
}

fn parse_topics(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(|t| t.trim())
        .filter(|t| !t.is_empty())
        .map(|t| t.to_string())
        .collect()
}

fn read_database_url_from_env_file() -> Option<String> {
    let env_path = Path::new(env!("CARGO_MANIFEST_DIR")).join(".env");
    let content = fs::read_to_string(env_path).ok()?;
    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') {
            continue;
        }
        if let Some(value) = trimmed.strip_prefix("DATABASE_URL=") {
            return Some(value.trim().to_string());
        }
    }
    None
}

fn parse_box_completed_event(value: &Value) -> Option<BoxCompletedEvent> {
    let id_caja = value.get("id_caja").and_then(|v| v.as_str()).unwrap_or("");
    let color = value.get("color").and_then(|v| v.as_str()).unwrap_or("");
    let etiqueta = value
        .get("codigo_etiqueta")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let estado = value
        .get("estado")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);

    if id_caja.is_empty() || color.is_empty() || etiqueta.is_empty() {
        return None;
    }

    let lotes = value
        .get("lotes")
        .and_then(|v| v.as_array())
        .map(|lotes| {
            lotes
                .iter()
                .filter_map(|lote| lote.as_str())
                .filter(|lote| !lote.is_empty())
                .map(|lote| lote.to_string())
                .collect()
        })
        .unwrap_or_default();

    Some(BoxCompletedEvent {
        id_caja: id_caja.to_string(),
        color_db: color.to_ascii_uppercase(),
        etiqueta: etiqueta.to_string(),
        estado,
        lotes,
    })
}

fn parse_gen_command(value: &Value) -> Option<GenCommand> {
    let proveedor = value
        .get("proveedor")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string());
    let id_lote = value
        .get("id_lote")
        .and_then(|v| v.as_str())
        .or_else(|| value.get("lote").and_then(|v| v.as_str()))
        .unwrap_or("");
    let quantity = value.get("quantity").and_then(|v| v.as_i64()).unwrap_or(0) as i32;

    if id_lote.is_empty() || quantity <= 0 {
        return None;
    }

    Some(GenCommand {
        proveedor,
        id_lote: id_lote.to_string(),
        quantity,
    })
}

fn parse_caja_paletizada(value: &Value) -> Option<CajaPaletizadaEvent> {
    let id_caja  = value.get("id_caja").and_then(|v| v.as_str()).unwrap_or("");
    let id_palet = value.get("id_palet").and_then(|v| v.as_str()).unwrap_or("");
    let id_color = value.get("id_color").and_then(|v| v.as_str()).unwrap_or("");
    let estado   = value.get("estado").and_then(|v| v.as_bool()).unwrap_or(false);

    if id_caja.is_empty() || id_palet.is_empty() || id_color.is_empty() {
        return None;
    }

    let id_operario = if estado {
        value.get("id_operario").and_then(|v| v.as_str()).map(|v| v.to_string())
    } else {
        None
    };

    Some(CajaPaletizadaEvent {
        id_caja:  id_caja.to_string(),
        id_palet: id_palet.to_string(),
        id_color: id_color.to_string(),
        estado,
        id_operario,
    })
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt::init();

    if dotenv().is_err() {
        let env_path = Path::new(env!("CARGO_MANIFEST_DIR")).join(".env");
        let _ = dotenvy::from_path(&env_path);
    }

    let mqtt_host = env_or_default("MQTT_HOST", "broker.hivemq.com");
    let mqtt_port: u16 = env_or_default("MQTT_PORT", "1883")
        .parse()
        .context("MQTT_PORT must be a valid u16")?;
    let mqtt_client_id = env_or_default("MQTT_CLIENT_ID", "mqtt-db-bridge");
    let topics_raw = env_or_default(
        "MQTT_TOPICS",
        "giirob/pr2-A1/db/push,giirob/pr2-A1/db/pull,giirob/pr2-A1/devices/scada/action",
    );
    let topics = parse_topics(&topics_raw);

    let database_url = env::var("DATABASE_URL")
        .ok()
        .or_else(read_database_url_from_env_file)
        .context("DATABASE_URL is required. Check mqtt_db_bridge/.env")?;

    info!("Conectando a MQTT {}:{}", mqtt_host, mqtt_port);
    let mut mqtt_options = MqttOptions::new(mqtt_client_id, mqtt_host, mqtt_port);
    mqtt_options.set_keep_alive(Duration::from_secs(30));

    let (mqtt, mut eventloop) = AsyncClient::new(mqtt_options, 10);
    for topic in &topics {
        mqtt.subscribe(topic, QoS::AtLeastOnce).await?;
        info!("Suscrito a: {}", topic);
    }

    info!("Conectando a PostgreSQL...");
    let (pg, connection) = tokio_postgres::connect(&database_url, NoTls).await?;
    tokio::spawn(async move {
        if let Err(err) = connection.await {
            error!("PostgreSQL connection error: {err}");
        }
    });
    info!("PostgreSQL conectado");

    let insert_caja_stmt = pg
        .prepare(
            "INSERT INTO caja (id_caja, color, codigo_etiqueta, estado, id_palet) \
             VALUES ($1, $2, $3, $4, NULL) \
             ON CONFLICT (id_caja) DO UPDATE \
             SET color = EXCLUDED.color, \
                 codigo_etiqueta = EXCLUDED.codigo_etiqueta, \
                 estado = EXCLUDED.estado",
        )
        .await?;

    let insert_material_caja_stmt = pg
        .prepare(
            "INSERT INTO material_caja (lote, id_caja) \
             VALUES ($1, $2) \
             ON CONFLICT (lote, id_caja) DO NOTHING",
        )
        .await?;

    let insert_lote_stmt = pg
        .prepare(
            "INSERT INTO lote \
             (id_lote, fecha_inicio, total_tapas_entrada, total_tapas_clasificadas, observaciones) \
             VALUES ($1, CURRENT_DATE, $2, 0, NULL) \
             ON CONFLICT (id_lote) DO NOTHING",
        )
        .await?;

    let insert_proveedor_material_stmt = pg
        .prepare(
            "INSERT INTO proveedor_material (proveedor, lote) \
             VALUES ($1, $2) \
             ON CONFLICT (proveedor, lote) DO NOTHING",
        )
        .await?;

    let upsert_palet_stmt = pg
        .prepare(
            "INSERT INTO palet (id_palet, id_color, estado) \
             VALUES ($1, $2, $3) \
             ON CONFLICT (id_palet) DO UPDATE \
             SET estado = EXCLUDED.estado",
        )
        .await?;

    let link_caja_palet_stmt = pg
        .prepare("UPDATE caja SET id_palet = $1 WHERE id_caja = $2")
        .await?;

    let set_operario_cierre_stmt = pg
        .prepare("UPDATE palet SET id_operario = $1 WHERE id_palet = $2")
        .await?;

    info!("Bridge listo, esperando mensajes...");

    loop {
        if let Event::Incoming(Packet::Publish(publish)) = eventloop.poll().await? {
            let topic = publish.topic.clone();
            let payload = String::from_utf8_lossy(&publish.payload).to_string();
            info!("Mensaje recibido en [{}]: {}", topic, payload);

            if topic == "giirob/pr2-A1/db/push" {
                match serde_json::from_str::<Value>(&payload) {
                    Ok(value) => {
                        let event = value.get("event").and_then(|v| v.as_str()).unwrap_or("");
                        info!("Evento: {}", event);

                        if event.eq_ignore_ascii_case("box_completed") {
                            if let Some(event) = parse_box_completed_event(&value) {
                                info!(
                                    "Insertando caja: id={} color={} etiqueta={} estado={}",
                                    event.id_caja, event.color_db, event.etiqueta, event.estado
                                );

                                match pg
                                    .execute(
                                        &insert_caja_stmt,
                                        &[
                                            &event.id_caja,
                                            &event.color_db,
                                            &event.etiqueta,
                                            &event.estado,
                                        ],
                                    )
                                    .await
                                {
                                    Ok(rows) => {
                                        info!("Caja insertada/actualizada ({} filas)", rows)
                                    }
                                    Err(e) => error!("Error insertando caja: {:?}", e),
                                }

                                for lote_id in event.lotes {
                                    match pg
                                        .execute(
                                            &insert_material_caja_stmt,
                                            &[&lote_id, &event.id_caja],
                                        )
                                        .await
                                    {
                                        Ok(_) => info!(
                                            "material_caja insertado: lote={} caja={}",
                                            lote_id, event.id_caja
                                        ),
                                        Err(e) => {
                                            error!("Error insertando material_caja: {}", e)
                                        }
                                    }
                                }
                            } else {
                                warn!("caja_ready sin datos requeridos: {}", payload);
                            }
                        } else if event.eq_ignore_ascii_case("caja_paletizada") {
                            if let Some(ev) = parse_caja_paletizada(&value) {
                                info!(
                                    "Paletizando caja: caja={} palet={} estado={}",
                                    ev.id_caja, ev.id_palet, ev.estado
                                );

                                match pg
                                    .execute(
                                        &upsert_palet_stmt,
                                        &[&ev.id_palet, &ev.id_color, &ev.estado],
                                    )
                                    .await
                                {
                                    Ok(_) => info!("Palet upserted: id={}", ev.id_palet),
                                    Err(e) => error!("Error upsertando palet: {:?}", e),
                                }

                                match pg
                                    .execute(&link_caja_palet_stmt, &[&ev.id_palet, &ev.id_caja])
                                    .await
                                {
                                    Ok(rows) => info!("Caja {} vinculada a palet {} ({} filas)", ev.id_caja, ev.id_palet, rows),
                                    Err(e) => error!("Error vinculando caja a palet: {:?}", e),
                                }

                                if ev.estado {
                                    if let Some(ref operario_id) = ev.id_operario {
                                        match pg.execute(&set_operario_cierre_stmt, &[operario_id, &ev.id_palet]).await {
                                            Ok(_) => info!("Operario {} asignado como cierre del palet {}", operario_id, ev.id_palet),
                                            Err(e) => error!("Error asignando operario_cierre: {:?}", e),
                                        }
                                    } else {
                                        warn!("Palet {} cerrado sin id_operario — no se asigna cierre", ev.id_palet);
                                    }
                                }
                            } else {
                                warn!("caja_paletizada sin datos requeridos: {}", payload);
                            }
                        } else {
                            warn!("Evento desconocido: {}", event);
                        }
                    }
                    Err(e) => error!("JSON inválido en topic db: {} — {}", e, payload),
                }
            }

            if topic == "giirob/pr2-A1/devices/scada/action" {
                match serde_json::from_str::<Value>(&payload) {
                    Ok(value) => {
                        let cmd = value.get("cmd").and_then(|v| v.as_str()).unwrap_or("");
                        info!("Comando SCADA: {}", cmd);

                        if cmd.eq_ignore_ascii_case("gen") {
                            if let Some(command) = parse_gen_command(&value) {
                                info!(
                                    "Insertando lote: id={} quantity={} proveedor={:?}",
                                    command.id_lote, command.quantity, command.proveedor
                                );

                                match pg
                                    .execute(
                                        &insert_lote_stmt,
                                        &[&command.id_lote, &command.quantity],
                                    )
                                    .await
                                {
                                    Ok(rows) => info!("Lote insertado ({} filas)", rows),
                                    Err(e) => error!("Error insertando lote: {:?}", e),
                                }

                                if let Some(ref proveedor) = command.proveedor {
                                    match pg
                                        .execute(
                                            &insert_proveedor_material_stmt,
                                            &[proveedor, &command.id_lote],
                                        )
                                        .await
                                    {
                                        Ok(rows) => {
                                            info!("Proveedor insertado ({} filas)", rows)
                                        }
                                        Err(e) => error!("Error insertando proveedor: {:?}", e),
                                    }
                                }
                            } else {
                                warn!("gen sin id_lote o quantity inválido: {}", payload);
                            }
                        } else {
                            warn!("Comando SCADA desconocido: {}", cmd);
                        }
                    }
                    Err(e) => error!("JSON inválido en topic scada: {} — {}", e, payload),
                }
            }

            if topic == "giirob/pr2-A1/db/pull" {
                match serde_json::from_str::<Value>(&payload) {
                    Ok(value) => {
                        let query = value.get("query").and_then(|v| v.as_str()).unwrap_or("");
                        info!("Pull request: query={}", query);

                        if query.eq_ignore_ascii_case("operarios") {
                            match pg.query("SELECT id_operario, nombre, apellido FROM operario", &[]).await {
                                Ok(rows) => {
                                    let operarios: Vec<serde_json::Value> = rows.iter().map(|r| {
                                        let id:       &str = r.get(0);
                                        let nombre:   &str = r.get(1);
                                        let apellido: &str = r.get(2);
                                        serde_json::json!({
                                            "id_operario": id,
                                            "nombre":      nombre,
                                            "apellido":    apellido,
                                        })
                                    }).collect();
                                    let response = serde_json::json!({ "operarios": operarios }).to_string();
                                    if let Err(e) = mqtt.publish("giirob/pr2-A1/db/pull/response", QoS::AtLeastOnce, false, response.as_bytes()).await {
                                        error!("Error publicando respuesta de operarios: {:?}", e);
                                    } else {
                                        info!("Operarios enviados: {} registros", rows.len());
                                    }
                                }
                                Err(e) => error!("Error consultando operarios: {:?}", e),
                            }
                        } else {
                            warn!("Pull query desconocida: {}", query);
                        }
                    }
                    Err(e) => error!("JSON inválido en topic pull: {} — {}", e, payload),
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parse_topics_trims_and_ignores_empty_entries() {
        assert_eq!(
            parse_topics(" alpha, beta ,,  gamma  ,"),
            vec!["alpha", "beta", "gamma"]
        );
    }

    #[test]
    fn parse_box_completed_event_normalizes_color_and_lotes() {
        let value = json!({
            "event": "box_completed",
            "id_caja": "B0001",
            "color": "blue",
            "codigo_etiqueta": "ETQ0000001",
            "estado": false,
            "lotes": ["L0001", "", 42, "L0002"]
        });

        assert_eq!(
            parse_box_completed_event(&value),
            Some(BoxCompletedEvent {
                id_caja: "B0001".to_string(),
                color_db: "BLUE".to_string(),
                etiqueta: "ETQ0000001".to_string(),
                estado: false,
                lotes: vec!["L0001".to_string(), "L0002".to_string()],
            })
        );
    }

    #[test]
    fn parse_box_completed_event_defaults_estado_to_true() {
        let value = json!({
            "id_caja": "B0002",
            "color": "red",
            "codigo_etiqueta": "ETQ0000002"
        });

        assert_eq!(parse_box_completed_event(&value).unwrap().estado, true);
    }

    #[test]
    fn parse_box_completed_event_rejects_missing_required_fields() {
        let value = json!({
            "id_caja": "B0003",
            "color": "",
            "codigo_etiqueta": "ETQ0000003"
        });

        assert_eq!(parse_box_completed_event(&value), None);
    }

    #[test]
    fn parse_gen_command_accepts_lote_alias_and_provider() {
        let value = json!({
            "cmd": "gen",
            "lote": "L0001",
            "quantity": 25,
            "proveedor": "P0001"
        });

        assert_eq!(
            parse_gen_command(&value),
            Some(GenCommand {
                proveedor: Some("P0001".to_string()),
                id_lote: "L0001".to_string(),
                quantity: 25,
            })
        );
    }

    #[test]
    fn parse_gen_command_rejects_missing_lote_or_non_positive_quantity() {
        assert_eq!(parse_gen_command(&json!({"quantity": 1})), None);
        assert_eq!(
            parse_gen_command(&json!({"id_lote": "L0001", "quantity": 0})),
            None
        );
        assert_eq!(
            parse_gen_command(&json!({"id_lote": "L0001", "quantity": -2})),
            None
        );
    }
}
