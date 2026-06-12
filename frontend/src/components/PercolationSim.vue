<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'

// Renders an invasion-percolation result: the int16 time-of-invasion map is
// decoded and animated by sweeping a threshold t — every pore voxel with
// 0 <= time <= t is "filled". The most recently invaded band is drawn as a
// bright magenta front over the cyan filled region, the classic finger view.
const props = defineProps({
  result: { type: Object, required: true }, // { shape, time_map_b64, n_steps, saturation_curve, breakthrough_step, percolates, porosity }
})

const canvas = ref(null)
const playing = ref(false)
const t = ref(0)          // current threshold (invasion step)
const speed = ref(1)
const state = reactive({ h: 0, w: 0, tmax: 0 })
let timeMap = null        // Int16Array
let raf = null
let imageData = null
let ctx = null

function decode() {
  const [h, w] = props.result.shape
  state.h = h; state.w = w
  const bin = atob(props.result.time_map_b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  timeMap = new Int16Array(bytes.buffer)
  let tmax = 0
  for (let i = 0; i < timeMap.length; i++) if (timeMap[i] > tmax) tmax = timeMap[i]
  state.tmax = tmax
  t.value = tmax // start fully filled; user can scrub/replay
}

function setup() {
  const cv = canvas.value
  cv.width = state.w
  cv.height = state.h
  ctx = cv.getContext('2d')
  imageData = ctx.createImageData(state.w, state.h)
  render()
}

// Colour ramp: filled voxels go cyan (old) -> violet (mid); the leading front
// (within ~6% of the current threshold) is magenta and brightest.
function render() {
  if (!timeMap || !imageData) return
  const data = imageData.data
  const cur = t.value
  const front = Math.max(1, state.tmax * 0.06)
  for (let i = 0; i < timeMap.length; i++) {
    const v = timeMap[i]
    const o = i * 4
    if (v < 0 || v > cur) {
      // un-invaded: faint dark-field
      data[o] = 10; data[o + 1] = 13; data[o + 2] = 18; data[o + 3] = 255
      continue
    }
    const age = cur > 0 ? v / cur : 1
    if (cur - v <= front) {
      // bright invasion front (magenta)
      data[o] = 240; data[o + 1] = 81; data[o + 2] = 158; data[o + 3] = 255
    } else {
      // filled body: cyan -> violet by age
      data[o] = 47 + age * 90
      data[o + 1] = 230 - age * 110
      data[o + 2] = 207 + age * 30
      data[o + 3] = 255
    }
  }
  ctx.putImageData(imageData, 0, 0)
}

function tick() {
  if (!playing.value) return
  t.value = Math.min(state.tmax, t.value + Math.max(1, Math.round(state.tmax / 240)) * speed.value)
  render()
  if (t.value >= state.tmax) { playing.value = false; return }
  raf = requestAnimationFrame(tick)
}

function play() {
  if (t.value >= state.tmax) t.value = 0
  playing.value = true
  raf = requestAnimationFrame(tick)
}
function pause() { playing.value = false; if (raf) cancelAnimationFrame(raf) }
function replay() { pause(); t.value = 0; render(); play() }
function onScrub() { pause(); render() }

// saturation sparkline path
const sparkPath = computed(() => {
  const c = props.result.saturation_curve || []
  if (c.length < 2) return ''
  const W = 220, H = 44
  return c.map((s, i) => `${(i / (c.length - 1)) * W},${H - s * H}`).join(' ')
})
const progressFrac = computed(() => state.tmax ? t.value / state.tmax : 0)

watch(() => props.result, () => { pause(); decode(); setup() })
onMounted(() => { decode(); setup() })
onBeforeUnmount(pause)
</script>

<template>
  <div class="perc">
    <div class="perc-stage viewport">
      <canvas ref="canvas" class="perc-canvas"></canvas>
      <div class="badge perc-tag mono" :class="result.percolates ? 'pos' : 'neg'">
        {{ result.percolates ? 'PERCOLATES' : 'NO SPANNING PATH' }}
      </div>
    </div>

    <div class="perc-controls">
      <button class="btn btn-primary" @click="playing ? pause() : play()">
        {{ playing ? '❚❚ Pause' : '▶ Play' }}
      </button>
      <button class="btn btn-sm" @click="replay">↻ Replay</button>

      <input
        class="scrub"
        type="range" min="0" :max="state.tmax" v-model.number="t"
        @input="onScrub"
      />
      <span class="mono faint step">{{ t }} / {{ state.tmax }}</span>

      <label class="spd mono">
        speed
        <select v-model.number="speed" class="field spd-sel">
          <option :value="0.5">0.5×</option>
          <option :value="1">1×</option>
          <option :value="2">2×</option>
          <option :value="4">4×</option>
        </select>
      </label>
    </div>

    <div class="perc-stats">
      <div class="stat">
        <span class="eyebrow">Porosity φ</span>
        <span class="mono big">{{ (result.porosity ?? 0).toFixed(3) }}</span>
      </div>
      <div class="stat">
        <span class="eyebrow">Breakthrough</span>
        <span class="mono big">{{ result.breakthrough_step ?? '—' }}</span>
      </div>
      <div class="stat">
        <span class="eyebrow">Invasion steps</span>
        <span class="mono big">{{ result.n_steps }}</span>
      </div>
      <div class="stat spark-stat">
        <span class="eyebrow">Saturation curve</span>
        <svg viewBox="0 0 220 44" class="spark" preserveAspectRatio="none">
          <polyline :points="sparkPath" fill="none" stroke="var(--cyan)" stroke-width="1.6" />
          <line :x1="progressFrac * 220" :x2="progressFrac * 220" y1="0" y2="44" stroke="var(--magenta)" stroke-width="1" />
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.perc { display: flex; flex-direction: column; gap: 14px; }
.perc-stage { position: relative; display: flex; align-items: center; justify-content: center; padding: 16px; min-height: 320px; }
.perc-canvas {
  max-width: 100%; max-height: 60vh; image-rendering: pixelated;
  border-radius: 6px; box-shadow: 0 0 40px -16px var(--magenta);
}
.perc-tag { position: absolute; top: 14px; left: 14px; }
.perc-tag.pos { color: var(--cyan); border-color: var(--cyan-deep); }
.perc-tag.neg { color: var(--ink-soft); }

.perc-controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.scrub { flex: 1; min-width: 160px; accent-color: var(--magenta); }
.step { font-size: 12px; white-space: nowrap; }
.spd { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-soft); }
.spd-sel { width: auto; padding: 5px 8px; }

.perc-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }
.stat { background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 12px; display: flex; flex-direction: column; gap: 6px; }
.big { font-size: 22px; color: var(--ink); }
.spark-stat { grid-column: span 2; }
.spark { width: 100%; height: 44px; }

@media (max-width: 640px) { .spark-stat { grid-column: span 1; } }
</style>
