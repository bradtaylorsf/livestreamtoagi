# Minecraft Command Eval Report

- Provider: `lmstudio`
- Model: `qwen-local`
- Base URL: `http://localhost:1234/v1`
- Key present: `true`
- Request count: `4`
- Collected: `4/4`
- Scenarios scored: `4`

## Outcome Breakdown

| Outcome | Count |
| --- | ---: |
| `malformed` | 1 |
| `unknown_command` | 1 |
| `disallowed_tool` | 0 |
| `wrong_args` | 0 |
| `invalid_arg` | 0 |
| `unsafe_context` | 0 |
| `semantic_reject` | 0 |
| `accepted_chat` | 1 |
| `accepted_command` | 1 |
| `total` | 4 |

## Malformed Examples

- `malformed-output`: outcome=`malformed`, matched=`n/a`, reasons=`parse_error=no-leading-command`, content=`I should observe first.`

## Rejected Examples

- `unknown-command`: outcome=`unknown_command`, matched=`n/a`, reasons=`unknown command: !teleport; constraint failed: require_command !observe`, content=`!teleport home`

## Accepted Chat-Only Examples

- `accepted-chat`: outcome=`accepted_chat`, matched=`n/a`, reasons=`none`, content=`chat: I cannot run !stop, but I can keep watch.`

## Valid Command Examples

- `valid-command`: outcome=`accepted_command`, matched=`!observe`, reasons=`none`, content=`!observe`

## Token And Cost Summary

- Prompt tokens: `50`
- Completion tokens: `22`
- Total tokens: `72`
- Estimated cost: `0.010`
