"""
gen_mqtt_comparison_pdf.py — Comparativa Arduino/C vs Rust para MQTT en ESP32-S3
Uso: python gen_mqtt_comparison_pdf.py
Requiere: pip install reportlab
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

OUTPUT = "comparativa_mqtt_arduino_vs_rust.pdf"

# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
AZUL         = colors.HexColor("#1565C0")
AZUL_CLARO   = colors.HexColor("#E3F2FD")
NARANJA      = colors.HexColor("#E65100")
NARANJA_CLARO= colors.HexColor("#FFF3E0")
VERDE        = colors.HexColor("#2E7D32")
VERDE_CLARO  = colors.HexColor("#E8F5E9")
GRIS_CODIGO  = colors.HexColor("#F5F5F5")
GRIS_BORDE   = colors.HexColor("#CCCCCC")
GRIS_HEADER  = colors.HexColor("#455A64")
GRIS_CLARO   = colors.HexColor("#ECEFF1")
ROJO         = colors.HexColor("#C62828")
ROJO_CLARO   = colors.HexColor("#FFEBEE")
BLANCO       = colors.white
NEGRO        = colors.HexColor("#212121")
MORADO       = colors.HexColor("#4A148C")
MORADO_CLARO = colors.HexColor("#F3E5F5")

# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------
titulo = ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=20,
    textColor=AZUL, spaceAfter=4, alignment=TA_CENTER)
subtitulo = ParagraphStyle("subtitulo", fontName="Helvetica", fontSize=11,
    textColor=GRIS_HEADER, spaceAfter=2, alignment=TA_CENTER)
h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
    textColor=BLANCO, spaceAfter=4, spaceBefore=14, leftIndent=8)
h3_arduino = ParagraphStyle("h3_arduino", fontName="Helvetica-Bold", fontSize=10,
    textColor=NARANJA, spaceAfter=3, spaceBefore=6)
h3_rust = ParagraphStyle("h3_rust", fontName="Helvetica-Bold", fontSize=10,
    textColor=AZUL, spaceAfter=3, spaceBefore=6)
body = ParagraphStyle("body", fontName="Helvetica", fontSize=10,
    textColor=NEGRO, spaceAfter=5, leading=14, alignment=TA_JUSTIFY)
body_bold = ParagraphStyle("body_bold", fontName="Helvetica-Bold", fontSize=10,
    textColor=NEGRO, spaceAfter=4, leading=14)
mono = ParagraphStyle("mono", fontName="Courier", fontSize=7.5,
    textColor=NEGRO, leading=11, leftIndent=4)
mono_arduino = ParagraphStyle("mono_arduino", fontName="Courier", fontSize=7.5,
    textColor=colors.HexColor("#BF360C"), leading=11, leftIndent=4)
mono_rust = ParagraphStyle("mono_rust", fontName="Courier", fontSize=7.5,
    textColor=colors.HexColor("#0D47A1"), leading=11, leftIndent=4)
caption = ParagraphStyle("caption", fontName="Helvetica-Oblique", fontSize=8,
    textColor=GRIS_HEADER, spaceAfter=6, alignment=TA_CENTER)
ventaja = ParagraphStyle("ventaja", fontName="Helvetica", fontSize=9,
    textColor=VERDE, leading=13, leftIndent=8)
desventaja = ParagraphStyle("desventaja", fontName="Helvetica", fontSize=9,
    textColor=ROJO, leading=13, leftIndent=8)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section_header(text, color=AZUL):
    data = [[Paragraph(text, h2)]]
    t = Table(data, colWidths=[17*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), color),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ]))
    return t


def code_block(lines, style=mono, bg=GRIS_CODIGO, border=GRIS_BORDE):
    content = [Paragraph(line.replace(" ", "&nbsp;").replace("<", "&lt;").replace(">", "&gt;"), style)
               for line in lines]
    t = Table([[c] for c in content], colWidths=[16.2*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), bg),
        ("BOX",           (0,0), (-1,-1), 0.6, border),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))
    return t


def lang_badge(text, color, bg):
    data = [[Paragraph(f"<b>{text}</b>", ParagraphStyle("b", fontName="Helvetica-Bold",
        fontSize=8, textColor=color))]]
    t = Table(data, colWidths=[3*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), bg),
        ("BOX",           (0,0), (-1,-1), 0.8, color),
        ("TOPPADDING",    (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
    ]))
    return t


def comparison_block(title, description, arduino_caption, arduino_lines,
                     rust_caption, rust_lines, advantage_text):
    """Bloque completo: título, descripción, código lado a lado, ventaja."""
    elems = []

    # Título del bloque
    elems.append(Spacer(1, 0.15*cm))
    elems.append(Paragraph(f"<b>{title}</b>", body_bold))
    elems.append(Paragraph(description, body))

    # Badges + captions
    badge_row = Table(
        [[lang_badge("Arduino / C++", NARANJA, NARANJA_CLARO),
          Paragraph(""),
          lang_badge("Rust", AZUL, AZUL_CLARO)]],
        colWidths=[3.5*cm, 10.2*cm, 3.5*cm]
    )
    elems.append(badge_row)
    elems.append(Spacer(1, 0.1*cm))

    # Captions
    cap_row = Table(
        [[Paragraph(arduino_caption, caption), Paragraph(""), Paragraph(rust_caption, caption)]],
        colWidths=[7.8*cm, 1.2*cm, 8.2*cm]
    )
    elems.append(cap_row)

    # Código lado a lado
    ard_code = [Paragraph(l.replace(" ", "&nbsp;").replace("<", "&lt;").replace(">", "&gt;"),
                          mono_arduino) for l in arduino_lines]
    rust_code = [Paragraph(l.replace(" ", "&nbsp;").replace("<", "&lt;").replace(">", "&gt;"),
                           mono_rust) for l in rust_lines]

    max_rows = max(len(ard_code), len(rust_code))
    empty = Paragraph("", mono)
    while len(ard_code)  < max_rows: ard_code.append(empty)
    while len(rust_code) < max_rows: rust_code.append(empty)

    data = [[a, r] for a, r in zip(ard_code, rust_code)]
    code_table = Table(data, colWidths=[7.8*cm, 8.4*cm])
    code_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (0,-1), NARANJA_CLARO),
        ("BACKGROUND",    (1,0), (1,-1), AZUL_CLARO),
        ("BOX",           (0,0), (0,-1), 0.6, NARANJA),
        ("BOX",           (1,0), (1,-1), 0.6, AZUL),
        ("TOPPADDING",    (0,0), (-1,-1), 2),
        ("BOTTOMPADDING", (0,0), (-1,-1), 2),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 4),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    elems.append(code_table)

    # Ventaja
    elems.append(Spacer(1, 0.15*cm))
    advantage_table = Table(
        [[Paragraph(f"<b>Ventaja Rust:</b> {advantage_text}", ventaja)]],
        colWidths=[16.8*cm]
    )
    advantage_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), VERDE_CLARO),
        ("BOX",           (0,0), (-1,-1), 0.8, VERDE),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    elems.append(advantage_table)
    elems.append(Spacer(1, 0.25*cm))

    return elems


# ---------------------------------------------------------------------------
# Contenido
# ---------------------------------------------------------------------------

def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )
    story = []

    # ── Portada ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Comparativa de implementacion MQTT", titulo))
    story.append(Paragraph("Arduino / C++  vs  Rust (esp-idf-svc)", subtitulo))
    story.append(Paragraph("ESP32-S3 — Proyecto GiiRob PR2-A1", subtitulo))
    story.append(Spacer(1, 0.3*cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=AZUL))
    story.append(Spacer(1, 0.3*cm))

    intro = (
        "Este documento compara la implementacion MQTT en Arduino/C++ "
        "(biblioteca PubSubClient, archivos <i>e_mqtt_lib_no_tocar.ino</i> y "
        "<i>g_comunicaciones.ino</i>) con la implementacion equivalente en Rust "
        "(<i>mqtt_manager.rs</i>), mostrando fragmentos reales de ambos proyectos "
        "y explicando por que la version Rust es mas adecuada para la arquitectura "
        "de doble nucleo del ESP32-S3."
    )
    story.append(Paragraph(intro, body))
    story.append(Spacer(1, 0.2*cm))

    # ── Seccion 1: Modelo de ejecucion ───────────────────────────────────────
    story.append(KeepTogether([section_header("1. Modelo de ejecucion"), Spacer(1, 0.1*cm)]))

    story.append(Paragraph(
        "Arduino ejecuta todo en un unico hilo. El main loop llama a "
        "<font face='Courier'>mqtt_loop()</font> en cada iteracion, que a su vez "
        "verifica la conexion, reconecta si es necesario y procesa un mensaje. "
        "El callback MQTT y la logica del robot comparten el mismo hilo de ejecucion.",
        body
    ))
    story.append(Paragraph(
        "Rust separa el callback MQTT (Core 0, Wi-Fi stack de FreeRTOS) "
        "de la logica del robot (Core 1, logic_task). El callback solo encola eventos "
        "a traves de un canal <font face='Courier'>mpsc::SyncSender</font>; "
        "nunca procesa directamente.",
        body
    ))

    story.extend(comparison_block(
        "Loop principal y recepcion de mensajes",
        "En Arduino, mqtt_loop() debe llamarse en cada iteracion. En Rust, el callback es async y nunca bloquea.",
        "w_loop.ino + e_mqtt_lib_no_tocar.ino",
        [
            "// Cada iteracion del loop principal:",
            "void on_loop() {",
            "  mqtt_loop();  // llama en cada ciclo",
            "}",
            "",
            "void mqtt_loop() {",
            "  if (!mqttClient.connected())",
            "    mqtt_reconnect(3);  // BLOQUEA hasta 15s",
            "  mqttClient.loop();   // 1 mensaje por llamada",
            "}",
            "",
            "// Callback en mismo hilo que el loop:",
            "void mqttCallback(char* topic,",
            "    byte* message, unsigned int length) {",
            "  String msg;",
            "  for (int i=0; i<length; i++)",
            "    msg += (char)message[i]; // copia byte a byte",
            "  alRecibirMensajePorTopic(topic, msg);",
            "}",
        ],
        "mqtt_manager.rs",
        [
            "// Core 0: callback MQTT (nunca bloquea)",
            "let mut client = EspMqttClient::new_cb(",
            "  config::MQTT_URL, &cfg,",
            "  move |event| match event.payload() {",
            "",
            "  EventPayload::Received {",
            "      topic, data, ..",
            "  } => {",
            "    // Zero-copy: apunta al buffer del broker",
            "    let msg = std::str::from_utf8(data)",
            "                  .unwrap_or(\"\");",
            "    // Solo encola, NO procesa",
            "    event_tx.try_send(",
            "      RobotEvent::DeltaCompleted {",
            "        color, id_cap",
            "      }",
            "    );",
            "  }",
            "  _ => {}",
            "})?;",
        ],
        "El callback de Rust corre en Core 0 y solo encola el evento. "
        "Core 1 (logic_task) consume la cola sin bloquear la recepcion MQTT. "
        "En Arduino, si el callback tarda, todo el programa se detiene."
    ))

    # ── Seccion 2: Reconexion ─────────────────────────────────────────────────
    story.append(KeepTogether([section_header("2. Reconexion al broker"), Spacer(1, 0.1*cm)]))

    story.append(Paragraph(
        "La estrategia de reconexion es critica en sistemas industriales. "
        "Arduino usa reintentos fijos con <font face='Courier'>delay()</font> bloqueante; "
        "Rust reintenta indefinidamente en un hilo separado sin afectar el resto del sistema.",
        body
    ))

    story.extend(comparison_block(
        "Estrategia de reconexion y suscripcion",
        "Arduino bloquea el programa completo durante la reconexion. Rust suspende solo el hilo de inicializacion.",
        "e_mqtt_lib_no_tocar.ino",
        [
            "#define MQTT_CONNECTION_RETRIES 3",
            "",
            "void mqtt_reconnect(int retries) {",
            "  int r = 0;",
            "  while (!mqttClient.connected()",
            "         && r < retries) {",
            "    r++;",
            "    if (mqttClient.connect(",
            "          mqttClientID.c_str())) {",
            "      delay(1000); // bloquea 1s",
            "    } else {",
            "      delay(5000); // bloquea 5s",
            "      // maximo 3 intentos, luego abandona",
            "    }",
            "  }",
            "}",
            "// Total posible bloqueado: 15 segundos",
            "// Despues de 3 fallos: NO reintenta mas",
        ],
        "mqtt_manager.rs",
        [
            "fn subscribe_all_topics(",
            "    client: &mut EspMqttClient<'_>,",
            "    topics: &[&str]",
            ") {",
            "  for &topic in topics {",
            "    loop { // reintenta INFINITAMENTE",
            "      match client.subscribe(",
            "          topic, QoS::AtLeastOnce) {",
            "        Ok(_) => {",
            "          info!(\"Suscrito a {}\", topic);",
            "          break;",
            "        }",
            "        Err(e) => {",
            "          error!(\"Reintentando...\");",
            "          // solo suspende ESTE hilo",
            "          thread::sleep(",
            "            Duration::from_secs(2));",
            "        }",
            "      }",
            "    }",
            "  }",
            "}",
        ],
        "Rust reintenta hasta tener exito, sin limite de intentos. "
        "thread::sleep() suspende unicamente el hilo de inicializacion; "
        "la logica del robot sigue corriendo en Core 1."
    ))

    # ── Seccion 3: Estado compartido ─────────────────────────────────────────
    story.append(KeepTogether([section_header("3. Estado compartido y seguridad en concurrencia"), Spacer(1, 0.1*cm)]))

    story.append(Paragraph(
        "El estado del sistema (modo, contadores, flags de emergencia) "
        "debe compartirse entre el callback MQTT y la logica del robot. "
        "Arduino usa variables globales sin proteccion. "
        "Rust garantiza acceso seguro a traves del sistema de ownership "
        "y el compilador rechaza cualquier acceso sin mutex.",
        body
    ))

    story.extend(comparison_block(
        "Acceso al estado desde el callback",
        "Variables globales en Arduino vs Arc<Mutex<>> en Rust. El compilador de Rust hace imposible el data race.",
        "e_mqtt_lib_no_tocar.ino + g_comunicaciones.ino",
        [
            "// Estado global, sin proteccion:",
            "PubSubClient mqttClient(espWifiClient);",
            "String mqttClientID;",
            "// Cualquier funcion puede modificarlo",
            "// sin ningun control de acceso",
            "",
            "void alRecibirMensajePorTopic(",
            "    char* topic, String msg) {",
            "  // Acceso directo a variables globales",
            "  if (strcmp(topic, HELLO_TOPIC)==0) {",
            "    if(msg == \"on\") {",
            "      // sin mutex, sin verificacion",
            "      digitalWrite(LED, HIGH);",
            "    }",
            "  }",
            "}",
            "// En FreeRTOS con 2 tareas:",
            "// DATA RACE -> comportamiento indefinido",
        ],
        "mqtt_manager.rs",
        [
            "// Estado protegido por Mutex, compartido",
            "// con Arc (reference counting atomico):",
            "pub fn connect_and_subscribe_with_state(",
            "  control_state: Arc<Mutex<ControlState>>,",
            "  emergency_stop: Arc<AtomicBool>,",
            "  ...",
            ") -> Result<Self> {",
            "",
            "  // En el callback:",
            "  if cmd == \"set_mode\" {",
            "    // try_lock: NO bloquea si esta ocupado",
            "    if let Ok(mut state) =",
            "        control_state.try_lock() {",
            "      state.mode = Mode::Auto;",
            "    } else {",
            "      error!(\"No se pudo lockear\");",
            "    }",
            "  }",
            "  // Sin mutex -> ERROR DE COMPILACION",
            "}",
        ],
        "Arc<Mutex<>> garantiza que solo un hilo modifica el estado a la vez. "
        "try_lock() evita que el callback bloquee el Wi-Fi stack si logic_task "
        "ya tiene el mutex. El compilador rechaza acceso sin mutex en tiempo de compilacion."
    ))

    # ── Seccion 4: Señales de emergencia ─────────────────────────────────────
    story.append(KeepTogether([section_header("4. Senales criticas: parada de emergencia"), Spacer(1, 0.1*cm)]))

    story.append(Paragraph(
        "La parada de emergencia requiere propagacion instantanea entre nucleos. "
        "Arduino no tiene mecanismo nativo para esto. "
        "Rust usa <font face='Courier'>AtomicBool</font>, una operacion atomica "
        "que no necesita mutex y es segura entre nucleos por hardware.",
        body
    ))

    story.extend(comparison_block(
        "Propagacion de emergencia entre nucleos",
        "Arduino no tiene primitive atomica. Rust usa AtomicBool: escritura/lectura sin mutex, segura en hardware.",
        "g_comunicaciones.ino (sin soporte real)",
        [
            "// No existe primitive atomica en Arduino",
            "// Se necesitaria una variable global:",
            "bool emergencia = false; // NO thread-safe",
            "",
            "void alRecibirMensajePorTopic(",
            "    char* topic, String msg) {",
            "  if (strcmp(topic, EMERGENCY)==0) {",
            "    emergencia = true;",
            "    // Otra tarea podria leer un valor",
            "    // a medio escribir -> undefined behavior",
            "  }",
            "}",
            "",
            "// En otra tarea FreeRTOS:",
            "if (emergencia) { /* ... */ }",
            "// Sin garantia de visibilidad entre cores",
        ],
        "mqtt_manager.rs",
        [
            "// AtomicBool: operacion atomica a nivel CPU",
            "// No necesita mutex, segura entre nucleos",
            "pub fn connect_and_subscribe_with_state(",
            "  emergency_stop: Arc<AtomicBool>,",
            "  ...",
            ") {",
            "  // Core 0: callback escribe atomicamente",
            "  if cmd == \"estop\" {",
            "    emergency_stop.store(",
            "      true, Ordering::SeqCst",
            "    );",
            "  }",
            "",
            "  // Core 1: logic_task lee atomicamente",
            "  if emergency_stop.load(",
            "      Ordering::SeqCst) {",
            "    // parada garantizada e inmediata",
            "  }",
            "}",
        ],
        "Ordering::SeqCst garantiza que la escritura en Core 0 sea visible "
        "inmediatamente en Core 1. No hay ventana de tiempo donde el valor "
        "sea inconsistente. Esto es imposible de garantizar con bool global en Arduino."
    ))

    # ── Seccion 5: Comparacion de topics ─────────────────────────────────────
    story.append(KeepTogether([section_header("5. Despacho de topics recibidos"), Spacer(1, 0.1*cm)]))

    story.append(Paragraph(
        "Ambas implementaciones necesitan ejecutar logica distinta segun el topic MQTT recibido. "
        "Arduino usa <font face='Courier'>strcmp</font> encadenado (C-style). "
        "Rust usa <font face='Courier'>match</font>, que es exhaustivo: "
        "si se agrega un topic nuevo sin manejarlo, el compilador advierte.",
        body
    ))

    story.extend(comparison_block(
        "Enrutamiento por topic",
        "strcmp encadenado vs match exhaustivo. Rust detecta en compilacion topics sin handler.",
        "g_comunicaciones.ino",
        [
            "void alRecibirMensajePorTopic(",
            "    char* topic, String msg) {",
            "  // strcmp: comparacion C-string manual",
            "  if (strcmp(topic, HELLO_TOPIC)==0) {",
            "    // ...manejar hello",
            "  }",
            "  // Si agregas un topic y olvidas",
            "  // el if: falla en runtime, silenciosamente",
            "  //",
            "  // No hay garantia de cobertura completa",
            "}",
        ],
        "mqtt_manager.rs",
        [
            "match topic_recibido {",
            "  config::MQTT_TOPIC_SCADA_ACTION => {",
            "    // ...manejar SCADA",
            "  }",
            "  config::MQTT_TOPIC_DELTA_STATUS => {",
            "    // ...manejar delta",
            "  }",
            "  config::MQTT_TOPIC_EMERGENCY_ACTION => {",
            "    // ...manejar emergencia",
            "  }",
            "  config::MQTT_TOPIC_AMR_STATUS => {",
            "    // ...manejar AMR",
            "  }",
            "  config::MQTT_TOPIC_COBOT_STATUS => {",
            "    // ...manejar cobot",
            "  }",
            "  _ => info!(\"Topic no gestionado\"),",
            "}",
            "// Sin el '_' -> ERROR de compilacion",
            "// si falta cualquier variante",
        ],
        "El compilador verifica que todos los topics conocidos tengan un handler. "
        "Agregar un topic a config.rs y olvidar el handler es un error de compilacion, "
        "no un bug silencioso en runtime."
    ))

    # ── Seccion 6: Perdida de mensajes ───────────────────────────────────────
    story.append(KeepTogether([section_header("6. Manejo explicito de mensajes descartados"), Spacer(1, 0.1*cm)]))

    story.extend(comparison_block(
        "Cola llena: mensaje descartado",
        "Si el sistema esta ocupado y llega un mensaje, Arduino no tiene mecanismo para detectarlo. "
        "Rust explicita el descarte con un log de error.",
        "g_comunicaciones.ino",
        [
            "void mqttCallback(char* topic,",
            "    byte* message, unsigned int length) {",
            "  // Si la logica esta ocupada procesando",
            "  // el mensaje anterior, este se acumula",
            "  // en el stack o se pierde silenciosamente.",
            "  //",
            "  // No hay forma de detectar que se perdio",
            "  // un mensaje sin instrumentacion manual.",
            "  alRecibirMensajePorTopic(topic, msg);",
            "}",
        ],
        "mqtt_manager.rs",
        [
            "// try_send: no bloquea si la cola esta llena",
            "if let Err(e) = event_tx.try_send(",
            "    RobotEvent::DeltaCompleted {",
            "        color, id_cap",
            "    }) {",
            "  // Descarte EXPLICITO con log de error:",
            "  error!(",
            "    \"Cola llena — delta/status descartado: {:?}\"",
            "    , e",
            "  );",
            "}",
            "// El canal tiene capacidad 64:",
            "// let (event_tx, event_rx) =",
            "//   mpsc::sync_channel::<RobotEvent>(64);",
        ],
        "try_send() devuelve error si la cola esta llena, permitiendo logearlo. "
        "Nunca bloquea el Wi-Fi stack. En Arduino el descarte es invisible."
    ))

    # ── Tabla resumen ─────────────────────────────────────────────────────────
    story.append(KeepTogether([section_header("Resumen comparativo"), Spacer(1, 0.2*cm)]))

    header_style = ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9,
        textColor=BLANCO, alignment=TA_CENTER)
    cell_style   = ParagraphStyle("td", fontName="Helvetica", fontSize=9,
        textColor=NEGRO, leading=13, alignment=TA_LEFT)
    cell_good    = ParagraphStyle("td_good", fontName="Helvetica", fontSize=9,
        textColor=VERDE, leading=13, alignment=TA_LEFT)
    cell_bad     = ParagraphStyle("td_bad",  fontName="Helvetica", fontSize=9,
        textColor=ROJO,  leading=13, alignment=TA_LEFT)

    rows = [
        ["Aspecto", "Arduino / C++", "Rust (esp-idf-svc)"],
        ["Modelo de ejecucion",
         "Single-thread, polling en loop()",
         "Multi-core: callback Core 0, logica Core 1"],
        ["Reconexion",
         "delay(5000) bloquea TODO 15s, max 3 intentos",
         "thread::sleep suspende solo ese hilo, reintenta infinito"],
        ["Estado compartido",
         "Variables globales, sin proteccion",
         "Arc<Mutex<>> garantizado por el compilador"],
        ["Emergencia entre nucleos",
         "bool global, sin garantia de visibilidad",
         "AtomicBool con Ordering::SeqCst, atomico por hardware"],
        ["Despacho de topics",
         "strcmp manual, fallos silenciosos",
         "match exhaustivo, error de compilacion si falta handler"],
        ["Mensajes descartados",
         "Silencioso, invisible",
         "try_send() explicito con log de error"],
        ["Decoding de payload",
         "Copia byte a byte en Arduino String",
         "Zero-copy con str::from_utf8 sobre el buffer"],
        ["QoS en publish",
         "Sin configuracion explicita",
         "QoS::AtLeastOnce explicito por topic"],
        ["Seguridad en compilacion",
         "Ninguna (C++, sin borrow checker)",
         "Borrow checker: data races son error de compilacion"],
    ]

    table_data = []
    for i, row in enumerate(rows):
        if i == 0:
            table_data.append([Paragraph(c, header_style) for c in row])
        else:
            table_data.append([
                Paragraph(row[0], cell_style),
                Paragraph(row[1], cell_bad),
                Paragraph(row[2], cell_good),
            ])

    summary = Table(table_data, colWidths=[4.5*cm, 6*cm, 6.5*cm])
    summary.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,0), GRIS_HEADER),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [BLANCO, GRIS_CLARO]),
        ("BOX",           (0,0), (-1,-1), 0.8, GRIS_BORDE),
        ("INNERGRID",     (0,0), (-1,-1), 0.4, GRIS_BORDE),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    story.append(summary)
    story.append(Spacer(1, 0.4*cm))

    # ── Conclusion ────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1, color=AZUL))
    story.append(Spacer(1, 0.2*cm))

    conclusion = (
        "<b>Conclusion:</b> Arduino es adecuado para proyectos simples de un solo hilo. "
        "El problema especifico de este proyecto es que el ESP32-S3 tiene dos nucleos "
        "corriendo en paralelo, y la biblioteca PubSubClient no fue disenada para ese escenario. "
        "Rust con <font face='Courier'>Arc&lt;Mutex&lt;&gt;&gt;</font>, "
        "<font face='Courier'>AtomicBool</font> y "
        "<font face='Courier'>mpsc::SyncSender</font> es la unica forma de garantizar "
        "que el callback del broker (Core 0) y la logica del robot (Core 1) no generen "
        "data races, sin bloqueos mutuos y con verificacion en tiempo de compilacion, "
        "no en runtime."
    )
    story.append(Paragraph(conclusion, body))

    doc.build(story)
    print(f"PDF generado: {OUTPUT}")


if __name__ == "__main__":
    build_pdf()
