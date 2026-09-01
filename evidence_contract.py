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
    comments = platform.get("comments_data") or []
    hashtags = platform.get("hashtags") or []
    transcript = str(tk_note.get("transcript") or "").strip()
    shot_analysis = str(shot.get("shot_analysis") or "").strip()

    sources = f"""[META:title]
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
{shot_analysis or '未获得镜头证据；必须停止分析'}

[SHOT:project]
镜头引擎：{shot.get('provider') or '未返回'}；模型：{shot.get('model') or '未返回'}；画布：{shot.get('project_url') or '不适用'}
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
    citations = re.findall(r"\[(?:META|TK|SHOT):[^\]]+\]", text)
    unique = set(citations)
    if not any(item.startswith("[META:") for item in unique):
        return "报告没有引用平台元数据"
    shot_citations = {item for item in unique if re.fullmatch(r"\[SHOT:S\d{3}\]", item)}
    evidence = (((video_data or {}).get("evidence_bundle") or {}).get("shot_evidence") or {})
    required_shots = min(2, max(int(evidence.get("shot_count") or 1), 1))
    if len(shot_citations) < required_shots:
        return f"报告没有引用足够的具体镜头证据（需要至少 {required_shots} 个镜头 ID）"
    if len(unique) < 3 or len(citations) < 4:
        return "报告的证据引用不足，无法区分事实与推断"
    platform = ((video_data or {}).get("evidence_bundle") or {}).get("platform_evidence") or {}
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
