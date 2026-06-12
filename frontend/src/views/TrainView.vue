<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useJobs } from '@/composables/useJobs'
import { api } from '@/api/client'

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const tasks = useTaskStore()
const { dispatch } = useJobs()

const subtab = ref('train')
const err = ref(null)
const train = reactive({
  task_type: 'segmentation', model_size: 'medium',
  epochs: 50, batch_size: 8, lr: 0.001, input_size: 512, resume_model: null,
  // dataset customization
  subset: 'all',            // 'all' | 'selected' | 'pick'
  include_extra: true,
  val_fraction: 0.15, seed: 42,
  augment: { hflip: true, vflip: false, rot90: false, brightness: false },
})
const pickedIds = ref(new Set())          // hand-picked training images
const trainPairs = ref([])                // external uploaded pairs
const pairImgInput = ref(null)
const pairMaskInput = ref(null)
const pairBusy = ref(false)
const infer = reactive({ kind: 'interactive', model: 'interactive.joblib', source: 'test', conf: 0.25, tta: true })

const SIZES = [
  { v: 'light', label: 'Light', note: 'EfficientNet-B0 · fastest' },
  { v: 'medium', label: 'Medium', note: 'EfficientNet-B3 · balanced' },
  { v: 'heavy', label: 'Heavy', note: 'EfficientNet-B5 · most accurate' },
]

const models = ref([])
const testImages = ref([])
const testInput = ref(null)
const uploading = ref(false)
const reviewOpacity = ref(0.55)

onMounted(async () => {
  if (store.current?.id !== props.id) await store.open(props.id)
  train.task_type = store.current?.task_type || 'segmentation'
  await Promise.all([refreshTest(), refreshModels(), refreshPairs()])
})

const images = computed(() => store.images)
// images that actually have a saved mask (only these can train)
const maskedImages = computed(() => images.value.filter((i) => i.has_mask || i.mask))
async function refreshPairs() {
  try { trainPairs.value = await api.listTrainPairs(props.id) } catch { trainPairs.value = [] }
}
function togglePick(id) {
  const s = new Set(pickedIds.value)
  s.has(id) ? s.delete(id) : s.add(id)
  pickedIds.value = s
}
function pickImages() { pairImgInput.value.click() }
function pickMasks() { pairMaskInput.value.click() }
const pendingImgs = ref([])
function onPairImgs(e) { pendingImgs.value = Array.from(e.target.files || []); e.target.value = '' }
async function onPairMasks(e) {
  const masks = Array.from(e.target.files || [])
  if (!pendingImgs.value.length) { err.value = 'Choose the images first, then their masks.'; return }
  if (masks.length !== pendingImgs.value.length) {
    err.value = `Picked ${pendingImgs.value.length} images but ${masks.length} masks — counts must match (same order).`
    e.target.value = ''; return
  }
  pairBusy.value = true
  try { await api.uploadTrainPairs(props.id, pendingImgs.value, masks); pendingImgs.value = []; await refreshPairs() }
  catch (ex) { err.value = ex.message }
  finally { pairBusy.value = false; e.target.value = '' }
}
async function removePair(id) {
  try { await api.deleteTrainPair(props.id, id); await refreshPairs() } catch { /* ignore */ }
}

async function refreshModels() {
  try { models.value = await api.listModels(props.id) } catch { models.value = [] }
}
async function refreshTest() {
  try { testImages.value = await api.listTestImages(props.id) } catch { testImages.value = [] }
}
// Re-list models whenever a training run finishes.
watch(() => tasks.list.filter((t) => t.type === 'train' && t.state === 'done').length, refreshModels)

function pickTest() { testInput.value.click() }
async function onTestFiles(e) {
  if (e.target.files?.length) {
    uploading.value = true
    try { await api.uploadTestImages(props.id, e.target.files); await refreshTest() }
    finally { uploading.value = false }
  }
  e.target.value = ''
}

function fmtSize(b) { return b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : (b / 1e3).toFixed(0) + ' KB' }
function fmtAge(t) {
  const s = Date.now() / 1000 - t
  if (s < 90) return 'just now'
  if (s < 5400) return Math.round(s / 60) + ' min ago'
  if (s < 129600) return Math.round(s / 3600) + ' h ago'
  return Math.round(s / 86400) + ' d ago'
}
function continueTraining(m) {
  subtab.value = 'train'
  train.task_type = 'segmentation'
  train.resume_model = m.name
}
function useForInference(m) {
  subtab.value = 'inference'
  infer.kind = m.kind
  infer.model = m.name
}

const trainTask = computed(() => tasks.list.find((t) => t.type === 'train'))
const trainPct = computed(() => Math.round((trainTask.value?.progress || 0) * 100))

const inferTask = computed(() => tasks.list.find((t) => t.type === 'inference'))
const inferPct = computed(() => Math.round((inferTask.value?.progress || 0) * 100))
const inferResult = computed(() =>
  tasks.list.find((t) => t.type === 'inference' && t.state === 'done')?.result)
const exportHref = computed(() => {
  const name = inferResult.value?.export
  return name ? api.exportUrl(props.id, name) : null
})

// Pick up to 3 evenly-spaced result slices (along Z) to review input vs output.
const reviewSlices = computed(() => {
  const rs = inferResult.value?.results || []
  if (!rs.length) return []
  const n = Math.min(3, rs.length)
  const out = []
  for (let k = 0; k < n; k++) {
    const idx = Math.round((k * (rs.length - 1)) / Math.max(1, n - 1))
    out.push(rs[idx])
  }
  return out
})

async function startTrain() {
  err.value = null
  const payload = { ...train }
  // resolve which images become the training subset
  if (train.subset === 'all') payload.image_ids = null
  else if (train.subset === 'selected') payload.image_ids = images.value.filter((i) => i.selected !== false).map((i) => i.id)
  else payload.image_ids = Array.from(pickedIds.value)
  delete payload.subset
  if (train.task_type === 'segmentation' && train.subset !== 'all' && !(payload.image_ids || []).length && !train.include_extra) {
    err.value = 'No training images chosen. Pick some images or enable external pairs.'; return
  }
  try { await dispatch('train', props.id, payload) }
  catch (e) { err.value = e.message }
}
function cancelResume() { train.resume_model = null }

async function startInfer() {
  err.value = null
  if (infer.source === 'test' && !testImages.value.length) { err.value = 'Upload test images first.'; return }
  try { await dispatch('inference', props.id, { ...infer, export: true }) }
  catch (e) { err.value = e.message }
}
</script>

<template>
  <div class="trainpage">
    <div class="subtabs">
      <button class="subtab" :class="{ on: subtab === 'train' }" @click="subtab = 'train'">◇ Train</button>
      <button class="subtab" :class="{ on: subtab === 'inference' }" @click="subtab = 'inference'">→ Inference</button>
    </div>

    <p v-if="err" class="err mono">{{ err }}</p>

    <!-- ===================== TRAIN ===================== -->
    <section v-show="subtab === 'train'" class="train">
      <div class="panel ctrl">
        <div class="eyebrow">Train a model</div>
        <p class="muted small">Optional deep-learning step. If the interactive (scribble) model is good enough you can skip straight to inference. Training runs on the worker; the best validation Dice is saved as a checkpoint.</p>

        <div v-if="train.resume_model" class="resume-tag mono">
          <span class="dot done"></span> Continuing from {{ train.resume_model }}
          <button class="x" @click="cancelResume">✕</button>
        </div>

        <label class="lbl">Task</label>
        <select class="field" v-model="train.task_type">
          <option value="segmentation">Segmentation (U-Net + EfficientNet)</option>
          <option value="detection">Detection (YOLO)</option>
        </select>

        <label class="lbl">Model size</label>
        <div class="sizes">
          <button v-for="s in SIZES" :key="s.v" class="size" :class="{ on: train.model_size === s.v }" @click="train.model_size = s.v">
            <strong>{{ s.label }}</strong><span class="faint">{{ s.note }}</span>
          </button>
        </div>

        <div class="grid3">
          <div><label class="lbl">Epochs</label><input class="field mono" type="number" v-model.number="train.epochs" /></div>
          <div><label class="lbl">Batch</label><input class="field mono" type="number" v-model.number="train.batch_size" /></div>
          <div><label class="lbl">Input</label><input class="field mono" type="number" step="32" v-model.number="train.input_size" /></div>
        </div>
        <label class="lbl">Learning rate</label>
        <input class="field mono" type="number" step="0.0001" v-model.number="train.lr" />

        <!-- ===== Dataset customization (segmentation only) ===== -->
        <div v-if="train.task_type === 'segmentation'" class="dataset">
          <div class="eyebrow ds-head">Training dataset</div>

          <label class="lbl">Which images</label>
          <div class="seg3">
            <button class="seg3-btn" :class="{ on: train.subset === 'all' }" @click="train.subset = 'all'">All masked</button>
            <button class="seg3-btn" :class="{ on: train.subset === 'selected' }" @click="train.subset = 'selected'">Selected</button>
            <button class="seg3-btn" :class="{ on: train.subset === 'pick' }" @click="train.subset = 'pick'">Pick…</button>
          </div>

          <div v-if="train.subset === 'pick'" class="picklist">
            <p v-if="!maskedImages.length" class="faint mono small">No masked images yet — run segmentation first.</p>
            <label v-for="i in maskedImages" :key="i.id" class="pick-row">
              <input type="checkbox" :checked="pickedIds.has(i.id)" @change="togglePick(i.id)" />
              <span class="mono small">{{ i.name }}</span>
            </label>
            <p class="faint mono small">{{ pickedIds.size }} picked</p>
          </div>

          <label class="check"><input type="checkbox" v-model="train.include_extra" /> <span>Include external uploaded pairs ({{ trainPairs.length }})</span></label>

          <!-- external pairs uploader -->
          <div class="pairs">
            <div class="pairs-head">
              <span class="lbl" style="margin:0">External image+mask pairs</span>
              <span class="pairs-actions">
                <button class="btn btn-sm" :disabled="pairBusy" @click="pickImages">{{ pendingImgs.length ? `${pendingImgs.length} imgs ✓` : '1 · Images' }}</button>
                <button class="btn btn-sm" :disabled="pairBusy || !pendingImgs.length" @click="pickMasks">{{ pairBusy ? 'Uploading…' : '2 · Masks' }}</button>
              </span>
            </div>
            <input ref="pairImgInput" type="file" accept="image/*" multiple class="hidden" @change="onPairImgs" />
            <input ref="pairMaskInput" type="file" accept="image/*" multiple class="hidden" @change="onPairMasks" />
            <p class="faint mono small">Pick images, then their label-masks in the same order. Masks must be class-id PNGs.</p>
            <div v-if="trainPairs.length" class="pair-rows">
              <div v-for="p in trainPairs" :key="p.id" class="pair-row">
                <span class="mono small">{{ p.filename }}</span>
                <button class="x" @click="removePair(p.id)">✕</button>
              </div>
            </div>
          </div>

          <div class="two">
            <div><label class="lbl">Val fraction</label><input class="field mono" type="number" step="0.05" min="0" max="0.5" v-model.number="train.val_fraction" /></div>
            <div><label class="lbl">Seed</label><input class="field mono" type="number" v-model.number="train.seed" /></div>
          </div>

          <label class="lbl">Augmentation</label>
          <div class="augs">
            <label class="aug"><input type="checkbox" v-model="train.augment.hflip" /> <span>H-flip</span></label>
            <label class="aug"><input type="checkbox" v-model="train.augment.vflip" /> <span>V-flip</span></label>
            <label class="aug"><input type="checkbox" v-model="train.augment.rot90" /> <span>Rot 90°</span></label>
            <label class="aug"><input type="checkbox" v-model="train.augment.brightness" /> <span>Brightness</span></label>
          </div>
        </div>

        <button class="btn btn-primary full" @click="startTrain">{{ train.resume_model ? 'Continue training' : 'Start training' }}</button>

        <div v-if="trainTask" class="progress">
          <div class="row"><span class="mono small">{{ trainTask.message || trainTask.state }}</span><span class="spacer"></span><span class="mono small faint">{{ trainPct }}%</span></div>
          <div class="bar"><div class="bar-fill" :class="trainTask.state" :style="{ width: trainPct + '%' }"></div></div>
          <p v-if="trainTask.state === 'done' && trainTask.result" class="faint mono small">
            {{ trainTask.result.n_train }} train · {{ trainTask.result.n_val }} val
            <template v-if="trainTask.result.n_extra"> · {{ trainTask.result.n_extra }} external</template>
            · best dice {{ (trainTask.result.best_dice ?? 0).toFixed(3) }}
          </p>
        </div>
      </div>

      <!-- model registry -->
      <div class="panel ctrl">
        <div class="row">
          <div class="eyebrow">Trained models</div>
          <span class="spacer"></span>
          <button class="btn btn-sm" @click="refreshModels">↻</button>
        </div>
        <p class="muted small">Every saved model in this project. Continue training to refine one, or send it to inference.</p>
        <div v-if="models.length" class="model-list">
          <div v-for="m in models" :key="m.name" class="model-card">
            <div class="m-main">
              <span class="m-kind" :class="m.kind">{{ m.kind }}</span>
              <span class="m-name mono">{{ m.name }}</span>
            </div>
            <div class="m-meta mono faint">{{ fmtSize(m.size) }} · {{ fmtAge(m.modified) }}</div>
            <div class="m-actions">
              <button v-if="m.kind === 'segmentation'" class="btn btn-sm" @click="continueTraining(m)">Continue</button>
              <button class="btn btn-sm" @click="useForInference(m)">Use for inference →</button>
            </div>
          </div>
        </div>
        <p v-else class="muted empty">No trained models yet. The "Apply to all" interactive model also appears here once you've run it in Annotate.</p>
      </div>
    </section>

    <!-- ===================== INFERENCE ===================== -->
    <section v-show="subtab === 'inference'" class="train">
      <div class="panel ctrl">
        <div class="eyebrow">Run inference</div>
        <p class="muted small">Predict with a trained model on uploaded test images or on the project's own images ("Apply to rest"). Masks are written at original resolution and exported.</p>

        <label class="lbl">Predict on</label>
        <select class="field" v-model="infer.source">
          <option value="test">Uploaded test images</option>
          <option value="images">Project images (apply to rest)</option>
        </select>

        <template v-if="infer.source === 'test'">
          <div class="testhead">
            <span class="lbl" style="margin:0">Test images</span>
            <span class="badge mono">{{ testImages.length }}</span>
            <span class="spacer"></span>
            <button class="btn btn-sm" :disabled="uploading" @click="pickTest">{{ uploading ? 'Uploading…' : '＋ Upload' }}</button>
            <input ref="testInput" type="file" accept="image/*,.tif,.tiff" multiple hidden @change="onTestFiles" />
          </div>
          <div v-if="testImages.length" class="test-strip">
            <div v-for="t in testImages" :key="t.id" class="test-thumb"><img :src="api.testRawUrl(id, t.id)" :alt="t.filename" loading="lazy" /></div>
          </div>
          <p v-else class="muted small">No test images yet — upload images to predict on.</p>
        </template>

        <label class="lbl">Model kind</label>
        <select class="field" v-model="infer.kind">
          <option value="interactive">Interactive (LightGBM)</option>
          <option value="segmentation">Segmentation (U-Net checkpoint)</option>
          <option value="detection">Detection (YOLO checkpoint)</option>
        </select>
        <label class="lbl">Model file</label>
        <input class="field mono" v-model="infer.model" placeholder="interactive.joblib" />

        <div class="two" v-if="infer.kind !== 'interactive'">
          <div><label class="lbl">Confidence</label><input class="field mono" type="number" step="0.05" v-model.number="infer.conf" /></div>
          <label class="check"><input type="checkbox" v-model="infer.tta" /> <span>Flip TTA</span></label>
        </div>

        <button class="btn btn-primary full" @click="startInfer">Run inference &amp; export</button>

        <div v-if="inferTask" class="progress">
          <div class="row"><span class="mono small">{{ inferTask.message || inferTask.state }}</span><span class="spacer"></span><span class="mono small faint">{{ inferPct }}%</span></div>
          <div class="bar"><div class="bar-fill" :class="inferTask.state" :style="{ width: inferPct + '%' }"></div></div>
        </div>
        <a v-if="exportHref" class="btn btn-primary full" :href="exportHref" download>⬇ Download results (.zip)</a>
      </div>

      <!-- review -->
      <div class="panel ctrl">
        <div class="row">
          <div class="eyebrow">Review predictions</div>
          <span class="spacer"></span>
          <span v-if="inferResult" class="badge mono">{{ inferResult.n_images }} images</span>
        </div>
        <p class="muted small">Three slices sampled across the test set (along Z) so you can eyeball the model's real performance. Adjust overlay opacity.</p>

        <template v-if="reviewSlices.length && infer.source === 'test'">
          <div class="opacity-row">
            <span class="lbl" style="margin:0">Overlay opacity · {{ Math.round(reviewOpacity * 100) }}%</span>
            <input type="range" min="0" max="1" step="0.05" v-model.number="reviewOpacity" class="range" />
          </div>
          <div class="review-grid">
            <div v-for="r in reviewSlices" :key="r.image_id" class="review-cell">
              <div class="rc-img">
                <img :src="api.testRawUrl(id, r.image_id)" alt="input" />
                <img class="rc-overlay" :src="api.testResultUrl(id, r.image_id)" alt="mask" :style="{ opacity: reviewOpacity }" />
              </div>
              <span class="rc-name mono faint">{{ r.filename }} · {{ r.width }}×{{ r.height }}</span>
            </div>
          </div>
        </template>
        <p v-else class="muted empty">Run inference on test images to review results here.</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dataset { display: flex; flex-direction: column; gap: 10px; padding: 12px; margin: 4px 0; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-2); }
.ds-head { margin-bottom: 2px; }
.seg3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 6px; }
.seg3-btn { padding: 7px 8px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink-soft); cursor: pointer; font-size: 12px; }
.seg3-btn.on { border-color: var(--cyan); color: var(--ink); background: var(--surface-3); }
.picklist { max-height: 160px; overflow: auto; display: flex; flex-direction: column; gap: 3px; padding: 8px; border: 1px solid var(--line-soft); border-radius: 8px; }
.pick-row { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.pairs { display: flex; flex-direction: column; gap: 6px; }
.pairs-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.pairs-actions { display: flex; gap: 6px; }
.hidden { display: none; }
.pair-rows { display: flex; flex-direction: column; gap: 3px; max-height: 130px; overflow: auto; }
.pair-row { display: flex; align-items: center; justify-content: space-between; padding: 4px 8px; background: var(--surface); border-radius: 6px; }
.pair-row .x { background: none; border: none; color: var(--ink-soft); cursor: pointer; }
.augs { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.aug { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-soft); }
.check { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-soft); }
.trainpage { display: flex; flex-direction: column; gap: 16px; max-width: 1080px; margin: 0 auto; }
.subtabs { display: flex; gap: 6px; }
.subtab { padding: 8px 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink-soft); cursor: pointer; font-size: 14px; }
.subtab.on { border-color: var(--cyan); color: var(--ink); background: var(--surface-2); }
.train { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
.ctrl { padding: 20px; display: flex; flex-direction: column; gap: 12px; }
.small { font-size: 12px; line-height: 1.55; }
.sizes { display: flex; flex-direction: column; gap: 8px; }
.size { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2); color: var(--ink-soft); cursor: pointer; text-align: left; }
.size strong { color: var(--ink); font-weight: 600; }
.size .faint { font-size: 11px; }
.size.on { border-color: var(--cyan); background: var(--surface-3); }
.grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.two { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: end; }
.full { width: 100%; justify-content: center; margin-top: 4px; }
.check { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-soft); padding-bottom: 9px; }

.progress { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.bar { height: 6px; background: var(--bg-deep); border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; background: linear-gradient(90deg, var(--cyan), var(--violet)); border-radius: 4px; transition: width 0.3s var(--ease); }
.bar-fill.done, .bar-fill.success { background: var(--green); }
.bar-fill.error, .bar-fill.failed { background: var(--red); }

.resume-tag { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-soft); padding: 8px 10px; background: var(--surface-2); border-radius: 8px; }
.resume-tag .x { margin-left: auto; background: none; border: none; color: var(--ink-faint); cursor: pointer; }

.model-list { display: flex; flex-direction: column; gap: 8px; }
.model-card { border: 1px solid var(--line); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 8px; background: var(--surface-2); }
.m-main { display: flex; align-items: center; gap: 8px; }
.m-kind { font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; padding: 2px 7px; border-radius: 5px; background: var(--surface-3); color: var(--ink-soft); }
.m-kind.interactive { color: var(--cyan); }
.m-kind.segmentation { color: var(--violet); }
.m-kind.detection { color: var(--amber); }
.m-name { font-size: 12px; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m-meta { font-size: 11px; }
.m-actions { display: flex; gap: 8px; }

.testhead { display: flex; align-items: center; gap: 8px; }
.test-strip { display: flex; gap: 6px; flex-wrap: wrap; }
.test-thumb { width: 52px; height: 40px; border-radius: 6px; overflow: hidden; border: 1px solid var(--line); background: var(--bg-deep); }
.test-thumb img { width: 100%; height: 100%; object-fit: cover; }

.opacity-row { display: flex; flex-direction: column; gap: 6px; }
.review-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.review-cell { display: flex; flex-direction: column; gap: 4px; }
.rc-img { position: relative; aspect-ratio: 1; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--bg-deep); }
.rc-img img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; }
.rc-overlay { mix-blend-mode: screen; }
.rc-name { font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty { padding: 30px 12px; text-align: center; }
a.btn { text-decoration: none; }
.err { color: var(--red); }

@media (max-width: 900px) { .train { grid-template-columns: 1fr; } }
</style>
