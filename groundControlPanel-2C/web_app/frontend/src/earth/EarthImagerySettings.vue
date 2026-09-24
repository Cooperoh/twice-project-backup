<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { imageryPresets, imagerySource, normalizeImagery, type ImageryId, type ImagerySelection, type ImageryState } from './imageryConfig'

const props = defineProps<{ selection: ImagerySelection; state: ImageryState; running: boolean;
  onApply: (selection: ImagerySelection) => Promise<boolean> }>()
const open = ref(false)
const id = ref<ImageryId>('esri')
const url = ref('')
const maximumLevel = ref<number | string>(18)
const attribution = ref('')
const error = ref('')
const message = ref('')
const pending = ref(false)
const busy = computed(() => pending.value || props.state.status === 'loading')
const currentName = computed(() => imagerySource(props.selection).name)
const preset = computed(() => imageryPresets.find(item => item.id === id.value))
watch([id, url, maximumLevel, attribution], () => { error.value = ''; message.value = '' })
function toggle(): void {
  open.value = !open.value
  if (!open.value) return
  id.value = props.selection.id
  url.value = props.selection.url ?? ''
  maximumLevel.value = props.selection.maximumLevel ?? 18
  attribution.value = props.selection.attribution ?? ''
  error.value = ''; message.value = ''
}
async function apply(): Promise<void> {
  error.value = ''; message.value = ''
  try {
    const selection = normalizeImagery({ id: id.value, url: url.value,
      maximumLevel: maximumLevel.value === '' ? NaN : Number(maximumLevel.value), attribution: attribution.value })
    pending.value = true
    if (await props.onApply(selection)) message.value = props.running ? '影像已应用。' : '已选择，启动数字地球后加载。'
  } catch (failure) { error.value = failure instanceof Error ? failure.message : '请选择有效的影像源。' }
  finally { pending.value = false }
}
</script>

<template>
  <fieldset class="imagery-settings">
    <legend>地表影像</legend>
    <button class="imagery-toggle" type="button" aria-label="卫星影像" :aria-expanded="open" aria-controls="earth-imagery-form" @click="toggle">
      <span>卫星影像<small>{{ currentName }}</small></span><span aria-hidden="true">{{ open ? '−' : '+' }}</span>
    </button>
    <form v-if="open" id="earth-imagery-form" @submit.prevent="apply">
      <label for="earth-imagery-source">影像来源</label>
      <select id="earth-imagery-source" v-model="id" :disabled="busy">
        <option v-for="item in imageryPresets" :key="item.id" :value="item.id">{{ item.name }}</option>
        <option value="custom">自定义影像源</option>
      </select>
      <p v-if="preset">{{ preset.hint }} <a :href="preset.terms" target="_blank" rel="noopener noreferrer">来源说明</a></p>
      <template v-if="id === 'custom'">
        <label for="earth-imagery-url">卫星影像源地址</label>
        <textarea id="earth-imagery-url" v-model="url" rows="3" maxlength="4096" spellcheck="false" autocomplete="off" :disabled="busy" placeholder="https://example.com/tiles/{z}/{x}/{y}.jpg" />
        <p>支持 Web Mercator（EPSG:3857）XYZ 瓦片、TMS（用 {-y} 替代 {y}），或 ArcGIS /MapServer 服务地址。不是地图网页地址；服务须允许浏览器跨域访问。</p>
        <label for="earth-imagery-level">最大瓦片层级</label>
        <input id="earth-imagery-level" v-model="maximumLevel" type="number" min="0" max="22" step="1" :disabled="busy">
        <label for="earth-imagery-credit">数据来源署名（可选）</label>
        <input id="earth-imagery-credit" v-model="attribution" maxlength="240" :disabled="busy" placeholder="按数据提供方要求填写">
        <p>地址若含访问密钥，也会随设置保存在当前浏览器中。</p>
      </template>
      <button class="imagery-apply" type="submit" :disabled="busy">{{ busy ? '正在检查…' : running ? '应用影像' : '保存选择' }}</button>
      <p>一次显示一个卫星底图。选择保存在当前浏览器，切换不改变地形、飞机和视角。</p>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <p v-if="message" role="status">{{ message }}</p>
    </form>
    <p v-if="state.status !== 'idle'" :role="state.status === 'error' ? 'alert' : 'status'" :class="{error:state.status === 'error'}">{{ state.message }}</p>
  </fieldset>
</template>

<style scoped>
.imagery-settings { min-width: 0; border: 0; border-bottom: 1px solid #ffffff12; margin: 0 0 18px; padding: 0 0 18px; }
legend { padding: 0; color: #d2deef; font-size: 12px; margin-bottom: 12px; }
button, input, select, textarea { font: inherit; box-sizing: border-box; border: 1px solid #ffffff25; border-radius: 6px; background: #0b1421; color: #e1e9f3; padding: 8px; }
button { cursor: pointer; }
.imagery-toggle { display: flex; width: 100%; justify-content: space-between; align-items: center; text-align: left; background: #172438; font-size: 12px; }
small { display: block; color: #8e9eb4; font-size: 11px; margin-top: 5px; }
label { display: block; margin: 12px 0 6px; color: #c2d0e3; font-size: 11px; }
select, input, textarea { width: 100%; min-width: 0; font-size: 12px; }
textarea { resize: vertical; overflow-wrap: anywhere; }
p { color: #8e9eb4; font-size: 11px; line-height: 1.7; margin: 8px 0; overflow-wrap: anywhere; }
a { color: #a9d3ff; }
.imagery-apply { background: #203754; font-size: 12px; margin-top: 10px; }
.error { color: #ffb3b3; }
:disabled { opacity: .5; cursor: default; }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible { outline: 2px solid #a9d3ff; outline-offset: 2px; }
</style>
