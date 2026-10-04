# 🍳 今天吃什么 · 家庭餐桌助手

> 从"不知道吃什么"到"菜端上桌"，全流程帮你搞定。

输入几句话，得到一份完整方案：**吃什么 → 买什么 → 怎么做 → 营养如何**。

核心差异化：**约束内随机** —— 不做完全随机，也不做完全精准，而是在你的约束范围内"惊喜但不离谱"地推荐。为每个用户构建专属的"三层菜市场"。

## ✨ 特性

- **约束内随机推荐**：忌口/过敏/设备/预算/时间做硬约束过滤，口味/食材复用/荤素做软约束打分，加权随机 + 组合校验
- **全流程方案**：菜单组合 → 合并采购清单（分区+同类项合并）→ 营养粗估 → 分步做法
- **周计划（v0.2）**：一次生成 N 天菜单，全程不重样，自动合并整周采购清单
- **家庭味觉画像（v0.2）**：点 👍/👎 记口味，沉淀爱吃的口味/食材/菜，反哺推荐打分
- **一菜两吃（v0.2）**：输入剩菜名，复用其实质主料，推荐二次加工做法
- **BYOK**：自带 LLM Key，支持 DeepSeek / GLM / Qwen / Moonshot / Ollama 等所有 OpenAI 兼容接口
- **零依赖可跑**：不配 LLM 也能完整推荐（规则引擎），配了 Key 则叠加智能搭配说明
- **372 道中式家常菜**：内置结构化菜谱（难度/耗时/卡路里/原料/用量/分步做法）
- **纯本地**：数据全存本地，可完全离线（配 Ollama）

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
cp .env.example .env   # 可选
uvicorn app.main:app --reload
# 打开 http://localhost:8000
```

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

## 📦 项目结构

```
app/
├── main.py              FastAPI 入口 + API 路由
├── config.py            BYOK 配置（.env + 运行时设置）
├── core/
│   ├── constraint_engine.py   约束内随机引擎
│   ├── rules.py               忌口/过敏/设备/口味规则表 + 调料过滤
│   ├── shopping.py            采购清单合并
│   ├── nutrition.py           营养粗估
│   ├── profile.py             家庭味觉画像（v0.2）
│   ├── weekly.py              周计划生成器（v0.2）
│   └── leftover.py            一菜两吃（v0.2）
├── agents/planner.py    方案编排器
└── llm/client.py        OpenAI 兼容客户端
data/recipes.json        372 道结构化菜谱
scripts/                 HowToCook 下载器 + 解析器
frontend/index.html      单文件前端
```

## 📖 数据来源

菜谱数据来自 [Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook)（Unlicense，公共领域），经 `scripts/parse_recipes.py` 解析为结构化 JSON。

## 🗺️ 路线图

- [x] v0.1 单餐闭环：约束内随机 + 372 道菜 + 采购清单 + 做法
- [x] v0.2 周计划 + 家庭味觉画像 + 一菜两吃
- [ ] v0.3 多 Agent 真编排（LangGraph）
- [ ] v0.4 场景模板（便当/家宴/控糖）+ 本地模型完整支持

## 📄 协议

MIT License。菜谱数据为 HowToCook（Unlicense）衍生，同样可自由使用。
