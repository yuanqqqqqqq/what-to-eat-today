# 🍳 今天吃什么 · 家庭餐桌助手

> 从"不知道吃什么"到"菜端上桌"，全流程帮你搞定。

输入几句话，得到一份完整方案：**吃什么 → 买什么 → 怎么做 → 营养如何**。

核心差异化：**约束内随机** —— 不做完全随机，也不做完全精准，而是在你的约束范围内"惊喜但不离谱"地推荐。为每个用户构建专属的"三层菜市场"。

## ✨ 特性

- **约束内随机推荐**：忌口/过敏/设备/预算/时间做硬约束过滤，口味/时令/收藏/食材复用做软约束打分，加权随机 + 组合校验
- **家常化**：默认排除名贵食材（鲍鱼龙虾等）、牛羊肉、西式/异国菜，只出真正家常的菜
- **全流程方案**：菜单 → 合并采购清单（主菜/配菜/小料/调料四类）→ 分步做法（点击菜名即看）
- **周计划**：一次生成 N 天菜单，全程不重样，自动合并整周采购清单
- **喜好**：记录我的口味、讨厌食材、常备食材、收藏菜品，生成时自动生效
- **菜市场**：自定义食材价格（增删改），接入成本估算
- **搜菜 / 加菜**：搜全量菜谱（含被家常化过滤的），添加自己的菜（可设难度/耗时）
- **锁定 + 收藏**：锁定的菜下次随机一定保留，收藏的菜更常出现
- **场景模板**：便当 / 家宴 / 控糖 / 减脂轻食 / 家常，一键预设约束
- **BYOK**：配了 LLM Key 则叠加智能搭配说明（DeepSeek / GLM / Qwen / Moonshot / Ollama 等）
- **纯本地**：数据全存本地，不配 LLM 也能完整推荐（纯规则引擎）
- **372 道中式家常菜**：内置结构化菜谱（难度/耗时/原料/用量/分步做法），经过数据清洗

## 🚀 快速开始

### Docker 一键启动（推荐）

```bash
cp .env.example .env   # 可选：填 LLM Key（也可启动后在前端面板填）
docker compose up -d
# 打开 http://localhost:8000
```

### 本地运行

```bash
pip install -r requirements.txt
python run.py   # 起服务 + 自动打开浏览器
# 或：uvicorn app.main:app --reload
```

### 打包成 exe（Windows，无需装 Python）

```bash
build.bat   # 生成 dist\今天吃什么.exe
```

双击 `今天吃什么.exe` 即可使用（自动打开浏览器）。用户数据（自定义菜谱/价格/常备食材）存在 exe 旁边的 `data\` 目录。

首次使用：打开页面 → 点"⚙️ LLM 设置"填入你的 `base_url / api_key / model`（不填也能用，只是没有智能搭配说明）。

## 🧠 约束内随机引擎（产品灵魂）

```
第一步：硬约束过滤  → 忌口、过敏、设备、预算、时间
第二步：软约束打分  → 食材复用、口味偏好
第三步：加权随机    → 高分菜概率高，低分菜概率低但非零
第四步：组合校验    → 几菜几汤、荤素搭配、不重复
```

纯确定性代码实现（`app/core/constraint_engine.py`），可复现、零 token 消耗。

## 🏗️ 架构

```
用户输入（表单）
   ↓
[约束引擎] 硬过滤 + 加权随机 → 菜单         (代码，确定性)
   ↓
[采购员]   合并清单 + 分区                   (代码)
[营养师]   热量 + 荤素比                     (代码)
[搭配师]   搭配说明文案                      (LLM 可选，无 Key 用模板)
   ↓
完整方案 JSON → 前端渲染
```

## 🤖 多 Agent 编排（v0.3）

用 LangGraph 把"规则流水线"升级为"有状态、可回退"的多 Agent 工作流：

```
规划师(planner) → 营养师(nutritionist) ──不达标且未超轮次──┐
        ▲             │ 达标                    │
        │             ▼                         │
        └─────── 采购员(shopper) → 搭配师(writer) │
                          └──────────────────────┘
```

- **规划师**：约束引擎出菜单
- **营养师**：营养分析 + 达标评估（规则版，可复现）
- **条件路由**：不达标（缺蔬菜/热量偏高/蛋白质偏少）→ 回退规划师重选（最多 3 轮）
- **采购师 / 搭配师**：清单合并 / 搭配文案（LLM 优先，无 Key 用模板）

每个节点无 LLM 也能跑通（BYOK 友好）。返回结果带 `agent_trace`，前端可展开查看编排过程。
接口：`POST /api/plan/graph`（单餐多 Agent），`POST /api/recommend`（经典流水线）。

## 📦 项目结构

```
app/
├── main.py              FastAPI 入口 + API 路由
├── config.py            BYOK 配置（.env + 运行时设置）
├── paths.py             路径统一（区分只读资源与可写数据，支持打包）
├── core/
│   ├── constraint_engine.py   约束内随机引擎
│   ├── rules.py               忌口/过敏/设备/口味规则 + 家常化过滤
│   ├── shopping.py            采购清单合并（主菜/配菜/小料/调料）
│   ├── nutrition.py           营养粗估
│   ├── profile.py             口味画像（软约束打分）
│   ├── weekly.py              周计划生成器
│   ├── scenes.py              场景模板
│   └── food_db.py             食物成分表查询 + 热量/价格估算
├── agents/
│   ├── planner.py        方案编排器（规则流水线）
│   └── orchestrator.py   多 Agent 编排（LangGraph，v0.3）
└── llm/client.py        OpenAI 兼容客户端
data/recipes.json        372 道结构化菜谱
scripts/                 HowToCook 下载器 + 解析器
frontend/index.html      单文件前端
```

## 📖 数据来源

菜谱数据来自 [Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook)（Unlicense，公共领域），经 `scripts/parse_recipes.py` 解析为结构化 JSON。

热量数据来自 [中国食物成分表（第 6 版）](https://github.com/Sanotsu/china-food-composition-data)，由 `scripts/download_food_composition.py` 下载合并为 `data/food_composition.json`，再由 `scripts/recalc_calories.py` 按"主料密度 × 用量"重算每道菜热量。

## 🗺️ 路线图

- [x] v0.1 单餐闭环：约束内随机 + 372 道菜 + 采购清单 + 做法
- [x] v0.2 周计划 + 家庭味觉画像 + 一菜两吃
- [x] v0.3 多 Agent 真编排（LangGraph）
- [x] v0.4 场景模板（便当/家宴/控糖）+ 本地模型完整支持

## 📄 协议

MIT License。菜谱数据为 HowToCook（Unlicense）衍生，同样可自由使用。
