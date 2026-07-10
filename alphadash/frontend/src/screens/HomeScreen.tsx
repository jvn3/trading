import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { DigestPanel } from "../features/digest/DigestPanel";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { Card } from "../ui/Card";
import { Term } from "../ui/Term";
import { color, space } from "../ui/tokens";

// S1.10 home: orientation, not noise. S3.2 adds the daily digest panel.
export function HomeScreen() {
  const account = useQuery({ queryKey: ["account"], queryFn: api.account });
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Home</h2>
      <Card>
        <p style={{ margin: 0 }}>
          Welcome. This is a <Term k="paper trading">paper-money</Term> account
          {account.data && <> with {money(account.data.starting_equity)} starting equity</>} — a
          safe place to learn before any real money is ever involved.
        </p>
        {portfolio.data && (
          <p style={{ margin: `${space.md}px 0 0` }}>
            Current value: <strong>{money(portfolio.data.equity)}</strong> ·{" "}
            <Link to="/portfolio" style={{ color: color.primary }}>
              See portfolio &amp; place a trade
            </Link>
          </p>
        )}
      </Card>
      <DigestPanel />
    </div>
  );
}
