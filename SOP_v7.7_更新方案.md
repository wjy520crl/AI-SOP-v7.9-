# SOP v7.7 更新方案

> 基于第一卷Ch1-5自检发现的新问题模式
> 更新日期：2026-05-12

---

## 新问题模式总结

| 模式 | 问题案例 | 影响 |
|:---|:---|:---|
| **角色设定漂移** | 蝰蛇性别：第3章"男性"→第4章"她" | 读者出戏 |
| **地点名称不一致** | 塞壬-3 vs GCS-07 | 设定混乱 |
| **物品追踪失败** | 底座位置：口袋 vs 站内 | 逻辑矛盾 |
| **章末钩子模糊** | "通讯亮了"但无内容 | 悬念失效 |
| **时间线断裂** | 第3章结尾返程→第4章直接到塔诺伦 | 叙事跳跃 |

---

## v7.7 核心升级

### 1. 浓缩包新增字段

#### 1.1 character_registry 扩展
```yaml
character_registry:
  - name: "蝰蛇"
    role: "雇佣兵"
    first_appear: "Ch3"
    # v7.7 新增：关键属性锁定
    key_attributes:
      gender: "女性"        # 锁定，不可变更
      age: 28               # 锁定
      height: "172cm"       # 锁定
      background: "零号猎兵退役"
    # v7.7 新增：属性变更日志
    attribute_change_log: []  # 任何变更必须记录
    injury_record: []
```

**规则**：gender/age/height等关键属性一旦设定，**永久锁定**。如需变更，必须在`attribute_change_log`中记录理由。

#### 1.2 location_registry 新增
```yaml
# v7.7 新增：地点注册表
location_registry:
  - canonical_name: "GCS-07"           # 规范名称
    aliases: ["废弃科考站"]             # 别名列表
    first_appear: "Ch3"
    description: "废弃盖伦特科研站"
    # 规则：所有地点必须使用canonical_name，aliases仅用于首次介绍
  
  - canonical_name: "散人港"
    aliases: ["塔诺伦空间站"]
    first_appear: "Ch1"
```

**规则**：同一地点多个名称时，必须在`location_registry`中注册，后续章节**必须使用canonical_name**。

#### 1.3 physical_anchor_items 扩展
```yaml
physical_anchor_items:
  - name: "碎平板底座"
    type: "物品"
    # v7.7 新增：位置追踪链
    location_chain:
      - chapter: "Ch3"
        location: "陆川手中"
        action: "捡走"
      - chapter: "Ch4"
        location: "陆川口袋"
        action: "携带"
      - chapter: "Ch6"
        location: "桌上"
        action: "取出"
    # v7.7 新增：位置变更必须有角色动作确认
    last_confirmed_by: "陆川"
    last_confirmed_chapter: "Ch4"
```

**规则**：物品位置变更时，必须在`location_chain`中追加记录，且**必须有角色动作确认**（谁、做了什么、在哪）。

### 2. 章末钩子质量检查清单（v7.7 新增）

```yaml
# 浓缩包 chapter_end_state 新增
chapter_end_state:
  # v7.7 新增：钩子质量检查
  hook_quality_check:
    has_hook: true                    # 是否有钩子
    hook_type: "信息型/悬念型/情绪型"  # 钩子类型
    hook_content: "老钱发来新坐标"     # 钩子具体内容
    is_specific: true                 # 是否具体（非模糊）
    character_reaction: "陆川皱眉"     # 角色反应
    
  # 钩子质量标准
  # - 必须有明确指向（谁、什么、为什么）
  # - 禁止："通讯亮了""有人来了"等模糊表述
  # - 推荐："老钱发来新坐标，报酬三倍""蝰蛇警告：坐标不是你们能碰的"
```

**规则**：章末钩子必须通过`hook_quality_check`，`is_specific`必须为`true`。

### 3. 时间线连续性检查（v7.7 新增）

```yaml
# 浓缩包新增
timeline_continuity:
  current_chapter: "Ch4"
  previous_chapter_end: "Ch3"
  # v7.7 新增：章节间过渡检查
  transition_check:
    time_gap: "2天"                    # 时间跨度
    location_change: "GCS-07→塔诺伦"   # 地点变化
    has_transition: true               # 是否有过渡段落
    transition_summary: "返程航行两天"  # 过渡内容摘要
```

**规则**：如果`time_gap`>0或`location_change`存在，必须有`has_transition: true`和`transition_summary`。

### 4. sop_scanner.py 新增检测（v7.7）

#### 4.1 角色关键属性一致性检测
```python
def scan_character_attribute_consistency(text, character_registry):
    """
    扫描角色关键属性是否与注册表一致
    检测：gender/age/height等是否匹配
    """
    pass
```

#### 4.2 地点名称规范检测
```python
def scan_location_name_canonical(text, location_registry):
    """
    扫描地点名称是否使用canonical_name
    检测：是否使用了未注册的别名
    """
    pass
```

#### 4.3 物品位置追踪检测
```python
def scan_item_location_chain(text, physical_anchor_items):
    """
    扫描物品位置变更是否有记录
    检测：位置变更时是否有角色动作确认
    """
    pass
```

#### 4.4 章末钩子质量检测
```python
def scan_hook_quality(text):
    """
    扫描章末钩子质量
    检测：是否具体、是否有角色反应、是否模糊
    """
    pass
```

#### 4.5 时间线过渡检测
```python
def scan_timeline_transition(text, timeline_continuity):
    """
    扫描章节间过渡
    检测：时间/地点变化时是否有过渡段落
    """
    pass
```

### 5. 预提交清单 v7.7（10步）

```
□ 1. 运行 sop_scanner.py —— 附完整输出截图
□ 2. 核对截图与自检报告 —— 差异必须为0%
□ 3. 检查 character_registry —— 关键属性是否锁定
□ 4. 检查 location_registry —— 地点名称是否规范
□ 5. 检查 physical_anchor_items —— 物品位置是否有变更记录
□ 6. 检查 hook_quality_check —— 钩子是否具体
□ 7. 检查 timeline_continuity —— 章节过渡是否完整
□ 8. 人工快速浏览 —— 检查扫描器遗漏的语境问题
□ 9. 核对浓缩包 —— 所有强制字段填写完整
□ 10. 签字确认 —— 调度者签字+时间戳
```

---

## 实施计划

| 阶段 | 任务 | 时间 |
|:---|:---|:---|
| 第1阶段 | 更新流水线SOP.md | 0.5天 |
| 第2阶段 | 更新sop_scanner.py | 0.5天 |
| 第3阶段 | 更新浓缩包模板 | 0.5天 |
| 第4阶段 | 第一卷Ch6-10试点 | 持续 |

---

## 预期效果

| 问题模式 | v7.6发生率 | v7.7目标 |
|:---|:---:|:---:|
| 角色设定漂移 | 1处/5章 | 0处 |
| 地点名称不一致 | 1处/5章 | 0处 |
| 物品追踪失败 | 1处/5章 | 0处 |
| 章末钩子模糊 | 2处/5章 | 0处 |
| 时间线断裂 | 3处/5章 | 0处 |
