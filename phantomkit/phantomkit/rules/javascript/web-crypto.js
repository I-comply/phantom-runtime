// ruleid: phantom.js.dom-xss-sink
el.innerHTML = userInput;
// ok: phantom.js.dom-xss-sink
el.innerHTML = "<b>hi</b>";
// ok: phantom.js.dom-xss-sink
el.innerHTML = DOMPurify.sanitize(userInput);
// ruleid: phantom.js.dom-xss-sink
document.write(location.hash);

// ruleid: phantom.js.react-dangerously-set-inner-html
const v2 = <div dangerouslySetInnerHTML={{__html: html}} />;

app.get("/x", (req, res) => {
  const n = req.query.name;
  // ruleid: phantom.js.express-xss-send
  res.send("<h1>" + n + "</h1>");
  // ok: phantom.js.express-xss-send
  res.send("<h1>" + escapeHtml(n) + "</h1>");
});

// ruleid: phantom.js.weak-hash
crypto.createHash("md5").update(x);
// ok: phantom.js.weak-hash
crypto.createHash("sha256").update(x);
// ruleid: phantom.js.weak-cipher
crypto.createCipheriv("aes-128-ecb", k, null);
// ok: phantom.js.weak-cipher
crypto.createCipheriv("aes-256-gcm", k, iv);
// ruleid: phantom.js.deprecated-createcipher
crypto.createCipher("aes192", pw);

function makeResetToken() {
  // ruleid: phantom.js.insecure-random-for-secret
  return Math.random().toString(36);
}
function shuffle() {
  // ok: phantom.js.insecure-random-for-secret
  return Math.random();
}

// ruleid: phantom.js.tls-verification-disabled
https.request({ host: h, rejectUnauthorized: false });
// ruleid: phantom.js.tls-verification-disabled
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
// ruleid: phantom.js.jwt-insecure
const t = jwt.sign({ id: 1 }, "hardcoded-secret");
// ok: phantom.js.jwt-insecure
const t2 = jwt.sign({ id: 1 }, process.env.JWT_SECRET);
// ruleid: phantom.js.insecure-cookie
res.cookie("sid", sid, { secure: false });
// ruleid: phantom.js.cors-wildcard
app.use(cors({ origin: "*" }));
// ruleid: phantom.js.buffer-constructor
const b = new Buffer(10);
// ruleid: phantom.js.postmessage-wildcard
win.postMessage(data, "*");
// ruleid: phantom.js.hardcoded-bcrypt-low-rounds
bcrypt.hashSync(pw, 4);
// ok: phantom.js.hardcoded-bcrypt-low-rounds
bcrypt.hashSync(pw, 12);
// ruleid: phantom.js.eval-like-require
const m = require(name);
// ok: phantom.js.eval-like-require
const fs2 = require("fs");
