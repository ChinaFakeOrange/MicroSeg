<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useProjectStore } from '@/stores/projects'
import { api } from '@/api/client'

const router = useRouter()
const store = useProjectStore()
const creating = ref(false)
const createFiles = ref([])
const uploadOpts = reactive({ axis: 0, select_every: 1 })
const submitting = ref(false)
const tiffInfo = ref(null)        // { shape: [d0,d1,d2] } of the first selected TIFF

const hasTiff = () => createFiles.value.some((f) => /\.tiff?$/i.test(f.name))
async function onCreateFiles(e) {
  createFiles.value = Array.from(e.target.files || [])
  tiffInfo.value = null
  const tiff = createFiles.value.find((f) => /\.tiff?$/i.test(f.name))
  if (tiff) {
    try { tiffInfo.value = await api.inspectTiff(tiff) } catch { tiffInfo.value = null }
  }
}

// Number of slices along the chosen axis, and how many will be annotated.
const axisCount = computed(() => tiffInfo.value?.shape?.[uploadOpts.axis] ?? null)
const selectedCount = computed(() => {
  const n = axisCount.value
  if (!n) return null
  return Math.ceil(n / Math.max(1, uploadOpts.select_every))
})
const AXIS_NAMES = ['Z / pages', 'Y', 'X']

const draft = reactive({
  name: '',
  task_type: 'segmentation',
  pixel_size_um: 1.0,
  is_stack: false,
  description: '',
  classes: [
    { id: 1, name: 'particle', color: '#2fe6cf' },
    { id: 2, name: 'pore', color: '#f0519e' },
  ],
})

function addClass() {
  const id = (draft.classes.at(-1)?.id || 0) + 1
  const palette = ['#2fe6cf', '#f0519e', '#8b7bf0', '#f2b441', '#4fd178', '#f0604d']
  draft.classes.push({ id, name: `class ${id}`, color: palette[id % palette.length] })
}
function removeClass(i) { draft.classes.splice(i, 1) }

async function submit() {
  if (!draft.name.trim()) return
  submitting.value = true
  try {
    const project = await store.create({ ...draft })
    // Upload any chosen images right away (TIFF stacks are sliced server-side).
    if (createFiles.value.length) {
      await store.open(project.id)
      await store.upload(createFiles.value, { ...uploadOpts })
    }
    creating.value = false
    draft.name = ''
    createFiles.value = []; tiffInfo.value = null
    router.push({ name: 'annotate', params: { id: project.id } })
  } finally { submitting.value = false }
}

function open(p) { router.push({ name: 'annotate', params: { id: p.id } }) }
async function del(p, e) {
  e.stopPropagation()
  if (confirm(`Delete project "${p.name}"? This removes its images, masks and models.`)) {
    await store.remove(p.id)
  }
}

onMounted(() => store.refresh())
</script>

<template>
  <div class="wrap">
    <section class="hero">
      <div class="hero-copy">
        <div class="eyebrow">Microscopy analysis workbench</div>
        <h1 class="hero-title">
          Annotate, train and measure<br />
          <span class="grad">microscopic structure</span> in the browser.
        </h1>
        <p class="hero-sub muted">
          Scribble-driven segmentation, deep-learning training, particle morphometry,
          3D reconstruction and pore-network percolation — every long job runs
          asynchronously and streams its progress to the instrument log.
        </p>
        <button class="btn btn-primary" @click="creating = true">＋ New project</button>
      </div>
      <div class="hero-stage viewport">
        <div class="channel ch-cyan"></div>
        <div class="channel ch-magenta"></div>
        <div class="stage-grid mono">
          <span>FITC</span><span>·</span><span>TRITC</span>
        </div>
      </div>
    </section>

    <section class="list-head">
      <div class="eyebrow">Projects</div>
      <span class="badge mono">{{ store.projects.length }}</span>
      <span class="spacer"></span>
      <button class="btn btn-sm" @click="store.refresh()">Refresh</button>
    </section>

    <p v-if="store.error" class="err mono">{{ store.error }}</p>

    <div v-if="!store.projects.length && !store.loading" class="blank panel">
      <p class="muted">No projects yet. Create one to start annotating images.</p>
    </div>

    <div class="grid">
      <article v-for="p in store.projects" :key="p.id" class="card" @click="open(p)">
        <div class="card-top">
          <h3>{{ p.name }}</h3>
          <button class="btn btn-ghost btn-sm btn-danger" @click="del(p, $event)" title="Delete">✕</button>
        </div>
        <p class="card-desc muted">{{ p.description || 'No description' }}</p>
        <div class="swatches">
          <span
            v-for="c in (p.classes || [])"
            :key="c.id"
            class="sw"
            :style="{ background: c.color }"
            :title="c.name"
          ></span>
        </div>
        <div class="card-foot mono faint">
          <span>{{ p.task_type }}</span>
          <span>·</span>
          <span>{{ p.n_images ?? 0 }} images</span>
        </div>
      </article>
    </div>

    <!-- create modal -->
    <transition name="fade">
      <div v-if="creating" class="modal-scrim" @click.self="creating = false">
        <div class="modal panel">
          <header class="modal-head">
            <div>
              <div class="eyebrow">Configure</div>
              <h3>New project</h3>
            </div>
            <button class="btn btn-ghost btn-sm" @click="creating = false">✕</button>
          </header>

          <div class="modal-body">
            <div class="form-row">
              <div style="flex:2">
                <label class="lbl">Name</label>
                <input class="field" v-model="draft.name" placeholder="e.g. sandstone-thin-sections" />
              </div>
              <div style="flex:1">
                <label class="lbl">Task</label>
                <select class="field" v-model="draft.task_type">
                  <option value="segmentation">segmentation</option>
                  <option value="detection">detection</option>
                </select>
              </div>
            </div>

            <div class="form-row">
              <div style="flex:1">
                <label class="lbl">Pixel size (µm)</label>
                <input class="field mono" type="number" step="0.01" v-model.number="draft.pixel_size_um" />
              </div>
              <label class="stack-toggle">
                <input type="checkbox" v-model="draft.is_stack" />
                <span>Z-stack (enables 3D)</span>
              </label>
            </div>

            <div>
              <label class="lbl">Description</label>
              <input class="field" v-model="draft.description" placeholder="optional" />
            </div>

            <div class="uploads">
              <div class="row" style="margin-bottom:8px">
                <label class="lbl" style="margin:0">Images (optional)</label>
                <span class="spacer"></span>
                <label class="btn btn-sm filebtn">
                  ＋ Choose files
                  <input type="file" accept="image/*,.tif,.tiff" multiple hidden @change="onCreateFiles" />
                </label>
              </div>
              <p v-if="createFiles.length" class="faint mono small">{{ createFiles.length }} file(s) selected</p>
              <p v-else class="faint mono small">PNG/JPG, or a multi-page / 3D TIFF (sliced into a stack).</p>

              <div v-if="hasTiff()" class="tiffopts">
                <div style="grid-column: 1 / -1">
                  <p v-if="tiffInfo" class="dim mono">
                    TIFF dimensions: {{ tiffInfo.shape.join(' × ') }}
                    <span class="faint">(axis 0 × 1 × 2)</span>
                  </p>
                  <p v-else class="faint mono small">Reading dimensions…</p>
                </div>
                <div>
                  <label class="lbl">Slice axis</label>
                  <select class="field" v-model.number="uploadOpts.axis">
                    <option v-for="a in [0,1,2]" :key="a" :value="a">
                      axis {{ a }} ({{ AXIS_NAMES[a] }}){{ tiffInfo ? ` · ${tiffInfo.shape[a]} slices` : '' }}
                    </option>
                  </select>
                </div>
                <div>
                  <label class="lbl">Annotate every Nth</label>
                  <input class="field mono" type="number" min="1" v-model.number="uploadOpts.select_every" />
                </div>
                <p v-if="axisCount" class="sel-summary mono" style="grid-column: 1 / -1">
                  <span class="dot done"></span>
                  {{ axisCount }} slices along axis {{ uploadOpts.axis }} →
                  <strong>annotate {{ selectedCount }}</strong>, store the other {{ axisCount - selectedCount }}.
                </p>
              </div>
            </div>

            <div class="classes">
              <div class="row" style="margin-bottom:8px">
                <label class="lbl" style="margin:0">Classes</label>
                <span class="spacer"></span>
                <button class="btn btn-sm" @click="addClass">＋ Add</button>
              </div>
              <div v-for="(c, i) in draft.classes" :key="i" class="class-row">
                <input type="color" class="color" v-model="c.color" />
                <input class="field mono cid" type="number" v-model.number="c.id" />
                <input class="field" v-model="c.name" placeholder="class name" />
                <button class="btn btn-ghost btn-sm btn-danger" @click="removeClass(i)">✕</button>
              </div>
            </div>
          </div>

          <footer class="modal-foot">
            <button class="btn btn-ghost" @click="creating = false">Cancel</button>
            <button class="btn btn-primary" :disabled="!draft.name.trim() || submitting" @click="submit">
              {{ submitting ? 'Creating…' : 'Create project' }}
            </button>
          </footer>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.wrap { max-width: 1100px; margin: 0 auto; display: flex; flex-direction: column; gap: 28px; }

/* hero */
.hero { display: grid; grid-template-columns: 1.3fr 1fr; gap: 28px; align-items: stretch; padding-top: 8px; }
.hero-copy { display: flex; flex-direction: column; gap: 16px; justify-content: center; }
.hero-title { font-size: clamp(28px, 4vw, 42px); line-height: 1.08; letter-spacing: -0.03em; }
.grad {
  background: linear-gradient(100deg, var(--cyan), var(--magenta));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.hero-sub { font-size: 15px; line-height: 1.65; max-width: 52ch; }
.hero-copy .btn-primary { align-self: flex-start; margin-top: 4px; }

.hero-stage { min-height: 240px; position: relative; }
.channel { position: absolute; border-radius: 50%; filter: blur(28px); mix-blend-mode: screen; }
.ch-cyan { width: 55%; height: 60%; left: 12%; top: 16%; background: radial-gradient(circle, var(--cyan), transparent 70%); animation: drift1 9s var(--ease) infinite alternate; }
.ch-magenta { width: 50%; height: 55%; right: 12%; bottom: 14%; background: radial-gradient(circle, var(--magenta), transparent 70%); animation: drift2 11s var(--ease) infinite alternate; }
@keyframes drift1 { to { transform: translate(18px, -12px) scale(1.08); } }
@keyframes drift2 { to { transform: translate(-16px, 10px) scale(1.05); } }
.stage-grid { position: absolute; bottom: 12px; left: 14px; display: flex; gap: 8px; font-size: 11px; color: var(--ink-soft); letter-spacing: 0.12em; }

/* list */
.list-head { display: flex; align-items: center; gap: 10px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 16px; cursor: pointer; transition: border-color 0.15s, transform 0.1s;
  display: flex; flex-direction: column; gap: 10px;
}
.card:hover { border-color: var(--cyan-deep); transform: translateY(-2px); }
.card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.card-top h3 { font-size: 16px; }
.card-desc { font-size: 13px; line-height: 1.5; min-height: 2.6em; }
.swatches { display: flex; gap: 5px; }
.sw { width: 14px; height: 14px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.12); }
.card-foot { display: flex; gap: 6px; font-size: 11px; }

.blank { padding: 36px; text-align: center; }
.err { color: var(--red); }

/* modal */
.modal-scrim { position: fixed; inset: 0; background: rgba(4,6,9,0.6); z-index: 60; display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal { width: min(620px, 96vw); max-height: 90vh; display: flex; flex-direction: column; box-shadow: var(--shadow); }
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 20px; border-bottom: 1px solid var(--line); }
.modal-head h3 { font-size: 18px; margin-top: 2px; }
.modal-body { padding: 18px 20px; overflow: auto; display: flex; flex-direction: column; gap: 16px; }
.form-row { display: flex; gap: 12px; align-items: flex-end; }
.stack-toggle { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--ink-soft); padding-bottom: 9px; white-space: nowrap; }
.classes { border-top: 1px solid var(--line-soft); padding-top: 14px; }
.uploads { border-top: 1px solid var(--line-soft); padding-top: 14px; display: flex; flex-direction: column; gap: 6px; }
.small { font-size: 12px; }
.filebtn { cursor: pointer; }
.tiffopts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }
.dim { font-size: 13px; color: var(--ink); }
.sel-summary { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-soft); padding: 8px 10px; background: var(--surface-2); border-radius: 8px; }
.sel-summary strong { color: var(--cyan); }.class-row { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.color { width: 38px; height: 38px; padding: 0; border: 1px solid var(--line); border-radius: 8px; background: none; cursor: pointer; }
.cid { width: 64px; flex: none; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; padding: 16px 20px; border-top: 1px solid var(--line); }

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 760px) { .hero { grid-template-columns: 1fr; } .hero-stage { min-height: 160px; } }
</style>
