import unittest

from tracker import report, solana, telegram

WALLET = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
MINT = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"

TG_HTML = f"""
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="alphacalls/1042">
 <div class="tgme_widget_message_text js-message_text">New call 🚀 $FROG<br>CA: {MINT}<br>
   chart <a href="https://dexscreener.com/solana/5zpyutJu9ee6jFymDGoK7F6S5Kczqtc9FomP3ueKuyA9">dex</a>
   join <a href="https://t.me/alphacalls">t.me</a></div>
 <div class="tgme_widget_message_footer"><a class="tgme_widget_message_date" href="https://t.me/alphacalls/1042">
   <time datetime="2026-10-24T09:15:00+00:00" class="time">09:15</time></a></div>
</div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message" data-post="alphacalls/1043">
 <div class="tgme_widget_message_text">gm everyone, market looks hot. USDC EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v</div>
 <a class="tgme_widget_message_date" href="#"><time datetime="2026-10-24T10:00:00+00:00">10:00</time></a>
</div></div>
"""


def tx(sol_pre, sol_post, tok_pre, tok_post, err=None):
    bal = lambda amt: [{"accountIndex": 3, "mint": MINT, "owner": WALLET,
                        "uiTokenAmount": {"uiAmount": amt, "amount": str(int(amt * 1e6)), "decimals": 6}}]
    return {
        "blockTime": 1792800000,
        "meta": {"err": err, "preBalances": [sol_pre, 0], "postBalances": [sol_post, 0],
                 "preTokenBalances": bal(tok_pre) if tok_pre is not None else [],
                 "postTokenBalances": bal(tok_post)},
        "transaction": {"message": {"accountKeys": [{"pubkey": WALLET}, {"pubkey": "x"}]}},
    }


class TelegramTests(unittest.TestCase):
    def test_parse_page(self):
        posts = telegram.parse_page(TG_HTML)
        self.assertEqual([p["post_id"] for p in posts], [1042, 1043])
        self.assertEqual(posts[0]["channel"], "alphacalls")
        self.assertEqual(posts[0]["addresses"],
                         [MINT, "5zpyutJu9ee6jFymDGoK7F6S5Kczqtc9FomP3ueKuyA9"])
        self.assertEqual(posts[1]["addresses"], [])  # stablecoin ignored

    def test_ignores_plain_long_words(self):
        self.assertEqual(telegram.extract_addresses("abcdefghijkmnopqrstuvwxyzabcdefghijk"), [])


class WalletTests(unittest.TestCase):
    def test_buy(self):
        legs = solana.swaps_in_tx(tx(5_000_000_000, 3_000_000_000, None, 1000.0), WALLET)
        self.assertEqual(legs, [{"kind": "buy", "mint": MINT, "sol": 2.0, "usd": 0}])

    def test_sell(self):
        legs = solana.swaps_in_tx(tx(1_000_000_000, 4_000_000_000, 1000.0, 0.0), WALLET)
        self.assertEqual(legs[0]["kind"], "sell")
        self.assertEqual(legs[0]["sol"], 3.0)

    def test_transfer_ignored(self):
        self.assertEqual(solana.swaps_in_tx(tx(1_000_000_000, 999_995_000, None, 50.0), WALLET), [])

    def test_failed_tx_ignored(self):
        self.assertEqual(solana.swaps_in_tx(tx(5e9, 3e9, None, 1.0, err={"x": 1}), WALLET), [])


class ReportTests(unittest.TestCase):
    def make(self):
        evs = []
        base = 1_790_000_000
        for i in range(4):
            t = base + i * 86400
            evs.append({"id": f"p{i}", "kind": "post", "person": "A", "source": "@a", "ts": t,
                        "address": f"T{i}", "token": f"T{i}", "link": "",
                        "r": {"entry": 1.0, "h1": 1.5, "h24": 0.9, "peak24": 2.0, "low24": 0.8, "d7": 0.4}})
            evs.append({"id": f"b{i}", "kind": "buy", "person": "A", "source": "w", "ts": t - 3600,
                        "address": f"T{i}", "token": f"T{i}", "link": "", "r": {}})
            evs.append({"id": f"s{i}", "kind": "sell", "person": "A", "source": "w", "ts": t + 1800,
                        "address": f"T{i}", "link": ""})
        evs.append({"id": "q", "kind": "post", "person": "B", "source": "@b", "ts": base, "address": "X",
                    "token": "X", "link": "", "r": {"entry": 2.0, "h1": 2.2, "h24": 3.0}})
        return evs

    def test_build(self):
        out = report.build(self.make(), [{"name": "A"}, {"name": "B"}])
        a = next(p for p in out["persons"] if p["name"] == "A")
        self.assertAlmostEqual(a["posts"]["d7"], -0.6)
        self.assertEqual(a["score_basis"], "7日")
        self.assertEqual(a["pre_buy_rate"], 1.0)
        self.assertEqual(a["sold_after_rate"], 1.0)
        self.assertIn("一瞬だけ型", a["badges"])
        self.assertIn("投稿後に売却多め", a["badges"])
        b = next(p for p in out["persons"] if p["name"] == "B")
        self.assertEqual(b["badges"], ["データ不足"])
        self.assertEqual(out["persons"][-1]["name"], "B")  # unscored people go last


if __name__ == "__main__":
    unittest.main()
