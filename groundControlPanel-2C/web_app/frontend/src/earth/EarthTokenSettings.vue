<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { cesiumCredentials, type CesiumCredentialStatus } from './credentials'

const props = defineProps<{ onChanged: () => void }>()
const status = ref<CesiumCredentialStatus | null>(null)
const token = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const busy = ref(false)
const message = ref('')
const failed = ref(false)
let disposed = false
const failure = (error: unknown) => error instanceof Error && error.name !== 'TimeoutError'
  && error.name !== 'TypeError' ? error.message : '连接超时或网络不可用，请确认后台已启动后重试。'

async function refresh(): Promise<void> {
  busy.value = true
  try {
    const value = await cesiumCredentials.status()
    if (!disposed) status.value = value
  } catch (error) {
    if (!disposed) { message.value = failure(error); failed.value = true }
  } finally { if (!disposed) busy.value = false }
}

async function save(value = token.value): Promise<void> {
  if (busy.value) return
  busy.value = true
  failed.value = false
  message.value = '正在验证地形权限并保存…'
  try {
    const result = await cesiumCredentials.save(value.trim().replace(/^\uFEFF/, ''))
    // Notify even if the panel closed while saving: the running globe must update.
    props.onChanged()
    if (!disposed) {
      status.value = result
      token.value = ''
      message.value = '已验证并保存，关闭软件或重启电脑后会自动读取。'
    }
  } catch (error) {
    if (!disposed) { failed.value = true; message.value = failure(error) }
  } finally { if (!disposed) busy.value = false }
}

async function importFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || busy.value) return
  try {
    if (file.size > 8192) throw new Error('文件过大，请选择只包含 Token 的文本文件。')
    const content = await file.text()
    if (!disposed) await save(content)
  } catch (error) {
    if (!disposed) { failed.value = true; message.value = failure(error) }
  } finally { input.value = '' }
}

async function clear(): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const result = await cesiumCredentials.clear()
    props.onChanged()
    if (!disposed) {
      status.value = result
      token.value = ''
      failed.value = false
      message.value = '已清除本机保存的 Token，仍可使用普通地球。'
    }
  } catch (error) {
    if (!disposed) { failed.value = true; message.value = failure(error) }
  } finally { if (!disposed) busy.value = false }
}

onMounted(() => { void refresh() })
onBeforeUnmount(() => { disposed = true; token.value = '' })
</script>

<template>
  <fieldset class="token-settings">
    <legend>Cesium Token</legend>
    <p role="status">{{ status?.message ?? '正在读取本机配置…' }}</p>
    <p>首次导入后自动记住。可跳过，继续使用无地形起伏的普通地球。</p>
    <form @submit.prevent="save()">
      <label for="earth-token">{{ status?.configured ? '替换 Token' : '输入 Token' }}</label>
      <input id="earth-token" v-model="token" type="password" autocomplete="off" spellcheck="false" maxlength="4096" placeholder="粘贴自己的 Cesium ion Token" :disabled="busy || status?.supported === false">
      <div class="token-actions">
        <button type="submit" :disabled="busy || !token.trim() || status?.supported === false">验证并保存</button>
        <button type="button" :disabled="busy || status?.supported === false" @click="fileInput?.click()">从文件导入</button>
        <button v-if="status && status.state !== 'missing'" type="button" :disabled="busy" @click="clear">清除已保存 Token</button>
      </div>
      <input ref="fileInput" class="token-file" type="file" accept=".txt,.token,text/plain" aria-label="选择 Token 文件" :disabled="busy" @change="importFile">
    </form>
    <p v-if="message" :role="failed ? 'alert' : 'status'" :class="{ 'token-error': failed }">{{ message }}</p>
    <p v-if="status?.supported === false" class="token-error">本机加密保存目前支持 Windows。</p>
    <details v-if="status"><summary>保存位置</summary><p class="token-path">{{ status.storage_path }}</p><p>使用当前 Windows 用户加密，移动地面站目录不受影响。</p></details>
  </fieldset>
</template>

<style scoped>
.token-settings { min-width: 0; border: 0; border-bottom: 1px solid #ffffff12; margin: 0 0 18px; padding: 0 0 18px; }
legend { padding: 0; color: #d2deef; font-size: 12px; margin-bottom: 12px; }
p { color: #8e9eb4; font-size: 11px; line-height: 1.7; margin: 8px 0; }
label { display: block; margin: 12px 0 6px; color: #c2d0e3; font-size: 11px; }
input[type=password] { width: 100%; box-sizing: border-box; min-height: 36px; border: 1px solid #ffffff25; border-radius: 6px; background: #0b1421; color: #e1e9f3; padding: 8px; font-size: 12px; }
.token-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 9px; }
button { border: 1px solid #ffffff25; border-radius: 6px; background: #172438; color: #d2deef; padding: 8px; font-size: 11px; cursor: pointer; }
button:disabled { opacity: .4; cursor: default; }
input:focus-visible, button:focus-visible, summary:focus-visible { outline: 2px solid #a9d3ff; outline-offset: 2px; }
.token-file { display: none; }
.token-error { color: #ffb3b3; }
summary { cursor: pointer; color: #899bb3; font-size: 11px; margin-top: 12px; }
.token-path { overflow-wrap: anywhere; }
</style>
