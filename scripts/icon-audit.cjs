/**
 * .ico 底板形制的写盘前红线（Task 9 重定基线；判据本体，被 scripts/gen-icon.ico.js 消费，
 * 由 frontend/test/unit/iconLib.spec.ts 用合成字节守着）。
 *
 * 职责集合 = 旧判据的并集 + C1 的直接守门，逐条对应简报「重定审计基线」表：
 *   G1 符号(反白)区实心色阶 —— 防「模糊/柔化加回符号」(D2)；旧判据靠全帧 ≤2 色阶，
 *      但渐变底板天然数百色阶，必须把统计域缩到反白 ink 区（alpha===255 且各通道 >=240）。
 *      阈值**按帧分档**（I4：一个全局常量套在随尺寸变化的统计量上，会在 6 帧里的 4 帧丢判别力）。
 *   G2 底板两支 stop 真实出现 —— 防「night/错色底板进 .ico」；旧判据 dominant===EXPECTED_TONE
 *      在底板形制下必歪（出现最多的实心色是底板中段而非纯蓝），换成端点邻域像素计数。
 *   G3 底板几何三件套 —— 防 C1 本体「底板根本没画出来」：不透明占比区间 + 剪影===整帧 +
 *      四角 r/2 圆盘透明。旧判据对「没有底板」完全瞎（裸闪电 tones=1、主色也恰好是 #2563eb）。
 *   G4 16px 符号可辨性 —— 旧「bbox >=15x15」在底板铺满帧后恒真、失去判别力；换成
 *      ink 实心像素数与 spec §1.2「底部 25% 区最宽行」两小门（口径 alpha===255 且各通道 >=240）。
 *
 * 纪律（评审点名）：阈值必须严格优于交付实测值且余量写在本文件（I7：旧门实测 15×15 零余量）；
 * 报错文案只能指向该帧尺寸真实可能的原因（16px 外边距恒 0，禁写「留白吃掉面积」）。
 * 后者在 final review 里叫 I7、本轮又按同一缺陷类抓到两处（I3：G3b 的文案只写了
 * 「裸符号指纹」这一支，漏了「底板画了但被内缩/裁掉整边」——见下面 G3b 文案分支）。
 */

/**
 * 阈值表。统一口径：alpha===255 实心像素（ink 另加「各通道>=240」；角样本的「透明」是
 * alpha<128，理由见 icon-metrics.cjs 角样本注释）；栅格化 = 本机 Playwright Chromium
 * setContent+截图、锁 light（与 gen-icon.ico.js 同通路）。
 * 交付实测出处（tasks/_task9_probe_out.json，底板形制 frameHtml(现母版) 六帧，2026-10-15）：
 *   plateRatio 0.891(16px)~0.955(256)；cornerTransp 1.0(16/32)~0.86(48/256)；
 *   start/end 最少在 16px：37/46；inkTones 逐帧 5/8/10/11/15/14（16→256）；
 *   16px ink=72、尾行=2、间隙=2.5px；剪影六帧全 = 整帧。
 *   反面实测：旧 .ico 裸闪电 plateRatio 最大 0.355、start=0；旧模糊母版反白进底板
 *   inkTones = 8(16)/11(32)/15(48)/17(64)/24(128)/24(256)（本轮复测：tasks/_fixr_ctrl_verify.txt）；
 *   amber 板按 light 判据审 start=end=0。
 */
const AUDIT_LIMITS = {
  // G1 反白区实心色阶上限——**按帧分档**（本轮 I4：一档全局常量套在随尺寸增长的统计量上，
  // 在 6 帧里的 4 帧丢掉判别力：旧值 18 只红得了 128/256，而 64px 的真模糊实测 17 只差 1 阶）。
  // 定档规则（控制者裁定）：每帧阈值 = 该帧「交付实测 + 余量」与「该帧真模糊实测 − 1」取更严者，
  // 即 inkTonesMaxBySize[size] = min(交付+3, 真模糊−1)，且必须严格高于交付实测（I7 禁零余量）。
  // 两列实测都在同一 tracked 通路上渲出来（frameHtml(现母版/旧模糊母版) → Chromium 截图 → frameStats）：
  //   帧      16   32   48   64   128   256
  //   交付      5    8   10    13    17    20
  //   真模糊    8   11   20    21    25    29   （旧模糊母版反白进同一底板；母版从 git 取：
  //                                              `git show 5cad1b1^:frontend/public/favicon.svg`）
  //   阈值      7   10   13    16    20    23
  //   余量      2    2    3     3     3     3   /  拦得住真模糊的差距 1/1/7/5/5/6 阶
  // 上表是 **≥48px 内缩取 12% 之后**重测的（`tasks/_inset12_rebaseline.cjs`，2026-10-16）。
  // 19% 档下的旧值是 交付 5/8/10/11/15/14、真模糊 8/11/15/17/24/24、阈值 7/10/13/14/18/17 ——
  // 换内缩会同时挪动两列，所以**阈值表与内缩档位是一套，不许各改一半**（改档位不重测本表 = 门失效）。
  // 小帧上两个目标**互相挤压且不可兼得**（评审点名的这道题）：16px 交付 5、真模糊 8，任何 ≥3 的
  // 余量都要把阈值推到 >=8、于是这一帧的牙齿没了。这里选「保住牙齿」：16/32 只给 +2 余量，
  // 靠 1 阶差距拦住真回归；抗 AA 漂移的余量由 48px 以上承担（改 12% 后这一族差距升到 5~7 阶）。
  // 不要照着评审举例的 {16:9,…} 抄——9 在 16px 已经**高于**真模糊的 8，等于一边宣称恢复了小帧
  // 判别力一边把它悄悄丢掉。
  // 因为这道取舍，像素级模糊防线是**分层**的（spec §7-9 已点名）：本门的大帧 + 源码级门
  // frontend/test/unit/brandMark.spec.ts 的「不含任何滤镜与遮罩」用例（`/<filter|feGaussianBlur|<mask|mask=/`）
  // ——后者不花任何像素余量、覆盖所有帧，是这一维真正的补偿性控制；单测里 72 色阶的合成对照
  // 只证明「门能红」，不是真回归的证据（真回归证据是上面那行实测）。
  //
  // **上面「真模糊」那一列是一次性冻结采样，没有任何被跟踪的东西会再测它**（Task 11 E.6 点名）：
  // 交付那一列每次构建都被 gen-icon.ico.js 拿真字节重测，模糊那一列不会——逐帧重代入阈值的那条
  // 单测喂的是硬编 MEASURED 数字进合成字节，它验证的是「阈值还咬得住记录里的值」，不是「记录还
  // 等于渲染器今天的输出」。所以若某次 Chromium 升级把 16px 的真模糊从 8 推到 6，这一行的牙齿
  // 就没了而测试仍全绿。**要重测就跑这三步**（全部只依赖被跟踪的东西，别信任何 gitignored 缓存）：
  //   1) 素材从历史取：`git show 5cad1b1^:frontend/public/favicon.svg`（旧模糊母版，
  //      md5 7e840862…；本机探针副本 tasks/_t11_e6_blurred_remeasure.mjs 只是本轮记录，会随 tasks/ 蒸发）。
  //   2) 与生成器同通路逐帧渲 frameHtml(旧母版, size, brand) → Chromium 截图（锁 light）→ frameStats，
  //      读 inkTones；同一轮把 frameHtml(现母版) 也渲一遍拿交付列，两列必须**同轮**取，换渲染器时才有意义。
  //   3) 代回规则 min(交付+3, 真模糊−1) 重排阈值表，并把两列新值写回本注释与 spec §1.3；
  //      若某帧「+3 余量」与「−1 牙齿」撞上（像 16px 那样），按注释里既有的取舍保牙齿，
  //      不许静默加大阈值（I7 禁零余量图腾，也禁无理由放宽）。
  // 踩过的坑，重测时务必带上断言：**Windows 上 execSync 走 cmd.exe，`X^:path` 里的 `^` 是它的转义符**，
  // 会静默退化成 `X:path`（= 去模糊**之后**的母版），于是两列数字完全相等而探针一声不响。本轮第一次
  // 跑就中过；改用 execFileSync + argv，并断言素材里含 `feGaussianBlur`、且与现母版不相同，才拿到真值。
  // 2026-10-16 按上述三步重测过，Task 13 同日按同一通路二次复跑（本机探针记录
  // tasks/_t13_blurred_remeasure.json，随 gitignored tasks/ 蒸发；三步本身只依赖被跟踪素材，
  // 上列 1)–3) 就是可重跑的 durable 配方）：交付 5/8/10/11/15/14、真模糊 8/11/15/17/24/24、
  // 阈值逐帧仍等于 min(交付+3, 真模糊−1)，且模糊列六帧逐帧判红 —— 两列均未漂，未动任何阈值。
  inkTonesMaxBySize: { 16: 7, 32: 10, 48: 13, 64: 16, 128: 20, 256: 23 },
  // G2 端点邻域：切比雪夫距离容差。light 两支 #1d4ed8→#2563eb 通道差 (8,21,19)，
  // 端点间距 21 > 8 ✓：容差 8 既数得到渐变端头邻域，又让「渐变塌成纯 #2563eb」的
  // start 计数=0 判红；night amber 离蓝端点最近切比雪夫距离 >=137 >> 8（amber 板实渲 start=end=0）。
  STOP_TOL: 8,
  // G2 端点邻域像素数下限（绝对值，卡在最弱交付帧 16px start=37 上：阈值 26，余量 29.7%）。
  // 大帧同一判据余量 400 倍+（256px start=17288）。amber/无渐变对照实测 0。
  STOP_PIXELS_MIN: 26,
  // G3a 底板不透明占全帧比例区间。交付实测 0.891~0.955；裸闪电（旧 .ico 六帧）0.293~0.355。
  // 下沿 0.70 对交付最弱帧余量 21.5%、对裸闪电上界留 2 倍距离；上沿 0.975 对交付最强帧
  // 余量 2.0 个百分点，「方板不剪角」实渲 0.984~1.0 必红。
  // **区间挡不住「底板画了但被整圈内缩」**（I3），范围比早先记的更宽——本轮逐帧实测
  // （tasks/_t11_g3b_matrix.mjs，合成帧走真判据本体）：1px 内缩在**全部六帧**都把占比留在区间内
  // 且四角仍 ≥0.70（16/32/48/64/128/256 → 0.75 / 0.8398 / 0.8819 / 0.8975 / 0.9285 / 0.9434，
  // 角透明 1.0/1.0/1.0/1.0/0.97/0.91），于是 G3a/G3c/G1 全绿、**只剩 G3b 看得见**。
  // 所以「唯一承运人」不是 16px 的专属性，而是这条门对**所有帧的小内缩**都成立；16px 那一帧
  // 还会与 G4 同时红（取决于符号是否还站得住，本轮矩阵里符号偏小的合成帧就是两门齐红）。
  // 这句话因此从每帧消息里搬到这里（E.4）：消息只说这一帧此刻的指纹，尺寸无关的事实归注释。
  // 上界方向的可达性也实测过：**带圆角的底板再怎么内缩都越不过 0.975**（内缩后最大 0.9434），
  // 要与 G3b 同时红必须是「圆角没剪/方板」——实测 256px 方板内缩 1px → 占比 0.9844 越上界且
  // 剪影 254×254（评审举的「≥200px 帧留 1px 内缩 ⇒ ≈0.98」算的是 254²/256²，漏了 22% 圆角剪掉的
  // 面积，那条路径实际落在区间内）。钉在 iconLib.spec.ts 的「G3b 文案按方向措辞」用例。
  PLATE_RATIO_MIN: 0.7,
  PLATE_RATIO_MAX: 0.975,
  // G3c 四角 r/2 圆盘样本（连续像素中心）透明率（alpha<128）。交付实测 0.86~1.0
  //   （大帧圆角弧骑在圆盘外半区、AA 样本吃掉 12~14 个百分点是几何必然）；阈值 0.70，
  //   余量 16 个百分点。方板（这条门的靶）样本全 alpha=255 → 0，必红。
  CORNER_TRANS_MIN: 0.7,
  // G4a 16px 符号 ink 实心像素数下限。交付实测 72（内缩 1px 档）。阈值 50，余量 30.6%。
  INK_MIN_16: 50,
  // G4b 16px 底部 25% 区最宽 ink 行下限。交付实测 2 —— 简报选型规则的前提「>=3px」在
  // 16px **无任何档位可满足**（实测 inset0 才有尾行 3 但间隙=0 违反 gap>=1；inset>=1px
  // 一律 2 或更低）。这是双形制的直接代价（spec §8 已按实测更正），阈值取 1（余量 50%，
  // 仍守「严格低于交付实测」）：尾针再被吃掉一整行才红。
  // **这条门现在正好压在 ceil→round 回归的值上**（本轮点名的附加发现，实测见
  // tasks/_fixr_ctrl_verify.txt A 段）：底板形制下把内框高的 Math.ceil 换成 Math.round，
  // 16px 交付 2 → 1，仍 >=1 判绿（且剪影仍 16×16、G3b 也绿）。也就是说**尾针门对这一个已知
  // 回归是刻意留空的**，不是「已经防住了」：抬到 2 就是零余量图腾（I7 禁止，且双形制下 16px
  // 尾行本来就只剩 2，任何合规改动都会红）。承重改由单测那条改判来担——
  // frontend/test/unit/iconLib.spec.ts 的 frameHtml 内框高断言已从 `>=` 收成
  // `=== Math.ceil(w*46/48)` 精确等式，改回 round 会直接红在测试上而不是红在注释里。
  TAIL_MIN_16: 1,
}

const INK_FLOOR = 240 // ink 判定的通道下限（>=240 且 alpha===255），出处同 icon-metrics.cjs 注释

/**
 * G1 的逐帧阈值取法（表本体与两列实测出处在 AUDIT_LIMITS 上面）。
 *
 * 表里没有的尺寸（新增帧，或单测里的合成小帧）取「不小于它的第一档」。
 * **别把这条读成「色阶数随尺寸单调增」——它不单调**，本表自己的数据就地否证：交付列 16→256 是
 * 5/8/10/11/15/**14**（128 的 15 高于 256 的 14），真模糊列 8/11/15/17/**24/24**（末两档打平），
 * 于是阈值表也出现 128:18 **>** 256:17。借档的真实保证只有一条：**绝不返回 undefined**
 * （`inkTones > undefined` 恒 false = 把门关掉）。它**不保证方向**：
 *   向更大的已测档借 ⇒ 借来的数可能更宽（24 借 32 的 10 > 16 的 7；65–127 借 18 > 64 的 14），
 *   也可能更严（129–255 借 256 的 17 < 128 的 18）；比最大档还大时借最大档，对未测的大帧
 *   方向是**误红**（实测：单测里 512px 的合成帧判红）而不是静默放行。
 * 所以新增帧的正确动作永远是**先测后加行**；借档只是让「还没测过的尺寸」在过渡期有个能跑的值。
 * 第二个返回值 = 该尺寸是否在表里，供文案说明阈值是借来的（G1 消息里那句「借上一档」= 本函数
 * 的方向：**向更大的已测档借**，不是向更小的、也不是取平均值）。
 */
function inkTonesMax(size) {
  const table = AUDIT_LIMITS.inkTonesMaxBySize
  if (Object.prototype.hasOwnProperty.call(table, size)) return { max: table[size], tabulated: true }
  const sorted = Object.keys(table)
    .map(Number)
    .sort((a, b) => a - b)
  const by = sorted.find((s) => s >= size) ?? sorted[sorted.length - 1] // 比最大档还大时借最大档
  return { max: table[by], tabulated: false }
}

function rgbToHex([r, g, b]) {
  return [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')
}

function formatStop(rgb) {
  return `rgb(${rgb.join(',')})/#${rgbToHex(rgb)}`
}

/**
 * 底板形制的写盘前判据。brand 必须是 parseBrandGradient 的产物——不许回落常量。
 * @param stats frameStats(png, brand) 的返回值
 * @param brand { first:[r,g,b], last:[r,g,b], stops:[{hex,pct}] }
 */
function auditVerdict(stats, brand) {
  if (!brand || !Array.isArray(brand.first) || !Array.isArray(brand.last)) {
    throw new Error('auditVerdict 需要 parseBrandGradient 产出的 brand（缺它=解析失败，必须非零退出，不许静默放行）')
  }
  const required = ['plateRatio', 'cornerTransp', 'inkTones', 'inkCount', 'tailRowW', 'startPixels', 'endPixels']
  const missing = required.filter((k) => stats[k] === undefined || stats[k] === null)
  if (missing.length) {
    throw new Error(`auditVerdict 缺少底板形制度量字段：${missing.join(', ')}（frameStats 需要 brand 才能数端点）`)
  }
  const { size, bboxW, bboxH } = stats
  const problems = []

  // G1 —— 符号区色阶（阈值按帧分档，出处与取舍见 AUDIT_LIMITS.inkTonesMaxBySize 的注释）。
  const g1 = inkTonesMax(size)
  if (stats.inkTones > g1.max) {
    problems.push(
      `${size}px 帧符号(反白)区有 ${stats.inkTones} 个实心色阶（该帧阈值 <=${g1.max}${g1.tabulated ? '' : '，此尺寸不在逐帧表内、借上一档'}）——` +
        '模糊或柔化被加回符号了（D2 红线；底板渐变不进这一口径，只有符号糊边才进）。' +
        `同帧旧模糊母版实测见 icon-audit.cjs 的 G1 表；与尺寸无关的第一层防线是 ` +
        'brandMark.spec.ts 的「母版不得出现 filter/mask」源码正则',
    )
  }

  // G2 —— 底板两支 stop 必须真实出现。
  for (const [name, px, want] of [
    ['起点', stats.startPixels, brand.first],
    ['终点', stats.endPixels, brand.last],
  ]) {
    if (px < AUDIT_LIMITS.STOP_PIXELS_MIN) {
      problems.push(
        `${size}px 帧底板渐变${name} ${formatStop(want)} 邻域（切比雪夫<=${AUDIT_LIMITS.STOP_TOL}）只有 ` +
          `${px} 个实心像素（阈值 >=${AUDIT_LIMITS.STOP_PIXELS_MIN}）——底板渐变缺失或被换成别的配色` +
          `（night 的 #f9a825/#ffd54f 离蓝渐变端点极远，就是这个症状；先查 parseBrandGradient ` +
          `锚的是不是 design-tokens 的 light :root 块、gen-icon.ico.js 的 emulateMedia 是否还锁着 light）`,
      )
    }
  }

  // G3 —— 底板几何三件套。C1（底板根本没画出来）由这一组直接拦下。
  if (stats.plateRatio < AUDIT_LIMITS.PLATE_RATIO_MIN || stats.plateRatio > AUDIT_LIMITS.PLATE_RATIO_MAX) {
    problems.push(
      `${size}px 帧不透明像素占全帧 ${(stats.plateRatio * 100).toFixed(1)}%，不在 ` +
        `[${(AUDIT_LIMITS.PLATE_RATIO_MIN * 100).toFixed(1)}%, ${(AUDIT_LIMITS.PLATE_RATIO_MAX * 100).toFixed(1)}%]——` +
        (stats.plateRatio < AUDIT_LIMITS.PLATE_RATIO_MIN
          ? '底板没画出来或没铺满整帧（裸符号帧过不了这条，见 iconLib.spec.ts 的 G3 负对照）'
          : '占比超过圆角底板的几何上界——圆角没剪/外扩被填死了'),
    )
  }
  if (bboxW !== size || bboxH !== size) {
    // 文案只能指这一帧**真可达**的原因（I3，与早先整枝评审的 I7 同一缺陷类）：
    // 不达标有三种指纹，靠 G3a 的占比**及其越界方向**把它们分开（可达性逐帧实测见
    // AUDIT_LIMITS.PLATE_RATIO_* 的注释与 iconLib.spec.ts 的方向用例）。
    const belowMin = stats.plateRatio < AUDIT_LIMITS.PLATE_RATIO_MIN
    const aboveMax = stats.plateRatio > AUDIT_LIMITS.PLATE_RATIO_MAX
    const cause = belowMin
      ? '底板根本没画出来（裸符号帧的指纹：占比也一起掉到下界以下）；或底板画了但被大幅内缩/裁掉整边，' +
        '于是占比与剪影同时不达标'
      : aboveMax
        ? '占比同时越过上界：底板被画成方板（圆角没剪）或外扩把边缘填死了，剪影却又被内缩/裁走一边——' +
          '这一帧不是裸符号，裸符号的占比是往下掉的'
        : '底板画了、但被内缩或某一边整条裁掉（占比与四角都还正常，所以这条门是这类回归在该帧的唯一' +
          '承运人——哪几帧成立实测记在 AUDIT_LIMITS 的 G3a 注释里；查 <rect> 的 x/y/width/height ' +
          '是否还等于整帧、viewport 与截图尺寸是否一致）'
    problems.push(`${size}px 帧剪影 ${bboxW}×${bboxH}，底板形制必须等于整帧 ${size}×${size}——${cause}`)
  }
  if (stats.cornerTransp < AUDIT_LIMITS.CORNER_TRANS_MIN) {
    problems.push(
      `${size}px 帧四角 r/2 圆盘样本透明率 ${(stats.cornerTransp * 100).toFixed(0)}%（阈值 >=` +
        `${(AUDIT_LIMITS.CORNER_TRANS_MIN * 100).toFixed(0)}%）——圆角没画出来（方板）或底板画过了界`,
    )
  }

  // G4 —— 16px 符号可辨性。文案只许写该尺寸真实可能的原因：16px 外边距恒 0，所以「留白吃掉了
  // 小尺寸面积」在这条分支上根本不可能发生（I7 教训）。但**也别把原因写少**：本轮实测第三种
  // 可达原因是「符号没被反白」——底板/几何/端点全正常，只把符号画成品牌蓝，就得到
  // ink=0、尾行=0、占比 0.9531、剪影 16×16、其余门全绿、只有这一条红（复现见 iconLib.spec.ts
  // 的 G4 第二条负对照）。早先那句「只剩内缩档位和母版形状」是注释强于代码的残句（M3 同族）。
  if (size === 16) {
    const bad = []
    if (stats.inkCount < AUDIT_LIMITS.INK_MIN_16) bad.push(`ink ${stats.inkCount} px < ${AUDIT_LIMITS.INK_MIN_16}`)
    if (stats.tailRowW < AUDIT_LIMITS.TAIL_MIN_16) bad.push(`底部 25% 最宽行 ${stats.tailRowW} px < ${AUDIT_LIMITS.TAIL_MIN_16}`)
    if (bad.length) {
      problems.push(
        `16px 帧符号可辨性不足：${bad.join('，')}——底板形制下能吃掉符号像素的只有三种原因：` +
          '①内缩档位（查 insetPct）②母版形状（查 favicon.svg 尾针几何，spec §1.2）' +
          '③符号没被反白（模板里 svg.plate-symbol *{fill:#fff !important} 被改掉时，' +
          'ink 口径【各通道>=240 且 alpha===255】直接数不到像素，此时底板几何与端点门都是绿的）',
      )
    }
  }

  return problems
}

module.exports = { AUDIT_LIMITS, INK_FLOOR, inkTonesMax, auditVerdict }
