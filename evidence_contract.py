"""Evidence serialization, grounding validation, and audit persistence.

This module is deliberately independent from model and pipeline orchestration.
It defines the stable evidence boundary consumed by every final-analysis model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


def evidence_bundle_text(video_data: dict, limit: int = 80000) -> str:
    """Serialize the merged platform, TK Note, and shot evidence."""
    bundle = video_data.get("evidence_bundle")
    if not bundle:
        return "（尚无合并证据包）"
    try:
        return json.dumps(bundle, ensure_ascii=False, default=str, indent=2)[:limit]
    except (TypeError, ValueError):
        return str(bundle)[:limit]


def grounded_sources_text(video_data: dict, limit: int = 80000) -> str:
    """Render the merged bundle as named sources the final model must cite."""
    bundle = video_data.get("evidence_bundle") or {}
    platform = bundle.get("platform_evidence") or {}
    tk_note = bundle.get("tk_note_evidence") or {}
    shot = bundle.get("shot_evidence") or bundle.get("libtv_evidence") or {}
    video_input = bundle.get("video_input") or {}
    target_product = str(bundle.get("target_product") or video_data.get("target_product") or "").strip()
    comments = platform.get("comments_data") or []
    hashtags = platform.get("hashtags") or []
    transcript = str(tk_note.get("transcript") or "").strip()
    shot_analysis = str(shot.get("shot_analysis") or "").strip()

    sources = f"""[TARGET:product]
本次要研究的目标产品：{target_product or '未指定；只能描述画面主产品，不得把安装辅料或背景物品擅自当成目标产品'}
产品锁定规则：搜索词或用户填写的产品名称优先级高于帖子描述中的配件、安装耗材和关联商品。

[META:title]
标题：{platform.get('title') or '未采集'}
作者：{platform.get('author') or '未采集'}
时长：{platform.get('duration') if platform.get('duration') is not None else '未采集'} 秒

[META:metrics]
点赞：{platform.get('likes', 0)}；评论数：{platform.get('comments', 0)}；分享数：{platform.get('shares', 0)}；播放量：{platform.get('views', 0)}

[META:comments]
评论正文：{json.dumps(comments, ensure_ascii=False, default=str) if comments else '未采集；不得推断真实用户反馈'}

[META:hashtags]
标签：{json.dumps(hashtags, ensure_ascii=False, default=str) if hashtags else '未采集；不得虚构标签策略'}

[TK:metadata]
{json.dumps(tk_note.get('metadata') or {}, ensure_ascii=False, default=str, indent=2)}

[TK:transcript]
{transcript or '未获得有效转写；不得据此补写台词'}
转写来源：{tk_note.get('transcript_source') or '未知'}
警告：{json.dumps(tk_note.get('warnings') or [], ensure_ascii=False, default=str)}

[SHOT:evidence]
下列每行都带有唯一镜头引用；引用画面事实时必须保留对应的 [SHOT:Sxxx]：
{shot_analysis or '专业镜头索引未启用；画面事实必须直接引用原视频时间段 [VIDEO:MM:SS-MM:SS]'}

[SHOT:project]
镜头引擎：{shot.get('provider') or '未返回'}；模型：{shot.get('model') or '未返回'}；画布：{shot.get('project_url') or '不适用'}

[VIDEO:source]
原视频直读：{video_input.get('status') or '待模型读取'}；传输：{video_input.get('transport') or '由运行时选择'}；SHA-256：{video_input.get('source_sha256') or '未记录'}
"""
    return sources[:limit]


def final_evidence_prompt(video_data: dict) -> str:
    """Build the evidence-only final prompt shared by every model protocol."""
    return f"""你是 ViralX 的最终证据综合模型。你不能直接观看原视频，也不能补全缺失信息；只能使用下列命名证据源。

=== 可引用证据源 ===
{grounded_sources_text(video_data)}

=== 不可违反的规则 ===
1. 每条关于原视频的具体事实必须在句末引用来源标签。平台数据使用 [META:title]、[META:metrics]、[META:comments]、[META:hashtags]；转写使用 [TK:transcript]。
2. 每条画面、动作、镜头、屏幕文字事实必须引用它实际来自的镜头 ID，例如 [SHOT:S001]。不得只引用汇总标签 [SHOT:evidence]。
3. 声音和台词只能来自 [TK:transcript]；关键帧不能证明音频。没有评论正文、标签、价格或 CTA 证据时不得补写。
4. 所有营销机制、受众和因果解释必须明确标为“推断”，并同时引用支撑它的事实。
5. 翻拍内容必须标为“创意提案”，不能伪装成原片复原；缺少产品资料时只给结构。
6. 证据不足就写“未采集”或“无法判断”，不要为了完整而填空。

=== 输出格式 ===
## 证据覆盖
用表格列出平台元数据、评论正文、TK Note 转写、镜头证据是否可用和局限，每行附来源。

## 原视频事实
按时间顺序列出可核验事实，每条引用对应 [SHOT:Sxxx]；平台数字另加 [META:metrics]。

## 爆款机制
分为“观察事实”和“推断”两栏，每项都带来源；没有足够证据时明确无法判断。

## 用户反馈与受众
没有评论正文就明确写“评论正文未采集，无法判断真实用户诉求” [META:comments]。

## 可复用结构
只抽象证据支持的结构，说明适用边界并附来源。

## 创意提案：翻拍框架
这是新创作，不是原片复原。逐段注明借用了哪些已引用结构。"""


def final_video_prompt(video_data: dict) -> str:
    """Build the default prompt when the final vision model receives the source video."""
    target = str(
        ((video_data.get("evidence_bundle") or {}).get("target_product"))
        or video_data.get("target_product")
        or ""
    ).strip()
    return f"""你是 ViralX 的原片视觉分析与最终证据综合模型。你正在直接观看 TK Note 下载并校验过的完整原视频，同时收到平台、字幕和可选专业镜头索引。

=== 目标产品锁定（最高优先级） ===
目标产品：{target or '用户未指定；请识别画面叙事的主产品，并与安装辅料、赠品、背景物品分开'}
搜索词或用户填写的产品名称决定本次研究对象。帖子标题、描述和字幕中出现的胶条、支架、遥控器等配件不能替换目标产品。若画面同时出现目标产品与配件，必须分别陈述。

=== 可引用证据源 ===
{grounded_sources_text(video_data)}

=== 不可违反的规则 ===
1. 先完整理解原视频，再输出结论；不得只依据标题、字幕或某一张关键帧判断目标产品是否出现。
2. 每条画面、动作、镜头和屏幕文字事实必须引用原视频时间段，格式为 [VIDEO:MM:SS-MM:SS]。若提供了专业镜头索引，可同时补充 [SHOT:Sxxx]，但不能用它替代原视频核验。
3. 声音与台词只能来自 [TK:transcript]；Qwen-VL 的视频输入只作为视觉证据，不能凭画面猜声音。
4. 平台标题、互动、评论和标签分别引用 [META:title]、[META:metrics]、[META:comments]、[META:hashtags]。没有评论正文时不得虚构真实用户反馈。
5. 所有营销机制、受众和因果解释必须明确标为“推断”，并引用支撑事实。
6. 翻拍内容必须标为“创意提案”；证据不足就写“未采集”或“无法判断”。

=== 输出格式 ===
## 目标产品核验
- 目标：{target or '待识别'} [TARGET:product]
- 画面状态：只可选择 [TARGET:visible]、[TARGET:not_visible]、[TARGET:uncertain]
- 依据：至少引用两个覆盖不同时间段的 [VIDEO:MM:SS-MM:SS]；短于 2 秒的视频可引用一个。
- 配件区分：列出容易与目标产品混淆的配件；没有则写“未发现”。

## 证据覆盖
用表格列出原视频、平台元数据、评论正文、TK Note 转写和专业镜头索引是否可用、局限与来源。

## 原视频事实
按时间顺序列出可核验事实，每条引用 [VIDEO:MM:SS-MM:SS]；有对应镜头 ID 时可追加 [SHOT:Sxxx]。

## 爆款机制
分为“观察事实”和“推断”，每项都带来源；证据不足时明确无法判断。

## 用户反馈与受众
没有评论正文就写“评论正文未采集，无法判断真实用户诉求” [META:comments]。

## 可复用结构
只抽象证据支持的结构，说明适用边界并附来源。

## 创意提案：翻拍框架
这是新创作，不是原片复原。逐段说明借用了哪些证据支持的结构。"""


_USER_FEEDBACK_CLAIM_RE = re.compile(
    r"评论(?:显示|反映|指出|认为|提到|表示|反馈)|"
    r"用户(?:表示|认为|反馈|提到|指出|评价|评论称)"
)
_USER_FEEDBACK_DISCLOSURE_RE = re.compile(
    r"未采集|无法判断|不可用|无(?:具体)?评论|没有评论|缺少评论|"
    r"不得推断|不能判断|非直接用户反馈|待验证|仅能.{0,12}推断"
)


def _claims_unverified_user_feedback(report: str) -> bool:
    for raw_line in str(report or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if _USER_FEEDBACK_CLAIM_RE.search(line) and not _USER_FEEDBACK_DISCLOSURE_RE.search(line):
            return True
    return False


def grounding_error(report: str, video_data: dict | None = None) -> str:
    """Require traceable citations before a model report can be completed."""
    text = str(report or "").strip()
    if not text:
        return "模型没有返回报告"
    citations = re.findall(r"\[(?:META|TK|SHOT|VIDEO|TARGET):[^\]]+\]", text)
    unique = set(citations)
    if not any(item.startswith("[META:") for item in unique):
        return "报告没有引用平台元数据"
    bundle = ((video_data or {}).get("evidence_bundle") or {})
    visual_mode = str(bundle.get("visual_mode") or "professional").lower()
    shot_citations = {item for item in unique if re.fullmatch(r"\[SHOT:S\d{3}\]", item)}
    video_citations = set(re.findall(
        r"\[VIDEO:\d{1,2}:\d{2}(?:\.\d{1,3})?-\d{1,2}:\d{2}(?:\.\d{1,3})?\]",
        text,
    ))
    evidence = bundle.get("shot_evidence") or {}
    if visual_mode == "direct":
        try:
            duration = float((bundle.get("platform_evidence") or {}).get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        required_video_citations = 1 if 0 < duration < 2 else 2
        if len(video_citations) < required_video_citations:
            return f"报告没有引用足够的原视频时间段（需要至少 {required_video_citations} 个）"
        target = str(bundle.get("target_product") or "").strip()
        if target and "[TARGET:product]" not in text:
            return "报告没有确认本次目标产品"
        target_states = re.findall(r"\[TARGET:(visible|not_visible|uncertain)\]", text)
        if len(set(target_states)) != 1:
            return "报告缺少唯一的目标产品画面状态"
    else:
        required_shots = min(2, max(int(evidence.get("shot_count") or 1), 1))
        if len(shot_citations) < required_shots:
            return f"报告没有引用足够的具体镜头证据（需要至少 {required_shots} 个镜头 ID）"
    if len(unique) < 3 or len(citations) < 4:
        return "报告的证据引用不足，无法区分事实与推断"
    platform = bundle.get("platform_evidence") or {}
    if not (platform.get("comments_data") or []):
        if _claims_unverified_user_feedback(text):
            return "未采集评论正文，但报告仍声称存在真实用户反馈"
        if not re.search(r"评论.{0,16}未采集|未采集.{0,16}评论", text):
            return "报告没有披露评论正文未采集"
    if not (platform.get("hashtags") or []) and re.search(r"#[A-Za-z0-9_\-]+", text):
        return "未采集标签，但报告生成了具体标签"
    return ""


def persist_evidence_audit(
    video_file_path: str,
    evidence_bundle: dict,
    shot_text: str,
    report: str = "",
) -> dict:
    """Keep a local, secret-free audit copy beside the downloaded package."""
    try:
        audit_dir = Path(video_file_path).resolve().parent / "viralx-evidence"
        audit_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = audit_dir / "evidence-bundle.json"
        shot_path = audit_dir / "shot-evidence.md"
        report_path = audit_dir / "final-model-report.raw.md"
        bundle_path.write_text(
            json.dumps(evidence_bundle, ensure_ascii=False, default=str, indent=2),
            encoding="utf-8",
        )
        shot_path.write_text(str(shot_text or "").strip(), encoding="utf-8")
        if report:
            report_path.write_text(str(report).strip(), encoding="utf-8")
        return {
            "evidence_bundle_path": str(bundle_path),
            "shot_evidence_path": str(shot_path),
            "raw_model_report_path": str(report_path) if report else "",
        }
    except OSError as exc:
        print(f"[证据审计文件写入失败] {exc}")
        return {}
