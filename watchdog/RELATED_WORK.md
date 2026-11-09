# Related work

A first pass, done on 2026-11-08 in one evening of searching. It is not a
systematic review: a similar piece of work may well exist, above all where
economics meets AI. Kept so the watchdog does not reinvent what others have
measured, and so its own contribution is stated against theirs.

## What supports the design

- **The world carries the load.** ImpossibleBench gives coding agents tasks
  that can only be passed by cheating on the tests. GPT-5 exploited them 76% of
  the time on one variant. The strongest lever was access, not instructions:
  hiding the tests brought cheating near zero (at a cost to legitimate work),
  while a strict prompt helped on some tasks and barely on others. This is an
  environment-level restriction, like the gate.
- **The honest exit works, but not on every model.** In the same study an
  option to flag a task as impossible cut cheating for GPT-5 from 54% to 9% and
  for o3 from 49% to 12%; Claude Opus 4.1 rarely used it and stayed at 46%.
  The same pattern as series 2: the effect depends on the agent.
- **Gate the act, not the declaration.** Baker et al. (OpenAI) added a
  chain-of-thought monitor to the training reward as a penalty. Under strong
  optimization the agents learned to hide their intent and kept hacking. This
  is the watchdog's reason for gating at execution (refusing declarations makes
  silence safer than honesty) and for the mirror's rule that confirming the
  exit is never penalized.
- **Accuracy is not honesty.** MASK finds that larger models are more
  accurate but not more honest. The watchdog separates the same two things:
  `scores_right` (computed the incentives) and `follows_own` (acted on them).

## What already exists

- **Paired tasks for avoidable refusal.** AgentAbstain (July 2026): 263 pairs
  of near-identical tasks, one where the agent should act and one where it
  should not. The headline metric is *paired accuracy*, which counts a pair only
  when both twins pass, so always acting or always refusing scores at most 50%.
  Best model 59.5%; models abstain less reliably than they act.
- **Stopping on time.** Agentic Abstention: few agents stop when a task becomes
  infeasible, and on long episodes over-abstention on solvable tasks grows (one
  model reached 34% by turn 10). Laziness that appears with length.
- **The gate in working form.** AgentSpec intercepts an agent's action before
  it runs and checks it against rules: over 90% of unsafe code actions
  prevented, with false alarms visible as a cost (safe-task success 58.6% →
  54.3% in one setting). That cost is the "gate accuracy" assumption in
  `MODEL.md`, measured.
- **Models respond to prices.** Homo silicus (demand curves from LLMs) and
  STEER (economic rationality tests). Shopping and choice tasks, not harm to
  third parties, and without a placebo.
- **A causal model of incentives.** Everitt et al. define incentives on
  Pearl-style causal influence diagrams, among them the *response incentive*:
  which variables a decision should respond to. Series 3 measures whether the
  decision does respond to the price, so the diagram gives the normative side
  and the probe the empirical one.
- **Stated vs revealed preferences.** Small context changes can flip an LLM's
  revealed choice away from its stated principle. The mirror compares the two
  inside one answer: the model's own scores against its own act.
- **Older roots.** Returning an externality to whoever caused it is a Pigouvian
  tax (`lam`); an independent auditor and separated powers are institutional
  practice; AI control (Greenblatt et al.) studies monitoring protocols against
  a model that may actively subvert them.

## What looks like the watchdog's own (with the caveat above)

1. **A closed loop at deployment, without training.** The real cost of an act
   is returned to the agent inside its world, at the wall, next to an honest
   exit. Weights do not change, the environment does, which avoids the
   obfuscation trap of penalties in training.
2. **A decomposition by layer, per agent.** Which layer holds which failure,
   measured by ablation: the zone by the structure, priceable harm by the
   ledger, and the ledger only for agents that read prices.
3. **Price sensitivity as a causal quantity** (do(price), a placebo,
   equal-charge cells), used to set how wide the zone must be for an agent.
4. **Bypass and avoidable refusal in one ledger** under one scheme: "0
   bypasses" is not read without "work done".
5. **The mirror**: the agent's own claim set against its own act, as an
   intervention.

## Weak spot it exposed

The AI-control line assumes a model that may try to evade oversight. The
watchdog's agent only chooses; it never searches for a way around the gate. Until
there is a condition where the agent knows the gate and has a reason and a
means to find a blind channel, the gate is tested only against a cooperative
agent.

## Sources

- ImpossibleBench: https://www.greaterwrong.com/posts/qJYMbrabcQqCZ7iqm/impossiblebench-measuring-reward-hacking-in-llm-coding-1
- Baker et al., Monitoring Reasoning Models for Misbehavior and the Risks of Promoting Obfuscation: https://arxiv.org/abs/2503.11926
- MASK: https://arxiv.org/abs/2503.03750
- AgentAbstain: https://www.alphaxiv.org/abs/2607.10059
- Agentic Abstention: https://arxiv.org/abs/2606.28733
- AgentSpec: https://arxiv.org/abs/2503.18666
- Homo silicus: https://arxiv.org/abs/2301.07543
- STEER: https://arxiv.org/abs/2402.09552
- Everitt et al., Agent Incentives: A Causal Perspective: https://arxiv.org/abs/2102.01685
- Alignment Revisited (stated vs revealed preferences): https://arxiv.org/abs/2506.00751
- Greenblatt et al., AI Control: https://arxiv.org/abs/2312.06942
- van der Weij et al., AI Sandbagging: https://arxiv.org/abs/2406.07358
- OR-Bench (over-refusal): https://aitopics.org/doc/arxivorg:30507EA3
