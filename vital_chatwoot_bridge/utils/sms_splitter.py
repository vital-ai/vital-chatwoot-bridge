"""
Utility for splitting long SMS messages into ≤160-character chunks.

When Twilio sends a message longer than 160 characters (GSM-7), it segments it
into concatenated SMS.  Carriers may deliver these segments out of order.  By
pre-splitting the text on our side we ensure each Chatwoot → Twilio API call
maps to a single SMS segment, and a short inter-message delay keeps them
ordered on the recipient's phone.
"""

import logging
import re
from typing import List

logger = logging.getLogger(__name__)

# GSM-7 single-segment limit.  Using 160 rather than the concatenated-SMS
# per-segment limit (153) because each chunk will be its own standalone SMS.
SMS_CHAR_LIMIT = 160

# Delay in seconds between sending consecutive chunks.
SMS_CHUNK_DELAY_SECONDS = 1.5


def split_sms_message(text: str, limit: int = SMS_CHAR_LIMIT) -> List[str]:
    """Split *text* into chunks of at most *limit* characters.

    Splitting is done on word boundaries where possible so words are not
    broken mid-way.  If a single word exceeds *limit* it is hard-split.

    Returns a list with one or more non-empty strings.
    """
    if not text:
        return [text or ""]

    text = text.strip()
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    # Split on whitespace while preserving the delimiter position
    words = re.split(r"(\s+)", text)
    current = ""

    for token in words:
        # If adding this token would exceed the limit, flush current chunk
        if current and len(current) + len(token) > limit:
            chunks.append(current.strip())
            current = ""

        # Handle tokens (individual words) longer than the limit
        if len(token) > limit:
            # Flush anything accumulated
            if current:
                chunks.append(current.strip())
                current = ""
            # Hard-split the oversized token
            while len(token) > limit:
                chunks.append(token[:limit])
                token = token[limit:]
            if token:
                current = token
        else:
            current += token

    if current.strip():
        chunks.append(current.strip())

    logger.info(
        f"📱 SMS split: {len(text)} chars → {len(chunks)} chunk(s) "
        f"[{', '.join(str(len(c)) for c in chunks)} chars]"
    )
    return chunks
