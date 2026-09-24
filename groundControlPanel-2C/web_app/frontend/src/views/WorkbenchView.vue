<script setup lang="ts">
import { computed, ref } from 'vue'

import { api } from '../api'
import { useGcsStore } from '../stores/gcs'
import type { CommandResponse } from '../types'
import { errorMessage } from '../utils/format'

const store = useGcsStore()
const droneId = ref(1)
const busyCommand = ref<string | null>(null)

const groupZeroMembers = computed(() => store.formations.members[0] ?? [])
const controlsDisabled = computed(() => store.commandBlocked || busyCommand.value !== null)
const successMessages: Record<string, string> = {
  'single-dubins': '随机游走已下发',
  'group-dubins': '随机游走已下发',
  'global-dubins': 'Dubins 指令已下发',
  vo: 'VO 指令已下发',
  mission: 'Mission 指令已下发',
}

function reportDispatch(response: CommandResponse, successMessage: string): void {
  const targets = response.dispatches.flatMap((dispatch) => dispatch.targets)
  if (response.locally_dispatched) {
    store.notify(successMessage, 'success')
    return
  }
  const sent = targets.filter((target) => target.sent).length
  const suffix = targets.length ? `（本机发送 ${sent}/${targets.length}）` : ''
  store.notify(`${response.message}${suffix}`, 'error')
}

async function runCommand(
  key: string,
  command: 'test_dubins' | 'test_vo' | 'mission',
  targets?: number[],
): Promise<void> {
  if (controlsDisabled.value) return
  busyCommand.value = key
  try {
    reportDispatch(
      await api.workbenchCommand(command, targets),
      successMessages[key] ?? 'Workbench 指令已下发',
    )
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  } finally {
    busyCommand.value = null
  }
}

function runSingleRandomWalk(): void {
  const id = Number(droneId.value)
  if (!Number.isInteger(id) || id < 1 || id > 24) {
    store.notify('无人机 ID 必须是 1～24 的整数。', 'error')
    return
  }
  void runCommand('single-dubins', 'test_dubins', [id])
}

function runGroupZeroRandomWalk(): void {
  if (!groupZeroMembers.value.length) {
    store.notify('编队 0 当前没有可执行随机游走的无人机。', 'error')
    return
  }
  void runCommand('group-dubins', 'test_dubins', [...groupZeroMembers.value])
}

function toggleObstacles(): void {
  store.setObstaclesVisible(!store.obstaclesVisible)
  store.notify(
    store.obstaclesVisible ? 'Monitor 地图已显示预设障碍圆。' : 'Monitor 地图已隐藏预设障碍圆。',
    'success',
  )
}
</script>

<template>
  <section class="workbench-page">
    <header class="page-heading">
      <div>
        <span class="eyebrow">ALGORITHM WORKBENCH</span>
        <h1>算法开发与验证</h1>
        <p>测试指令仍通过完整的 24 端口 UDP 广播链路发送；本页只报告本机发送结果，不代表无人机已执行。</p>
      </div>
      <div class="safety-note">
        <span>LOCAL SEND</span>
        <strong>≠ DEVICE ACK</strong>
      </div>
    </header>

    <div class="workbench-grid">
      <article class="panel tool-card random-card">
        <header class="tool-header">
          <span class="tool-index">01</span>
          <div>
            <h2>随机游走</h2>
            <p>向指定目标发送带 targets 的 test_dubins。</p>
          </div>
          <code>test_dubins</code>
        </header>
        <div class="tool-body random-body">
          <label class="field-label">
            无人机 ID
            <input v-model.number="droneId" class="field id-input" type="number" min="1" max="24" step="1" :disabled="controlsDisabled" />
          </label>
          <button class="button" type="button" :disabled="controlsDisabled" @click="runSingleRandomWalk">
            {{ busyCommand === 'single-dubins' ? '正在发送…' : '启动单机随机游走' }}
          </button>
          <div class="tool-divider" />
          <div class="group-summary">
            <strong>编队 0</strong>
            <span>{{ groupZeroMembers.length ? groupZeroMembers.map((id) => `#${id}`).join(' · ') : '暂无成员' }}</span>
          </div>
          <button class="button button-secondary" type="button" :disabled="controlsDisabled || !groupZeroMembers.length" @click="runGroupZeroRandomWalk">
            {{ busyCommand === 'group-dubins' ? '正在发送…' : '全部启动（编队 0）' }}
          </button>
        </div>
      </article>

      <article class="panel tool-card">
        <header class="tool-header">
          <span class="tool-index">02</span>
          <div>
            <h2>Dubins 测试</h2>
            <p>发送不带目标列表的全局测试命令。</p>
          </div>
          <code>test_dubins</code>
        </header>
        <div class="tool-body">
          <div class="payload-preview">
            <span>PAYLOAD</span>
            <code>{ "cmd": "test_dubins" }</code>
          </div>
          <button class="button" type="button" :disabled="controlsDisabled" @click="runCommand('global-dubins', 'test_dubins')">
            {{ busyCommand === 'global-dubins' ? '正在发送…' : '上传 Dubins Cmd' }}
          </button>
        </div>
      </article>

      <article class="panel tool-card">
        <header class="tool-header">
          <span class="tool-index">03</span>
          <div>
            <h2>VO 测试</h2>
            <p>运行速度障碍算法测试入口。</p>
          </div>
          <code>test_vo</code>
        </header>
        <div class="tool-body">
          <div class="payload-preview">
            <span>PAYLOAD</span>
            <code>{ "cmd": "test_vo" }</code>
          </div>
          <button class="button" type="button" :disabled="controlsDisabled" @click="runCommand('vo', 'test_vo')">
            {{ busyCommand === 'vo' ? '正在发送…' : '上传 VO Cmd' }}
          </button>
        </div>
      </article>

      <article class="panel tool-card">
        <header class="tool-header">
          <span class="tool-index">04</span>
          <div>
            <h2>Mission 指令</h2>
            <p>触发无人机端 Mission 命令处理入口。</p>
          </div>
          <code>mission</code>
        </header>
        <div class="tool-body">
          <div class="payload-preview">
            <span>PAYLOAD</span>
            <code>{ "cmd": "mission" }</code>
          </div>
          <button class="button" type="button" :disabled="controlsDisabled" @click="runCommand('mission', 'mission')">
            {{ busyCommand === 'mission' ? '正在发送…' : '上传 Mission Cmd' }}
          </button>
        </div>
      </article>

      <article class="panel tool-card obstacle-card">
        <header class="tool-header">
          <span class="tool-index">05</span>
          <div>
            <h2>Monitor 障碍区</h2>
            <p>在 Monitor 地图显示配置中的预设障碍圆，仅影响当前浏览器。</p>
          </div>
          <code>LOCAL</code>
        </header>
        <div class="tool-body obstacle-body">
          <div class="obstacle-list">
            <div v-for="obstacle in store.config.obstacles" :key="obstacle.id">
              <span>{{ obstacle.id }}</span>
              <strong>{{ obstacle.radius_m.toFixed(0) }} m</strong>
            </div>
          </div>
          <button class="button" :class="store.obstaclesVisible ? 'button-secondary' : ''" type="button" @click="toggleObstacles">
            {{ store.obstaclesVisible ? '隐藏障碍圆' : `显示 ${store.config.obstacles.length} 个障碍圆` }}
          </button>
        </div>
      </article>
    </div>

    <footer class="workbench-footer">
      <span>UDP {{ store.udp.sender_ready ? '发送端已就绪' : '发送端不可用' }}</span>
      <span>指令不自动重试</span>
      <span>急停状态下测试指令禁用</span>
    </footer>
  </section>
</template>

<style scoped>
.workbench-page {
  display: grid;
  gap: 15px;
}

.page-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 6px 3px 5px;
}

.eyebrow {
  color: var(--blue);
  font: 800 var(--font-size-caption)/1 ui-monospace, monospace;
  letter-spacing: .18em;
}

.page-heading h1 {
  margin: 6px 0 4px;
  color: var(--ink);
  font-size: var(--font-size-page-title);
  letter-spacing: -.02em;
}

.page-heading p {
  max-width: 760px;
  margin: 0;
  color: var(--muted);
  font-size: var(--font-size-body);
}

.safety-note {
  display: grid;
  gap: 4px;
  padding: 10px 13px;
  color: #8b5700;
  border: 1px solid #e1c47b;
  border-radius: 5px;
  background: #fff6dc;
  font: 700 var(--font-size-caption)/1 ui-monospace, monospace;
  text-align: right;
}

.safety-note strong { font-size: var(--font-size-small); }

.workbench-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.tool-card {
  display: grid;
  min-height: 215px;
  grid-template-rows: auto 1fr;
  overflow: hidden;
}

.random-card { grid-column: 1 / -1; min-height: 190px; }
.obstacle-card { grid-column: 1 / -1; }

.tool-header {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 12px;
  padding: 13px 15px;
  color: #fff;
  background: #12213a;
}

.tool-index {
  color: #639eea;
  font: 800 var(--font-size-small)/1 ui-monospace, monospace;
}

.tool-header h2 { margin: 0 0 3px; font-size: var(--font-size-heading); }
.tool-header p { margin: 0; color: #a4b5cb; font-size: var(--font-size-meta); }
.tool-header > code {
  padding: 4px 6px;
  color: #77bcff;
  border: 1px solid #36587f;
  border-radius: 3px;
  background: rgb(23 104 229 / 10%);
  font-size: var(--font-size-caption);
}

.tool-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 20px;
}

.random-body {
  display: grid;
  grid-template-columns: auto auto 1px 1fr auto;
  justify-content: start;
}

.id-input { width: 105px; }

.tool-divider {
  width: 1px;
  height: 54px;
  background: var(--line);
}

.group-summary {
  display: grid;
  min-width: 160px;
  gap: 5px;
}

.group-summary strong { font-size: var(--font-size-body); }
.group-summary span { overflow: hidden; color: var(--muted); font: 600 var(--font-size-meta)/1.4 ui-monospace, monospace; text-overflow: ellipsis; white-space: nowrap; }

.payload-preview {
  display: grid;
  gap: 7px;
}

.payload-preview span { color: var(--muted); font: 800 var(--font-size-caption)/1 ui-monospace, monospace; letter-spacing: .1em; }
.payload-preview code { color: #315070; font: 600 var(--font-size-small)/1.4 ui-monospace, monospace; }

.obstacle-body { align-items: flex-end; }

.obstacle-list {
  display: grid;
  flex: 1;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.obstacle-list div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--red);
  border-radius: 4px;
  background: var(--surface-soft);
}

.obstacle-list span { color: var(--muted); font: 600 var(--font-size-meta)/1 ui-monospace, monospace; }
.obstacle-list strong { color: var(--red); font: 800 var(--font-size-meta)/1 ui-monospace, monospace; }

.workbench-footer {
  display: flex;
  gap: 18px;
  padding: 2px 3px;
  color: var(--muted);
  font: 600 var(--font-size-caption)/1.4 ui-monospace, monospace;
}

.workbench-footer span::before {
  display: inline-block;
  width: 5px;
  height: 5px;
  margin-right: 6px;
  content: "";
  border-radius: 50%;
  background: #8b99ad;
}

@media (max-width: 900px) {
  .workbench-grid { grid-template-columns: 1fr; }
  .random-card,
  .obstacle-card { grid-column: auto; }
  .random-body { grid-template-columns: 1fr auto; }
  .random-body .tool-divider { display: none; }
  .page-heading { align-items: flex-start; flex-direction: column; }
  .obstacle-body { align-items: stretch; flex-direction: column; }
}

@media (max-width: 600px) {
  .random-body { display: flex; align-items: stretch; flex-direction: column; }
  .tool-body { align-items: stretch; flex-direction: column; }
  .obstacle-list { grid-template-columns: 1fr; }
  .workbench-footer { flex-direction: column; gap: 5px; }
}
</style>
