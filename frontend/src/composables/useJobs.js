import { api } from '@/api/client'
import { useTaskStore } from '@/stores/tasks'

// Dispatch a job through the API and immediately register the returned task id
// with the task store so the monitor shows it as "queued" before the first
// WebSocket event arrives. Returns the task id (or throws on dispatch failure).
export function useJobs() {
  const tasks = useTaskStore()

  async function dispatch(kind, pid, payload) {
    const fn = api[kind]
    if (!fn) throw new Error(`Unknown job kind: ${kind}`)
    const { task_id } = await fn(pid, payload)
    tasks.register(task_id, kind)
    return task_id
  }

  return { dispatch }
}
