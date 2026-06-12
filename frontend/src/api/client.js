// Thin wrapper over the MicroSeg REST API. All calls go through /api which is
// proxied to the FastAPI backend (vite dev server in development, nginx in
// production), so the frontend never needs an absolute backend URL.

const BASE = '/api'

async function http(method, path, body, isForm = false) {
  const opts = { method, headers: {} }
  if (body !== undefined) {
    if (isForm) {
      opts.body = body // FormData — let the browser set the boundary
    } else {
      opts.headers['Content-Type'] = 'application/json'
      opts.body = JSON.stringify(body)
    }
  }
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    let detail
    try { detail = (await res.json()).detail } catch { detail = res.statusText }
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${res.status})`)
  }
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res
}

export const api = {
  // --- projects ---
  listProjects: () => http('GET', '/projects'),
  getProject: (id) => http('GET', `/projects/${id}`),
  createProject: (payload) => http('POST', '/projects', payload),
  deleteProject: (id) => http('DELETE', `/projects/${id}`),

  // --- images ---
  listImages: (pid) => http('GET', `/projects/${pid}/images`),
  uploadImages: (pid, fileList) => {
    const form = new FormData()
    for (const f of fileList) form.append('files', f)
    return http('POST', `/projects/${pid}/images`, form, true)
  },
  rawImageUrl: (pid, iid) => `${BASE}/projects/${pid}/images/${iid}/raw`,
  maskUrl: (pid, iid) => `${BASE}/projects/${pid}/images/${iid}/mask?colorized=true`,

  // --- annotations ---
  getAnnotation: (pid, iid) => http('GET', `/projects/${pid}/images/${iid}/annotation`),
  saveAnnotation: (pid, iid, ann) => http('PUT', `/projects/${pid}/images/${iid}/annotation`, ann),

  // --- jobs (return { task_id }) ---
  segment: (pid, payload) => http('POST', `/projects/${pid}/segment`, payload),
  morphometry: (pid, payload) => http('POST', `/projects/${pid}/morphometry`, payload),
  percolation: (pid, payload) => http('POST', `/projects/${pid}/percolation`, payload),
  mesh: (pid, payload) => http('POST', `/projects/${pid}/mesh`, payload),
  train: (pid, payload) => http('POST', `/projects/${pid}/train`, payload),
  inference: (pid, payload) => http('POST', `/projects/${pid}/inference`, payload),

  // --- tasks ---
  getTask: (tid) => http('GET', `/tasks/${tid}`),
  cancelTask: (tid) => http('POST', `/tasks/${tid}/cancel`),
  projectTasks: (pid) => http('GET', `/projects/${pid}/tasks`),
  exportUrl: (pid, name) => `${BASE}/projects/${pid}/exports/${name}`,
}

// WebSocket URL for the live task stream, optionally filtered by project.
export function taskSocketUrl(projectId) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const q = projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
  return `${proto}://${location.host}${BASE}/ws/tasks${q}`
}
