interface Props {
  startDate: string;
  endDate: string;
  flights: number;
  seconds: number;
}

export function BottomBar({ startDate, endDate, flights, seconds }: Props) {
  return (
    <div className="absolute bottom-0 left-0 right-0 z-20 flex items-center justify-between bg-black/60 px-4 py-2 text-xs text-white">
      <span>
        Data range: {startDate} to {endDate}
      </span>
      <span>
        Visible flights: {flights.toLocaleString()} | Visible time: {(seconds / 3600).toFixed(1)}h
      </span>
      <span>
        Data: ADS-B Exchange / adsb.lol, OpenAIP, Copernicus ERA5
      </span>
    </div>
  );
}
