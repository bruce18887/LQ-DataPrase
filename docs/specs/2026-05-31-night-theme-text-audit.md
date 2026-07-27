# Night Theme Text Color Audit & Fix

**Date:** 2026-05-31
**Status:** Approved Design

## Problem

When switching to night theme (`data-theme="night"`), all UI text should be light-colored. However, multiple `.vue` files contain hardcoded dark text colors that don't use CSS variables, causing invisible text on dark backgrounds.

## Fix Strategy

Replace hardcoded color values in `.vue` files with CSS variable references (`var(--text-primary)`, `var(--text-secondary)`, `var(--text-tertiary)`). Only target text color values, not layout, spacing, or semantic colors.

## Scope

### Files to modify

| # | File | Changes |
|---|------|---------|
| 1 | `roadmap/RoadmapPage.vue` | 6 hardcoded colors in inline style + unscoped `<style>` |
| 2 | `analysis/components/ChartConfigPanel.vue` | 5 hardcoded colors in scoped `<style>` |
| 3 | `analysis/components/WaferMapPanel.vue` | 5 inline + 1 ECharts config |
| 4 | `analysis/components/RangeComparisonTable.vue` | 1 scoped style |
| 5 | `analysis/components/SiteStatsTable.vue` | 1 scoped style |
| 6 | `analysis/components/ParamSelector.vue` | 1 scoped style |
| 7 | `dashboard/DashboardPage.vue` | 3 inline + 1 ECharts config |
| 8 | `analysis/components/FileCorrelationSection.vue` | 1 inline |
| 9 | `analysis/components/FileCorrelationPanel.vue` | 1 inline |

### Color replacement mapping

| Hardcoded | Replace with | Context |
|-----------|-------------|---------|
| `#303133` | `var(--text-primary)` | Primary text (darkest gray) |
| `#2c3e50` | `var(--text-primary)` | Roadmap titles |
| `#606266` | `var(--text-primary)` | Hints/value text |
| `#333` | `var(--text-primary)` | ECharts tooltip |
| `#464646` | `var(--text-primary)` | ECharts gauge label |
| `#5d4037` | `var(--text-primary)` | Roadmap stat text |
| `#7f8c8d` | `var(--text-secondary)` | Roadmap subtitle |
| `#909399` | `var(--text-secondary)` | Labels, hints, secondary text |
| `#999` | `var(--text-tertiary)` | Muted text |
| `#bdc3c7` | `var(--text-tertiary)` | Footer text |

### NOT changing (intentionally semantic)

- `#e53935` — error/range red
- `#2ECC71` — pass green
- `#E74C3C` — fail red
- `#f5576c` — accent pink
- `#667eea` — accent purple
- `#11998e` — accent green
- `#F39C12` — warning orange
- `el-button--primary` text color (intentional `--text-inverse`)
- `P1TaskManager.vue` — already uses its own dark bg with white text

## Verification

After all changes, re-run automated Playwright check across all pages and visually confirm no dark text on dark backgrounds.
