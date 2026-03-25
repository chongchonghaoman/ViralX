#!/usr/bin/env python3
"""
TikTok 美区爆款视频分析工具
使用 TikTok Research API 或第三方 API 抓取爆款视频
"""
import requests
import json
from pathlib import Path
from typing import List, Dict

class TikTokViralAnalyzer:
    def __init__(self, output_dir="E:/tiktok_analyzer/data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = ""  # 需要配置 RapidAPI 或其他 TikTok API key

    def search_viral_videos(self, keyword: str, min_likes: int = 10000, count: int = 50) -> List[Dict]:
        """搜索 TikTok 爆款视频"""
        # 优先使用 RapidAPI
        try:
            url = "https://tiktok-scraper7.p.rapidapi.com/feed/search"
            headers = {
                "x-rapidapi-key": self.api_key,
                "x-rapidapi-host": "tiktok-scraper7.p.rapidapi.com"
            }
            params = {"keywords": keyword, "count": count}
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                videos = data.get('data', {}).get('videos', [])
                viral_videos = [v for v in videos if v.get('digg_count', 0) >= min_likes]
                print(f"[RapidAPI] 找到 {len(viral_videos)} 个爆款视频")
                return viral_videos
            elif response.status_code == 429:
                print("[RapidAPI] 配额已用完，切换备用 API...")
                return self._search_with_backup_api(keyword, min_likes, count)
        except Exception as e:
            print(f"[RapidAPI 错误] {e}，尝试备用 API...")
            return self._search_with_backup_api(keyword, min_likes, count)

        return []

    def _search_with_backup_api(self, keyword: str, min_likes: int, count: int) -> List[Dict]:
        """使用备用 API（Evil0ctal/Douyin_TikTok_Download_API）"""
        try:
            # 使用公开的 TikTok API 服务
            url = "https://api.tiktok.com/v1/search/general"
            params = {"keyword": keyword, "count": count}
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                videos = data.get('data', [])
                viral_videos = [v for v in videos if v.get('stats', {}).get('diggCount', 0) >= min_likes]
                print(f"[备用 API] 找到 {len(viral_videos)} 个爆款视频")
                return viral_videos
        except Exception as e:
            print(f"[备用 API 错误] {e}")

        return []

    def get_video_comments(self, video_id: str, max_count: int = 20) -> List[Dict]:
        """抓取视频评论（只抓高赞评论）"""
        try:
            url = "https://tiktok-scraper7.p.rapidapi.com/comment/list"
            headers = {
                "x-rapidapi-key": self.api_key,
                "x-rapidapi-host": "tiktok-scraper7.p.rapidapi.com"
            }
            params = {"aweme_id": video_id, "count": max_count}
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                comments = data.get('data', {}).get('comments', [])
                # 只保留点赞数 > 100 的评论
                high_quality = [c for c in comments if c.get('digg_count', 0) > 100]
                return high_quality[:15]  # 最多15条
        except Exception as e:
            print(f"[评论抓取失败] {e}")
        return []

    def extract_video_info(self, video: Dict) -> Dict:
        """提取视频关键信息"""
        return {
            'video_id': video.get('video_id'),
            'title': video.get('title', ''),
            'author': video.get('author', {}).get('unique_id', ''),
            'likes': video.get('digg_count', 0),
            'comments': video.get('comment_count', 0),
            'shares': video.get('share_count', 0),
            'views': video.get('play_count', 0),
            'cover': video.get('cover', '')
        }

    def analyze_selling_points(self, videos: List[Dict]) -> Dict:
        """分析卖点（基础版：统计高频词和标签）"""
        all_text = ' '.join([v.get('title', '') for v in videos])
        all_tags = []
        for v in videos:
            all_tags.extend(v.get('hashtags', []))

        from collections import Counter
        tag_freq = Counter(all_tags)

        return {
            'top_hashtags': tag_freq.most_common(10),
            'avg_likes': sum(v.get('likes', 0) for v in videos) / len(videos) if videos else 0,
            'total_videos': len(videos)
        }

    def run_analysis(self, keyword: str, min_likes: int = 10000):
        """执行完整分析流程"""
        print(f"[1/3] 搜索关键词: {keyword}")
        videos = self.search_viral_videos(keyword, min_likes)

        print(f"[2/3] 提取 {len(videos)} 个爆款视频信息")
        video_data = [self.extract_video_info(v) for v in videos]

        print(f"[3/3] 分析卖点")
        analysis = self.analyze_selling_points(video_data)

        # 保存结果
        output = {
            'keyword': keyword,
            'analysis': analysis,
            'videos': video_data
        }
        output_file = self.output_dir / f"{keyword.replace(' ', '_')}_viral.json"
        output_file.write_text(json.dumps(output, ensure_ascii=False, indent=2))

        print(f"\n[完成] 结果保存至: {output_file}")
        return output

if __name__ == "__main__":
    analyzer = TikTokViralAnalyzer()
    print("请先配置 API Key（RapidAPI TikTok Scraper）")
    print("获取地址: https://rapidapi.com/DataFanatic/api/tiktok-scraper7")

    # analyzer.api_key = "YOUR_API_KEY"
    # analyzer.run_analysis("outdoor lighting lamp", min_likes=10000)
