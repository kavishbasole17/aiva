# AIVA rebuild in progress

This repository is being rebuilt from scratch on this branch (`main`) per a new
product spec: Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui frontend,
Node.js/Express + TypeScript API, PostgreSQL + Prisma, JWT/RBAC auth, and the
Anthropic API for all AI features (resume parsing, JD extraction, scoring,
questionnaire evaluation, multi-agent interviews, evaluation reports).

The previous implementation (Python/FastAPI + React, hand-built local/air-gapped
AI model gateway, "Atigro"-derived design tokens) is fully preserved on the
`legacy-python-stack` branch — nothing has been discarded, only replaced on `main`.

This file is a placeholder marking the start of the rebuild and will be removed
once the new README lands.
