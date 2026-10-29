package ai.lmctl.lmclient.areas;

import jakarta.activation.DataHandler;
import jakarta.mail.Address;
import jakarta.mail.AuthenticationFailedException;
import jakarta.mail.FetchProfile;
import jakarta.mail.Folder;
import jakarta.mail.Message;
import jakarta.mail.Session;
import jakarta.mail.internet.InternetAddress;
import jakarta.mail.internet.MimeMessage;
import jakarta.mail.util.ByteArrayDataSource;
import org.eclipse.angus.mail.imap.IMAPStore;
import org.eclipse.angus.mail.smtp.SMTPTransport;

import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

/** SMTP send, header-only IMAP read, and TCP ping. See docs/areas/mail.md. */
public final class MailArea {
    private MailArea() {}
    private static final Set<String> COMMON = Set.of("host", "port", "url", "timeout", "credentials-file", "user");

    public static int run(String[] args) {
        try {
            Options o = parse(args);
            if (o.command.equals("ping")) {
                try (Socket socket = new Socket()) {
                    socket.connect(new InetSocketAddress(o.host, o.port), o.timeout);
                    socket.setSoTimeout(o.timeout);
                }
                return Envelope.ok("{\"reachable\":true}");
            }
            Properties properties = new Properties();
            String protocol = o.command.equals("send") ? "smtp" : "imap";
            for (String setting : new String[]{"connectiontimeout", "timeout", "writetimeout"})
                properties.setProperty("mail." + protocol + "." + setting, Integer.toString(o.timeout));
            properties.setProperty("mail." + protocol + ".ssl.enable", Boolean.toString(o.ssl));
            properties.setProperty("mail." + protocol + ".ssl.checkserveridentity", "true");
            properties.setProperty("mail." + protocol + ".starttls.enable", Boolean.toString(o.starttls));
            properties.setProperty("mail." + protocol + ".starttls.required", Boolean.toString(o.starttls));
            properties.setProperty("mail.smtp.auth", Boolean.toString(o.user != null));
            properties.setProperty("mail.smtp.quitwait", "false");
            properties.setProperty("mail.imap.peek", "true");
            Session session = Session.getInstance(properties);
            session.setDebug(false);
            return o.command.equals("send") ? send(o, session) : read(o, session);
        } catch (Usage e) {
            return Envelope.fail("USAGE", e.getMessage());
        } catch (AuthenticationFailedException e) {
            return Envelope.fail("AUTH", "mail authentication failed; check user and password configuration");
        } catch (Exception e) {
            // Mail servers can include credentials in diagnostics; never expose exception text.
            return Envelope.fail("MAIL_ERROR", "mail operation failed; check connectivity, TLS, credentials, and folder configuration");
        }
    }

    private static int send(Options o, Session session) throws Exception {
        InternetAddress[] from = addresses(o.values.get("from"));
        if (from.length != 1) throw usage("--from must contain one address");
        InternetAddress[] to = addresses(o.values.get("to"));
        String body = o.values.getOrDefault("body", "");
        if (o.values.containsKey("body-file")) {
            Path file = Path.of(o.values.get("body-file"));
            if (Files.size(file) > 10 * 1024 * 1024) throw usage("--body-file exceeds 10 MiB");
            body = Files.readString(file, StandardCharsets.UTF_8);
        }
        MimeMessage message = new MimeMessage(session);
        message.setFrom(from[0]);
        message.setRecipients(Message.RecipientType.TO, to);
        message.setSubject(o.values.getOrDefault("subject", ""), "UTF-8");
        message.setSentDate(new java.util.Date());
        // A byte source avoids reflective activation handlers for object-to-text conversion.
        message.setDataHandler(new DataHandler(new ByteArrayDataSource(body.getBytes(StandardCharsets.UTF_8), "text/plain; charset=UTF-8")));
        message.saveChanges();
        try (SMTPTransport transport = new SMTPTransport(session, null)) {
            transport.connect(o.host, o.port, o.user, o.user == null ? null : o.password);
            transport.sendMessage(message, to);
        }
        StringBuilder json = new StringBuilder("{\"sent\":true,\"to\":[");
        for (int i = 0; i < to.length; i++) {
            if (i > 0) json.append(',');
            json.append(Envelope.quote(o.redact(to[i].getAddress())));
        }
        return Envelope.ok(json.append("]}").toString());
    }

    private static int read(Options o, Session session) throws Exception {
        StringBuilder json = new StringBuilder("{\"messages\":[");
        try (IMAPStore store = new IMAPStore(session, null)) {
            store.connect(o.host, o.port, o.user, o.password);
            Folder folder = store.getFolder(o.values.getOrDefault("folder", "INBOX"));
            try {
                folder.open(Folder.READ_ONLY);
                int count = folder.getMessageCount();
                if (count > 0) {
                    Message[] messages = folder.getMessages(Math.max(1, count - o.limit + 1), count);
                    FetchProfile profile = new FetchProfile();
                    profile.add(FetchProfile.Item.ENVELOPE);
                    folder.fetch(messages, profile);
                    for (int i = messages.length - 1; i >= 0; i--) {
                        if (i < messages.length - 1) json.append(',');
                        Message message = messages[i];
                        Address[] from = message.getFrom();
                        String sender = from == null || from.length == 0 ? null : from[0].toString();
                        java.util.Date date = message.getSentDate();
                        json.append("{\"from\":").append(Envelope.quote(o.redact(sender)))
                            .append(",\"subject\":").append(Envelope.quote(o.redact(message.getSubject())))
                            .append(",\"date\":").append(Envelope.quote(date == null ? null : date.toInstant().toString())).append('}');
                    }
                }
            } finally {
                if (folder.isOpen()) folder.close(false);
            }
        }
        return Envelope.ok(json.append("]}").toString());
    }

    private static InternetAddress[] addresses(String text) {
        try {
            if (text == null || text.contains("\r") || text.contains("\n")) throw usage("invalid mail address");
            InternetAddress[] addresses = InternetAddress.parse(text, true);
            if (addresses.length == 0) throw usage("at least one mail address is required");
            for (InternetAddress address : addresses) address.validate();
            return addresses;
        } catch (jakarta.mail.internet.AddressException e) { throw usage("invalid mail address"); }
    }

    private static Options parse(String[] args) throws Exception {
        if (args.length == 0 || !Set.of("send", "read", "ping").contains(args[0]))
            throw usage("usage: lmclient mail <send|read|ping> --host HOST [options]");
        Options o = new Options();
        o.command = args[0];
        Set<String> specific = switch (o.command) {
            case "send" -> Set.of("from", "to", "subject", "body", "body-file", "starttls", "ssl");
            case "read" -> Set.of("limit", "folder", "starttls", "ssl");
            default -> Set.of();
        };
        for (int i = 1; i < args.length; i++) {
            if (!args[i].startsWith("--")) throw usage("expected a mail option");
            String key = args[i].substring(2);
            if (!COMMON.contains(key) && !specific.contains(key)) throw usage("unknown mail option (passwords belong in env or --credentials-file)");
            if (o.values.containsKey(key)) throw usage("duplicate mail option");
            if (Set.of("starttls", "ssl").contains(key)) o.values.put(key, "true");
            else {
                if (++i >= args.length || args[i].startsWith("--")) throw usage("missing mail option value");
                o.values.put(key, args[i]);
            }
        }
        o.starttls = o.values.containsKey("starttls");
        o.ssl = o.values.containsKey("ssl");
        if (o.starttls && o.ssl) throw usage("choose --starttls or --ssl, not both");
        String url = o.values.getOrDefault("url", System.getenv("LMCLIENT_MAIL_URL"));
        String host = null; String user = null; int port = -1; String scheme = null;
        if (url != null) {
            try {
                URI uri = new URI(url); scheme = uri.getScheme(); host = uri.getHost(); port = uri.getPort();
                if (!Set.of("smtp", "smtps", "imap", "imaps").contains(scheme == null ? "" : scheme) || host == null ||
                    uri.getQuery() != null || uri.getFragment() != null || (uri.getPath() != null && !Set.of("", "/").contains(uri.getPath())))
                    throw usage("invalid mail URL; use smtp(s)://host:port or imap(s)://host:port");
                user = uri.getUserInfo();
                if (user != null && user.contains(":")) throw usage("URL passwords are not accepted; use LMCLIENT_MAIL_PASSWORD or --credentials-file");
            } catch (java.net.URISyntaxException e) { throw usage("invalid mail URL"); }
            if (o.command.equals("send") && !scheme.startsWith("smtp") || o.command.equals("read") && !scheme.startsWith("imap"))
                throw usage("mail URL scheme does not match the command");
            o.ssl |= scheme.equals("smtps") || scheme.equals("imaps");
        }
        o.host = o.values.getOrDefault("host", host);
        if (o.host == null || o.host.isBlank() || o.host.contains("/") || o.host.contains("@") || o.host.chars().anyMatch(Character::isWhitespace))
            throw usage("a host is required via --host, --url, or LMCLIENT_MAIL_URL");
        o.timeout = positive(o.values.getOrDefault("timeout", "10000"), Integer.MAX_VALUE, "--timeout");
        boolean imapEndpoint = o.command.equals("read") || (scheme != null && scheme.startsWith("imap"));
        int defaultPort = imapEndpoint ? (o.starttls ? 143 : (o.ssl || scheme == null ? 993 : 143))
            : (o.ssl ? 465 : o.starttls ? 587 : 25);
        o.port = positive(o.values.getOrDefault("port", Integer.toString(port == -1 ? defaultPort : port)), 65535, "--port");
        if (o.command.equals("read") && o.port == 993 || o.command.equals("send") && o.port == 465) o.ssl = true;
        if (o.ssl && o.starttls) throw usage("STARTTLS cannot be combined with implicit TLS");
        Properties credentials = new Properties();
        if (o.values.containsKey("credentials-file")) {
            Path file = Path.of(o.values.get("credentials-file"));
            if (Files.size(file) > 1024 * 1024) throw usage("credentials file exceeds 1 MiB");
            try (var reader = Files.newBufferedReader(file, StandardCharsets.UTF_8)) { credentials.load(reader); }
        }
        o.user = o.values.getOrDefault("user", System.getenv().getOrDefault("LMCLIENT_MAIL_USER", user == null ? credentials.getProperty("user") : user));
        o.password = System.getenv().getOrDefault("LMCLIENT_MAIL_PASSWORD", credentials.getProperty("password"));
        if (o.command.equals("send")) {
            if (!o.values.containsKey("from") || !o.values.containsKey("to")) throw usage("mail send requires --from and --to");
            if (o.values.containsKey("body") && o.values.containsKey("body-file")) throw usage("choose --body or --body-file");
            String subject = o.values.getOrDefault("subject", "");
            if (subject.contains("\r") || subject.contains("\n")) throw usage("subject must be one line");
        }
        if (o.command.equals("read")) {
            if (o.user == null || o.user.isBlank()) throw usage("mail read requires --user (or a credentials-file user)");
            if (!o.values.containsKey("limit")) throw usage("mail read requires --limit");
            o.limit = positive(o.values.get("limit"), 1000, "--limit");
        }
        return o;
    }

    private static int positive(String value, int max, String flag) {
        try { int n = Integer.parseInt(value); if (n > 0 && n <= max) return n; } catch (NumberFormatException ignored) { }
        throw usage(flag + " must be a positive integer at most " + max);
    }
    private static Usage usage(String message) { return new Usage(message); }
    private static final class Usage extends IllegalArgumentException { Usage(String message) { super(message); } }
    private static final class Options {
        String command, host, user, password;
        int port, timeout, limit;
        boolean ssl, starttls;
        final Map<String, String> values = new HashMap<>();
        String redact(String text) { return text == null || password == null || password.isEmpty() ? text : text.replace(password, "[REDACTED]"); }
    }
}
