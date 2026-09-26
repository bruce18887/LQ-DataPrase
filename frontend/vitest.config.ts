import { defineConfig } from 'vitest/config'

// T2 层：只跑零 DOM 的纯函数，故 environment 用 node 而非 jsdom。
export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/unit/**/*.spec.ts'],
  },
})
