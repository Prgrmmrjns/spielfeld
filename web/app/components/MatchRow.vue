<script setup lang="ts">
type XiPlayer = { id?: number, name?: string, number?: number, pos?: string }
type XiSide = {
  source?: 'confirmed' | 'last_xi' | 'squad_estimate' | 'unknown' | string
  formation?: string | null
  players?: XiPlayer[]
}
type Prediction = {
  date: string
  home_team: string
  away_team: string
  home_short: string
  away_short: string
  home_icon?: string
  away_icon?: string
  predicted: 'home_win' | 'draw' | 'away_win' | string
  p_home_win: number
  p_draw: number
  p_away_win: number
  lineups?: {
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

const props = defineProps<{
  match: Prediction
  index: number
}>()

const emit = defineEmits<{
  select: [Prediction]
}>()

const kickoff = computed(() => {
  const d = new Date(props.match.date.endsWith('Z') || props.match.date.includes('+')
    ? props.match.date
    : `${props.match.date}Z`)
  if (Number.isNaN(d.getTime())) return props.match.date
  return new Intl.DateTimeFormat('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Berlin'
  }).format(d)
})

const tip = computed(() => {
  if (props.match.predicted === 'home_win') return props.match.home_short
  if (props.match.predicted === 'away_win') return props.match.away_short
  return 'Draw'
})

const confidence = computed(() => {
  const vals = [props.match.p_home_win, props.match.p_draw, props.match.p_away_win]
  return Math.max(...vals)
})

const bars = computed(() => [
  { key: 'H', label: 'Home', value: props.match.p_home_win, tone: 'bg-[var(--accent)]' },
  { key: 'D', label: 'Draw', value: props.match.p_draw, tone: 'bg-white/55' },
  { key: 'A', label: 'Away', value: props.match.p_away_win, tone: 'bg-pitch-400' }
])

const xiLabel = computed(() => {
  const h = props.match.lineups?.home?.source
  const a = props.match.lineups?.away?.source
  if (!h && !a) return null
  const label = (s?: string) => {
    if (s === 'confirmed') return 'confirmed'
    if (s === 'last_xi') return 'last XI'
    if (s === 'squad_estimate') return 'squad est.'
    return 'pending'
  }
  return `${label(h)} · ${label(a)}`
})
</script>

<template>
  <article
    class="animate-rise group border-t border-white/10 py-7 first:border-t-0 md:py-8"
    :style="{ animationDelay: `${0.08 * index}s` }"
  >
    <button
      type="button"
      class="grid w-full gap-5 text-left transition md:grid-cols-[1.2fr_1fr] md:items-center md:rounded-sm md:px-3 md:py-2 md:hover:bg-white/[0.03]"
      @click="emit('select', match)"
    >
      <div>
        <div class="mb-3 flex items-center justify-between gap-3">
          <p class="text-xs uppercase tracking-[0.18em] text-white/45">
            {{ kickoff }}
          </p>
          <p class="text-xs uppercase tracking-[0.16em] text-[var(--accent)] opacity-0 transition group-hover:opacity-100">
            View detail
          </p>
        </div>
        <div class="flex items-center gap-3">
          <img
            v-if="match.home_icon"
            :src="match.home_icon"
            :alt="match.home_team"
            class="h-9 w-9 object-contain"
            loading="lazy"
          >
          <div class="min-w-0">
            <p class="truncate text-xl font-semibold tracking-tight text-white md:text-2xl">
              {{ match.home_team }}
            </p>
            <p class="mt-1 truncate text-lg text-white/55 md:text-xl">
              {{ match.away_team }}
            </p>
          </div>
          <img
            v-if="match.away_icon"
            :src="match.away_icon"
            :alt="match.away_team"
            class="ml-auto h-9 w-9 object-contain opacity-80"
            loading="lazy"
          >
        </div>
        <p
          v-if="xiLabel"
          class="mt-3 text-xs uppercase tracking-[0.14em] text-white/40"
        >
          XI {{ xiLabel }}
        </p>
      </div>

      <div>
        <div class="mb-4 flex items-end justify-between gap-4">
          <div>
            <p class="text-xs uppercase tracking-[0.18em] text-white/45">
              Model tip
            </p>
            <p class="font-[family-name:var(--font-display)] text-3xl tracking-wide text-[var(--accent)]">
              {{ tip }}
            </p>
          </div>
          <p class="text-sm text-white/60">
            {{ Math.round(confidence * 100) }}% lean
          </p>
        </div>

        <div class="space-y-2.5">
          <div
            v-for="(bar, i) in bars"
            :key="bar.key"
            class="grid grid-cols-[1.5rem_1fr_2.5rem] items-center gap-3 text-sm"
          >
            <span class="text-white/50">{{ bar.key }}</span>
            <div class="h-2 overflow-hidden rounded-sm bg-white/10">
              <div
                class="prob-bar h-full rounded-sm"
                :class="bar.tone"
                :style="{ width: `${Math.max(bar.value * 100, 2)}%`, animationDelay: `${0.15 * i}s` }"
              />
            </div>
            <span class="text-right tabular-nums text-white/70">
              {{ Math.round(bar.value * 100) }}%
            </span>
          </div>
        </div>
      </div>
    </button>
  </article>
</template>
