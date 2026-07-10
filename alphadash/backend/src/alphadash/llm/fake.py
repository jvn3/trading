"""Deterministic fake LLM (S2.3).

Two uses:
- ``FakeLLM(scripted=[...])`` — tests queue exact responses (including malformed ones to
  exercise the retry path).
- ``FakeLLM()`` — rule-based mode: parses the ``CANDIDATES_JSON:`` block out of the agent prompt
  and emits a valid suggestion array; answers chat prompts with a canned, cited, educational
  response. This is what dev/e2e run on when no provider key is configured — the whole product
  works offline, just with boring ideas.

Every call is recorded in ``.calls`` for prompt assertions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from alphadash.llm.base import LLMResponse

CANDIDATES_MARKER = "CANDIDATES_JSON:"
STRATEGY_MARKER = "STRATEGY_TEXT:"


@dataclass
class RecordedCall:
    system: str
    messages: list[dict[str, str]]


@dataclass
class FakeLLM:
    scripted: list[str] = field(default_factory=list)
    calls: list[RecordedCall] = field(default_factory=list)
    model_name: str = "fake-llm-1"

    @property
    def model(self) -> str:
        return self.model_name

    def complete(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> LLMResponse:
        self.calls.append(RecordedCall(system=system, messages=list(messages)))
        if self.scripted:
            return LLMResponse(
                text=self.scripted.pop(0), model=self.model_name, input_tokens=10, output_tokens=10
            )
        return LLMResponse(
            text=self._rule_based(messages),
            model=self.model_name,
            input_tokens=10,
            output_tokens=10,
        )

    def stream(
        self, *, system: str, messages: list[dict[str, str]], max_tokens: int = 4096
    ) -> Iterator[str]:
        text = self.complete(system=system, messages=messages, max_tokens=max_tokens).text
        # word-chunked so streaming consumers actually exercise incremental rendering
        for word in re.split(r"(\s+)", text):
            if word:
                yield word

    # --- rule-based behaviors -------------------------------------------------

    def _rule_based(self, messages: list[dict[str, str]]) -> str:
        prompt = messages[-1]["content"] if messages else ""
        if CANDIDATES_MARKER in prompt:
            return self._suggestions_from_prompt(prompt)
        if STRATEGY_MARKER in prompt:
            return self._strategy_from_prompt(prompt)
        return self._chat_answer(prompt)

    def _strategy_from_prompt(self, prompt: str) -> str:
        """Keyword-parse the user's strategy text into the frozen S4.2 rule schema.

        Deterministic and deliberately simple — good enough for dev/e2e to exercise the whole
        author → validate → backtest → activate flow offline.
        """
        text = prompt.split(STRATEGY_MARKER, 1)[1].strip().splitlines()[0]

        # skip common English words the symbol regex would otherwise grab
        stop_words = {"BUY", "SELL", "WHEN", "THE", "DAY", "OVER", "AND", "OR", "AT", "ITS", "IF"}
        symbol = "AAPL"
        for m in re.finditer(r"\b([A-Z]{2,6}USD|[A-Z]{2,5})\b", text):
            if m.group(1) not in stop_words:
                symbol = m.group(1)
                break
        asset_class = "crypto" if symbol.endswith("USD") else "equity"

        window_match = re.search(r"(\d+)[\s-]*day", text, re.IGNORECASE)
        window = int(window_match.group(1)) if window_match else 20

        lowered = text.lower()
        if re.search(r"risen|momentum|gained|up\s+\d+%", lowered):
            pct = re.search(r"(\d+(?:\.\d+)?)\s*%", lowered)
            entry = {
                "kind": "return_exceeds",
                "window": window,
                "threshold_pct": pct.group(1) if pct else "5",
            }
        elif re.search(r"dropped|fallen|dip|down\s+\d+%", lowered):
            pct = re.search(r"(\d+(?:\.\d+)?)\s*%", lowered)
            entry = {
                "kind": "return_below",
                "window": window,
                "threshold_pct": pct.group(1) if pct else "5",
            }
        elif "below" in lowered:
            entry = {"kind": "price_below_sma", "window": window}
        else:
            entry = {"kind": "price_above_sma", "window": window}

        profit = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(profit|gain|target)", lowered)
        stop = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(loss|stop)", lowered)
        size = re.search(r"(\d+(?:\.\d+)?)\s*%\s*of", lowered)

        params = {
            "symbol": symbol,
            "asset_class": asset_class,
            "entry": entry,
            "exit_condition": None,
            "take_profit_pct": profit.group(1) if profit else ("15" if not stop else None),
            "stop_loss_pct": stop.group(1) if stop else "8",
            "size_pct": size.group(1) if size else "5",
        }
        return json.dumps(
            {"name": f"{symbol} {entry['kind'].replace('_', ' ')} rule", "params": params}
        )

    def _suggestions_from_prompt(self, prompt: str) -> str:
        block = prompt.split(CANDIDATES_MARKER, 1)[1].strip()
        # candidates JSON is the first line after the marker
        candidates = json.loads(block.splitlines()[0])
        evidence_ids = [1] if '<evidence id="1"' in prompt else []
        out = []
        for c in candidates[:3]:
            feature_bits = ", ".join(f"{k} {v}" for k, v in sorted(c["features"].items())[:2])
            out.append(
                {
                    "candidate_ref": c["ref"],
                    "headline": f"Consider a small {c['side']} of {c['symbol']}",
                    "rationale": (
                        f"The {c['kind']} rule flagged {c['symbol']} ({feature_bits}). "
                        "This is a small, reversible step sized by your risk limits. "
                        "It is a simulated suggestion for learning, not advice."
                    ),
                    "confidence": 0.55,
                    "confidence_basis": "deterministic rule signal; limited corroborating evidence",
                    "evidence_ids": evidence_ids,
                    "worst_case": (
                        "If the price moves 10% against this position, the loss stays "
                        "within your per-trade cap."
                    ),
                    "falsifier": f"The {c['kind']} signal reversing on the next daily close.",
                    "reversibility": "High — liquid market, can be unwound any trading day.",
                }
            )
        return json.dumps(out)

    def _chat_answer(self, prompt: str) -> str:
        cited = " [1]" if '<evidence id="1"' in prompt else ""
        return (
            "Here's the educational view rather than a directive: whether to buy depends on "
            "your risk limits, position sizing, and time horizon — not on a single headline"
            + cited
            + ". A bounded option would be a small, capped paper position so you can learn "
            "how it behaves. This is simulated trading and not investment advice."
        )
