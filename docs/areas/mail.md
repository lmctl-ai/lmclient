# Mail (SMTP and IMAP)

## wiring

- Runtime dependency: `org.eclipse.angus:angus-mail:2.0.3`.
- Runtime API dependency: `jakarta.mail:jakarta.mail-api:2.1.3` (also transitively supplied by Angus).
- Activation implementation: `org.eclipse.angus:angus-activation:2.0.2`.
- Test invocation: `python3 scripts/test-mail.py target/lmclient-0.2.0-all.jar` (also accepts a native executable).
- Live fixture: `greenmail/standalone:2.0.1`, SMTP container port 3025, IMAP container port 3143. The Python script starts a uniquely named container with ephemeral loopback host ports and always removes it. No GreenMail Java test dependency is needed when using this fixture.
- Native: direct Angus SMTP/IMAP constructors avoid reflective provider discovery; minimal mail/activation handler reflection metadata is supplied under `META-INF/native-image/ai.lmctl/lmclient-mail/`. Keep service-loader resources when shading (existing ServicesResourceTransformer). JVM verification only locally; native verification belongs to the manually triggered CI build.

## Commands

```
lmclient mail send --host HOST [--port 25|465|587] [--starttls] [--ssl] [--user U] --from A --to B[,C...] [--subject S] [--body TEXT | --body-file PATH]
lmclient mail read --host HOST [--port 993|143] [--starttls|--ssl] --user U --limit N [--folder INBOX]
lmclient mail ping --host HOST [--port P]
```

All commands accept `--timeout MS` (default 10000), `--credentials-file PATH`, and `--url URL` or `LMCLIENT_MAIL_URL`. URL schemes are `smtp`, `smtps`, `imap`, `imaps`; explicit host/port/user override the URL. URL passwords are rejected: use `LMCLIENT_MAIL_PASSWORD` or a UTF-8 Java properties file containing `password=...` and optionally `user=...`. Environment password wins over the file. `LMCLIENT_MAIL_USER` is also supported. Generic JDBC password environment variables are not consulted.

URL schemes use their standard default ports (25/465/143/993). With `--host`, SMTP defaults to port 25 (587 with STARTTLS, 465 with SSL); port 465 implies SSL. IMAP defaults to SSL on 993, or cleartext port 143 with STARTTLS; explicitly selecting a non-993 port without `--ssl` allows a local plain IMAP fixture. STARTTLS is required when requested; TLS certificate and hostname verification stay enabled. SMTP authentication is enabled when a user is supplied. `ping` checks TCP connectivity only, not credentials or TLS.

Send emits `{sent:true,to:[...]}`. Read emits newest-first `{messages:[{from,subject,date},...]}` using read-only folder access and header fetching only, without retrieving message bodies or marking mail read. Dates are ISO UTC strings or null. `--limit` accepts 1–1000; body files are limited to 10 MiB and credential files to 1 MiB. Network operations have connect/read/write timeouts. Send/read also enforce an overall operation deadline, so a peer trickling partial replies cannot extend `--timeout` indefinitely (error code `TIMEOUT`). The timeout tests measure from socket acceptance, allow CI scheduling margin, and retry a timing failure once; errors use sanitized messages and never echo server diagnostics or passwords. Exit codes: 0 success, 2 usage, 3 runtime.

The demo targets local GreenMail ports 3025/3143 and skips cleanly if unavailable. Production delivery, attachments, HTML, folder mutations, OAuth SMTP authentication, and idle subscriptions are outside v1.
