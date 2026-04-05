"""Smart wallet command handlers"""
import logging
from duckscreeener.db.database import (
    get_all_smart_wallets, delete_smart_wallet, store_smart_wallet,
)
from duckscreeener.scanners.smart_wallet_tracker import (
    discover_smart_wallets, seed_wallet, analyze_wallet,
)
from duckscreeener.utils.message_split import send_long_message

logger = logging.getLogger(__name__)


async def smartwallets(update, context):
    """List all tracked smart wallets"""
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("🧠 Loading smart wallets...")

    wallets = get_all_smart_wallets(limit=50)
    if not wallets:
        await status_msg.edit_text("🧠 No smart wallets tracked yet.\nUse /smartwallet_discover to find new ones.")
        return

    msg = "🧠 Smart Wallets Tracker\n\n"
    msg += f"Total tracked: {len(wallets)}\n\n"

    for i, w in enumerate(wallets[:20], 1):
        addr_short = w['address'][:16] + "..."
        label = w.get('label', '?')
        wr = w.get('win_rate', 0)
        trades = w.get('total_trades', 0)
        tokens = w.get('unique_tokens', 0)
        trust = w.get('trust_score', 0)
        early = w.get('early_buyer_of', '')
        early_str = f" | Early: {early}" if early else ""

        emoji = "🌟" if label == "seed" else ("✅" if trust > 70 else "⚡" if trust > 50 else "📊")
        msg += f"{emoji} {i}. `{addr_short}`\n"
        msg += f"   Label: {label} | WR: {wr:.1f}% | Trades: {trades} | Tokens: {tokens}{early_str}\n"
        msg += f"   Trust: {trust:.0f}/100\n\n"

    if len(wallets) > 20:
        msg += f"... and {len(wallets) - 20} more\n"

    msg += "\nUse /smartwallet_discover to find new wallets"

    await send_long_message(msg, update, parse_mode="Markdown")


async def smartwallet_add(update, context):
    """Add a wallet manually"""
    if not context.args:
        await update.message.reply_text("Usage: /smartwallet_add <solana_address>")
        return

    wallet = context.args[0].strip()
    if len(wallet) < 32 or len(wallet) > 44:
        await update.message.reply_text("Invalid Solana address format.")
        return

    existing = get_all_smart_wallets(limit=100)
    if any(w['address'] == wallet for w in existing):
        await update.message.reply_text(f"Wallet `{wallet[:20]}...` already tracked.")
        return

    await update.message.reply_text(f"🔍 Analyzing wallet `{wallet[:20]}...`...")

    result = seed_wallet(wallet, label="manual")
    if result:
        wr = result.get('win_rate', 0)
        trades = result.get('total_trades', 0)
        tokens = result.get('unique_tokens', 0)
        trust = result.get('trust_score', 0)
        msg = (
            f"✅ Wallet added!\n\n"
            f"Address: `{wallet[:20]}...`\n"
            f"Win Rate: {wr:.1f}%\n"
            f"Total Trades: {trades}\n"
            f"Unique Tokens: {tokens}\n"
            f"Trust Score: {trust:.0f}/100"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"Failed to analyze wallet `{wallet[:20]}...`. Added with minimal data.")


async def smartwallet_remove(update, context):
    """Remove a wallet"""
    if not context.args:
        await update.message.reply_text("Usage: /smartwallet_remove <solana_address>")
        return

    wallet = context.args[0].strip()
    wallets = get_all_smart_wallets(limit=100)
    found = any(w['address'] == wallet for w in wallets)

    if not found:
        await update.message.reply_text("Wallet not found in tracked list.")
        return

    delete_smart_wallet(wallet)
    await update.message.reply_text(f"✅ Wallet `{wallet[:20]}...` removed.")


async def smartwallet_discover(update, context):
    """Trigger smart wallet discovery"""
    await update.message.reply_chat_action(action="typing")
    status_msg = await update.message.reply_text("🔍 Discovering new smart wallets... This may take a minute.")

    result = discover_smart_wallets()
    if isinstance(result, tuple):
        count, checked = result
    else:
        count = result
        checked = 0

    if count > 0:
        await status_msg.edit_text(f"✅ Found {count} new smart wallets! ({checked} wallets checked)\nUse /smartwallets to see the list.")
    else:
        await status_msg.edit_text(
            f"🔍 Discovery complete: {checked} wallets checked, no new smart wallets found.\n\n"
            f"Criteria: Win Rate ≥ 60%, Min Trade $50, ≥ 3 unique tokens, ≥ 5 trades.\n"
            f"Try again later or add wallets manually with /smartwallet_add."
        )
