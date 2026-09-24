<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'

import { api } from './api'
import { useGcsStore } from './stores/gcs'
import { errorMessage } from './utils/format'
import { earthStatus } from './earth/status'

const store = useGcsStore()
const router = useRouter()
const buildId = __GCS_BUILD_ID__

async function resumeCommands(): Promise<void> {
  try {
    const response = await api.resume()
    store.notify(response.message || '本地指令阻止已解除。', 'success')
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  }
}

async function retryBootstrap(): Promise<void> {
  try {
    await store.fetchBootstrap()
    store.notify('状态快照已恢复。', 'success')
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  }
}

onMounted(() => {
  const savedRoute = localStorage.getItem('gcs.lastRoute')
  const allowedRoutes = new Set(['/', '/formation', '/workbench'])
  if (
    savedRoute
    && allowedRoutes.has(savedRoute)
    && router.currentRoute.value.fullPath === '/'
  ) {
    router.replace(savedRoute)
  }
  void store.initialize()
})

onBeforeUnmount(() => store.disconnect())
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand" aria-label="Ground Control Panel">
        <span class="brand-mark">GC</span>
        <div>
          <strong>GROUND CONTROL</strong>
          <span>WEB CONSOLE</span>
        </div>
      </div>

      <nav class="main-nav" aria-label="主导航">
        <RouterLink to="/">
          <span class="nav-index">01</span>
          Monitor
        </RouterLink>
        <RouterLink to="/formation">
          <span class="nav-index">02</span>
          Formation
        </RouterLink>
        <RouterLink to="/workbench">
          <span class="nav-index">03</span>
          Workbench
        </RouterLink>
        <RouterLink to="/earth">
          <span class="nav-index">04</span>
          Earth
          <small v-if="earthStatus === 'running'" class="earth-running-badge">运行中</small>
        </RouterLink>
      </nav>

      <div class="system-status" aria-label="系统连接状态">
        <span class="build-chip" :title="`桌面安全副本构建 ${buildId}`">
          BUILD {{ buildId }}
        </span>
        <span
          class="status-chip"
          :class="store.wsConnected ? 'status-ok' : 'status-danger'"
          :title="store.wsConnected ? '实时通道已连接' : '正在自动重连'"
        >
          <i /> WS {{ store.wsConnected ? '在线' : '重连' }}
        </span>
        <span
          class="status-chip"
          :class="store.udpReady ? 'status-ok' : 'status-danger'"
          :title="store.udp.audit_last_error || store.udp.last_error || `${store.udp.bind_host}:${store.udp.bind_port}`"
        >
          <i /> UDP {{ store.udpReady ? '就绪' : '异常' }}
        </span>
      </div>
    </header>

    <div v-if="store.commandBlocked" class="emergency-banner" role="alert">
      <span class="emergency-icon">!</span>
      <div>
        <strong>急停状态 · 常规指令已阻止</strong>
        <span>飞行指令与测试指令保持禁用，恢复发令只解除地面站本地锁。</span>
      </div>
      <button class="button button-danger-outline" type="button" @click="resumeCommands">
        恢复发令
      </button>
    </div>

    <div v-if="store.stale && store.initialized" class="stale-banner" role="status">
      实时通道已中断，当前画面为最后一次状态，数据可能已过期；系统正在自动重连。
    </div>

    <div v-if="store.bootstrapError && !store.initialized" class="bootstrap-error" role="alert">
      <div>
        <strong>暂时无法读取后台状态</strong>
        <span>{{ store.bootstrapError }}</span>
      </div>
      <button class="button button-secondary" type="button" @click="retryBootstrap">重新加载</button>
    </div>

    <main class="page-stage">
      <RouterView v-slot="{ Component }">
        <KeepAlive>
          <component :is="Component" />
        </KeepAlive>
      </RouterView>
    </main>

    <div v-if="store.loading && !store.initialized" class="loading-screen" aria-live="polite">
      <span class="spinner" />
      <strong>正在连接地面站服务…</strong>
    </div>

    <div class="toast-stack" aria-live="polite">
      <button
        v-for="toast in store.toasts"
        :key="toast.id"
        class="toast"
        :class="`toast-${toast.kind}`"
        type="button"
        @click="store.dismissToast(toast.id)"
      >
        {{ toast.text }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.earth-running-badge { color: #6be2bd; font-size: 10px; white-space: nowrap; }
</style>
