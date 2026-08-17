# sun commands



Start with these

- `log`: same as git log but with agent sessions/turn number attached to each commit
- `show <commit>`: show operations for a specific commit
- `undo <—op|—commit>`: undo either one operation or commit
- `viz` : to visualize branch, commit, operation. with replay since the beginning



Later add these

- `env <commit> <—with-chats>` : export a state of the repo as an RL environment, optionally with chats
- `sft <suggestions|github>`: export SFT data from accept/reject and issues/PRs. 



# visualizations



Generate HTML visualizations. 

- Visualizes branches, commits, operations
- Replay from the beginning of history



Later add these

- Know who reviewed exactly what at what level of granularity.
- Show stats for percentage of operations for each agent, each person



# Example & Unit tests

## Create example 

1. On Belinda’s computer, ingest the sundial repo (sundial-org/sundial) with my personal claude code sessions in ~/.claude and Github PRs/issues
2. Synthetically (programmatically?) populate the entire operations log.



## Unit test

- log: latest log
- show: a random commit
- undo: undo latest operation, undo latest commit

## 



