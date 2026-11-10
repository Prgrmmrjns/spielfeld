import { MatchRow } from "@/components/MatchRow";
import { getForecasts, getMetrics, pct } from "@/lib/data";

export const dynamic = "force-static";

export default async function HomePage() {
  const [forecasts, metrics] = await Promise.all([getForecasts(), getMetrics()]);
  const overall = (metrics.overall || {}) as Record<string, { log_loss?: number; accuracy?: number }>;
  const slate = forecasts.matches.filter((m) => m.is_current_matchday);
  const shown = slate.length ? slate : forecasts.matches.slice(0, 9);

  return (
    <div>
      <section className="relative overflow-hidden">
        <div className="pitch-grid absolute inset-0 opacity-40" />
        <div className="relative mx-auto max-w-6xl px-5 pb-16 pt-16 md:pt-24">
          <p className="rise text-sm uppercase tracking-[0.25em]" style={{ color: "var(--accent-soft)" }}>
            Bundesliga · {forecasts.season_year}/{String(forecasts.season_year + 1).slice(2)}
          </p>
          <h1 className="display rise rise-delay-1 mt-3 max-w-3xl text-6xl leading-[0.95] md:text-8xl">
            SPIELFELD
          </h1>
          <p className="rise rise-delay-2 mt-5 max-w-xl text-lg text-muted">
            Matchday probabilities from a walk-forward LightGBM, blended with the market and stress-tested
            with feature ablation.
          </p>
          <div className="rise rise-delay-3 mt-8 flex flex-wrap gap-6 text-sm text-muted">
            <div>
              <div className="display text-3xl text-ink">
                {overall.model?.log_loss != null ? overall.model.log_loss.toFixed(3) : "—"}
              </div>
              <div>OOF log loss</div>
            </div>
            <div>
              <div className="display text-3xl text-ink">
                {overall.model?.accuracy != null ? pct(overall.model.accuracy) : "—"}
              </div>
              <div>OOF accuracy</div>
            </div>
            <div>
              <div className="display text-3xl text-ink">MD {forecasts.current_matchday ?? "—"}</div>
              <div>next matchday</div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 pb-24">
        <div className="mb-6 flex items-end justify-between gap-4">
          <div>
            <h2 className="display text-4xl">Upcoming matchday</h2>
            <p className="mt-1 text-muted">Tap a fixture for drivers, market comparison, and player what-ifs.</p>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {shown.map((m, i) => (
            <MatchRow key={m.match_uid} match={m} index={i} />
          ))}
        </div>
      </section>
    </div>
  );
}
