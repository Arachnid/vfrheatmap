import { binIndexToMaxFtInclusive, binIndexToMinFt, MAX_ALTITUDE_BIN_INDEX } from "../lib/altitudeBins";
import type { Metric } from "../types";

interface Props {
  showVfr: boolean;
  showIfr: boolean;
  showHelicopter: boolean;
  metric: Metric;
  minBin: number;
  maxBin: number;
  showAirspace: boolean;
  onToggleVfr: () => void;
  onToggleIfr: () => void;
  onToggleHelicopter: () => void;
  onMetricChange: (next: Metric) => void;
  onMinBinChange: (value: number) => void;
  onMaxBinChange: (value: number) => void;
  onToggleAirspace: () => void;
}

export function ControlPanel(props: Props) {
  return (
    <div className="absolute right-4 top-4 z-20 w-72 rounded-md bg-white/95 p-3 shadow-lg">
      <label className="block text-xs font-semibold">Classifications</label>
      <div className="mt-1 space-y-1 text-xs">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={props.showVfr} onChange={props.onToggleVfr} />
          VFR
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={props.showIfr} onChange={props.onToggleIfr} />
          IFR
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={props.showHelicopter} onChange={props.onToggleHelicopter} />
          Helicopter
        </label>
      </div>

      <label className="mt-3 block text-xs font-semibold">Metric</label>
      <select
        className="mt-1 w-full rounded border p-1 text-sm"
        value={props.metric}
        onChange={(event) => props.onMetricChange(event.target.value as Metric)}
      >
        <option value="flight_count">Flight count</option>
        <option value="time_seconds">Time spent</option>
      </select>

      <label className="mt-3 block text-xs font-semibold">Altitude min (ft)</label>
      <input
        type="range"
        min={0}
        max={MAX_ALTITUDE_BIN_INDEX}
        value={props.minBin}
        onChange={(event) => props.onMinBinChange(Number(event.target.value))}
        className="w-full"
      />
      <label className="mt-2 block text-xs font-semibold">Altitude max (ft)</label>
      <input
        type="range"
        min={0}
        max={MAX_ALTITUDE_BIN_INDEX}
        value={props.maxBin}
        onChange={(event) => props.onMaxBinChange(Number(event.target.value))}
        className="w-full"
      />
      <div className="text-xs text-slate-600">
        {binIndexToMinFt(props.minBin)} – {binIndexToMaxFtInclusive(props.maxBin)} ft
      </div>

      <div className="mt-3 flex items-center gap-2 text-xs">
        <input id="airspace" type="checkbox" checked={props.showAirspace} onChange={props.onToggleAirspace} />
        <label htmlFor="airspace">Airspace</label>
      </div>
    </div>
  );
}
