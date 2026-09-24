import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useGcsStore } from '../src/stores/gcs'
import MonitorView from '../src/views/MonitorView.vue'
import WorkbenchView from '../src/views/WorkbenchView.vue'

const apiMocks = vi.hoisted(() => ({
  abort: vi.fn(),
  basicCommand: vi.fn(),
  formationCommand: vi.fn(),
  resume: vi.fn(),
  workbenchCommand: vi.fn(),
}))

vi.mock('../src/api', () => ({ api: apiMocks }))
vi.mock('../src/components/MapPanel.vue', () => ({
  default: { template: '<div />' },
}))

function response(locallyDispatched: boolean, message: string) {
  return {
    locally_dispatched: locallyDispatched,
    message,
    dispatches: [{
      targets: [{
        host: '127.0.0.1',
        port: 57001,
        sent: locallyDispatched,
        error: locallyDispatched ? null : 'send failed',
      }],
    }],
  }
}

function button(wrapper: VueWrapper, label: string) {
  const match = wrapper.findAll('button').find((item) => item.text() === label)
  if (!match) throw new Error(`Button not found: ${label}`)
  return match
}

describe('command result toasts', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('uses a concise dispatched toast and keeps partial-send detail on Monitor', async () => {
    localStorage.setItem('gcs.monitor.group', '1')
    const store = useGcsStore()
    store.formations.members[1] = [1]
    apiMocks.basicCommand
      .mockResolvedValueOnce(response(
        true,
        '本机已尝试广播指令；该结果不代表无人机已收到或执行。',
      ))
      .mockResolvedValueOnce(response(false, '本机发送失败'))
    const wrapper = shallowMount(MonitorView)

    await button(wrapper, '起飞').trigger('click')
    await flushPromises()
    expect(store.toasts.at(-1)).toMatchObject({
      kind: 'success',
      text: '起飞已下发',
    })
    expect(store.toasts.at(-1)?.text).not.toContain('不代表')

    await button(wrapper, '返航 RTL').trigger('click')
    await flushPromises()
    expect(store.toasts.at(-1)).toMatchObject({
      kind: 'error',
      text: '本机发送失败（本机发送 0/1）',
    })

    apiMocks.resume.mockResolvedValueOnce({
      locally_dispatched: false,
      message: '本地指令阻止已解除；恢复操作不会发送 UDP。',
      dispatches: [],
    })
    store.commandBlocked = true
    await flushPromises()
    await button(wrapper, '恢复发令').trigger('click')
    await flushPromises()
    expect(store.toasts.at(-1)).toMatchObject({
      kind: 'success',
      text: '恢复发令已完成',
    })

    wrapper.unmount()
  })

  it('uses a concise workbench success toast without hiding send failures', async () => {
    const store = useGcsStore()
    apiMocks.workbenchCommand
      .mockResolvedValueOnce(response(
        true,
        '本机已尝试广播 Workbench 指令；该结果不代表无人机已收到或执行。',
      ))
      .mockResolvedValueOnce(response(false, 'Workbench 发送失败'))
    const wrapper = shallowMount(WorkbenchView)

    await button(wrapper, '上传 VO Cmd').trigger('click')
    await flushPromises()
    expect(store.toasts.at(-1)).toMatchObject({
      kind: 'success',
      text: 'VO 指令已下发',
    })
    expect(store.toasts.at(-1)?.text).not.toContain('不代表')

    await button(wrapper, '上传 Mission Cmd').trigger('click')
    await flushPromises()
    expect(store.toasts.at(-1)).toMatchObject({
      kind: 'error',
      text: 'Workbench 发送失败（本机发送 0/1）',
    })

    wrapper.unmount()
  })
})
