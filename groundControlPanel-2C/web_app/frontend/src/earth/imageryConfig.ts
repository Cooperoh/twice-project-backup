// This module deliberately has no Cesium import: settings are available before startup.
export type ImageryId = 'esri' | 'eox' | 'nasa' | 'custom'
export interface ImagerySelection { id: ImageryId; url?: string; maximumLevel?: number; attribution?: string }
export interface ImageryState { status: 'idle' | 'loading' | 'ready' | 'error'; message: string }
export interface ImagerySource { name: string; kind: 'arcgis' | 'xyz'; url: string; maximumLevel: number; attribution: string }
export const IMAGERY_STORAGE_KEY = 'gcs.earth.imagery.v1'
export const imageryPresets = [
  { id: 'esri', name: 'Esri World Imagery', hint: '近景细节丰富；部分地区不同层级存在色差。',
    kind: 'arcgis', url: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer',
    maximumLevel: 19, attribution: 'Esri World Imagery', terms: 'https://www.esri.com/en-us/legal/terms/full-master-agreement' },
  { id: 'eox', name: 'EOX Sentinel-2 cloudless', hint: '2020 年合成影像，适合大范围观察；近景约 10 米。公共服务限非商业用途，需署名。',
    kind: 'xyz', url: 'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg',
    maximumLevel: 14, attribution: 'Sentinel-2 cloudless © EOX · modified Copernicus Sentinel data 2020', terms: 'https://s2maps.eu/' },
  { id: 'nasa', name: 'NASA Blue Marble', hint: '全球卫星合成图，含地貌阴影；适合远景，不适合观察建筑和道路。',
    kind: 'xyz', url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/BlueMarble_ShadedRelief_Bathymetry/default/GoogleMapsCompatible_Level8/{z}/{y}/{x}.jpeg',
    maximumLevel: 8, attribution: 'NASA Blue Marble · NASA EOSDIS GIBS', terms: 'https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs' },
] as const

export function normalizeImagery(value: unknown): ImagerySelection {
  if (!value || typeof value !== 'object') throw new Error('请选择卫星影像。')
  const input = value as Record<string, unknown>
  if (imageryPresets.some(preset => preset.id === input.id)) return { id: input.id as ImageryId }
  if (input.id !== 'custom') throw new Error('未知的影像源。')
  const url = typeof input.url === 'string' ? input.url.trim() : ''
  if (!url || url.length > 4096) throw new Error('请输入有效的影像源地址（最多 4096 个字符）。')
  let parsed: URL
  try { parsed = new URL(url) } catch { throw new Error('地址必须是完整的 http:// 或 https:// 地址。') }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.hash) {
    throw new Error('请使用 HTTP/HTTPS 地址，不支持内嵌账号密码或 # 片段。')
  }
  const arcgis = /\/MapServer\/?$/i.test(parsed.pathname)
  if (!arcgis && (!url.includes('{z}') || !url.includes('{x}') ||
      !['{y}', '{-y}', '{reverseY}'].some(key => url.includes(key)))) {
    throw new Error('瓦片地址需包含 {z}、{x}、{y}（TMS 可用 {-y}）；或填写以 /MapServer 结尾的 ArcGIS 服务地址。')
  }
  if ((url.match(/\{[^}]*\}/g) ?? []).some(key => !['{z}', '{x}', '{y}', '{-y}', '{reverseY}', '{s}'].includes(key))) {
    throw new Error('地址含不支持的占位符。支持 {z}、{x}、{y}、{-y}、{reverseY} 和 {s}。')
  }
  const maximumLevel = input.maximumLevel ?? 18
  if (typeof maximumLevel !== 'number' || !Number.isInteger(maximumLevel) || maximumLevel < 0 || maximumLevel > 22) {
    throw new Error('最大层级须为 0–22 的整数。')
  }
  return { id: 'custom', url, maximumLevel,
    attribution: typeof input.attribution === 'string' ? input.attribution.trim().slice(0, 240) : '' }
}

export function imagerySource(value: ImagerySelection): ImagerySource {
  const selection = normalizeImagery(value)
  if (selection.id !== 'custom') return imageryPresets.find(p => p.id === selection.id)!
  return { name: '自定义卫星影像', kind: /\/MapServer\/?$/i.test(new URL(selection.url!).pathname) ? 'arcgis' : 'xyz',
    url: selection.url!.replaceAll('{-y}', '{reverseY}'), maximumLevel: selection.maximumLevel!,
    attribution: selection.attribution || '自定义卫星影像' }
}
export function loadImagerySelection(): ImagerySelection {
  try { return normalizeImagery(JSON.parse(localStorage.getItem(IMAGERY_STORAGE_KEY) ?? 'null')) }
  catch { return { id: 'esri' } }
}
export function saveImagerySelection(value: ImagerySelection): boolean {
  try { localStorage.setItem(IMAGERY_STORAGE_KEY, JSON.stringify(normalizeImagery(value))); return true }
  catch { return false }
}
