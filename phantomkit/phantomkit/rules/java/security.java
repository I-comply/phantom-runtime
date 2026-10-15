class A {
    void a(Statement st, Connection c, String u) throws Exception {
        // ruleid: phantom.java.command-injection
        Runtime.getRuntime().exec("ping " + u);
        // ok: phantom.java.command-injection
        Runtime.getRuntime().exec("ls");
        // ruleid: phantom.java.sql-string-building
        st.executeQuery("SELECT * FROM t WHERE n='" + u + "'");
        // ok: phantom.java.sql-string-building
        PreparedStatement ps = c.prepareStatement("SELECT * FROM t WHERE n=?");
        // ruleid: phantom.java.weak-hash
        MessageDigest md = MessageDigest.getInstance("MD5");
        // ok: phantom.java.weak-hash
        MessageDigest md2 = MessageDigest.getInstance("SHA-256");
        // ruleid: phantom.java.weak-cipher
        Cipher ci = Cipher.getInstance("DES");
        // ruleid: phantom.java.weak-cipher
        Cipher ci2 = Cipher.getInstance("AES/ECB/PKCS5Padding");
        // ok: phantom.java.weak-cipher
        Cipher ci3 = Cipher.getInstance("AES/GCM/NoPadding");
        // ruleid: phantom.java.unsafe-deserialization
        Object o = new ObjectInputStream(in).readObject();
        // ruleid: phantom.java.xxe-factory
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        // ruleid: phantom.java.trust-all-certs
        HttpsURLConnection.setDefaultHostnameVerifier((h, s) -> true);
        // ruleid: phantom.java.spring-csrf-disabled
        http.csrf().disable();
    }

    String generateResetToken() {
        // ruleid: phantom.java.insecure-random
        return Long.toString(new Random().nextLong());
    }

    int rollDice() {
        // ok: phantom.java.insecure-random
        return new Random().nextInt(6);
    }
}
