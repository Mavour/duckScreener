import logging
import time
import requests
from datetime import datetime
from duckscreeener.services.external_apis import openrouter_chat

logger = logging.getLogger(__name__)

NARRATIVE_KEYWORDS = {
    "AI": ["ai", "artificial", "intelligence", "neural", "deep", "learning", "bot", "agent", "gpt", "llm", "model", "grok", "openai", "compute", "gpu", "tensor", "algorithm"],
    "Gaming": ["game", "gaming", "play", "nft", "metaverse", "virtual", "world", "quest", "arena", "battle", "pixel", "rpg", "adventure", "level", "xp", "guild", "clan"],
    "Political": ["trump", "biden", "election", "vote", "president", "usa", "freedom", "democrat", "republican", "politic", "congress", "senate", "maga", "kamala", "bernie"],
    "Animal": [
        "dog", "cat", "frog", "bird", "fish", "bear", "wolf", "tiger", "lion", "monkey",
        "ape", "penguin", "hamster", "duck", "goose", "chicken", "pig", "cow", "horse",
        "shiba", "inu", "pup", "kitty", "kitten", "bunny", "rabbit", "rat", "mouse", "snake",
        "dragon", "eagle", "owl", "shark", "whale", "dolphin", "crab", "lobster",
        "fox", "deer", "elk", "moose", "raccoon", "squirrel", "beaver", "otter",
        "seal", "panda", "koala", "sloth", "lemur", "gorilla", "chimp", "hyena",
        "coyote", "husky", "corgi", "pug", "bulldog", "lab", "poodle", "terrier",
        "spaniel", "hound", "beagle", "dachshund", "chihuahua", "pomeranian",
        "samoyed", "akita", "maltese", "rottweiler", "doberman", "boxer", "schnauzer",
        "collie", "mastiff", "bull", "staffy", "pitbull", "feline", "tabby",
        "siamese", "persian", "bengal", "sphynx", "ragdoll", "maine", "coon",
        "toad", "pepe", "kermit", "ribbit", "amphibian", "tadpole",
        "parrot", "hawk", "flamingo", "toucan", "swan", "rooster", "hen", "turkey",
        "octopus", "squid", "jellyfish", "seahorse", "starfish", "turtle", "walrus",
        "polar", "sloth", "raccoon", "gerbil", "guinea",
    ],
    "Meme Culture": [
        "pepe", "based", "wif", "hat", "bonk", "meme", "lol", "funny", "vibe",
        "chill", "sigma", "alpha", "beta", "giga", "chad", "mog", "rizz",
        "skibidi", "ohio", "gyatt", "fanum", "tax", "grimace", "shake",
        "pookie", "bussin", "delulu", "girlboss", "gaslight", "gatekeep",
        "main", "character", "era", "villain", "energy", "touch", "grass",
        "ratio", "cringe", "mid", "goated", "banger", "slaps",
        "vibes", "aesthetic", "core", "maxxing", "looks", "mewing", "hunter",
        "mogging", "hawk", "tuah", "no", "cap", "fr", "ong",
        "slay", "ate", "left", "crumbs", "delusional", "it", "girl", "boy",
    ],
    "DeFi": [
        "swap", "dex", "yield", "farm", "stake", "lend", "borrow", "vault",
        "pool", "liquid", "protocol", "finance", "bank", "credit", "debt",
        "interest", "apy", "apr", "reward", "tokenomics", "defi", "amm",
        "lp", "slippage", "impermanent", "loss", "arbitrage", "mev", "flash",
        "loan", "collateral", "liquidation", "margin", "leverage", "perpetual",
        "futures", "options", "derivative", "synthetic", "wrapped", "bridge",
    ],
    "Meme/Parody": [
        "elon", "musk", "snoop", "dogg", "kardashian", "trump", "biden",
        "bezos", "zuck", "mark", "buffett", "dalio", "cohen", "ship", "hol",
        "robin", "hood", "game", "stop", "amc", "bb", "nok", "gme",
        "moon", "lambo", "diamond", "hands", "hodl", "wen", "ngmi", "gm",
        "gn", "wagmi", "ape", "in", "fud", "fomo", "dyor", "nfa",
        "ta", "fa", "mc", "fdv", "ath", "atl", "roi", "pnl", "whale",
        "shrimp", "crab", "fish", "shark", "bull", "bear", "degen", "normie",
        "chad", "virgin", "sigma", "beta", "alpha", "omega", "giga",
        "based", "cringe", "mid", "goated", "banger", "slaps", "vibes",
        "aesthetic", "core", "rizz", "skibidi", "ohio", "gyatt", "fanum",
        "tax", "grimace", "shake", "hawk", "tuah", "pookie", "bussin",
        "delulu", "girlboss", "gaslight", "gatekeep", "main", "character",
        "era", "villain", "energy", "touch", "grass", "ratio", "L", "W",
    ],
    "Food": [
        "pizza", "burger", "taco", "sushi", "ramen", "noodle", "rice",
        "bread", "cake", "cookie", "candy", "chocolate", "coffee", "tea",
        "beer", "wine", "vodka", "whiskey", "gin", "rum", "tequila",
        "milk", "cheese", "butter", "cream", "sugar", "salt", "pepper",
        "spice", "herb", "sauce", "ketchup", "mustard", "mayo", "honey",
        "banana", "apple", "orange", "lemon", "lime", "grape", "melon",
        "watermelon", "strawberry", "blueberry", "raspberry", "cherry",
        "peach", "mango", "pineapple", "coconut", "avocado", "tomato",
        "potato", "carrot", "onion", "garlic", "ginger", "mushroom",
    ],
    "Culture/Pop": [
        "anime", "manga", "otaku", "weeb", "naruto", "goku", "sailor",
        "pokemon", "digimon", "dragon", "ball", "one", "piece",
        "attack", "titan", "demon", "slayer", "jujutsu", "kaisen",
        "chainsaw", "man", "spy", "family", "tokyo", "revengers",
        "movie", "film", "cinema", "hollywood", "netflix", "disney",
        "marvel", "dc", "star", "wars", "harry", "potter", "lord",
        "rings", "game", "thrones", "breaking", "bad", "stranger",
        "things", "squid", "wednesday", "barbie", "oppenheimer",
    ],
    "Music": [
        "music", "song", "beat", "dj", "rap", "hip", "hop", "rock",
        "pop", "jazz", "blues", "metal", "punk", "reggae", "country",
        "classical", "electronic", "dance", "edm", "techno", "house",
        "trance", "dubstep", "trap", "lofi", "chillhop", "synthwave",
        "retrowave", "vaporwave", "phonk", "drift", "bass", "treble",
    ],
    "Science/Space": [
        "space", "moon", "mars", "planet", "star", "galaxy", "universe",
        "cosmos", "astro", "naut", "rocket", "launch", "orbit", "satellite",
        "alien", "ufo", "nasa", "spacex", "tesla", "quantum", "physics",
        "chemistry", "biology", "math", "number", "equation", "formula",
    ],
    "Religion/Mythology": [
        "god", "goddess", "angel", "demon", "devil", "satan", "heaven",
        "hell", "paradise", "nirvana", "karma", "dharma", "zen", "buddha",
        "christ", "jesus", "mary", "joseph", "moses", "abraham", "noah",
        "adam", "eve", "lucifer", "archangel", "seraphim", "cherubim",
        "zeus", "hera", "poseidon", "hades", "athena", "apollo", "artemis",
        "ares", "aphrodite", "hermes", "hephaestus", "dionysus", "demeter",
        "odin", "thor", "loki", "freya", "frigg", "heimdall", "tyr",
        "anubis", "ra", "isis", "osiris", "horus", "seth", "bastet",
        "cthulhu", "lovecraft", "eldritch", "cosmic", "horror", "abyss",
    ],
    "Math/Numbers": [
        "420", "69", "42", "777", "666", "1337", "888", "999",
        "lucky", "number", "math", "equation", "formula", "calculate",
        "multiply", "divide", "add", "subtract", "times", "plus", "minus",
    ],
}


def detect_narrative(name, symbol, description=""):
    text = f"{name} {symbol} {description}".lower()
    detected = []
    for narrative, keywords in NARRATIVE_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                detected.append(narrative)
                break
    if detected:
        return detected

    # Fallback: AI detect (only if not rate-limited)
    try:
        ai_prompt = (
            f"Classify this memecoin into ONE narrative category. "
            f"Choose from: AI, Gaming, Political, Animal, Meme Culture, DeFi, Meme/Parody, "
            f"Food, Culture/Pop, Music, Science/Space, Religion/Mythology, Math/Numbers, Random/Abstract. "
            f"Return ONLY the category name, nothing else.\n\n"
            f"Name: {name}\nSymbol: {symbol}"
        )
        result = openrouter_chat(ai_prompt, system="You are a crypto narrative classifier.")
        if "429" in result or "Too Many" in result:
            return ["Random/Abstract"]
        result = result.strip().strip('"').strip("'")
        if result and len(result) < 50:
            return [result]
    except Exception:
        pass

    return ["Random/Abstract"]


def get_new_solana_pairs(hours=24, min_liquidity=5000, max_liquidity=2000000, limit=50):
    try:
        search_queries = [
            "solana meme",
            "sol meme",
            "solana coin",
            "sol dog",
            "sol cat",
            "solana ai",
            "sol presale",
            "sol new",
        ]

        all_pairs = []
        seen_addresses = set()
        current_time = time.time()
        max_age_seconds = hours * 3600

        for query in search_queries:
            try:
                url = f"https://api.dexscreener.com/latest/dex/search?q={query}"
                resp = requests.get(url, timeout=15)
                if resp.status_code != 200:
                    continue

                data = resp.json()
                pairs = data.get('pairs') or []

                for pair in pairs:
                    try:
                        chain_id = pair.get('chainId', '')
                        if chain_id != 'solana':
                            continue

                        base_token = pair.get('baseToken', {})
                        token_address = base_token.get('address', '')
                        symbol = base_token.get('symbol', '').upper()

                        if not token_address or token_address.startswith('0x'):
                            continue
                        if token_address in seen_addresses:
                            continue

                        pair_created_at = pair.get('pairCreatedAt', 0)
                        if not pair_created_at:
                            continue

                        age_seconds = current_time - (pair_created_at / 1000)
                        if age_seconds > max_age_seconds:
                            continue
                        if age_seconds < 0:
                            continue

                        age_hours = age_seconds / 3600

                        liquidity = float(pair.get('liquidity', {}).get('usd', 0) or 0)
                        if liquidity < min_liquidity or liquidity > max_liquidity:
                            continue

                        volume_24h = float(pair.get('volume', {}).get('h24', 0) or 0)
                        volume_1h = float(pair.get('volume', {}).get('h1', 0) or 0)
                        price_change_1h = float(pair.get('priceChange', {}).get('h1', 0) or 0)
                        price_change_6h = float(pair.get('priceChange', {}).get('h6', 0) or 0)
                        fdv = float(pair.get('fdv', 0) or 0)

                        volume_1h_ratio = volume_1h / liquidity if liquidity > 0 else 0

                        seen_addresses.add(token_address)

                        all_pairs.append({
                            'address': token_address,
                            'symbol': symbol,
                            'name': base_token.get('name', ''),
                            'price': float(pair.get('priceUsd', 0) or 0),
                            'price_change_1h': price_change_1h,
                            'price_change_6h': price_change_6h,
                            'volume_1h': volume_1h,
                            'volume_24h': volume_24h,
                            'liquidity': liquidity,
                            'market_cap': fdv,
                            'age_hours': age_hours,
                            'volume_liq_ratio': volume_1h_ratio,
                            'dex': pair.get('dexId', ''),
                            'url': pair.get('url', ''),
                            'narrative': detect_narrative(base_token.get('name', ''), symbol),
                        })
                    except Exception:
                        continue
            except Exception:
                continue

        all_pairs.sort(key=lambda x: x['volume_liq_ratio'], reverse=True)
        return all_pairs[:limit]

    except Exception as e:
        logger.error(f"Failed to get new pairs: {e}")
        return []


def analyze_memecoin_potential(pairs):
    if not pairs:
        return []

    results = []

    for pair in pairs:
        score = 0
        signals = []
        risks = []

        age = pair['age_hours']
        vol_liq_ratio = pair['volume_liq_ratio']
        liq = pair['liquidity']
        mc = pair['market_cap']
        change_1h = pair['price_change_1h']
        change_6h = pair['price_change_6h']

        if age < 2:
            score += 30
            signals.append("Very new (< 2h) - early opportunity")
        elif age < 6:
            score += 20
            signals.append("New (< 6h) - still early")
        elif age < 12:
            score += 10
            signals.append("Relatively new (< 12h)")

        if vol_liq_ratio > 2:
            score += 25
            signals.append(f"Extreme volume/liquidity ratio ({vol_liq_ratio:.1f}x)")
        elif vol_liq_ratio > 1:
            score += 15
            signals.append(f"High volume/liquidity ratio ({vol_liq_ratio:.1f}x)")
        elif vol_liq_ratio > 0.5:
            score += 10
            signals.append(f"Good volume/liquidity ratio ({vol_liq_ratio:.1f}x)")

        if liq > 50000:
            score += 10
            signals.append(f"Decent liquidity (${liq/1000:.0f}K)")
        elif liq < 10000:
            score -= 10
            risks.append(f"Low liquidity (${liq/1000:.0f}K) - high slippage risk")

        if 0 < change_1h < 100:
            score += 10
            signals.append(f"Healthy 1h growth (+{change_1h:.0f}%)")
        elif change_1h > 100:
            score -= 5
            signals.append(f"Already pumped +{change_1h:.0f}% in 1h")
            risks.append("May be past initial pump")
        elif change_1h < -20:
            score -= 15
            risks.append(f"Dumping -{change_1h:.0f}% in 1h")

        if mc > 0 and mc < 500000:
            score += 10
            signals.append(f"Low market cap (${mc/1000:.0f}K) - room to grow")
        elif mc > 5000000:
            score -= 5
            risks.append(f"Already high MC (${mc/1000000:.1f}M)")

        narrative = pair.get('narrative', ['Unknown'])
        if 'AI' in narrative:
            score += 10
            signals.append("AI narrative - hot trend")
        if 'Political' in narrative:
            score += 5
            signals.append("Political narrative - event-driven potential")
        if 'Meme Culture' in narrative or 'Animal' in narrative:
            score += 5
            signals.append("Classic memecoin narrative")

        if score >= 50:
            rating = "HIGH"
        elif score >= 30:
            rating = "MEDIUM"
        elif score >= 15:
            rating = "LOW"
        else:
            rating = "SKIP"

        results.append({
            'address': pair['address'],
            'symbol': pair['symbol'],
            'name': pair['name'],
            'price': pair['price'],
            'price_change_1h': pair['price_change_1h'],
            'price_change_6h': pair['price_change_6h'],
            'volume_1h': pair['volume_1h'],
            'volume_24h': pair['volume_24h'],
            'liquidity': pair['liquidity'],
            'market_cap': pair['market_cap'],
            'age_hours': pair['age_hours'],
            'volume_liq_ratio': pair['volume_liq_ratio'],
            'narrative': narrative,
            'score': score,
            'rating': rating,
            'signals': signals,
            'risks': risks,
            'dex_screener_url': f"https://dexscreener.com/solana/{pair['address']}",
            'gmgn_url': f"https://gmgn.ai/sol/token/{pair['address']}",
            'raydium_url': f"https://raydium.io/swap/?inputCurrency=sol&outputCurrency={pair['address']}",
        })

        from duckscreeener.db.database import store_signal
        store_signal(
            symbol=pair['symbol'],
            entry_price=pair['price'],
            source_type='memecoin',
            signal_type=f"NEW ({pair['age_hours']:.1f}h)",
            token_address=pair['address'],
            market_cap=pair['market_cap'],
            volume=pair['volume_1h'],
            score=score,
            narrative=', '.join(narrative),
            analysis='; '.join(signals[:3]),
        )

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def scan_new_memecoins(hours=24, min_liquidity=5000, max_liquidity=2000000, limit=10):
    logger.info(f"Scanning for new memecoins (last {hours}h, liq ${min_liquidity}-${max_liquidity})")

    pairs = get_new_solana_pairs(
        hours=hours,
        min_liquidity=min_liquidity,
        max_liquidity=max_liquidity,
        limit=limit * 3
    )

    if not pairs:
        logger.warning("No new pairs found")
        return []

    results = analyze_memecoin_potential(pairs)

    top_results = [r for r in results if r['rating'] in ['HIGH', 'MEDIUM']][:limit]

    logger.info(f"Found {len(top_results)} promising new memecoins out of {len(pairs)} pairs")
    return top_results


def get_ai_memecoin_analysis(pairs):
    if not pairs:
        return None

    data_summary = "New Solana Memecoins Analysis:\n\n"
    for i, p in enumerate(pairs[:10], 1):
        data_summary += (
            f"{i}. {p['name']} ({p['symbol']})\n"
            f"   Age: {p['age_hours']:.1f}h | Score: {p['score']} | Rating: {p['rating']}\n"
            f"   Price: ${p['price']:.8f} | 1h: {p['price_change_1h']:.1f}% | 6h: {p['price_change_6h']:.1f}%\n"
            f"   Volume 1h: ${p['volume_1h']/1000:.1f}K | Liquidity: ${p['liquidity']/1000:.1f}K\n"
            f"   MC: ${p['market_cap']/1000:.1f}K | Vol/Liq Ratio: {p['volume_liq_ratio']:.1f}x\n"
            f"   Narrative: {', '.join(p['narrative'])}\n"
            f"   Signals: {'; '.join(p['signals'][:3])}\n"
            f"   Risks: {'; '.join(p['risks'][:2]) if p['risks'] else 'None detected'}\n\n"
        )

    return data_summary
