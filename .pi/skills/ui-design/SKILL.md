---
name: ui-design
description: 本项目「今天吃什么」前端 UI 的设计规范与样式约定。包含设计 tokens（纸白底 + 墨字 + 葱绿强调色、圆角、字号层级、缓动曲线与时长）、布局与组件规范、动效规则。用于修改 frontend/index.html、新增或调整组件、改配色/间距/字号、加动效、或审查视觉一致性时。
---

# UI 设计规范（今天吃什么）

单文件前端 `frontend/index.html`（原生 HTML + CSS + vanilla JS，无框架、无动效库）。
改 UI 时遵循本规范，保持"简约、克制、不眼花缭乱"。

## 设计原则

1. **一个主路径**：用户看页面只做一件事——选场景、调人数、点「生成」。次要功能一律收进折叠/侧栏，不抢主视觉。
2. **克制配色**：纸白做底、墨色为字，只用一种葱绿 `--accent` 做强调，绝不再引入第三种主色。
3. **留白与层级**：靠留白和字号层级（20/18/15/14/13/12/11）区分信息，不用重边框或大阴影。
4. **动效只为正确性**：动效用来解释状态变化（从哪来、到哪去），不为了"好看"。加动效前先问"为什么动"。
5. **不要占位内容**：没有真实数据支撑的元素一律不展示，宁可留白。

## Design Tokens（直接复用，勿另造）

```css
:root {
  /* 颜色 */
  --bg: #F7F4EE;          /* 页面底（纸白） */
  --card: #FFFFFF;        /* 卡片 */
  --soft: #F1EFE8;        /* 浅填充（chip 底） */
  --hover: #EAE7DD;       /* hover 填充 */
  --entry-bg: #FBF9F1;    /* 入口面板 / 摘要 / 菜单条目 hover 底（暖纸） */
  --t1: #2A2722;          /* 主文字（墨） */
  --t2: #6E6A61;          /* 次文字 */
  --t3: #A09B8F;          /* 弱文字 / 占位 */
  --line: #E9E5DA;        /* 分隔线 */
  --line2: #DBD6C9;       /* 边框 */
  --accent: #4A6B3A;      /* 强调色（葱绿） */
  --accent-soft: #EDF1E5; /* 强调浅底 */
  --accent-hover: #3C572E;/* 强调 hover */

  /* 圆角 */
  --r-lg: 16px;   /* 面板 / 弹窗 */
  --r-md: 10px;   /* 卡片 / 摘要 */
  --r-sm: 6px;    /* 按钮 / chip / 输入框 */

  /* 字体：宋体只做菜名/标题，其余无衬线 */
  --serif: "Songti SC", "STSong", "SimSun", "Noto Serif SC", serif;

  /* 动效：强缓动曲线 + 时长刻度 */
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);      /* 入场/退出 */
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);  /* 屏幕内移动 */
  --dur-fast: 120ms;    /* chip、hover 反馈 */
  --dur-base: 160ms;    /* 按钮、卡片 */
  --dur-slow: 250ms;    /* 弹窗、toast、折叠箭头 */
}
```

字号层级：标题 20（页头·宋体）/ 18（面板标题、菜名·宋体）/ 15（弹窗标题、关闭按钮），正文 14，辅助 13，标签 12，弱标签 11。

## 布局规范

- 页面容器 `.page`：`max-width: 1240px; padding: 40px 32px 80px`（移动端 `<700px` 时 `24px 16px 48px`）。
- 三段式：顶栏 → 入口面板（选约束）→ 主体双栏 `.main-grid: 1fr 300px`（主内容 + 侧栏，`<1024px` 时单栏）。
- 卡片统一 `background: var(--card); border: 1px solid var(--line); border-radius: var(--r-lg); padding: 20px+`。
- 侧栏放"真数据"小卡（味觉画像、剩菜再利用），不放占位快捷入口。

## 组件约定

- **场景 pill**：圆角胶囊 `border-radius: 24px`，选中态 `background: var(--accent); color: #fff`。
- **chip**（忌口/口味多选）：`background: var(--soft)`，选中 `background: var(--accent-soft); color: var(--accent); border-color: var(--accent)`。
- **菜品条目**：纵向列表（`.dish-grid` flex column），每道菜一行 `border-bottom` 分隔；菜名宋体 18px 固定宽 180px 做主角，口味/时令/难度/热量弱化居中，操作按钮右置；「再加工 / 简化做法」为次级按钮，hover 淡入。
- **主按钮** `.btn-generate`：`background: var(--accent); border-radius: var(--r-sm); font-weight: 600`。
- **弹窗 modal**：遮罩 `rgba(42,39,34,0.4)`，卡片 `scale(0.97)→1` + 淡入。
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
- [ ] 没有引入第三种主色（只用暖灰 + 葱绿）
- [ ] 没有 `transition: all`、没有 `ease-in`、时长 ≤300ms
- [ ] 可点元素有 `:active` 按压反馈
- [ ] 有位移/缩放的地方都有 reduced-motion 降级
- [ ] 字号用了现有层级，没有新增介于两级之间的字号
- [ ] 没有添加无真实数据支撑的占位 UI

## 参考

- 动效哲学与审计规则：全局 skill `apple-design`、`improve-animations`（`~/.pi/agent/skills/`）。
- 本 skill 由 `skill-creator` 生成，固化当前 `frontend/index.html` 的既有设计决策；改动 UI 后若 token 有变，同步更新本文件。
