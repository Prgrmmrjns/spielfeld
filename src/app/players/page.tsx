import { getPlayerImpact } from "@/lib/data";

export const dynamic = "force-static";

export default async function PlayersPage() {
  const impact = await getPlayerImpact();
  const board = (impact.leaderboard || []) as {
    player_id: number;
    player_name: string;
    team_name: string;
    goals_120d: number;
    avg_delta_win_pp: number;
  }[];

  return (
    <div className="mx-auto max-w-4xl px-5 py-12">
      <h1 className="display text-5xl md:text-6xl">Player impact</h1>
      <p className="mt-3 max-w-2xl text-muted">{impact.method}</p>

      <div className="glass mt-8 overflow-hidden rounded-2xl">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-white/10 text-muted">
            <tr>
              <th className="px-4 py-3 font-medium">Player</th>
              <th className="px-4 py-3 font-medium">Club</th>
              <th className="px-4 py-3 font-medium">Goals 120d</th>
              <th className="px-4 py-3 font-medium">Avg |Δ win|</th>
            </tr>
          </thead>
          <tbody>
            {board.map((p) => (
              <tr key={p.player_id} className="border-b border-white/5">
                <td className="px-4 py-3">{p.player_name}</td>
                <td className="px-4 py-3 text-muted">{p.team_name}</td>
                <td className="px-4 py-3">{p.goals_120d}</td>
                <td className="px-4 py-3 text-accent">{p.avg_delta_win_pp.toFixed(2)} pp</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
