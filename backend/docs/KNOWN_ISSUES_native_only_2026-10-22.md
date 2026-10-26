# Known issues found building a phone-only app (Cart Buddy), 2026-10-22

Found while building `Cart Buddy` (native-only, project `b21b7697-4ee0-4900-bdbe-0b0721ba7511`, folder `output/h5dgk5pm`),
checking its phone preview, and putting it on an Android emulator. Each entry: what was seen, why, how to fix, and where
it stands. "Fixed" means fixed in the working tree with tests, and not yet committed.

## Fixed (in the working tree)

1. **A phone-only app was asked for web layouts.** The App Flow review said "PAGE-004: no composed tree, so the page cannot
   be projected" for the sign-in pair and sent App Flow back for a repair (a model call, nothing to repair).
   Fix: `verification.check_page_layout` and `functional_completeness.page_findings` skip a page with no web tree when
   `app_target.web_pages_enabled(doc)` is false. Tests: `test_a_phone_only_app_needs_no_web_layout.py`.
2. **The writer's guide said `useMe() // { user, account }`.** It returns `{ data: { user, account }, loading, error }`.
   The Account screen read `account` off `useMe() as any`, drew nothing on every phone, and compiled (`as any`).
   Fix: README line corrected; `native_engineer._native_findings` now refuses `as any`. Tests:
   `test_an_account_screen_cannot_hide_its_bugs.py`.
3. **The planner's "Sign Out" workflow does not sign anyone out** (one `end` step). The Account screen ran it, stayed signed
   in, and the sign-in screen bounced the person back to the list. Fix: README says sign out is `useSession().signOut()`;
   a screen using `workflows.signOut` is refused with the way out. The planner still makes the workflow (open, item 8).
4. **Compiler errors reached the writer as "(2,79): no exported member 'toast'"** with no code line and no cause. Fix:
   `native_engineer.explain_error` shows the line with a mark under the spot and says where a missing name lives
   (`toast` is in `@/sdk`, not `@/ui`). Tests: `test_the_writer_is_shown_the_line_and_what_to_do.py`.
5. **The phone preview reinstalled the packages on every redraw** (about 3 minutes) when the phone project had none.
   Fix: `phone_preview._ensure_packages` installs once into `.forge/phone-preview/packages` and links it.
6. **Smith could not open a page on Windows** (`open_page`: WinError 1314, a symlink needs a privilege). Fix:
   `page_review._link_node_modules` makes a junction on Windows. Two older tests of that code
   (`test_review_wiring::test_the_review_can_be_narrowed_to_named_routes`,
   `test_page_review_opens_a_page_as_its_role::test_the_shot_config_carries_who_opens_each_page`) still fail on Windows
   because they point at a folder that does not exist; they pass on Linux.

## Fixed later the same day (working tree, tests added; numbers refer to the Open list below)

- **7. Packages before Expo.** `native_build.ensure_packages` installs the phone project's packages once, and the runner
  (`mobile_builds._run_build_and_poll`) calls it before `ensure_eas_project`. `eas_client._reason` now keeps both output streams
  and drops the CLI's noise, so a failed `eas init` says "Failed to resolve plugin ... node modules installed?" instead of only
  "project:init command failed". Tests: `test_the_phone_build_installs_its_packages_first.py`.
- **8. The duplicate sign-in pages: the real cause was found.** The model's `/sign-in` and `/sign-up` pair (PAGE-006/007) had
  higher numbers than the platform's pair, so they were added LATER: by the App Flow repair loop that the checker bug of item 1
  set off ("PAGE-004: no composed tree"). The model "repaired" it by writing its own sign-in pages and marked one as the entry
  page. Not the prompt, and not luck. Fix 1 removes the trigger. Not built: a deterministic retire of auth pages at other
  routes (it would also have to re-point `navigation.initialRoute`); the planner's fake "Sign Out" workflow remains, with the
  screen-level rule from fix 3 as the guard.
- **9. A phone-only app writes no web pages.** `_compose_page_layouts` makes no trees; `project_frontend` writes no content
  schemas for it and its sweep removes the old ones; `page_funnel` plans no web routes; `_entry_route` sends "/" to `/login`.
  Tests: `test_a_phone_only_app_gets_no_web_page_trees.py`, `test_a_phone_only_app_writes_no_web_pages.py`. Still to do: a
  small "this app lives on your phone" page at the address, and the Publish dialog wording. End-to-end proof on a fresh build.
- **10. Tests no longer write to the real usage ledger** (`tests/conftest.py` sets `FORGE_USAGE_LOG`). Checked: a run of the
  usage tests grew `data/build-usage.jsonl` by 0 bytes. The fake rows already in the ledger (`blueprint`, `t`, `a`) are still
  there; removing them needs the owner's say.
- **11. `langgraph-checkpoint-sqlite`** is in `requirements.txt`.
- **12. `assemble` retries once on `kill EPERM`** (`assembly.verify_build`); a compile error is never retried.
- **14. Preview sample names:** a person-like field of the account entity reads as a person ("Alex Rivera", not "DisplayName 1").

## Open

7. **The phone build never installs the phone project's packages, so Expo cannot link the project.**
   Seen: build `616d5562` failed at `eas init`: "Failed to resolve plugin for module expo-router ... Do you have node
   modules installed?" The `install` node installs the WEB app's packages (`app/`); `native_engineer` installs a separate
   shared type-check toolchain; nothing installs `native/node_modules`. Pantry Pal only worked because its packages had
   been installed by hand.
   Fix: before `ensure_eas_project` in `mobile_builds._run_build_and_poll`, install `native/` once (`npm install`), or use
   the same kept-folder approach as `phone_preview._ensure_packages`. Add a test with a fake installer.
   Also: `error_message` keeps only the tail of the CLI output, so the cause (a line above "project:init command failed")
   was cut off. Keep the line that names the cause, and store the full output where the logs link points.
8. **The planner invents a "Sign Out" workflow and a second sign-in pair.** The plan held `PAGE-004/005` (the platform's own
   `/login` and `/signup`) and also `PAGE-006/007` (`/sign-in`, `/sign-up`, written by the model). The writer then used
   `pages.signIn2` (`/sign-in`, no screen) as the sign-out target. Pantry Pal's brief had the same words and no extras, so
   it is partly luck. Fix: tell the planner the platform already has sign in, sign up and sign out and that it must not add
   pages or workflows for them; drop any copies after planning. Needs a fresh phone-only build to prove (about $2-3).
9. **A phone-only app still gets a website.** `page_layouts` is a free service node ("no model call"); only `page_code`
   (model-written web pages) was emptied for `native_only`. The `frontend` projection then builds the layout trees into real
   web pages. Seen at https://h5dgk5pm.vercel.app: a full Shopping List table page for an app that has no website.
   Fix (the "slim backend", approved, not built): skip `page_layouts` for `native_only`; make the `frontend` projection write
   no web pages but keep sign-in, the data routes and the workflows; make every check that reads web pages accept none; the
   Publish dialog should call the address the app's backend, not a website.
10. **The tests write fake rows into the real usage ledger** (`data/build-usage.jsonl`, projects `blueprint`, `t`, `a`, round
    numbers such as 20,000 tokens). Real cost reports and the cost guard count them. Fix: the test setup should point
    `FORGE_USAGE_LOG` at a temporary file.
11. **`langgraph-checkpoint-sqlite` is not in `requirements.txt`** but `pipeline_graph.py` imports
    `langgraph.checkpoint.sqlite.aio`; 10 tests fail without it.
12. **`assemble` failed once with `kill EPERM`** (Windows) in the platform run, and passed with exit 0 when run by hand.
    Fix: retry the build step once on that error.
13. **A screen can ask for a workflow that does not exist.** "Clear bought" was asked for; the screen now shows the action as
    quiet text with no control. Better: leave the action out, and say so in Smith's reply.
14. **Preview sample data names read oddly** for some fields (`DisplayName 1`). Make person-like fields look like people.
15. **Sign-in form keeps its red hints after the field is filled** until the next submit (generated login screen).
16. **The stored project name was doubled** ("Pantry PalPantry Pal") — a data bug in the project record.
17. **Windows-only test failures** (about 166 in the full suite, the same on plain `smithv5`): bash suites, `node_modules/.bin/tsx`
    and `esbuild` launchers, Windows paths given to node, `os.killpg`, symlinks, tests that read project folders that exist
    only on one machine.
