import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { pct } from "../../lib/format";
import { Card } from "../../ui/Card";
import { Term } from "../../ui/Term";
import { color, font, space } from "../../ui/tokens";

// S3.5 honest performance review: verdict is always benchmark-relative, drawdown and the
// small-sample caveat ride along, and the disclaimers come from the API payload — the framing
// is server-enforced, not frontend decoration.

export function ReviewCard() {
  const review = useQuery({ queryKey: ["review", 90], queryFn: () => api.review(90) });

  if (review.isLoading) {
    return (
      <Card>
        <p style={{ margin: 0, color: color.textMuted }}>
          Preparing your honest review — comparing you against the benchmark…
        </p>
      </Card>
    );
  }
  if (review.isError || !review.data) {
    return (
      <Card>
        <p role="alert" style={{ margin: 0 }}>
          Could not load the performance review.
        </p>
      </Card>
    );
  }

  const { performance, trades, verdict, disclaimers } = review.data;

  return (
    <Card>
      <h3 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeLg }}>
        Honest review (90 days)
      </h3>
      <p style={{ margin: `0 0 ${space.md}px` }}>{verdict}</p>
      <ul style={{ margin: `0 0 ${space.md}px`, paddingLeft: space.lg, lineHeight: 1.8 }}>
        <li>
          Your return: <strong>{pct(performance.return_pct, true)}</strong> ·{" "}
          <Term k="benchmark">{performance.benchmark_symbol}</Term> same period:{" "}
          <strong>{pct(performance.benchmark_return_pct, true)}</strong>
        </li>
        <li>
          Max <Term k="drawdown" />: <strong>{pct(performance.max_drawdown_pct)}</strong>{" "}
          (current: {pct(performance.current_drawdown_pct)})
        </li>
        <li>
          Closed trades: <strong>{trades.closed_trades}</strong>
          {trades.win_rate_pct != null && (
            <>
              {" "}
              · <Term k="win rate" />: <strong>{pct(trades.win_rate_pct)}</strong> ({trades.wins}{" "}
              won, {trades.losses} lost)
            </>
          )}
          {trades.small_sample && (
            <span style={{ color: color.textMuted }}>
              {" "}
              — small sample; treat every conclusion as provisional.
            </span>
          )}
        </li>
      </ul>
      {disclaimers.map((d) => (
        <p
          key={d}
          style={{ margin: `${space.xs}px 0 0`, color: color.textMuted, fontSize: font.sizeSm }}
        >
          {d}
        </p>
      ))}
    </Card>
  );
}
