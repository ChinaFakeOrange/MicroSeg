<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter, RouterView, RouterLink } from 'vue-router'
import { useProjectStore } from '@/stores/projects'
import { useTaskStore } from '@/stores/tasks'
import TaskMonitor from '@/components/TaskMonitor.vue'

const route = useRoute()
const router = useRouter()
const projects = useProjectStore()
const tasks = useTaskStore()
const drawerOpen = ref(false)

const projectId = computed(() => route.params.id || null)
const inProject = computed(() => !!projectId.value)

const tabs = [
  { name: 'annotate', label: 'Annotate', glyph: '✎' },
  { name: 'analyze', label: 'Analyze', glyph: '∑' },
  { name: 'volume', label: '3D Volume', glyph: '⬡' },
  { name: 'train', label: 'Train', glyph: '◈' },
]

// When the project in the URL changes, open it and (re)wire the task socket.
watch(projectId, async (id, prev) => {
  if (id && id !== prev) {
    if (projects.current?.id !== id) await projects.open(id)
    await tasks.hydrate(id)
    tasks.connect(id)
  }
}, { immediate: true })

onMounted(() => { projects.refresh() })

const activeCount = computed(() => tasks.active.length)
const goProjects = () => router.push('/')
</script>

<template>
  <div class="shell">
    <!-- instrument rail -->
    <aside class="rail">
      <button class="brand" @click="goProjects" title="Projects">
        <span class="brand-mark"></span>
        <span class="brand-text">Micro<span class="accent">Seg</span></span>
      </button>

      <div class="rail-section">
        <div class="eyebrow rail-eyebrow">Workspace</div>
        <button class="rail-item" :class="{ on: route.name === 'projects' }" @click="goProjects">
          <span class="rail-glyph">▦</span> Projects
        </button>
      </div>

      <div v-if="inProject" class="rail-section">
        <div class="eyebrow rail-eyebrow">{{ projects.current?.name || 'Project' }}</div>
        <RouterLink
          v-for="t in tabs"
          :key="t.name"
          class="rail-item"
          :class="{ on: route.name === t.name }"
          :to="{ name: t.name, params: { id: projectId } }"
        >
          <span class="rail-glyph">{{ t.glyph }}</span> {{ t.label }}
        </RouterLink>
      </div>

      <div class="spacer"></div>

      <div class="rail-foot mono">
        <span class="dot" :class="tasks.connected ? 'done' : 'queued'"></span>
        {{ tasks.connected ? 'stream live' : 'polling' }}
      </div>
    </aside>

    <!-- main column -->
    <div class="main">
      <header class="topbar">
        <div class="crumbs mono">
          <span class="faint">microseg</span>
          <span v-if="inProject" class="faint"> / </span>
          <span v-if="inProject">{{ projects.current?.name }}</span>
          <span v-if="inProject" class="faint"> / {{ route.name }}</span>
        </div>
        <div class="spacer"></div>
        <button class="btn btn-sm task-pill" @click="drawerOpen = !drawerOpen">
          <span class="dot" :class="activeCount ? 'running' : 'done'"></span>
          <span class="mono">{{ activeCount }} active</span>
          <span class="faint">tasks</span>
        </button>
      </header>

      <main class="content">
        <RouterView />
      </main>
    </div>

    <!-- task drawer -->
    <transition name="drawer">
      <TaskMonitor v-if="drawerOpen" @close="drawerOpen = false" />
    </transition>
    <transition name="fade">
      <div v-if="drawerOpen" class="scrim" @click="drawerOpen = false"></div>
    </transition>
  </div>
</template>

<style scoped>
.shell { display: flex; height: 100vh; overflow: hidden; }

/* --- rail --- */
.rail {
  width: 232px;
  flex-shrink: 0;
  background: linear-gradient(180deg, var(--surface), var(--bg));
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  gap: 22px;
}
.brand {
  display: flex; align-items: center; gap: 10px;
  background: none; border: none; cursor: pointer; padding: 4px;
}
.brand-mark {
  width: 24px; height: 24px; border-radius: 7px;
  background:
    radial-gradient(circle at 32% 32%, var(--cyan), transparent 60%),
    radial-gradient(circle at 70% 70%, var(--magenta), transparent 60%),
    var(--bg-deep);
  box-shadow: var(--glow-cyan);
  flex-shrink: 0;
}
.brand-text { font-family: var(--font-display); font-weight: 700; font-size: 19px; letter-spacing: -0.02em; color: var(--ink); }
.brand-text .accent { color: var(--cyan); }

.rail-section { display: flex; flex-direction: column; gap: 4px; }
.rail-eyebrow { padding: 0 8px 6px; }
.rail-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 10px; border-radius: var(--radius-sm);
  color: var(--ink-soft); cursor: pointer;
  background: none; border: 1px solid transparent; text-align: left;
  font-size: 14px; transition: background 0.12s, color 0.12s, border-color 0.12s;
}
.rail-item:hover { background: var(--surface-2); color: var(--ink); }
.rail-item.on { background: var(--surface-2); color: var(--ink); border-color: var(--line); }
.rail-item.on .rail-glyph { color: var(--cyan); }
.rail-glyph { width: 18px; text-align: center; color: var(--ink-faint); font-size: 14px; }

.rail-foot { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--ink-faint); padding: 0 8px; }

/* --- main --- */
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.topbar {
  height: 56px; flex-shrink: 0;
  display: flex; align-items: center; gap: 14px;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: rgba(12, 15, 21, 0.7);
  backdrop-filter: blur(8px);
}
.crumbs { font-size: 13px; }
.task-pill { gap: 8px; }

.content { flex: 1; overflow: auto; padding: 24px; }

/* --- drawer --- */
.scrim { position: fixed; inset: 0; background: rgba(4, 6, 9, 0.5); z-index: 40; }
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.drawer-enter-active, .drawer-leave-active { transition: transform 0.28s var(--ease); }
.drawer-enter-from, .drawer-leave-to { transform: translateX(100%); }

@media (max-width: 760px) {
  .rail { width: 64px; padding: 14px 8px; }
  .brand-text, .rail-eyebrow, .rail-item span:not(.rail-glyph), .rail-foot { display: none; }
  .rail-item { justify-content: center; }
}
</style>
