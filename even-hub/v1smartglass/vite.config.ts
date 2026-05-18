import { defineConfig } from 'vite'
import { createStandaloneViteConfig } from '../../../apps/_shared/standalone-vite'
import v1Proxy from './vite-plugin'

// `apps/_shared/standalone-vite` lives in the even-dev workspace, which this
// package is meant to be cloned into. Path is `apps/v1smartglass/...` when
// dropped into BxNxM/even-dev — adjust if you stage it elsewhere.
export default defineConfig({
  ...createStandaloneViteConfig(import.meta.url, 5178),
  plugins: [v1Proxy()],
})
