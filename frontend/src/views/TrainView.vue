<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useJobs } from '@/composables/useJobs'
import { api } from '@/api/client'

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const tasks = useTaskStore()
const { dispatch } = useJobs()

const err = ref(null)
const train = reactive({
  task_type: 'segmentation', model_size: 'medium',
  epochs: 50, batch_size: 8, lr: 0.001, input_size: 512,
})
const infer = reactive({ kind: 'interactive', model: 'interactive.joblib', conf: 0.25, tta: true })

const SIZES = [
  { v: 'light', label: 'Light', note: 'EfficientNet-B0 · fastest' },
  { v: 'medium', label: 'Medium', note: 'EfficientNet-B3 · balanced' },
  { v: 'heavy', label: 'Heavy', note: 'EfficientNet-B5 · most accurate' },
]

const testImages = ref([])
const testInput = ref(null)
const uploading = ref(false)

onMounted(async () => {
  if (store.current?.id !== props.id) await store.open(props.id)
  train.task_type = store.current?.task_type || 'segmentation'
  await refreshTest()
})

async function refreshTest() {
  try { testImages.value = await api.listTestImages(props.id) } catch { testImages.value = [] }
}
function pickTest() { testInput.value.click() }
async function onTestFiles(e) {
  if (e.target.files?.length) {
    uploading.value = true
    try { await api.uploadTestImages(props.id, e.target.files); await refreshTest() }
    finally { uploading.value = false }
  }
  e.target.value = ''
}

const trainTask = computed(() => tasks.list.find((t) => t.type === 'train'))
const trainPct = computed(() => Math.round((trainTask.value?.progress || 0) * 100))

// Latest inference task + its export download link (once finished).
const inferTask = computed(() => tasks.list.find((t) => t.type === 'inference'))
const inferPct = computed(() => Math.round((inferTask.value?.progress || 0) * 100))
const exportHref = computed(() => {
  const name = inferTask.value?.result?.export
  return name ? api.exportUrl(props.id, name) : null
})

async function startTrain() {
  err.value = null
  try { await dispatch('train', props.id, { ...train }) }
  catch (e) { err.value = e.message }
}
async function startInfer() {
  err.value = null
  if (!testImages.value.length) { err.value = 'Upload test images first.'; return }
  try { await dispatch('inference', props.id, { ...infer, source: 'test', export: true }) }
  catch (e) { err.value = e.message }
}
</script>

<template>
  <div class="train">
    <div class="panel ctrl">
      <div class="eyebrow">Train a model</div>
      <p class="muted small">Training runs out-of-process on the worker so the UI stays responsive. Progress and the best validation Dice stream to the task log.</p>

      <label class="lbl">Task</label>
      <select class="field" v-model="train.task_type">
        <option value="segmentation">Segmentation (U-Net + EfficientNet)</option>
        <option value="detection">Detection (YOLOv8)</option>
      </select>

      <label class="lbl">Model size</label>
      <div class="sizes">
        <button
          v-for="s in SIZES" :key="s.v"
          class="size" :class="{ on: train.model_size === s.v }"
          @click="train.model_size = s.v"
        >
          <strong>{{ s.label }}</strong>
          <span class="faint mono">{{ s.note }}</span>
        </button>
      </div>

      <div class="grid3">
        <div><label class="lbl">Epochs</label><input class="field mono" type="number" v-model.number="train.epochs" /></div>
        <div><label class="lbl">Batch</label><input class="field mono" type="number" v-model.number="train.batch_size" /></div>
        <div><label class="lbl">Input</label><input class="field mono" type="number" step="32" v-model.number="train.input_size" /></div>
      </div>
      <label class="lbl">Learning rate</label>
      <input class="field mono" type="number" step="0.0001" v-model.number="train.lr" />

      <button class="btn btn-primary full" @click="startTrain">Start training</button>

      <div v-if="trainTask" class="progress">
        <div class="row"><span class="mono small">{{ trainTask.message || trainTask.state }}</span><span class="spacer"></span><span class="mono small faint">{{ trainPct }}%</span></div>
        <div class="bar"><div class="bar-fill" :class="trainTask.state" :style="{ width: trainPct + '%' }"></div></div>
      </div>
      <p v-if="err" class="err mono">{{ err }}</p>
    </div>

    <div class="panel ctrl">
      <div class="eyebrow">Inference on test data</div>
      <p class="muted small">Upload a separate set of test images, predict with a trained model, and download the results. Masks are written back at the original image resolution.</p>

      <div class="testhead">
        <span class="lbl" style="margin:0">Test images</span>
        <span class="badge mono">{{ testImages.length }}</span>
        <span class="spacer"></span>
        <button class="btn btn-sm" :disabled="uploading" @click="pickTest">{{ uploading ? 'Uploading…' : '＋ Upload' }}</button>
        <input ref="testInput" type="file" accept="image/*" multiple hidden @change="onTestFiles" />
      </div>
      <div v-if="testImages.length" class="test-strip">
        <div v-for="t in testImages" :key="t.id" class="test-thumb">
          <img :src="api.testRawUrl(id, t.id)" :alt="t.filename" loading="lazy" />
        </div>
      </div>
      <p v-else class="muted small">No test images yet — upload images you want to predict on.</p>

      <label class="lbl">Model kind</label>
      <select class="field" v-model="infer.kind">
        <option value="interactive">Interactive (LightGBM) — uses your scribble model</option>
        <option value="segmentation">Segmentation (U-Net checkpoint)</option>
        <option value="detection">Detection (YOLO checkpoint)</option>
      </select>

      <label class="lbl">Model file</label>
      <input class="field mono" v-model="infer.model" placeholder="interactive.joblib" />

      <div class="two" v-if="infer.kind !== 'interactive'">
        <div><label class="lbl">Confidence</label><input class="field mono" type="number" step="0.05" v-model.number="infer.conf" /></div>
        <label class="check"><input type="checkbox" v-model="infer.tta" /> <span>Flip TTA</span></label>
      </div>

      <button class="btn btn-primary full" :disabled="!testImages.length" @click="startInfer">
        Run inference & export
      </button>

      <div v-if="inferTask" class="progress">
        <div class="row"><span class="mono small">{{ inferTask.message || inferTask.state }}</span><span class="spacer"></span><span class="mono small faint">{{ inferPct }}%</span></div>
        <div class="bar"><div class="bar-fill" :class="inferTask.state" :style="{ width: inferPct + '%' }"></div></div>
      </div>

      <a v-if="exportHref" class="btn btn-primary full" :href="exportHref" download>
        ⬇ Download results (.zip)
      </a>

      <div class="note mono faint">
        <span class="dot done"></span> Interactive inference runs on CPU using the
        model from "Run segmentation". Segmentation/detection checkpoints need the
        ML worker (torch + ultralytics + smp).
      </div>
    </div>
  </div>
</template>

<style scoped>
.train { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; max-width: 1080px; margin: 0 auto; align-items: start; }
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
.bar-fill.done { background: var(--green); }
.bar-fill.error { background: var(--red); }

.note { display: flex; align-items: center; gap: 8px; font-size: 11px; line-height: 1.5; padding: 10px; border: 1px dashed var(--line); border-radius: 8px; }
.testhead { display: flex; align-items: center; gap: 8px; }
.test-strip { display: flex; gap: 6px; flex-wrap: wrap; }
.test-thumb { width: 56px; height: 44px; border-radius: 6px; overflow: hidden; border: 1px solid var(--line); background: var(--bg-deep); }
.test-thumb img { width: 100%; height: 100%; object-fit: cover; }
a.btn { text-decoration: none; }
.err { color: var(--red); font-size: 12px; }

@media (max-width: 860px) { .train { grid-template-columns: 1fr; } }
</style>
