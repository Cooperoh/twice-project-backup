import { createRouter, createWebHashHistory } from 'vue-router'

import FormationView from '../views/FormationView.vue'
import MonitorView from '../views/MonitorView.vue'
import WorkbenchView from '../views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'monitor',
      component: MonitorView,
      meta: { title: 'Monitor' },
    },
    {
      path: '/formation',
      name: 'formation',
      component: FormationView,
      meta: { title: 'Formation' },
    },
    {
      path: '/workbench',
      name: 'workbench',
      component: WorkbenchView,
      meta: { title: 'Workbench' },
    },
    {
      path: '/earth',
      name: 'earth',
      component: () => import('../views/EarthView.vue'),
      meta: { title: 'Earth' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.afterEach((route) => {
  document.title = `${String(route.meta.title ?? 'GCS')} · Ground Control Panel`
  localStorage.setItem('gcs.lastRoute', route.fullPath)
})

export default router
