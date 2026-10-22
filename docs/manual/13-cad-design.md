# 3D CAD design, CNC, 3D printing

Chapter 13 of the ResearchTools manual. Back to [table of contents](../../README.md).

**This chapter is a placeholder.** It is empty on purpose and will be written during the week of
2026-10-26, together with the Vibe Design book project (see [chapter 00](00-purpose.md)).

## What it will cover

A 3D model treated as code, for example written with a Python CAD library such as Build123d, and so
generated, reviewed and tested like any other program, possibly by the nightly Aider pipeline of
[chapter 14](14-aider-pipeline.md). The parts then go to CNC machining or to a 3D printer. The
content is not decided yet, so nothing below is a feature of this repository today.

## What exists today

No skill, agent or command in this repository handles 3D CAD, CNC or 3D printing, and no CAD library
is declared in the requirements files of [chapter 02](02-profiles.md). The code loop and the choice
of executor in [chapter 11](11-local-coding.md) and the [dashboard](10-rt-observe-dashboard.md) apply
to any project, including one that holds CAD sources, but they know nothing about models or
assemblies.

---
[← 12 PCB design, mixed signals](12-pcb-design.md) | [Table of contents](../../README.md) | [14 Aider nightly pipeline →](14-aider-pipeline.md)
