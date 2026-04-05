"""
Self-Reflection Loop — analyzes historical signal performance
and generates insights for improvement.
Runs daily after backtest.
"""
import logging
from datetime import datetime
from duckscreeener.db.database import get_pattern_analysis, get_signal_stats, store_knowledge, save_setting, load_setting

logger = logging.getLogger(__name__)


def run_reflection():
    """
    Analyze all signal outcomes and generate insights.
    Stores insights in knowledge base for future reference.
    """
    try:
        stats = get_signal_stats()
        if not stats or stats['total'] == 0:
            return "No data for reflection yet."

        patterns = get_pattern_analysis()

        insights = []

        # Overall performance insight
        win_rate = stats['win_rate']
        avg_change = stats['avg_change']

        prev_win_rate = float(load_setting("last_win_rate", "0"))
        if prev_win_rate > 0:
            trend = "improving" if win_rate > prev_win_rate else "declining"
            insights.append(f"Win rate trend: {trend} ({prev_win_rate:.1f}% -> {win_rate:.1f}%)")

        save_setting("last_win_rate", str(win_rate))

        # Pattern insights
        if patterns:
            best = patterns[0]
            worst = patterns[-1]

            insights.append(
                f"Best performing pattern: {best['signal_type']} ({best['source_type']}) "
                f"with {best['win_rate']:.0f}% win rate ({best['total']} signals)"
            )

            if worst['win_rate'] < 40 and worst['total'] >= 3:
                insights.append(
                    f"Weakest pattern: {worst['signal_type']} ({worst['source_type']}) "
                    f"with {worst['win_rate']:.0f}% win rate — consider adjusting thresholds"
                )

        # Narrative insights
        narrative_stats = {}
        db = get_db()
        rows = db.execute(
            """
            SELECT s.narrative, COUNT(o.id) as total,
                   SUM(CASE WHEN o.result = 'SUCCESS' THEN 1 ELSE 0 END) as successes,
                   AVG(o.change_pct) as avg_change
            FROM scan_signals s
            JOIN signal_outcomes o ON s.id = o.signal_id
            WHERE s.narrative IS NOT NULL AND s.narrative != ''
            GROUP BY s.narrative
            HAVING total >= 2
            ORDER BY avg_change DESC
            """
        ).fetchall()

        for row in rows:
            narrative = row[0]
            total = row[1]
            successes = row[2]
            avg_chg = row[3]
            wr = (successes / total * 100) if total > 0 else 0
            narrative_stats[narrative] = {'total': total, 'win_rate': wr, 'avg_change': avg_chg}

        if narrative_stats:
            best_narrative = max(narrative_stats.items(), key=lambda x: x[1]['win_rate'])
            insights.append(
                f"Best narrative: '{best_narrative[0]}' — "
                f"{best_narrative[1]['win_rate']:.0f}% WR, avg {best_narrative[1]['avg_change']:+.1f}%"
            )

        # Store insight in knowledge base
        insight_text = f"Reflection {datetime.now().strftime('%Y-%m-%d')}:\n" + "\n".join(f"- {i}" for i in insights)
        store_knowledge("reflection", insight_text)

        logger.info(f"Reflection completed: {len(insights)} insights generated")
        return insight_text

    except Exception as e:
        logger.error(f"Reflection error: {e}")
        return f"Reflection error: {e}"
