import { defineStore } from 'pinia'
import { api } from '@/api/client'

export const useProjectStore = defineStore('projects', {
  state: () => ({
    projects: [],
    current: null,      // full project object
    images: [],
    loading: false,
    error: null,
  }),

  getters: {
    classes: (s) => s.current?.classes || [],
    classById: (s) => (id) => (s.current?.classes || []).find((c) => c.id === id),
  },

  actions: {
    // The backend manifest stores `filename`; views display `.name`. Normalise
    // here so every image has a friendly, non-empty name in one place.
    _normalize(images) {
      return (images || []).map((img) => ({
        ...img,
        name: img.name || img.filename || img.path || img.id,
      }))
    },

    async refresh() {
      this.loading = true
      this.error = null
      try {
        this.projects = await api.listProjects()
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },

    async open(id) {
      this.loading = true
      this.error = null
      try {
        this.current = await api.getProject(id)
        this.images = this._normalize(await api.listImages(id))
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },

    async create(payload) {
      const project = await api.createProject(payload)
      await this.refresh()
      return project
    },

    async remove(id) {
      await api.deleteProject(id)
      if (this.current?.id === id) {
        this.current = null
        this.images = []
      }
      await this.refresh()
    },

    async reloadImages() {
      if (this.current) this.images = this._normalize(await api.listImages(this.current.id))
    },

    async upload(fileList, opts = {}) {
      if (!this.current) return
      await api.uploadImages(this.current.id, fileList, opts)
      await this.reloadImages()
    },

    async updateClasses(classes) {
      if (!this.current) return
      this.current = await api.updateClasses(this.current.id, classes)
    },

    async toggleSelected(imageId, selected) {
      if (!this.current) return
      await api.setImageSelected(this.current.id, imageId, selected)
      const img = this.images.find((i) => i.id === imageId)
      if (img) img.selected = selected
    },

    async setSelectedMany(ids, selected) {
      if (!this.current || !ids.length) return
      await api.selectImages(this.current.id, ids, selected)
      const idset = new Set(ids)
      for (const img of this.images) if (idset.has(img.id)) img.selected = selected
    },
  },
})
