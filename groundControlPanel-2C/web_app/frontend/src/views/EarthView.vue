<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useGcsStore } from '../stores/gcs'
import { earthStatus } from '../earth/status'
import { EarthSession } from '../earth/session'
import EarthTokenSettings from '../earth/EarthTokenSettings.vue'
import EarthImagerySettings from '../earth/EarthImagerySettings.vue'
import { loadImagerySelection, saveImagerySelection, type ImagerySelection, type ImageryState } from '../earth/imageryConfig'
import { altitudeOverride } from '../earth/altitude'
import type { EarthDestination, EarthEffects, EarthPresentation, EarthQuality, EarthStats, EarthTerrainStatus } from '../earth/contracts'

defineOptions({ name: 'EarthView' })
const store = useGcsStore()
const root = ref<HTMLElement | null>(null)
const host = ref<HTMLElement | null>(null)
const settingsPanel = ref<HTMLElement | null>(null)
const settingsButton = ref<HTMLButtonElement | null>(null)
const settingsOpen = ref(false)
const immersive = ref(false)
const error = ref('')
const warning = ref('')
const stats = ref<EarthStats>({ drones: 0, points: 0, catchingUp: false })
const showTracks = ref(true)
const altitudeInput = ref<number | string>('')
const configuredAltitude = computed(() => altitudeOverride(altitudeInput.value))
const focus = ref('')
const quality = ref<EarthQuality>('balanced')
const terrainEnabled = ref(true)
const terrainStatus = ref<EarthTerrainStatus>('idle')
const imagery = ref(loadImagerySelection())
const imageryState = ref<ImageryState>({ status: 'idle', message: '' })
const terrainMessages: Record<EarthTerrainStatus, string> = {
  idle: '启动地球后按视野加载', off: '地形已关闭 · 光滑地球',
  loading: '正在连接在线地形…', ready: '地形已启用 · 按视野加载细节',
  error: '地形暂不可用，当前使用普通地球。请检查网络或在 Token 设置中重新导入。',
  unconfigured: '尚未导入 Token，当前使用普通地球。可在 Token 设置中导入以启用真实地形。',
}
const effects = ref<EarthEffects>({ clouds: true, satellites: true, animate: true, labels: true, labelDensity: 'detailed', boundaries: true, cumulus: true, cirrus: true, haze: true, atmosphere: true })
const presentation = ref<EarthPresentation>({ tour: false, sunlight: false, sunLongitude: 45 })
const running = computed(() => earthStatus.value === 'running')
const started = computed(() => running.value || earthStatus.value === 'loading')
const qualityHints = {
  smooth: '降低分辨率，优先操作响应。',
  balanced: '原生像素比例，兼顾清晰度与响应。',
  sharp: '高分屏优先细节，图形开销更高。',
}
const session = new EarthSession(store, {
  warning: (message) => { warning.value = message },
  error: (message) => { error.value = message },
  stats: (value) => { stats.value = value },
  tour: (active) => { presentation.value.tour = active },
  terrain: (status) => { terrainStatus.value = status },
  imagery: (state) => { imageryState.value = state },
})
void session.setImagery(imagery.value)
async function applyImagery(selection: ImagerySelection): Promise<boolean> {
  if (!await session.setImagery(selection)) return false
  imagery.value = selection
  if (!saveImagerySelection(selection)) warning.value = '影像选择本次有效，但浏览器未允许保存，刷新后会恢复默认。'
  return true
}
function start(): void { if (host.value) void session.start(host.value) }
function close(): void { session.close(); warning.value = ''; error.value = '' }
function locate(): void { focus.value = ''; session.locateAll() }
function visit(destination: EarthDestination): void { focus.value = ''; session.visit(destination) }
function follow(): void { session.follow(focus.value ? Number(focus.value) : null) }
function skyView(): void {
  presentation.value.sunlight = false
  updatePresentation()
  session.skyView()
}
function updateEffects(): void { session.setEffects(effects.value) }
function updatePresentation(): void { session.setPresentation(presentation.value) }
async function openTokenSettings(): Promise<void> {
  settingsOpen.value = true
  await nextTick()
  settingsPanel.value?.focus()
}
function toggleTour(): void {
  focus.value = ''
  session.follow(null)
  presentation.value.tour = !presentation.value.tour
  updatePresentation()
}
function toggleSunlight(): void { presentation.value.sunlight = !presentation.value.sunlight; updatePresentation() }
async function toggleSettings(): Promise<void> {
  settingsOpen.value = !settingsOpen.value
  await nextTick()
  if (settingsOpen.value) settingsPanel.value?.focus()
  else settingsButton.value?.focus()
}
async function toggleImmersive(): Promise<void> {
  try {
    if (document.fullscreenElement === root.value) await document.exitFullscreen()
    else await root.value?.requestFullscreen()
  } catch { warning.value = '当前浏览器未允许全屏，可继续使用普通视图。' }
}
function syncFullscreen(): void { immersive.value = document.fullscreenElement === root.value; session.resize() }
onMounted(() => document.addEventListener('fullscreenchange', syncFullscreen))
onActivated(() => { void nextTick(() => session.resize()) })
onDeactivated(() => {
  presentation.value.tour = false
  updatePresentation()
  if (document.fullscreenElement === root.value) void document.exitFullscreen().catch(() => {})
})
onBeforeUnmount(() => { document.removeEventListener('fullscreenchange', syncFullscreen); session.close() })
</script>

<template>
  <section ref="root" class="earth-page" aria-label="数字地球实验页" :class="{ 'is-immersive': immersive }">
    <header class="earth-header">
      <div class="earth-title">
        <span class="earth-eyebrow">EARTH / 04</span>
        <h1>数字地球<span>换个视角，探索世界。</span></h1>
      </div>
      <div class="earth-header-actions">
        <button class="earth-button" type="button" @click="openTokenSettings">Token 设置</button>
        <span class="earth-status"><i :class="{ active: running }" />{{ running ? '地球运行中' : started ? '正在加载' : '待启动' }}</span>
        <button ref="settingsButton" class="earth-button" type="button" :aria-expanded="settingsOpen" aria-controls="earth-settings" @click="toggleSettings">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 17h16M9 4v6m6 4v6" /></svg>配置
        </button>
        <button v-if="!started" class="earth-button earth-primary" type="button" @click="start">{{ earthStatus === 'error' ? '重试启动' : '启动数字地球' }}<span aria-hidden="true">↗</span></button>
        <button v-else class="earth-button earth-close" type="button" @click="close">关闭数字地球</button>
      </div>
    </header>

    <p v-if="error" class="earth-message earth-error" role="alert">启动失败：{{ error }}</p>
    <p v-if="warning" class="earth-message" role="status">{{ warning }}</p>
    <p v-if="imageryState.status === 'error' && !settingsOpen" class="earth-message" role="status">{{ imageryState.message }}</p>
    <p v-if="terrainStatus === 'error' || terrainStatus === 'unconfigured'" class="earth-message" role="status">{{ terrainMessages[terrainStatus] }}</p>

    <div class="earth-workspace" :class="{ 'with-settings': settingsOpen }">
      <div class="earth-main">
        <div class="earth-toolbar" aria-label="地球视角工具">
          <div class="earth-tool-group">
            <button class="earth-tool" type="button" :disabled="!running" @click="visit('asia')"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><ellipse cx="12" cy="12" rx="3.5" ry="8"/><path d="M4 12h16"/></svg>全球视角</button>
            <button class="earth-tool" type="button" :disabled="!running || !stats.drones" @click="locate"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="6"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4"/></svg>定位飞机</button>
            <button class="earth-tool" type="button" :disabled="!running" @click="skyView"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 17h18M5 12a4 4 0 0 1 4-4 5 5 0 0 1 9 2 3 3 0 0 1 1 6"/></svg>天空视角</button>
          </div>
          <div class="earth-tool-group">
            <button class="earth-tool" type="button" :disabled="!running" :aria-pressed="presentation.tour" @click="toggleTour"><svg viewBox="0 0 24 24" aria-hidden="true"><path v-if="presentation.tour" d="M9 6v12m6-12v12"/><path v-else d="m9 5 10 7-10 7z"/></svg>{{ presentation.tour ? '停止环游' : '自动环游' }}</button>
            <button class="earth-tool" type="button" :disabled="!running" :aria-pressed="presentation.sunlight" @click="toggleSunlight"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/></svg>日照演示</button>
            <button class="earth-tool" type="button" :aria-pressed="immersive" @click="toggleImmersive"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></svg>{{ immersive ? '退出沉浸' : '沉浸视图' }}</button>
          </div>
        </div>

        <div class="earth-stage">
          <div ref="host" class="earth-host" aria-label="三维地球" :aria-hidden="!running" />
          <div v-if="!started" class="earth-placeholder">
            <div class="earth-idle-art" aria-hidden="true"><div class="idle-ring"/><div class="idle-globe"/><div class="idle-orbit"/></div>
            <span class="earth-idle-kicker">A WORLD TO EXPLORE</span>
            <h2>从这里，看见整个世界。</h2>
            <p>打开地球，让云层、轨道与飞行轨迹在眼前展开。</p>
            <button class="earth-button earth-primary" type="button" @click="start">进入地球<span aria-hidden="true">↗</span></button>
          </div>
          <div v-else-if="earthStatus === 'loading'" class="earth-placeholder" role="status"><span class="earth-spinner"/><h2>正在准备你的地球…</h2><p>首次加载需要片刻，可随时关闭。</p></div>
        </div>

        <div class="earth-bottom-bar">
          <div class="earth-destinations" aria-label="快速抵达">
            <span>快速抵达</span>
            <button type="button" :disabled="!running" @click="visit('asia')">东亚</button>
            <button type="button" :disabled="!running" @click="visit('pacific')">太平洋</button>
            <button type="button" :disabled="!running" @click="visit('polar')">北极</button>
            <button type="button" :disabled="!running" @click="visit('himalaya')">喜马拉雅</button>
          </div>
          <div class="earth-count" aria-live="polite"><span><b>{{ stats.drones }}</b> 架飞机</span><span><b>{{ stats.points.toLocaleString() }}</b> 轨迹点</span><span v-if="stats.catchingUp">同步历史中</span></div>
        </div>
      </div>

      <aside v-if="settingsOpen" id="earth-settings" ref="settingsPanel" tabindex="-1" class="earth-settings" aria-label="地球配置" @keydown.esc.stop="toggleSettings">
        <div class="earth-settings-header"><div><span>YOUR EARTH</span><h2>地球配置</h2></div><button class="earth-icon-button" type="button" aria-label="关闭配置" @click="toggleSettings">×</button></div>
        <EarthImagerySettings :selection="imagery" :state="imageryState" :running="running" :on-apply="applyImagery" />
        <EarthTokenSettings :on-changed="() => session.reloadTerrain()" />
        <fieldset><legend>地形起伏</legend>
          <label class="earth-switch"><span>真实地形<small>Cesium World Terrain 在线高程</small></span><input v-model="terrainEnabled" type="checkbox" aria-label="真实地形" @change="session.setTerrainEnabled(terrainEnabled)"></label>
          <p class="earth-setting-note" role="status">{{ terrainMessages[terrainStatus] }}</p>
          <p class="earth-setting-note">点击“喜马拉雅”查看山地起伏；右键拖动缩放，中键拖动倾斜视角。</p>
        </fieldset>
        <fieldset><legend>场景氛围</legend>
          <label class="earth-switch"><span>地理标注<small>国家、地区、城市与城镇</small></span><input v-model="effects.labels" type="checkbox" @change="updateEffects"></label>
          <div v-if="effects.labels" class="earth-label-density">
            <div class="earth-quality" role="group" aria-label="标注密度">
              <button v-for="item in (['sparse', 'standard', 'detailed'] as const)" :key="item" type="button" :aria-pressed="effects.labelDensity === item" @click="effects.labelDensity = item; updateEffects()">{{ { sparse: '简洁', standard: '标准', detailed: '详细' }[item] }}</button>
            </div>
            <p class="earth-setting-note">拉近可查看更多城市和城镇，文字自动避让。</p>
          </div>
          <label class="earth-switch"><span>行政边界<small>国界与省州界，随缩放显示</small></span><input v-model="effects.boundaries" type="checkbox" @change="updateEffects"></label>
          <label class="earth-switch"><span>全球云图<small>从太空观看的历史云图</small></span><input v-model="effects.clouds" type="checkbox" aria-label="云层" @change="updateEffects"></label>
          <label class="earth-switch"><span>演示卫星<small>轨道与发光尾迹</small></span><input v-model="effects.satellites" type="checkbox" @change="updateEffects"></label>
          <label class="earth-switch"><span>播放特效动画</span><input v-model="effects.animate" type="checkbox" @change="updateEffects"></label>
          <p class="earth-setting-note">云图和卫星为演示效果，近景自动隐藏。</p>
        </fieldset>
        <fieldset><legend>白天天空</legend>
          <label class="earth-switch"><span>近地积云<small>有高度层次的静态云群</small></span><input v-model="effects.cumulus" type="checkbox" aria-label="近地积云" @change="updateEffects"></label>
          <label class="earth-switch"><span>高空薄云<small>轻薄舒展的高空云纹</small></span><input v-model="effects.cirrus" type="checkbox" aria-label="高空薄云" @change="updateEffects"></label>
          <label class="earth-switch"><span>远山薄雾<small>柔化远景，保留近处细节</small></span><input v-model="effects.haze" type="checkbox" aria-label="远山薄雾" @change="updateEffects"></label>
          <label class="earth-switch"><span>大气渐变<small>蓝天向明亮地平线过渡</small></span><input v-model="effects.atmosphere" type="checkbox" aria-label="大气渐变" @change="updateEffects"></label>
          <p class="earth-setting-note">点击“天空视角”，中键或 Ctrl + 左键拖动抬头看天。跟随飞机时也能自由转动视角。云与薄雾为场景装饰，不代表实时天气。</p>
        </fieldset>
        <fieldset><legend>画质与响应</legend>
          <div class="earth-quality" role="group" aria-label="地球画质"><button v-for="item in (['smooth', 'balanced', 'sharp'] as const)" :key="item" type="button" :aria-pressed="quality === item" @click="quality = item; session.setQuality(item)">{{ { smooth: '流畅', balanced: '均衡', sharp: '精细' }[item] }}</button></div>
          <p class="earth-setting-note">{{ qualityHints[quality] }}<br>刷新节奏跟随浏览器与屏幕。</p>
        </fieldset>
        <fieldset><legend>飞机与轨迹</legend>
          <label class="earth-select-label">统一显示高度（米）<input v-model="altitudeInput" type="number" step="any" placeholder="留空跟随遥测" aria-label="统一显示高度（米）" aria-describedby="earth-altitude-help" @input="session.setAltitude(altitudeInput)"></label>
          <p id="earth-altitude-help" class="earth-setting-note">留空或小于 0：使用各机遥测 alt，缺失或无效时使用 2000 米。填写 0 或正数：所有飞机与轨迹统一使用该高度。仅调整显示，不下发飞行指令。</p>
          <p class="earth-setting-note">轨迹点没有高度时使用 2000 米。高度直接用于椭球坐标，不随地形抬升。</p>
          <label class="earth-switch"><span>显示轨迹</span><input v-model="showTracks" type="checkbox" @change="session.setTracksVisible(showTracks)"></label>
          <label class="earth-select-label">跟随飞机<select v-model="focus" aria-label="跟随飞机" @change="follow"><option value="">自由视角</option><option v-for="drone in store.sortedDrones" :key="drone.id" :value="String(drone.id)">{{ drone.tag || `DRONE${drone.id}` }}</option></select></label>
        </fieldset>
        <fieldset><legend>日照演示</legend>
          <label class="earth-switch"><span>晨昏分界</span><input v-model="presentation.sunlight" type="checkbox" @change="updatePresentation"></label>
          <label v-if="presentation.sunlight" class="earth-sun-control">光照方向 <output>{{ presentation.sunLongitude }}°</output><input v-model.number="presentation.sunLongitude" aria-label="光照方向" type="range" min="-180" max="180" step="1" @input="updatePresentation"></label>
          <p class="earth-setting-note">转动光源，观察光照与大气变化。<br>这是可调日照演示。</p>
        </fieldset>
      </aside>
    </div>
    <footer class="earth-footer">
      <span><i class="earth-line"/>实际轨迹 <i class="earth-line earth-planned"/>规划轨迹 <span class="earth-altitude">{{ configuredAltitude === null ? '高度：遥测 alt · 缺失时 2000 m' : `统一显示高度：${configuredAltitude} m` }}</span></span>
      <span>{{ presentation.tour ? '环游中 · 拖动即可接管视角' : '左键拖动环视 · 滚轮缩放 · 中键 / Ctrl + 左键抬头看天' }}</span>
    </footer>
  </section>
</template>

<style scoped>
:global(.page-stage:has(.earth-page)) { max-width: none; padding: 0; }
.earth-page { --earth-text: #e1e9f3; --earth-muted: #8593a9; --earth-border: #ffffff12; min-height: calc(100dvh - 66px); background: #080d16; color: var(--earth-text); padding: 26px 30px 16px; font-size: 13px; color-scheme: dark; }
.earth-header { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-bottom: 25px; }
.earth-eyebrow { font-size: 10px; letter-spacing: 3px; color: #8aa0bf; }
.earth-title h1 { display: flex; align-items: baseline; gap: 22px; font-size: 27px; font-weight: 550; letter-spacing: -.5px; margin: 7px 0 0; }
.earth-title h1 span { font-size: 12px; font-weight: 400; color: var(--earth-muted); letter-spacing: 1px; }
.earth-header-actions { display: flex; align-items: center; gap: 10px; }
.earth-status { display: flex; align-items: center; gap: 7px; color: var(--earth-muted); font-size: 11px; margin-right: 10px; }
.earth-status i { width: 5px; height: 5px; border-radius: 50%; background: #65748a; }
.earth-status i.active { background: #81cabc; }
.earth-button { border: 1px solid #ffffff1c; border-radius: 7px; padding: 10px 14px; background: #141d2b; color: #cbd8eb; display: inline-flex; align-items: center; justify-content: center; gap: 10px; font-size: 12px; min-height: 38px; }
.earth-button:hover { background: #202d40; }
.earth-primary { background: #d6e6fc; color: #142338; border-color: transparent; font-weight: 600; }
.earth-primary:hover { background: #edf4ff; }
.earth-primary span { margin-left: 16px; }
.earth-close { color: #aa95a2; background: transparent; border-color: var(--earth-border); }
.earth-close:hover { background: #321d2b; color: #edb9ca; }
.earth-page button:focus-visible, .earth-page input:focus-visible, .earth-page select:focus-visible { outline: 2px solid #a9d3ff; outline-offset: 3px; }
.earth-page button:disabled { opacity: .38; }
.earth-page svg { width: 17px; height: 17px; stroke: currentColor; stroke-width: 1.4; fill: none; stroke-linecap: round; stroke-linejoin: round; }
.earth-workspace { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; align-items: start; }
.earth-workspace.with-settings { grid-template-columns: minmax(0, 1fr) 282px; }
.earth-main { min-width: 0; border: 1px solid var(--earth-border); border-radius: 12px; overflow: hidden; background: #0c1320; }
.earth-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; min-height: 53px; padding: 8px 13px; border-bottom: 1px solid var(--earth-border); }
.earth-tool-group { display: flex; gap: 5px; align-items: center; }
.earth-tool { display: flex; align-items: center; justify-content: center; gap: 7px; border: 1px solid transparent; background: transparent; color: #9baac0; border-radius: 6px; font-size: 12px; padding: 8px 10px; white-space: nowrap; }
.earth-tool:hover:not(:disabled) { color: #eef4fc; background: #ffffff08; }
.earth-tool[aria-pressed="true"] { color: #c6e2ff; border-color: #86baff28; background: #739cd414; }
.earth-stage { position: relative; height: max(480px, calc(100dvh - 328px)); overflow: hidden; background: #030711; }
.earth-host { position: absolute; inset: 0; }
.earth-bottom-bar { min-height: 51px; display: flex; flex-wrap: wrap; gap: 15px; align-items: center; justify-content: space-between; padding: 10px 18px; border-top: 1px solid var(--earth-border); }
.earth-destinations { display: flex; align-items: center; gap: 17px; font-size: 11px; }
.earth-destinations > span { color: #64748b; margin-right: 4px; }
.earth-destinations button { background: none; border: 0; color: #a8b8cf; padding: 3px 0; font-size: 11px; }
.earth-destinations button:hover:not(:disabled) { color: #edf5ff; }
.earth-count { display: flex; align-items: baseline; gap: 18px; font-size: 10px; color: #7e8da4; }
.earth-count b { color: #c8d5e6; font-weight: 500; font-size: 13px; font-variant-numeric: tabular-nums; padding-right: 3px; }
.earth-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; font-size: 10px; color: #74839a; padding: 15px 1px 0; }
.earth-line { display: inline-block; width: 15px; border-top: 1px solid #6fbca8; vertical-align: middle; margin-right: 6px; }
.earth-planned { border-top: 1px dashed #7c9eca; margin-left: 17px; }
.earth-altitude { margin-left: 22px; color: #637188; }
.earth-placeholder { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; flex-direction: column; text-align: center; padding: 26px; background: radial-gradient(ellipse at 50% 25%, #15284277, #040913 68%); }
.earth-placeholder h2 { font-size: 27px; font-weight: 450; letter-spacing: 1px; margin: 12px 0 6px; }
.earth-placeholder p { color: #8294af; font-size: 12px; line-height: 1.8; margin: 0 0 24px; }
.earth-idle-kicker { color: #677f9f; font-size: 9px; letter-spacing: 3px; }
.earth-idle-art { width: 240px; height: 170px; position: relative; margin-bottom: 25px; }
.idle-globe { position: absolute; width: 150px; height: 150px; border-radius: 50%; left: 45px; top: 10px; border: 1px solid #82b8f66b; background: radial-gradient(circle at 30% 20%, #3d6787, #122d48 45%, #030a15 76%); box-shadow: -7px -5px 28px #719bcb17, inset 4px 2px 8px #acd5ff44; }
.idle-ring, .idle-orbit { position: absolute; top: 35px; left: 5px; width: 230px; height: 100px; border: 1px solid #a9c4e132; border-radius: 50%; transform: rotate(-28deg); }
.idle-orbit { transform: rotate(45deg); height: 65px; top: 53px; border-color: #a9c4e123; }
.earth-spinner { width: 32px; height: 32px; border: 1px solid #aacbfa33; border-top-color: #b7d7ff; border-radius: 50%; animation: earth-loading 1s linear infinite; margin-bottom: 16px; }
@keyframes earth-loading { to { transform: rotate(360deg); } }
.earth-message { margin: 0 0 16px; padding: 12px 16px; background: #392e1e; color: #e9cd9c; border: 1px solid #9e743b44; border-radius: 8px; line-height: 1.7; }
.earth-error { background: #38212b; color: #e7b5c2; border-color: #af536544; }
.earth-settings { background: #0f1826; border: 1px solid var(--earth-border); border-radius: 12px; padding: 19px; outline: none; }
.earth-settings-header { display: flex; align-items: center; justify-content: space-between; }
.earth-settings-header span { font-size: 9px; letter-spacing: 2px; color: #657d9d; }
.earth-settings h2 { font-size: 17px; font-weight: 500; margin: 7px 0 3px; }
.earth-icon-button { color: #8da1be; border: 0; background: transparent; font-size: 24px; width: 32px; height: 32px; }
.earth-icon-button:hover { color: #fff; }
.earth-settings fieldset { border: 0; border-top: 1px solid var(--earth-border); padding: 17px 0 0; margin: 24px 0 0; min-width: 0; }
.earth-settings legend { padding: 0 9px 0 0; font-size: 11px; color: #b6c6db; }
.earth-switch { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin: 0 0 17px; cursor: pointer; color: #b7c5d8; font-size: 12px; }
.earth-switch small { display: block; color: #6f829e; margin-top: 5px; font-size: 10px; }
.earth-switch input { appearance: none; flex: 0 0 29px; width: 29px; height: 17px; border-radius: 12px; border: 1px solid #465369; background: #202c3d; position: relative; cursor: pointer; margin: 0; }
.earth-switch input::after { content: ''; position: absolute; height: 11px; width: 11px; left: 2px; top: 2px; border-radius: 50%; background: #8293ab; }
.earth-switch input:checked { background: #7caddc; border-color: #7caddc; }
.earth-switch input:checked::after { background: #f1f7ff; left: 14px; }
.earth-setting-note { color: #778ba7; font-size: 10px; line-height: 1.9; margin: 11px 0 0; }
.earth-label-density { margin: -3px 0 20px; }
.earth-quality { display: flex; padding: 3px; background: #070e18; border: 1px solid #ffffff0c; border-radius: 6px; }
.earth-quality button { flex: 1; color: #7e92af; border: 0; background: transparent; padding: 7px 4px; border-radius: 4px; font-size: 11px; }
.earth-quality button[aria-pressed="true"] { color: #e2edff; background: #24364e; }
.earth-select-label { font-size: 11px; color: #7f92ad; display: block; }
.earth-select-label select, .earth-select-label input { box-sizing: border-box; width: 100%; margin-top: 9px; padding: 9px 10px; color: #b8cbe2; background: #0a1220; border: 1px solid #ffffff18; border-radius: 5px; }
.earth-sun-control { display: flex; align-items: center; flex-wrap: wrap; justify-content: space-between; color: #8ca1bd; font-size: 11px; gap: 10px; }
.earth-sun-control output { color: #d2e3f6; font-variant-numeric: tabular-nums; }
.earth-sun-control input { width: 100%; accent-color: #a7ccef; }
.earth-page:fullscreen { overflow: auto; padding: 22px 28px 15px; }
.earth-page:fullscreen .earth-stage { height: max(480px, calc(100dvh - 257px)); }
.earth-host :deep(.cesium-viewer), .earth-host :deep(.cesium-viewer-cesiumWidgetContainer), .earth-host :deep(.cesium-widget), .earth-host :deep(canvas) { width: 100%; height: 100%; }
.earth-host :deep(.cesium-widget-credits) { opacity: .75; }
@media (min-width: 2000px) { .earth-page { padding-left: 42px; padding-right: 42px; } }
@media (max-width: 1000px) { .earth-title h1 span, .earth-status { display: none; } .earth-tool { padding: 8px 6px; } .earth-workspace.with-settings { grid-template-columns: minmax(0, 1fr) 250px; } }
@media (max-width: 760px) {
  .earth-page { padding: 18px 12px 15px; }
  .earth-header { margin-bottom: 17px; gap: 12px; }
  .earth-title h1 { font-size: 22px; }
  .earth-header-actions { gap: 7px; }
  .earth-header-actions .earth-button { padding: 9px; font-size: 11px; }
  .earth-workspace.with-settings { grid-template-columns: minmax(0, 1fr); }
  .earth-toolbar { flex-wrap: wrap; padding: 8px; gap: 3px; }
  .earth-tool { font-size: 11px; padding: 8px 5px; gap: 5px; }
  .earth-tool-group { gap: 3px; }
  .earth-stage { height: max(430px, calc(100dvh - 310px)); }
  .earth-bottom-bar { padding: 10px 12px; }
  .earth-destinations { gap: 13px; }
  .earth-count { gap: 13px; }
  .earth-altitude { display: none; }
  .earth-placeholder h2 { font-size: 23px; }
  .earth-settings { padding: 20px; }
}
@media (prefers-reduced-motion: reduce) { .earth-spinner { animation: none; } }
</style>
