"""
Proactive Insights — generates unsolicited insights based on
current market data and historical patterns.
"""
import logging
from datetime import datetime
from duckscreeener.db.database import get_signal_stats, get_pattern_analysis, get_recent_knowledge, store_knowledge
from duckscreeener.scanners.coin_scanner import scan_potential_coins
from duckscreeener.scanners.memecoin_scanner import scan_new_memecoins

logger = logging.getLogger(__name__)


def generate_daily_briefing():
    """Generate a morning briefing with proactive insights"""
    try:
        stats = get_signal_stats()
        patterns = get_pattern_analysis()
        recent = get_recent_knowledge(3)

        briefing = f"Morning Briefing — {datetime.now().strftime('%d %B %Y')}\n\n"

        # Performance summary
        if stats and stats['total'] > 0:
            briefing += f"PERFORMA SIGNAL\n"
            briefing += f"- Total checked: {stats['total']}\n"
            briefing += f"- Win rate: {stats['win_rate']:.1f}%\n"
            briefing += f"- Avg change: {stats['avg_change']:+.1f}%\n\n"

        # Pattern insights
        if patterns:
            briefing += "PATTERN TERBAIK:\n"
            for p in patterns[:3]:
                briefing += f"- {p['signal_type']} ({p['source_type']}): {p['win_rate']:.0f}% WR\n"
            briefing += "\n"

        # Recent knowledge
        if recent:
            briefing += "PELAJARAN TERAKHIR:\n"
            for r in recent:
                preview = r['text'][:100].replace('\n', ' ')
                briefing += f"- [{r['source']}] {preview}...\n"
            briefing += "\n"

        return briefing

    except Exception as e:
        logger.error(f"Daily briefing error: {e}")
        return f"Morning Briefing error: {e}"


def detect_opportunities():
    """Scan for opportunities matching historical winning patterns"""
    try:
        patterns = get_pattern_analysis()
        if not patterns:
            return None

        # Find best performing pattern
        best = max(patterns, key=lambda p: p['win_rate'])

        briefing = f"OPPORTUNITY DETECTED\n"
        briefing += f"Pattern '{best['signal_type']}' has {best['win_rate']:.0f}% win rate.\n"
        briefing += f"Scanning for matches...\n\n"

        # Run scans
        coins = scan_potential_coins()
        memecoins = scan_new_memecoins(hours=12, limit=5)

        if coins:
            briefing += f"Found {len(coins)} whale accumulation signals:\n"
            for c in coins[:3]:
                briefing += f"- {c['name']} ({c['symbol']}): {c['gem_type']}\n"

        if memecoins:
            briefing += f"\nFound {len(memecoins)} promising memecoins:\n"
            for m in memecoins[:3]:
                briefing += f"- {m['name']} ({m['symbol']}): Score {m['score']}\n"

        if not coins and not memecoins:
            briefing += "No matching opportunities found right now."

        return briefing

    except Exception as e:
        logger.error(f"Opportunity detection error: {e}")
        return None
