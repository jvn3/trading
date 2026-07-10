import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, type OnboardingRequest } from "../../lib/api";
import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { Chip } from "../../ui/Chip";
import { Term } from "../../ui/Term";
import { color, font, space } from "../../ui/tokens";

// S3.1 guided onboarding: three questions → a named starter risk profile, explained in plain
// language before anything else happens. The account already exists (registration provisions
// balanced defaults); this interview tunes the safety rules to the person.

type Answers = Partial<OnboardingRequest>;

const QUESTIONS: Array<{
  key: keyof OnboardingRequest;
  title: string;
  options: Array<{ value: string; label: string }>;
}> = [
  {
    key: "experience",
    title: "How much investing have you done?",
    options: [
      { value: "new", label: "I'm brand new" },
      { value: "some", label: "I've dabbled a bit" },
      { value: "confident", label: "I'm fairly comfortable" },
    ],
  },
  {
    key: "drop_reaction",
    title: "Your portfolio drops 15% in a month. What's your honest instinct?",
    options: [
      { value: "sell", label: "Sell — I'd want out" },
      { value: "wait", label: "Wait it out" },
      { value: "buy_more", label: "Buy more while it's cheap" },
    ],
  },
  {
    key: "goal",
    title: "What matters most right now?",
    options: [
      { value: "preserve", label: "Not losing what I have" },
      { value: "learn", label: "Learning how this works" },
      { value: "grow", label: "Growing it as much as I can" },
    ],
  },
];

export function OnboardingWizard({ onDone }: { onDone: () => void }) {
  const [answers, setAnswers] = useState<Answers>({});
  const status = useQuery({ queryKey: ["onboarding"], queryFn: api.onboardingStatus });

  const submit = useMutation({
    mutationFn: () => api.completeOnboarding(answers as OnboardingRequest),
  });

  const complete = QUESTIONS.every((q) => answers[q.key]);

  if (submit.isSuccess) {
    const result = submit.data;
    return (
      <main style={{ fontFamily: font.family, maxWidth: 640, margin: "0 auto", padding: space.lg }}>
        <Card>
          <h2 style={{ marginTop: 0 }}>
            Your safety rules: <span style={{ textTransform: "capitalize" }}>{result.profile}</span>
          </h2>
          <p>
            Based on your answers, we set up the <strong>{result.profile}</strong> profile. These
            limits are enforced by code on every trade — the agent can suggest, but nothing gets
            past them. You can change them anytime in Settings.
          </p>
          <ul style={{ lineHeight: 1.9 }}>
            <li>
              No single <Term k="position sizing">position</Term> above{" "}
              <strong>{result.limits.max_position_pct}%</strong> of your portfolio
            </li>
            <li>
              At most <strong>{result.limits.max_trades_per_week}</strong> trades per week
            </li>
            <li>
              A <Term k="cash floor">cash floor</Term> of{" "}
              <strong>{result.limits.cash_floor_pct}%</strong>
            </li>
            <li>
              Buying pauses automatically past a{" "}
              <strong>{result.limits.drawdown_pause_pct}%</strong> <Term k="drawdown" />
            </li>
          </ul>
          <p style={{ color: color.textMuted, fontSize: font.sizeSm }}>
            This is a <Term k="paper trading">paper</Term> account — simulated money, real
            learning. Not investment advice.
          </p>
          <ActionButton label="Take me to my dashboard" intent="primary" onClick={onDone} />
        </Card>
      </main>
    );
  }

  return (
    <main style={{ fontFamily: font.family, maxWidth: 640, margin: "0 auto", padding: space.lg }}>
      <header style={{ display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.lg }}>
        <strong style={{ fontSize: font.sizeLg }}>Welcome to AlphaDash</strong>
        <Chip label="PAPER — simulated money" tone="info" icon="🛈" />
      </header>
      <Card>
        <h2 style={{ marginTop: 0 }}>Three quick questions</h2>
        <p style={{ color: color.textMuted }}>
          Your answers pick the starter safety rules for your simulated account. There are no
          wrong answers — honest ones make the rules fit.
        </p>
        {QUESTIONS.map((q) => (
          <fieldset
            key={q.key}
            style={{
              border: `1px solid ${color.border}`,
              borderRadius: 8,
              marginBottom: space.md,
              padding: space.md,
            }}
          >
            <legend style={{ fontWeight: 600 }}>{q.title}</legend>
            {q.options.map((option) => (
              <label
                key={option.value}
                style={{ display: "flex", alignItems: "center", gap: space.sm, padding: 4 }}
              >
                <input
                  type="radio"
                  name={q.key}
                  value={option.value}
                  checked={answers[q.key] === option.value}
                  onChange={() => setAnswers((a) => ({ ...a, [q.key]: option.value }))}
                />
                {option.label}
              </label>
            ))}
          </fieldset>
        ))}
        {submit.isError && (
          <p role="alert" style={{ color: color.danger }}>
            {submit.error instanceof ApiError ? submit.error.detail : "Something went wrong."}
          </p>
        )}
        <ActionButton
          label="Set up my safety rules"
          intent="primary"
          disabled={!complete || submit.isPending || status.isLoading}
          onClick={() => submit.mutate()}
        />
        {!complete && (
          <p style={{ color: color.textMuted, fontSize: font.sizeSm }}>
            Answer all three questions to continue.
          </p>
        )}
      </Card>
    </main>
  );
}
