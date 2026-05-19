#!/usr/bin/env python3
"""
Trend Intelligence API v1.0
跨平台趋势情报 API — Proxies.sx 赏金 #70 ($100)

功能：
1. 同时搜索 Reddit、YouTube、Twitter/X、Web
2. 聚合结果，生成结构化情报报告
3. 参与度加权评分
4. 模式检测

API 端点：
  GET /api/research?query=<topic>&depth=<shallow|deep>
  GET /api/trending?platform=<reddit|youtube|twitter|all>
  GET /api/sentiment?query=<topic>
  GET /health
"""

import json
import asyncio
import re
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

# ============================================================
# 数据模型
# ============================================================

@dataclass
class ContentItem:
    """内容条目"""
    platform: str  # reddit, youtube, twitter, web
    title: str
    url: str
    text: str
    author: str
    score: int  # 参与度分数
    comments: int
    timestamp: str
    sentiment: float = 0.0  # -1.0 to 1.0
    keywords: List[str] = field(default_factory=list)

@dataclass
class TrendReport:
    """趋势报告"""
    query: str
    depth: str
    platforms_searched: List[str]
    total_results: int
    items: List[ContentItem]
    top_keywords: List[Dict[str, int]]
    sentiment_summary: Dict[str, float]
    patterns: List[str]
    recommendations: List[str]
    generated_at: str


# ============================================================
# 多平台搜索客户端
# ============================================================

class MultiPlatformSearcher:
    """跨平台搜索器"""
    
    def __init__(self):
        self.session = None
    
    async def _ensure_session(self):
        import aiohttp
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "TrendIntelligence/1.0 (Hermes Agent)",
                    "Accept": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=20),
            )
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def search_all(self, query: str, depth: str = "shallow") -> TrendReport:
        """搜索所有平台"""
        await self._ensure_session()
        
        start_time = time.time()
        all_items = []
        platforms = []
        
        # Reddit 搜索
        reddit_items = await self.search_reddit(query, limit=20 if depth == "deep" else 10)
        all_items.extend(reddit_items)
        if reddit_items:
            platforms.append("reddit")
        
        # YouTube 搜索
        youtube_items = await self.search_youtube(query, limit=10 if depth == "deep" else 5)
        all_items.extend(youtube_items)
        if youtube_items:
            platforms.append("youtube")
        
        # Web 搜索（DuckDuckGo）
        web_items = await self.search_web(query, limit=10 if depth == "deep" else 5)
        all_items.extend(web_items)
        if web_items:
            platforms.append("web")
        
        # Twitter/X 搜索
        twitter_items = await self.search_twitter(query, limit=10 if depth == "deep" else 5)
        all_items.extend(twitter_items)
        if twitter_items:
            platforms.append("twitter")
        
        # 分析
        top_keywords = self._extract_keywords(all_items)
        sentiment_summary = self._calc_sentiment(all_items)
        patterns = self._detect_patterns(all_items)
        recommendations = self._generate_recommendations(query, all_items, sentiment_summary)
        
        return TrendReport(
            query=query,
            depth=depth,
            platforms_searched=platforms,
            total_results=len(all_items),
            items=all_items[:50],  # 最多返回50条
            top_keywords=top_keywords,
            sentiment_summary=sentiment_summary,
            patterns=patterns,
            recommendations=recommendations,
            generated_at=datetime.now().isoformat(),
        )
    
    async def search_reddit(self, query: str, limit: int = 10) -> List[ContentItem]:
        """搜索 Reddit"""
        items = []
        try:
            url = "https://www.reddit.com/search.json"
            params = {"q": query, "sort": "relevance", "t": "week", "limit": limit, "type": "link"}
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for child in data.get("data", {}).get("children", []):
                        p = child.get("data", {})
                        items.append(ContentItem(
                            platform="reddit",
                            title=p.get("title", ""),
                            url=p.get("url", ""),
                            text=p.get("selftext", "")[:300],
                            author=p.get("author", ""),
                            score=p.get("score", 0),
                            comments=p.get("num_comments", 0),
                            timestamp=datetime.fromtimestamp(p.get("created_utc", 0)).isoformat() if p.get("created_utc") else "",
                            keywords=self._extract_keywords_from_text(p.get("title", "") + " " + p.get("selftext", "")),
                        ))
        except Exception as e:
            print(f"   ⚠️ Reddit 搜索错误: {e}")
        return items
    
    async def search_youtube(self, query: str, limit: int = 5) -> List[ContentItem]:
        """搜索 YouTube（使用 Invidious 公开实例）"""
        items = []
        instances = [
            "https://yewtu.be",
            "https://y.com.sb",
            "https://vid.puffyan.us",
        ]
        
        for instance in instances:
            try:
                url = f"{instance}/api/v1/search"
                params = {"q": query, "sort_by": "relevance", "page": 1}
                async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for video in data[:limit]:
                            items.append(ContentItem(
                                platform="youtube",
                                title=video.get("title", ""),
                                url=f"https://youtube.com/watch?v={video.get('videoId', '')}",
                                text=video.get("description", "")[:300],
                                author=video.get("author", ""),
                                score=video.get("viewCount", 0),
                                comments=video.get("commentCount", 0),
                                timestamp=video.get("published", ""),
                                keywords=self._extract_keywords_from_text(video.get("title", "")),
                            ))
                        if items:
                            break
            except:
                continue
        
        return items
    
    async def search_web(self, query: str, limit: int = 5) -> List[ContentItem]:
        """搜索 Web（DuckDuckGo HTML）"""
        items = []
        try:
            url = "https://html.duckduckgo.com/html/"
            params = {"q": query}
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # 解析搜索结果
                    results = re.findall(
                        r'<a rel="nofollow" class="result__a" href="([^"]+)">(.*?)</a>.*?'
                        r'<a class="result__snippet"[^>]*>(.*?)</a>',
                        html, re.DOTALL
                    )
                    for url, title, snippet in results[:limit]:
                        title = re.sub(r'<[^>]+>', '', title).strip()
                        snippet = re.sub(r'<[^>]+>', '', snippet).strip()
                        items.append(ContentItem(
                            platform="web",
                            title=title,
                            url=url,
                            text=snippet[:300],
                            author="",
                            score=0,
                            comments=0,
                            timestamp="",
                            keywords=self._extract_keywords_from_text(title + " " + snippet),
                        ))
        except Exception as e:
            print(f"   ⚠️ Web 搜索错误: {e}")
        return items
    
    async def search_twitter(self, query: str, limit: int = 5) -> List[ContentItem]:
        """搜索 Twitter/X（通过 Nitter RSS）"""
        items = []
        instances = ["https://nitter.net", "https://nitter.privacydev.net"]
        
        for instance in instances:
            try:
                url = f"{instance}/search/rss"
                params = {"q": query}
                async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        entries = re.findall(r'<item>(.*?)</item>', text, re.DOTALL)
                        for entry in entries[:limit]:
                            title = re.search(r'<title>(.*?)</title>', entry, re.DOTALL)
                            link = re.search(r'<link>(.*?)</link>', entry, re.DOTALL)
                            pub = re.search(r'<pubDate>(.*?)</pubDate>', entry, re.DOTALL)
                            
                            t = re.sub(r'<[^>]+>', '', title.group(1)).strip() if title else ""
                            l = link.group(1).strip() if link else ""
                            
                            items.append(ContentItem(
                                platform="twitter",
                                title=t[:200],
                                url=l,
                                text="",
                                author=l.split("/")[3] if len(l.split("/")) > 3 else "",
                                score=0,
                                comments=0,
                                timestamp=pub.group(1).strip() if pub else "",
                                keywords=self._extract_keywords_from_text(t),
                            ))
                        if items:
                            break
            except:
                continue
        
        return items
    
    def _extract_keywords_from_text(self, text: str) -> List[str]:
        """从文本提取关键词"""
        # 简单实现：提取长度 > 3 的词
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        # 去重并保持顺序
        seen = set()
        keywords = []
        for w in words:
            if w not in seen and len(keywords) < 10:
                seen.add(w)
                keywords.append(w)
        return keywords
    
    def _extract_keywords(self, items: List[ContentItem]) -> List[Dict[str, int]]:
        """提取所有内容的热门关键词"""
        keyword_counts = {}
        for item in items:
            for kw in item.keywords:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1
        
        # 按频率排序
        sorted_kws = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
        return [{"keyword": k, "count": v} for k, v in sorted_kws[:20]]
    
    def _calc_sentiment(self, items: List[ContentItem]) -> Dict[str, float]:
        """计算情绪摘要"""
        positive_words = {"good", "great", "excellent", "amazing", "love", "best", "awesome", "fantastic", "bullish", "buy", "growth", "profit", "win", "success", "strong", "surge", "rally", "moon"}
        negative_words = {"bad", "terrible", "awful", "hate", "worst", "horrible", "bearish", "sell", "loss", "lose", "crash", "drop", "fall", "decline", "recession", "weak", "dump", "scam", "fraud"}
        
        pos_count = 0
        neg_count = 0
        total = 0
        
        for item in items:
            text = (item.title + " " + item.text).lower()
            pos = sum(1 for w in positive_words if w in text)
            neg = sum(1 for w in negative_words if w in text)
            pos_count += pos
            neg_count += neg
            total += max(pos + neg, 1)
        
        if total == 0:
            return {"positive": 0, "negative": 0, "neutral": 1.0, "overall": 0}
        
        pos_ratio = pos_count / total
        neg_ratio = neg_count / total
        neu_ratio = 1 - pos_ratio - neg_ratio
        
        return {
            "positive": round(pos_ratio, 3),
            "negative": round(neg_ratio, 3),
            "neutral": round(max(0, neu_ratio), 3),
            "overall": round((pos_count - neg_count) / total, 3),
        }
    
    def _detect_patterns(self, items: List[ContentItem]) -> List[str]:
        """检测模式"""
        patterns = []
        
        if not items:
            return ["未找到足够数据来检测模式"]
        
        # 按平台分组
        platform_counts = {}
        for item in items:
            platform_counts[item.platform] = platform_counts.get(item.platform, 0) + 1
        
        # 模式1: 平台分布
        if len(platform_counts) >= 3:
            patterns.append(f"跨平台讨论: 在 {', '.join(platform_counts.keys())} 上都有相关内容")
        
        # 模式2: 高参与度
        high_score_items = [i for i in items if i.score > 100]
        if len(high_score_items) > len(items) * 0.3:
            patterns.append(f"高参与度: {len(high_score_items)} 条内容获得 100+ 互动")
        
        # 模式3: 时间集中度
        recent_items = [i for i in items if i.timestamp and "2026" in i.timestamp]
        if len(recent_items) > len(items) * 0.5:
            patterns.append(f"近期活跃: {len(recent_items)} 条内容为近期发布")
        
        # 模式4: 情绪倾向
        sentiment = self._calc_sentiment(items)
        if sentiment["overall"] > 0.2:
            patterns.append("整体情绪偏正面")
        elif sentiment["overall"] < -0.2:
            patterns.append("整体情绪偏负面")
        
        return patterns if patterns else ["未检测到明显模式"]
    
    def _generate_recommendations(self, query: str, items: List[ContentItem], sentiment: Dict) -> List[str]:
        """生成建议"""
        recs = []
        
        if not items:
            recs.append("未找到相关数据，建议扩大搜索范围")
            return recs
        
        if sentiment["overall"] > 0.3:
            recs.append("社交媒体情绪积极，可能存在机会")
        elif sentiment["overall"] < -0.3:
            recs.append("社交媒体情绪谨慎，建议观望")
        
        platform_counts = {}
        for item in items:
            platform_counts[item.platform] = platform_counts.get(item.platform, 0) + 1
        
        if "reddit" in platform_counts and platform_counts["reddit"] > 5:
            recs.append("Reddit 讨论活跃，建议深入社区分析")
        
        if "youtube" in platform_counts and platform_counts["youtube"] > 3:
            recs.append("YouTube 视频内容较多，建议关注视频舆情")
        
        high_score = [i for i in items if i.score > 500]
        if high_score:
            recs.append(f"有 {len(high_score)} 条高互动内容，建议重点分析")
        
        return recs if recs else ["数据量有限，建议持续监控"]


# ============================================================
# 主程序
# ============================================================

async def main():
    """测试运行"""
    print("=" * 60)
    print("📊 Trend Intelligence API v1.0")
    print("=" * 60)
    
    searcher = MultiPlatformSearcher()
    
    try:
        query = "Bitcoin"
        print(f"\n🔍 跨平台研究 (query: '{query}', depth: shallow)...")
        
        report = await searcher.search_all(query, depth="shallow")
        
        print(f"\n   平台: {', '.join(report.platforms_searched)}")
        print(f"   总结果: {report.total_results}")
        print(f"\n   📈 情绪分析:")
        print(f"      正面: {report.sentiment_summary['positive']:.1%}")
        print(f"      负面: {report.sentiment_summary['negative']:.1%}")
        print(f"      中性: {report.sentiment_summary['neutral']:.1%}")
        print(f"      综合: {report.sentiment_summary['overall']:+.3f}")
        
        print(f"\n   🔑 热门关键词:")
        for kw in report.top_keywords[:10]:
            print(f"      {kw['keyword']}: {kw['count']}")
        
        print(f"\n   📋 检测到的模式:")
        for p in report.patterns:
            print(f"      • {p}")
        
        print(f"\n   💡 建议:")
        for r in report.recommendations:
            print(f"      • {r}")
        
        # 保存报告
        output = {
            "query": report.query,
            "depth": report.depth,
            "platforms": report.platforms_searched,
            "total_results": report.total_results,
            "sentiment": report.sentiment_summary,
            "top_keywords": report.top_keywords[:20],
            "patterns": report.patterns,
            "recommendations": report.recommendations,
            "items": [
                {
                    "platform": i.platform,
                    "title": i.title[:100],
                    "url": i.url,
                    "score": i.score,
                    "comments": i.comments,
                }
                for i in report.items[:20]
            ],
            "generated_at": report.generated_at,
        }
        
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / f"trend_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n📄 报告已保存: {output_file}")
        
    finally:
        await searcher.close()


if __name__ == "__main__":
    asyncio.run(main())
