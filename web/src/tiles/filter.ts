import type { Metric, RenderableCell, TileCell } from "../types";

/** Project tile cells to the chosen metric for heatmap colouring (no altitude breakdown). */
export function cellsWithMetric(cells: TileCell[], metric: Metric): RenderableCell[] {
  return cells
    .map((cell) => ({
      ...cell,
      metricValue: metric === "flight_count" ? cell.flight_count : cell.time_seconds,
    }))
    .filter((cell) => cell.metricValue > 0);
}
