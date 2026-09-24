import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'
import { viteStaticCopy } from 'vite-plugin-static-copy'

const buildId = new Date().toISOString()
  .replace(/[-:]/g, '')
  .replace('T', '-')
  .replace(/\..+$/, 'Z')

export default defineConfig({
  base: './',
  define: {
    __GCS_BUILD_ID__: JSON.stringify(buildId),
  },
  plugins: [vue(), viteStaticCopy({
    targets: [
      ...['Assets', 'Widgets', 'Workers', 'ThirdParty'].map((directory) => ({
        src: `node_modules/cesium/Build/Cesium/${directory}`,
        dest: 'cesium',
      })),
      { src: 'src/earth/assets/clouds-CREDIT.txt', dest: 'licenses', rename: 'earth-effects.txt' },
      { src: 'src/earth/assets/cartography-CREDIT.txt', dest: 'licenses', rename: 'earth-cartography.txt' },
      { src: 'node_modules/cesium/LICENSE.md', dest: 'licenses', rename: 'cesium.md' },
      { src: 'node_modules/cesium/ThirdParty.json', dest: 'licenses', rename: 'cesium-third-party.json' },
    ],
  })],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        ws: true,
        configure(proxy) {
          const backendOrigin = 'http://127.0.0.1:8765'
          proxy.on('proxyReq', (proxyRequest) => {
            if (proxyRequest.hasHeader('origin')) proxyRequest.setHeader('origin', backendOrigin)
          })
          proxy.on('proxyReqWs', (proxyRequest) => {
            if (proxyRequest.hasHeader('origin')) proxyRequest.setHeader('origin', backendOrigin)
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
})
