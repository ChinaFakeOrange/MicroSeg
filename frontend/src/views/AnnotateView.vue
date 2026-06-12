<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useJobs } from '@/composables/useJobs'
import { api } from '@/api/client'
import AnnotationCanvas from '@/components/AnnotationCanvas.vue'

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const tasks = useTaskStore()
const { dispatch } = useJobs()

const canvas = ref(null)
const currentImage = ref(null)
const annotation = reactive({ boxes: [], scribbles: [] })
const tool = ref('scribble')
const activeLabel = ref(1)
const brush = ref(6)
const showMask = ref(false)
const maskOpacity = ref(0.5)
const saving = ref(false)
const savingMask = ref(false)
const dispatchError = ref(null)

const classes = computed(() => store.classes)
const images = computed(() => store.images)
const maskEditing = computed(() => tool.value === 'maskedit')

const maskUrl = computed(() =>
  currentImage.value ? api.maskUrl(props.id, currentImage.value.id) + `&t=${maskVersion.value}` : null
)
const rawMaskUrl = computed(() =>
  currentImage.value ? api.rawMaskUrl(props.id, currentImage.value.id) + `&t=${maskVersion.value}` : null
)
const maskVersion = ref(0)

watch(classes, (c) => {
  if (c.length && !c.find((x) => x.id === activeLabel.value)) activeLabel.value = c[0].id
})

async function selectImage(img) {
  await saveCurrent()
  currentImage.value = img
  const ann = await api.getAnnotation(props.id, img.id)
  annotation.boxes = ann.boxes || []
  annotation.scribbles = ann.scribbles || []
  showMask.value = false
}

// --- navigation for large image sets (sliders instead of a giant list) ---
const selectedOnly = ref(true)
const navList = computed(() => {
  if (!selectedOnly.value) return images.value
  const sel = images.value.filter((i) => i.selected !== false)
  return sel.length ? sel : images.value   // fall back to all if nothing is selected
})
const navIndex = computed(() => {
  const i = navList.value.findIndex((x) => x.id === currentImage.value?.id)
  return i < 0 ? 0 : i
})
// A small window of thumbnails around the current image (so we never render
// hundreds of <img> at once).
const windowImages = computed(() => {
  const list = navList.value
  if (!list.length) return []
  const c = navIndex.value
  const start = Math.max(0, Math.min(c - 4, list.length - 9))
  return list.slice(start, start + 9).map((img) => ({ img, idx: list.indexOf(img) }))
})
function goToIndex(i) {
  const list = navList.value
  const clamped = Math.max(0, Math.min(i, list.length - 1))
  if (list[clamped]) selectImage(list[clamped])
}
function step(d) { goToIndex(navIndex.value + d) }

async function saveCurrent() {
  if (!currentImage.value) return
  saving.value = true
  try {
    await api.saveAnnotation(props.id, currentImage.value.id, {
      boxes: annotation.boxes, scribbles: annotation.scribbles,
    })
  } finally { saving.value = false }
}

// Image gallery picker: the image pool is fixed at project creation; here you
// browse those images and choose which ones to annotate (no new uploads).
const pickerOpen = ref(false)
const everyN = ref(1)
const selectedCount = computed(() => images.value.filter((i) => i.selected !== false).length)

async function selectAllImages() {
  await store.setSelectedMany(images.value.map((i) => i.id), true)
}
async function clearSelection() {
  await store.setSelectedMany(images.value.map((i) => i.id), false)
}
async function selectEveryNth() {
  const n = Math.max(1, everyN.value)
  const sel = [], unsel = []
  images.value.forEach((img, i) => (i % n === 0 ? sel : unsel).push(img.id))
  await store.setSelectedMany(sel, true)
  await store.setSelectedMany(unsel, false)
}
function pickInGallery(img, e) {
  e.stopPropagation()
  store.toggleSelected(img.id, !(img.selected !== false))
}

// Dispatch interactive segmentation. Trains on the scribbles saved across ALL
// images and labels every uploaded image (matching the original behaviour).
async function runSegment() {
  dispatchError.value = null
  await saveCurrent()
  // Need scribbles on at least one image somewhere in the project.
  const hasLocal = annotation.scribbles.length > 0
  try {
    await dispatch('segment', props.id, { use_saved: true })  // image_ids omitted -> all
    showMask.value = true
  } catch (e) { dispatchError.value = e.message }
  if (!hasLocal && !store.images.length) dispatchError.value = 'Upload and scribble at least one image first.'
}

// When a segment task for this image finishes, bump the mask URL to reload it.
watch(() => tasks.list.map((t) => `${t.id}:${t.state}`).join(','), () => {
  const done = tasks.list.find((t) => t.type === 'segment' && t.state === 'done')
  if (done) maskVersion.value++
})

onMounted(async () => {
  if (store.current?.id !== props.id) await store.open(props.id)
  const first = store.images.find((i) => i.selected !== false) || store.images[0]
  if (first) selectImage(first)
})

const isDetection = computed(() => store.current?.task_type === 'detection')
watch(isDetection, (d) => { if (d) tool.value = 'box' }, { immediate: true })

// --- class add / delete (req 1) ---
const PALETTE = ['#2fe6cf', '#f0519e', '#8b7bf0', '#f2b441', '#4fd178', '#f0604d', '#3aa0ff', '#e0e0e0']
async function addClass() {
  const next = [...classes.value]
  const id = (next.at(-1)?.id || 0) + 1
  next.push({ id, name: `class ${id}`, color: PALETTE[id % PALETTE.length] })
  await store.updateClasses(next)
}
async function removeClass(c) {
  if (classes.value.length <= 1) { dispatchError.value = 'Keep at least one class.'; return }
  if (!confirm(`Delete class "${c.name}"? You'll need to re-run segmentation for the overlay to update.`)) return
  await store.updateClasses(classes.value.filter((x) => x.id !== c.id))
  dispatchError.value = 'Class deleted — re-run segmentation to refresh the overlay.'
}
async function renameClass(c, name) {
  await store.updateClasses(classes.value.map((x) => (x.id === c.id ? { ...x, name } : x)))
}

// --- manual mask edit save (req 6) ---
async function saveMask() {
  if (!currentImage.value || !canvas.value) return
  const png = canvas.value.getMaskPng()
  if (!png) return
  savingMask.value = true
  try {
    await api.saveMask(props.id, currentImage.value.id, png)
    maskVersion.value++          // refresh the colorized overlay from the saved labels
    dispatchError.value = null
  } catch (e) { dispatchError.value = e.message } finally { savingMask.value = false }
}

// --- apply segmentation to the rest of the images + export (req 5) ---
async function applyToRest() {
  dispatchError.value = null
  await saveCurrent()
  try {
    await dispatch('segment', props.id, { scope: 'rest', export: true })
  } catch (e) { dispatchError.value = e.message }
}

// --- selected / stored toggle (req 4) ---
async function toggleSelected(img, e) {
  e.stopPropagation()
  await store.toggleSelected(img.id, !(img.selected ?? true))
}

const exportHref = computed(() => {
  const t = tasks.list.find((t) => t.type === 'segment' && t.state === 'done' && t.result?.export)
  return t ? api.exportUrl(props.id, t.result.export) : null
})

// --- export ---
const exporting = ref(false)

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function baseName() {
  const n = currentImage.value?.name || currentImage.value?.id || 'image'
  return n.replace(/\.[^.]+$/, '') // strip extension
}

// Download the segmentation result as a PNG. `colorized=false` gives the raw
// label map (pixel value = class id) for downstream use; true gives the overlay.
async function exportMask(colorized) {
  if (!currentImage.value) return
  dispatchError.value = null
  exporting.value = true
  try {
    const url = colorized
      ? api.maskUrl(props.id, currentImage.value.id)
      : api.rawMaskUrl(props.id, currentImage.value.id)
    const res = await fetch(url)
    if (!res.ok) throw new Error(res.status === 404 ? 'No segmentation yet — run segmentation first.' : `Export failed (${res.status})`)
    const blob = await res.blob()
    triggerDownload(blob, `${baseName()}_${colorized ? 'overlay' : 'labels'}.png`)
  } catch (e) { dispatchError.value = e.message } finally { exporting.value = false }
}

// Download the raw annotation (boxes + scribbles) as JSON.
async function exportAnnotation() {
  if (!currentImage.value) return
  dispatchError.value = null
  await saveCurrent()
  const payload = {
    project_id: props.id,
    image_id: currentImage.value.id,
    image_name: currentImage.value.name,
    classes: classes.value,
    boxes: annotation.boxes,
    scribbles: annotation.scribbles,
  }
  triggerDownload(
    new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }),
    `${baseName()}_annotation.json`
  )
}
</script>

<template>
  <div class="annotate">
    <!-- left: image strip -->
    <div class="strip panel">
      <div class="strip-head">
        <span class="eyebrow">Images</span>
        <span class="badge mono">{{ images.length }}</span>
        <span class="spacer"></span>
        <span class="sel-count mono faint">{{ selectedCount }} to annotate</span>
        <button class="btn btn-sm" :disabled="!images.length" @click="pickerOpen = true">Select…</button>
      </div>
      <div v-if="images.length" class="nav">
        <div class="nav-row">
          <input
            class="nav-slider"
            type="range" min="0" :max="Math.max(0, navList.length - 1)"
            :value="navIndex" @input="goToIndex(+$event.target.value)"
          />
        </div>
        <div class="nav-row mono">
          <button class="btn btn-ghost btn-sm" :disabled="navIndex <= 0" @click="step(-1)">‹</button>
          <span class="counter">{{ navList.length ? navIndex + 1 : 0 }} / {{ navList.length }}</span>
          <button class="btn btn-ghost btn-sm" :disabled="navIndex >= navList.length - 1" @click="step(1)">›</button>
          <span class="spacer"></span>
          <label class="selonly"><input type="checkbox" v-model="selectedOnly" /> selected</label>
        </div>
        <div class="cur-name mono" v-if="currentImage">
          <span class="sel-dot inline" :class="{ on: currentImage.selected !== false }"
                @click="toggleSelected(currentImage, $event)"
                :title="currentImage.selected === false ? 'Stored — click to select' : 'Selected for annotation'"></span>
          <span class="ellipsis">{{ currentImage.name }}</span>
        </div>
      </div>

      <div class="thumbs">
        <button
          v-for="w in windowImages"
          :key="w.img.id"
          class="thumb"
          :class="{ on: currentImage?.id === w.img.id, stored: w.img.selected === false }"
          @click="selectImage(w.img)"
        >
          <img :src="api.rawImageUrl(id, w.img.id)" :alt="w.img.name" loading="lazy" />
          <span class="thumb-idx mono">{{ w.idx + 1 }}</span>
          <span class="sel-dot" :class="{ on: w.img.selected !== false }"
                @click="toggleSelected(w.img, $event)"
                :title="w.img.selected === false ? 'Stored (not annotated) — click to select' : 'Selected for annotation'"></span>
        </button>
        <p v-if="!images.length" class="muted empty">Upload microscopy images to begin.</p>
      </div>
    </div>

    <!-- center: canvas -->
    <div class="stage-col">
      <AnnotationCanvas
        v-if="currentImage"
        ref="canvas"
        v-model="annotation"
        :image-url="api.rawImageUrl(id, currentImage.id)"
        :mask-url="maskUrl"
        :mask-src="rawMaskUrl"
        :show-mask="showMask"
        :mask-opacity="maskOpacity"
        :mask-editing="maskEditing"
        :classes="classes"
        :tool="tool"
        :active-label="activeLabel"
        :brush="brush"
      />
      <div v-else class="placeholder viewport">
        <p class="muted">Select or upload an image to annotate.</p>
      </div>
    </div>

    <!-- right: tools -->
    <div class="tools panel">
      <div class="tool-block">
        <span class="eyebrow">Tool</span>
        <div class="seg">
          <button class="seg-btn" :class="{ on: tool === 'scribble' }" @click="tool = 'scribble'" :disabled="isDetection">✎ Scribble</button>
          <button class="seg-btn" :class="{ on: tool === 'box' }" @click="tool = 'box'">▭ Box</button>
          <button class="seg-btn" :class="{ on: tool === 'erase' }" @click="tool = 'erase'">⌫ Erase</button>
          <button class="seg-btn" :class="{ on: tool === 'pan' }" @click="tool = 'pan'">✋ Pan</button>
          <button class="seg-btn wide" :class="{ on: tool === 'maskedit' }" @click="tool = 'maskedit'">✐ Edit mask (manual)</button>
        </div>
      </div>

      <div class="tool-block">
        <div class="row">
          <span class="eyebrow">Class</span>
          <span class="spacer"></span>
          <button class="btn btn-ghost btn-sm" @click="addClass">＋ Add</button>
        </div>
        <div class="class-list">
          <div
            v-for="c in classes"
            :key="c.id"
            class="class-pick"
            :class="{ on: activeLabel === c.id }"
          >
            <span class="sw" :style="{ background: c.color }" @click="activeLabel = c.id"></span>
            <input class="cl-name" :value="c.name" @click="activeLabel = c.id"
                   @change="renameClass(c, $event.target.value)" />
            <span class="mono faint">{{ c.id }}</span>
            <button class="cl-del" @click="removeClass(c)" title="Delete class">✕</button>
          </div>
        </div>
      </div>

      <div class="tool-block" v-if="tool === 'scribble' || tool === 'erase' || tool === 'maskedit'">
        <span class="eyebrow">Brush · {{ brush }}px</span>
        <input type="range" min="2" max="40" v-model.number="brush" class="range" />
      </div>

      <div class="tool-block">
        <label class="check">
          <input type="checkbox" v-model="showMask" />
          <span>Overlay prediction</span>
        </label>
        <span class="eyebrow">Overlay opacity · {{ Math.round(maskOpacity * 100) }}%</span>
        <input type="range" min="0" max="1" step="0.05" v-model.number="maskOpacity" class="range" />
      </div>

      <div class="tool-block" v-if="tool === 'maskedit'">
        <button class="btn btn-primary full" :disabled="savingMask" @click="saveMask">
          {{ savingMask ? 'Saving…' : 'Save edited mask' }}
        </button>
        <p class="hint faint mono">Paint label corrections directly onto the mask, then save. Loads the current prediction as a starting point.</p>
      </div>

      <div class="spacer"></div>

      <p v-if="dispatchError" class="err mono">{{ dispatchError }}</p>

      <div class="actions">
        <button class="btn" :disabled="saving || !currentImage" @click="saveCurrent">
          {{ saving ? 'Saving…' : 'Save annotation' }}
        </button>
        <button class="btn btn-primary" :disabled="!currentImage" @click="runSegment">
          Run segmentation
        </button>
        <button class="btn" :disabled="!currentImage" @click="applyToRest">
          Apply to rest & export
        </button>
        <a v-if="exportHref" class="btn btn-sm full" :href="exportHref" download>⬇ Download results (.zip)</a>
        <p class="hint faint mono">
          Scribble foreground & background on the selected images, then run.
          LightGBM labels all images; "Apply to rest" predicts the stored
          (unselected) images and exports them.
        </p>
      </div>

      <div class="export">
        <span class="eyebrow">Export</span>
        <button class="btn btn-sm full" :disabled="!currentImage || exporting" @click="exportMask(false)">
          ⬇ Label mask (PNG)
        </button>
        <button class="btn btn-sm full" :disabled="!currentImage || exporting" @click="exportMask(true)">
          ⬇ Overlay (PNG)
        </button>
        <button class="btn btn-sm full" :disabled="!currentImage" @click="exportAnnotation">
          ⬇ Annotation (JSON)
        </button>
        <p class="hint faint mono">
          Label mask = raw class-id image for downstream tools. JSON keeps your
          boxes, scribbles & class palette.
        </p>
      </div>
    </div>

    <!-- look-and-select gallery: choose which of the project's images to annotate -->
    <transition name="fade">
      <div v-if="pickerOpen" class="gal-backdrop" @click.self="pickerOpen = false">
        <div class="gal">
          <header class="gal-head">
            <div>
              <strong>Select images to annotate</strong>
              <span class="faint mono small"> · {{ selectedCount }} / {{ images.length }} selected</span>
            </div>
            <span class="spacer"></span>
            <div class="gal-tools">
              <button class="btn btn-sm" @click="selectAllImages">All</button>
              <button class="btn btn-sm" @click="clearSelection">None</button>
              <span class="evn">
                every
                <input class="field mono nth" type="number" min="1" v-model.number="everyN" />
                <button class="btn btn-sm" @click="selectEveryNth">Apply</button>
              </span>
              <button class="btn btn-primary btn-sm" @click="pickerOpen = false">Done</button>
            </div>
          </header>
          <p class="faint mono small gal-hint">Click an image to toggle whether it's annotated. Unselected images are stored and can be auto-labelled later via "Apply to rest".</p>
          <div class="gal-grid">
            <button
              v-for="(img, i) in images"
              :key="img.id"
              class="gal-cell"
              :class="{ sel: img.selected !== false }"
              @click="pickInGallery(img, $event)"
            >
              <img :src="api.rawImageUrl(id, img.id)" :alt="img.name" loading="lazy" />
              <span class="gal-idx mono">{{ i + 1 }}</span>
              <span class="gal-check" v-if="img.selected !== false">✓</span>
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.annotate { display: grid; grid-template-columns: 220px 1fr 260px; gap: 16px; height: calc(100vh - 56px - 48px); }

.strip { display: flex; flex-direction: column; overflow: hidden; }
.strip-head { display: flex; align-items: center; gap: 8px; padding: 14px; border-bottom: 1px solid var(--line); }
.nav { padding: 12px 14px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 8px; }
.nav-row { display: flex; align-items: center; gap: 8px; }
.nav-slider { width: 100%; accent-color: var(--cyan); }
.counter { font-size: 12px; color: var(--ink-soft); min-width: 64px; text-align: center; }
.selonly { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--ink-soft); cursor: pointer; }
.cur-name { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--ink-soft); }
.cur-name .ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.thumbs { flex: 1; overflow: auto; padding: 10px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; align-content: start; }
.thumb {
  position: relative; border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
  background: var(--bg-deep); cursor: pointer; padding: 0; aspect-ratio: 4 / 3;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0.85; }
.thumb.on { border-color: var(--cyan); box-shadow: var(--glow-cyan); }
.thumb.on img { opacity: 1; }
.thumb-idx {
  position: absolute; bottom: 0; left: 0; padding: 1px 5px;
  font-size: 10px; background: rgba(8,10,14,0.8); color: var(--ink-soft); border-top-right-radius: 6px;
}
.sel-dot.inline { position: static; }
.empty { padding: 20px 8px; font-size: 13px; text-align: center; grid-column: 1 / -1; }
.sel-count { font-size: 11px; }

.gal-backdrop { position: fixed; inset: 0; background: rgba(4,6,10,0.72); backdrop-filter: blur(3px); z-index: 50; display: flex; align-items: center; justify-content: center; padding: 32px; }
.gal { width: min(1100px, 94vw); max-height: 88vh; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; overflow: hidden; box-shadow: 0 24px 80px rgba(0,0,0,0.5); }
.gal-head { display: flex; align-items: center; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--line); }
.gal-tools { display: flex; align-items: center; gap: 8px; }
.evn { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-soft); }
.nth { width: 56px; }
.gal-hint { padding: 8px 18px 0; }
.gal-grid { padding: 16px 18px; overflow: auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 10px; }
.gal-cell { position: relative; aspect-ratio: 4/3; border: 2px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--bg-deep); cursor: pointer; padding: 0; opacity: 0.55; transition: opacity .12s, border-color .12s; }
.gal-cell img { width: 100%; height: 100%; object-fit: cover; display: block; }
.gal-cell.sel { opacity: 1; border-color: var(--cyan); box-shadow: var(--glow-cyan); }
.gal-idx { position: absolute; bottom: 0; left: 0; padding: 1px 6px; font-size: 10px; background: rgba(8,10,14,0.82); color: var(--ink-soft); border-top-right-radius: 6px; }
.gal-check { position: absolute; top: 4px; right: 5px; width: 18px; height: 18px; display: grid; place-items: center; font-size: 12px; border-radius: 50%; background: var(--cyan); color: #04221e; font-weight: 700; }
.fade-enter-active, .fade-leave-active { transition: opacity .15s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.stage-col { min-width: 0; }
.placeholder { display: flex; align-items: center; justify-content: center; height: 100%; }

.tools { display: flex; flex-direction: column; gap: 18px; padding: 16px; overflow: auto; }
.tool-block { display: flex; flex-direction: column; gap: 8px; }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.seg-btn {
  padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-2);
  color: var(--ink-soft); cursor: pointer; font-size: 13px; transition: all 0.12s;
}
.seg-btn:hover { color: var(--ink); border-color: var(--line); }
.seg-btn.on { border-color: var(--cyan); color: var(--ink); background: var(--surface-3); }
.seg-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.seg-btn.wide { grid-column: 1 / -1; }
.cl-name { flex: 1; background: none; border: none; color: inherit; font-size: 13px; min-width: 0; padding: 0; }
.cl-name:focus { outline: none; border-bottom: 1px solid var(--cyan); }
.cl-del { background: none; border: none; color: var(--ink-faint); cursor: pointer; font-size: 12px; padding: 0 2px; }
.cl-del:hover { color: var(--red); }
.sel-dot { position: absolute; top: 6px; right: 6px; width: 13px; height: 13px; border-radius: 50%; border: 2px solid var(--ink-faint); background: transparent; cursor: pointer; }
.sel-dot.on { background: var(--cyan); border-color: var(--cyan); box-shadow: var(--glow-cyan); }
.thumb.stored { opacity: 0.55; }
.thumb.stored img { filter: grayscale(0.5); }
a.btn { text-decoration: none; }

.class-list { display: flex; flex-direction: column; gap: 5px; }
.class-pick {
  display: flex; align-items: center; gap: 8px; padding: 7px 9px; border-radius: 6px;
  border: 1px solid transparent; background: var(--surface-2); color: var(--ink-soft);
  cursor: pointer; font-size: 13px; text-align: left;
}
.class-pick .spacer, .class-pick span:nth-child(3) { margin-left: auto; }
.class-pick:hover { color: var(--ink); }
.class-pick.on { border-color: var(--cyan); color: var(--ink); }
.sw { width: 14px; height: 14px; border-radius: 4px; flex-shrink: 0; }

.range { width: 100%; accent-color: var(--cyan); }
.check { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-soft); }

.actions { display: flex; flex-direction: column; gap: 8px; }
.actions .btn { width: 100%; justify-content: center; }
.export {
  display: flex; flex-direction: column; gap: 8px;
  margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--line-soft);
}
.export .full { width: 100%; justify-content: center; }
.hint { font-size: 10px; line-height: 1.5; }
.err { color: var(--red); font-size: 12px; }

@media (max-width: 980px) {
  .annotate { grid-template-columns: 1fr; height: auto; }
  .stage-col { min-height: 60vh; }
}
</style>
