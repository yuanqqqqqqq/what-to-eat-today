# -*- coding: utf-8 -*-
"""按 improve-animations 审计结论，对 frontend/index.html 落地动效优化。"""
import io

p = "frontend/index.html"
t = open(p, encoding="utf-8").read()

def rep(old, new, label):
    global t
    n = t.count(old)
    if n == 0:
        print(f"  [WARN] 未找到: {label} ({old[:40]}...)")
        return
    t = t.replace(old, new)
    print(f"  [OK] {label}: 替换 {n} 处")

# 1. 动效 tokens
rep(
    "    --r-lg: 16px;\n    --r-md: 10px;\n    --r-sm: 6px;\n  }",
    "    --r-lg: 16px;\n    --r-md: 10px;\n    --r-sm: 6px;\n\n"
    "    /* 动效 tokens（克制 + 强缓动曲线） */\n"
    "    --ease-out: cubic-bezier(0.23, 1, 0.32, 1);\n"
    "    --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);\n"
    "    --dur-fast: 120ms;\n"
    "    --dur-base: 160ms;\n"
    "    --dur-slow: 250ms;\n  }",
    "tokens",
)

# 2. 菜卡（先精确替换，含 transform + box-shadow）
rep(
    "border-radius: var(--r-md); transition: all 0.15s;",
    "border-radius: var(--r-md); transition: transform var(--dur-base) var(--ease-out), "
    "box-shadow var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out);",
    "dish-card",
)

# 3. 其余 transition: all 0.15s → 颜色类 + transform
COLOR_FAST = ("transition: background-color var(--dur-fast) var(--ease-out), "
              "color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), "
              "transform var(--dur-fast) var(--ease-out);")
COLOR_BASE = ("transition: background-color var(--dur-base) var(--ease-out), "
              "color var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out), "
              "transform var(--dur-base) var(--ease-out);")
rep("transition: all 0.15s;", COLOR_BASE, "all 0.15s → 颜色+transform")
rep("transition: all 0.12s;", COLOR_FAST, "all 0.12s → 颜色+transform")

# 4. toast
rep("transition: all 0.25s;",
    "transition: opacity var(--dur-slow) var(--ease-out), transform var(--dur-slow) var(--ease-out);",
    "toast")

# 5. background / transform / border-color
rep("transition: background 0.15s;",
    "transition: background-color var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);",
    "background")
rep("transition: transform 0.2s;",
    "transition: transform var(--dur-slow) var(--ease-out);",
    "transform 0.2s")
rep("transition: border-color 0.15s;",
    "transition: border-color var(--dur-base) var(--ease-out);",
    "border-color")

# 6. 按压反馈 + reduced-motion（插在 </style> 前）
press_and_rm = """  /* ========== 按压反馈 ========== */
  button:active, .chip:active, .scene-pill:active, .day-chip:active {
    transform: scale(0.97);
  }

  /* ========== 减弱动效：去掉位移/缩放，保留颜色与透明度反馈 ========== */
  @media (prefers-reduced-motion: reduce) {
    .dish-card:hover { transform: none; }
    #toast, #toast.show { transform: translateX(-50%); }
    .advanced-toggle .arrow, .disclosure .arrow { transition: none; }
    button:active, .chip:active, .scene-pill:active, .day-chip:active { transform: none; }
  }
</style>"""
rep("</style>", press_and_rm, "按压反馈 + reduced-motion")

open(p, "w", encoding="utf-8").write(t)
print("\n完成，已写回", p)
