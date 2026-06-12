<script setup>
import { computed } from 'vue'
import { useTaskStore } from '@/stores/tasks'

const emit = defineEmits(['close'])
const tasks = useTaskStore()
const list = computed(() => tasks.list)

const STATE_LABEL = {
  queued: 'queued', running: 'running', done: 'done',
  error: 'error', cancelled: 'cancelled',
}

function pct(t) { return Math.round((t.progress || 0) * 100) }
function isActive(t) { return !['done', 'error', 'cancelled'].includes(t.state) }
function elapsed(t) {
  const s = (t.updated_at - t.created_at) || 0
  return s < 60 ? `${s.toFixed(1)}s` : `${(s / 60).toFixed(1)}m`
}

// Surface a useful result line per task type.
function resultLine(t) {
  const r = t.result
  if (!r) return null
  if (t.type === 'percolation')
    return `percolates=${r.percolates} · breakthrough=${r.breakthrough_step ?? '—'} · φ=${(r.porosity ?? 0).toFixed(3)}`
  if (t.type === 'morphometry')
    return `${r.summary?.count ?? '?'} objects · total area ${Math.round(r.summary?.total_area ?? 0)}`
  if (t.type === 'mesh')
    return `${r.vertex_count} verts · ${r.triangle_count} tris`
  if (t.type === 'segment')
    return `${r.n_images ?? r.image_ids?.length ?? ''} image(s) segmented`
  if (t.type === 'train')
    return r.best_dice != null ? `best dice ${r.best_dice.toFixed(3)}` : 'checkpoint saved'
  return null
}
</script>

<template>
  <aside class="drawer panel">
    <header class="dhead">
      <div>
        <div class="eyebrow">Instrument log</div>
        <h3>Tasks</h3>
      </div>
      <button class="btn btn-ghost btn-sm" @click="emit('close')">✕</button>
    </header>

    <div class="dbody">
      <p v-if="!list.length" class="empty muted">
        No tasks yet. Dispatch segmentation, morphometry, a mesh build or training
        and progress will stream here.
      </p>

      <article v-for="t in list" :key="t.id" class="task">
        <div class="task-top">
          <span class="dot" :class="t.state"></span>
          <span class="ttype mono">{{ t.type }}</span>
          <span class="badge">{{ STATE_LABEL[t.state] || t.state }}</span>
          <span class="spacer"></span>
          <span class="mono faint tid">{{ t.id }}</span>
        </div>

        <div class="task-msg muted">{{ t.message || '—' }}</div>

        <div class="bar" :class="{ indeterminate: t.state === 'running' && !t.progress }">
          <div class="bar-fill" :class="t.state" :style="{ width: pct(t) + '%' }"></div>
        </div>

        <div class="task-foot mono">
          <span class="faint">{{ pct(t) }}%</span>
          <span class="faint">·</span>
          <span class="faint">{{ elapsed(t) }}</span>
          <span class="spacer"></span>
          <span v-if="resultLine(t)" class="resline">{{ resultLine(t) }}</span>
          <button v-if="isActive(t)" class="btn btn-ghost btn-sm btn-danger" @click="tasks.cancel(t.id)">cancel</button>
        </div>

        <div v-if="t.error" class="task-err mono">{{ t.error }}</div>
      </article>
    </div>
  </aside>
</template>

<style scoped>
.drawer {
  position: fixed; top: 0; right: 0; bottom: 0;
  width: min(440px, 92vw);
  z-index: 50;
  border-radius: 0;
  border-left: 1px solid var(--line);
  display: flex; flex-direction: column;
  background: var(--surface);
}
.dhead {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 18px 14px; border-bottom: 1px solid var(--line);
}
.dhead h3 { font-size: 18px; margin-top: 2px; }
.dbody { flex: 1; overflow: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.empty { padding: 32px 8px; line-height: 1.6; font-size: 14px; }

.task {
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  padding: 12px;
}
.task-top { display: flex; align-items: center; gap: 8px; }
.ttype { font-size: 13px; color: var(--ink); font-weight: 600; }
.tid { font-size: 10px; }
.task-msg { font-size: 13px; margin: 8px 0; min-height: 1.2em; }

.bar { height: 5px; background: var(--bg-deep); border-radius: 4px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s var(--ease); background: var(--cyan); }
.bar-fill.done { background: var(--green); }
.bar-fill.error, .bar-fill.cancelled { background: var(--red); }
.bar-fill.running { background: linear-gradient(90deg, var(--cyan), var(--violet)); }
.bar.indeterminate .bar-fill {
  width: 35% !important;
  animation: slide 1.1s var(--ease) infinite;
}
@keyframes slide { 0% { margin-left: -35%; } 100% { margin-left: 100%; } }

.task-foot { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 11px; }
.resline { color: var(--cyan); font-size: 11px; }
.task-err {
  margin-top: 8px; padding: 8px; border-radius: 6px;
  background: rgba(240, 96, 77, 0.08); color: var(--red);
  font-size: 11px; white-space: pre-wrap; word-break: break-word;
}
</style>
