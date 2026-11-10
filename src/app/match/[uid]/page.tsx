import Link from "next/link";
import { notFound } from "next/navigation";
import { ProbBar } from "@/components/ProbBar";
import { formatKickoff, getForecasts, getPlayerImpact, pct } from "@/lib/data";

export const dynamic = "force-static";

export async function generateStaticParams() {
  const forecasts = await getForecasts();
  const current = forecasts.matches.filter((m) => m.is_current_matchday);
  const list = current.length ? current : forecasts.matches.slice(0, 18);
  return list.map((m) => ({ uid: m.match_uid }));
}

export default async function MatchPage({ params }: { params: Promise<{ uid: string }> }) {
  const { uid } = await params;
  const [forecasts, impact] = await Promise.all([getForecasts(), getPlayerImpact()]);
  const match = forecasts.matches.find((m) => m.match_uid === uid);
  if (!match) notFound();

  const playerRows = (impact.impacts || []).filter((r) => r.match_uid === uid) as {
    player_name: string;
    team_name: string;
    side: string;
    goals_120d: number;
    delta_team_win_pp: number;
    without_p_home: number;
    without_p_draw: number;
    without_p_away: number;
  }[];

  return (
    <div className="mx-auto max-w-4xl px-5 py-12">
      <Link href="/" className="text-sm text-muted hover:text-ink">
        ← Matchday
      </Link>
      <div className="mt-6 rise">
        <p className="text-sm text-muted">{formatKickoff(match.kickoff)} · MD {match.matchday}</p>
        <h1 className="display mt-2 text-5xl md:text-6xl">
          {match.home_display}{" "}
          <span className="text-muted">vs</span> {match.away_display}
        </h1>
      </div>

      <div className="glass rise rise-delay-1 mt-8 rounded-2xl p-6">
        <h2 className="display text-3xl">Probabilities</h2>
        <div className="mt-4">
          <ProbBar home={match.p_home} draw={match.p_draw} away={match.p_away} />
        </div>
        <div className="mt-4 grid gap-3 text-sm text-muted md:grid-cols-3">
          <div>
            Model pick <span className="text-ink">{match.pick}</span>
          </div>
          <div>
            Elo {match.elo_home?.toFixed?.(0)}–{match.elo_away?.toFixed?.(0)}
          </div>
          <div>
            Market {pct(match.imp_home)} / {pct(match.imp_draw)} / {pct(match.imp_away)}
          </div>
        </div>
      </div>

      <div className="glass rise rise-delay-2 mt-6 rounded-2xl p-6">
        <h2 className="display text-3xl">Key drivers</h2>
        <p className="mt-1 text-sm text-muted">Largest deviations from seasonal medians, weighted by importance.</p>
        <ul className="mt-4 space-y-2">
          {(match.drivers || []).slice(0, 8).map((d) => (
            <li key={d.feature} className="flex justify-between gap-4 border-b border-white/5 py-2 text-sm">
              <span>{d.feature}</span>
              <span className="text-muted">{Number(d.value).toFixed(2)}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="glass rise rise-delay-3 mt-6 rounded-2xl p-6">
        <h2 className="display text-3xl">What if a player is out?</h2>
        <p className="mt-1 text-sm text-muted">
          Counterfactual: reduce squad-strength features by the player&apos;s recent scoring, re-score, and
          keep the market blend fixed.
        </p>
        <div className="mt-4 space-y-3">
          {playerRows.length === 0 && <p className="text-muted">No scorer impacts for this slate.</p>}
          {playerRows
            .sort((a, b) => Math.abs(b.delta_team_win_pp) - Math.abs(a.delta_team_win_pp))
            .slice(0, 12)
            .map((r) => (
              <div key={`${r.player_name}-${r.side}`} className="flex items-center justify-between gap-4 text-sm">
                <div>
                  <div className="font-medium">{r.player_name}</div>
                  <div className="text-muted">
                    {r.team_name} · {r.goals_120d} goals / 120d
                  </div>
                </div>
                <div className={r.delta_team_win_pp < 0 ? "text-accent" : "text-home"}>
                  {r.delta_team_win_pp.toFixed(2)} pp win
                </div>
              </div>
            ))}
        </div>
        <div className="mt-4 flex gap-4 text-sm">
          <Link href={`/team/${match.home_slug}`} className="text-accent-soft hover:underline">
            {match.home_display} page
          </Link>
          <Link href={`/team/${match.away_slug}`} className="text-accent-soft hover:underline">
            {match.away_display} page
          </Link>
        </div>
      </div>
    </div>
  );
}
