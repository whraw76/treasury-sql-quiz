# Treasury SQL Lab

A 20-point SQL quiz using a small sample of U.S. Treasury yields. Sign in, choose a question, write SQL, and compare the returned rows with the hint. The site uses Flask, Supabase Auth, and hosted PostgreSQL.

**Quiz site URL: pending deployment.** This local version is not submission-ready until the hosted checks below are complete.

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
4. To make your own version, change the quiz title and optionally use **Edit this question** to change a prompt and its reference SQL. Click **Save quiz**. Saving runs the reference queries again and stores the whole quiz in PostgreSQL.
5. Reload the page and select the saved quiz under **My saved quizzes** to reopen it.

Signed-out visitors can read questions and hints but cannot run SQL or save. SQL answer drafts stay in the current page only; **Save quiz saves the question set and hints, not answer submissions**. The starter quiz remains available to everyone. Saved copies are private to their owner.

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

**Render:** create a Blueprint from this repository using [render.yaml](render.yaml). The configuration installs the Python dependencies and serves Flask with Gunicorn. Set `SUPABASE_URL`, `SUPABASE_KEY`, `QUERY_DATABASE_URL`, and `SAVE_DATABASE_URL` using the values in the local `.env` file, without its surrounding double quotes. The Blueprint generates a separate `SECRET_KEY` and sets `APP_ENV=production`. After deployment, add the actual HTTPS URL to this README and to Supabase Auth's URL configuration. [Render's Flask guide](https://render.com/docs/deploy-flask) explains the hosting setup.

**GitHub Actions:** in repository **Settings → Secrets and variables → Actions**, add a repository secret named `QUERY_DATABASE_URL` containing the reader connection value. Do not put the assignment, outer quotes, or password directly in the workflow YAML. [GitHub's Secrets guide](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets) shows where to add it.

[The workflow](.github/workflows/ci.yml) runs local tests, then connects to the hosted database using that Secret. The hosted job checks the restricted role, the record count, and all five reference results. Missing credentials or a failed connection cause a failure, not a skipped success. Push to `main` or use **Actions → SQL quiz checks → Run workflow**. Both jobs must be green; a pull-request run alone is insufficient because its hosted job is deliberately skipped.

## Tests

```bash
python -m pytest -q -m 'not integration'
ruff check .
python scripts/verify_live.py
```

The first command checks authentication gates, expired sessions, ownership, parameter handling and the permitted SQL syntax using isolated test doubles. The last command requires the real hosted database and verifies its data and permissions.

An optional local PostgreSQL check runs all tests against a disposable database:

```bash
python -m pip install pgserver==0.1.4
python scripts/check_local_postgres.py
```

This creates and deletes its own temporary database. It checks actual query results, save/reopen behavior and denied database operations. It does **not** establish that Supabase Auth or the deployed website works. The local implementation checks passed **60 tests**. On October 20, 2026, the hosted verification also passed: the reader used the Session pooler with SSL, all 60 records were present, and all five reference result tables matched. Deployed browser sign-in and GitHub Actions still need verification.

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

The SQL playground supports the features used in the quiz, including filtering, joins, grouping and basic aggregates. It is not a general PostgreSQL console. Results are capped at 200 rows and statements at five seconds. Sessions require sign-in again when their token expires.

## Before submission

- [ ] Put the actual deployed quiz URL near the top of this README.
- [x] Confirm the hosted database contains the 60 records and all five hints match real query results.
- [ ] In a signed-out browser, confirm Run and Save require sign-in.
- [ ] Sign in, run each question, save an edited quiz, reload, and reopen it.
- [ ] Sign out and confirm Run and Save are blocked again.
- [ ] Check a successful main-branch Actions run with both jobs green and the hosted job's verification output.
- [ ] Confirm no credentials were committed, then submit the GitHub repository URL.
