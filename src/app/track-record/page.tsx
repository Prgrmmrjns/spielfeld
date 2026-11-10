import { getTrackRecord, pct } from "@/lib/data";

export const dynamic = "force-static";

export default async function TrackRecordPage() {
  const track = await getTrackRecord();
  const matches = (track.matches || []) as {
    match_uid: string;
    kickoff: string;
    home_name: string;
    away_name: string;
    p_home: number;
    p_draw: number;
    p_away: number;
    pick: string;
    actual: string;
    correct: boolean;
    score: string | null;
    season_year: number;
  }[];

  return (
    <div className="mx-auto max-w-5xl px-5 py-12">
      <h1 className="display text-5xl md:text-6xl">Track record</h1>
      <p className="mt-3 text-muted">
        Out-of-fold walk-forward predictions vs results · {track.summary.n} matches ·{" "}
        {pct(track.summary.accuracy, 1)} accuracy
      </p>

      <div className="mt-6 flex flex-wrap gap-4">
        {Object.entries(track.summary.by_season || {}).map(([season, acc]) => (
          <div key={season} className="glass rounded-xl px-4 py-3 text-sm">
            <div className="display text-2xl">{pct(acc as number, 1)}</div>
            <div className="text-muted">{season}/{String(Number(season) + 1).slice(2)}</div>
          </div>
        ))}
      </div>

      <div className="glass mt-8 overflow-hidden rounded-2xl">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-white/10 text-muted">
            <tr>
              <th className="px-4 py-3">Match</th>
              <th className="px-4 py-3">Pick</th>
              <th className="px-4 py-3">Actual</th>
              <th className="px-4 py-3">Score</th>
              <th className="px-4 py-3">P(H/D/A)</th>
            </tr>
          </thead>
          <tbody>
            {matches.slice(0, 80).map((m) => (
              <tr key={m.match_uid} className="border-b border-white/5">
                <td className="px-4 py-3">
                  <div>
                    {m.home_name} vs {m.away_name}
                  </div>
                  <div className="text-xs text-muted">{m.kickoff}</div>
                </td>
                <td className="px-4 py-3">{m.pick}</td>
                <td className={`px-4 py-3 ${m.correct ? "text-home" : "text-accent"}`}>{m.actual}</td>
                <td className="px-4 py-3">{m.score ?? "—"}</td>
                <td className="px-4 py-3 text-muted">
                  {pct(m.p_home)}/{pct(m.p_draw)}/{pct(m.p_away)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
