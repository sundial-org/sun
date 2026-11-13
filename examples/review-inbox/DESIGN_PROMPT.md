# Sun review design prompt

Use this brief when generating or revising the review UI. It guides design; it is
separate from the prompt that asks an agent to review code.

---

Use Impeccable in Operate mode. Design a quiet, white review workspace that helps
someone decide what deserves their attention and what to do next.

The user's existing agent generates the review from a Sun snapshot, the default
Sun PR review skill, and the user's selected skills and instructions. Design for
plugin delivery. Use an in-chat interface when the host supports it, with a browser
fallback. Do not imply those integrations exist in a standalone prototype.

## Show the decision

- Show at most five ranked PRs initially, even when the queue contains hundreds.
  Keep the rest searchable and reachable. Rank using concrete risk, blocked work,
  missing evidence, and the user's priorities. Make the ranking rationale inspectable.
- Each queue row needs a rank and PR title. Add metadata only when it changes the
  choice. Functional filter counts are fine; promotional totals are not.
- For the selected PR, lead with its title and one specific review question.
  Show required checks and their state nearby. Offer the relevant diff and, when
  useful, a dependency view. A graph must explain a relationship that matters.
- Reveal the explanation, before/after behavior, and supporting evidence on demand.
  Connect claims to files, lines, revisions, or check records. Do not bury an urgent
  failure or consequential action inside collapsed content.
- Let users select personal skills and add instructions alongside Sun's default
  review skill. Make their effect on priorities and required checks inspectable.

## Remove noise

- White surfaces, neutral borders, restrained typography, generous alignment.
  Match the existing Sun review UI. Color communicates state, not decoration.
- No hero, dashboard introduction, decorative cards, eyebrow labels, or repeated
  section titles. Use the review question itself instead of a “Review question” label.
- No “100 sample PRs,” “6 min,” invented estimates, slogans, or filler explanations.
  Document fixtures outside the product view; do not present them as live results.
- Say each fact once. Keep helpful action labels, persistent form labels, keyboard
  access, visible focus, and accessible names. Shortness must not obscure consequences.

## Keep evidence honest

Distinguish passing, failing, running, outdated, not run, and unknown checks.
Tie results to their recorded revision and scope. Selecting a skill never counts
as running its check. Separate observed results from agent judgments. Never label
local navigation as GitHub approval or claim an unimplemented action succeeded.

Before delivering, inspect the rendered flow at narrow and wide widths. Verify
ranking, search, check details, diff navigation, and personalization. Include empty,
loading, and failed-data states. Remove any remaining text that does not help the
user choose, understand, or act. Report which integrations are mocked.
