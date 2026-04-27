# Project Context

## What we're building
Email automation agent for My-Art (my-art.com.ua) — Ukrainian handcraft 
store (diamond embroidery, cross-stitch, paint-by-numbers, frames).

The store has dropshipping partners across Ukraine and Poland who send 
emails asking about stock availability, reservations, prices, and order 
status. The agent reads these emails, classifies intent, and automates 
responses or notifies the store owner.

## Business context
- Primary language: Ukrainian
- Secondary: Polish (some partners), Russian (legacy, but rare)
- Partners are dropshippers — they resell My-Art products
- Key product types: diamond mosaic sets, cross-stitch kits, frames
- SKU format: TN1283, AR-3221, TNG1619, IND-ZAKAZ, 2933-4030
- Special case: "individual_order" intent for custom photo-based items

## Tech stack
- Python 3.13
- LLM: Groq (Llama 3.3 70B) primary, Gemini 2.0 Flash fallback
- Gmail API (email I/O)
- Supabase PostgreSQL (products, partners, emails, reservations)

## Architecture decisions
- src/llm/ is provider-agnostic abstraction layer
- LLM_PROVIDER env var switches between Groq and Gemini
- Main code uses LLMClient interface, never imports providers directly
- Gmail OAuth via credentials.json + token.json (not committed)
- All secrets in .env

## Why this architecture
- Free tiers run out → easy to switch providers
- Future-proof: adding Claude or GPT = new file in src/llm/

## Project structure
dropship-agent/
├── src/
│   ├── llm/              # LLM abstraction layer
│   │   ├── base.py       # LLMClient abstract class
│   │   ├── groq_client.py
│   │   ├── gemini_client.py
│   │   └── factory.py    # returns client based on LLM_PROVIDER env var
│   ├── classifier.py     # email classification logic
│   ├── db.py             # Supabase client
│   ├── gmail_client.py   # Gmail API wrapper
│   ├── config.py
│   └── main.py           # entry point
└── tests/

## Current progress
- [x] Day 1: Setup, structure, accounts, Groq tested
- [ ] Day 2: LLM abstraction + Groq + Gemini integration  ← we are here
- [ ] Day 3: Supabase schema + db.py
- [ ] Day 4-5: Gmail OAuth + email reading
- [ ] Day 6: First end-to-end pipeline
- [ ] Day 7: Reflection