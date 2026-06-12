<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useJobs } from '@/composables/useJobs'

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const tasks = useTaskStore()
const { dispatch } = useJobs()

const err = ref(null)
const train = reactive({
  task_type: 'segmentation', model_size: 'medium',
  epochs: 50, batch_size: 8, lr: 0.001, input_size: 512,
})
const infer = reactive({ kind: 'segmentation', model: 'best', conf: 0.25, tta: true })

const SIZES = [
  { v: 'light', label: 'Light', note: 'EfficientNet-B0 · fastest' },
  { v: 'medium', label: 'Medium', note: 'EfficientNet-B3 · balanced' },
  { v: 'heavy', label: 'Heavy', note: 'EfficientNet-B5 · most accurate' },
]

onMounted(async () => {
  if (store.current?.id !== props.id) await store.open(props.id)
  train.task_type = store.current?.task_type || 'segmentation'
  infer.kind = train.task_type
})

const trainTask = computed(() =>
  tasks.list.find((t) => t.type === 'train'))
const trainPct = computed(() => Math.round((trainTask.value?.progress || 0) * 100))

async function startTrain() {
  err.value = null
  try { await dispatch('train', props.id, { ...train }) }
  catch (e) { err.value = e.message }
}
async function startInfer() {
  err.value = null
  try { await dispatch('inference', props.id, { ...infer }) }
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
      <div class="eyebrow">Run inference</div>
      <p class="muted small">Apply a trained checkpoint to the project images. Results are written back as masks you can measure or reconstruct.</p>

      <label class="lbl">Kind</label>
      <select class="field" v-model="infer.kind">
        <option value="segmentation">Segmentation</option>
        <option value="detection">Detection</option>
        <option value="interactive">Interactive (LightGBM)</option>
      </select>

      <label class="lbl">Model / checkpoint</label>
      <input class="field mono" v-model="infer.model" placeholder="best" />

      <div class="two">
        <div><label class="lbl">Confidence</label><input class="field mono" type="number" step="0.05" v-model.number="infer.conf" /></div>
        <label class="check"><input type="checkbox" v-model="infer.tta" /> <span>Flip TTA</span></label>
      </div>

      <button class="btn full" @click="startInfer">Run inference</button>

      <div class="note mono faint">
        <span class="dot done"></span> The worker requires the ML image
        (torch + ultralytics + smp). On the CPU API image these jobs queue but
        need a GPU/ML worker to execute.
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
.err { color: var(--red); font-size: 12px; }

@media (max-width: 860px) { .train { grid-template-columns: 1fr; } }
</style>
