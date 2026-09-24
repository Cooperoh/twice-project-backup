import { describe, expect, it } from 'vitest'

import router from '../src/router'
import FormationView from '../src/views/FormationView.vue'
import MonitorView from '../src/views/MonitorView.vue'
import WorkbenchView from '../src/views/WorkbenchView.vue'


describe('application routes', () => {
  it.each([
    ['/', MonitorView],
    ['/formation', FormationView],
    ['/workbench', WorkbenchView],
  ])('statically includes %s in the main frontend bundle', (path, component) => {
    const route = router.getRoutes().find((item) => item.path === path)
    expect(route?.components?.default).toBe(component)
  })
})
