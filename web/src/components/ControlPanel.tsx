import type { Metric } from "../types";

interface Props {
  showVfr: boolean;
  showIfr: boolean;
  showUnknown: boolean;
  showHelicopter: boolean;
  metric: Metric;
  minBin: number;
  maxBin: number;
  showAirspace: boolean;
  showArrows: boolean;
  onToggleVfr: () => void;
  onToggleIfr: () => void;
  onToggleUnknown: () => void;
  onToggleHelicopter: () => void;
  onMetricChange: (next: Metric) => void;
  onMinBinChange: (value: number) => void;
  onMaxBinChange: (value: number) => void;
  onToggleAirspace: () => void;
  onToggleArrows: () => void;
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
          <input type="checkbox" checked={props.showUnknown} onChange={props.onToggleUnknown} />
          Unknown
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
        max={120}
        value={props.minBin}
        onChange={(event) => props.onMinBinChange(Number(event.target.value))}
        className="w-full"
      />
      <label className="mt-2 block text-xs font-semibold">Altitude max (ft)</label>
      <input
        type="range"
        min={0}
        max={120}
        value={props.maxBin}
        onChange={(event) => props.onMaxBinChange(Number(event.target.value))}
        className="w-full"
      />
      <div className="text-xs text-slate-600">{props.minBin * 100} - {props.maxBin * 100} ft</div>

      <div className="mt-3 flex items-center gap-2 text-xs">
        <input id="airspace" type="checkbox" checked={props.showAirspace} onChange={props.onToggleAirspace} />
        <label htmlFor="airspace">Airspace</label>
      </div>
      <div className="mt-1 flex items-center gap-2 text-xs">
        <input id="arrows" type="checkbox" checked={props.showArrows} onChange={props.onToggleArrows} />
        <label htmlFor="arrows">Direction arrows</label>
      </div>
    </div>
  );
}
