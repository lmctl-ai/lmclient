package ai.lmctl.lmclient.areas;

/**
 * mail area — replaces n8n's EmailSend (SMTP) and EmailReadImap nodes.
 * PINNED CLI contract (wave 5b; owner Astra2; details docs/areas/mail.md):
 *   lmclient mail send --host HOST [--port 25|465|587] [--starttls] --from A --to B[,C...]
 *                      [--subject S] [--body TEXT | --body-file PATH]
 *   lmclient mail read --host HOST [--port 993|143] [--starttls|--ssl] --user U --limit N [--folder INBOX]
 *   lmclient mail ping --host HOST [--port P]
 * Password: LMCLIENT_MAIL_PASSWORD env or password= in --credentials-file; never argv.
 * Envelope per Envelope.java. Client: angus-mail; tests: greenmail.
 */
public final class MailArea {
    private MailArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "mail area not implemented yet"); }
}
