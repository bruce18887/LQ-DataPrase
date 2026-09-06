# Project Taste Profile — LQ-DataPrase

Root-level preferences that span frontend, backend, and workflow.

- Communicates in Chinese (Simplified); project docs, prompts, and reports are all expected in Chinese. Default to responding in 中文. Confidence: 0.9
- On long multi-batch tasks the user expects continuous, end-to-end autonomous execution — and silence reads as "stuck" to them: they've repeatedly piped up mid-run ("继续卡住了", "这是卡住了吗，一直没动静"). Give a short one-line status/plan before each long operation, and when a stall is reported immediately stop the stuck background task and resume in the foreground — don't stop to re-confirm or explain at length. Confidence: 0.8
