/**
 * The figures the analysis screen shows. **Every one of them is invented.**
 *
 * Nothing in this system records what a representative decided — the stage where a person
 * approves a report, changes it, or sends it back is specified (FR-2.8, FR-C.1) and unbuilt. So
 * there is no real history to draw, and the screen carries a year of made-up history instead.
 *
 * **This breaks the rule the rest of the screens keep.** CLAUDE.md says the interface shows what
 * the service returned and never invents a record, because fabricated content on screen is
 * indistinguishable from real history and a reader has no way to tell. That rule is deliberately
 * set aside here, for one reason: the dashboard is worthless empty, and requiring somebody to run
 * a command before a demonstration means the tab is blank for anyone who does not know to. The
 * cost is that nothing a viewer can see reveals these numbers are not real, so the warning lives
 * in this docstring, in DESIGN.md, and in UI-TODO.md — those are the only ones anybody gets.
 *
 * **The numbers were not typed by hand.** They were produced by running the real thing:
 * `tools/seed_analysis_history.py` invents a year of decisions, and the service's own arithmetic
 * in `src/claim_agent/analysis/` turns them into exactly this shape. So every figure below is
 * internally consistent — the four shares of each week really do come to one, and every written
 * figure really does match the value beside it — in a way hand-written numbers would not be.
 *
 * That also means they can be made again rather than edited:
 *
 *     uv run python -m tools.seed_analysis_history --figures web/src/analysis/demoFigures.json
 *
 * To change what the screen shows, change the invented history or the arithmetic and run that.
 * Correcting a number in the data file by hand would break the agreement between the value a
 * chart draws and the words printed beside it, and nothing would catch it.
 *
 * The service that produced them still exists and still works: `GET /analysis/performance` reads
 * the real store and answers in this same shape. Nothing on this screen calls it any more.
 */
import figures from "./demoFigures.json";
import type { AnalysisView } from "../api/analysisTypes";

/** The invented figures: one year, which is the only stretch of time the screen shows. */
export const DEMO_FIGURES = figures as unknown as AnalysisView;
