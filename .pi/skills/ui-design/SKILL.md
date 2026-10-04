---
name: ui-design
description: 本项目「今天吃什么」前端 UI 的设计规范与样式约定。包含设计 tokens（暖灰白配色 + 棕橙强调色、圆角、字号层级、缓动曲线与时长）、布局与组件规范、动效规则。用于修改 frontend/index.html、新增或调整组件、改配色/间距/字号、加动效、或审查视觉一致性时。
---

# UI 设计规范（今天吃什么）

单文件前端 `frontend/index.html`（原生 HTML + CSS + vanilla JS，无框架、无动效库）。
改 UI 时遵循本规范，保持"简约、克制、不眼花缭乱"。

## 设计原则

1. **一个主路径**：用户看页面只做一件事——选场景、调人数、点「生成」。次要功能一律收进折叠/侧栏，不抢主视觉。
2. **克制配色**：暖灰白做底，只用一种棕橙 `--accent` 做强调，绝不再引入第三种主色。
3. **留白与层级**：靠留白和字号层级（20/18/15/14/13/12/11）区分信息，不用重边框或大阴影。
4. **动效只为正确性**：动效用来解释状态变化（从哪来、到哪去），不为了"好看"。加动效前先问"为什么动"。
5. **不要占位内容**：没有真实数据支撑的元素一律不展示，宁可留白。

## Design Tokens（直接复用，勿另造）

```css
:root {
  /* 颜色 */
  --bg: #FAFAF7;          /* 页面底 */
  --card: #FFFFFF;        /* 卡片 */
  --soft: #F4F3EF;        /* 浅填充（chip 底） */
  --hover: #EFEEE9;       /* hover 填充 */
  --entry-bg: #FFFBF5;    /* 入口面板 / 摘要底（暖） */
  --t1: #1F1E1B;          /* 主文字 */
  --t2: #6B6862;          /* 次文字 */
  --t3: #9B978F;          /* 弱文字 / 占位 */
  --line: #EDEBE5;        /* 分隔线 */
  --line2: #E2DFD8;       /* 边框 */
  --accent: #C8622B;      /* 强调色（棕橙） */
  --accent-soft: #FBF0E9; /* 强调浅底 */
  --accent-hover: #B5561F;/* 强调 hover */

  /* 圆角 */
  --r-lg: 16px;   /* 面板 / 弹窗 */
  --r-md: 10px;   /* 卡片 / 摘要 */
  --r-sm: 6px;    /* 按钮 / chip / 输入框 */

  /* 动效：强缓动曲线 + 时长刻度 */
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);      /* 入场/退出 */
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);  /* 屏幕内移动 */
  --dur-fast: 120ms;    /* chip、hover 反馈 */
  --dur-base: 160ms;    /* 按钮、卡片 */
  --dur-slow: 250ms;    /* 弹窗、toast、折叠箭头 */
}
```

字号层级：标题 20（页头）/ 18（面板标题）/ 15（菜名），正文 14，辅助 13，标签 12，弱标签 11。

## 布局规范

- 页面容器 `.page`：`max-width: 1240px; padding: 40px 32px 80px`（移动端 `<700px` 时 `24px 16px 48px`）。
- 三段式：顶栏 → 入口面板（选约束）→ 主体双栏 `.main-grid: 1fr 300px`（主内容 + 侧栏，`<1024px` 时单栏）。
- 卡片统一 `background: var(--card); border: 1px solid var(--line); border-radius: var(--r-lg); padding: 20px+`。
- 侧栏放"真数据"小卡（味觉画像、剩菜再利用），不放占位快捷入口。

## 组件约定

- **场景 pill**：圆角胶囊 `border-radius: 24px`，选中态 `background: var(--accent); color: #fff`。
- **chip**（忌口/口味多选）：`background: var(--soft)`，选中 `background: var(--accent-soft); color: var(--accent); border-color: var(--accent)`。
- **菜品卡**：三栏网格 `repeat(3, 1fr)`（`<900px` 单栏），hover 仅 `translateY(-1px)` + 轻阴影，禁止大位移。
- **主按钮** `.btn-generate`：`background: var(--accent); border-radius: var(--r-sm); font-weight: 600`。
- **弹窗 modal**：遮罩 `rgba(31,30,27,0.4)`，卡片 `scale(0.97)→1` + 淡入。
- **toast**：底部居中，`opacity + translateY(10px→0)` 淡入。

## 动效规则（勿违反）

1. **禁用 `transition: all`**——只过渡明确属性（`background-color / color / border-color / transform / box-shadow / opacity`）。
2. **禁用 `ease-in`**——入场/退出用 `var(--ease-out)`，屏幕内移动用 `var(--ease-in-out)`。
3. **时长刻度**：hover/按压 `--dur-fast` 或 `--dur-base`，弹窗/toast `--dur-slow`。UI 动效一律 ≤300ms。
4. **按压反馈**：可点元素加 `:active { transform: scale(0.97); }`，保持细微。
5. **可访问性**：必须带 `@media (prefers-reduced-motion: reduce)`，去掉位移/缩放、保留颜色与透明度反馈。
6. **只动 `transform` 和 `opacity`**——不要动画 `width/height/margin/padding/top/left`。

## 改动时的检查清单

- [ ] 新组件用了现有 token，没有硬编码新颜色/新圆角/新时长
- [ ] 没有引入第三种主色（只用暖灰 + 棕橙）
- [ ] 没有 `transition: all`、没有 `ease-in`、时长 ≤300ms
- [ ] 可点元素有 `:active` 按压反馈
- [ ] 有位移/缩放的地方都有 reduced-motion 降级
- [ ] 字号用了现有层级，没有新增介于两级之间的字号
- [ ] 没有添加无真实数据支撑的占位 UI

## 参考

- 动效哲学与审计规则：全局 skill `apple-design`、`improve-animations`（`~/.pi/agent/skills/`）。
- 本 skill 由 `skill-creator` 生成，固化当前 `frontend/index.html` 的既有设计决策；改动 UI 后若 token 有变，同步更新本文件。
