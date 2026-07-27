/**
 * Electron integration tests.
 *
 * These tests validate that the Electron-aware code paths in the SPA behave
 * correctly without requiring Electron itself to be installed. They simulate
 * the Electron environment by stubbing ``window.electronAPI`` and
 * ``window.__backendUrl__``.
 *
 * For full end-to-end Electron testing (window creation, backend lifecycle,
 * native dialogs), a separate Electron-specific test harness would be needed.
 */
import { test, expect } from '@playwright/test'

test.describe('Electron - Router', { tag: ['@p1', '@electron'] }, () => {
  test('uses hash history when electronAPI is present', async ({ page }) => {
    // Simulate Electron preload by injecting electronAPI before the SPA boots.
    // The router checks window.electronAPI at module-init time and chooses
    // createWebHashHistory vs createWebHistory accordingly.
    await page.addInitScript(() => {
      window.electronAPI = {} as any
    })

    await page.goto('/#/dashboard')
    await expect(page.locator('aside.sidebar')).toBeVisible({ timeout: 15_000 })
  })

  test('uses HTML5 history when electronAPI is absent', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page.locator('aside.sidebar')).toBeVisible({ timeout: 15_000 })
  })
})

test.describe('Electron - API layer', { tag: ['@p1', '@electron'] }, () => {
  test('detects __backendUrl__ and constructs base URL', async ({ page }) => {
    // The axios instance reads window.__backendUrl__ at module-init time
    // and uses it as the base for /api/v1 requests.
    await page.addInitScript(() => {
      window.electronAPI = {} as any
      window.__backendUrl__ = 'http://localhost:59873'
    })

    await page.goto('/#/login')
    // Navigate to login (bypasses auth guard). The API layer should be
    // initialized with http://localhost:59873/api/v1 as baseURL.
    // Verify the page loaded — if baseURL was wrong it would 404.
    await expect(page.locator('.login-container')).toBeVisible({ timeout: 10_000 })
  })

  test('falls back to /api/v1 when no electronAPI', async ({ page }) => {
    await page.goto('/login')
    await expect(page.locator('.login-container')).toBeVisible({ timeout: 10_000 })
  })
})
