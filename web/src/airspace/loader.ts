export interface AirspaceStyleRule {
  line_color: string;
  line_dash: number[];
  fill_color: string;
  fill_opacity: number;
  label: boolean;
}

export interface AirspaceStyleConfig {
  render_mode?: "raster_tiles" | "geojson";
  tile_url_template?: string;
  bounds?: [number, number, number, number];
  minzoom?: number;
  maxzoom?: number;
  attribution?: string;
  vector_fallback_style?: Record<string, AirspaceStyleRule>;
}

async function parseMaybeGzipJson<T>(response: Response): Promise<T> {
  const bytes = await response.arrayBuffer();
  const decoder = new TextDecoder();
  try {
    return JSON.parse(decoder.decode(bytes)) as T;
  } catch {
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    const text = await new Response(stream).text();
    return JSON.parse(text) as T;
  }
}

export async function loadAirspaceGeoJson(): Promise<GeoJSON.FeatureCollection> {
  const response = await fetch("./data/airspace/uk.geojson.gz");
  if (!response.ok) {
    return { type: "FeatureCollection", features: [] };
  }
  return parseMaybeGzipJson<GeoJSON.FeatureCollection>(response);
}

export async function loadAirspaceStyle(): Promise<AirspaceStyleConfig> {
  const response = await fetch("./data/airspace/style.json");
  if (!response.ok) {
    return {};
  }
  return (await response.json()) as AirspaceStyleConfig;
}
