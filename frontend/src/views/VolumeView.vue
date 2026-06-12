<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useJobs } from '@/composables/useJobs'
import VolumeViewer3D from '@/components/VolumeViewer3D.vue'

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const tasks = useTaskStore()
const { dispatch } = useJobs()

const err = ref(null)
const wireframe = ref(false)
const cfg = reactive({ source: 'masks', label: null, threshold: 128, downsample: 2, step_size: 1 })

const classes = computed(() => store.classes)
const latestMesh = computed(() =>
  tasks.list.find((t) => t.type === 'mesh' && t.state === 'done')?.result)
const meshTask = computed(() =>
  tasks.list.find((t) => t.type === 'mesh'))

onMounted(async () => {
  if (store.current?.id !== props.id) await store.open(props.id)
  if (classes.value.length) cfg.label = classes.value[0].id
})

async function build() {
  err.value = null
  try {
    const payload = {
      source: cfg.source,
      downsample: cfg.downsample,
      step_size: cfg.step_size,
      spacing: [1.0, 1.0, 1.0],
    }
    if (cfg.source === 'masks') payload.label = cfg.label
    else payload.threshold = cfg.threshold
    await dispatch('mesh', props.id, payload)
  } catch (e) { err.value = e.message }
}
</script>

<template>
  <div class="volume">
    <div class="panel ctrl">
      <div class="eyebrow">3D reconstruction</div>
      <p class="muted small">Stack the image set as a Z-volume and extract an isosurface with marching cubes. Drag to orbit, scroll to zoom.</p>

      <label class="lbl">Source</label>
      <select class="field" v-model="cfg.source">
        <option value="masks">Segmented masks</option>
        <option value="images">Raw intensity</option>
      </select>

      <template v-if="cfg.source === 'masks'">
        <label class="lbl">Label</label>
        <select class="field" v-model.number="cfg.label">
          <option v-for="c in classes" :key="c.id" :value="c.id">{{ c.name }} ({{ c.id }})</option>
        </select>
      </template>
      <template v-else>
        <label class="lbl">Iso threshold</label>
        <input class="field mono" type="number" v-model.number="cfg.threshold" />
      </template>

      <div class="two">
        <div><label class="lbl">Downsample</label><input class="field mono" type="number" min="1" v-model.number="cfg.downsample" /></div>
        <div><label class="lbl">Step size</label><input class="field mono" type="number" min="1" v-model.number="cfg.step_size" /></div>
      </div>

      <button class="btn btn-primary full" @click="build">Build mesh</button>

      <div v-if="latestMesh" class="meshstats">
        <div class="ms"><span class="eyebrow">Vertices</span><span class="mono">{{ latestMesh.vertex_count.toLocaleString() }}</span></div>
        <div class="ms"><span class="eyebrow">Triangles</span><span class="mono">{{ latestMesh.triangle_count.toLocaleString() }}</span></div>
      </div>

      <label class="check"><input type="checkbox" v-model="wireframe" /> <span>Wireframe</span></label>
      <p v-if="err" class="err mono">{{ err }}</p>
    </div>

    <div class="stage">
      <VolumeViewer3D v-if="latestMesh" :mesh="latestMesh" :wireframe="wireframe" />
      <div v-else class="placeholder viewport">
        <div class="ph-inner">
          <div class="ph-icon">⬡</div>
          <p class="muted">{{ meshTask ? 'Building isosurface…' : 'Build a mesh to view it in 3D.' }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.volume { display: grid; grid-template-columns: 300px 1fr; gap: 16px; height: calc(100vh - 56px - 48px); max-width: 1200px; margin: 0 auto; }
.ctrl { padding: 18px; display: flex; flex-direction: column; gap: 12px; overflow: auto; }
.small { font-size: 12px; line-height: 1.55; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.full { width: 100%; justify-content: center; }
.check { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-soft); }
.meshstats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; padding: 12px 0; border-top: 1px solid var(--line-soft); }
.ms { display: flex; flex-direction: column; gap: 4px; }
.ms .mono { font-size: 16px; color: var(--ink); }
.err { color: var(--red); font-size: 12px; }

.stage { min-width: 0; }
.placeholder { display: flex; align-items: center; justify-content: center; height: 100%; }
.ph-inner { text-align: center; }
.ph-icon { font-size: 48px; color: var(--ink-faint); opacity: 0.5; margin-bottom: 10px; }

@media (max-width: 900px) { .volume { grid-template-columns: 1fr; height: auto; } .stage { min-height: 60vh; } }
</style>
