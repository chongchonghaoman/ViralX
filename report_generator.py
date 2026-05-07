#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成分析报告"""
import json
from pathlib import Path
from collections import Counter

def generate_report(videos: list, keyword: str) -> dict:
    """生成综合分析报告"""
    if not videos:
        return {}

    # 统计数据
    total_likes = sum(v.get('likes', 0) for v in videos)
    total_comments = sum(v.get('comments', 0) for v in videos)
    avg_likes = total_likes / len(videos) if videos else 0
    avg_comments = total_comments / len(videos) if videos else 0

    # 提取标题关键词
    titles = [v.get('title', '') for v in videos]
    all_words = ' '.join(titles).split()
    word_freq = Counter(all_words)
    top_words = word_freq.most_common(10)

    # 作者分析
    authors = [v.get('author', '') for v in videos]
    author_freq = Counter(authors)

    report = {
        'keyword': keyword,
        'total_videos': len(videos),
        'statistics': {
            'total_likes': total_likes,
            'total_comments': total_comments,
            'avg_likes': round(avg_likes, 0),
            'avg_comments': round(avg_comments, 0),
            'max_likes': max(v.get('likes', 0) for v in videos),
            'min_likes': min(v.get('likes', 0) for v in videos)
        },
        'top_keywords': [{'word': w, 'count': c} for w, c in top_words],
        'top_authors': [{'author': a, 'count': c} for a, c in author_freq.most_common(5)],
        'videos': videos
    }

    return report

if __name__ == "__main__":
    # 测试
    test_videos = [
        {'title': 'Best outdoor light', 'likes': 10000, 'comments': 200, 'author': 'user1'},
        {'title': 'Solar outdoor lamp', 'likes': 8000, 'comments': 150, 'author': 'user2'}
    ]
    report = generate_report(test_videos, 'outdoor lighting')
    print(json.dumps(report, indent=2, ensure_ascii=False))
