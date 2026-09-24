import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import EarthTokenSettings from '../src/earth/EarthTokenSettings.vue'
import { cesiumCredentials, type CesiumCredentialStatus } from '../src/earth/credentials'

vi.mock('../src/earth/credentials', () => ({ cesiumCredentials: {
  status: vi.fn(), save: vi.fn(), clear: vi.fn(), read: vi.fn(),
} }))
const missing: CesiumCredentialStatus = {
  configured: false, state: 'missing', message: '尚未导入', supported: true, storage_path: 'user-data/cesium-token.dat',
}
const saved: CesiumCredentialStatus = { ...missing, configured: true, state: 'saved', message: '已保存' }

describe('Earth token import UI', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(cesiumCredentials.status).mockResolvedValue(missing)
    vi.mocked(cesiumCredentials.save).mockResolvedValue(saved)
    vi.mocked(cesiumCredentials.clear).mockResolvedValue(missing)
  })

  it('only checks local status on opening, then saves, clears input and clears storage', async () => {
    const changed = vi.fn()
    const view = mount(EarthTokenSettings, { props: { onChanged: changed } })
    await flushPromises()
    expect(cesiumCredentials.read).not.toHaveBeenCalled()
    expect(cesiumCredentials.save).not.toHaveBeenCalled()
    await view.get('input[type=password]').setValue('sample.account.signature')
    await view.get('form').trigger('submit')
    await flushPromises()
    expect(cesiumCredentials.save).toHaveBeenCalledWith('sample.account.signature')
    expect((view.get('input[type=password]').element as HTMLInputElement).value).toBe('')
    expect(changed).toHaveBeenCalledOnce()
    const clear = view.findAll('button').find(button => button.text() === '清除已保存 Token')!
    await clear.trigger('click')
    await flushPromises()
    expect(cesiumCredentials.clear).toHaveBeenCalledOnce()
    expect(changed).toHaveBeenCalledTimes(2)
    expect(view.text()).toContain('仍可使用普通地球')
    view.unmount()
  })

  it('keeps the saved credential when replacement validation fails', async () => {
    vi.mocked(cesiumCredentials.status).mockResolvedValue(saved)
    vi.mocked(cesiumCredentials.save).mockRejectedValue(new Error('Token 无效'))
    const changed = vi.fn()
    const view = mount(EarthTokenSettings, { props: { onChanged: changed } })
    await flushPromises()
    await view.get('input[type=password]').setValue('invalid.account.signature')
    await view.get('form').trigger('submit')
    await flushPromises()
    expect(changed).not.toHaveBeenCalled()
    expect(view.get('[role=alert]').text()).toBe('Token 无效')
    expect(view.text()).toContain('已保存')
    view.unmount()
  })

  it('imports file contents, never persists its original path', async () => {
    const changed = vi.fn()
    const view = mount(EarthTokenSettings, { props: { onChanged: changed } })
    await flushPromises()
    const input = view.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { value: [{ size: 30, text: async () => '\ufeffsample.account.signature\r\n' }] })
    await input.trigger('change')
    await flushPromises()
    expect(cesiumCredentials.save).toHaveBeenCalledWith('sample.account.signature')
    expect(changed).toHaveBeenCalledOnce()
    view.unmount()
  })

  it('notifies the running globe even if the panel closes during saving', async () => {
    let finish!: (value: CesiumCredentialStatus) => void
    vi.mocked(cesiumCredentials.save).mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const changed = vi.fn()
    const view = mount(EarthTokenSettings, { props: { onChanged: changed } })
    await flushPromises()
    await view.get('input[type=password]').setValue('sample.account.signature')
    await view.get('form').trigger('submit')
    view.unmount()
    finish(saved)
    await flushPromises()
    expect(changed).toHaveBeenCalledOnce()
  })
})
