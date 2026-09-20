# AutoHunter

Telegram bot for monitoring Ukrainian car listings and finding vehicles priced below the market.

## Current stage

- Telegram bot scaffold
- Environment-based secrets
- Source adapter architecture for AUTO.RIA and OLX
- Railway-ready Dockerfile
- Minimum vehicle year configurable from environment

## Planned stages

1. Connect AUTO.RIA API.
2. Add PostgreSQL.
3. Store and deduplicate listings.
4. Calculate market prices from comparable vehicles.
5. Send below-market alerts to Telegram.
6. Add OLX source.
7. Add price-change history and deal economics.

## Local environment variables

Copy `.env.example` to `.env` only for local development.

Never commit real API keys or Telegram tokens.

## Railway

Deploy this repository as a service using the included Dockerfile and add the environment variables in Railway:
- TELEGRAM_BOT_TOKEN
- AUTORIA_API_KEY
- DATABASE_URL (after PostgreSQL is added)
