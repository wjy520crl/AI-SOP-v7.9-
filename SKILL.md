---
name: novel_creator
description: 小说多智能体协同创作系统 — SOP v6.8流水线，5个Agent协作，35章/卷
---

# 📖 novel_creator — 小说多智能体协同创作系统

> 基于 CoPaw 的章节流水线创作系统。协调者直调模式，5个Agent按步骤接力。

## 当前架构（SOP v6.8）

```
协调者（小林）
  ↓ 步骤1：发送章纲+浓缩包+写作偏好+自检清单
  novel-chapter-writer（主笔初稿）
  ↓ 步骤2：台词优化+氛围增润
  novel-dialogue-editor（台词优化）
  ↓ 步骤3：100分制质检
  novel-quality-reviewer（质检）
  ↓ 步骤4：正本存盘 + CKP-2验证
  ↓ 步骤5：浓缩包更新 + CKP-3验证
  ↓ 步骤6：发用户
  ↓ 步骤7：自进化日志
  ↓ 步骤8：每10章回顾
```

## Agent 列表（实际运行中）

| Agent ID | 职责 | 调用方式 |
|----------|------|---------|
| `novel-chapter-writer` | 章节主笔，撰写初稿 | chat_with_agent（新session） |
| `novel-dialogue-editor` | 台词优化，氛围增润 | chat_with_agent |
| `novel-quality-reviewer` | 100分制质检 | chat_with_agent |
| `novel-memory-archive` | 记忆存储（基建阶段） | 基建专用 |
| 协调者 | 调度+工程自检+自进化+回顾 | 用户（小林） |

> ⚠️ 以下Agent已废弃：novel-node-controller, novel-node-outliner, novel-node-writer。配置JSON已标注DEPRECATED。

## 核心文件

| 文件 | 说明 |
|------|------|
| `流水线SOP.md` | 权威文档。全流程定义 |
| `写作偏好_共享.md` | 文笔五律+硬核六条+AI味禁区 v2.4 |
| `主笔自检清单.md` | 主笔提交前逐条核对 v1.4 |
| `SOP工程自检模块.md` | 工程质量检查（CKP-0/1/2/3）v1.1 |
| `第一卷浓缩包.md` | 前文章节摘要，每章更新 |
| `archives/novel_settings/第一卷详细章纲.md` | 35章完整章纲 |
| `archives/自进化日志.md` | 每章自进化记录 |
| `archives/回顾报告_第XX章.md` | 每10章五维回顾 |

## 文件结构

```
novel_creator/
├── SKILL.md                       # 本文件
├── 流水线SOP.md                    # 权威流程文档
├── 写作偏好_共享.md                # 全部写作规则
├── 主笔自检清单.md                 # 主笔自检
├── SOP工程自检模块.md              # 工程检查
├── 第一卷浓缩包.md                 # 章节摘要
├── agents/                        # Agent JSON配置
│   ├── novel_chapter_writer.json  # 当前主笔
│   ├── novel_dialogue_editor.json # 台词优化 v1.4
│   ├── novel_quality_reviewer.json # 质检 v1.4
│   ├── novel_node_*.json          # 【已废弃】
│   └── create_agents.py           # 批量注册脚本
├── chapters/第一卷/               # 正本存盘
│   └── 第X章_标题.md
├── archives/                      # 档案
│   ├── novel_settings/            # 章纲+设定
│   ├── 自进化日志.md
│   ├── 回顾报告_第XX章.md
│   ├── FLOW_GUIDE.md              # 【已废弃】
│   ├── 工程自检日志.md
│   └── 系统审查报告_2026-05-04.md
└── memory/                        # 协调者记忆
```

## 快速开始

1. 阅读 `流水线SOP.md` → 理解全流程
2. 阅读 `写作偏好_共享.md` → 理解规则
3. 查看 `第一卷浓缩包.md` → 了解当前进度
4. 查看 `archives/novel_settings/第一卷详细章纲.md` → 定位下一章

## 质量标准

- 连续12章零返工（Ch9→Ch20）
- AI味连续9章满分（Ch12→Ch20）
- 「不是…是…」连续5章三端归零（Ch16→Ch20）
- 第一卷 20/35章完成（57.1%）

---

*最后更新：2026-05-04 | 从全系统审查中重建*
