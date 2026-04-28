export type Classification = "vfr" | "ifr" | "unknown";
export type Metric = "flight_count" | "time_seconds";

export interface AltBinValue {
  bin_index: number;
  time_seconds: number;
  flight_count: number;
}

export interface TileCell {
  h3: string;
  flight_count: number;
  time_seconds: number;
  mean_track_x: number;
  mean_track_y: number;
  coherence: number;
  mean_speed: number;
  alt_bins: AltBinValue[];
}

export interface TilePayload {
  z: number;
  x: number;
  y: number;
  h3_resolution: number;
  cells: TileCell[];
}

export interface Manifest {
  schema_version: number;
  generated_at: string;
  bbox: [number, number, number, number];
  date_range: { start: string; end: string };
  classifier_config_hash: string;
  h3_resolutions: number[];
  altitude_bins: number[];
  classifications: Classification[];
}

export interface RenderableCell extends TileCell {
  metricValue: number;
  selectedFlightCount: number;
  selectedTimeSeconds: number;
}
