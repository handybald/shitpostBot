"""
Performance Analysis Engine - Analyze metrics and optimize content selection.

Handles:
- Engagement pattern analysis
- Time-of-day optimization
- Theme effectiveness tracking
- Content combination analysis
- Self-learning weight optimization
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from statistics import mean, stdev

from src.utils.logger import get_logger
from src.utils.config_loader import get_config_instance
from src.database import get_session
from src.database.repositories import (
    PostMetricsRepository, PublishedPostRepository,
    GeneratedReelRepository
)

logger = get_logger(__name__)


class PerformanceAnalyzer:
    """Analyze performance metrics and generate insights."""

    def __init__(self, session=None):
        """
        Initialize analyzer.

        Args:
            session: Database session (auto-created if not provided)
        """
        self.session = session or get_session()
        self.config = get_config_instance()
        self.metrics_repo = PostMetricsRepository(self.session)
        self.pub_repo = PublishedPostRepository(self.session)
        self.reel_repo = GeneratedReelRepository(self.session)

        logger.info("Performance analyzer initialized")

    def analyze_engagement_patterns(self, days: int = 30) -> Dict[str, Any]:
        """
        Analyze engagement patterns over time.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with engagement statistics
        """
        logger.info(f"Analyzing engagement patterns (last {days} days)")

        cutoff = datetime.utcnow() - timedelta(days=days)
        recent_metrics = self.metrics_repo.get_recent(days)

        if not recent_metrics:
            logger.warning(f"No metrics found for last {days} days")
            return {"error": "No data available"}

        # Calculate statistics
        likes = [m.likes or 0 for m in recent_metrics]
        comments = [m.comments or 0 for m in recent_metrics]
        shares = [m.shares or 0 for m in recent_metrics]
        reach = [m.reach or 0 for m in recent_metrics]
        engagement_rates = [m.engagement_rate or 0 for m in recent_metrics if m.engagement_rate]

        stats = {
            "period_days": days,
            "posts_analyzed": len(recent_metrics),
            "likes": {
                "total": sum(likes),
                "average": mean(likes),
                "max": max(likes),
                "min": min(likes),
                "stdev": stdev(likes) if len(likes) > 1 else 0,
            },
            "comments": {
                "total": sum(comments),
                "average": mean(comments),
                "max": max(comments),
                "min": min(comments),
                "stdev": stdev(comments) if len(comments) > 1 else 0,
            },
            "shares": {
                "total": sum(shares),
                "average": mean(shares),
                "max": max(shares),
                "min": min(shares),
            },
            "reach": {
                "total": sum(reach),
                "average": mean(reach),
                "max": max(reach),
                "min": min(reach),
            },
            "engagement_rate": {
                "average": mean(engagement_rates) if engagement_rates else 0,
                "max": max(engagement_rates) if engagement_rates else 0,
            }
        }

        logger.info(f"Engagement stats: {stats['posts_analyzed']} posts, {stats['likes']['total']} likes")
        return stats

    def analyze_by_theme(self, days: int = 30) -> Dict[str, Dict[str, Any]]:
        """
        Analyze performance by content theme.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with theme-specific statistics
        """
        logger.info(f"Analyzing performance by theme (last {days} days)")

        theme_data = {}

        try:
            # Get all published posts from last N days
            cutoff = datetime.utcnow() - timedelta(days=days)
            published = self.pub_repo.get_all()

            for post in published:
                if not post.reel or post.published_at < cutoff:
                    continue

                theme = post.reel.video.theme or "unknown"

                if theme not in theme_data:
                    theme_data[theme] = {
                        "count": 0,
                        "likes": [],
                        "comments": [],
                        "reach": [],
                        "engagement_rates": []
                    }

                # Get metrics for this post
                metrics = self.metrics_repo.session.query(
                    self.metrics_repo.model
                ).filter(self.metrics_repo.model.post_id == post.id).all()

                for metric in metrics:
                    theme_data[theme]["count"] += 1
                    theme_data[theme]["likes"].append(metric.likes or 0)
                    theme_data[theme]["comments"].append(metric.comments or 0)
                    theme_data[theme]["reach"].append(metric.reach or 0)
                    if metric.engagement_rate:
                        theme_data[theme]["engagement_rates"].append(metric.engagement_rate)

            # Calculate aggregates
            theme_stats = {}
            for theme, data in theme_data.items():
                if data["count"] == 0:
                    continue

                theme_stats[theme] = {
                    "post_count": data["count"],
                    "avg_likes": mean(data["likes"]),
                    "avg_comments": mean(data["comments"]),
                    "avg_reach": mean(data["reach"]),
                    "avg_engagement": mean(data["engagement_rates"]) if data["engagement_rates"] else 0,
                    "total_reach": sum(data["reach"])
                }

            logger.info(f"Theme analysis: {len(theme_stats)} themes analyzed")
            return theme_stats

        except Exception as e:
            logger.error(f"Error analyzing by theme: {e}")
            return {}

    def analyze_by_posting_time(self, days: int = 30) -> Dict[int, Dict[str, Any]]:
        """
        Analyze performance by hour of day posted.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with performance by hour (0-23)
        """
        logger.info(f"Analyzing performance by posting time (last {days} days)")

        hour_data = {h: {"count": 0, "likes": [], "engagement": []} for h in range(24)}

        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            published = self.pub_repo.get_all()

            for post in published:
                if not post.published_at or post.published_at < cutoff:
                    continue

                hour = post.published_at.hour

                metrics = self.metrics_repo.session.query(
                    self.metrics_repo.model
                ).filter(self.metrics_repo.model.post_id == post.id).all()

                for metric in metrics:
                    hour_data[hour]["count"] += 1
                    hour_data[hour]["likes"].append(metric.likes or 0)
                    if metric.engagement_rate:
                        hour_data[hour]["engagement"].append(metric.engagement_rate)

            # Calculate aggregates, remove empty hours
            hour_stats = {}
            for hour, data in hour_data.items():
                if data["count"] > 0:
                    hour_stats[hour] = {
                        "posts": data["count"],
                        "avg_likes": mean(data["likes"]),
                        "avg_engagement": mean(data["engagement"]) if data["engagement"] else 0
                    }

            logger.info(f"Posting time analysis: {len(hour_stats)} hours with posts")
            return hour_stats

        except Exception as e:
            logger.error(f"Error analyzing by posting time: {e}")
            return {}

    def find_top_performers(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Find highest performing posts.

        Args:
            limit: Number of top posts to return

        Returns:
            List of top performing posts with metadata
        """
        logger.info(f"Finding top {limit} performers")

        try:
            published = self.pub_repo.get_all()

            # Score each post
            scored = []
            for post in published:
                metrics = self.metrics_repo.session.query(
                    self.metrics_repo.model
                ).filter(self.metrics_repo.model.post_id == post.id).all()

                if metrics:
                    total_engagement = sum(
                        (m.likes or 0) + (m.comments or 0) + (m.shares or 0)
                        for m in metrics
                    )
                    avg_engagement = mean([m.engagement_rate or 0 for m in metrics])

                    scored.append({
                        "id": post.id,
                        "caption": post.caption[:60],
                        "theme": post.reel.video.theme if post.reel else "unknown",
                        "total_engagement": total_engagement,
                        "avg_engagement_rate": avg_engagement,
                        "published_at": post.published_at.isoformat() if post.published_at else None
                    })

            # Sort by engagement and return top N
            top = sorted(scored, key=lambda x: x["total_engagement"], reverse=True)[:limit]

            logger.info(f"Found {len(top)} top performers")
            return top

        except Exception as e:
            logger.error(f"Error finding top performers: {e}")
            return []

    def generate_insights(self, days: int = 30) -> Dict[str, str]:
        """
        Generate AI-like insights from data.

        Args:
            days: Number of days to analyze

        Returns:
            Dict with insight messages
        """
        logger.info(f"Generating insights (last {days} days)")

        insights = {}

        try:
            # Overall performance
            stats = self.analyze_engagement_patterns(days)
            if stats.get("error"):
                return {"error": "Not enough data for insights"}

            insights["engagement"] = (
                f"Average engagement: {stats['engagement_rate']['average']:.2%}. "
                f"Max engagement rate: {stats['engagement_rate']['max']:.2%}"
            )

            # Best theme
            theme_stats = self.analyze_by_theme(days)
            if theme_stats:
                best_theme = max(theme_stats.items(), key=lambda x: x[1]["avg_engagement"])
                insights["best_theme"] = (
                    f"🏆 {best_theme[0].title()} theme performs best with "
                    f"{best_theme[1]['avg_engagement']:.2%} avg engagement"
                )

            # Best posting time
            hour_stats = self.analyze_by_posting_time(days)
            if hour_stats:
                best_hour = max(hour_stats.items(), key=lambda x: x[1]["avg_engagement"])
                insights["best_time"] = (
                    f"⏰ Posts at {best_hour[0]:02d}:00 get {best_hour[1]['avg_engagement']:.2%} "
                    f"avg engagement ({best_hour[1]['posts']} posts)"
                )

            logger.info(f"Generated {len(insights)} insights")
            return insights

        except Exception as e:
            logger.error(f"Error generating insights: {e}")
            return {"error": str(e)}

    def calculate_recommended_weights(self) -> Dict[str, float]:
        """
        Calculate recommended content selection weights based on performance.

        Returns:
            Dict with theme weights (sum to 1.0)
        """
        logger.info("Calculating recommended weights")

        try:
            theme_stats = self.analyze_by_theme(days=90)

            if not theme_stats:
                logger.warning("No performance data for weight calculation")
                return {}

            # Normalize by engagement rate
            total_engagement = sum(s["avg_engagement"] for s in theme_stats.values())

            weights = {}
            for theme, stats in theme_stats.items():
                weight = stats["avg_engagement"] / total_engagement if total_engagement > 0 else 1.0
                weights[theme] = round(weight, 3)

            logger.info(f"Calculated weights: {weights}")
            return weights

        except Exception as e:
            logger.error(f"Error calculating weights: {e}")
            return {}

    def get_summary_report(self, days: int = 30) -> str:
        """
        Generate a summary report for Telegram.

        Args:
            days: Number of days to include

        Returns:
            Formatted report string
        """
        logger.info(f"Generating summary report ({days} days)")

        try:
            stats = self.analyze_engagement_patterns(days)
            if stats.get("error"):
                return "Not enough data for report"

            insights = self.generate_insights(days)

            report = f"""
📊 *Performance Report ({days} days)*

👍 *Engagement*
• Total Likes: {stats['likes']['total']}
• Average: {stats['likes']['average']:.0f}
• Peak: {stats['likes']['max']}

💬 *Comments*
• Total: {stats['comments']['total']}
• Average: {stats['comments']['average']:.1f}

📢 *Reach*
• Total Reach: {stats['reach']['total']:,}
• Average: {stats['reach']['average']:.0f}

⚡ *Engagement Rate*
• Average: {stats['engagement_rate']['average']:.2%}
• Peak: {stats['engagement_rate']['max']:.2%}

🎯 *Insights*
{chr(10).join(f"• {v}" for v in insights.values())}
            """

            return report

        except Exception as e:
            logger.error(f"Error generating report: {e}")
            return f"Error generating report: {e}"
