import { getAblation, getMetrics, getShap, pct } from "@/lib/data";

export const dynamic = "force-static";

export default async function ModelPage() {
  const [metrics, ablation, shap] = await Promise.all([getMetrics(), getAblation(), getShap()]);
  const overall = (metrics.overall || {}) as Record<string, unknown>;
  const metricOf = (key: string) =>
    (overall[key] || {}) as { log_loss?: number; brier?: number; accuracy?: number; n?: number };
  const findings = ((ablation.findings || []) as {
    group: string;
    delta_log_loss_when_removed: number | null;
    useful: boolean;
    alone: { log_loss: number | null };
  }[]);
  const importance = ((metrics.feature_importance || []) as { feature: string; importance: number }[]).slice(
    0,
    15
  );
  const cal = (overall.calibration_home || {}) as {
    fraction_positives?: number[];
    mean_predicted?: number[];
  };

  const rows = [
    { name: "Spielfeld blend", key: "model" },
    { name: "LightGBM only", key: "lgbm_only" },
    { name: "Bookmaker", key: "bookmaker" },
    { name: "Elo only", key: "elo" },
  ];

  return (
    <div className="mx-auto max-w-5xl px-5 py-12">
      <h1 className="display text-5xl md:text-6xl">Model & findings</h1>
      <p className="mt-3 max-w-2xl text-muted">
        {(metrics.notes as string) ||
          "Walk-forward by season, LightGBM on pre-match features, blended with bookmaker implied probabilities."}
      </p>

      <section className="mt-10">
        <h2 className="display text-3xl">Walk-forward metrics</h2>
        <div className="glass mt-4 overflow-hidden rounded-2xl">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-white/10 text-muted">
              <tr>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3">Log loss</th>
                <th className="px-4 py-3">Brier</th>
                <th className="px-4 py-3">Accuracy</th>
                <th className="px-4 py-3">N</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const m = metricOf(r.key);
                return (
                  <tr key={r.key} className="border-b border-white/5">
                    <td className="px-4 py-3">{r.name}</td>
                    <td className="px-4 py-3">{m?.log_loss?.toFixed(4) ?? "—"}</td>
                    <td className="px-4 py-3">{m?.brier?.toFixed(4) ?? "—"}</td>
                    <td className="px-4 py-3">{m?.accuracy != null ? pct(m.accuracy, 1) : "—"}</td>
                    <td className="px-4 py-3">{m?.n ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-sm text-muted">
          Blend weight (bookmaker share):{" "}
          <span className="text-ink">{Number(metrics.blend_weight ?? 0).toFixed(2)}</span>
        </p>
      </section>

      <section className="mt-12 grid gap-6 md:grid-cols-2">
        <div className="glass rounded-2xl p-5">
          <h2 className="display text-3xl">Feature-group ablation</h2>
          <p className="mt-1 text-sm text-muted">Δ log loss when the group is removed from the full set.</p>
          <ul className="mt-4 space-y-2 text-sm">
            {findings.map((f) => (
              <li key={f.group} className="flex justify-between gap-3 border-b border-white/5 py-2">
                <span>
                  {f.group}{" "}
                  {f.useful ? <span className="text-home">useful</span> : <span className="text-muted">weak</span>}
                </span>
                <span className="text-muted">
                  {f.delta_log_loss_when_removed == null
                    ? "—"
                    : `${f.delta_log_loss_when_removed >= 0 ? "+" : ""}${f.delta_log_loss_when_removed.toFixed(4)}`}
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-sm text-muted">
            Selected groups:{" "}
            <span className="text-ink">{((ablation.selected_groups as string[]) || []).join(", ")}</span>
          </p>
        </div>

        <div className="glass rounded-2xl p-5">
          <h2 className="display text-3xl">SHAP / importance</h2>
          <p className="mt-1 text-sm text-muted">Mean |TreeSHAP| on the latest holdout season.</p>
          <ul className="mt-4 space-y-2 text-sm">
            {(shap.features || []).slice(0, 12).map((f) => (
              <li key={f.feature} className="flex justify-between gap-3 border-b border-white/5 py-2">
                <span>{f.feature}</span>
                <span className="text-muted">{f.mean_abs_shap.toFixed(3)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-6">
            <h3 className="text-sm text-muted">Gain importance</h3>
            <ul className="mt-2 space-y-2 text-sm">
              {importance.map((f) => (
                <li key={f.feature} className="flex justify-between gap-3">
                  <span>{f.feature}</span>
                  <span className="text-muted">{f.importance}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {cal.mean_predicted && cal.fraction_positives && (
        <section className="mt-12">
          <h2 className="display text-3xl">Home-win calibration</h2>
          <div className="glass mt-4 rounded-2xl p-5">
            <div className="flex h-40 items-end gap-2">
              {cal.mean_predicted.map((x, i) => {
                const y = cal.fraction_positives![i];
                return (
                  <div key={i} className="flex flex-1 flex-col items-center gap-2">
                    <div className="flex w-full items-end gap-1" style={{ height: "8rem" }}>
                      <div className="w-1/2 rounded-t bg-home/80" style={{ height: `${x * 100}%` }} title="pred" />
                      <div className="w-1/2 rounded-t bg-white/30" style={{ height: `${y * 100}%` }} title="obs" />
                    </div>
                    <div className="text-[10px] text-muted">{(x * 100).toFixed(0)}</div>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-muted">Green = mean predicted · Grey = observed home-win rate</p>
          </div>
        </section>
      )}
    </div>
  );
}
