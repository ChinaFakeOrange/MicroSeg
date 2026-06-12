import { defineStore } from 'pinia'
import { api, taskSocketUrl } from '@/api/client'

// Central registry of every task we have dispatched or learned about, kept live
// through the task WebSocket. Survives view changes; a single socket is shared
// across the whole app. If the socket drops, we fall back to polling the tasks
// we still consider active.

const TERMINAL = new Set(['done', 'error', 'cancelled'])

// The backend speaks pending/running/success/failed/cancelled; the rest of the
// UI speaks queued/running/done/error/cancelled. Normalise on the way in so a
// finished task actually reads as "done" (otherwise results never render and
// tasks appear active forever).
const STATE_MAP = {
  pending: 'queued', queued: 'queued', running: 'running',
  success: 'done', done: 'done', failed: 'error', error: 'error',
  cancelled: 'cancelled', canceled: 'cancelled',
}
const normState = (s) => STATE_MAP[s] || s

export const useTaskStore = defineStore('tasks', {
  state: () => ({
    tasks: {},          // id -> task record
    socket: null,
    connected: false,
    projectId: null,
    _poll: null,
  }),

  getters: {
    list: (s) => Object.values(s.tasks).sort((a, b) => b.created_at - a.created_at),
    active: (s) => Object.values(s.tasks).filter((t) => !TERMINAL.has(t.state)),
    byId: (s) => (id) => s.tasks[id],
  },

  actions: {
    ingest(task) {
      if (!task || !task.id) return
      if (task.state) task = { ...task, state: normState(task.state) }
      // Merge so a partial WS event never clobbers a fuller record.
      this.tasks[task.id] = { ...this.tasks[task.id], ...task }
    },

    async hydrate(projectId) {
      this.projectId = projectId
      try {
        const existing = await api.projectTasks(projectId)
        for (const t of existing) this.ingest(t)
      } catch { /* no tasks yet */ }
    },

    connect(projectId) {
      this.projectId = projectId ?? this.projectId
      this.disconnect()
      let ws
      try {
        ws = new WebSocket(taskSocketUrl(this.projectId))
      } catch {
        this.startPolling()
        return
      }
      ws.onopen = () => { this.connected = true; this.stopPolling() }
      ws.onmessage = (ev) => {
        try { this.ingest(JSON.parse(ev.data)) } catch { /* ignore */ }
      }
      ws.onclose = () => {
        this.connected = false
        this.socket = null
        // Reconnect with backoff; poll meanwhile so progress keeps flowing.
        this.startPolling()
        setTimeout(() => { if (!this.connected) this.connect(this.projectId) }, 4000)
      }
      ws.onerror = () => ws.close()
      this.socket = ws
    },

    disconnect() {
      if (this.socket) {
        this.socket.onclose = null
        this.socket.close()
        this.socket = null
      }
      this.connected = false
    },

    // Polling fallback — only refreshes tasks that are still active.
    startPolling() {
      if (this._poll) return
      this._poll = setInterval(async () => {
        const ids = this.active.map((t) => t.id)
        await Promise.all(ids.map(async (id) => {
          try { this.ingest(await api.getTask(id)) } catch { /* gone */ }
        }))
      }, 1500)
    },
    stopPolling() {
      if (this._poll) { clearInterval(this._poll); this._poll = null }
    },

    async cancel(id) {
      try { this.ingest(await api.cancelTask(id)) } catch { /* already gone */ }
    },

    // Convenience: dispatch a job and register its returned task id immediately
    // so the UI shows it as "queued" before the first WS event arrives.
    register(taskId, type) {
      this.ingest({
        id: taskId, type, state: 'queued', progress: 0, message: 'Queued',
        project_id: this.projectId, created_at: Date.now() / 1000, updated_at: Date.now() / 1000,
      })
    },
  },
})
