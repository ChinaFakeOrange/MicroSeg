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
        this.images = await api.listImages(id)
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
      if (this.current) this.images = await api.listImages(this.current.id)
    },

    async upload(fileList) {
      if (!this.current) return
      await api.uploadImages(this.current.id, fileList)
      await this.reloadImages()
    },
  },
})
