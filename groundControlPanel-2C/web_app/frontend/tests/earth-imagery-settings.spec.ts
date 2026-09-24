import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import EarthImagerySettings from '../src/earth/EarthImagerySettings.vue'

describe('Earth imagery settings', () => {
  it('opens on demand and saves a preset before Earth is started', async () => {
    const onApply=vi.fn(async()=>true)
    const wrapper=mount(EarthImagerySettings,{props:{selection:{id:'esri'},state:{status:'idle',message:''},running:false,onApply}})
    expect(wrapper.find('form').exists()).toBe(false)
    await wrapper.get('button[aria-label="卫星影像"]').trigger('click')
    await wrapper.get('select').setValue('eox')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(onApply).toHaveBeenCalledWith({id:'eox'})
    expect(wrapper.text()).toContain('启动数字地球后加载')
    wrapper.unmount()
  })
  it('shows URL validation errors without attempting to change imagery', async () => {
    const onApply=vi.fn(async()=>true)
    const wrapper=mount(EarthImagerySettings,{props:{selection:{id:'esri'},state:{status:'idle',message:''},running:true,onApply}})
    await wrapper.get('button[aria-label="卫星影像"]').trigger('click')
    await wrapper.get('select').setValue('custom')
    await wrapper.get('textarea').setValue('https://example.test/map')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.get('[role="alert"]').text()).toContain('瓦片地址需包含')
    expect(onApply).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
