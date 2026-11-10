import { pct } from "@/lib/data";

export function ProbBar({
  home,
  draw,
  away,
  showLabels = true,
}: {
  home: number;
  draw: number;
  away: number;
  showLabels?: boolean;
}) {
  const h = `${Math.max(home, 0.02) * 100}%`;
  const d = `${Math.max(draw, 0.02) * 100}%`;
  const a = `${Math.max(away, 0.02) * 100}%`;
  return (
    <div className="space-y-2">
      <div className="prob-bar" style={{ ["--h" as string]: h, ["--d" as string]: d, ["--a" as string]: a }}>
        <span />
        <span />
        <span />
      </div>
      {showLabels && (
        <div className="flex justify-between text-xs tracking-wide text-muted">
          <span className="text-home">Home {pct(home)}</span>
          <span className="text-draw">Draw {pct(draw)}</span>
          <span className="text-away">Away {pct(away)}</span>
        </div>
      )}
    </div>
  );
}
