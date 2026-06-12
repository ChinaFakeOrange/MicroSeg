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
const saving = ref(false)
const fileInput = ref(null)
const dispatchError = ref(null)

const classes = computed(() => store.classes)
const images = computed(() => store.images)

const maskUrl = computed(() =>
  currentImage.value ? api.maskUrl(props.id, currentImage.value.id) + `&t=${maskVersion.value}` : null
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

async function saveCurrent() {
  if (!currentImage.value) return
  saving.value = true
  try {
    await api.saveAnnotation(props.id, currentImage.value.id, {
      boxes: annotation.boxes, scribbles: annotation.scribbles,
    })
  } finally { saving.value = false }
}

function pickFiles() { fileInput.value.click() }
async function onFiles(e) {
  const files = e.target.files
  if (files?.length) {
    await store.upload(files)
    if (!currentImage.value && store.images.length) selectImage(store.images[0])
  }
  e.target.value = ''
}

// Dispatch interactive segmentation for the current image using its scribbles.
async function runSegment() {
  dispatchError.value = null
  await saveCurrent()
  if (!currentImage.value) return
  const strokes = annotation.scribbles
  if (!strokes.length) { dispatchError.value = 'Add foreground/background scribbles first.'; return }
  try {
    await dispatch('segment', props.id, {
      image_ids: [currentImage.value.id],
      strokes_by_image: { [currentImage.value.id]: strokes },
    })
    showMask.value = true
  } catch (e) { dispatchError.value = e.message }
}

// When a segment task for this image finishes, bump the mask URL to reload it.
watch(() => tasks.list.map((t) => `${t.id}:${t.state}`).join(','), () => {
  const done = tasks.list.find((t) => t.type === 'segment' && t.state === 'done')
  if (done) maskVersion.value++
})

onMounted(async () => {
  if (store.current?.id !== props.id) await store.open(props.id)
  if (store.images.length) selectImage(store.images[0])
})

const isDetection = computed(() => store.current?.task_type === 'detection')
watch(isDetection, (d) => { if (d) tool.value = 'box' }, { immediate: true })
</script>

<template>
  <div class="annotate">
    <!-- left: image strip -->
    <div class="strip panel">
      <div class="strip-head">
        <span class="eyebrow">Images</span>
        <span class="badge mono">{{ images.length }}</span>
        <span class="spacer"></span>
        <button class="btn btn-sm" @click="pickFiles">＋</button>
        <input ref="fileInput" type="file" accept="image/*" multiple hidden @change="onFiles" />
      </div>
      <div class="thumbs">
        <button
          v-for="img in images"
          :key="img.id"
          class="thumb"
          :class="{ on: currentImage?.id === img.id }"
          @click="selectImage(img)"
        >
          <img :src="api.rawImageUrl(id, img.id)" :alt="img.name" loading="lazy" />
          <span class="thumb-name mono">{{ img.name }}</span>
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
        :show-mask="showMask"
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
        </div>
      </div>

      <div class="tool-block">
        <span class="eyebrow">Class</span>
        <div class="class-list">
          <button
            v-for="c in classes"
            :key="c.id"
            class="class-pick"
            :class="{ on: activeLabel === c.id }"
            @click="activeLabel = c.id"
          >
            <span class="sw" :style="{ background: c.color }"></span>
            <span>{{ c.name }}</span>
            <span class="mono faint">{{ c.id }}</span>
          </button>
        </div>
      </div>

      <div class="tool-block" v-if="tool === 'scribble' || tool === 'erase'">
        <span class="eyebrow">Brush · {{ brush }}px</span>
        <input type="range" min="2" max="24" v-model.number="brush" class="range" />
      </div>

      <div class="tool-block">
        <label class="check">
          <input type="checkbox" v-model="showMask" />
          <span>Overlay prediction</span>
        </label>
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
        <p class="hint faint mono">
          Scribble foreground & background, then run. LightGBM learns from your
          strokes and labels the whole frame.
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.annotate { display: grid; grid-template-columns: 220px 1fr 260px; gap: 16px; height: calc(100vh - 56px - 48px); }

.strip { display: flex; flex-direction: column; overflow: hidden; }
.strip-head { display: flex; align-items: center; gap: 8px; padding: 14px; border-bottom: 1px solid var(--line); }
.thumbs { flex: 1; overflow: auto; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.thumb {
  position: relative; border: 1px solid var(--line); border-radius: 8px; overflow: hidden;
  background: var(--bg-deep); cursor: pointer; padding: 0; aspect-ratio: 4 / 3;
}
.thumb img { width: 100%; height: 100%; object-fit: cover; display: block; opacity: 0.85; }
.thumb.on { border-color: var(--cyan); box-shadow: var(--glow-cyan); }
.thumb.on img { opacity: 1; }
.thumb-name {
  position: absolute; bottom: 0; left: 0; right: 0; padding: 3px 6px;
  font-size: 10px; background: rgba(8,10,14,0.8); color: var(--ink-soft);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.empty { padding: 20px 8px; font-size: 13px; text-align: center; }

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
.hint { font-size: 10px; line-height: 1.5; }
.err { color: var(--red); font-size: 12px; }

@media (max-width: 980px) {
  .annotate { grid-template-columns: 1fr; height: auto; }
  .stage-col { min-height: 60vh; }
}
</style>
