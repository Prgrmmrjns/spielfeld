import Link from "next/link";
import { ForecastMatch, formatKickoff, pct } from "@/lib/data";
import { ProbBar } from "./ProbBar";

export function MatchRow({ match, index = 0 }: { match: ForecastMatch; index?: number }) {
  return (
    <Link
      href={`/match/${encodeURIComponent(match.match_uid)}`}
      className={`glass rise rise-delay-${Math.min(index, 3)} block rounded-2xl px-4 py-4 transition hover:border-accent/40 hover:bg-white/[0.03]`}
    >
      <div className="mb-3 flex items-start justify-between gap-3 text-sm text-muted">
        <span>{formatKickoff(match.kickoff)}</span>
        {match.matchday != null && <span>MD {match.matchday}</span>}
      </div>
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {match.home_icon ? <img src={match.home_icon} alt="" className="h-8 w-8 object-contain" /> : null}
          <div className="truncate font-medium">{match.home_display}</div>
        </div>
        <div className="display text-lg text-muted">vs</div>
        <div className="flex min-w-0 flex-1 items-center justify-end gap-3">
          <div className="truncate text-right font-medium">{match.away_display}</div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {match.away_icon ? <img src={match.away_icon} alt="" className="h-8 w-8 object-contain" /> : null}
        </div>
      </div>
      <ProbBar home={match.p_home} draw={match.p_draw} away={match.p_away} />
      <div className="mt-3 text-xs text-muted">
        Model pick <span className="text-ink">{match.pick}</span>
        {match.imp_home != null && (
          <>
            {" "}
            · Market {pct(match.imp_home)}/{pct(match.imp_draw)}/{pct(match.imp_away)}
          </>
        )}
      </div>
    </Link>
  );
}
