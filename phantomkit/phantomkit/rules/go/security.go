package main

func a(db *sql.DB, name string) {
	// ruleid: phantom.go.command-injection
	exec.Command("sh", "-c", "ping "+name)
	// ok: phantom.go.command-injection
	exec.Command("sh", "-c", "ls -l")
	// ruleid: phantom.go.sql-string-building
	db.Query(fmt.Sprintf("SELECT * FROM t WHERE n='%s'", name))
	// ruleid: phantom.go.sql-string-building
	db.Exec("DELETE FROM t WHERE n=" + name)
	// ok: phantom.go.sql-string-building
	db.Query("SELECT * FROM t WHERE n=$1", name)
}

func b() {
	// ruleid: phantom.go.tls-insecure-skip-verify
	cfg := &tls.Config{InsecureSkipVerify: true}
	// ok: phantom.go.tls-insecure-skip-verify
	cfg2 := &tls.Config{MinVersion: tls.VersionTLS12}
	// ruleid: phantom.go.tls-min-version
	cfg3 := &tls.Config{MinVersion: tls.VersionTLS10}
	// ruleid: phantom.go.weak-hash
	h := md5.New()
	// ok: phantom.go.weak-hash
	h2 := sha256.New()
	// ruleid: phantom.go.unescaped-html-template
	t := template.HTML(userInput)
	// ok: phantom.go.unescaped-html-template
	t2 := template.HTML("<b>ok</b>")
	// ruleid: phantom.go.insecure-file-permissions
	os.Chmod(path, 0777)
	// ok: phantom.go.insecure-file-permissions
	os.Chmod(path, 0600)
	// ruleid: phantom.go.http-no-timeout
	http.ListenAndServe(":8080", nil)
	// ruleid: phantom.go.ssrf-http-get
	http.Get(url)
	// ok: phantom.go.ssrf-http-get
	http.Get("https://example.com")
}

func newSessionToken() string {
	// ruleid: phantom.go.math-rand-for-secret
	return fmt.Sprint(rand.Int())
}

func pickIndex() int {
	// ok: phantom.go.math-rand-for-secret
	return rand.Intn(10)
}
