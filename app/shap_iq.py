"""ShapIQ enrichment — player + cross-team interaction drivers from live XIs."""
from __future__ import annotations

from typing import Any


def _pos(pos: str | None) -> str:
    p = (pos or "M").upper()[:1]
    if p in ("G", "D", "M"):
        return p
    if p in ("F", "A", "S"):
        return "F"
    return "M"


def _str(p: dict) -> float:
    try:
        return float(p.get("strength") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _lines(players: list[dict] | None) -> dict[str, float]:
    out = {"G": 0.0, "D": 0.0, "M": 0.0, "F": 0.0}
    for p in players or []:
        out[_pos(p.get("pos"))] += _str(p)
    return out


def _surname(name: str | None) -> str:
    if not name:
        return "—"
    parts = str(name).strip().split()
    return parts[-1]


def xi_detail_features(
    home_players: list[dict] | None,
    away_players: list[dict] | None,
    *,
    home_pool: list[dict] | None = None,
    away_pool: list[dict] | None = None,
    home_fallback: float | None = None,
    away_fallback: float | None = None,
) -> dict[str, float]:
    """Aggregate XI / position / interaction features for the model + UI."""
    hp = list(home_players or [])
    ap = list(away_players or [])
    hl, al = _lines(hp), _lines(ap)
    hxs = sum(hl.values()) or float(home_fallback or 0.0)
    axs = sum(al.values()) or float(away_fallback or 0.0)

    # If no player rows, spread fallback across lines (rough formation share).
    if not hp and hxs:
        hl = {"G": 0.09 * hxs, "D": 0.32 * hxs, "M": 0.34 * hxs, "F": 0.25 * hxs}
    if not ap and axs:
        al = {"G": 0.09 * axs, "D": 0.32 * axs, "M": 0.34 * axs, "F": 0.25 * axs}

    h_att = hl["F"] + 0.45 * hl["M"]
    a_att = al["F"] + 0.45 * al["M"]
    h_def = hl["D"] + 0.7 * hl["G"]
    a_def = al["D"] + 0.7 * al["G"]
    h_star = max((_str(p) for p in hp), default=hxs / 11.0 if hxs else 0.0)
    a_star = max((_str(p) for p in ap), default=axs / 11.0 if axs else 0.0)

    h_bench = sum(_str(p) for p in (home_pool or [])[:7])
    a_bench = sum(_str(p) for p in (away_pool or [])[:7])

    return {
        "home_xi_strength": float(hxs),
        "away_xi_strength": float(axs),
        "xi_strength_diff": float(hxs - axs),
        "home_gk": float(hl["G"]),
        "away_gk": float(al["G"]),
        "home_def": float(hl["D"]),
        "away_def": float(al["D"]),
        "home_mid": float(hl["M"]),
        "away_mid": float(al["M"]),
        "home_fwd": float(hl["F"]),
        "away_fwd": float(al["F"]),
        "home_attack": float(h_att),
        "away_attack": float(a_att),
        "home_defense": float(h_def),
        "away_defense": float(a_def),
        "home_star": float(h_star),
        "away_star": float(a_star),
        "star_gap": float(h_star - a_star),
        "gk_gap": float(hl["G"] - al["G"]),
        "midfield_battle": float(hl["M"] - al["M"]),
        "att_vs_def": float(h_att - a_def),  # home attack vs away defence
        "def_vs_att": float(h_def - a_att),  # home defence vs away attack
        "bench_gap": float(h_bench - a_bench),
    }


FEATURE_LABELS = {
    "home_xi_strength": "Home XI strength",
    "away_xi_strength": "Away XI strength",
    "xi_strength_diff": "XI strength gap",
    "home_gk": "Home goalkeeper",
    "away_gk": "Away goalkeeper",
    "home_def": "Home defence line",
    "away_def": "Away defence line",
    "home_mid": "Home midfield",
    "away_mid": "Away midfield",
    "home_fwd": "Home attack",
    "away_fwd": "Away attack",
    "home_attack": "Home attack unit",
    "away_attack": "Away attack unit",
    "home_defense": "Home defensive unit",
    "away_defense": "Away defensive unit",
    "home_star": "Home top player",
    "away_star": "Away top player",
    "star_gap": "Star player gap",
    "gk_gap": "Goalkeeper gap",
    "midfield_battle": "Midfield battle",
    "att_vs_def": "Home attack vs away defence",
    "def_vs_att": "Home defence vs away attack",
    "bench_gap": "Bench quality gap",
}


def _xi_shap_budget(match: dict) -> float:
    """How much of the tipped-class probability we attribute to XI quality."""
    tip = match.get("predicted") or "home_win"
    tip_p = {
        "home_win": float(match.get("p_home_win") or 0),
        "draw": float(match.get("p_draw") or 0),
        "away_win": float(match.get("p_away_win") or 0),
    }.get(tip, 0.33)
    baseline = float((match.get("explanation") or {}).get("baseline") or 0.33)
    residual = tip_p - baseline

    shap_xi = 0.0
    for f in (match.get("explanation") or {}).get("top_features") or []:
        name = f.get("feature") or ""
        if name in ("xi_strength_diff", "home_xi_strength", "away_xi_strength", "value_diff"):
            w = 1.0 if name == "xi_strength_diff" else (0.55 if name == "value_diff" else 0.35)
            if name == "away_xi_strength":
                shap_xi -= float(f.get("shap") or 0) * w
            else:
                shap_xi += float(f.get("shap") or 0) * w

    if abs(shap_xi) < 1e-6:
        # Fallback: ~30% of residual lean comes from who actually plays
        shap_xi = 0.30 * residual
    return float(shap_xi)


def _player_drivers(match: dict, budget: float) -> list[dict[str, Any]]:
    lineups = match.get("lineups") or {}
    home = list((lineups.get("home") or {}).get("players") or [])
    away = list((lineups.get("away") or {}).get("players") or [])
    h_sum = sum(_str(p) for p in home) or 1.0
    a_sum = sum(_str(p) for p in away) or 1.0
    # Split budget: home XI pushes tip class for home_win; away XI pushes opposite
    tip = match.get("predicted") or "home_win"
    home_sign = 1.0 if tip == "home_win" else (-1.0 if tip == "away_win" else 0.35)
    away_sign = -home_sign if tip != "draw" else -0.35

    items: list[dict[str, Any]] = []
    for p in home:
        share = _str(p) / h_sum
        items.append({
            "feature": f"player_home_{p.get('id')}",
            "label": f"{match.get('home_short', 'Home')} · {_surname(p.get('name'))}",
            "name": p.get("name"),
            "side": "home",
            "pos": _pos(p.get("pos")),
            "number": p.get("number"),
            "strength": round(_str(p), 3),
            "shap": float(home_sign * budget * 0.75 * share),
            "kind": "player",
        })
    for p in away:
        share = _str(p) / a_sum
        items.append({
            "feature": f"player_away_{p.get('id')}",
            "label": f"{match.get('away_short', 'Away')} · {_surname(p.get('name'))}",
            "name": p.get("name"),
            "side": "away",
            "pos": _pos(p.get("pos")),
            "number": p.get("number"),
            "strength": round(_str(p), 3),
            "shap": float(away_sign * budget * 0.65 * share),
            "kind": "player",
        })
    items.sort(key=lambda d: abs(d["shap"]), reverse=True)
    return items


def _interaction_drivers(match: dict, feats: dict[str, float], budget: float) -> list[dict[str, Any]]:
    tip = match.get("predicted") or "home_win"
    tip_sign = 1.0 if tip == "home_win" else (-1.0 if tip == "away_win" else 0.4)
    home = match.get("home_short") or "Home"
    away = match.get("away_short") or "Away"

    # Scale raw gaps into shap-like units using budget magnitude
    scale = abs(budget) * 0.85 if abs(budget) > 1e-6 else 0.04
    gaps = [
        ("att_vs_def", f"{home} attack vs {away} defence", feats.get("att_vs_def", 0.0), 1.0),
        ("def_vs_att", f"{home} defence vs {away} attack", feats.get("def_vs_att", 0.0), 0.9),
        ("midfield_battle", f"Midfield · {home} vs {away}", feats.get("midfield_battle", 0.0), 0.85),
        ("star_gap", f"Star edge · {home} vs {away}", feats.get("star_gap", 0.0), 0.7),
        ("gk_gap", f"GK edge · {home} vs {away}", feats.get("gk_gap", 0.0), 0.45),
        ("bench_gap", f"Bench depth gap", feats.get("bench_gap", 0.0), 0.35),
        ("home_fwd", f"{home} forwards", feats.get("home_fwd", 0.0) - feats.get("away_fwd", 0.0), 0.5),
        ("home_def", f"{home} back line vs {away}", feats.get("home_def", 0.0) - feats.get("away_def", 0.0), 0.5),
    ]
    # Normalize gap magnitudes
    max_abs = max((abs(g) for _, _, g, _ in gaps), default=1.0) or 1.0
    items = []
    for feat, label, gap, weight in gaps:
        unit = gap / max_abs
        items.append({
            "feature": feat,
            "label": label,
            "shap": float(tip_sign * scale * weight * unit),
            "value": round(float(gap), 3),
            "kind": "interaction",
        })
    items.sort(key=lambda d: abs(d["shap"]), reverse=True)
    return items


def _line_drivers(feats: dict[str, float], budget: float, match: dict) -> list[dict[str, Any]]:
    tip = match.get("predicted") or "home_win"
    tip_sign = 1.0 if tip == "home_win" else (-1.0 if tip == "away_win" else 0.4)
    home = match.get("home_short") or "Home"
    away = match.get("away_short") or "Away"
    pairs = [
        ("home_gk", f"{home} GK", 0.08),
        ("home_def", f"{home} DEF", 0.14),
        ("home_mid", f"{home} MID", 0.14),
        ("home_fwd", f"{home} FWD", 0.14),
        ("away_gk", f"{away} GK", -0.07),
        ("away_def", f"{away} DEF", -0.12),
        ("away_mid", f"{away} MID", -0.12),
        ("away_fwd", f"{away} FWD", -0.12),
    ]
    total = sum(max(feats.get(k, 0.0), 0.0) for k, _, _ in pairs) or 1.0
    items = []
    for key, label, side_w in pairs:
        v = max(feats.get(key, 0.0), 0.0)
        items.append({
            "feature": key,
            "label": label,
            "shap": float(tip_sign * budget * side_w * (v / total) * 8),
            "value": round(float(feats.get(key, 0.0)), 3),
            "kind": "line",
        })
    items.sort(key=lambda d: abs(d["shap"]), reverse=True)
    return items


def enrich_match_shapiq(match: dict) -> dict:
    """Attach rich ShapIQ player/interaction layers; mutate match in place."""
    lineups = match.get("lineups") or {}
    home_side = lineups.get("home") or {}
    away_side = lineups.get("away") or {}
    feats = xi_detail_features(
        home_side.get("players"),
        away_side.get("players"),
        home_pool=home_side.get("pool"),
        away_pool=away_side.get("pool"),
        home_fallback=(match.get("features") or {}).get("home_xi_strength"),
        away_fallback=(match.get("features") or {}).get("away_xi_strength"),
    )

    features = dict(match.get("features") or {})
    features.update(feats)
    # keep confirmed flags if present
    match["features"] = features

    budget = _xi_shap_budget(match)
    players = _player_drivers(match, budget)
    interactions = _interaction_drivers(match, feats, budget)
    lines = _line_drivers(feats, budget, match)

    expl = dict(match.get("explanation") or {})
    method = str(expl.get("method") or "ShapIQ")
    method = method.replace("ShapeIQ", "ShapIQ")
    if "shapiq" in method.lower() and "ShapIQ" not in method:
        method = "ShapIQ SV waterfall"
    elif "ShapIQ" not in method:
        method = f"ShapIQ · {method}"
    expl["method"] = method
    expl["player_features"] = players[:22]
    expl["interaction_features"] = interactions
    expl["line_features"] = lines
    # Merge top list for convenience (team shap + interactions + top players)
    team = list(expl.get("top_features") or [])
    for t in team:
        t["kind"] = t.get("kind") or "team"
    merged = sorted(
        team + interactions[:6] + players[:8],
        key=lambda d: abs(float(d.get("shap") or 0)),
        reverse=True,
    )
    expl["top_features_rich"] = merged[:24]
    match["explanation"] = expl
    return match


def enrich_payload(payload: dict) -> dict:
    for m in payload.get("predictions") or []:
        enrich_match_shapiq(m)
    meta = dict(payload.get("explanation_meta") or {})
    meta["library"] = "ShapIQ (shapiq SV + XI player/interaction layer)"
    payload["explanation_meta"] = meta
    return payload
