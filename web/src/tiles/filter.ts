import type { Metric, RenderableCell, TileCell } from "../types";

export function filterCellsByAltitude(
  cells: TileCell[],
  minBin: number,
  maxBin: number,
  metric: Metric
): RenderableCell[] {
  return cells
    .map((cell) => {
      let selectedTimeSeconds = 0;
      let selectedFlightCount = 0;
      for (const bin of cell.alt_bins) {
        if (bin.bin_index >= minBin && bin.bin_index <= maxBin) {
          selectedTimeSeconds += bin.time_seconds;
          selectedFlightCount += bin.flight_count;
        }
      }
      if (selectedTimeSeconds <= 0 && selectedFlightCount <= 0) {
        return null;
      }
      return {
        ...cell,
        selectedTimeSeconds,
        selectedFlightCount,
        metricValue: metric === "flight_count" ? selectedFlightCount : selectedTimeSeconds,
      };
    })
    .filter((value): value is RenderableCell => value !== null);
}
