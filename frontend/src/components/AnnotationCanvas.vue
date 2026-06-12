<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  imageUrl: { type: String, required: true },
  maskUrl: { type: String, default: null },
  showMask: { type: Boolean, default: false },
  classes: { type: Array, default: () => [] },
  tool: { type: String, default: 'scribble' }, // 'scribble' | 'box' | 'pan' | 'erase'
  activeLabel: { type: Number, default: 1 },
  brush: { type: Number, default: 6 },
})
const annotation = defineModel({ default: () => ({ boxes: [], scribbles: [] }) })

const wrap = ref(null)
const overlay = ref(null)
const imgEl = ref(null)
const natural = reactive({ w: 0, h: 0 })
const view = reactive({ scale: 1, x: 0, y: 0 })
const loaded = ref(false)

let drawing = false
let panning = false
let last = { x: 0, y: 0 }
let activeStroke = null
let activeBox = null

const colorFor = (label) =>
  props.classes.find((c) => c.id === label)?.color || '#2fe6cf'

// --- coordinate mapping: screen -> image pixels ---
function toImage(ev) {
  const r = wrap.value.getBoundingClientRect()
  const sx = ev.clientX - r.left
  const sy = ev.clientY - r.top
  return {
    x: (sx - view.x) / view.scale,
    y: (sy - view.y) / view.scale,
  }
}

function onImgLoad() {
  natural.w = imgEl.value.naturalWidth
  natural.h = imgEl.value.naturalHeight
  overlay.value.width = natural.w
  overlay.value.height = natural.h
  loaded.value = true
  fit()
  redraw()
}

function fit() {
  const r = wrap.value.getBoundingClientRect()
  const s = Math.min(r.width / natural.w, r.height / natural.h) * 0.96
  view.scale = s || 1
  view.x = (r.width - natural.w * view.scale) / 2
  view.y = (r.height - natural.h * view.scale) / 2
}

// --- pointer handlers ---
function down(ev) {
  if (!loaded.value) return
  const wantPan = props.tool === 'pan' || ev.button === 1 || ev.spaceKey
  if (wantPan) { panning = true; last = { x: ev.clientX, y: ev.clientY }; return }
  const p = toImage(ev)
  if (props.tool === 'box') {
    activeBox = { label: props.activeLabel, x: p.x, y: p.y, w: 0, h: 0 }
    drawing = true
  } else if (props.tool === 'scribble') {
    activeStroke = { label: props.activeLabel, points: [[round(p.x), round(p.y)]] }
    annotation.value.scribbles.push(activeStroke)
    drawing = true
  } else if (props.tool === 'erase') {
    eraseAt(p)
  }
}

function move(ev) {
  if (panning) {
    view.x += ev.clientX - last.x
    view.y += ev.clientY - last.y
    last = { x: ev.clientX, y: ev.clientY }
    return
  }
  if (!drawing) return
  const p = toImage(ev)
  if (props.tool === 'box' && activeBox) {
    activeBox.w = p.x - activeBox.x
    activeBox.h = p.y - activeBox.y
    redraw()
  } else if (props.tool === 'scribble' && activeStroke) {
    activeStroke.points.push([round(p.x), round(p.y)])
    redraw()
  }
}

function up() {
  if (drawing && props.tool === 'box' && activeBox) {
    // normalise negative drags and commit if non-trivial
    let { x, y, w, h } = activeBox
    if (w < 0) { x += w; w = -w }
    if (h < 0) { y += h; h = -h }
    if (w > 3 && h > 3) {
      annotation.value.boxes.push({ label: activeBox.label, x: round(x), y: round(y), w: round(w), h: round(h) })
    }
    activeBox = null
  }
  drawing = false
  panning = false
  activeStroke = null
  redraw()
}

function eraseAt(p) {
  const R = props.brush * 2.5
  annotation.value.scribbles = annotation.value.scribbles.filter(
    (s) => !s.points.some(([x, y]) => Math.hypot(x - p.x, y - p.y) < R)
  )
  annotation.value.boxes = annotation.value.boxes.filter(
    (b) => !(p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h)
  )
  redraw()
}

function wheel(ev) {
  ev.preventDefault()
  const r = wrap.value.getBoundingClientRect()
  const cx = ev.clientX - r.left
  const cy = ev.clientY - r.top
  const factor = ev.deltaY < 0 ? 1.12 : 1 / 1.12
  const ns = Math.min(20, Math.max(0.1, view.scale * factor))
  // zoom toward cursor
  view.x = cx - (cx - view.x) * (ns / view.scale)
  view.y = cy - (cy - view.y) * (ns / view.scale)
  view.scale = ns
}

const round = (v) => Math.round(v)

// --- overlay drawing ---
function redraw() {
  const cv = overlay.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  ctx.clearRect(0, 0, cv.width, cv.height)

  // scribbles
  for (const s of annotation.value.scribbles) {
    if (s.points.length < 1) continue
    ctx.strokeStyle = colorFor(s.label)
    ctx.fillStyle = colorFor(s.label)
    ctx.lineWidth = props.brush
    ctx.lineJoin = ctx.lineCap = 'round'
    if (s.points.length === 1) {
      const [x, y] = s.points[0]
      ctx.beginPath(); ctx.arc(x, y, props.brush / 2, 0, Math.PI * 2); ctx.fill()
    } else {
      ctx.beginPath()
      ctx.moveTo(s.points[0][0], s.points[0][1])
      for (const [x, y] of s.points.slice(1)) ctx.lineTo(x, y)
      ctx.stroke()
    }
  }

  // committed boxes
  for (const b of annotation.value.boxes) drawBox(ctx, b)
  // box being drawn
  if (activeBox) drawBox(ctx, activeBox, true)
}

function drawBox(ctx, b, live = false) {
  ctx.save()
  ctx.strokeStyle = colorFor(b.label)
  ctx.lineWidth = Math.max(1.5, 2 / view.scale)
  ctx.setLineDash(live ? [6, 4] : [])
  ctx.strokeRect(b.x, b.y, b.w, b.h)
  ctx.fillStyle = colorFor(b.label) + '22'
  ctx.fillRect(b.x, b.y, b.w, b.h)
  ctx.restore()
}

const transform = computed(
  () => `translate(${view.x}px, ${view.y}px) scale(${view.scale})`
)

watch(() => annotation.value, redraw, { deep: true })
watch(() => props.brush, redraw)

// space-to-pan
function keydown(e) { if (e.code === 'Space') spaceHeld = true }
function keyup(e) { if (e.code === 'Space') spaceHeld = false }
let spaceHeld = false
function downWrap(ev) { down({ ...ev, spaceKey: spaceHeld, clientX: ev.clientX, clientY: ev.clientY, button: ev.button }) }

onMounted(() => {
  window.addEventListener('keydown', keydown)
  window.addEventListener('keyup', keyup)
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', keydown)
  window.removeEventListener('keyup', keyup)
  window.removeEventListener('pointermove', move)
  window.removeEventListener('pointerup', up)
})

defineExpose({ fit, clear: () => { annotation.value.boxes = []; annotation.value.scribbles = []; redraw() } })
</script>

<template>
  <div
    ref="wrap"
    class="canvas-wrap viewport"
    :class="{ panning: tool === 'pan' }"
    @pointerdown="downWrap"
    @wheel="wheel"
  >
    <div class="stage" :style="{ transform }">
      <img
        ref="imgEl"
        :src="imageUrl"
        class="base-img"
        @load="onImgLoad"
        draggable="false"
        alt="annotation target"
      />
      <img
        v-if="showMask && maskUrl"
        :src="maskUrl"
        class="mask-img"
        draggable="false"
        alt="predicted mask"
      />
      <canvas ref="overlay" class="overlay"></canvas>
    </div>

    <div class="hud mono">
      <span>{{ natural.w }}×{{ natural.h }}</span>
      <span class="faint">·</span>
      <span>{{ (view.scale * 100).toFixed(0) }}%</span>
      <button class="btn btn-ghost btn-sm" @click="fit">fit</button>
    </div>
  </div>
</template>

<style scoped>
.canvas-wrap { position: relative; width: 100%; height: 100%; cursor: crosshair; touch-action: none; }
.canvas-wrap.panning { cursor: grab; }
.stage { position: absolute; top: 0; left: 0; transform-origin: 0 0; will-change: transform; }
.base-img { display: block; image-rendering: pixelated; user-select: none; }
.mask-img { position: absolute; top: 0; left: 0; opacity: 0.5; mix-blend-mode: screen; image-rendering: pixelated; pointer-events: none; }
.overlay { position: absolute; top: 0; left: 0; pointer-events: none; }
.hud {
  position: absolute; bottom: 10px; left: 10px;
  display: flex; align-items: center; gap: 8px;
  padding: 5px 8px; border-radius: 6px;
  background: rgba(8, 10, 14, 0.7); border: 1px solid var(--line);
  font-size: 11px; color: var(--ink-soft);
}
</style>
