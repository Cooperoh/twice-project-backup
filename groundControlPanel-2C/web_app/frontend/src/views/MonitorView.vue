<script setup lang="ts">
import {
  computed,
  ref,
  watch,
} from 'vue'

import { api } from '../api'
import MapPanel from '../components/MapPanel.vue'
import { useGcsStore } from '../stores/gcs'
import type { CommandResponse, GroupId, LogEntry } from '../types'
import { GROUP_IDS } from '../types'
import {
  displayNumber,
  errorMessage,
  FLIGHT_CONTROL_LABELS,
  formationError,
  localTime,
  rowSeverity,
  storedOptionalInteger,
  TELEMETRY_LABELS,
} from '../utils/format'

const store = useGcsStore()
const storedGroup = storedOptionalInteger(localStorage.getItem('gcs.monitor.group'))
const storedFocus = storedOptionalInteger(localStorage.getItem('gcs.monitor.focus'))

const selectedGroup = ref<GroupId | null>(
  storedGroup !== null && GROUP_IDS.includes(storedGroup as GroupId)
    ? storedGroup as GroupId
    : null,
)
const focusId = ref<number | null>(storedFocus !== null && storedFocus > 0 ? storedFocus : null)
const showTracks = ref(localStorage.getItem('gcs.monitor.showTracks') !== 'false')
const showGoto = ref(localStorage.getItem('gcs.monitor.showGoto') !== 'false')
const idDescending = ref(localStorage.getItem('gcs.monitor.idDescending') === 'true')
const formType = ref(1)
const spacing = ref(2000)
const sending = ref(false)
const logScroller = ref<HTMLElement | null>(null)
const logScrollTop = ref(0)
const logKeys = new WeakMap<LogEntry, number>()
let nextLogKey = 0
const LOG_ROW_HEIGHT = 28
const LOG_OVERSCAN_ROWS = 12
const LOG_VISIBLE_ROWS = 32
const visibleLogStart = computed(() => Math.max(
  0,
  Math.floor(logScrollTop.value / LOG_ROW_HEIGHT) - LOG_OVERSCAN_ROWS,
))
const visibleLogs = computed(() => store.logs.slice(
  visibleLogStart.value,
  visibleLogStart.value + LOG_VISIBLE_ROWS + LOG_OVERSCAN_ROWS * 2,
))
const logSpacerHeight = computed(() => `${store.logs.length * LOG_ROW_HEIGHT}px`)
const logWindowOffset = computed(() => `${visibleLogStart.value * LOG_ROW_HEIGHT}px`)
const groupLabels: Record<GroupId, string> = {
  0: '编队 0',
  1: '编队 1',
  2: '编队 2',
  3: '编队 3',
}

const displayDrones = computed(() => {
  const result = [...store.sortedDrones]
  return idDescending.value ? result.reverse() : result
})
const selectedGroupMembers = computed(() => selectedGroup.value === null
  ? []
  : store.formations.members[selectedGroup.value] ?? [])
const selectedGroupReady = computed(() => selectedGroup.value !== null && selectedGroupMembers.value.length > 0)
const controlsDisabled = computed(() => store.commandBlocked || sending.value)
const showErrors = computed(() => store.activeFormations.length > 0)

watch(
  () => store.formationSettings,
  (settings) => {
    formType.value = settings.form_type
    spacing.value = settings.spacing
  },
  { immediate: true, deep: true },
)
watch(selectedGroup, (value) => localStorage.setItem('gcs.monitor.group', value === null ? '' : String(value)))
watch(focusId, (value) => localStorage.setItem('gcs.monitor.focus', value === null ? '' : String(value)))
watch(showTracks, (value) => localStorage.setItem('gcs.monitor.showTracks', String(value)))
watch(showGoto, (value) => localStorage.setItem('gcs.monitor.showGoto', String(value)))
watch(idDescending, (value) => localStorage.setItem('gcs.monitor.idDescending', String(value)))
watch(
  () => store.knownDroneIds,
  (ids) => {
    if (focusId.value !== null && !ids.includes(focusId.value)) focusId.value = null
  },
)
watch(
  () => store.logs.at(-1),
  () => {
    const scroller = logScroller.value
    if (!scroller) return
    const bottom = Math.max(0, scroller.scrollHeight - scroller.clientHeight)
    if (Math.abs(scroller.scrollTop - bottom) > 1) scroller.scrollTop = bottom
    logScrollTop.value = bottom
  },
  { flush: 'post' },
)

function logKey(entry: LogEntry): number {
  const existing = logKeys.get(entry)
  if (existing !== undefined) return existing
  const key = ++nextLogKey
  logKeys.set(entry, key)
  return key
}

function onLogScroll(): void {
  logScrollTop.value = logScroller.value?.scrollTop ?? 0
}

function reportDispatch(response: CommandResponse, successMessage: string): void {
  const targets = response.dispatches.flatMap((dispatch) => dispatch.targets)
  if (!targets.length) {
    store.notify(successMessage, 'success')
    return
  }
  if (response.locally_dispatched) {
    store.notify(successMessage, 'success')
    return
  }
  const sent = targets.filter((target) => target.sent).length
  store.notify(`${response.message}（本机发送 ${sent}/${targets.length}）`, 'error')
}

async function withSending(
  action: () => Promise<CommandResponse>,
  successMessage: string,
): Promise<void> {
  if (sending.value) return
  sending.value = true
  try {
    reportDispatch(await action(), successMessage)
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  } finally {
    sending.value = false
  }
}

function dispatchBasic(command: 'takeoff' | 'rtl' | 'land'): void {
  if (selectedGroup.value === null) {
    store.notify('请先选择控制目标编队。', 'error')
    return
  }
  if (!selectedGroupMembers.value.length) {
    store.notify(`${groupLabels[selectedGroup.value]} 暂无无人机。`, 'error')
    return
  }
  const successMessages = {
    takeoff: '起飞已下发',
    rtl: '返航已下发',
    land: '降落已下发',
  } as const
  void withSending(
    () => api.basicCommand(command, selectedGroup.value as GroupId),
    successMessages[command],
  )
}

async function saveSettings(silent = false): Promise<boolean> {
  if (![1, 2, 3].includes(formType.value) || !Number.isFinite(spacing.value) || spacing.value <= 0) {
    store.notify('请选择有效编队类型，并输入大于 0 的间距。', 'error')
    return false
  }
  try {
    const settings = await api.updateFormationSettings({ form_type: formType.value, spacing: spacing.value })
    store.formationSettings = settings
    if (!silent) store.notify('编队参数已保存。', 'success')
    return true
  } catch (error) {
    store.notify(errorMessage(error), 'error')
    return false
  }
}

async function dispatchFormation(): Promise<void> {
  if (selectedGroup.value === null || !selectedGroupMembers.value.length) {
    store.notify('请选择包含无人机的目标编队。', 'error')
    return
  }
  if (!await saveSettings(true)) return
  await withSending(
    () => api.formationCommand(selectedGroup.value as GroupId, {
      form_type: formType.value,
      spacing: spacing.value,
    }),
    '编队指令已下发',
  )
}

async function abortAll(): Promise<void> {
  if (sending.value || store.commandBlocked) return
  store.commandBlocked = true
  store.activeFormations = []
  sending.value = true
  try {
    reportDispatch(await api.abort(), '急停已下发')
  } catch (error) {
    store.notify(`急停请求结果不明：${errorMessage(error)}。本地界面继续保持阻止状态。`, 'error')
  } finally {
    sending.value = false
  }
}

async function resumeCommands(): Promise<void> {
  if (sending.value) return
  await withSending(() => api.resume(), '恢复发令已完成')
}

async function clearTracks(): Promise<void> {
  try {
    await api.clearTracks()
    store.notify('历史轨迹已清空。', 'success')
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  }
}

async function clearGotoTargets(): Promise<void> {
  try {
    await api.clearGotoTargets()
    store.drones = Object.fromEntries(Object.entries(store.drones).map(([id, state]) => {
      const clean = { ...state }
      delete clean.goto_lat
      delete clean.goto_lon
      return [id, clean]
    }))
    store.notify('期望点已清除。', 'success')
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  }
}

async function clearLogs(): Promise<void> {
  try {
    await api.clearLogs()
    store.logs = []
    store.notify('事件日志已清除。', 'success')
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  }
}

async function exportLogs(): Promise<void> {
  try {
    await api.downloadVisibleLogs(store.logs)
    store.notify('日志文件已生成。', 'success')
  } catch (error) {
    store.notify(errorMessage(error), 'error')
  }
}
</script>

<template>
  <section class="monitor-grid">
    <div class="monitor-left">
      <article class="panel map-panel">
        <header class="panel-header map-toolbar">
          <h1 class="panel-title">Flight Map</h1>
          <div class="map-tools">
            <label class="compact-field">
              <span>跟随</span>
              <select v-model.number="focusId" class="field field-compact">
                <option :value="null">不跟随</option>
                <option v-for="id in store.knownDroneIds" :key="id" :value="id">无人机 #{{ id }}</option>
              </select>
            </label>
            <label class="check-control">
              <input v-model="showGoto" type="checkbox" />
              期望点
            </label>
            <label class="check-control">
              <input v-model="showTracks" type="checkbox" />
              轨迹
            </label>
            <button class="button button-secondary button-small" type="button" @click="clearGotoTargets">清除期望点</button>
            <button class="button button-secondary button-small" type="button" @click="clearTracks">清空轨迹</button>
          </div>
        </header>
        <MapPanel
          :drones="displayDrones"
          :track-session="store.trackSession"
          :track-appends="store.lastTrackAppends"
          :track-revision="store.trackRevision"
          :trajectories="store.trajectories"
          :config="store.config"
          :focus-id="focusId"
          :show-tracks="showTracks"
          :show-goto="showGoto"
          :obstacles="store.config.obstacles"
          :show-obstacles="store.obstaclesVisible"
        />
      </article>

      <article class="panel command-panel">
        <header class="panel-header">
          <h2 class="panel-title">Flight Control</h2>
          <span class="panel-meta">
            {{ selectedGroup === null ? '未选择目标' : `${groupLabels[selectedGroup]} · ${selectedGroupMembers.length} 架` }}
          </span>
        </header>
        <div class="command-body">
          <fieldset class="target-groups" :disabled="sending">
            <legend>控制目标</legend>
            <label v-for="groupId in GROUP_IDS" :key="groupId" class="target-option">
              <input v-model="selectedGroup" type="radio" name="group" :value="groupId" />
              <span>
                <strong>{{ groupLabels[groupId] }}</strong>
                <small>{{ store.formations.members[groupId]?.length ?? 0 }} 架</small>
              </span>
            </label>
          </fieldset>

          <div class="flight-actions">
            <button class="button" type="button" :disabled="controlsDisabled || !selectedGroupReady" @click="dispatchBasic('takeoff')">起飞</button>
            <button class="button button-secondary" type="button" :disabled="controlsDisabled || !selectedGroupReady" @click="dispatchBasic('rtl')">返航 RTL</button>
            <button class="button button-secondary" type="button" :disabled="controlsDisabled || !selectedGroupReady" @click="dispatchBasic('land')">降落</button>
            <button class="button button-danger" type="button" :disabled="sending || store.commandBlocked" @click="abortAll">急停</button>
            <button class="button button-secondary" type="button" :disabled="sending || !store.commandBlocked" @click="resumeCommands">恢复发令</button>
          </div>

          <div class="formation-controls">
            <label class="field-label">
              编队类型
              <select v-model.number="formType" class="field" :disabled="controlsDisabled">
                <option :value="1">三角编队</option>
                <option :value="2">横向一线</option>
                <option :value="3">纵向一线</option>
              </select>
            </label>
            <label class="field-label">
              间距（米）
              <input v-model.number="spacing" class="field spacing-field" type="number" min="0.1" step="0.1" :disabled="controlsDisabled" />
            </label>
            <button class="button button-secondary" type="button" :disabled="controlsDisabled" @click="saveSettings(false)">保存参数</button>
            <button class="button" type="button" :disabled="controlsDisabled || !selectedGroupReady" @click="dispatchFormation">下发编队</button>
          </div>
        </div>
      </article>
    </div>

    <aside class="monitor-right">
      <article class="panel log-panel">
        <header class="panel-header">
          <h2 class="panel-title">Event Log</h2>
          <div class="panel-actions">
            <span class="panel-meta">{{ store.logs.length }} 条</span>
            <button class="button button-secondary button-small" type="button" @click="clearLogs">清除</button>
            <button class="button button-secondary button-small" type="button" @click="exportLogs">导出 TXT</button>
          </div>
        </header>
          <div ref="logScroller" class="log-stream" @scroll="onLogScroll">
            <div v-if="!store.logs.length" class="empty-state">等待事件日志…</div>
            <div v-else class="log-virtual-spacer" :style="{ height: logSpacerHeight }">
              <div class="log-virtual-window" :style="{ transform: `translateY(${logWindowOffset})` }">
                <div v-for="entry in visibleLogs" :key="logKey(entry)" class="log-line">
                  <time>{{ localTime(entry.timestamp) }}</time>
                  <span :title="entry.text">{{ entry.text }}</span>
                </div>
              </div>
            </div>
          </div>
      </article>

      <article class="panel telemetry-panel">
        <header class="panel-header">
          <h2 class="panel-title">Telemetry</h2>
          <button class="sort-button" type="button" @click="idDescending = !idDescending">
            ID {{ idDescending ? 'DESC ↓' : 'ASC ↑' }}
          </button>
        </header>
        <div class="table-scroll">
          <table class="telemetry-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>标签</th>
                <th>速度</th>
                <th>航向</th>
                <th>误差</th>
                <th>遥测</th>
                <th>飞控</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!displayDrones.length">
                <td colspan="7"><div class="empty-state">尚未发现无人机</div></td>
              </tr>
              <tr
                v-for="drone in displayDrones"
                :key="drone.id"
                :class="`row-${rowSeverity(drone)}`"
              >
                <td class="id-cell">#{{ drone.id }}</td>
                <td>{{ drone.tag || `DRONE${drone.id}` }}</td>
                <td class="numeric">{{ displayNumber(drone.speed, 1) }}</td>
                <td class="numeric">{{ displayNumber(drone.heading, 0) }}</td>
                <td class="numeric">{{ formationError(drone, showErrors) }}</td>
                <td><span class="state-text" :data-state="drone.telemetry_status">{{ TELEMETRY_LABELS[drone.telemetry_status ?? ''] ?? '断开' }}</span></td>
                <td><span class="state-text" :data-state="drone.flight_control_status">{{ FLIGHT_CONTROL_LABELS[drone.flight_control_status ?? ''] ?? '断开' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>
    </aside>
  </section>
</template>

<style scoped>
.monitor-grid {
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(390px, 2fr);
  grid-template-rows: minmax(0, 1fr);
  gap: 14px;
  height: max(700px, calc(100dvh - 105px));
  min-height: 0;
}

.monitor-left,
.monitor-right {
  display: grid;
  min-width: 0;
  min-height: 0;
  gap: 14px;
}

.monitor-left { grid-template-rows: minmax(480px, 1fr) auto; }
.monitor-right { grid-template-rows: minmax(260px, .85fr) minmax(310px, 1.15fr); }

.map-panel,
.log-panel,
.telemetry-panel {
  min-height: 0;
  overflow: hidden;
}

.map-panel { display: grid; grid-template-rows: auto 1fr; }
.map-toolbar { flex-wrap: wrap; }
.map-tools,
.panel-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.compact-field,
.check-control {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}

.check-control input { accent-color: var(--blue); }
.field-compact { min-height: 32px; padding: 4px 7px; }

.command-body {
  display: grid;
  grid-template-columns: minmax(250px, .9fr) minmax(280px, 1fr);
  gap: 13px 18px;
  padding: 13px;
}

.target-groups {
  display: grid;
  grid-row: 1 / span 2;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-content: start;
  gap: 7px;
  margin: 0;
  padding: 0;
  border: 0;
}

.target-groups legend {
  grid-column: 1 / -1;
  margin-bottom: 5px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}

.target-option {
  position: relative;
  display: block;
}

.target-option input {
  position: absolute;
  opacity: 0;
}

.target-option span {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface-soft);
  cursor: pointer;
}

.target-option input:checked + span {
  color: var(--blue-dark);
  border-color: #6ba1ed;
  background: #edf5ff;
  box-shadow: inset 3px 0 var(--blue);
}

.target-option strong { font-size: 13px; }
.target-option small { color: var(--muted); font: 600 11px/1 ui-monospace, monospace; }

.flight-actions,
.formation-controls {
  display: flex;
  align-items: flex-end;
  gap: 7px;
  flex-wrap: wrap;
}

.formation-controls {
  padding-top: 10px;
  border-top: 1px dashed var(--line);
}

.spacing-field { width: 100px; }

.log-panel,
.telemetry-panel {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.log-stream {
  position: relative;
  min-height: 0;
  overflow: auto;
  padding: 0;
  background: #101c31;
  contain: layout paint;
  scrollbar-color: #56677f #101c31;
}

.log-virtual-spacer { position: relative; width: 100%; }
.log-virtual-window { position: absolute; top: 0; left: 0; width: 100%; }

.log-line {
  display: grid;
  grid-template-columns: 66px 1fr;
  gap: 8px;
  height: 28px;
  padding: 4px 11px;
  color: #d7e1ef;
  border-bottom: 1px solid rgb(255 255 255 / 4%);
  font: 500 12px/20px ui-monospace, "Cascadia Mono", monospace;
}

.log-line:hover { background: rgb(255 255 255 / 4%); }
.log-line time { color: #6f88ab; }
.log-line span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-stream .empty-state { color: #70819a; }

.sort-button {
  padding: 4px 6px;
  color: var(--blue-dark);
  border: 0;
  background: transparent;
  font: 700 12px/1 ui-monospace, monospace;
}

.table-scroll { min-height: 0; overflow: auto; }

.telemetry-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  white-space: nowrap;
}

.telemetry-table th {
  position: sticky;
  z-index: 1;
  top: 0;
  padding: 9px 7px;
  color: #59677e;
  border-bottom: 1px solid var(--line-strong);
  background: #f1f4f8;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .04em;
}

.telemetry-table td {
  max-width: 110px;
  overflow: hidden;
  padding: 8px 7px;
  border-bottom: 1px solid #e8ecf2;
  text-align: center;
  text-overflow: ellipsis;
}

.telemetry-table tr:hover td { background: #f4f8fd; }
.telemetry-table .id-cell { color: var(--blue-dark); font-weight: 800; }
.telemetry-table .numeric { font-family: ui-monospace, "Cascadia Mono", monospace; }
.telemetry-table .row-warning { color: #8c5700; }
.telemetry-table .row-danger { color: #b51f2d; }
.telemetry-table .row-muted { color: #8993a2; }

.state-text {
  display: inline-block;
  min-width: 37px;
  padding: 3px 5px;
  border-radius: 3px;
  background: #eef2f6;
}

.state-text[data-state="normal"] { color: #087447; background: #e4f6ed; }
.state-text[data-state="weak"],
.state-text[data-state="fault"] { color: #986000; background: #fff1d4; }
.state-text[data-state="poor"],
.state-text[data-state="dead"] { color: #aa1d29; background: #ffe6e8; }

@media (max-width: 1180px) {
  .monitor-grid { height: auto; grid-template-columns: 1fr; grid-template-rows: auto; }
  .monitor-left { grid-template-rows: minmax(540px, auto) auto; }
  .monitor-right { grid-template-columns: 1fr 1.35fr; grid-template-rows: minmax(330px, 45vh); }
}

@media (max-width: 760px) {
  .map-tools { width: 100%; }
  .command-body { grid-template-columns: 1fr; }
  .target-groups { grid-row: auto; }
  .monitor-right { grid-template-columns: 1fr; grid-template-rows: 330px 360px; }
  .flight-actions .button { flex: 1 1 90px; }
  .formation-controls .field-label { flex: 1 1 130px; }
}
</style>
