# Agent Guide

This directory contains instructions and context for AI coding agents working with this repository.

The repository is intended to remain agent-agnostic. Do not assume a specific model, IDE, agent runtime, or toolset.

## Project

This repository contains unofficial module ports and adaptations for:

https://github.com/ProjectSkyfire/SkyFire_548

The target is ProjectSkyFire 5.4.8 unless explicitly stated otherwise.

## Before You Start

Before modifying the repository:

1. Understand the user's current task.
2. Read only the project documentation relevant to that task.
3. Inspect the existing repository structure and related modules before creating new files or conventions.
4. Do not assume APIs, database schemas, hooks, or behavior from other WoW emulator cores are compatible with SkyFire 5.4.8.

## Project Context

Additional instructions are kept in this directory.

As the repository grows, task-specific documentation may include:

- `project.md` — project goals and scope
- `repository.md` — repository structure and conventions
- `modules.md` — module format and requirements
- `porting.md` — rules for porting code from other cores
- `verification.md` — validation and testing requirements

Only read files that exist and are relevant to the current task.

## Public Documentation

User-facing documentation is located in:

- `docs/`

Do not treat public documentation and agent instructions as separate sources of truth.

If behavior, structure, installation steps, or other user-visible information changes, check whether the relevant documentation also needs to be updated.

## CI and Verification

Repository automation and verification tooling is located in:

- `.ci/`
- `.github/`

When verification tooling exists, run the relevant checks before considering a task complete.

Do not bypass or weaken verification just to make a check pass.

## General Rules

- Prefer existing project conventions over introducing new ones.
- Keep changes scoped to the requested task.
- Do not perform unrelated refactors.
- Do not claim something works unless it has actually been verified at the appropriate level.
- Preserve upstream authorship, credits, and licensing information.
- Do not silently remove functionality while porting code.
- When uncertain about SkyFire-specific behavior, inspect the target SkyFire source instead of guessing.