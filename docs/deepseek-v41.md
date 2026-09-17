# DeepSeek V4.1 Flash

Maintained DeepSeek profiles use `deepseek-flash`, the official V4.1 Flash
identifier released September 10, 2026. The endpoint remains
`https://api.deepseek.com`; credentials remain in `DEEPSEEK_API_KEY`.

Source: https://www.deepseek.com/en/news/deepseek-v4-1-flash/

Modeled costs use peak USD rates per million tokens: $0.30 uncached input,
$0.006 cached input and $1.20 output. Off-peak rates are half those amounts;
the static estimate deliberately does not apply time-based discounts.
Historical model pricing and stored run configurations remain unchanged.

For a bounded local demonstration with regularly active citizens:

```powershell
python run.py --config runs/deepseek-v41-demo.yaml --ticks 100 --serve --host 127.0.0.1 --port 8000 --preflight-live --approve-live-inference
```

Open the printed local URL and press Run. The profile retains the smoke
world's $2 budget. The server stops advancing at tick 100; a provider failure
or exhausted budget may pause it earlier. All model routes use DeepSeek,
with live readiness and no scripted fallback. This is a small demonstration,
not acceptance evidence for the unfinished research-city roadmap.
