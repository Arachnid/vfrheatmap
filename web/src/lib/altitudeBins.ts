/** Must match adsb_vfr/lib/altitude_bins.py */

export const TRANSITION_ALTITUDE_FT = 3000;
export const N_LOW_BINS = 30;
export const LOW_BAND_FT = 100;
export const HIGH_BAND_FT = 500;

const MAX_AGG_FT = 65_000;

export const MAX_ALTITUDE_BIN_INDEX =
  Math.floor((MAX_AGG_FT - TRANSITION_ALTITUDE_FT) / HIGH_BAND_FT) + N_LOW_BINS;

export function binIndexToMinFt(bin: number): number {
  if (bin < 0) {
    return 0;
  }
  if (bin < N_LOW_BINS) {
    return bin * LOW_BAND_FT;
  }
  return TRANSITION_ALTITUDE_FT + (bin - N_LOW_BINS) * HIGH_BAND_FT;
}

/** Last foot altitude included in this bin (inclusive range with min). */
export function binIndexToMaxFtInclusive(bin: number): number {
  if (bin < N_LOW_BINS) {
    return (bin + 1) * LOW_BAND_FT - 1;
  }
  return TRANSITION_ALTITUDE_FT + (bin - N_LOW_BINS + 1) * HIGH_BAND_FT - 1;
}
