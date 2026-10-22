import { useEChartsTheme } from '../../../utils/echarts-theme'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../../utils/download'
import { weightApi } from '../../../api/weight'
import { useWeightStore } from '../../../stores/weight'
import { TEXT_CHAR_LIMIT, describeExportError, describeWeightError } from './weightErrorText'

export function useWeightPlot() {
  const store = useWeightStore()
  const { colors } = useEChartsTheme()

  async function loadFile(file: File) {
    store.busy = true
    store.errorText = ''
    try {
      const text = await file.text()
      if (text.length > TEXT_CHAR_LIMIT) {
        store.errorText = `文件超出可处理范围（上限 ${TEXT_CHAR_LIMIT.toLocaleString()} 字符）`
        return
      }
      const r = await weightApi.parse({ filename: file.name, text })
      store.setDoc(r.data, text)
    } catch (e: any) {
      // 不碰 doc/rawText/visible —— 解析失败要保留现图（spec §3.2 / §11）
      store.errorText = describeWeightError(e)
    } finally {
      store.busy = false
    }
  }

  async function exportXlsx() {
    if (!store.doc) return
    store.busy = true
    try {
      const r = await weightApi.export({
        filename: store.filename, text: store.rawText,
        visible_group_indexes: store.visible, show_mean: store.showMean,
        palette: colors.value.seriesColors,
        mean_color: colors.value.textColor,
      })
      downloadBlob(r.data as Blob, extractFilenameFromContentDisposition(r.headers?.['content-disposition']) ?? 'weight-plot.xlsx')
    } catch (e: any) {
      store.errorText = await describeExportError(e)   // 导出 lane 的错误体是 Blob
    } finally {
      store.busy = false
    }
  }

  return {
    store, loadFile, exportXlsx,
    toggleMean: () => { store.showMean = !store.showMean },
    toggleLegend: () => { store.showLegend = !store.showLegend },
  }
}
