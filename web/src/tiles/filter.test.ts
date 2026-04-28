import { describe, expect, it } from "vitest";

import { filterCellsByAltitude } from "./filter";

describe("filterCellsByAltitude", () => {
  it("projects selected metric values", () => {
    const out = filterCellsByAltitude(
      [
        {
          h3: "87195da4cffffff",
          vehicle_class: "fixed_wing",
          flight_count: 10,
          time_seconds: 120,
          mean_track_x: 0.5,
          mean_track_y: 0.2,
          coherence: 0.54,
          mean_speed: 95,
          track_hist: Array(16).fill(1),
          alt_bins: [
            { bin_index: 5, time_seconds: 60, flight_count: 2 },
            { bin_index: 35, time_seconds: 60, flight_count: 5 },
          ],
        },
      ],
      0,
      20,
      "flight_count"
    );
    expect(out).toHaveLength(1);
    expect(out[0]?.metricValue).toBe(2);
  });
});
