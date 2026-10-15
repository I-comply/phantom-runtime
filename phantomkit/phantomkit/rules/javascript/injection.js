const cp = require("child_process");

function a(x) {
  // ruleid: phantom.js.eval-nonliteral
  eval(x);
  // ruleid: phantom.js.eval-nonliteral
  const f = new Function("a", x);
  // ok: phantom.js.eval-nonliteral
  eval("1+1");
  // ok: phantom.js.eval-nonliteral
  setTimeout(() => { run(); }, 100);
  // ok: phantom.js.eval-nonliteral
  setTimeout(function () { run(); }, 100);
  // ruleid: phantom.js.eval-nonliteral
  setTimeout(x, 100);
}

function b(cmd) {
  // ruleid: phantom.js.child-process-exec
  cp.exec("ls " + cmd, cb);
  // ok: phantom.js.child-process-exec
  cp.execFile("ls", [cmd], cb);
  // ok: phantom.js.child-process-exec
  cp.exec("ls -l", cb);
}

app.get("/ping", (req, res) => {
  const host = req.query.host;
  // ruleid: phantom.js.taint-command-injection, phantom.js.child-process-exec
  cp.exec("ping " + host, cb);
  const n = parseInt(req.query.n);
  // ruleid: phantom.js.child-process-exec
  // ok: phantom.js.taint-command-injection
  cp.exec(`sleep ${n}`, cb);
});

app.get("/user", (req, res) => {
  const id = req.params.id;
  const q = "SELECT * FROM users WHERE id = " + id;
  // ruleid: phantom.js.taint-sql-injection
  db.query(q);
  // ruleid: phantom.js.sql-string-building, phantom.js.taint-sql-injection
  db.query(`SELECT * FROM users WHERE id = ${id}`, (e, r) => {});
  // ok: phantom.js.sql-string-building
  db.query("SELECT * FROM users WHERE id = ?", [id]);
});

app.get("/file", (req, res) => {
  const f = req.query.f;
  // ruleid: phantom.js.taint-path-traversal
  fs.readFile("/data/" + f, cb);
  // ok: phantom.js.taint-path-traversal
  fs.readFile(path.basename(f), cb);
});

app.get("/proxy", async (req, res) => {
  const u = req.query.url;
  // ruleid: phantom.js.taint-ssrf
  const r = await fetch(u);
  // ok: phantom.js.taint-ssrf
  const r2 = await fetch("https://api.example.com/x");
});

app.get("/go", (req, res) => {
  const dest = req.query.next;
  // ruleid: phantom.js.taint-open-redirect
  res.redirect(dest);
  // ok: phantom.js.taint-open-redirect
  res.redirect("/home");
});

// ruleid: phantom.js.nosql-where-injection
db.find({ $where: "this.a == " + v });
