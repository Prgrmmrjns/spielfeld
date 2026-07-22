<script setup lang="ts">
type TopFeature = {
  feature: string
  label: string
  shap: number
}

type Prediction = {
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
  explanation?: {
    plot: string
    method: string
    class: string
    baseline: number
    top_features: TopFeature[]
  } | null
}

const props = defineProps<{
  match: Prediction | null
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

watch(() => props.open, (isOpen) => {
  if (!import.meta.client) return
  document.body.style.overflow = isOpen ? 'hidden' : ''
})

onBeforeUnmount(() => {
  if (!import.meta.client) return
  document.body.style.overflow = ''
})

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  if (!import.meta.client) return
  window.addEventListener('keydown', onKey)
})

onBeforeUnmount(() => {
  if (!import.meta.client) return
  window.removeEventListener('keydown', onKey)
})

const tipLabel = computed(() => {
  if (!props.match) return ''
  if (props.match.predicted === 'home_win') return props.match.home_short
  if (props.match.predicted === 'away_win') return props.match.away_short
  return 'Draw'
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open && match"
      class="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-4 backdrop-blur-sm md:items-center"
      @click.self="emit('close')"
    >
      <div class="animate-rise max-h-[92vh] w-full max-w-3xl overflow-y-auto border border-white/10 bg-[#101912] shadow-2xl">
        <div class="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-white/10 bg-[#101912]/95 px-5 py-4 backdrop-blur md:px-6">
          <div>
            <p class="text-xs uppercase tracking-[0.18em] text-white/45">
              SHAP explanation
            </p>
            <h3 class="mt-1 font-[family-name:var(--font-display)] text-3xl tracking-[0.06em] text-white">
              {{ match.home_short }} vs {{ match.away_short }}
            </h3>
            <p class="mt-1 text-sm text-white/60">
              Tip <span class="text-[var(--accent)]">{{ tipLabel }}</span>
              · {{ match.explanation?.method || 'unavailable' }}
            </p>
          </div>
          <button
            type="button"
            class="border border-white/20 px-3 py-2 text-xs uppercase tracking-[0.16em] text-white/70 transition hover:border-white/40 hover:text-white"
            @click="emit('close')"
          >
            Close
          </button>
        </div>

        <div class="space-y-6 px-5 py-5 md:px-6">
          <div v-if="match.explanation?.plot" class="overflow-hidden bg-white">
            <img
              :src="match.explanation.plot"
              :alt="`SHAP waterfall for ${match.home_team} vs ${match.away_team}`"
              class="h-auto w-full"
            >
          </div>
          <div v-else class="py-10 text-center text-white/50">
            No SHAP plot for this matchup. Re-run <code class="text-[var(--accent)]">python predict.py</code>.
          </div>

          <div v-if="match.explanation?.top_features?.length">
            <p class="mb-3 text-xs uppercase tracking-[0.18em] text-white/45">
              Top drivers for {{ match.predicted.replace('_', ' ') }}
            </p>
            <ul class="space-y-2">
              <li
                v-for="feat in match.explanation.top_features"
                :key="feat.feature"
                class="grid grid-cols-[1fr_auto] gap-3 border-t border-white/10 py-2 text-sm first:border-t-0"
              >
                <span class="text-white/80">{{ feat.label }}</span>
                <span
                  class="tabular-nums"
                  :class="feat.shap >= 0 ? 'text-[var(--accent)]' : 'text-pitch-300'"
                >
                  {{ feat.shap >= 0 ? '+' : '' }}{{ feat.shap.toFixed(3) }}
                </span>
              </li>
            </ul>
            <p class="mt-4 text-xs leading-relaxed text-white/40">
              Shapley values attribute the predicted class probability relative to the baseline
              ({{ match.explanation.baseline.toFixed(3) }}). Positive pushes toward the tip.
              Method from
              <a
                href="https://docs.priorlabs.ai/capabilities/interpretability"
                target="_blank"
                rel="noopener"
                class="text-white/70 underline decoration-white/30 underline-offset-2 hover:text-white"
              >Prior Labs interpretability</a>.
            </p>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>
