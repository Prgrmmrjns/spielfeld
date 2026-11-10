import Link from "next/link";
import { notFound } from "next/navigation";
import { MatchRow } from "@/components/MatchRow";
import { getForecasts, getPlayerImpact, getTeams, pct } from "@/lib/data";

export const dynamic = "force-static";

export async function generateStaticParams() {
  const teams = await getTeams();
  return teams.map((t) => ({ slug: t.slug }));
}

export default async function TeamPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [teams, forecasts, impact] = await Promise.all([getTeams(), getForecasts(), getPlayerImpact()]);
  const team = teams.find((t) => t.slug === slug);
  if (!team) notFound();

  const matches = forecasts.matches
    .filter((m) => m.home_slug === slug || m.away_slug === slug)
    .slice(0, 8);
  const players = (impact.leaderboard || []).filter((p) => p.team_slug === slug) as {
    player_name: string;
    goals_120d: number;
    avg_delta_win_pp: number;
  }[];

  return (
    <div className="mx-auto max-w-6xl px-5 py-12">
      <Link href="/" className="text-sm text-muted hover:text-ink">
        ← Matchday
      </Link>
      <div className="mt-6 flex items-center gap-4">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        {team.icon_url ? <img src={team.icon_url} alt="" className="h-14 w-14 object-contain" /> : null}
        <div>
          <h1 className="display text-5xl md:text-6xl">{team.name}</h1>
          <p className="text-muted">Upcoming fixtures and scorer impact on this side.</p>
        </div>
      </div>

      <section className="mt-10">
        <h2 className="display text-3xl">Upcoming</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {matches.map((m, i) => (
            <MatchRow key={m.match_uid} match={m} index={i} />
          ))}
        </div>
      </section>

      <section className="mt-12">
        <h2 className="display text-3xl">Player impact</h2>
        <div className="glass mt-4 rounded-2xl p-5">
          {players.length === 0 && <p className="text-muted">No recent scorers ranked for this club.</p>}
          <ul className="space-y-3">
            {players.map((p) => (
              <li key={p.player_name} className="flex justify-between gap-4 text-sm">
                <span>
                  {p.player_name}{" "}
                  <span className="text-muted">· {p.goals_120d} goals / 120d</span>
                </span>
                <span className="text-accent">{pct(p.avg_delta_win_pp / 100, 2)} avg |Δwin|</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
