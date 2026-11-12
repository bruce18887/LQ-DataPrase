import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import { h } from 'vue'
import './custom.css'
import UiHost from './components/UiHost.vue'
import MockFrame from './components/MockFrame.vue'
import FeatureCards from './components/FeatureCards.vue'
import ShotFigure from './components/ShotFigure.vue'
import LoginMock from './components/LoginMock.vue'
import BatchYieldMock from './components/BatchYieldMock.vue'
import FileListMock from './components/FileListMock.vue'
import BatchDataMock from './components/BatchDataMock.vue'
import ViewDataMock from './components/ViewDataMock.vue'
import ExportWizardMock from './components/ExportWizardMock.vue'
import CompareMock from './components/CompareMock.vue'
import GageMock from './components/GageMock.vue'
import BuyoffMock from './components/BuyoffMock.vue'
import SftpBrowserMock from './components/SftpBrowserMock.vue'
import SftpSearchMock from './components/SftpSearchMock.vue'
import SettingsMock from './components/SettingsMock.vue'
import UsersMock from './components/UsersMock.vue'
import AuditMock from './components/AuditMock.vue'
import HistDemo from './components/HistDemo.vue'
import WaferDemo from './components/WaferDemo.vue'
import CorrDemo from './components/CorrDemo.vue'
import WeightDemo from './components/WeightDemo.vue'
import AdminPanel from './components/AdminPanel.vue'

export default {
  extends: DefaultTheme,
  Layout: () => h(DefaultTheme.Layout, null, { 'layout-bottom': () => h(UiHost) }),
  enhanceApp({ app }) {
    const comps: Record<string, unknown> = {
      MockFrame, FeatureCards, ShotFigure, LoginMock, BatchYieldMock, FileListMock,
      BatchDataMock, ViewDataMock, ExportWizardMock, CompareMock, GageMock, BuyoffMock,
      SftpBrowserMock, SftpSearchMock, SettingsMock, UsersMock, AuditMock,
      HistDemo, WaferDemo, CorrDemo, WeightDemo, AdminPanel,
    }
    for (const [name, comp] of Object.entries(comps)) app.component(name, comp as never)
  },
} satisfies Theme