// Estado compartido entre los dos escenarios y el gestor MQTT.

#[derive(Debug)]
pub struct DemoState {
    // Escenario 1: AMR -> Cobot
    pub cobot_ready: bool,         // El AMR llegó a cobot_pick
    pub cobot_in_progress: bool,   // El cobot está ejecutando una operación
    pub pallet_count: u32,         // Cajas paletizadas en el pallet activo
    pub current_pallet_id: u32,    // ID del pallet activo

    // Escenario 1 y 2: caja en vuelo
    pub current_caja_id: Option<String>,
    pub current_color: Option<String>,
}

impl Default for DemoState {
    fn default() -> Self {
        Self {
            cobot_ready: false,
            cobot_in_progress: false,
            pallet_count: 0,
            current_pallet_id: crate::config::PALLET_ID_BASE,
            current_caja_id: None,
            current_color: None,
        }
    }
}
