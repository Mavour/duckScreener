import logging
import re
import requests
from duckscreeener.config.settings import OPENROUTER_API_KEY, OPENROUTER_MODEL, TWITTER_BEARER_TOKEN, COINGECKO_NEWS_URL, COINGECKO_API_URL, TWITTER_FALLBACK_MODE, BOT_LANGUAGE

logger = logging.getLogger(__name__)

try:
    import tweepy
    TWEEPY_AVAILABLE = True
except ImportError:
    TWEEPY_AVAILABLE = False
    logger.warning("Tweepy not installed for X (Twitter) integration; /tweets disabled.")


def fetch_latest_news(limit=5):
    try:
        resp = requests.get(f"{COINGECKO_NEWS_URL}?page=1", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        news_items = data.get('data', [])
        selected = news_items[:limit]
        summary_parts = []
        for item in selected:
            title = item.get('title', '').strip()
            desc = item.get('description', '').strip()
            url = item.get('url', '')
            if title:
                summary_parts.append(f"{title} - {desc[:150]}... ({url})")
        result = "\n".join(summary_parts) if summary_parts else "No recent news found."
        return result
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return "Failed to fetch news."


def fetch_latest_news_with_items(limit=10):
    try:
        resp = requests.get(f"{COINGECKO_NEWS_URL}?page=1", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get('data', [])[:limit]
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return []


def get_twitter_client():
    if not TWEEPY_AVAILABLE or not TWITTER_BEARER_TOKEN:
        return None
    try:
        client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
        return client
    except Exception as e:
        logger.error(f"Failed to initialize Twitter client: {e}")
        return None


def fetch_tweets(query, max_results=10, trusted_only=False, trusted_accounts=None):
    error_msg = ""
    error_code = None

    if not TWEEPY_AVAILABLE or not TWITTER_BEARER_TOKEN:
        return [], "Tweepy not available or missing bearer token.", None

    try:
        client = get_twitter_client()
        if not client:
            return [], "Failed to initialize Twitter client.", None

        safe_query = query.strip()
        if not safe_query:
            return [], "Empty query.", None

        if 'is:retweet' not in safe_query.lower():
            safe_query += ' -is:retweet'
        if BOT_LANGUAGE == 'id':
            safe_query += ' lang:id'
        else:
            safe_query += ' lang:en'

        tweets = client.search_recent_tweets(
            query=safe_query,
            max_results=min(max_results, 100),
            tweet_fields=['created_at', 'author_id', 'lang'],
            expansions=['author_id'],
            user_fields=['username']
        )

        if not tweets.data:
            return [], "", None

        user_map = {}
        if tweets.includes and 'users' in tweets.includes:
            for user in tweets.includes['users']:
                user_map[user.id] = user.username

        result = []
        for tweet in tweets.data:
            author = user_map.get(tweet.author_id, 'unknown')

            if trusted_only and trusted_accounts:
                if author.lower() not in [x.lower() for x in trusted_accounts]:
                    continue

            result.append({
                'text': tweet.text,
                'author': author,
                'created_at': tweet.created_at.isoformat() if tweet.created_at else '',
                'tweet_id': tweet.id
            })
        return result, "", None
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_code = getattr(e.response, 'status_code', None)
        elif hasattr(e, 'status_code'):
            error_code = getattr(e, 'status_code', None)
        elif TWEEPY_AVAILABLE and isinstance(e, tweepy.errors.TooManyRequests):
            error_code = 429
        logger.error(f"Error fetching tweets: {e}")
        return [], error_msg, error_code


def openrouter_chat(prompt: str, system: str = "You are a helpful crypto analyst.") -> str:
    import random
    import time as time_module

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4000,
    }
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            message = result.get('choices', [{}])[0].get('message', {})
            content = message.get('content')
            if content is None:
                refusal = message.get('refusal')
                if refusal:
                    return refusal.strip()
                reasoning = message.get('reasoning')
                if reasoning:
                    return reasoning.strip()
                return "Sorry, I couldn't generate a response."
            return content.strip()
        except requests.exceptions.RequestException as e:
            logger.warning(f"OpenRouter request attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                sleep_time = (2 ** attempt) + random.uniform(0, 1)
                time_module.sleep(sleep_time)
            else:
                logger.error(f"OpenRouter error after {max_retries} attempts: {e}")
                if "401" in str(e) or "Unauthorized" in str(e):
                    return "OpenRouter API key tidak valid atau expired."
                return "LLM service sedang unavailable. Coba lagi nanti."
        except (KeyError, IndexError, ValueError) as e:
            logger.error(f"OpenRouter response parsing error: {e}")
            return "Error parsing response. Coba lagi nanti."


def extract_text_from_pdf(file_path):
    try:
        import fitz
        doc = fitz.open(file_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        return "\n".join(text_parts).strip()
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return f"PDF extraction failed: {e}"


def extract_text_from_image(file_path):
    try:
        from PIL import Image
        import pytesseract
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as e:
        logger.error(f"Image OCR failed: {e}")
        return f"Image OCR failed: {e}"


def extract_text_from_youtube(url):
    try:
        import yt_dlp
    except ImportError:
        try:
            import subprocess, sys
            subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp", "-q"])
            import yt_dlp
        except:
            return "YouTube extraction not available. Please install yt-dlp: pip install yt-dlp"

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'writesubtitles': True,
        'subtitleslangs': ['en', 'id'],
        'writeautomaticsub': True,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', '')
            duration = info.get('duration', 0)
            description = info.get('description', '')

            # Try to get transcript/subtitles
            transcript_text = ""
            subtitles = info.get('subtitles', {})
            automatic_captions = info.get('automatic_captions', {})

            # Merge both sources
            all_subs = {**automatic_captions, **subtitles}

            for lang in ['en', 'id', 'en-US', 'id-ID']:
                if lang in all_subs:
                    sub_list = all_subs[lang]
                    for sub in sub_list:
                        if sub.get('ext') == 'vtt' or sub.get('ext') == 'json3':
                            sub_url = sub.get('url')
                            if sub_url:
                                try:
                                    sub_resp = requests.get(sub_url, timeout=10)
                                    if sub_resp.status_code == 200:
                                        sub_content = sub_resp.text
                                        # Strip VTT timestamps
                                        clean = re.sub(r'\d{2}:\d{2}:\d{2}\.\d{3} --> \d{2}:\d{2}:\d{2}\.\d{3}\n', '', sub_content)
                                        clean = re.sub(r'<[^>]+>', '', clean)
                                        transcript_text = clean.strip()
                                        if transcript_text:
                                            break
                                except:
                                    pass
                    if transcript_text:
                        break

            if transcript_text:
                return f"Video: {title}\nDuration: {duration//60} min\n\nTranscript:\n{transcript_text[:8000]}"
            else:
                return f"Video: {title}\nDuration: {duration//60} min\n\nDescription:\n{description[:5000] if description else 'No description or transcript available'}"
    except Exception as e:
        logger.error(f"YouTube extraction failed: {e}")
        return f"YouTube extraction failed: {e}"


def extract_tweet_from_url(url):
    tweet_content = ""
    tweet_id = None
    username = None

    if "/status/" in url:
        parts = url.split("/status/")
        if len(parts) > 1:
            tweet_id = parts[-1].split("?")[0]
        path_parts = url.split("/")
        for i, p in enumerate(path_parts):
            if p == "status" and i > 0:
                username = path_parts[i-1]
                break

    # Try Tweepy API
    if tweet_id and TWITTER_BEARER_TOKEN and TWEEPY_AVAILABLE:
        try:
            client = get_twitter_client()
            tweet = client.get_tweet(tweet_id, expansions=["author_id"])
            if tweet.data:
                tweet_content = f"Tweet by @{tweet.includes['users'][0].username if tweet.includes and 'users' in tweet.includes else username}: {tweet.data.text}"
        except Exception:
            pass

    # Try OEmbed API
    if not tweet_content and "/status/" in url:
        try:
            oembed_url = f"https://publish.twitter.com/oembed?url={url}"
            resp = requests.get(oembed_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                html_content = data.get('html', '')
                clean_text = re.sub(r'<[^>]+>', '', html_content)
                clean_text = clean_text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                if clean_text and len(clean_text) > 10:
                    tweet_content = f"Tweet embed:\n{clean_text}"
        except Exception:
            pass

    # Try web scraping as fallback
    if not tweet_content and "/status/" in url:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                html = resp.text
                content_match = re.search(r'"text":"([^"]+)"', html)
                if content_match:
                    tweet_content = content_match.group(1).replace('\\n', '\n')
                if not tweet_content:
                    meta_match = re.search(r'<meta name="description" content="([^"]+)"', html)
                    if meta_match:
                        tweet_content = meta_match.group(1)
        except Exception:
            pass

    return tweet_content, username, tweet_id
