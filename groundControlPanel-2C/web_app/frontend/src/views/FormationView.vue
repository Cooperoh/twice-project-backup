<script setup lang="ts">
import Sortable, { type SortableEvent } from 'sortablejs'
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { ApiError, api } from '../api'
import { useGcsStore } from '../stores/gcs'
import type { FormationState, GroupId } from '../types'
import { GROUP_IDS } from '../types'
import { errorMessage } from '../utils/format'

const store = useGcsStore()
const groupLabels: Record<GroupId, string> = {
  0: '编队 0 · 待分配池',
  1: '编队 1',
  2: '编队 2',
  3: '编队 3',
}

const draftMembers = ref<Record<GroupId, number[]>>({ 0: [], 1: [], 2: [], 3: [] })
const draftRevision = ref(0)
const dirty = ref(false)
const publishing = ref(false)
const serverChanged = ref(false)
const zoneElements = new Map<GroupId, HTMLElement>()
const sortableInstances = new Map<GroupId, Sortable>()

const draftLeaders = computed<Record<GroupId, number | null>>(() => ({
  0: draftMembers.value[0][0] ?? null,
  1: draftMembers.value[1][0] ?? null,
  2: draftMembers.value[2][0] ?? null,
  3: draftMembers.value[3][0] ?? null,
}))
const totalAssigned = computed(() => GROUP_IDS.reduce<number>((sum, id) => sum + draftMembers.value[id].length, 0))
const canPublish = computed(() => dirty.value && !publishing.value && !store.stale)

function loadFromServer(state: FormationState = store.formations): void {
  draftRevision.value = state.revision
  draftMembers.value = {
    0: [...state.members[0]].sort((a, b) => a - b),
    1: [...state.members[1]].sort((a, b) => a - b),
    2: [...state.members[2]].sort((a, b) => a - b),
    3: [...state.members[3]].sort((a, b) => a - b),
  }
  dirty.value = false
  serverChanged.value = false
}

function groupOf(droneId: number): GroupId | null {
  return GROUP_IDS.find((groupId) => draftMembers.value[groupId].includes(droneId)) ?? null
}

function moveDrone(droneId: number, target: GroupId): void {
  if (!GROUP_IDS.includes(target)) return
  const source = groupOf(droneId)
  if (source === target) return
  const next: Record<GroupId, number[]> = {
    0: [...draftMembers.value[0]],
    1: [...draftMembers.value[1]],
    2: [...draftMembers.value[2]],
    3: [...draftMembers.value[3]],
  }
  for (const groupId of GROUP_IDS) next[groupId] = next[groupId].filter((id) => id !== droneId)
  next[target] = [...next[target], droneId].sort((a, b) => a - b)
  draftMembers.value = next
  dirty.value = true
}

function changeGroup(event: Event, droneId: number): void {
  const target = Number((event.target as HTMLSelectElement).value) as GroupId
  moveDrone(droneId, target)
}

function setZoneRef(groupId: GroupId, element: Element | null): void {
  if (element instanceof HTMLElement) zoneElements.set(groupId, element)
}

function handleSort(event: SortableEvent): void {
  const droneId = Number((event.item as HTMLElement).dataset.droneId)
  const source = Number((event.from as HTMLElement).dataset.group) as GroupId
  const target = Number((event.to as HTMLElement).dataset.group) as GroupId
  if (!Number.isInteger(droneId) || !GROUP_IDS.includes(target)) return
  if (source === target) {
    // Sortable mutates the DOM directly. Vue sees no membership change here,
    // so explicitly restore the physical DOM order through Sortable itself.
    const orderedIds = [...draftMembers.value[target]]
      .sort((a, b) => a - b)
      .map(String)
    sortableInstances.get(target)?.sort(orderedIds, true)
    return
  }
  moveDrone(droneId, target)
}

function initializeSortable(): void {
  if (sortableInstances.size || zoneElements.size !== 4) return
  for (const groupId of GROUP_IDS) {
    const element = zoneElements.get(groupId)
    if (!element) continue
    sortableInstances.set(groupId, Sortable.create(element, {
      group: 'formation-members',
      animation: 160,
      dataIdAttr: 'data-drone-id',
      ghostClass: 'drone-card-ghost',
      chosenClass: 'drone-card-chosen',
      dragClass: 'drone-card-dragging',
      draggable: '.drone-card',
      handle: '.drag-handle',
      onEnd: handleSort,
    }))
  }
}

async function publish(): Promise<void> {
  if (!canPublish.value) return
  publishing.value = true
  const payload: FormationState = {
    revision: draftRevision.value,
    members: {
      0: [...draftMembers.value[0]],
      1: [...draftMembers.value[1]],
      2: [...draftMembers.value[2]],
      3: [...draftMembers.value[3]],
    },
    leaders: { ...draftLeaders.value },
  }
  try {
    const response = await api.updateFormations(payload)
    const state = 'formations' in response ? response.formations : response
    store.formations = state
    loadFromServer(state)
    store.notify('编队调整已下发', 'success')
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      dirty.value = false
      await store.fetchBootstrap().catch(() => undefined)
      loadFromServer(store.formations)
      store.notify('编队版本已变化，本次草稿未发布；已载入后台最新分组。', 'error')
    } else {
      store.notify(errorMessage(error), 'error')
    }
  } finally {
    publishing.value = false
  }
}

watch(
  () => store.formations,
  (state) => {
    if (!dirty.value) loadFromServer(state)
    else if (state.revision !== draftRevision.value) serverChanged.value = true
  },
  { immediate: true, deep: true },
)

watch(
  () => store.knownDroneIds,
  (ids) => {
    const knownInDraft = new Set(GROUP_IDS.flatMap((groupId) => draftMembers.value[groupId]))
    const newIds = ids.filter((id) => !knownInDraft.has(id))
    if (!newIds.length) return
    draftMembers.value = {
      ...draftMembers.value,
      0: [...draftMembers.value[0], ...newIds].sort((a, b) => a - b),
    }
    dirty.value = true
    store.notify(`新发现 ${newIds.length} 架无人机，已合并到编队 0 草稿。`, 'info')
  },
  { deep: true },
)

onMounted(() => nextTick(initializeSortable))
onActivated(() => nextTick(initializeSortable))
onBeforeUnmount(() => {
  for (const instance of sortableInstances.values()) instance.destroy()
  sortableInstances.clear()
})
</script>

<template>
  <section class="formation-page">
    <header class="page-heading">
      <div>
        <span class="eyebrow">FORMATION ASSIGNMENT</span>
        <h1>编队成员管理</h1>
        <p>拖动无人机卡片，或使用卡片上的移动菜单。每个非空编队自动以最小 ID 为队长。</p>
      </div>
      <div class="heading-metrics">
        <div><strong>{{ totalAssigned }}</strong><span>已发现</span></div>
        <div><strong>r{{ draftRevision }}</strong><span>状态版本</span></div>
        <div><strong>{{ dirty ? '未发布' : '已同步' }}</strong><span>草稿状态</span></div>
      </div>
    </header>

    <div v-if="serverChanged" class="revision-alert" role="status">
      后台编队版本已更新。当前草稿仍被保留，发布时若发生版本冲突将自动载入后台最新状态。
    </div>

    <div class="formation-top-grid">
      <article v-for="groupId in ([1, 2, 3] as GroupId[])" :key="groupId" class="panel formation-zone">
        <header class="zone-header">
          <div>
            <span class="zone-id">0{{ groupId }}</span>
            <h2>{{ groupLabels[groupId] }}</h2>
          </div>
          <div class="zone-stats">
            <span>{{ draftMembers[groupId].length }} 架</span>
            <span>队长 {{ draftLeaders[groupId] === null ? '—' : `#${draftLeaders[groupId]}` }}</span>
          </div>
        </header>
        <div
          :ref="(element) => setZoneRef(groupId, element as Element | null)"
          class="drone-zone"
          :data-group="groupId"
        >
          <div v-if="!draftMembers[groupId].length" class="zone-empty">拖放无人机到此编队</div>
          <div
            v-for="droneId in draftMembers[groupId]"
            :key="droneId"
            class="drone-card"
            :data-drone-id="droneId"
          >
            <span class="drag-handle" title="拖动">⋮⋮</span>
            <div class="drone-identity">
              <strong>#{{ droneId }}</strong>
              <span>{{ store.drones[String(droneId)]?.tag || `DRONE${droneId}` }}</span>
            </div>
            <span v-if="draftLeaders[groupId] === droneId" class="leader-badge">队长</span>
            <select class="move-select" :value="groupId" title="移动到编队" @change="changeGroup($event, droneId)">
              <option v-for="target in GROUP_IDS" :key="target" :value="target">移至编队 {{ target }}</option>
            </select>
          </div>
        </div>
      </article>
    </div>

    <article class="panel formation-zone pool-zone">
      <header class="zone-header">
        <div>
          <span class="zone-id">00</span>
          <h2>{{ groupLabels[0] }}</h2>
        </div>
        <div class="zone-stats">
          <span>{{ draftMembers[0].length }} 架</span>
          <span>未参与正式编队</span>
        </div>
      </header>
      <div
        :ref="(element) => setZoneRef(0, element as Element | null)"
        class="drone-zone pool-grid"
        data-group="0"
      >
        <div v-if="!draftMembers[0].length" class="zone-empty">全部无人机均已分配</div>
        <div
          v-for="droneId in draftMembers[0]"
          :key="droneId"
          class="drone-card"
          :data-drone-id="droneId"
        >
          <span class="drag-handle" title="拖动">⋮⋮</span>
          <div class="drone-identity">
            <strong>#{{ droneId }}</strong>
            <span>{{ store.drones[String(droneId)]?.tag || `DRONE${droneId}` }}</span>
          </div>
          <select class="move-select" :value="0" title="移动到编队" @change="changeGroup($event, droneId)">
            <option v-for="target in GROUP_IDS" :key="target" :value="target">移至编队 {{ target }}</option>
          </select>
        </div>
      </div>
    </article>

    <footer class="formation-footer panel">
      <div>
        <strong>发布会一次提交四个编队</strong>
        <span>成员唯一且按 ID 排序；发布成功后，后台向对应无人机广播 config_update。</span>
      </div>
      <div class="footer-actions">
        <button class="button button-secondary" type="button" :disabled="publishing || !dirty" @click="loadFromServer()">放弃草稿</button>
        <button class="button" type="button" :disabled="!canPublish" @click="publish">
          {{ publishing ? '正在发布…' : '发布编队调整' }}
        </button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.formation-page {
  display: grid;
  gap: 14px;
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
  margin: 0;
  color: var(--muted);
  font-size: var(--font-size-body);
}

.heading-metrics {
  display: flex;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: #fff;
  box-shadow: var(--shadow);
}

.heading-metrics div {
  display: grid;
  min-width: 90px;
  gap: 3px;
  padding: 10px 13px;
  border-left: 1px solid var(--line);
  text-align: right;
}

.heading-metrics div:first-child { border-left: 0; }
.heading-metrics strong { color: var(--ink); font: 800 var(--font-size-heading)/1 ui-monospace, monospace; }
.heading-metrics span { color: var(--muted); font-size: var(--font-size-caption); }

.revision-alert {
  padding: 9px 12px;
  color: #765000;
  border: 1px solid #e6c671;
  border-radius: 5px;
  background: #fff6d7;
  font-size: var(--font-size-small);
}

.formation-top-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.formation-zone {
  min-height: 285px;
  overflow: hidden;
}

.zone-header {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 14px;
  color: #fff;
  background: linear-gradient(120deg, #152743, #0f1d36);
}

.zone-header > div:first-child {
  display: flex;
  align-items: center;
  gap: 10px;
}

.zone-id {
  display: grid;
  width: 29px;
  height: 29px;
  place-items: center;
  border: 1px solid #567aa9;
  border-radius: 4px;
  color: #8fb9f2;
  font: 800 var(--font-size-meta)/1 ui-monospace, monospace;
}

.zone-header h2 { margin: 0; font-size: var(--font-size-heading); }

.zone-stats {
  display: grid;
  gap: 3px;
  color: #b8c8dc;
  font: 600 var(--font-size-caption)/1.2 ui-monospace, monospace;
  text-align: right;
}

.drone-zone {
  display: grid;
  min-height: 226px;
  align-content: start;
  gap: 7px;
  padding: 10px;
  background:
    linear-gradient(90deg, rgb(23 104 229 / 3%) 1px, transparent 1px),
    linear-gradient(rgb(23 104 229 / 3%) 1px, transparent 1px),
    #fbfcfe;
  background-size: 20px 20px;
}

.zone-empty {
  display: grid;
  min-height: 80px;
  place-items: center;
  color: #96a0af;
  border: 1px dashed #c8d1de;
  border-radius: 5px;
  font-size: var(--font-size-small);
  pointer-events: none;
}

.drone-card {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  align-items: center;
  gap: 8px;
  min-height: 52px;
  padding: 7px 8px;
  border: 1px solid #cfdae8;
  border-left: 3px solid var(--blue);
  border-radius: 5px;
  background: #fff;
  box-shadow: 0 2px 6px rgb(15 29 54 / 5%);
}

.drag-handle {
  color: #8b98aa;
  font: 900 var(--font-size-heading)/1 ui-monospace, monospace;
  cursor: grab;
  user-select: none;
}

.drag-handle:active { cursor: grabbing; }

.drone-identity {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.drone-identity strong { color: var(--blue-dark); font: 800 var(--font-size-body)/1 ui-monospace, monospace; }
.drone-identity span { overflow: hidden; color: var(--muted); font-size: var(--font-size-caption); text-overflow: ellipsis; white-space: nowrap; }

.leader-badge {
  padding: 3px 5px;
  color: #8c5a00;
  border: 1px solid #e8c879;
  border-radius: 3px;
  background: #fff5d6;
  font-size: var(--font-size-caption);
  font-weight: 800;
}

.move-select {
  width: 32px;
  height: 32px;
  color: transparent;
  border: 1px solid #c8d2df;
  border-radius: 4px;
  background-color: #f7f9fc;
  background-image: linear-gradient(45deg, transparent 50%, #506078 50%), linear-gradient(135deg, #506078 50%, transparent 50%);
  background-position: calc(50% - 3px) 14px, calc(50% + 3px) 14px;
  background-repeat: no-repeat;
  background-size: 5px 5px, 5px 5px;
  cursor: pointer;
}

.move-select option { color: var(--ink); }

:global(.drone-card-ghost) { opacity: .28; }
:global(.drone-card-chosen) { border-color: #74a8ef; box-shadow: 0 8px 20px rgb(23 104 229 / 15%); }
:global(.drone-card-dragging) { transform: rotate(1deg); }

.pool-zone { min-height: 220px; }
.pool-zone .zone-header { background: linear-gradient(120deg, #44536a, #2e3b4f); }
.pool-grid {
  min-height: 160px;
  grid-template-columns: repeat(6, minmax(145px, 1fr));
}

.formation-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 13px 15px;
}

.formation-footer > div:first-child { display: grid; gap: 3px; }
.formation-footer strong { font-size: var(--font-size-body); }
.formation-footer span { color: var(--muted); font-size: var(--font-size-meta); }
.footer-actions { display: flex; gap: 8px; }

@media (max-width: 1200px) {
  .pool-grid { grid-template-columns: repeat(4, minmax(140px, 1fr)); }
}

@media (max-width: 900px) {
  .formation-top-grid { grid-template-columns: 1fr; }
  .formation-zone { min-height: 210px; }
  .drone-zone { min-height: 150px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pool-grid { grid-template-columns: repeat(3, minmax(140px, 1fr)); }
  .page-heading { align-items: flex-start; flex-direction: column; }
}

@media (max-width: 650px) {
  .heading-metrics { width: 100%; }
  .heading-metrics div { min-width: 0; flex: 1; }
  .drone-zone,
  .pool-grid { grid-template-columns: 1fr; }
  .formation-footer { align-items: stretch; flex-direction: column; }
  .footer-actions .button { flex: 1; }
}
</style>
