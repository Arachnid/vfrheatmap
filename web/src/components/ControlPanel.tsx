import { useState } from "react";
import type { Metric } from "../types";

interface Props {
  showVfr: boolean;
  showIfr: boolean;
  showHelicopter: boolean;
  metric: Metric;
  showAirspace: boolean;
  onToggleVfr: () => void;
  onToggleIfr: () => void;
  onToggleHelicopter: () => void;
  onMetricChange: (next: Metric) => void;
  onToggleAirspace: () => void;
  onCopyShareLink: () => void | Promise<void>;
}

export function ControlPanel(props: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    void (async () => {
      try {
        await Promise.resolve(props.onCopyShareLink());
        setCopied(true);
        window.setTimeout(() => setCopied(false), 2200);
      } catch {
        // Clipboard or app handler failed; keep button label unchanged.
      }
    })();
  };

  return (
    <div className="absolute right-4 top-4 z-20 w-72 rounded-md bg-white/95 p-3 shadow-lg">
      <label className="block text-xs font-semibold">Share</label>
      <button
        type="button"
        className="mt-1 w-full rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-100"
        onClick={handleCopy}
      >
        {copied ? "Copied link to clipboard" : "Copy link to this view"}
      </button>

      <label className="mt-4 block text-xs font-semibold">Classifications</label>
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

      <div className="mt-3 flex items-center gap-2 text-xs">
        <input id="airspace" type="checkbox" checked={props.showAirspace} onChange={props.onToggleAirspace} />
        <label htmlFor="airspace">Airspace</label>
      </div>
    </div>
  );
}
