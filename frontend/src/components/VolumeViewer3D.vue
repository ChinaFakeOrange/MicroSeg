<script setup>
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'

// Renders the isosurface mesh returned by the mesh build job. Flat
// vertices/normals/indices arrays are loaded straight into a BufferGeometry.
const props = defineProps({
  mesh: { type: Object, required: true }, // { vertices, normals, indices, bounds }
  wireframe: { type: Boolean, default: false },
})

const host = ref(null)
let renderer, scene, camera, controls, meshObj, raf, ro

function init() {
  const el = host.value
  const w = el.clientWidth, h = el.clientHeight

  scene = new THREE.Scene()
  scene.background = new THREE.Color('#080a0e')

  camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 5000)

  renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(w, h)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  el.appendChild(renderer.domElement)

  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  controls.dampingFactor = 0.08

  // fluorescence-style two-channel lighting: cyan key, magenta rim
  scene.add(new THREE.AmbientLight(0x223044, 1.1))
  const key = new THREE.DirectionalLight(0x6fe9da, 1.4); key.position.set(1, 1, 1); scene.add(key)
  const rim = new THREE.DirectionalLight(0xf0519e, 0.8); rim.position.set(-1, -0.5, -1); scene.add(rim)
  const top = new THREE.DirectionalLight(0xffffff, 0.3); top.position.set(0, 1, 0); scene.add(top)

  buildMesh()
  frameCamera()
  animate()

  ro = new ResizeObserver(onResize)
  ro.observe(el)
}

function buildMesh() {
  if (meshObj) { scene.remove(meshObj); meshObj.geometry.dispose(); meshObj.material.dispose() }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(props.mesh.vertices, 3))
  if (props.mesh.normals?.length) {
    g.setAttribute('normal', new THREE.Float32BufferAttribute(props.mesh.normals, 3))
  }
  g.setIndex(props.mesh.indices)
  if (!props.mesh.normals?.length) g.computeVertexNormals()

  const mat = new THREE.MeshStandardMaterial({
    color: 0x2fe6cf, metalness: 0.1, roughness: 0.55,
    wireframe: props.wireframe, side: THREE.DoubleSide, flatShading: false,
  })
  meshObj = new THREE.Mesh(g, mat)
  scene.add(meshObj)
}

function frameCamera() {
  const b = props.mesh.bounds
  const size = Math.max(
    b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2], 1
  )
  const d = size * 2.2
  camera.position.set(d * 0.7, d * 0.5, d)
  camera.near = size / 100; camera.far = size * 20
  camera.updateProjectionMatrix()
  controls.target.set(0, 0, 0)
  controls.update()
}

function animate() {
  controls.update()
  renderer.render(scene, camera)
  raf = requestAnimationFrame(animate)
}

function onResize() {
  if (!host.value) return
  const w = host.value.clientWidth, h = host.value.clientHeight
  camera.aspect = w / h; camera.updateProjectionMatrix()
  renderer.setSize(w, h)
}

function resetView() { frameCamera() }

watch(() => props.mesh, () => { buildMesh(); frameCamera() })
watch(() => props.wireframe, (v) => { if (meshObj) meshObj.material.wireframe = v })

onMounted(init)
onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf)
  if (ro) ro.disconnect()
  if (controls) controls.dispose()
  if (meshObj) { meshObj.geometry.dispose(); meshObj.material.dispose() }
  if (renderer) { renderer.dispose(); renderer.domElement.remove() }
})

defineExpose({ resetView })
</script>

<template>
  <div class="vol3d viewport">
    <div ref="host" class="host"></div>
    <button class="btn btn-sm reset" @click="resetView">⤢ Reset view</button>
  </div>
</template>

<style scoped>
.vol3d { position: relative; width: 100%; height: 100%; min-height: 420px; }
.host { width: 100%; height: 100%; }
.reset { position: absolute; top: 12px; right: 12px; }
</style>
