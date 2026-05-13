#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SOP v7.8 强制扫描脚本
=====================
自动化扫描小说章节，检测以下问题：
1. 冻结意象重复
2. 「不是...是...」句式（零容忍，含破折号变体）
3. 参数连珠炮（连续数字句）
4. 句式模板重复
5. 章节号引用验证
6. 时间锚点一致性（v7.6 新增）
7. 物象状态观察者确认（v7.6 新增）
8. 伤势-行动时间冲突（v7.6 新增）
9. 角色关键属性一致性（v7.7 新增）
10. 地点名称规范性（v7.7 新增）
11. 物品位置追踪链（v7.7 新增）
12. 章末钩子质量（v7.7 新增）
13. 时间线过渡完整性（v7.7 新增）

作者：工具开发工程师
版本：v7.8
日期：2026-05-12

v7.8 更新：
- 扫描器修复：scan_bushi_pattern/scan_time_anchor_consistency/scan_item_status_observer/scan_injury_action_conflict
  全部改用_get_content_lines_only()排除元数据区域误报
- 句式模板阈值收紧：从10次/章收紧到5次/章
- location_registry升级为强制字段
- hook_quality_check升级为强制字段

v7.7 更新：
- 新增跨章一致性强制检查：角色属性、地点名称、物品位置、钩子质量、时间线过渡
- 预提交清单从7步扩展为10步

v7.6 更新：
- 新增截图友好模式输出（时间戳、章节名、总评颜色、验证水印）
- 用于自检报告强制验证，差异>0%即熔断
- 新增三类盲区检测：时间锚点一致性、物象状态观察者、伤势-行动时间冲突
"""

import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


# ============================================================================
# 配置常量
# ============================================================================

# 冻结意象列表 - 这些词汇过度使用会导致读者疲劳
FROZEN_IMAGERY = [
    "指节发白", "嘴角勾起", "倒吸一口凉气",
    "眼窝深陷", "嘴唇干裂", "空气凝固",
    "时间仿佛静止", "折叠椅铁管硌肩胛骨",
    "座椅弹簧硌后背"
]

# 句式模板正则表达式
TEMPLATE_PATTERNS = [
    (r"嘴角[^，。！？\n]{0,5}了一下", "嘴角*了一下"),      # 嘴角动了一下
    (r"手指[^，。！？\n]{0,5}紧", "手指*紧"),              # 手指攥紧
    (r"手指[^，。！？\n]{0,5}敲", "手指*敲"),              # 手指在XX上敲了敲（v7.4新增）
    (r"手指[^，。！？\n]{0,5}停", "手指*停"),              # 手指停在XX上（v7.4新增）
    (r"手指[^，。！？\n]{0,5}收紧", "手指*收紧"),           # 手指收紧（v7.4新增）
    (r"沉默了[^，。！？\n]{0,10}", "沉默了*"),             # 沉默了几秒/一阵（v7.4新增）
    (r"安静了[^，。！？\n]{0,10}", "安静了*"),             # 安静了一阵/片刻（v7.4新增）
    (r"座椅[^，。！？\n]{0,5}硌", "座椅*硌"),              # 座椅导轨硌
    (r"第[一二三四五六七八九十百千万]+章", "第*章引用")     # 章节号引用
]

# 「不是...是...」正则模式（v7.4 扩展：零容忍，含破折号变体）
BUSHI_PATTERNS = [
    r"不是[^，。！？\n]{0,30}是",           # 不是A，是B
    r"不是[^，。！？\n]{0,30}——是",        # 不是A——是B（破折号）
    r"不是[^，。！？\n]{0,30}——\s*是",     # 不是A—— 是B（破折号+空格）
]

# 阈值配置
THRESHOLDS = {
    "bushi_per_chapter": 0,      # 「不是...是...」每章阈值（v7.4 零容忍）
    "template_repeat": 5,         # 模板重复阈值（v7.8 调整：每章最多5次）
    "number_sentence_streak": 3   # 数字句连续阈值
}

# 替换模板库（v7.5 新增）
REPLACEMENT_TEMPLATES = {
    "手指*敲": ["拇指摩挲", "手掌按在", "拳头攥紧", "指甲抠进掌心"],
    "手指*停": ["指尖悬在半空", "手僵住了", "动作顿住"],
    "手指*收紧": ["指节用力到发白", "掌心攥出汗", "手指绞在一起"],
    "沉默了*": ["没说话", "没接话", "没再说话", "停顿", "过了几秒"],
    "安静了*": ["没人接话", "气氛沉下来", "声音断了"],
}


# ============================================================================
# 扫描器类
# ============================================================================

class SOPScanner:
    """SOP v7.7 扫描器主类（截图友好模式）"""
    
    def __init__(self, chapter_path: str, window: int = 5, verbose: bool = False):
        """
        初始化扫描器
        
        Args:
            chapter_path: 当前章节文件路径
            window: 扫描窗口（最近N章）
            verbose: 是否详细输出
        """
        self.chapter_path = Path(chapter_path)
        self.window = window
        self.verbose = verbose
        self.content = ""
        self.lines: List[str] = []
        self.chapter_name = self.chapter_path.stem
        
        # 结果存储
        self.results = {
            "frozen_imagery": [],
            "bushi_pattern": [],
            "number_streak": [],
            "template_repeat": {},
            "chapter_reference": [],
            "time_anchor_consistency": [],      # v7.6 新增
            "item_status_observer": [],         # v7.6 新增
            "injury_action_conflict": [],       # v7.6 新增
            "character_attribute_consistency": [],  # v7.7 新增
            "location_name_canonical": [],      # v7.7 新增
            "item_location_chain": [],          # v7.7 新增
            "hook_quality": [],                 # v7.7 新增
            "timeline_transition": []           # v7.7 新增
        }
        
        # 错误级别统计
        self.warnings = 0   # 黄色警告
        self.errors = 0     # 红色错误
        self.suggestions = 0  # 建议优化
    
    def load_chapter(self) -> bool:
        """
        加载章节内容
        
        Returns:
            是否成功加载
        """
        if not self.chapter_path.exists():
            print(f"错误：章节文件不存在 - {self.chapter_path}")
            return False
        
        try:
            with open(self.chapter_path, 'r', encoding='utf-8') as f:
                self.content = f.read()
            self.lines = self.content.split('\n')
            return True
        except Exception as e:
            print(f"错误：读取文件失败 - {e}")
            return False
    
    def get_recent_chapters(self) -> List[Path]:
        """
        获取最近N章的文件路径
        
        Returns:
            章节文件路径列表
        """
        # 获取章节所在目录
        chapter_dir = self.chapter_path.parent
        
        # 获取所有章节文件
        chapter_files = sorted(chapter_dir.glob("第*章*.md"))
        
        # 找到当前章节的位置
        try:
            current_idx = chapter_files.index(self.chapter_path)
        except ValueError:
            # 如果找不到，返回最近的window个章节
            return chapter_files[-self.window:] if len(chapter_files) >= self.window else chapter_files
        
        # 返回从当前章节往前window个章节
        start_idx = max(0, current_idx - self.window + 1)
        return chapter_files[start_idx:current_idx + 1]
    
    # ------------------------------------------------------------------------
    # 扫描功能实现
    # ------------------------------------------------------------------------
    
    def _get_content_lines_only(self) -> List[Tuple[int, str]]:
        """
        获取仅包含正文的行（排除元数据区域）
        
        Returns:
            [(行号, 行内容), ...]
        """
        content_lines = []
        in_metadata = False
        metadata_permanent = False  # 一旦遇到永久标记，后面全部视为metadata
        # 注意：--- 和 ``` 已在上面单独处理（精确匹配），不放入此列表
        # 否则 "---" 会 substring 匹配表格分隔行 "|--------|----------|"
        metadata_markers = [
            "# 章节", "chapter_end_state:", "imagery_registry:",
            "character_registry:", "time_anchors:", "physical_anchor_items:",
            "ship_status:", "硬约束检查", "D22", "D23", "D24", "D25",
            "D26", "D27", "D28", "hook_quality_check", "location_registry:",
            "质检确认", "imagery_registry", "pre_submit_checklist",
            "writer_self_check", "sop_v7", "cross_reference_notes",
            "quality_verification:", "pending_abstractions:", "injury_record:",
            "status_change_log:", "attribute_change_log:", "deviation_log:",
            "emotional_pressure_map:", "timeline_continuity:"
        ]
        # 永久metadata标记：遇到后，后续所有内容都是metadata
        permanent_markers = ["硬约束检查", "chapter_end_state:", "质检确认"]
        
        for line_num, line in enumerate(self.lines, 1):
            stripped = line.strip()
            
            # 永久metadata标记：一旦触发，后面全部跳过
            if metadata_permanent:
                continue
            if any(pmarker in stripped for pmarker in permanent_markers):
                metadata_permanent = True
                continue
            
            # 检测元数据区域开始/结束（精确匹配）
            if stripped == "---":
                in_metadata = not in_metadata
                continue
            
            # ``` 在非metadata区域时进入metadata（代码块是metadata格式）
            # 在metadata区域内时忽略（避免 toggle 破坏状态）
            if stripped.startswith("```"):
                if not in_metadata:
                    in_metadata = True
                continue
            
            # 检测元数据标记（substring 匹配，但不含 ---/```）
            if any(marker in stripped for marker in metadata_markers):
                in_metadata = True
                continue
            
            # 如果在元数据区域内，跳过
            if in_metadata:
                continue
            
            # 只保留非空行且不是纯标记的行
            if stripped and not stripped.startswith("#") and not stripped.startswith("**【第"):
                content_lines.append((line_num, line))
        
        return content_lines
    
    @staticmethod
    def _filter_metadata_lines(lines: List[str]) -> List[Tuple[int, str]]:
        """
        过滤元数据行，只保留正文（用于外部文件扫描）
        
        Args:
            lines: 原始行列表
            
        Returns:
            [(行号, 行内容), ...]
        """
        content_lines = []
        in_metadata = False
        metadata_markers = [
            "---", "```", "# 章节", "# 第",
            "chapter_end_state:", "imagery_registry:", "character_registry:",
            "time_anchors:", "physical_anchor_items:", "ship_status:",
            "location_registry:", "timeline_continuity:", "hook_quality_check:",
            "deviation_log:", "emotional_pressure_map:", "pre_submit_checklist:",
            "writer_self_check:", "sop_v7", "cross_reference_notes:",
            "quality_verification:", "pending_abstractions:", "injury_record:",
            "status_change_log:", "attribute_change_log:"
        ]
        
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            
            if stripped == "---" or stripped.startswith("```"):
                in_metadata = not in_metadata
                continue
            
            if any(marker in stripped for marker in metadata_markers):
                in_metadata = True
                continue
            
            if in_metadata:
                continue
            
            if stripped and not stripped.startswith("#") and not stripped.startswith("**【第"):
                content_lines.append((line_num, line))
        
        return content_lines
    
    def scan_frozen_imagery(self) -> Tuple[int, List[Tuple[int, str]]]:
        """
        扫描冻结意象（v7.6 修复：只扫描正文，排除元数据）
        
        Returns:
            (匹配数量, [(行号, 匹配文本), ...])
        """
        matches = []
        content_lines = self._get_content_lines_only()
        
        for line_num, line in content_lines:
            for imagery in FROZEN_IMAGERY:
                if imagery in line:
                    matches.append((line_num, imagery))
        
        self.results["frozen_imagery"] = matches
        
        # v7.6：任何冻结意象都是红色错误
        if len(matches) > 0:
            self.errors += 1
        
        return len(matches), matches
    
    def scan_bushi_pattern(self) -> Tuple[int, List[Tuple[int, str]]]:
        """
        扫描「不是...是...」句式（v7.4 零容忍，含破折号变体）
        
        Returns:
            (匹配数量, [(行号, 匹配文本), ...])
        """
        compiled_patterns = [re.compile(p) for p in BUSHI_PATTERNS]
        matches = []
        
        # v7.7 修复：只扫描正文，排除元数据区域
        content_lines = self._get_content_lines_only()
        
        for line_num, line in content_lines:
            for pattern in compiled_patterns:
                found = pattern.findall(line)
                for match in found:
                    # 去重：同一行同一匹配文本不重复记录
                    if (line_num, match) not in matches:
                        matches.append((line_num, match))
        
        self.results["bushi_pattern"] = matches
        
        # v7.4 零容忍：>0处即为红色错误
        if len(matches) > 0:
            self.errors += 1
        
        return len(matches), matches
    
    def scan_number_streak(self) -> List[Tuple[int, int, str]]:
        """
        检测参数连珠炮（连续N句含数字）
        
        Returns:
            [(起始行号, 结束行号, 摘要), ...]
        """
        # 按句号分割句子，同时记录行号
        sentences_with_lines = []
        current_line = 1
        current_text = ""
        
        for char in self.content:
            if char == '\n':
                current_line += 1
            current_text += char
            
            # 遇到句号，保存句子
            if char in '。！？':
                if current_text.strip():
                    sentences_with_lines.append((current_line, current_text.strip()))
                current_text = ""
        
        # 检测连续数字句
        streaks = []
        streak_start = None
        streak_count = 0
        streak_lines = []
        
        number_pattern = re.compile(r'\d+')
        
        for line_num, sentence in sentences_with_lines:
            has_number = bool(number_pattern.search(sentence))
            
            if has_number:
                if streak_start is None:
                    streak_start = line_num
                    streak_count = 1
                    streak_lines = [line_num]
                else:
                    streak_count += 1
                    streak_lines.append(line_num)
            else:
                # 连续中断，检查是否达到阈值
                if streak_count >= THRESHOLDS["number_sentence_streak"]:
                    streaks.append((
                        streak_start,
                        streak_lines[-1],
                        f"连续{streak_count}句含数字"
                    ))
                    self.suggestions += 1
                streak_start = None
                streak_count = 0
                streak_lines = []
        
        # 检查末尾是否有未处理的连续
        if streak_count >= THRESHOLDS["number_sentence_streak"]:
            streaks.append((
                streak_start,
                streak_lines[-1],
                f"连续{streak_count}句含数字"
            ))
            self.suggestions += 1
        
        self.results["number_streak"] = streaks
        return streaks
    
    def scan_template_repeat(self) -> Dict[str, Tuple[int, List[Tuple[int, str]]]]:
        """
        扫描句式模板重复
        
        Returns:
            {模板名: (出现次数, [(行号, 匹配文本), ...])}
        """
        recent_chapters = self.get_recent_chapters()
        template_results = {}
        
        for pattern_str, template_name in TEMPLATE_PATTERNS:
            pattern = re.compile(pattern_str)
            all_matches = []
            current_chapter_matches = []
            
            # 扫描所有最近章节
            for chapter_file in recent_chapters:
                try:
                    with open(chapter_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    lines = content.split('\n')
                    
                    # v7.8 修复：排除元数据区域，只扫描正文
                    content_lines = self._filter_metadata_lines(lines)
                    
                    is_current = (chapter_file.stem == Path(self.filepath).stem)
                    for line_num, line in content_lines:
                        found = pattern.findall(line)
                        if found:
                            for match in found:
                                all_matches.append((line_num, match, chapter_file.stem))
                                if is_current:
                                    current_chapter_matches.append((line_num, match, chapter_file.stem))
                except Exception:
                    continue
            
            # v7.8 修复：阈值检查只针对当前章节
            template_results[template_name] = (len(current_chapter_matches), all_matches)
            
            if len(current_chapter_matches) >= THRESHOLDS["template_repeat"]:
                self.warnings += 1
        
        self.results["template_repeat"] = template_results
        return template_results
    
    def verify_chapter_reference(self) -> List[Tuple[str, str, str]]:
        """
        验证章节号引用
        
        Returns:
            [(引用文本, 状态, 说明), ...]
            状态: "ok", "warning", "error"
        """
        # 提取所有章节引用（排除标题行和元数据）
        pattern = re.compile(r"第([一二三四五六七八九十百千万]+)章")
        references = []
        content_lines = self._get_content_lines_only()
        
        for line_num, line in content_lines:
            found = pattern.findall(line)
            for ref in found:
                references.append((line_num, ref, line))
        
        # 获取实际存在的章节编号
        chapter_dir = self.chapter_path.parent
        existing_chapters = set()
        for chapter_file in chapter_dir.glob("第*章*.md"):
            match = pattern.search(chapter_file.stem)
            if match:
                existing_chapters.add(self._chinese_to_number(match.group(1)))
        
        # 获取当前章节编号
        current_match = pattern.search(self.chapter_name)
        current_chapter_num = None
        if current_match:
            current_chapter_num = self._chinese_to_number(current_match.group(1))
        
        # 验证引用
        results = []
        for line_num, ref, context in references:
            ref_num = self._chinese_to_number(ref)
            
            if ref_num not in existing_chapters:
                # 引用不存在
                results.append((f"第{ref}章", "error", f"引用不存在"))
                self.errors += 1
            elif ref_num == current_chapter_num:
                # 引用当前章节
                results.append((f"第{ref}章", "warning", f"引用当前章节"))
                self.warnings += 1
            else:
                results.append((f"第{ref}章", "ok", f"存在"))
        
        self.results["chapter_reference"] = results
        return results
    
    # ------------------------------------------------------------------------
    # v7.6 新增：三类盲区检测
    # ------------------------------------------------------------------------
    
    def scan_time_anchor_consistency(self) -> List[Dict]:
        """
        扫描时间锚点一致性
        
        检测文本中的"X年前"等时间表述，标记需要与time_anchors核对的位置
        
        Returns:
            [{"line": 行号, "text": 匹配文本, "type": "时间表述", "needs_check": True}, ...]
        """
        # 匹配模式：X年前、X个月前、X天前等
        time_patterns = [
            re.compile(r'(\d+|十|二十|三十|几十)[年载]前'),
            re.compile(r'(\d+|十|二十|三十|几十)个月前'),
            re.compile(r'(\d+|十|二十|三十|几十)天前'),
            re.compile(r'(\d+|十|二十|三十|几十)周前'),
        ]
        
        matches = []
        # v7.7 修复：只扫描正文，排除元数据区域
        content_lines = self._get_content_lines_only()
        for line_num, line in content_lines:
            for pattern in time_patterns:
                found = pattern.findall(line)
                if found:
                    # 提取完整匹配文本
                    for match in pattern.finditer(line):
                        matches.append({
                            "line": line_num,
                            "text": match.group(),
                            "type": "时间表述",
                            "needs_check": True,
                            "note": "必须grep time_anchors区块确认一致性"
                        })
        
        self.results["time_anchor_consistency"] = matches
        
        # 标记为警告（需要人工核对）
        if matches:
            self.warnings += 1
        
        return matches
    
    def scan_item_status_observer(self) -> List[Dict]:
        """
        扫描物象状态描述，检查是否有observer字段记录
        
        检测物象状态变化描述（颜色/亮度/完整性/位置），标记需要确认是否有角色观察
        
        Returns:
            [{"line": 行号, "text": 匹配文本, "item": "物象名", "change_type": "变化类型"}, ...]
        """
        # 物象状态变化关键词
        status_keywords = [
            ("指示灯", ["灯", "闪", "亮", "灭", "红", "绿", "蓝", "白", "黄"]),
            ("屏幕", ["亮", "灭", "闪", "显示", "跳出", "浮现"]),
            ("伤口", ["愈合", "结痂", "流血", "红肿", "发紫"]),
            ("设备", ["启动", "关闭", "运转", "停止", "故障"]),
            ("门", ["开", "关", "锁", "敞"]),
        ]
        
        matches = []
        # v7.7 修复：只扫描正文，排除元数据区域
        content_lines = self._get_content_lines_only()
        for line_num, line in content_lines:
            for item_name, keywords in status_keywords:
                for keyword in keywords:
                    # 简单匹配：物象名 + 状态词
                    pattern = re.compile(f'{item_name}.*{keyword}|{keyword}.*{item_name}')
                    if pattern.search(line):
                        matches.append({
                            "line": line_num,
                            "text": line.strip()[:50],  # 前50字符
                            "item": item_name,
                            "change_type": keyword,
                            "note": "确认physical_anchor_items.status_change_log中有observer记录"
                        })
                        break  # 每行每物象只记录一次
        
        self.results["item_status_observer"] = matches
        
        # 标记为建议（需要人工确认是否有observer）
        if matches:
            self.suggestions += 1
        
        return matches
    
    def scan_injury_action_conflict(self, character_registry: Dict = None) -> List[Dict]:
        """
        扫描带伤行动的时间冲突
        
        若章节中出现"伤愈/能行动/参与战斗"等表述，且该角色injury_record中status为"恢复中"，
        则标记为"需人工核对时间线"
        
        Args:
            character_registry: 角色注册表，包含injury_record信息
            
        Returns:
            [{"line": 行号, "character": "角色名", "action": "行动", "warning": "警告信息"}, ...]
        """
        # 带伤行动关键词
        action_keywords = ["战斗", "作战", "冲锋", "奔跑", "跳跃", "攀爬", "搏斗"]
        recovery_keywords = ["伤愈", "康复", "恢复", "能走", "能动", "参战"]
        
        matches = []
        # v7.7 修复：只扫描正文，排除元数据区域
        content_lines = self._get_content_lines_only()
        for line_num, line in content_lines:
            # 检测恢复/行动关键词
            for keyword in recovery_keywords + action_keywords:
                if keyword in line:
                    # 尝试提取角色名（简单启发式：前面的人名）
                    # 这里简化处理，标记整行供人工检查
                    matches.append({
                        "line": line_num,
                        "text": line.strip()[:50],
                        "action": keyword,
                        "warning": "若角色处于恢复中，需核对injury_record时间线"
                    })
                    break
        
        self.results["injury_action_conflict"] = matches
        
        # 标记为警告（需要人工核对时间线）
        if matches:
            self.warnings += 1
        
        return matches
    
    # ------------------------------------------------------------------------
    # v7.7 新增：跨章一致性强制检查
    # ------------------------------------------------------------------------
    
    def scan_character_attribute_consistency(self, character_registry: Dict = None) -> List[Dict]:
        """
        扫描角色关键属性一致性
        
        检测文本中角色属性描述是否与character_registry.key_attributes一致
        标记属性变更但未记录attribute_change_log的情况
        
        Args:
            character_registry: 角色注册表，包含key_attributes信息
            
        Returns:
            [{"line": 行号, "character": "角色名", "attribute": "属性", "issue": "问题描述"}, ...]
        """
        matches = []
        
        # 从章节元数据中提取character_registry
        registry = self._extract_character_registry()
        
        # 性别检测模式
        gender_patterns = {
            "男": [r"他[的说是]", r"那个男人", r"这个男人", r"一名男[子人]", r"男性", r"汉子"],
            "女": [r"她[的说是]", r"那个女人", r"这个女人", r"一名女[子人]", r"女性", r"女子"]
        }
        
        # 年龄检测模式
        age_pattern = re.compile(r'(\d+)[岁]|([二三四五六七八九十]+十[一二三四五六七八九]?岁)')
        
        # 身高检测模式
        height_pattern = re.compile(r'(\d{3})\s*(?:cm|厘米)')
        
        # 遍历注册表中的角色
        for char_info in registry:
            char_name = char_info.get("name", "")
            key_attrs = char_info.get("key_attributes", {})
            
            if not char_name or not key_attrs:
                continue
            
            # 在文本中搜索该角色的性别描述
            expected_gender = key_attrs.get("gender", "")
            if expected_gender:
                opposite_gender = "女" if expected_gender == "男" else "男"
                content_lines = self._get_content_lines_only()
                for pattern in gender_patterns.get(opposite_gender, []):
                    for line_num, line in content_lines:
                        # 检测：角色名 + 相反性别代词
                        if char_name in line and re.search(pattern, line):
                            matches.append({
                                "line": line_num,
                                "character": char_name,
                                "attribute": "gender",
                                "expected": expected_gender,
                                "found": opposite_gender,
                                "issue": f"性别漂移：注册为{expected_gender}，文本描述为{opposite_gender}"
                            })
                            self.errors += 1
            
            # 检测年龄描述
            expected_age = key_attrs.get("age")
            if expected_age:
                content_lines = self._get_content_lines_only()
                for line_num, line in content_lines:
                    if char_name in line:
                        found = age_pattern.findall(line)
                        for age_match in found:
                            found_age = int(age_match[0]) if age_match[0] else self._chinese_age_to_number(age_match[1])
                            if found_age and abs(found_age - expected_age) > 2:  # 允许±2岁误差
                                matches.append({
                                    "line": line_num,
                                    "character": char_name,
                                    "attribute": "age",
                                    "expected": expected_age,
                                    "found": found_age,
                                    "issue": f"年龄漂移：注册为{expected_age}岁，文本描述为{found_age}岁"
                                })
                                self.warnings += 1
        
        self.results["character_attribute_consistency"] = matches
        return matches
    
    def _extract_character_registry(self) -> List[Dict]:
        """从章节元数据中提取character_registry"""
        registry = []
        in_registry = False
        current_char = {}
        
        for line in self.lines:
            stripped = line.strip()
            
            # 检测character_registry区块开始
            if stripped.startswith("character_registry:"):
                in_registry = True
                continue
            
            # 检测区块结束
            if in_registry and stripped and not stripped.startswith("-") and not stripped.startswith(" ") and ":" in stripped:
                if current_char:
                    registry.append(current_char)
                in_registry = False
                continue
            
            # 解析角色条目
            if in_registry:
                if stripped.startswith("- name:"):
                    if current_char:
                        registry.append(current_char)
                    current_char = {"name": stripped.split(":")[1].strip().strip('"')}
                elif stripped.startswith("gender:") and current_char:
                    if "key_attributes" not in current_char:
                        current_char["key_attributes"] = {}
                    current_char["key_attributes"]["gender"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("age:") and current_char:
                    if "key_attributes" not in current_char:
                        current_char["key_attributes"] = {}
                    try:
                        current_char["key_attributes"]["age"] = int(stripped.split(":")[1].strip())
                    except:
                        pass
        
        if current_char:
            registry.append(current_char)
        
        return registry
    
    def _chinese_age_to_number(self, chinese: str) -> int:
        """中文年龄转数字"""
        mapping = {'二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
        if '十' in chinese:
            parts = chinese.replace('岁', '').split('十')
            tens = mapping.get(parts[0], 1) if parts[0] else 1
            ones = mapping.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
            return tens * 10 + ones
        return mapping.get(chinese.replace('岁', ''), 0)
    
    def scan_location_name_canonical(self, location_registry: Dict = None) -> List[Dict]:
        """
        扫描地点名称规范性
        
        检测文本中地点名称是否使用canonical_name
        标记使用aliases（非首次介绍）或自创名称的情况
        
        Args:
            location_registry: 地点注册表
            
        Returns:
            [{"line": 行号, "location": "地点名", "issue": "问题描述", "suggestion": "建议"}, ...]
        """
        matches = []
        
        # 从章节元数据中提取location_registry
        registry = self._extract_location_registry()
        
        # 构建别名到规范名的映射
        alias_to_canonical = {}
        canonical_names = set()
        for loc_info in registry:
            canonical = loc_info.get("canonical_name", "")
            if canonical:
                canonical_names.add(canonical)
                alias_to_canonical[canonical] = canonical
                for alias in loc_info.get("aliases", []):
                    alias_to_canonical[alias] = canonical
        
        # 检测文本中的地点名称
        # 精确地点模式（编号型）
        location_patterns = [
            re.compile(r'(GCS-\d+(?:-\d+)?)'),  # 编号型地点如GCS-07
            re.compile(r'(SRN-\d+(?:-\d+)?)'),  # 编号型地点如SRN-3
            re.compile(r'(塞壬-\d+)'),  # 塞壬系列
            re.compile(r'(伊毕斯号|伊毕斯)'),  # 船名
            re.compile(r'(散人港|新伊甸|零号猎兵|B-7区|B-\d+区)'),  # 具体地点名
        ]
        
        # 获取当前章节编号（用于判断是否首次介绍）
        current_chapter = self._get_current_chapter_num()
        
        content_lines = self._get_content_lines_only()
        for line_num, line in content_lines:
            for pattern in location_patterns:
                for match in pattern.finditer(line):
                    found_name = match.group(1)
                    
                    # 检查是否为规范名
                    if found_name in canonical_names:
                        continue  # 使用规范名，无问题
                    
                    # 检查是否为已知别名
                    if found_name in alias_to_canonical:
                        canonical = alias_to_canonical[found_name]
                        # 检查是否为首次介绍
                        loc_info = next((l for l in registry if l.get("canonical_name") == canonical), None)
                        if loc_info:
                            first_appear = loc_info.get("first_appear", "")
                            first_ch_num = self._extract_chapter_num(first_appear)
                            if first_ch_num and current_chapter and current_ch_num > first_ch_num:
                                matches.append({
                                    "line": line_num,
                                    "location": found_name,
                                    "canonical": canonical,
                                    "issue": f"非首次介绍使用了别名'{found_name}'，应使用规范名'{canonical}'",
                                    "suggestion": f"将'{found_name}'改为'{canonical}'"
                                })
                                self.warnings += 1
                    else:
                        # 未知地点名，可能是自创或遗漏注册
                        # 排除一些常见非地点词和误匹配
                        exclude_words = [
                            "这艘船", "那艘船", "这层", "那层", "本区", "该区", "老区", "新区",
                            "很多区", "几个区", "那个区", "这个区", "什么区", "哪个区",
                            "这可是", "座废弃", "一个区", "两个区", "三个区",
                            "科考站", "停机坪", "造船厂",  # 这些是通用名词，需要更具体
                        ]
                        # 检查是否为误匹配（包含排除词或过短）
                        is_excluded = any(ex in found_name for ex in exclude_words)
                        if not is_excluded and len(found_name) >= 4 and len(found_name) <= 10:
                            matches.append({
                                "line": line_num,
                                "location": found_name,
                                "canonical": "未注册",
                                "issue": f"地点'{found_name}'未在location_registry中注册",
                                "suggestion": f"在location_registry中添加'{found_name}'或确认是否应使用已有规范名"
                            })
                            self.suggestions += 1
        
        self.results["location_name_canonical"] = matches
        return matches
    
    def _extract_location_registry(self) -> List[Dict]:
        """从章节元数据中提取location_registry"""
        registry = []
        in_registry = False
        current_loc = {}
        
        for line in self.lines:
            stripped = line.strip()
            
            if stripped.startswith("location_registry:"):
                in_registry = True
                continue
            
            if in_registry and stripped and not stripped.startswith("-") and not stripped.startswith(" ") and ":" in stripped:
                if current_loc:
                    registry.append(current_loc)
                in_registry = False
                continue
            
            if in_registry:
                if stripped.startswith("- canonical_name:"):
                    if current_loc:
                        registry.append(current_loc)
                    current_loc = {"canonical_name": stripped.split(":")[1].strip().strip('"')}
                elif stripped.startswith("aliases:") and current_loc:
                    # 解析别名列表
                    aliases_str = stripped.split(":")[1].strip()
                    if aliases_str.startswith("["):
                        aliases_str = aliases_str[1:-1]  # 去掉方括号
                        aliases = [a.strip().strip('"') for a in aliases_str.split(",") if a.strip()]
                        current_loc["aliases"] = aliases
                elif stripped.startswith("first_appear:") and current_loc:
                    current_loc["first_appear"] = stripped.split(":")[1].strip().strip('"')
        
        if current_loc:
            registry.append(current_loc)
        
        return registry
    
    def _get_current_chapter_num(self) -> Optional[int]:
        """获取当前章节编号"""
        match = re.search(r'第(\d+)章', self.chapter_name)
        if match:
            return int(match.group(1))
        match = re.search(r'第([一二三四五六七八九十百千万]+)章', self.chapter_name)
        if match:
            return self._chinese_to_number(match.group(1))
        return None
    
    def _extract_chapter_num(self, ch_ref: str) -> Optional[int]:
        """从章节引用中提取编号"""
        if not ch_ref:
            return None
        match = re.search(r'Ch(\d+)', ch_ref)
        if match:
            return int(match.group(1))
        match = re.search(r'第(\d+)章', ch_ref)
        if match:
            return int(match.group(1))
        return None
    
    def scan_item_location_chain(self, physical_anchor_items: List[Dict] = None) -> List[Dict]:
        """
        扫描物品位置追踪链
        
        检测文本中物品位置变更是否在physical_anchor_items.location_chain中记录
        标记位置变更但未记录的情况
        
        Args:
            physical_anchor_items: 物品列表，包含location_chain信息
            
        Returns:
            [{"line": 行号, "item": "物品名", "issue": "问题描述"}, ...]
        """
        matches = []
        
        # 从章节元数据中提取physical_anchor_items
        items_registry = self._extract_physical_anchor_items()
        
        # 物品位置变更关键词
        location_change_patterns = [
            re.compile(r'(.{2,10})从(.{2,10})[拿取放扔给递]'),
            re.compile(r'(.{2,10})[放插塞]进(.{2,10})'),
            re.compile(r'(.{2,10})[拿取]出(.{2,10})'),
            re.compile(r'(.{2,10})[递给交给递给]了(.{2,10})'),
            re.compile(r'(.{2,10})[揣放塞]在(.{2,10})'),
        ]
        
        # 已注册物品名称集合
        registered_items = {item.get("item", "").lower(): item for item in items_registry}
        
        content_lines = self._get_content_lines_only()
        for line_num, line in content_lines:
            for pattern in location_change_patterns:
                for match in pattern.finditer(line):
                    # 提取物品名（通常是第一个捕获组）
                    potential_item = match.group(1).strip()
                    
                    # 检查是否为已注册物品
                    item_key = potential_item.lower()
                    if item_key in registered_items or any(item in potential_item for item in registered_items.keys()):
                        # 找到对应的注册物品
                        matched_item = None
                        if item_key in registered_items:
                            matched_item = registered_items[item_key]
                        else:
                            for item_name, item_data in registered_items.items():
                                if item_name in potential_item:
                                    matched_item = item_data
                                    break
                        
                        if matched_item:
                            # 检查是否有location_chain记录
                            location_chain = matched_item.get("location_chain", [])
                            current_location = matched_item.get("location", "")
                            
                            # 如果物品有位置变更描述但没有location_chain记录
                            if not location_chain and "给" in line or "递" in line or "放" in line:
                                matches.append({
                                    "line": line_num,
                                    "item": matched_item.get("item", potential_item),
                                    "current_location": current_location,
                                    "issue": f"物品位置变更未记录：'{line.strip()[:40]}...'",
                                    "suggestion": f"在physical_anchor_items中添加location_chain记录"
                                })
                                self.warnings += 1
        
        # 检查物品状态一致性
        for item_info in items_registry:
            item_name = item_info.get("item", "")
            registered_location = item_info.get("location", "")
            status = item_info.get("status", "")
            
            # 检测物品丢失但状态未更新
            if "丢失" in self.content or "不见了" in self.content or "找不到" in self.content:
                if item_name in self.content and status not in ["丢失", "lost"]:
                    content_lines = self._get_content_lines_only()
                    for line_num, line in content_lines:
                        if item_name in line and ("丢失" in line or "不见了" in line or "找不到" in line):
                            matches.append({
                                "line": line_num,
                                "item": item_name,
                                "current_location": registered_location,
                                "issue": f"物品丢失但状态未更新：当前状态为'{status}'",
                                "suggestion": f"将status更新为'丢失'"
                            })
                            self.errors += 1
        
        self.results["item_location_chain"] = matches
        return matches
    
    def _extract_physical_anchor_items(self) -> List[Dict]:
        """从章节元数据中提取physical_anchor_items"""
        items = []
        in_items = False
        current_item = {}
        
        for line in self.lines:
            stripped = line.strip()
            
            if stripped.startswith("physical_anchor_items:"):
                in_items = True
                continue
            
            if in_items and stripped and not stripped.startswith("-") and not stripped.startswith(" ") and ":" in stripped:
                if current_item:
                    items.append(current_item)
                in_items = False
                continue
            
            if in_items:
                if stripped.startswith("- item:"):
                    if current_item:
                        items.append(current_item)
                    current_item = {"item": stripped.split(":")[1].strip().strip('"')}
                elif stripped.startswith("location:") and current_item:
                    current_item["location"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("status:") and current_item:
                    current_item["status"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("location_chain:") and current_item:
                    current_item["location_chain"] = []
        
        if current_item:
            items.append(current_item)
        
        return items
    
    def scan_hook_quality(self) -> Dict:
        """
        扫描章末钩子质量
        
        检测章末是否有钩子，以及钩子是否具体（is_specific）
        标记模糊钩子或缺少character_reaction的情况
        
        Returns:
            {"has_hook": bool, "is_specific": bool, "issues": ["问题1", ...]}
        """
        issues = []
        has_hook = False
        is_specific = True
        hook_type = ""
        hook_content = ""
        
        # 提取章末段落（从正文最后几行获取，排除metadata）
        content_lines = self._get_content_lines_only()
        if content_lines:
            # 取最后10行正文作为章末段落
            end_lines_raw = content_lines[-10:]
            end_content = '\n'.join(line for _, line in end_lines_raw)
            end_lines = [line.strip() for _, line in end_lines_raw]
        else:
            end_content = ""
            end_lines = []
        
        # 从元数据中提取hook_quality_check
        hook_metadata = self._extract_hook_quality_check()
        
        if hook_metadata:
            has_hook = hook_metadata.get("has_hook", False)
            is_specific = hook_metadata.get("is_specific", True)
            hook_type = hook_metadata.get("hook_type", "")
            hook_content = hook_metadata.get("hook_content", "")
            character_reaction = hook_metadata.get("character_reaction", "")
            
            # 检查钩子具体性
            if has_hook and hook_content:
                # 模糊钩子特征：只有事件没有具体内容
                vague_patterns = [
                    r'通讯[亮响]',
                    r'有人[来敲门]',
                    r'消息来了',
                    r'发生了什么',
                    r'出事了',
                ]
                
                for pattern in vague_patterns:
                    if re.search(pattern, hook_content):
                        is_specific = False
                        issues.append(f"钩子过于模糊：'{hook_content}' - 需要具体的人物+事件+后果")
                        self.warnings += 1
                        break
                
                # 检查是否缺少character_reaction
                if not character_reaction:
                    issues.append("缺少character_reaction：章末钩子应有角色反应描述")
                    self.suggestions += 1
            elif not has_hook:
                issues.append("章末无钩子：建议添加悬念/信息/情绪型钩子")
                self.warnings += 1
        else:
            # 没有元数据记录，尝试从文本检测
            # 钩子特征：通讯、消息、发现、转折等
            hook_patterns = [
                (r'通讯[频道]?.*[响亮]', "信息型"),
                (r'[发现看到听到].*[坐标|信号|消息|数据]', "信息型"),
                (r'突然.*[出现响起传来]', "悬念型"),
                (r'[沉默不说话]了.*[秒分]', "情绪型"),
                (r'有人[来敲门喊]', "悬念型"),
            ]
            
            for pattern, h_type in hook_patterns:
                if re.search(pattern, end_content):
                    has_hook = True
                    hook_type = h_type
                    # 提取钩子内容
                    for line in reversed(end_lines):
                        if re.search(pattern, line):
                            hook_content = line.strip()[:50]
                            break
                    break
            
            if not has_hook:
                issues.append("章末未检测到明显钩子 - 建议添加章末悬念")
                self.suggestions += 1
        
        result = {
            "has_hook": has_hook,
            "is_specific": is_specific,
            "hook_type": hook_type,
            "hook_content": hook_content,
            "issues": issues
        }
        
        self.results["hook_quality"] = [result]
        return result
    
    def _extract_hook_quality_check(self) -> Optional[Dict]:
        """从章节元数据中提取hook_quality_check"""
        in_hook = False
        hook_data = {}
        
        for line in self.lines:
            stripped = line.strip()
            
            if stripped.startswith("hook_quality_check:"):
                in_hook = True
                continue
            
            if in_hook:
                if stripped and not stripped.startswith(" ") and ":" in stripped:
                    break
                if stripped.startswith("has_hook:"):
                    hook_data["has_hook"] = "true" in stripped.lower()
                elif stripped.startswith("hook_type:"):
                    hook_data["hook_type"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("hook_content:"):
                    hook_data["hook_content"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("is_specific:"):
                    hook_data["is_specific"] = "true" in stripped.lower()
                elif stripped.startswith("character_reaction:"):
                    hook_data["character_reaction"] = stripped.split(":")[1].strip().strip('"')
        
        return hook_data if hook_data else None
    
    def scan_timeline_transition(self, previous_chapter_end: Dict = None) -> List[Dict]:
        """
        扫描时间线过渡完整性
        
        检测当前章节与上一章的时间/地点过渡是否在timeline_continuity中记录
        标记过渡缺失或不完整的情况
        
        Args:
            previous_chapter_end: 上一章结尾状态
            
        Returns:
            [{"issue": "问题描述", "suggestion": "建议"}, ...]
        """
        matches = []
        
        # 从章节元数据中提取timeline_continuity
        timeline_data = self._extract_timeline_continuity()
        
        # 从章节元数据中提取chapter_end_state
        end_state = self._extract_chapter_end_state()
        
        # 检测章节开头的时间/地点信息
        start_content = self.content[:500]  # 前500字
        start_lines = start_content.split('\n')
        
        # 时间表述模式
        time_patterns = [
            re.compile(r'(\d+)[天日小时分钟]后'),
            re.compile(r'(\d+)[天日小时分钟]前'),
            re.compile(r'第二天|次日|翌日|当晚|当夜'),
            re.compile(r'[上中下早晚][午夜晨]'),
        ]
        
        # 地点表述模式
        location_patterns = [
            re.compile(r'在(.{2,10})[里内中]'),
            re.compile(r'回到(.{2,10})'),
            re.compile(r'离开(.{2,10})'),
            re.compile(r'到达(.{2,10})'),
        ]
        
        # 检测开头是否有时间跳跃
        has_time_gap = False
        time_gap_text = ""
        for pattern in time_patterns:
            for line in start_lines[:10]:  # 只检查前10行
                match = pattern.search(line)
                if match:
                    has_time_gap = True
                    time_gap_text = match.group()
                    break
            if has_time_gap:
                break
        
        # 检测开头是否有地点变更
        has_location_change = False
        location_change_text = ""
        for pattern in location_patterns:
            for line in start_lines[:10]:
                match = pattern.search(line)
                if match:
                    has_location_change = True
                    location_change_text = match.group()
                    break
            if has_location_change:
                break
        
        # 验证timeline_continuity记录
        if timeline_data:
            recorded_time_gap = timeline_data.get("time_gap", "")
            recorded_location_change = timeline_data.get("location_change", "")
            has_transition = timeline_data.get("has_transition", False)
            transition_summary = timeline_data.get("transition_summary", "")
            
            # 检查时间跳跃是否记录
            if has_time_gap and not recorded_time_gap:
                matches.append({
                    "issue": f"时间跳跃未记录：开头出现'{time_gap_text}'，但timeline_continuity.time_gap为空",
                    "suggestion": f"在timeline_continuity中记录time_gap: '{time_gap_text}'"
                })
                self.warnings += 1
            
            # 检查地点变更是否记录
            if has_location_change and not recorded_location_change:
                matches.append({
                    "issue": f"地点变更未记录：开头出现'{location_change_text}'，但timeline_continuity.location_change为空",
                    "suggestion": f"在timeline_continuity中记录location_change"
                })
                self.warnings += 1
            
            # 检查是否有过渡描述
            if (has_time_gap or has_location_change) and not has_transition:
                matches.append({
                    "issue": "缺少过渡描述：时间/地点有变化但has_transition为false",
                    "suggestion": "添加transition_summary描述过渡情节"
                })
                self.suggestions += 1
        else:
            # 没有timeline_continuity记录
            if has_time_gap or has_location_change:
                matches.append({
                    "issue": f"缺少timeline_continuity记录：开头有{'时间跳跃' if has_time_gap else ''}{'和' if has_time_gap and has_location_change else ''}{'地点变更' if has_location_change else ''}",
                    "suggestion": "在章节元数据中添加timeline_continuity字段"
                })
                self.warnings += 1
        
        # 检查chapter_end_state是否完整
        if end_state:
            location = end_state.get("location", "")
            time = end_state.get("time", "")
            characters = end_state.get("characters", [])
            
            if not location:
                matches.append({
                    "issue": "chapter_end_state.location为空",
                    "suggestion": "记录章节结束时的地点"
                })
                self.suggestions += 1
            
            if not time:
                matches.append({
                    "issue": "chapter_end_state.time为空",
                    "suggestion": "记录章节结束时的时间"
                })
                self.suggestions += 1
        
        self.results["timeline_transition"] = matches
        return matches
    
    def _extract_timeline_continuity(self) -> Optional[Dict]:
        """从章节元数据中提取timeline_continuity"""
        in_timeline = False
        timeline_data = {}
        
        for line in self.lines:
            stripped = line.strip()
            
            if stripped.startswith("timeline_continuity:"):
                in_timeline = True
                continue
            
            if in_timeline:
                if stripped and not stripped.startswith(" ") and ":" in stripped:
                    break
                if stripped.startswith("time_gap:"):
                    timeline_data["time_gap"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("location_change:"):
                    timeline_data["location_change"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("has_transition:"):
                    timeline_data["has_transition"] = "true" in stripped.lower()
                elif stripped.startswith("transition_summary:"):
                    timeline_data["transition_summary"] = stripped.split(":")[1].strip().strip('"')
        
        return timeline_data if timeline_data else None
    
    def _extract_chapter_end_state(self) -> Optional[Dict]:
        """从章节元数据中提取chapter_end_state"""
        in_state = False
        state_data = {}
        
        for line in self.lines:
            stripped = line.strip()
            
            if stripped.startswith("chapter_end_state:"):
                in_state = True
                continue
            
            if in_state:
                if stripped and not stripped.startswith(" ") and not stripped.startswith("#") and ":" in stripped:
                    # 检查是否是子字段还是新区块
                    if not any(stripped.startswith(k) for k in ["location:", "time:", "characters:", "item_chain_verified:", "cross_ref_checked:"]):
                        break
                if stripped.startswith("location:"):
                    state_data["location"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("time:"):
                    state_data["time"] = stripped.split(":")[1].strip().strip('"')
                elif stripped.startswith("characters:"):
                    state_data["characters"] = []
        
        return state_data if state_data else None
    
    def _chinese_to_number(self, chinese: str) -> int:
        """
        中文数字转阿拉伯数字
        
        Args:
            chinese: 中文数字字符串
            
        Returns:
            阿拉伯数字
        """
        mapping = {
            '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
            '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
            '十': 10, '百': 100, '千': 1000, '万': 10000
        }
        
        # 简单处理：直接拼接数字
        result = 0
        temp = 0
        
        for char in chinese:
            if char in mapping:
                num = mapping[char]
                if num >= 10:
                    if temp == 0:
                        temp = 1
                    result += temp * num
                    temp = 0
                else:
                    temp = num
        
        result += temp
        return result if result > 0 else 1
    
    # ------------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------------
    
    def generate_report(self) -> str:
        """
        生成扫描报告（v7.6 截图友好模式）
        
        Returns:
            报告文本
        """
        lines = []
        now = datetime.now()
        
        # 报告头（截图友好格式）
        lines.append("=" * 50)
        lines.append("SOP v7.8 强制扫描报告")
        lines.append("=" * 50)
        lines.append(f"📄 章节：{self.chapter_name}.md")
        lines.append(f"⏰ 时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"🔧 扫描器版本：v7.8")
        lines.append("=" * 50)
        lines.append("")
        
        # 1. 冻结意象扫描
        lines.append("【冻结意象扫描】")
        count, matches = len(self.results["frozen_imagery"]), self.results["frozen_imagery"]
        if count == 0:
            lines.append(f"匹配：0处 ✓")
        else:
            match_strs = [f'行{m[0]}: "{m[1]}"' for m in matches]
            lines.append(f"匹配：{count}处（{', '.join(match_strs)}）")
            self.warnings += 1
        lines.append("")
        
        # 2. 「不是...是...」扫描（v7.4 零容忍）
        lines.append("【「不是...是...」扫描（零容忍）】")
        count, matches = len(self.results["bushi_pattern"]), self.results["bushi_pattern"]
        if count == 0:
            lines.append(f"匹配：0处 ✓")
        else:
            match_strs = [f'行{m[0]}: "{m[1]}"' for m in matches]
            lines.append(f"匹配：{count}处（{', '.join(match_strs)}）")
            lines.append(f"错误：零容忍违规，必须全部删除 ✗")
        lines.append("")
        
        # 3. 参数连珠炮检测
        lines.append("【参数连珠炮检测】")
        streaks = self.results["number_streak"]
        if not streaks:
            lines.append("匹配：0处 ✓")
        else:
            for start, end, desc in streaks:
                lines.append(f"匹配：1处（行{start}-{end}: {desc}）")
                lines.append("建议：触发1.8.1一问一答拆解")
        lines.append("")
        
        # 4. 句式模板重复
        lines.append("【句式模板重复】")
        template_results = self.results["template_repeat"]
        for template_name, (current_count, all_matches) in template_results.items():
            # 统计跨章累积
            cross_chapter_count = len(all_matches) - current_count
            if current_count == 0:
                lines.append(f'- "{template_name}"：本章0次 ✓')
            elif current_count <= THRESHOLDS["template_repeat"]:
                lines.append(f'- "{template_name}"：本章{current_count}次 ✓')
            else:
                lines.append(f'- "{template_name}"：本章{current_count}次 ⚠ 超过阈值({THRESHOLDS["template_repeat"]})')
                # v7.5 新增：输出替换建议
                if template_name in REPLACEMENT_TEMPLATES:
                    replacements = REPLACEMENT_TEMPLATES[template_name]
                    lines.append(f'    建议替换为：{" / ".join(replacements)}')
        
        # 详细模式下显示具体匹配
        if self.verbose:
            for template_name, (count, matches) in template_results.items():
                if matches:
                    for line_num, text, chapter in matches[:5]:  # 只显示前5个
                        lines.append(f'    - {chapter} 行{line_num}: "{text}"')
        lines.append("")
        
        # 5. 章节号引用验证
        lines.append("【章节号引用验证】")
        ref_results = self.results["chapter_reference"]
        if not ref_results:
            lines.append("引用：无 ✓")
        else:
            for ref, status, desc in ref_results:
                if status == "ok":
                    lines.append(f"引用：{ref} → {desc} ✓")
                elif status == "warning":
                    lines.append(f"引用：{ref} → {desc} ⚠")
                else:
                    lines.append(f"引用：{ref} → {desc} ✗")
        lines.append("")
        
        # 6. 时间锚点一致性检测（v7.6 新增）
        lines.append("【时间锚点一致性检测（v7.6）】")
        time_results = self.results.get("time_anchor_consistency", [])
        if not time_results:
            lines.append("时间表述：无 ✓")
        else:
            lines.append(f"时间表述：{len(time_results)}处 ⚠")
            for match in time_results[:5]:  # 只显示前5个
                lines.append(f'  行{match["line"]}: "{match["text"]}" → {match["note"]}')
            if len(time_results) > 5:
                lines.append(f"  ... 还有 {len(time_results) - 5} 处")
        lines.append("")
        
        # 7. 物象状态观察者检测（v7.6 新增）
        lines.append("【物象状态观察者检测（v7.6）】")
        item_results = self.results.get("item_status_observer", [])
        if not item_results:
            lines.append("物象状态变更：无 ✓")
        else:
            lines.append(f"物象状态变更：{len(item_results)}处 💡")
            for match in item_results[:5]:
                lines.append(f'  行{match["line"]}: [{match["item"]}] {match["change_type"]}')
                lines.append(f'    → {match["note"]}')
            if len(item_results) > 5:
                lines.append(f"  ... 还有 {len(item_results) - 5} 处")
        lines.append("")
        
        # 8. 伤势-行动时间冲突检测（v7.6 新增）
        lines.append("【伤势-行动时间冲突检测（v7.6）】")
        injury_results = self.results.get("injury_action_conflict", [])
        if not injury_results:
            lines.append("带伤行动描述：无 ✓")
        else:
            lines.append(f"带伤行动描述：{len(injury_results)}处 ⚠")
            for match in injury_results[:5]:
                lines.append(f'  行{match["line"]}: "{match["text"]}..."')
                lines.append(f'    → {match["warning"]}')
            if len(injury_results) > 5:
                lines.append(f"  ... 还有 {len(injury_results) - 5} 处")
        lines.append("")
        
        # 9. 角色关键属性一致性检测（v7.7 新增）
        lines.append("【角色关键属性一致性检测（v7.7）】")
        char_attr_results = self.results.get("character_attribute_consistency", [])
        if not char_attr_results:
            lines.append("角色属性：无异常 ✓")
        else:
            lines.append(f"角色属性检查：{len(char_attr_results)}处 💡")
            for match in char_attr_results[:5]:
                lines.append(f'  [{match["character"]}] {match["attribute"]}')
                lines.append(f'    → {match["issue"]}')
        lines.append("")
        
        # 10. 地点名称规范性检测（v7.7 新增）
        lines.append("【地点名称规范性检测（v7.7）】")
        loc_results = self.results.get("location_name_canonical", [])
        if not loc_results:
            lines.append("地点名称：无异常 ✓")
        else:
            lines.append(f"地点名称检查：{len(loc_results)}处 💡")
            for match in loc_results[:5]:
                lines.append(f'  [{match["location"]}]')
                lines.append(f'    → {match["issue"]}')
                lines.append(f'    → 建议：{match["suggestion"]}')
        lines.append("")
        
        # 11. 物品位置追踪链检测（v7.7 新增）
        lines.append("【物品位置追踪链检测（v7.7）】")
        item_chain_results = self.results.get("item_location_chain", [])
        if not item_chain_results:
            lines.append("物品位置链：无异常 ✓")
        else:
            lines.append(f"物品位置链检查：{len(item_chain_results)}处 💡")
            for match in item_chain_results[:5]:
                lines.append(f'  [{match["item"]}]')
                lines.append(f'    → {match["issue"]}')
        lines.append("")
        
        # 12. 章末钩子质量检测（v7.7 新增）
        lines.append("【章末钩子质量检测（v7.7）】")
        hook_results = self.results.get("hook_quality", [])
        if not hook_results:
            lines.append("钩子质量：无数据")
        else:
            hook = hook_results[0]
            if hook.get("has_hook"):
                lines.append("钩子存在：✓")
                if hook.get("is_specific"):
                    lines.append("钩子具体性：✓")
                else:
                    lines.append("钩子具体性：⚠ 需细化")
            else:
                lines.append("钩子存在：✗ 未检测到钩子")
            if hook.get("issues"):
                for issue in hook["issues"]:
                    lines.append(f'  → {issue}')
        lines.append("")
        
        # 13. 时间线过渡完整性检测（v7.7 新增）
        lines.append("【时间线过渡完整性检测（v7.7）】")
        timeline_results = self.results.get("timeline_transition", [])
        if not timeline_results:
            lines.append("时间线过渡：无异常 ✓")
        else:
            lines.append(f"时间线过渡检查：{len(timeline_results)}处 💡")
            for match in timeline_results[:5]:
                lines.append(f'  → {match["issue"]}')
                lines.append(f'    → 建议：{match["suggestion"]}')
        lines.append("")
        
        # 总评（截图友好格式）
        lines.append("=" * 50)
        lines.append("【总评】")
        if self.errors > 0:
            status = "🔴 未通过"
            status_code = "FAIL"
            detail = f"{self.errors}处错误，{self.warnings}处警告"
        elif self.warnings > 0:
            status = "🟡 通过（有警告）"
            status_code = "WARN"
            detail = f"{self.warnings}处警告"
        elif self.suggestions > 0:
            status = "🟢 通过（有建议）"
            status_code = "PASS"
            detail = f"{self.suggestions}处建议优化"
        else:
            status = "🟢 通过"
            status_code = "PASS"
            detail = "无问题"
        
        lines.append(f"状态：{status}")
        lines.append(f"详情：{detail}")
        lines.append(f"返回码：{self.get_return_code()} ({status_code})")
        lines.append("=" * 50)
        lines.append("")
        lines.append("【自检报告验证声明】")
        lines.append("此截图用于自检报告强制验证")
        lines.append("差异>0% → 零容忍熔断")
        lines.append(f"生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 50)
        
        return '\n'.join(lines)
    
    def get_return_code(self) -> int:
        """
        获取返回码
        
        Returns:
            0: 全部通过
            1: 有黄色警告
            2: 有红色错误
        """
        if self.errors > 0:
            return 2
        elif self.warnings > 0:
            return 1
        else:
            return 0


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description='SOP v7.7 强制扫描脚本（截图友好模式）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python sop_scanner.py --chapter ch15.md
  python sop_scanner.py --chapter ch15.md --window 5
  python sop_scanner.py --chapter ch15.md --window 5 --verbose

返回码:
  0 - 全部通过
  1 - 有黄色警告（建议优化）
  2 - 有红色错误（必须修复）

v7.7 更新:
  - 新增跨章一致性强制检查：角色属性、地点名称、物品位置、钩子质量、时间线过渡
  - 预提交清单从7步扩展为10步
  - 新增5个检测函数框架（TODO标记待完善）

v7.6 更新:
  - 新增截图友好模式输出（时间戳、章节名、总评颜色、验证水印）
  - 用于自检报告强制验证，差异>0%即熔断
  - 自检报告必须附本工具输出截图
  - 新增三类盲区检测：时间锚点一致性、物象状态观察者、伤势-行动时间冲突

v7.5 更新:
  - D23阈值收紧：每章最多2次同类模板
  - 新增替换模板库输出
        '''
    )
    
    parser.add_argument(
        '--chapter', '-c',
        required=True,
        help='当前章节文件路径'
    )
    
    parser.add_argument(
        '--window', '-w',
        type=int,
        default=5,
        help='扫描窗口（最近N章），默认5'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='详细输出模式'
    )
    
    args = parser.parse_args()
    
    # 创建扫描器并执行扫描
    scanner = SOPScanner(
        chapter_path=args.chapter,
        window=args.window,
        verbose=args.verbose
    )
    
    # 加载章节
    if not scanner.load_chapter():
        return 2
    
    # 执行所有扫描
    scanner.scan_frozen_imagery()
    scanner.scan_bushi_pattern()
    scanner.scan_number_streak()
    scanner.scan_template_repeat()
    scanner.verify_chapter_reference()
    scanner.scan_time_anchor_consistency()      # v7.6 新增
    scanner.scan_item_status_observer()         # v7.6 新增
    scanner.scan_injury_action_conflict()       # v7.6 新增
    scanner.scan_character_attribute_consistency()  # v7.7 新增
    scanner.scan_location_name_canonical()      # v7.7 新增
    scanner.scan_item_location_chain()          # v7.7 新增
    scanner.scan_hook_quality()                 # v7.7 新增
    scanner.scan_timeline_transition()          # v7.7 新增
    
    # 生成并输出报告
    report = scanner.generate_report()
    print(report)
    
    # 返回状态码
    return scanner.get_return_code()


if __name__ == '__main__':
    exit(main())
