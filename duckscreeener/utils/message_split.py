"""
Utility: split and send long Telegram messages.
Replaces duplicated message-splitting logic across handlers.
"""
import logging

logger = logging.getLogger(__name__)

MAX_TELEGRAM_MSG = 4000


async def send_long_message(message, update, parse_mode=None):
    """Split and send messages exceeding Telegram's 4096 char limit."""
    if len(message) <= MAX_TELEGRAM_MSG:
        return await update.message.reply_text(message, parse_mode=parse_mode)

    # Split on double newlines first
    parts = message.split("\n\n")
    chunks = []
    current = ""
    for part in parts:
        if len(current) + len(part) + 2 > MAX_TELEGRAM_MSG:
            if current.strip():
                chunks.append(current.strip())
            current = part
        else:
            current = current + "\n\n" + part if current else part
    if current.strip():
        chunks.append(current.strip())

    # If any single chunk is still too long, split on single newlines
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= MAX_TELEGRAM_MSG:
            final_chunks.append(chunk)
        else:
            sub_parts = chunk.split("\n")
            sub_current = ""
            for sub in sub_parts:
                if len(sub_current) + len(sub) + 1 > MAX_TELEGRAM_MSG:
                    if sub_current.strip():
                        final_chunks.append(sub_current.strip())
                    sub_current = sub
                else:
                    sub_current = sub_current + "\n" + sub if sub_current else sub
            if sub_current.strip():
                final_chunks.append(sub_current.strip())

    for chunk in final_chunks:
        try:
            await update.message.reply_text(chunk, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Failed to send message chunk: {e}")
