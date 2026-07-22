<script setup lang="ts">
import payload from '~/data/predictions.json'

type XiPlayer = { id?: number, name?: string, number?: number, pos?: string }
type XiSide = {
  source?: string
  formation?: string | null
  players?: XiPlayer[]
  strength?: number | null
}

type Prediction = {
  match_id?: number
  date: string
  home_team: string
  away_team: string
  home_short: string
  away_short: string
  home_icon?: string
  away_icon?: string
  predicted: string
  p_home_win: number
  p_draw: number
  p_away_win: number
  lineups?: {
    api_fixture_id?: number | null
    home?: XiSide
    away?: XiSide
  } | null
  explanation?: {
    plot: string
    method: string
    class: string
    baseline: number
    top_features: Array<{ feature: string, label: string, shap: number }>
  } | null
}

type PredictionPayload = {
  league: string
  season: string
  matchday: number
  matchday_name: string
  generated_at: string
  lineups_refreshed_at?: string
  lineups_provider?: string | null
  model: string
  train_matches: number
  predictions: Prediction[]
}

const data = ref(payload as PredictionPayload)
const pending = ref(false)
const error = ref<Error | null>(null)
const lineupsLiveAt = ref<string | null>(null)

async function mergeLiveLineups() {
  if (!import.meta.client) return
  try {
    const res = await $fetch<{
      refreshed_at?: string
      lineups?: Record<string, Prediction['lineups']>
    }>('/api/lineups')
    if (!res?.lineups) return
    data.value = {
      ...data.value,
      predictions: data.value.predictions.map((m) => {
        const live = res.lineups?.[String(m.match_id)]
        return live ? { ...m, lineups: live } : m
      })
    }
    lineupsLiveAt.value = res.refreshed_at || new Date().toISOString()
  } catch {
    // keep baked lineups
  }
}

onMounted(() => {
  mergeLiveLineups()
  // Refresh lineups while the page is open (pre-match window).
  const id = window.setInterval(mergeLiveLineups, 15 * 60 * 1000)
  onBeforeUnmount(() => window.clearInterval(id))
})

const selected = ref<Prediction | null>(null)
const modalOpen = computed({
  get: () => selected.value !== null,
  set: (open: boolean) => {
    if (!open) selected.value = null
  }
})

const generatedLabel = computed(() => {
  const stamp = lineupsLiveAt.value || data.value?.lineups_refreshed_at || data.value?.generated_at
  if (!stamp) return ''
  const d = new Date(stamp)
  if (Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat('en-GB', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Europe/Berlin'
  }).format(d)
})
</script>

<template>
  <div class="relative min-h-screen overflow-hidden">
    <div class="pointer-events-none absolute inset-0">
      <div class="absolute inset-0 bg-[radial-gradient(ellipse_at_20%_0%,#2a5a38_0%,transparent_45%),radial-gradient(ellipse_at_90%_10%,#1d3a28_0%,transparent_40%),linear-gradient(180deg,#101912_0%,#0b130e_55%,#08100c_100%)]" />
      <div
        class="hero-glow absolute -top-24 left-1/2 h-[28rem] w-[48rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(212,255,63,0.18),transparent_70%)] blur-2xl"
      />
      <div
        class="absolute inset-0 opacity-[0.07]"
        style="background-image: linear-gradient(rgba(255,255,255,0.35) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.35) 1px, transparent 1px); background-size: 72px 72px;"
      />
    </div>

    <header class="relative z-10 mx-auto flex max-w-6xl items-center justify-between px-6 py-6 md:px-8">
      <p class="font-[family-name:var(--font-display)] text-3xl tracking-[0.08em] text-white">
        SPIELFELD
      </p>
      <p class="text-xs uppercase tracking-[0.2em] text-white/50">
        Bundesliga · Next Matchday
      </p>
    </header>

    <main class="relative z-10 mx-auto max-w-6xl px-6 pb-20 md:px-8">
      <section class="min-h-[72vh] content-center py-10 md:py-16">
        <p class="animate-rise text-sm uppercase tracking-[0.24em] text-[var(--accent)]">
          {{ data?.matchday_name || 'Next Spieltag' }} · {{ data?.season }}
        </p>
        <h1 class="animate-rise animate-rise-delay-1 mt-4 max-w-4xl font-[family-name:var(--font-display)] text-6xl leading-[0.92] tracking-[0.04em] text-white md:text-8xl">
          SPIELFELD
        </h1>
        <p class="animate-rise animate-rise-delay-2 mt-5 max-w-xl text-lg text-white/70 md:text-xl">
          Probability tips for the next Bundesliga matchday — form, ELO, and live starting XIs from API-Football.
        </p>
        <div class="animate-rise animate-rise-delay-3 mt-8 flex flex-wrap items-center gap-3">
          <a
            href="#tips"
            class="inline-flex items-center bg-[var(--accent)] px-5 py-3 text-sm font-semibold uppercase tracking-[0.14em] text-[#132016] transition hover:brightness-110"
          >
            See tips
          </a>
        </div>
      </section>

      <section id="tips" class="mt-4 border-t border-white/10 pt-12">
        <div class="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 class="font-[family-name:var(--font-display)] text-4xl tracking-[0.06em] text-white md:text-5xl">
              Matchday tips
            </h2>
            <p class="mt-2 max-w-xl text-white/60">
              Click a matchup for starting XI and SHAP drivers. Unconfirmed sides use the last starting XI.
            </p>
          </div>
          <div class="text-right text-sm text-white/45">
            <p v-if="data">
              {{ data.model }} · {{ data.train_matches }} training matches
            </p>
            <p v-if="generatedLabel">
              Lineups {{ generatedLabel }}
            </p>
          </div>
        </div>

        <div v-if="pending && !data" class="py-16 text-white/50">
          Loading predictions…
        </div>
        <div v-else-if="error" class="py-16 text-red-300">
          Could not load predictions.
        </div>
        <div v-else-if="data?.predictions?.length" class="divide-y divide-transparent">
          <MatchRow
            v-for="(match, index) in data.predictions"
            :key="`${match.home_team}-${match.away_team}-${match.date}`"
            :match="match"
            :index="index"
            @select="selected = $event"
          />
        </div>
        <div v-else class="py-16 text-white/50">
          No fixtures in the current prediction set.
        </div>
      </section>
    </main>

    <ShapModal
      :open="modalOpen"
      :match="selected"
      @close="selected = null"
    />
  </div>
</template>
