import { createRouter, createWebHistory } from 'vue-router'

const ProjectsView = () => import('@/views/ProjectsView.vue')
const AnnotateView = () => import('@/views/AnnotateView.vue')
const AnalyzeView = () => import('@/views/AnalyzeView.vue')
const VolumeView = () => import('@/views/VolumeView.vue')
const TrainView = () => import('@/views/TrainView.vue')

const routes = [
  { path: '/', name: 'projects', component: ProjectsView },
  { path: '/p/:id/annotate', name: 'annotate', component: AnnotateView, props: true },
  { path: '/p/:id/analyze', name: 'analyze', component: AnalyzeView, props: true },
  { path: '/p/:id/volume', name: 'volume', component: VolumeView, props: true },
  { path: '/p/:id/train', name: 'train', component: TrainView, props: true },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
