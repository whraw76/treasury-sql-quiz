"use strict";

const $ = (id) => document.getElementById(id);
const topics = ["First observations", "Filter the yields", "Average by maturity", "Join the tables", "Find an inversion"];
let csrf = "", quiz, starter, selected = 0, user = null, quizId = null;
let drafts = ["", "", "", "", ""];
let needsHintRefresh = new Set();
let draftOwner = null, loadRequest = 0;

function openQuiz(document, id = null) {
  quiz = structuredClone(document); quizId = id; selected = 0;
  drafts = [...(quiz.answers || ["", "", "", "", ""])];
  needsHintRefresh.clear(); loadRequest += 1;
  $("quiz-title").value = quiz.title; $("saved-quizzes").value = id || "";
  renderQuestion();
}

function notice(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
  $("status").hidden = !message;
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method, credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let result;
  try { result = await response.json(); }
  catch { throw new Error("The server did not return a usable response. Please try again."); }
  if (!response.ok) {
    if (response.status === 401) { user = null; renderAccount(); }
    throw new Error(result.error || "The request failed.");
  }
  return result;
}

async function busy(button, action) {
  if (button.disabled) return;
  button.disabled = true;
  const label = button.textContent;
  button.textContent = "Working…";
  try { await action(); } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; button.textContent = label; }
}

function table(container, result) {
  container.replaceChildren();
  container.className = "table-wrap";
  const element = document.createElement("table");
  const head = element.createTHead().insertRow();
  result.columns.forEach((column) => {
    const cell = document.createElement("th"); cell.textContent = column; head.append(cell);
  });
  const body = element.createTBody();
  result.rows.forEach((row) => {
    const tr = body.insertRow();
    row.forEach((value) => { tr.insertCell().textContent = value === null ? "NULL" : String(value); });
  });
  container.append(element);
  if (!result.rows.length) {
    const message = document.createElement("p"); message.textContent = "No rows returned."; container.append(message);
  }
}

function renderAccount() {
  $("account-button").textContent = user ? "Sign out" : "Sign in";
  $("account-button").title = user ? user.email : "Sign in to your account";
  $("run-note").textContent = user ? "Signed in · Run a SELECT query against PostgreSQL" : "Sign in to run your query.";
  $("saved-quizzes").disabled = !user;
}

function renderQuestion() {
  const q = quiz.questions[selected];
  $("questions").replaceChildren();
  quiz.questions.forEach((question, index) => {
    const button = document.createElement("button");
    button.className = "question-link" + (index === selected ? " active" : "");
    button.setAttribute("aria-current", index === selected ? "step" : "false");
    button.setAttribute("aria-label", `Question ${index + 1}: ${topics[index]}`);
    [String(index + 1).padStart(2, "0"), topics[index], "4 pts"].forEach((text, part) => {
      const span = document.createElement("span"); span.className = ["number", "topic", "small-points"][part];
      span.textContent = text; button.append(span);
    });
    button.addEventListener("click", () => {
      drafts[selected] = $("sql-editor").value; selected = index; renderQuestion();
    });
    $("questions").append(button);
  });
  $("question-number").textContent = `QUESTION ${String(selected + 1).padStart(2, "0")} / 05`;
  $("question-title").textContent = topics[selected];
  $("question-prompt").textContent = q.prompt;
  $("sql-editor").value = drafts[selected];
  $("reference-sql").textContent = q.reference_sql;
  $("hint-panel").open = false;
  $("question-edit-panel").hidden = true;
  $("query-result").className = "empty-result";
  $("query-result").textContent = "Your result table will appear here.";
  $("result-count").textContent = "";
  if (needsHintRefresh.has(selected)) {
    $("expected-result").className = "empty-result";
    $("expected-result").textContent = "Save this quiz to run the updated reference query and refresh its expected result.";
  } else { table($("expected-result"), q.expected); }
}

async function savedQuizzes() {
  $("saved-quizzes").replaceChildren(new Option("My saved quizzes", ""));
  if (!user) return;
  const owner = user.id;
  const result = await api("/api/quizzes");
  if (user?.id !== owner) return;
  result.quizzes.forEach((q) => $("saved-quizzes").add(new Option(q.title, q.id)));
  if (quizId) $("saved-quizzes").value = quizId;
}

function openAuth() { $("auth-status").textContent = ""; $("auth-dialog").showModal(); }

$("account-button").addEventListener("click", async () => {
  if (!user) return openAuth();
  await busy($("account-button"), async () => {
    await api("/api/auth/logout", "POST", {}); user = null; draftOwner = null;
    openQuiz(starter);
    await savedQuizzes(); notice("Signed out. Run and Save now require sign-in.");
  });
  renderAccount();
});
$("close-auth").addEventListener("click", () => $("auth-dialog").close());
$("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await busy($("sign-in"), async () => {
    try {
      const result = await api("/api/auth/login", "POST", {email: $("email").value, password: $("password").value});
      if (draftOwner && draftOwner !== result.user.id) openQuiz(starter);
      user = result.user; draftOwner = user.id;
      $("password").value = ""; $("auth-dialog").close(); renderAccount();
      notice(`Signed in as ${user.email}.`); await savedQuizzes();
    } catch (error) { $("auth-status").textContent = error.message; }
  });
});
$("sign-up").addEventListener("click", async () => {
  if (!$("auth-form").reportValidity()) return;
  await busy($("sign-up"), async () => {
    try {
      const result = await api("/api/auth/signup", "POST", {email: $("email").value, password: $("password").value});
      $("auth-status").textContent = result.message; $("password").value = "";
    } catch (error) { $("auth-status").textContent = error.message; }
  });
});
$("sql-editor").addEventListener("input", () => { drafts[selected] = $("sql-editor").value; });
$("run-query").addEventListener("click", async () => {
  if (!user) return openAuth();
  await busy($("run-query"), async () => {
    const questionIndex = selected, currentQuiz = quiz;
    drafts[selected] = $("sql-editor").value;
    const result = await api("/api/query", "POST", {sql: drafts[selected]});
    if (selected !== questionIndex || quiz !== currentQuiz) return;
    table($("query-result"), result);
    $("result-count").textContent = `${result.rows.length} rows${result.truncated ? " · limited to 200" : ""}`;
    notice("");
  });
});
$("copy-hint").addEventListener("click", () => {
  $("sql-editor").value = quiz.questions[selected].reference_sql;
  drafts[selected] = $("sql-editor").value; $("sql-editor").focus();
});
$("save-quiz").addEventListener("click", async () => {
  if (!user) return openAuth();
  if (!$("question-edit-panel").hidden) return notice("Apply or cancel the open question edits before saving.", true);
  await busy($("save-quiz"), async () => {
    drafts[selected] = $("sql-editor").value;
    const currentQuiz = quiz, owner = user.id;
    const snapshot = {...structuredClone(quiz), title: $("quiz-title").value, answers: [...drafts]};
    const result = await api("/api/quizzes", "POST", {id: quizId, quiz: snapshot});
    if (quiz !== currentQuiz || user?.id !== owner) return;
    quizId = result.id;
    // Do not overwrite text typed or question edits made while Save was running.
    quiz.questions.forEach((question, index) => {
      if (question.reference_sql === snapshot.questions[index].reference_sql) {
        question.expected = result.quiz.questions[index].expected;
        needsHintRefresh.delete(index);
      }
    });
    if (!needsHintRefresh.has(selected)) table($("expected-result"), quiz.questions[selected].expected);
    await savedQuizzes();
    if (quiz !== currentQuiz || user?.id !== owner) return;
    const changed = JSON.stringify(drafts) !== JSON.stringify(snapshot.answers)
      || $("quiz-title").value !== snapshot.title
      || quiz.questions.some((q, i) => q.prompt !== snapshot.questions[i].prompt
        || q.reference_sql !== snapshot.questions[i].reference_sql);
    notice(changed ? "Saved the answers from when you clicked Save. You have newer edits; save again to keep them."
      : "Quiz and all five SQL answer drafts saved. Reopen them under My saved quizzes.");
  });
});
$("saved-quizzes").addEventListener("change", async () => {
  if (!$("saved-quizzes").value) return;
  try {
    const owner = user?.id, requestNumber = ++loadRequest;
    const result = await api(`/api/quizzes/${encodeURIComponent($("saved-quizzes").value)}`);
    if (user?.id !== owner || requestNumber !== loadRequest) return;
    openQuiz(result.quiz, result.id);
    notice("Opened your saved quiz and SQL answers.");
  } catch (error) { notice(error.message, true); }
});
$("new-quiz").addEventListener("click", () => {
  openQuiz(starter); notice("Starter quiz loaded with blank answers. Saving will create a new copy.");
});
$("edit-question").addEventListener("click", () => {
  const q = quiz.questions[selected];
  $("edit-prompt").value = q.prompt; $("edit-reference").value = q.reference_sql;
  $("question-edit-panel").hidden = false; $("edit-prompt").focus();
});
$("cancel-edit").addEventListener("click", () => { $("question-edit-panel").hidden = true; });
$("apply-question").addEventListener("click", () => {
  drafts[selected] = $("sql-editor").value;
  quiz.questions[selected].prompt = $("edit-prompt").value;
  quiz.questions[selected].reference_sql = $("edit-reference").value;
  needsHintRefresh.add(selected); renderQuestion(); notice("Edits applied locally. Save the quiz to update its database copy and expected results.");
});

(async () => {
  // Supabase confirmation redirects can include tokens in the URL fragment.
  // This app uses password sign-in; remove that fragment rather than storing it.
  if (location.hash.includes("access_token=")) history.replaceState(null, "", location.pathname + location.search);
  try {
    const data = await api("/api/bootstrap"); csrf = data.csrf_token;
    quiz = data.quiz; starter = structuredClone(quiz); $("quiz-title").value = quiz.title;
    $("setup-notice").hidden = data.configured;
    renderQuestion();
    try { user = (await api("/api/me")).user; } catch { user = null; }
    draftOwner = user?.id || null; renderAccount(); await savedQuizzes();
  } catch (error) { notice(error.message, true); }
})();
