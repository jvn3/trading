// S3.3 contextual education: the single plain-English glossary. Every first-use jargon term in
// the UI goes through <Term k="..."> (ui/Term.tsx) so the definition is one tap away, defined
// once, and test-enforced (a missing key is a compile error via GlossaryKey).

export const GLOSSARY = {
  drawdown:
    "How far your portfolio has fallen from its highest point, in percent. The number that tells you what losing feels like.",
  benchmark:
    "A simple comparison like SPY (the S&P 500). If a strategy doesn't beat just buying the benchmark, the extra effort wasn't paying you.",
  "position sizing":
    "How much of your money goes into one idea. Sizing, not stock picking, is what keeps one mistake from mattering too much.",
  "limit order":
    "An order that only executes at your chosen price or better. You give up certainty of filling to gain certainty of price.",
  "market order":
    "An order that executes right away at the best available price. You get certainty of filling but the exact price can slip a little.",
  confidence:
    "How strongly the evidence supports a suggestion, from 0 to 1. It is an honest estimate, not a promise — low confidence means 'weak signal', not 'secret sure thing'.",
  allocation:
    "How your money is split across investments and cash, in percent. Diversification lives or dies here.",
  "cash floor":
    "The minimum share of your portfolio kept in cash. Dry powder for opportunities — and a cushion for mistakes.",
  "paper trading":
    "Trading with simulated money. Same decisions, same data, zero financial risk — the flight simulator of investing.",
  "unrealized P/L":
    "Profit or loss on paper for positions you still hold. It only becomes real when you sell.",
  "win rate":
    "The share of your closed trades that made money. A high win rate with tiny wins and huge losses still loses — read it next to drawdown.",
  slippage:
    "The small difference between the price you saw and the price you got. Modeled here so paper results don't flatter you.",
  volatility:
    "How much a price swings around. More volatility means bigger gains AND bigger losses — it cuts both ways.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
