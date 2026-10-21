# Treasury SQL Lab

A 20-point SQL quiz using a small sample of U.S. Treasury yields. Sign in, choose a question, write SQL, and compare the returned rows with the hint. The site uses Flask, Supabase Auth, and hosted PostgreSQL.

**Quiz site:** https://treasury-sql-quiz.onrender.com/

[![SQL quiz checks](https://github.com/whraw76/treasury-sql-quiz/actions/workflows/ci.yml/badge.svg)](https://github.com/whraw76/treasury-sql-quiz/actions/workflows/ci.yml)

The site runs on Render's free plan. After inactivity, the first visit can take about a minute to wake up. **For the evaluator:** sign in as `admin@admin.com` with the password supplied privately in the Canvas submission comment. This is a regular quiz account, not a Supabase administrator. It can run SQL and save its own answers. Passwords are not published in this repository.

## The quiz and data

| Question | SQL practice | Points |
| --- | --- | ---: |
| 1 | Select the first five 10-year observations in 2023 | 4 |
| 2 | Filter 10-year yields at or above 4.5% and sort them | 4 |
| 3 | Calculate the average yield for each maturity | 4 |
| 4 | Join the yields and maturity-name tables | 4 |
| 5 | Find dates when the 10-year yield is below the 2-year yield | 4 |
| **Total** | | **20** |

Every question includes reference SQL and its expected result table. Other queries can be correct if they return the requested result; the app does not grade SQL text or assign automatic scores.

The [Federal Reserve GSW dataset](https://www.federalreserve.gov/data/nominal-yield-curve.htm) contains fitted, continuously compounded zero-coupon Treasury yields. This quiz reuses the downloaded snapshot from my earlier Treasury project: the first 10 complete dates in each of 2023 and 2025, with 2-, 10-, and 30-year maturities. That gives **60 records over 20 dates**. The sample is fixed; the database is live, but these are not current market prices.

`yield_percent = 4.5` means **4.5% per year**. A difference between two yields in this column is in **percentage points**. Source links, dates and file hashes are in [data/source.json](data/source.json).

## Use the website

1. Sign in with a Supabase email/password account configured for this project. For a new account, use **Create an account** and confirm the email when required.
2. Pick a question, enter a single `SELECT` query, and click **Run query**.
3. Open **View hint & expected result** to compare the rows. **Use this SQL** copies the example into the editor.
4. Enter answers for any of the five questions and click **Save quiz**. This saves all five SQL drafts under your account, including blank or unfinished answers. You can give the attempt a different title.
5. Reload the page and choose the saved quiz under **My saved quizzes**. Your answers reappear in their original questions. Edit an answer and save again to update that same copy. **Starter quiz** starts a new copy with blank answers.

Optional: **Edit this question** changes a prompt and its reference SQL. Saving also refreshes the hints from the database. Your answer drafts are stored as text; only **Run query** executes a student answer. There is no automatic grading or auto-save.

Signed-out visitors can read questions and hints but cannot run SQL or save. **Save quiz stores the question set, hints and your five SQL answer drafts in PostgreSQL**. Unsaved edits are lost on refresh. Older saved quizzes open with blank answers because they did not store answer drafts. The starter quiz remains available to everyone. Saved copies are private to their owner.

## Run locally

Use Python 3.12. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m flask --app app run --port 5057
```

Open `http://127.0.0.1:5057`. Without Supabase settings the page shows a preview notice, and query/save/sign-in are unavailable. It never substitutes sample rows for a database query.

## Set up Supabase once

1. Create a dedicated Supabase project, or use a project that does not already contain this app's `treasury_reader` and `treasury_writer` roles.
2. In **Connect**, choose the **Session pooler**, port **5432**. Do not use the Direct connection or the transaction pooler. Find the project's publishable key (a legacy anon key also works); the app does not need a service-role key.
3. Stop the local web server and run:

   ```bash
   python scripts/setup_database.py
   python scripts/verify_live.py
   ```

   Setup prompts privately for the initial `postgres.PROJECT_REF` connection string and the publishable key. Include the actual database password in that connection string, URL-encoding it if necessary. Do not paste it into chat or commit it. Setup creates the tables, loads the 60 records, and generates two restricted database logins. It writes their connection settings to the ignored `.env` file; it does not save the admin password. Existing configured credentials are not overwritten.

   If the project URL, publishable key, `SUPABASE_PROJECT_REF`, and `SUPABASE_POOLER_HOST` have already been entered in the local `.env`, setup only asks for the database password. Enter it as-is; this path handles special characters without manually editing a connection URI.

4. In Supabase Auth, enable email/password sign-in and configure **Site URL** and allowed redirects for the local address and, after deployment, the actual website URL. Ensure there is a confirmed account for testing.
5. Restart the local server, sign in, run a question, and save/reopen a quiz.

Supabase's [default email service](https://supabase.com/docs/guides/auth/auth-smtp) restricts delivery to project-team addresses. For classmate self-registration with email confirmation, configure custom SMTP. For a small demonstration, the project owner can instead create a confirmed test user in Supabase Auth and privately provide its login to the tester. Do not publish account passwords in this README.

`.env.example` lists the settings. All hosted database connections use `sslmode=require`. Session-pooler usernames for the generated logins are `treasury_reader.PROJECT_REF` and `treasury_writer.PROJECT_REF`.

## Deploy and run GitHub Actions

Push this project to a GitHub repository, keeping `.env` and `.venv` excluded.

**Render:** this deployment uses a free Python Web Service connected to this public repository, on branch `main` in Virginia. Use these settings:

| Setting | Value |
| --- | --- |
| Build command | `pip install -r requirements.txt` |
| Start command | `gunicorn --workers 2 --threads 4 --timeout 60 --bind 0.0.0.0:$PORT app:app` |
| Health check | `/health` |
| `PYTHON_VERSION` | `3.12.15` |
| `APP_ENV` | `production` |

In Render's Environment settings, enter `SUPABASE_URL`, `SUPABASE_KEY`, `QUERY_DATABASE_URL`, `SAVE_DATABASE_URL`, and `SECRET_KEY` from the local `.env`, without the outer double quotes. These settings stay outside Git. Set Supabase Auth's **Site URL** to the deployed HTTPS address. The `/health` endpoint checks the web process; database access is checked separately by the workflow and by running quiz questions.

[render.yaml](render.yaml) also provides an equivalent Blueprint configuration, which generates its own session secret. If using a public repository without automatic deploys, use **Manual Deploy → Deploy latest commit** after code changes. [Render's Flask guide](https://render.com/docs/deploy-flask) explains the hosting setup.

**GitHub Actions:** in repository **Settings → Secrets and variables → Actions**, add a repository secret named `QUERY_DATABASE_URL` containing the reader connection value. Do not put the assignment, outer quotes, or password directly in the workflow YAML. [GitHub's Secrets guide](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets) shows where to add it.

[The workflow](.github/workflows/ci.yml) runs local tests, then connects to the hosted database using that Secret. The hosted job checks the restricted role, the record count, and all five reference results. Missing credentials or a failed connection cause a failure, not a skipped success. Push to `main` or use **Actions → SQL quiz checks → Run workflow**. Both jobs must be green; a pull-request run alone is insufficient because its hosted job is deliberately skipped.

## Tests

```bash
python -m pytest -q -m 'not integration'
ruff check .
python scripts/verify_live.py
```

The first command checks authentication gates, expired sessions, ownership, parameter handling and the permitted SQL syntax using isolated test doubles. It also checks all five answer drafts, unfinished/blank answers, updates, invalid payloads and older saved quizzes. The last command requires the real hosted database and verifies its data and permissions.

An optional local PostgreSQL check runs all tests against a disposable database:

```bash
python -m pip install pgserver==0.1.4
python scripts/check_local_postgres.py
```

This creates and deletes its own temporary database. It checks actual query results, save/reopen behavior and denied database operations. It does **not** establish that Supabase Auth or the deployed website works.

The local implementation checks passed **82 tests**, including answer draft persistence, backward compatibility, and five alternative solutions that compare result values and ordering rather than SQL text or column aliases. A local browser check with disposable PostgreSQL and simulated authentication also verified five different drafts (including blank and unfinished SQL), refresh/reopen, updating the same saved copy, and clearing private drafts on sign-out. This browser check does not replace the deployed Supabase login check.

On October 20, 2026, the hosted verification also passed: the reader used the Session pooler with SSL, all 60 records were present, and all five reference result tables matched. The deployed browser checks also passed on October 20, 2026: sign-in, all five question results, saving a renamed quiz, refreshing and reopening it, and query/save restrictions before sign-in and after sign-out. Direct signed-out API requests returned HTTP 401 for both query and save. After deploying answer persistence, the signed-in website also passed the five-draft save/refresh/reopen check, retained blank and unfinished answers, updated the same saved copy, and reopened the earlier quiz with blank answers. The updated first answer ran successfully and returned the five expected rows. A separate evaluator account also passed sign-in, query, save and refresh/reopen checks; its saved list did not show the original account's records. The final audit checked all five alternative solutions against hosted PostgreSQL, with matching row counts of 5, 10, 3, 3 and 10.

[The successful main-branch Actions run](https://github.com/whraw76/treasury-sql-quiz/actions/runs/39532277061) passed both `tests` and `hosted-postgres`. The hosted job used the `QUERY_DATABASE_URL` repository Secret to connect to Supabase and verify all five hints.

## How the code fits together

| File | Purpose |
| --- | --- |
| `app.py` | Web routes; verifies the signed-in user before query/save; validates quiz input |
| `auth.py` | Calls Supabase Auth to sign in and verify the access token |
| `query_policy.py` | Parses one permitted SELECT and restricts tables, SQL features and result size |
| `db.py` | Runs queries with the reader login; saves and retrieves owner-specific quizzes with the writer login |
| `templates/index.html`, `static/` | Quiz page, styling, question navigation and result-table display |
| `data/` | The fixed sample, provenance and five questions with reference results |
| `sql/schema.sql` | Tables and database grants |
| `scripts/` | One-time database setup and verification commands |
| `tests/` | Unit checks and real PostgreSQL integration checks |

A query follows `browser → Flask → verified Supabase user → read-only PostgreSQL connection → result table`. The reader cannot modify the sample or access saved quizzes. Save requests use a separate writer connection and bound SQL parameters, including an owner ID taken from the verified session. Ownership is enforced by the application's queries; this version does not claim row-level-security policies or an audit-log extra credit feature.

The SQL playground supports the features used in the quiz, including filtering, joins, grouping, basic aggregates, CTEs, and `DATE '2025-01-02'` / `CAST(... AS DATE)` date expressions. Other cast types remain outside this small playground. It is not a general PostgreSQL console. Results are capped at 200 rows and statements at five seconds. Sessions require sign-in again when their token expires.

## Verification checklist (October 20, 2026)

- [x] Put the actual deployed quiz URL near the top of this README.
- [x] Confirm the hosted database contains the 60 records and all five hints match real query results.
- [x] Check a differently written solution for every question, including different aliases and explicit dates.
- [x] In a signed-out browser, confirm Run and Save require sign-in.
- [x] Sign in, run each question, save a renamed quiz, reload, and reopen it.
- [x] Verify SQL answer persistence, update and sign-out cleanup in the local browser.
- [x] Repeat the answer-save/refresh/reopen check on the updated deployed site, including blank and unfinished answers, updating the same copy, and reopening an older saved quiz.
- [x] Sign out and confirm Run and Save are blocked again.
- [x] Check a successful main-branch Actions run with both jobs green and the hosted job's verification output.
- [x] Confirm `.env` is ignored and no configured passwords or session secret appear in tracked files or Git history.

Submit this repository URL: https://github.com/whraw76/treasury-sql-quiz. Give the evaluator a confirmed quiz login privately so they can run and save; do not add its password to Git.
