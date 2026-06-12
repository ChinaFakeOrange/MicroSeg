<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import { useJobs } from '@/composables/useJobs'
import PercolationSim from '@/components/PercolationSim.vue'

const props = defineProps({ id: { type: String, required: true } })
const store = useProjectStore()
const tasks = useTaskStore()
const { dispatch } = useJobs()

const subtab = ref('morphometry')
const err = ref(null)

const morph = reactive({ image_id: '', watershed: true, watershed_level: 0.1, min_area: 0, spacing: 1.0 })
const perc = reactive({ image_id: '', pore_label: 0, inlet_axis: 0, inlet_side: 'low', n_frames: 120 })

const images = computed(() => store.images)
const classes = computed(() => store.classes)

onMounted(async () => {
  if (store.current?.id !== props.id) await store.open(props.id)
  if (images.value.length) {
    morph.image_id = images.value[0].id
    perc.image_id = images.value[0].id
  }
  morph.spacing = store.current?.pixel_size_um || 1.0
})

// latest finished results of each kind
const latestMorph = computed(() =>
  tasks.list.find((t) => t.type === 'morphometry' && t.state === 'done')?.result)
const latestPerc = computed(() =>
  tasks.list.find((t) => t.type === 'percolation' && t.state === 'done')?.result)

async function runMorph() {
  err.value = null
  try {
    await dispatch('morphometry', props.id, {
      image_ids: morph.image_id ? [morph.image_id] : images.value.map((i) => i.id),
      spacing: morph.spacing, watershed: morph.watershed,
      watershed_level: morph.watershed_level, min_area: morph.min_area,
    })
  } catch (e) { err.value = e.message }
}

async function runPerc() {
  err.value = null
  try {
    await dispatch('percolation', props.id, {
      image_id: perc.image_id, pore_label: perc.pore_label,
      inlet_axis: perc.inlet_axis, inlet_side: perc.inlet_side, n_frames: perc.n_frames,
    })
  } catch (e) { err.value = e.message }
}

const COLS = ['object', 'area', 'ed', 'esp', 'perimeter', 'rugosity', 'cpc', 'elongation', 'roundness', 'feret_diameter']
function fmt(v) { return typeof v === 'number' ? (Number.isInteger(v) ? v : v.toFixed(2)) : v }

function downloadCsv() {
  const rows = latestMorph.value?.rows || []
  if (!rows.length) return
  const head = Object.keys(rows[0])
  const lines = [head.join(','), ...rows.map((r) => head.map((h) => r[h]).join(','))]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = 'morphometry.csv'; a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="analyze">
    <div class="subtabs">
      <button class="subtab" :class="{ on: subtab === 'morphometry' }" @click="subtab = 'morphometry'">∑ Morphometry</button>
      <button class="subtab" :class="{ on: subtab === 'percolation' }" @click="subtab = 'percolation'">≈ Percolation</button>
    </div>

    <p v-if="err" class="err mono">{{ err }}</p>

    <!-- MORPHOMETRY -->
    <section v-show="subtab === 'morphometry'" class="grid2">
      <div class="panel ctrl">
        <div class="eyebrow">Measure particles</div>
        <p class="muted small">Watershed-split the predicted mask and compute per-object area, equivalent diameter, perimeter, rugosity, roundness and more.</p>
        <label class="lbl">Image</label>
        <select class="field" v-model="morph.image_id">
          <option value="">All images</option>
          <option v-for="i in images" :key="i.id" :value="i.id">{{ i.name }}</option>
        </select>
        <label class="check"><input type="checkbox" v-model="morph.watershed" /> <span>Watershed split touching objects</span></label>
        <div class="two">
          <div><label class="lbl">Watershed level</label><input class="field mono" type="number" step="0.01" v-model.number="morph.watershed_level" /></div>
          <div><label class="lbl">Min area (px)</label><input class="field mono" type="number" v-model.number="morph.min_area" /></div>
        </div>
        <label class="lbl">Spacing (µm/px)</label>
        <input class="field mono" type="number" step="0.01" v-model.number="morph.spacing" />
        <button class="btn btn-primary full" @click="runMorph">Run morphometry</button>
      </div>

      <div class="panel results">
        <div class="res-head">
          <div class="eyebrow">Results</div>
          <span v-if="latestMorph" class="badge mono">{{ latestMorph.summary?.count ?? 0 }} objects</span>
          <span class="spacer"></span>
          <button class="btn btn-sm" :disabled="!latestMorph" @click="downloadCsv">Export CSV</button>
        </div>
        <div v-if="latestMorph" class="table-wrap">
          <table class="data mono">
            <thead><tr><th v-for="c in COLS" :key="c">{{ c }}</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in latestMorph.rows.slice(0, 200)" :key="i">
                <td v-for="c in COLS" :key="c">{{ fmt(r[c]) }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="latestMorph.rows.length > 200" class="faint small">showing first 200 of {{ latestMorph.rows.length }}</p>
        </div>
        <p v-else class="muted empty">Run a measurement to populate the table.</p>
      </div>
    </section>

    <!-- PERCOLATION -->
    <section v-show="subtab === 'percolation'" class="grid2">
      <div class="panel ctrl">
        <div class="eyebrow">Pore-network percolation</div>
        <p class="muted small">Treat one label as pore space and simulate invasion percolation — fluid enters from an inlet face and advances through the widest available throats. Watch the front break through.</p>
        <label class="lbl">Image (segmented)</label>
        <select class="field" v-model="perc.image_id">
          <option v-for="i in images" :key="i.id" :value="i.id">{{ i.name }}</option>
        </select>
        <label class="lbl">Pore label</label>
        <select class="field" v-model.number="perc.pore_label">
          <option v-for="c in classes" :key="c.id" :value="c.id">{{ c.name }} ({{ c.id }})</option>
        </select>
        <div class="two">
          <div>
            <label class="lbl">Inlet axis</label>
            <select class="field" v-model.number="perc.inlet_axis"><option :value="0">rows (top/bottom)</option><option :value="1">cols (left/right)</option></select>
          </div>
          <div>
            <label class="lbl">Inlet side</label>
            <select class="field" v-model="perc.inlet_side"><option value="low">low</option><option value="high">high</option></select>
          </div>
        </div>
        <button class="btn btn-primary full" @click="runPerc">Run percolation</button>
      </div>

      <div class="panel results">
        <PercolationSim v-if="latestPerc" :result="latestPerc" />
        <p v-else class="muted empty">Run a simulation to see the invasion animation.</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.analyze { display: flex; flex-direction: column; gap: 16px; max-width: 1200px; margin: 0 auto; }
.subtabs { display: flex; gap: 6px; }
.subtab { padding: 8px 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: var(--ink-soft); cursor: pointer; font-size: 14px; }
.subtab.on { border-color: var(--cyan); color: var(--ink); background: var(--surface-2); }

.grid2 { display: grid; grid-template-columns: 320px 1fr; gap: 16px; align-items: start; }
.ctrl { padding: 18px; display: flex; flex-direction: column; gap: 12px; }
.ctrl .small { font-size: 12px; line-height: 1.55; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.full { width: 100%; justify-content: center; margin-top: 4px; }
.check { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-soft); }

.results { padding: 16px; min-height: 360px; }
.res-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.table-wrap { overflow: auto; max-height: 62vh; }
table.data { width: 100%; border-collapse: collapse; font-size: 12px; }
table.data th { position: sticky; top: 0; background: var(--surface-2); color: var(--ink-soft); text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--line); font-weight: 500; letter-spacing: 0.03em; }
table.data td { text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--line-soft); color: var(--ink); }
table.data tbody tr:hover { background: var(--surface-2); }
.empty { padding: 60px 20px; text-align: center; }
.err { color: var(--red); }
.small { font-size: 12px; }

@media (max-width: 900px) { .grid2 { grid-template-columns: 1fr; } }
</style>
