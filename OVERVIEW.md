# PaySwitch Credit Scoring AI — Service Overview

**Audience:** Product, compliance, executive, and engineering readers who want to understand what this AI service does and how it was built — without reading code.

---

## 1. What this service does

When someone applies for credit with PaySwitch, this AI service looks at their credit history from XDS (Ghana's national credit bureau), scores them against a set of risk and fraud signals, and returns a structured decision: **approve, conditionally approve, refer to a human reviewer, decline, or fraud hold.** Every decision comes with a recommended loan amount, the top reasons behind the outcome, and a permanent audit record that regulators or internal compliance can pull up years later.

In short: we replace the manual "look at the credit report and make a judgement call" step with a consistent, explainable, and auditable automated process — while keeping humans in the loop for edge cases.

---

## 2. The parts of the service

> #TODO: insert flowchart image — system architecture (replace the ASCII diagram below)

```
        Application (30 signals from XDS + applicant details)
                             │
                             ▼
                  ┌──────────────────────┐          ┌──────────────────┐
                  │     ORCHESTRATOR     │◄─────────│ Customer Service │
                  │  (traffic control)   │          │   Assistant      │
                  └──────────┬───────────┘          │  (LLM-powered)   │
                             │                      └──────────────────┘
           ┌─────────────────┼──────────────────┬─────────────────┐
           ▼                 ▼                  ▼                 ▼
      ┌─────────┐      ┌──────────┐       ┌──────────┐      ┌──────────┐
      │ Credit  │      │  Fraud   │       │   Loan   │      │  Income  │
      │  Risk   │      │Detection │       │  Amount  │      │  Verify  │
      └─────────┘      └──────────┘       └──────────┘      └──────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │   DECISION ENGINE    │
                  │  (business rules)    │
                  └──────────┬───────────┘
                             │
                             ▼
             Decision + reasons + permanent audit record
```

The service is built out of seven cooperating parts. Each does one thing well.

- **Orchestrator** — the traffic controller. It receives the application, hands pieces of it to the right specialists, waits for their answers, and assembles the final decision.
- **Credit Risk Specialist** — answers the core question: *how likely is this applicant to default?* This is the primary signal in every decision.
- **Fraud Detection Specialist** — answers: *does this application look unusual or suspicious?* If it returns a strong fraud signal, it can override every other outcome and route the application to a fraud hold.
- **Loan Amount Specialist** — answers: *if we approve, how much should we lend?* It only runs when the application looks approvable, to avoid wasted work on clear declines.
- **Income Verification Specialist** — answers: *can the applicant realistically afford the loan?* Like the loan amount specialist, it only runs for approvable applications.
- **Decision Engine** — turns the specialists' numeric outputs into a human-readable decision plus any conditions (for example, *"cap the loan at 5,000 GHS"* or *"limit the first draw to 50% of the approved amount"*). This is where business rules live.
- **Customer Service Assistant** — a separate AI helper that can answer plain-English questions about any past decision — *"why was application X declined?"* — by looking up the audit record and explaining it back in natural language.

---

## 3. How a credit decision gets made

> #TODO: insert flowchart image — two-phase inference flow (replace the ASCII diagram below)

```
                     Application arrives
                             │
                             ▼
                Fill gaps (impute missing signals)
                             │
                             ▼
         ┌──────────────── PHASE 1 (always) ─────────────────┐
         │                                                    │
         │  Credit Risk  ◄─── in parallel ───►  Fraud Detect  │
         │                                                    │
         └────────────────────────┬───────────────────────────┘
                                  │
                                  ▼
                    Decision point: approvable?
                                  │
                  ┌───────────────┴───────────────┐
                  │ No                            │ Yes
                  │ (decline / refer /            │
                  │  fraud hold)                  │
                  │                               ▼
                  │              ┌── PHASE 2 (conditional) ───┐
                  │              │                             │
                  │              │  Loan Amount  ◄─ parallel ─►│
                  │              │  Income Verification        │
                  │              │                             │
                  │              └──────────────┬──────────────┘
                  │                             │
                  └───────────────┬─────────────┘
                                  │
                                  ▼
                         DECISION ENGINE
                                  │
                                  ▼
                  Final decision + permanent audit record
```

Every decision goes through the same five-step process. The whole thing typically takes a few seconds.

1. **The application arrives** with around 30 signals drawn from the credit bureau report — payment history, active debt, credit age, recent enquiries, any adverse records — plus basic details like applicant age and product type.

2. **The orchestrator fills in any gaps.** Some signals only exist for certain product types. For example, mobile loan history is only present on mobile-loan reports. The orchestrator auto-completes missing signals with sensible defaults so every specialist sees a complete picture.

3. **Risk and fraud specialists run in parallel.** This is the fast path: both answer within seconds. At this point the orchestrator has enough information to decide whether the application is obviously being declined (low score, clear adverse records) or is worth looking at more carefully.

4. **If the application is approvable, two more specialists run in parallel** — the loan amount and income verification specialists. This second phase is skipped entirely for declines and fraud holds, which keeps the system efficient.

5. **The decision engine combines everything** with a set of business rules: it maps the risk score into a risk tier, applies any soft-stop rules (certain risk patterns automatically route to a human reviewer instead of being auto-decided), resolves conflicts between signals by always favouring the more conservative outcome, and produces the final decision plus any conditions. The full record is written to a permanent, tamper-proof audit blob and published to the Backend for downstream processing.

---

## 4. How the models are trained

> #TODO: insert flowchart image — training flow (replace the ASCII diagram below)

```
              Historical data (with known outcomes)
                             │
                             ▼
          Validate, clean, split (train / validation / test)
                             │
                             ▼
         ┌──────────── Train in parallel ──────────────┐
         │                                              │
         │   Credit     Fraud      Loan       Income   │
         │   Risk     Detection   Amount      Verify   │
         │                                              │
         └──────────────────────┬───────────────────────┘
                                │
                                ▼
                  Champion vs Challenger gate
                                │
                  ┌─────────────┴─────────────┐
                  │ Better than champion?     │
                  │                           │
              Yes │                           │ No
                  ▼                           ▼
           Promoted to                   Rejected
           production                    (logged but
                                         not deployed)
```

Training happens whenever fresh data arrives — either on a scheduled cadence or when the drift monitor (see Section 5) detects that live traffic no longer matches what the models were trained on.

**The data.** We train on historical credit bureau records where we already know how the loan performed — whether it was repaid, defaulted, written off, or settled. The orchestrator validates the dataset, fills in any missing signals, and splits it for training, validation, and a held-out test set so each model can be evaluated fairly.

**The training run.** All four specialists train in parallel, each using a different machine learning technique suited to its job. Hyperparameters are tuned automatically against the validation set. Every training run writes experiment tracking metadata so any past model can be reproduced.

**Quality gates.** A newly trained model is only promoted to production if it beats the current champion on its key metric — accuracy for risk, precision-recall balance for income, goodness-of-fit for loan amount. Models that don't beat the champion are logged for traceability but stay benched — production always runs the best model we've ever trained.

---

## 5. How the service has been developed properly

This is the trust layer. These are the things a reviewer or auditor should ask about.

- **Immutable audit trail.** Every single decision — approvals, declines, fraud holds, errors — is written to a tamper-proof record that cannot be overwritten. Records are retained for at least 8 years per regulatory requirement. Compliance can always reconstruct exactly why any past decision was made.

- **Explainability built in.** Every decision comes with the top factors that drove it and a set of standardised reason codes (R01 through R10). A declined applicant is never told just *"declined"* — they can be told *why*, down to specific features like *"utilisation too high"* or *"multiple recent enquiries"*.

- **Human-in-the-loop safety.** Specific risk patterns — severe debt distress markers, contradictory signals, borderline cases — automatically route to a *"REFER"* outcome for manual review rather than being auto-decided. Fraud signals override everything else: a strong fraud flag forces a fraud hold regardless of how the credit score looks.

- **Fairness checks.** Before any new model is promoted, we verify it doesn't produce materially different approval rates across demographic slices (applicant age groups, product type). Bias gates block promotion if thresholds are breached — we'd rather keep an older model than ship one that's measurably less fair.

- **Drift monitoring.** Every week the system checks whether live applicants look statistically similar to the applicants we trained on. If they start drifting — a new product launches, macroeconomic conditions shift, the applicant mix changes — an alert fires and retraining is triggered so models don't silently decay.

- **Champion-challenger promotion.** New models compete against the current champion, head-to-head on the same evaluation data. Only winners get promoted. Old models are never overwritten silently; there is always an explicit, logged decision to replace the production model with a better one.

---

## 6. What's not in scope

In the spirit of honesty — a few things this service deliberately does *not* do, so reviewers know what's owned elsewhere.

- **Identity verification.** Confirming the applicant is who they say they are is handled upstream by the Data Engineering team and is assumed complete by the time we see an application.
- **Real-time synchronous scoring via HTTP.** Today all scoring flows through an asynchronous message bus. A synchronous HTTP scoring path is planned but deferred.
- **Consolidated secret management.** Connection strings currently live as application settings on each service. A migration to a centralised secret vault is on the roadmap.
- **Consumer-facing adverse action language.** The service emits standardised reason codes; translating those into regulator-compliant applicant letters is the Backend's responsibility.

Keeping this section visible makes the rest of the document credible — we're not claiming the AI does everything, only the parts it actually owns.
