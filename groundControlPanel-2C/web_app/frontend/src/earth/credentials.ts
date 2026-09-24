export interface CesiumCredentialStatus {
  configured: boolean
  state: 'saved' | 'missing' | 'unreadable'
  message: string
  storage_path: string
  supported: boolean
}

async function request<T>(suffix = '', method = 'GET', token?: string): Promise<T> {
  const response = await fetch(`/api/earth/cesium-token${suffix}`, {
    method, credentials: 'same-origin', cache: 'no-store',
    headers: { 'X-GCS-Token-Request': '1', 'Content-Type': 'application/json' },
    body: token === undefined ? undefined : JSON.stringify({ token }),
    signal: AbortSignal.timeout(method === 'PUT' ? 20_000 : 5_000),
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof body?.detail === 'string'
    ? body.detail : '无法读取本机 Token 配置，请确认地面站后台已启动。')
  return body as T
}

export const cesiumCredentials = {
  status: () => request<CesiumCredentialStatus>(),
  save: (token: string) => request<CesiumCredentialStatus>('', 'PUT', token),
  clear: () => request<CesiumCredentialStatus>('', 'DELETE'),
  read: async (): Promise<string | null> => (await request<{ token: string | null }>('/read', 'POST')).token,
}
