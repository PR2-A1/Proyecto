use esp_idf_svc::{
    nvs::{EspDefaultNvsPartition, EspNvs, NvsDefault},
    sys::EspError,
};

pub enum RobotEvent {
    DeltaCompleted { color: String, id_cap: String },
    AmrArrived     { location: String },
    CobotCompleted { id_pallet: String },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Manual,
    Auto,
}

#[derive(Clone, Debug)]
pub struct ExpectedTapa {
    pub color: String,
}

#[derive(Debug)]
pub struct ControlState {
    pub mode: Mode,
    pub auto_target: u32,           // Cantidad total solicitada en Auto
    pub auto_spawned: u32,           // Tapas ya generadas/spawneadas
    pub auto_validated: u32,         // Tapas validadas por cámara
    pub id_lote: Option<String>,
    pub manual_remaining: u32,
    pub manual_color: String,
    pub manual_spawn_pending: bool,
    pub expected_tapa: Option<ExpectedTapa>,
    pub total_processed: u64,
    pub tolva_counts: [u64; 6],
    pub amr_pending_tolva: Option<usize>,
    pub amr_dispatched_at: Option<std::time::Instant>,
    pub amr_arrived_tolva: Option<usize>,
    pub amr_arrived_at: Option<std::time::Instant>,
    pub amr_id_caja: Option<String>,
    pub amr_caja_tolva: Option<usize>,
    pub cobot_ready: bool,
    pub cobot_in_progress: bool,
    pub cobot_started_at: Option<std::time::Instant>,
    pub cobot_next_pallet: [u32; 6],     // pallet activo por color (red=0..blue=5)
    pub cobot_pending_color: Option<String>,
    pub cobot_pending_caja: Option<String>,
    pub cobot_active_color: Option<String>,
    pub cobot_completed_event: Option<String>,
    pub pallet_counts: [u64; 6],         // cajas en pallet actual por color
    pub status_requested: bool,
    pub batch_complete_pending: bool,
    pub reset_db_pending: bool,
    pub tapas_clasificadas_pending: u32,
}

impl Default for ControlState {
    fn default() -> Self {
        Self {
            mode: Mode::Manual,
            auto_target: 0,
            auto_spawned: 0,
            auto_validated: 0,
            id_lote: None,
            manual_remaining: 0,
            manual_color: "red".to_string(),
            manual_spawn_pending: false,
            expected_tapa: None,
            total_processed: 0,
            tolva_counts: [0; 6],
            amr_pending_tolva: None,
            amr_dispatched_at: None,
            amr_arrived_tolva: None,
            amr_arrived_at: None,
            amr_id_caja: None,
            amr_caja_tolva: None,
            cobot_ready: false,
            cobot_in_progress: false,
            cobot_started_at: None,
            cobot_next_pallet: [1, 2, 3, 4, 5, 6],
            cobot_pending_color: None,
            cobot_pending_caja: None,
            cobot_active_color: None,
            cobot_completed_event: None,
            pallet_counts: [0; 6],
            status_requested: false,
            batch_complete_pending: false,
            reset_db_pending: false,
            tapas_clasificadas_pending: 0,
        }
    }
}

impl ControlState {
    pub fn save_tolva_counts(&self, nvs: &EspDefaultNvsPartition) -> Result<(), EspError> {
        let nvs = EspNvs::<NvsDefault>::new(nvs.clone(), "tolva_counts", true)?;
        for (index, count) in self.tolva_counts.iter().enumerate() {
            let key = format!("tolva_{}", index + 1);
            nvs.set_u64(&key, *count)?;
        }
        Ok(())
    }

    pub fn reset_tolva_counts(&mut self) {
        for count in self.tolva_counts.iter_mut() {
            *count = 0;
        }
    }

    pub fn load_tolva_counts(nvs: &EspDefaultNvsPartition) -> Result<[u64; 6], EspError> {
        let nvs = EspNvs::<NvsDefault>::new(nvs.clone(), "tolva_counts", true)?;
        let mut counts = [0u64; 6];
        for (index, count) in counts.iter_mut().enumerate() {
            let key = format!("tolva_{}", index + 1);
            if let Ok(value) = nvs.get_u64(&key) {
                if let Some(v) = value {
                    *count = v;
                }
            }
        }
        Ok(counts)
    }
}
